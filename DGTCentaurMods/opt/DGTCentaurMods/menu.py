# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

import configparser
import os
import pathlib
import sys
import threading
import time
import urllib.request
import json
import socket
import subprocess
import signal
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple
from DGTCentaurMods.display.ui_components import AssetManager

from DGTCentaurMods.board import *
from DGTCentaurMods.board.sync_centaur import command
from DGTCentaurMods.epaper import Manager, WelcomeWidget, StatusBarWidget, TextWidget
from DGTCentaurMods.epaper.menu_arrow import MenuArrowWidget
from DGTCentaurMods.epaper.framework.regions import Region
from PIL import Image, ImageDraw, ImageFont
from DGTCentaurMods.board.logging import log

menuitem = 1
curmenu = None
selection = ""
centaur_software = "/home/pi/centaur/centaur"
game_folder = "games"

event_key = threading.Event()
_active_arrow_widget: Optional[MenuArrowWidget] = None
idle = False # ensure defined before keyPressed can be called

# Constants matching old widgets module
STATUS_BAR_HEIGHT = 16
TITLE_GAP = 8
TITLE_HEIGHT = 24
TITLE_TOP = STATUS_BAR_HEIGHT + TITLE_GAP
MENU_TOP = TITLE_TOP + TITLE_HEIGHT
MENU_ROW_HEIGHT = 24
MENU_BODY_TOP_WITH_TITLE = MENU_TOP
MENU_BODY_TOP_NO_TITLE = STATUS_BAR_HEIGHT + TITLE_GAP
DESCRIPTION_GAP = 8

# Global display manager
display_manager: Optional[Manager] = None

# Global status bar widget
status_bar_widget: Optional[StatusBarWidget] = None

current_renderer: Optional["MenuRenderer"] = None


def _get_display_manager() -> Manager:
    """Get or create the global display manager."""
    global display_manager, status_bar_widget
    if display_manager is None:
        display_manager = Manager()
        display_manager.init()
        # Create and add status bar widget
        status_bar_widget = StatusBarWidget(0, 0)
        display_manager.add_widget(status_bar_widget)
    return display_manager


def _paint_region(region: Region, painter: Callable[[Image.Image, ImageDraw.ImageDraw], None]) -> None:
    """Paint a region using the display manager's framebuffer."""
    manager = _get_display_manager()
    canvas = manager._framebuffer.get_canvas()
    draw = ImageDraw.Draw(canvas)
    painter(canvas, draw)
    # Update display - the scheduler will handle dirty regions
    manager.update(full=False)


def _clear_rect(x1: int, y1: int, x2: int, y2: int) -> None:
    """Clear a rectangular area."""
    manager = _get_display_manager()
    canvas = manager._framebuffer.get_canvas()
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([x1, y1, x2, y2], fill=255, outline=255)
    manager.update(full=False)


def _draw_battery_icon_to_canvas(canvas: Image.Image, top_padding: int = 2) -> None:
    """Draw battery icon directly to canvas (for use within canvas context)."""
    indicator = "battery1"
    if board.batterylevel >= 18:
        indicator = "battery4"
    elif board.batterylevel >= 12:
        indicator = "battery3"
    elif board.batterylevel >= 6:
        indicator = "battery2"
    if board.chargerconnected > 0:
        indicator = "batteryc"
        if board.batterylevel == 20:
            indicator = "batterycf"
    path = AssetManager.get_resource_path(f"{indicator}.bmp")
    image = Image.open(path)
    canvas.paste(image, (98, top_padding))


def clear_screen() -> None:
    """Clear the entire screen."""
    log.info(">>> clear_screen() ENTERED")
    manager = _get_display_manager()
    canvas = manager._framebuffer.get_canvas()
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, 128, 296], fill=255, outline=255)
    log.info(">>> clear_screen() canvas cleared, submitting full refresh")
    future = manager.update(full=True)
    future.result(timeout=10.0)
    log.info(">>> clear_screen() EXITING")


def write_text(row: int, text: str, *, inverted: bool = False) -> None:
    """Write text at a specific row."""
    ROW_HEIGHT = 20
    top = row * ROW_HEIGHT
    manager = _get_display_manager()
    canvas = manager._framebuffer.get_canvas()
    draw = ImageDraw.Draw(canvas)
    font_18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
    fill, fg = (0, 255) if inverted else (255, 0)
    draw.rectangle([0, top, 128, top + ROW_HEIGHT], fill=fill, outline=fill)
    draw.text((0, top - 1), text, font=font_18, fill=fg)
    manager.update(full=False)


def loading_screen() -> None:
    """Display loading screen."""
    manager = _get_display_manager()
    canvas = manager._framebuffer.get_canvas()
    draw = ImageDraw.Draw(canvas)
    font_18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
    logo = Image.open(AssetManager.get_resource_path("logo_mods_screen.jpg"))
    canvas.paste(logo, (0, 20))
    draw.text((0, 200), "     Loading", font=font_18, fill=0)
    future = manager.update(full=False)
    future.result(timeout=10.0)


def welcome_screen(status_text: str = "READY") -> None:
    """Display welcome screen."""
    from DGTCentaurMods.board.logging import log
    log.info(f">>> welcome_screen() ENTERED with status_text='{status_text}'")
    manager = _get_display_manager()
    canvas = manager._framebuffer.get_canvas()
    draw = ImageDraw.Draw(canvas)
    font_18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
    status_font = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 14)
    
    # Draw status bar
    status_region = Region(0, 0, 128, STATUS_BAR_HEIGHT)
    draw.rectangle([status_region.x1, status_region.y1, status_region.x2, status_region.y2], fill=255, outline=255)
    draw.text((2, -1), status_text, font=status_font, fill=0)
    # Draw battery icon
    _draw_battery_icon_to_canvas(canvas, top_padding=1)
    
    # Draw welcome content
    welcome_region = Region(0, STATUS_BAR_HEIGHT, 128, 296)
    draw.rectangle([welcome_region.x1, welcome_region.y1, welcome_region.x2, welcome_region.y2], fill=255, outline=255)
    logo = Image.open(AssetManager.get_resource_path("logo_mods_screen.jpg"))
    canvas.paste(logo, (0, STATUS_BAR_HEIGHT + 4))
    draw.text((0, STATUS_BAR_HEIGHT + 180), "   Press [>||]", font=font_18, fill=0)
    
    log.info(">>> welcome_screen() canvas updated, submitting full refresh")
    future = manager.update(full=True)
    future.result(timeout=10.0)
    log.info(">>> welcome_screen() EXITING")


@dataclass
class MenuEntry:
    key: str
    label: str


class MenuRenderer:
    def __init__(self, title: Optional[str], entries: Sequence[MenuEntry], description: Optional[str]) -> None:
        self.title = title or ""
        self.entries: List[MenuEntry] = list(entries)
        self.description = (description or "").strip()
        self.row_height = MENU_ROW_HEIGHT
        self.body_top = MENU_BODY_TOP_WITH_TITLE if title else MENU_BODY_TOP_NO_TITLE
        self.arrow_width = 20
        self.selected_index = 0
        self._description_font = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 16)

    def max_index(self) -> int:
        return max(0, len(self.entries) - 1)

    def draw(self, selected_index: int) -> None:
        log.info(f">>> MenuRenderer.draw() ENTERED with selected_index={selected_index}")
        self.selected_index = max(0, min(selected_index, self.max_index()))
        log.info(f">>> MenuRenderer.draw() normalized selected_index={self.selected_index}")
        
        manager = _get_display_manager()
        
        # SAFER APPROACH: Remove all widgets except status bar, then re-add only what we need
        # This ensures a clean state and avoids leftover widgets
        global status_bar_widget
        widgets_to_keep = []
        if status_bar_widget and status_bar_widget in manager._widgets:
            widgets_to_keep.append(status_bar_widget)
        
        # Clear all widgets except status bar
        manager._widgets.clear()
        manager._widgets.extend(widgets_to_keep)
        log.info(f">>> MenuRenderer.draw() cleared all widgets except {len(widgets_to_keep)} status bar widget(s)")
        
        # Create and add title widget if present
        if self.title:
            log.info(f">>> MenuRenderer.draw() creating title widget: '{self.title}'")
            title_text = f"[ {self.title} ]"
            title_top = MENU_BODY_TOP_WITH_TITLE - TITLE_HEIGHT
            title_widget = TextWidget(0, title_top, 128, TITLE_HEIGHT, title_text, 
                                     background=3, font_size=18)
            manager.add_widget(title_widget)
        
        # Create and add menu entry widgets
        # Position text after vertical line (arrow_width) with 2 pixel gap
        text_x = self.arrow_width + 2
        text_width = 128 - text_x
        log.info(f">>> MenuRenderer.draw() creating {len(self.entries)} entry widgets, body_top={self.body_top}")
        for idx, entry in enumerate(self.entries):
            top = self._row_top(idx)
            log.info(f">>> MenuRenderer.draw() entry {idx}: top={top}, label='{entry.label}'")
            entry_widget = TextWidget(text_x, top, text_width, self.row_height, entry.label,
                                     background=0, font_size=18)
            manager.add_widget(entry_widget)
        
        # Arrow will be drawn by MenuArrowWidget, not here
        
        # Create and add description widgets if present
        if self.description:
            log.info(">>> MenuRenderer.draw() creating description widgets")
            desc_top = self._row_top(len(self.entries)) + DESCRIPTION_GAP
            desc_width = 128 - 10  # Leave 5px margin on each side
            wrapped = self._wrap_text(self.description, max_width=desc_width - 10)
            for idx, line in enumerate(wrapped[:9]):
                y_pos = desc_top + 2 + (idx * 16)
                desc_widget = TextWidget(5, y_pos, 123, 16, line,
                                        background=0, font_size=16)
                manager.add_widget(desc_widget)
        
        log.info(">>> MenuRenderer.draw() widgets created and added to manager, EXITING")

    def change_selection(self, new_index: int) -> None:
        """
        Change the selected menu item.
        
        This method is deprecated - selection is now handled by MenuArrowWidget.
        Kept for backward compatibility but does nothing.
        """
        pass

    def _row_top(self, idx: int) -> int:
        return self.body_top + (idx * self.row_height)

    def _draw_entry(self, idx: int, selected: bool) -> None:
        """
        Draw menu entry to framebuffer without submitting refresh.
        Used during initial menu draw - selection changes use direct canvas access.
        """
        if idx < 0 or idx >= len(self.entries):
            return
        text = f"    {self.entries[idx].label}"
        # Use direct canvas access to avoid widgets.draw_menu_entry() which submits refresh
        top = self._row_top(idx)
        with service.acquire_canvas() as canvas:
            draw = canvas.draw
            region = Region(0, top, 128, top + self.row_height)
            if selected:
                draw.rectangle(region.to_box(), fill=0, outline=0)  # Black background
                draw.text((0, top - 1), text, font=widgets.FONT_18, fill=255)  # White text
            else:
                draw.rectangle(region.to_box(), fill=255, outline=255)  # White background
                draw.text((0, top - 1), text, font=widgets.FONT_18, fill=0)  # Black text
            canvas.mark_dirty(region)

    def _draw_entries(self) -> None:
        for idx, _ in enumerate(self.entries):
            self._draw_entry(idx, selected=(idx == self.selected_index))

    def _draw_arrow(self, idx: int, selected: bool) -> None:
        if idx < 0 or idx >= len(self.entries):
            return
        top = self._row_top(idx)
        region = Region(0, top, self.arrow_width, top + self.row_height)
        with service.acquire_canvas() as canvas:
            draw = canvas.draw
            draw.rectangle(region.to_box(), fill=255, outline=255)
            if selected and self.entries:
                draw.polygon(
                    [
                        (2, top + 2),
                        (2, top + self.row_height - 2),
                        (self.arrow_width - 3, top + (self.row_height // 2)),
                    ],
                    fill=0,
                )
            canvas.mark_dirty(region)
        # DO NOT submit refresh here - batch all selection changes and refresh once

    def _draw_description(self) -> None:
        if not self.description:
            return
        top = self._row_top(len(self.entries)) + DESCRIPTION_GAP
        region = Region(0, top, 128, 296)
        widgets.clear_area(region)
        wrapped = self._wrap_text(self.description, max_width=region.x2 - region.x1 - 10)
        with service.acquire_canvas() as canvas:
            draw = canvas.draw
            for idx, line in enumerate(wrapped[:9]):
                y_pos = top + 2 + (idx * 16)
                draw.text((5, y_pos), line, font=self._description_font, fill=0)
            canvas.mark_dirty(region)
        service.submit_region(region)

    def _wrap_text(self, text: str, max_width: int) -> List[str]:
        """Wrap text to fit within max_width using description font."""
        words = text.split()
        if not words:
            return []
        lines: List[str] = []
        current = words[0]
        temp_image = Image.new("1", (1, 1), 255)
        temp_draw = ImageDraw.Draw(temp_image)
        for word in words[1:]:
            candidate = f"{current} {word}"
            if temp_draw.textlength(candidate, font=self._description_font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

def keyPressed(id):
    # This function receives key presses
    global menuitem
    global curmenu
    global selection
    global event_key
    global _active_arrow_widget
    
    log.info(f">>> keyPressed: key_id={id}, _active_arrow_widget={_active_arrow_widget is not None}")
    
    # If arrow widget is active, let it handle the key
    if _active_arrow_widget is not None:
        log.info(f">>> keyPressed: delegating to arrow widget.handle_key({id})")
        handled = _active_arrow_widget.handle_key(id)
        log.info(f">>> keyPressed: arrow widget.handle_key returned {handled}")
        if handled:
            return  # Widget handled the key
    
    # Original key handling for non-menu contexts
    if idle:
        if id == board.Key.TICK:
            event_key.set()
            return
    else:
        if id == board.Key.TICK:
            if not curmenu:
                selection = "BTNTICK"
                #log.info(selection)
                # event_key.set()
                return
            c = 1
            r = ""
            for k, v in curmenu.items():
                if c == menuitem:
                    selection = k
                    #print(selection)
                    event_key.set()
                    menuitem = 1
                    return
                c = c + 1

        if id == board.Key.LONG_PLAY:
            board.shutdown()
            return
        if id == board.Key.DOWN:
            menuitem = menuitem + 1
        if id == board.Key.UP:
            menuitem = menuitem - 1
        if id == board.Key.BACK:
            selection = "BACK"
            event_key.set()
            return
        if id == board.Key.HELP:
            selection = "BTNHELP"
            event_key.set()
            return
        if curmenu is None:
            return
        if menuitem < 1:
            menuitem = len(curmenu)
        if menuitem > len(curmenu):
            menuitem = 1
        if current_renderer:
            current_renderer.change_selection(menuitem - 1)


quickselect = 0

COLOR_MENU = {"white": "White", "black": "Black", "random": "Random"}

MENU_CONFIG = {
    "EmulateEB": {
        "title": "e-Board",
        "description": "Emulate DGT Classic or Millennium electronic boards for compatibility",
        "items": {"dgtclassic": "DGT REVII", "millennium": "Millennium"}
    },
    "settings": {
        "title": "Settings",
        "description": "Configure WiFi, Bluetooth, sound, updates, and system settings",
        "items": None  # Built dynamically
    },
    "Lichess": {
        "title": "Lichess",
        "description": "Play online games and challenges on Lichess.org with your account",
        "items": {"Rated": "Rated", "Unrated": "Unrated", "Ongoing": "Ongoing", "Challenges": "Challenges"}
    },
    "Engines": {
        "title": "Engines",
        "description": "Play against computer opponents with various difficulty levels",
        "items": None  # Built dynamically
    },
    "HandBrain": {
        "title": "Hand + Brain",
        "description": "Two-player cooperative mode where one sees the board and the other calls moves",
        "items": None  # Built dynamically (uses enginemenu)
    }
}

def doMenu(menu_or_key, title_or_key=None, description=None):
    """
    Display a menu and wait for user selection.
    
    Args:
        menu_or_key: Either a menu dict {"key": "Display"} or a config key string
        title_or_key: Either a title string, a config key, or None
        description: Menu description (optional, can be looked up from config)
    
    Returns:
        Selected menu key or "BACK"
    """
    actual_menu = None
    actual_title = None
    actual_description = None
    
    # Case 1: menu_or_key is a config key (e.g., "EmulateEB" or "Lichess")
    if isinstance(menu_or_key, str) and menu_or_key in MENU_CONFIG:
        config = MENU_CONFIG[menu_or_key]
        actual_menu = config.get("items")
        actual_title = config.get("title")
        actual_description = config.get("description")
    
    # Case 2: menu_or_key is a dict and title_or_key is a config key (e.g., enginemenu, "Engines")
    elif isinstance(menu_or_key, dict) and isinstance(title_or_key, str) and title_or_key in MENU_CONFIG:
        config = MENU_CONFIG[title_or_key]
        actual_menu = menu_or_key
        actual_title = config.get("title")
        actual_description = config.get("description")
    
    # Case 3: Explicit parameters (backward compatible)
    else:
        actual_menu = menu_or_key
        actual_title = title_or_key
        actual_description = description
    
    log.info(f">>> doMenu: {actual_menu}, Title: {actual_title}, Description: {actual_description}")
    global menuitem
    global curmenu
    global selection
    global quickselect
    global event_key
    global status_bar_widget
    log.info(">>> doMenu: ensuring display manager is initialized")
    manager = _get_display_manager()
    log.info(">>> doMenu: display manager initialized")
    
    # CRITICAL: Don't clear screen separately - draw menu directly over existing content
    # Clearing then immediately drawing causes rapid successive full refreshes that interfere
    log.info(">>> doMenu: proceeding directly to menu drawing (no separate clear)")
    
    selection = ""
    curmenu = actual_menu
    # Display the given menu
    menuitem = 1
    quickselect = 0    

    quickselect = 1    
    ordered_menu = list(actual_menu.items()) if actual_menu else []
    log.info(f">>> doMenu: creating MenuRenderer with {len(ordered_menu)} entries")
    renderer = MenuRenderer(actual_title, [MenuEntry(k, v) for k, v in ordered_menu], actual_description)
    global current_renderer
    current_renderer = renderer
    initial_index = 0
    if ordered_menu:
        initial_index = max(0, min(len(ordered_menu) - 1, menuitem - 1))
    log.info(f">>> doMenu: calling renderer.draw(initial_index={initial_index})")
    renderer.draw(initial_index)
    log.info(">>> doMenu: renderer.draw() complete, text widgets added to manager")
    
    # Create arrow widget and add it to manager so it uses proper widget mechanism
    # Calculate widget position and dimensions
    arrow_box_top = renderer.body_top  # Top position of arrow box (first selectable row)
    arrow_widget_height = len(ordered_menu) * renderer.row_height if ordered_menu else renderer.row_height
    arrow_widget = MenuArrowWidget(
        x=0,
        y=arrow_box_top,  # Position at top of selectable rows
        width=renderer.arrow_width + 1,  # +1 for vertical line on rightmost side
        height=arrow_widget_height,  # Total height of all selectable rows
        row_height=renderer.row_height,
        num_entries=len(ordered_menu)
    )
    
    # Add arrow widget to manager so it's part of the widget system
    manager.add_widget(arrow_widget)
    log.info(f">>> doMenu: arrow widget added to manager, widgets count={len(manager._widgets)}")
    log.info(f">>> doMenu: arrow widget has update_callback={arrow_widget._update_callback is not None}")
    
    menuitem = (initial_index + 1) if ordered_menu else 1
    
    # Ensure status bar widget is added to manager (it was preserved during MenuRenderer.draw() clear)
    if status_bar_widget and status_bar_widget not in manager._widgets:
        manager.add_widget(status_bar_widget)
    
    # Widgets should call request_update() themselves when ready
    # The arrow widget triggers its own update after being added
    log.info(f">>> doMenu: all widgets added, manager._widgets contains: {[w.__class__.__name__ for w in manager._widgets]}")
    # Wait for arrow widget to trigger its update (it does this automatically)
    if arrow_widget._update_callback:
        future = arrow_widget.request_update(full=False)
        if future:
            future.result(timeout=10.0)
    log.info(">>> doMenu: all widgets rendered")
    
    # Use arrow widget to wait for selection
    try:
        result = arrow_widget.wait_for_selection(initial_index)
        log.info(f">>> doMenu: arrow widget returned result='{result}'")
        
        # Map widget result to menu selection
        if result == "SELECTED":
            # Get the selected menu key from the widget's current selection index
            selected_idx = arrow_widget.selected_index
            if ordered_menu and selected_idx < len(ordered_menu):
                selection = ordered_menu[selected_idx][0]
            else:
                selection = "BACK"
        elif result == "BACK":
            selection = "BACK"
        elif result == "HELP":
            selection = "BTNHELP"
        else:
            selection = "BACK"
        
        # SAFER APPROACH: Remove all widgets except status bar after selection
        widgets_to_keep = []
        if status_bar_widget and status_bar_widget in manager._widgets:
            widgets_to_keep.append(status_bar_widget)
        
        manager._widgets.clear()
        manager._widgets.extend(widgets_to_keep)
        
        log.info(f">>> doMenu: returning selection='{selection}'")
        return selection
    except KeyboardInterrupt:
        log.info(">>> doMenu: KeyboardInterrupt caught")
        # SAFER APPROACH: Remove all widgets except status bar on interrupt
        widgets_to_keep = []
        if status_bar_widget and status_bar_widget in manager._widgets:
            widgets_to_keep.append(status_bar_widget)
        
        manager._widgets.clear()
        manager._widgets.extend(widgets_to_keep)
        return "SHUTDOWN"

def changedCallback(piece_event, field, time_in_seconds):
    log.info(f"changedCallback: {piece_event} {field} {time_in_seconds}")
    board.printChessState()


# Turn Leds off, beep, clear DGT Centaur Serial
_get_display_manager()  # Initialize display
# Create a simple statusbar class
class StatusBar:
    """Simple helper that prints time + battery indicator."""
    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def build(self) -> str:
        clock = time.strftime("%H:%M")
        return clock

    def print_once(self) -> None:
        """Update status bar widget by invalidating and requesting update."""
        global status_bar_widget
        if status_bar_widget:
            status_bar_widget.update(full=False)

    def print(self) -> None:
        self.print_once()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="epaper-status-bar", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None

    def _loop(self) -> None:
        """Status bar update loop."""
        time.sleep(30)
        while self._running:
            self.print_once()
            time.sleep(30)

statusbar = StatusBar()
update = centaur.UpdateSystem()
log.info("Setting checking for updates in 5 mins.")
threading.Timer(300, update.main).start()

# Only initialize board events if menu.py is the main script (not when imported)
# This prevents conflicts when other scripts (like uci.py) import from menu.py
if __name__ == "__main__" or not hasattr(board, '_events_initialized'):
    # Subscribe to board events. First parameter is the function for key presses. The second is the function for
    # field activity
    board.subscribeEvents(keyPressed, changedCallback, timeout=900)
    board._events_initialized = True  # Mark as initialized to prevent re-initialization
    board.printChessState()
    resp = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    log.info(f"Discovery: RESPONSE FROM F0 - {' '.join(f'{b:02x}' for b in resp)}")
    resp = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F4)
    log.info(f"Discovery: RESPONSE FROM F4 - {' '.join(f'{b:02x}' for b in resp)}")
    resp = board.sendCommand(command.DGT_BUS_SEND_96)
    log.info(f"Discovery: RESPONSE FROM 96 - {' '.join(f'{b:02x}' for b in resp)}")
    resp = board.sendCommand(command.DGT_BUS_SEND_STATE)
    log.info(f"Discovery: RESPONSE FROM 83 - {' '.join(f'{b:02x}' for b in resp)}")


def show_welcome():
    global idle
    log.info(">>> show_welcome() ENTERED")
    log.info(">>> show_welcome() calling display manager init")
    manager = _get_display_manager()
    log.info(">>> show_welcome() display manager initialized")
    
    # SAFER APPROACH: Remove all widgets, then add only welcome widget
    manager._widgets.clear()
    log.info(">>> show_welcome() cleared all widgets")
    
    # Create and add welcome widget
    # Widget should call request_update() itself when ready
    status_text = statusbar.build() if 'statusbar' in globals() else "READY"
    welcome_widget = WelcomeWidget(status_text=status_text)
    manager.add_widget(welcome_widget)
    
    # Widget triggers its own update after being added
    log.info(">>> show_welcome() waiting for welcome widget update")
    if welcome_widget._update_callback:
        future = welcome_widget.request_update(full=False)
        if future:
            future.result(timeout=5.0)
    log.info(">>> show_welcome() welcome widget displayed")
    
    idle = True
    log.info(">>> show_welcome() setting idle=True, about to BLOCK on event_key.wait()")
    try:
        event_key.wait()
        log.info(">>> show_welcome() event_key.wait() RETURNED - key was pressed")
    except KeyboardInterrupt:
        log.info(">>> show_welcome() KeyboardInterrupt caught")
        event_key.clear()
        raise  # Re-raise to exit program
    event_key.clear()
    idle = False
    
    # Remove all widgets (including welcome widget) before showing menu
    # Don't update display here - doMenu() will render the menu on a fresh white canvas
    # This avoids triggering a full flash from the scheduler's transition logic
    log.info(">>> show_welcome() EXITING, idle=False")


# Only run main menu initialization if menu.py is executed directly (not when imported)
if __name__ == "__main__":
    log.info(">>> MAIN: About to call show_welcome() - this will BLOCK until key press")
    show_welcome()
    log.info(">>> MAIN: show_welcome() returned, about to start statusbar")
    statusbar.start()
    log.info(">>> MAIN: statusbar.start() complete - entering menu loop")


def run_external_script(script_rel_path: str, *args: str, start_key_polling: bool = True) -> int:
    process = None
    interrupted = False
    
    def signal_handler(signum, frame):
        """Handle Ctrl+C by terminating the subprocess - NO LOGGING to avoid reentrant calls"""
        nonlocal process, interrupted
        if interrupted:
            # Already handling interrupt, force kill immediately and exit
            if process is not None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except:
                    try:
                        process.kill()
                    except:
                        pass
            os._exit(130)
            return
        
        interrupted = True
        if process is not None:
            # Try to terminate gracefully (no blocking wait in signal handler)
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except:
                try:
                    process.terminate()
                except:
                    pass
            
            # Start a background thread to kill if it doesn't exit quickly
            def force_kill_after_delay():
                time.sleep(1.5)
                if process.poll() is None:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except:
                        try:
                            process.kill()
                        except:
                            pass
            threading.Thread(target=force_kill_after_delay, daemon=True).start()
        # Don't block or log - let the main wait() handle completion
    
    # Register signal handler for graceful shutdown
    original_handler = signal.signal(signal.SIGINT, signal_handler)
    try:
        loading_screen()
        board.pauseEvents()
        board.cleanup(leds_off=True)
        statusbar.stop()

        script_path = str((pathlib.Path(__file__).parent / script_rel_path).resolve())
        log.info(f"script_path: {script_path}")
        cmd = [sys.executable, script_path, *map(str, args)]
        
        # Start process in its own process group so we can kill all children
        process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        
        try:
            result = process.wait()
            return result
        except KeyboardInterrupt:
            log.info(">>> KeyboardInterrupt caught, subprocess should already be terminated")
            if process is not None:
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
            return 130  # Standard exit code for SIGINT
    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)
        log.info(">>> Reinitializing after external script...")
        _get_display_manager()  # Reinitialize display
        log.info(">>> display manager initialized")
        clear_screen()
        log.info(">>> clear_screen() complete")
        board.run_background(start_key_polling=start_key_polling)
        log.info(">>> board.run_background() complete")
        board.unPauseEvents()
        log.info(">>> board.unPauseEvents() complete")
        statusbar.start()
        log.info(">>> statusbar.start() complete")


def bluetooth_pairing():
    """
    Run Bluetooth pairing mode with timeout.
    Displays pairing instructions on e-paper screen.
    
    Returns:
        bool: True if device paired successfully, False on timeout
    """
    from DGTCentaurMods.board.bluetooth_controller import BluetoothController
    
    clear_screen()
    write_text(0, "Pair Now use")
    write_text(1, "any passcode if")
    write_text(2, "prompted.")
    write_text(4, "Times out in")
    write_text(5, "one minute.")
    
    def on_device_detected():
        """Callback when pairing device is detected"""
        write_text(8, "Pairing...")
    
    # Create Bluetooth controller instance and start pairing with 60 second timeout
    bluetooth_controller = BluetoothController()
    paired = bluetooth_controller.start_pairing(
        timeout=60, 
        on_device_detected=on_device_detected
    )
    
    # Show result
    clear_screen()
    if paired:
        write_text(0, "Paired!")
        time.sleep(2)
    else:
        write_text(0, "Pairing timeout")
        time.sleep(2)
    clear_screen()
    
    return paired


def chromecast_menu():
    """
    Select and start Chromecast display.
    
    Discovers available Chromecasts, presents menu for selection,
    and launches background cchandler process to stream board display.
    """
    import pychromecast
    
    # Kill any existing cchandler processes
    os.system("ps -ef | grep 'cchandler.py' | grep -v grep | awk '{print $2}' | xargs -r kill -9")
    
    # Discover Chromecasts
    clear_screen()
    write_text(0, "Discovering...")
    write_text(1, "Chromecasts...")
    time.sleep(1)
    
    try:
        chromecasts = pychromecast.get_chromecasts()
    except Exception as e:
        clear_screen()
        write_text(0, "Discovery failed")
        write_text(1, str(e)[:20])
        time.sleep(2)
        return
    
    # Build menu of available Chromecasts (cast type only, not audio devices)
    cc_menu = {}
    cc_mapping = {}  # Map menu keys to actual Chromecast objects
    
    for idx, cc in enumerate(chromecasts[0]):
        if cc.device.cast_type == 'cast':
            friendly_name = cc.device.friendly_name
            # Use friendly name as both key and display value
            cc_menu[friendly_name] = friendly_name
            cc_mapping[friendly_name] = cc
    
    if not cc_menu:
        clear_screen()
        write_text(0, "No Chromecasts")
        write_text(1, "found")
        time.sleep(2)
        return
    
    # Let user select Chromecast using main menu system
    result = doMenu(cc_menu, "Chromecast")
    
    if result == "BACK":
        return
    
    # Launch cchandler in background for selected Chromecast
    cchandler_path = str(pathlib.Path(__file__).parent / 'display' / 'cchandler.py')
    cmd = f'{sys.executable} "{cchandler_path}" "{result}" &'
    os.system(cmd)
    
    # Show feedback
    clear_screen()
    write_text(0, "Streaming to:")
    # Truncate long names to fit on screen (20 chars per line)
    if len(result) > 20:
        write_text(1, result[:20])
        if len(result) > 40:
            write_text(2, result[20:40])
        else:
            write_text(2, result[20:])
    else:
        write_text(1, result)
    time.sleep(2)


def connect_to_wifi(ssid, password):
    """
    Connect to a WiFi network by configuring wpa_supplicant.
    
    Args:
        ssid: The network SSID to connect to
        password: The WiFi password
        
    Returns:
        bool: True if configuration succeeded, False otherwise
    """
    import re
    
    try:
        # Generate wpa_supplicant network block
        # Use subprocess.run for proper resource cleanup
        result = subprocess.run(
            ["sudo", "sh", "-c", f"wpa_passphrase '{ssid}' '{password}'"],
            capture_output=True,
            text=True,
            timeout=5
        )
        section = result.stdout if result.returncode == 0 else ""
        
        if "ssid" not in section:
            log.error("Failed to generate network configuration")
            return False
        
        conf_path = "/etc/wpa_supplicant/wpa_supplicant.conf"
        
        # Read current configuration
        with open(conf_path, "r") as f:
            curconf = f.read()
        
        # Remove any existing block for this SSID (non-greedy)
        newconf = re.sub(
            r'network={[^\}]+?ssid="' + re.escape(ssid) + r'"[^\}]+?}\n',
            '',
            curconf,
            flags=re.DOTALL
        )
        
        # Write updated configuration
        with open(conf_path, "w") as f:
            f.write(newconf)
        
        # Append new network block
        with open(conf_path, "a") as f:
            f.write(section)
        
        # Reconfigure wpa_supplicant
        os.system("sudo wpa_cli -i wlan0 reconfigure")
        
        log.info(f"Successfully configured WiFi for {ssid}")
        return True
        
    except Exception as e:
        log.error(f"Error connecting to WiFi: {e}")
        return False


def get_lichess_client():
    log.debug("get_lichess_client")
    import berserk
    import berserk.exceptions
    token = centaur.get_lichess_api()
    if not len(token):
        log.error('lichess token not defined')
        raise ValueError('lichess token not defined')
    session = berserk.TokenSession(token)
    client = berserk.Client(session=session)
    # just to test if the token is a valid one
    try:
        who = client.account.get()
    except berserk.exceptions.ResponseError:
        log.error('Lichess API error. Wrong token maybe?')
        raise
    return client


# Handle the menu structure
# Only run menu loop if menu.py is executed directly (not when imported)
if __name__ == "__main__":
    while True:    
        menu = {}
        if os.path.exists(centaur_software):
            centaur_item = {"Centaur": "DGT Centaur"}
            menu.update(centaur_item)
        menu.update({"pegasus": "DGT Pegasus"})
        if centaur.lichess_api:
            lichess_item = {"Lichess": "Lichess"}
            menu.update(lichess_item)
        if centaur.get_menuEngines() != "unchecked":
            menu.update({"Engines": "Engines"})
        if centaur.get_menuHandBrain() != "unchecked":
            menu.update({"HandBrain": "Hand + Brain"})
        if centaur.get_menu1v1Analysis() != "unchecked":
            menu.update({"1v1Analysis": "1v1 Analysis"})
        if centaur.get_menuEmulateEB() != "unchecked":
            menu.update({"EmulateEB": "e-Board"})
        if centaur.get_menuCast() != "unchecked":
            menu.update({"Cast": "Chromecast"})
        log.debug("Checking for custom files")
        pyfiles = os.listdir("/home/pi")
        foundpyfiles = 0
        for pyfile in pyfiles:        
            if pyfile[-3:] == ".py" and pyfile != "firstboot.py":
                log.debug("found custom files")
                foundpyfiles = 1
                break
        log.debug("Custom file check complete")
        if foundpyfiles == 1:
            menu.update({"Custom": "Custom"})
        if centaur.get_menuSettings() != "unchecked":
            menu.update({"settings": "Settings"})
        if centaur.get_menuAbout() != "unchecked":
            menu.update({"About": "About"})                                
        result = doMenu(menu, "Main menu")
        # Historical note: previous firmware called into the raw epaper driver here.
        # time.sleep(0.7)
        # time.sleep(1)
        if result == "SHUTDOWN":
            # Graceful shutdown requested via Ctrl+C
            try:
                statusbar.stop()
                board.cleanup(leds_off=True)
                board.pauseEvents()
            except:
                pass
            break
        if result == "BACK":
            board.beep(board.SOUND_POWER_OFF)
            show_welcome()
        if result == "Cast":
            chromecast_menu()
        if result == "Centaur":
            loading_screen()
            #time.sleep(1)
            board.pauseEvents()
            board.cleanup(leds_off=True)
            statusbar.stop()
            time.sleep(1)
            if os.path.exists(centaur_software):
                # Ensure file is executable (Trixie compatibility)
                try:
                    os.chmod(centaur_software, 0o755)
                except Exception as e:
                    log.warning(f"Could not set execute permissions on centaur: {e}")
                # Change directory and use relative path (bypasses sudo secure_path, Trixie compatibility)
                # Don't restore directory since we exit immediately after
                os.chdir("/home/pi/centaur")
                # Use os.system to launch interactive application (blocks until process completes)
                os.system("sudo ./centaur")
            else:
                log.error(f"Centaur executable not found at {centaur_software}")
                write_text(0, "Centaur not found")
                time.sleep(2)
                continue
            # Once started we cannot return to DGTCentaurMods, we can kill that
            time.sleep(3)
            os.system("sudo systemctl stop DGTCentaurMods.service")
            sys.exit()
        if result == "pegasus":
            rc = run_external_script(f"{game_folder}/pegasus.py", start_key_polling=True)
        if result == "EmulateEB":
            result = doMenu("EmulateEB")
            if result == "dgtclassic":
                rc = run_external_script(f"{game_folder}/eboard.py", start_key_polling=True)
            if result == "millennium":
                rc = run_external_script(f"{game_folder}/millennium.py", start_key_polling=True)
        if result == "1v1Analysis":
            rc = run_external_script(f"{game_folder}/1v1Analysis.py", start_key_polling=True)
        if result == "settings":
            setmenu = {
                "WiFi": "Wifi Setup",
                "Pairing": "BT Pair",
                "Sound": "Sound",
                "LichessAPI": "Lichess API",
                "reverseshell": "Shell 7777",
                "update": "Update opts",            
                "Shutdown": "Shutdown",
                "Reboot": "Reboot",
            }
            topmenu = False
            while topmenu == False:
                result = doMenu(setmenu, "settings")
                log.debug(result)
                if result == "update":
                    topmenu = False
                    while topmenu == False:
                        updatemenu = {"status": "State: " + update.getStatus()}
                        package = "/tmp/dgtcentaurmods_armhf.deb"
                        if update.getStatus() == "enabled":
                            updatemenu.update(
                                {
                                    "channel": "Chnl: " + update.getChannel(),
                                    "policy": "Plcy: " + update.getPolicy(),
                                }
                            )
                        # Check for .deb files in the /home/pi folder that have been uploaded by webdav
                        updatemenu["lastrelease"] = "Last Release"
                        debfiles = os.listdir("/home/pi")
                        log.debug("Check for deb files that system can update to")
                        for debfile in debfiles:        
                            if debfile[-4:] == ".deb" and debfile[:15] == "dgtcentaurmods_":
                                log.debug("Found " + debfile)
                                updatemenu[debfile] = debfile[15:debfile.find("_",15)]                    
                        selection = ""
                        result = doMenu(updatemenu, "Update opts")
                        if result == "status":
                            result = doMenu(
                                {"enable": "Enable", "disable": "Disable"}, "Status"
                            )
                            log.debug(result)
                            if result == "enable":
                                update.enable()
                            if result == "disable":
                                update.disable()
                                try:
                                    os.remove(package)
                                except:
                                    pass
                        if result == "channel":
                            result = doMenu({"stable": "Stable", "beta": "Beta"}, "Channel")
                            update.setChannel(result)
                        if result == "policy":
                            result = doMenu(
                                {"always": "Always", "revision": "Revisions"}, "Policy"
                            )
                            update.setPolicy(result)
                        if result == "lastrelease":
                            log.debug("Last Release")
                            update_source = update.conf.read_value('update', 'source')
                            log.debug(update_source)
                            url = 'https://raw.githubusercontent.com/{}/master/DGTCentaurMods/DEBIAN/versions'.format(update_source)                   
                            log.debug(url)
                            ver = None
                            try:
                                with urllib.request.urlopen(url) as versions:
                                    ver = json.loads(versions.read().decode())
                                    log.debug(ver)
                            except Exception as e:
                                log.debug('!! Cannot download update info: ', e)
                            pass
                            if ver != None:
                                log.debug(ver["stable"]["release"])
                                download_url = 'https://github.com/{}/releases/download/v{}/dgtcentaurmods_{}_armhf.deb'.format(update_source,ver["stable"]["release"],ver["stable"]["release"])
                                log.debug(download_url)
                                try:
                                    urllib.request.urlretrieve(download_url,'/tmp/dgtcentaurmods_armhf.deb')
                                    log.debug("downloaded to /tmp")
                                    os.system("cp -f /home/pi/" + result + " /tmp/dgtcentaurmods_armhf.deb")
                                    log.debug("Starting update")
                                    update.updateInstall()
                                except:
                                    pass
                        if os.path.exists("/home/pi/" + result):
                            log.debug("User selected .deb file. Doing update")
                            log.debug("Copying .deb file to /tmp")
                            os.system("cp -f /home/pi/" + result + " /tmp/dgtcentaurmods_armhf.deb")
                            log.debug("Starting update")
                            update.updateInstall()
                        if selection == "BACK":
                            # Trigger the update system to appply new settings
                            try:
                                os.remove(package)
                            except:
                                pass
                            finally:
                                threading.Thread(target=update.main, args=()).start()
                            topmenu = True
                            log.debug("return to settings")
                            selection = ""
                topmenu = False
                if selection == "BACK":
                    topmenu = True
                    result = ""

                if result == "Sound":
                    soundmenu = {"On": "On", "Off": "Off"}
                    result = doMenu(soundmenu, "Sound")
                    if result == "On":
                        centaur.set_sound("on")
                    if result == "Off":
                        centaur.set_sound("off")
                if result == "WiFi":
                    if network.check_network():
                        wifimenu = {"wpa2": "WPA2-PSK", "wps": "WPS Setup"}
                    else:
                        wifimenu = {
                            "wpa2": "WPA2-PSK",
                            "wps": "WPS Setup",
                            "recover": "Recover wifi",
                        }
                    if network.check_network():
                        cmd = (
                            'sudo sh -c "'
                            + str(pathlib.Path(__file__).parent.resolve())
                            + '/scripts/wifi_backup.sh backup"'
                        )                    
                        centaur.shell_run(cmd)
                    result = doMenu(wifimenu, "Wifi Setup")
                    if result != "BACK":
                        if result == "wpa2":
                            # Scan for WiFi networks
                            import subprocess
                            try:
                                scan_result = subprocess.run(['sudo', 'iwlist', 'wlan0', 'scan'], capture_output=True, text=True)
                                if scan_result.returncode == 0:
                                    networks = []
                                    lines = scan_result.stdout.split('\n')
                                    for line in lines:
                                        if 'ESSID:' in line:
                                            essid = line.split('ESSID:')[1].strip().strip('"')
                                            if essid and essid not in networks:
                                                networks.append(essid)
                                
                                    if networks:
                                        # Create menu for networks
                                        network_menu = {}
                                        for ssid in sorted(networks):
                                            network_menu[ssid] = ssid
                                    
                                        # Use doMenu to select network
                                        selected_network = doMenu(network_menu, "WiFi Networks")
                                    
                                        if selected_network and selected_network != "BACK":
                                            # Get password using getText
                                            from DGTCentaurMods.ui.get_text_from_board import getText
                                            password = getText("Enter WiFi password")
                                            #password = board.getText("Enter WiFi password")
                                        
                                            if password:
                                                write_text(0, f"Connecting to")
                                                write_text(1, selected_network)
                                                # Connect to the network
                                                if connect_to_wifi(selected_network, password):
                                                    write_text(3, "Connected!")
                                                else:
                                                    write_text(3, "Connection failed!")
                                                time.sleep(2)
                                            else:
                                                write_text(0, "No password provided")
                                                time.sleep(2)

                                    else:
                                        write_text(0, "No networks found")
                                        time.sleep(2)
                                else:
                                    write_text(0, "Scan failed")
                                    time.sleep(2)
                            except Exception as e:
                                write_text(0, f"Error: {str(e)[:20]}")
                                time.sleep(2)
                        if result == "wps":
                            if network.check_network():
                                selection = ""
                                curmenu = None
                                IP = network.check_network()
                                clear_screen()
                                write_text(0, "Network is up.")
                                write_text(1, "Press OK to")
                                write_text(2, "disconnect")
                                write_text(4, IP)
                                timeout = time.time() + 15
                                while time.time() < timeout:
                                    if selection == "BTNTICK":
                                        network.wps_disconnect_all()
                                        break
                                    time.sleep(2)
                            else:
                                wpsMenu = {"connect": "Connect wifi"}
                                result = doMenu(wpsMenu, "WPS")
                                if result == "connect":
                                    clear_screen()
                                    write_text(0, "Press WPS button")
                                    network.wps_connect()
                        if result == "recover":
                            selection = ""
                            cmd = (
                                'sudo sh -c "'
                                + str(pathlib.Path(__file__).parent.resolve())
                                + '/scripts/wifi_backup.sh restore"'
                            )
                            centaur.shell_run(cmd)                    
                            timeout = time.time() + 20
                            clear_screen()
                            write_text(0, "Waiting for")
                            write_text(1, "network...")
                            while not network.check_network() and time.time() < timeout:
                                time.sleep(1)
                            if not network.check_network():
                                write_text(1, "Failed to restore...")
                                time.sleep(4)

                if result == "Pairing":
                    bluetooth_pairing()
                if result == "LichessAPI":
                    rc = run_external_script("config/lichesstoken.py", start_key_polling=True)
                if result == "Shutdown":
                    # Stop statusbar
                    statusbar.stop()
                
                    # Pause events and cleanup board
                    board.pauseEvents()
                    board.cleanup(leds_off=False)  # LEDs handled by shutdown()
                
                    # Execute shutdown (handles LEDs, e-paper, controller sleep)
                    board.shutdown()
                
                    # Exit cleanly
                    sys.exit()
                if result == "Reboot":
                    board.beep(board.SOUND_POWER_OFF)
                    manager = _get_display_manager()
                    clear_screen()
                    time.sleep(5)
                    manager.shutdown()
                    time.sleep(2)
                
                    # LED cascade pattern h1→h8 (squares 0 to 7) for reboot
                    try:
                        for i in range(0, 8):
                            board.led(i, intensity=5)
                            time.sleep(0.2)
                    except Exception:
                        pass
                
                    board.pauseEvents()
                    board.cleanup(leds_off=True)
                    os.system("/sbin/shutdown -r now &")
                    sys.exit()
                if result == "reverseshell":
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.bind(("0.0.0.0", 7777))
                    s.listen(1)
                    conn, addr = s.accept()
                    conn.send(b'With great power comes great responsibility! Use this if you\n')
                    conn.send(b'can\'t get into ssh for some reason. Otherwise use ssh!\n')
                    conn.send(b'\nBy using this you agree that a modified DGT Centaur Mods board\n')
                    conn.send(b'is the best chessboard in the world.\n')
                    conn.send(b'----------------------------------------------------------------------\n')                
                    os.dup2(conn.fileno(),0)
                    os.dup2(conn.fileno(),1)
                    os.dup2(conn.fileno(),2)
                    p=subprocess.call(["/bin/bash","-i"])
        if result == "Lichess":
            result = doMenu("Lichess")
            log.debug('menu active: lichess')
            if result != "BACK":
                if result == "Ongoing":
                    log.debug('menu active: Ongoing')
                    client = get_lichess_client()
                    ongoing_games = client.games.get_ongoing(10)
                    ongoing_menu = {}
                    log.debug(f"{ongoing_menu}")
                    for game in ongoing_games:
                        gameid = game["gameId"]
                        opponent = game['opponent']['id']
                        if game['color'] == 'white':
                            desc = f"{client.account.get()['username']} vs. {opponent}"
                        else:
                            desc = f" {opponent} vs. {client.account.get()['username']}"
                        ongoing_menu[gameid] = desc
                    log.debug(f"ongoing menu: {ongoing_menu}")
                    if len(ongoing_menu) > 0:
                        result = doMenu(ongoing_menu, "Current games:")
                        if result != "BACK":
                            log.debug(f"menu current games")
                            game_id = result
                            log.debug(f"staring lichess")
                            rc = run_external_script(f"{game_folder}/lichess.py", "Ongoing", game_id, start_key_polling=True)
                    else:
                        log.warning("No ongoing games!")
                        write_text(1, "No ongoing games!")
                        time.sleep(3)


                elif result == "Challenges":
                    client = get_lichess_client()
                    challenge_menu = {}
                    # very ugly call, there is no adequate method in berserk's API,
                    # see https://github.com/rhgrant10/berserk/blob/master/berserk/todo.md
                    challenges = client._r.get('api/challenge')
                    for challenge in challenges['in']:
                        challenge_menu[f"{challenge['id']}:in"] = f"in: {challenge['challenger']['id']}"
                    for challenge in challenges['out']:
                        challenge_menu[f"{challenge['id']}:out"] = f"out: {challenge['destUser']['id']}"
                    result = doMenu(challenge_menu, "Challenges")
                    if result != "BACK":
                        log.debug('menu active: Challenge')
                        game_id, challenge_direction = result.split(":")
                        rc = run_external_script(f"{game_folder}/lichess.py", "Challenge", game_id, challenge_direction, start_key_polling=True)

                else:  # new Rated or Unrated
                    if result == "Rated":
                        rated = True
                    else:
                        assert result == "Unrated", "Wrong game type"  #nie można rzucać wyjątków, bo cała aplikacja się sypie
                        rated = False
                    result = doMenu(COLOR_MENU, "Color")
                    if result != "BACK":
                        color = result
                        timemenu = {
                            "10 , 5": "10+5 minutes",
                            "15 , 10": "15+10 minutes",
                            "30 , 0": "30 minutes",
                            "30 , 20": "30+20 minutes",
                            "45 , 45": "45+45 minutes",
                            "60 , 20": "60+20 minutes",
                            "60 , 30": "60+30 minutes",
                            "90 , 30": "90+30 minutes",
                        }
                        result = doMenu(timemenu, "Time")

                        if result != "BACK":
                            # split time and increment '10 , 5' -> ['10', '5']
                            seek_time = result.split(",")
                            gtime = int(seek_time[0])
                            gincrement = int(seek_time[1])
                            rc = run_external_script(f"{game_folder}/lichess.py", "New", gtime, gincrement, rated, color, start_key_polling=True)
        if result == "Engines":
            enginemenu = {}
            # Pick up the engines from the engines folder and build the menu
            enginepath = str(pathlib.Path(__file__).parent.resolve()) + "/engines/"
            enginefiles = os.listdir(enginepath)
            enginefiles = list(
                filter(lambda x: os.path.isfile(enginepath + x), os.listdir(enginepath))
            )        
            for f in enginefiles:
                fn = str(f)
                if "." not in fn:
                    # If this file don't have an extension then it is an engine
                    enginemenu[fn] = fn
            result = doMenu(enginemenu, "Engines")
            log.debug("Engines")
            log.debug(result)
            if result != "BACK":
                # There are two options here. Either a file exists in the engines folder as enginename.uci which will give us menu options, or one doesn't and we run it as default
                enginefile = enginepath + result
                ucifile = enginepath + result + ".uci"
            
                # Get engine description from .uci file if it exists
                engine_desc = None
                # Check both engines/ and defaults/engines/ directories for .uci files
                ucifile_paths = [
                    enginepath + result + ".uci",  # engines/ directory
                    str(pathlib.Path(__file__).parent.resolve()) + "/defaults/engines/" + result + ".uci"  # defaults/engines/ directory
                ]
                for ucifile_path in ucifile_paths:
                    if os.path.exists(ucifile_path):
                        config = configparser.ConfigParser()
                        config.read(ucifile_path)
                        if 'DEFAULT' in config and 'Description' in config['DEFAULT']:
                            engine_desc = config['DEFAULT']['Description']
                        break
            
                color = doMenu(COLOR_MENU, result, engine_desc)
                # Current game will launch the screen for the current
                log.info("ucifile: " + ucifile)
                if color != "BACK":
                    if os.path.exists(ucifile):
                        # Read the uci file and build a menu
                        config = configparser.ConfigParser()
                        config.read(ucifile)
                        log.debug(config.sections())
                        smenu = {}
                        for sect in config.sections():
                            smenu[sect] = sect
                        sec = doMenu(smenu, result)
                        if sec != "BACK":
                            rc = run_external_script(f"{game_folder}/uci.py", color, result, sec, start_key_polling=True)
                    else:
                        # With no uci file we just call the engine
                        rc = run_external_script(f"{game_folder}/uci.py", color, result, start_key_polling=True)
        if result == "HandBrain":
            # Pick up the engines from the engines folder and build the menu
            enginemenu = {}
            enginepath = str(pathlib.Path(__file__).parent.resolve()) + "/engines/"
            enginefiles = os.listdir(enginepath)
            enginefiles = list(
                filter(lambda x: os.path.isfile(enginepath + x), os.listdir(enginepath))
            )
            log.debug(enginefiles)
            for f in enginefiles:
                fn = str(f)
                if ".uci" not in fn:
                    # If this file is not .uci then assume it is an engine
                    enginemenu[fn] = fn
            result = doMenu(enginemenu, "HandBrain")
            log.debug(result)
            if result != "BACK":
                # There are two options here. Either a file exists in the engines folder as enginename.uci which will give us menu options, or one doesn't and we run it as default
                enginefile = enginepath + result
                ucifile = enginepath + result + ".uci"
            
                # Get engine description from .uci file if it exists
                engine_desc = None
                # Check both engines/ and defaults/engines/ directories for .uci files
                ucifile_paths = [
                    enginepath + result + ".uci",  # engines/ directory
                    str(pathlib.Path(__file__).parent.resolve()) + "/defaults/engines/" + result + ".uci"  # defaults/engines/ directory
                ]
                for ucifile_path in ucifile_paths:
                    if os.path.exists(ucifile_path):
                        config = configparser.ConfigParser()
                        config.read(ucifile_path)
                        if 'DEFAULT' in config and 'Description' in config['DEFAULT']:
                            engine_desc = config['DEFAULT']['Description']
                        break
            
                color = doMenu(COLOR_MENU, result, engine_desc)
                # Current game will launch the screen for the current
                if color != "BACK":
                    if os.path.exists(ucifile):
                        # Read the uci file and build a menu
                        config = configparser.ConfigParser()
                        config.read(ucifile)
                        log.info(config.sections())
                        smenu = {}
                        for sect in config.sections():
                            smenu[sect] = sect
                        sec = doMenu(smenu, result)
                        if sec != "BACK":
                            rc = run_external_script(f"{game_folder}/handbrain.py", color, result, sec, start_key_polling=True)
                    else:
                        # With no uci file we just call the engine
                        rc = run_external_script(f"{game_folder}/handbrain.py", color, result, start_key_polling=True)
        if result == "Custom":
            pyfiles = os.listdir("/home/pi")
            menuitems = {}
            for pyfile in pyfiles:        
                if pyfile[-3:] == ".py" and pyfile != "firstboot.py":                
                    menuitems[pyfile] = pyfile
            result = doMenu(menuitems,"Custom Scripts")
            if result.find("..") < 0:
                log.info("Running custom file: " + result)
                os.system("python /home/pi/" + result)

        if result == "About" or result == "BTNHELP":
            selection = ""
            clear_screen()
            statusbar.print()
            # Use subprocess.run for proper resource cleanup
            result = subprocess.run(
                ["dpkg", "-l"],
                capture_output=True,
                text=True,
                timeout=5
            )
            version = ""
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'dgtcentaurmods' in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            version = parts[2]
                            break
            write_text(1, "Get support:")
            write_text(9, "DGTCentaur")
            write_text(10, "      Mods")
            write_text(11, "Ver:" + version)        
            qr = Image.open(AssetManager.get_resource_path("qr-support.png")).resize((128, 128))
            manager = _get_display_manager()
            canvas = manager._framebuffer.get_canvas()
            canvas.paste(qr, (0, 42))
            manager.update(full=True)
            timeout = time.time() + 15
            while selection == "" and time.time() < timeout:
                if selection == "BTNTICK" or selection == "BTNBACK":
                    break
            clear_screen()        
