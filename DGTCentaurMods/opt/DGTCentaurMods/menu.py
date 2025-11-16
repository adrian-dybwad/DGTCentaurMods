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
from DGTCentaurMods.display.epaper_service import service, widgets
from DGTCentaurMods.display.epaper_service.regions import Region
from PIL import Image, ImageDraw, ImageFont
from DGTCentaurMods.board.logging import log

menuitem = 1
curmenu = None
selection = ""
centaur_software = "/home/pi/centaur/centaur"
game_folder = "games"

event_key = threading.Event()
idle = False # ensure defined before keyPressed can be called

MENU_ROW_HEIGHT = widgets.MENU_ROW_HEIGHT
MENU_BODY_TOP_WITH_TITLE = widgets.MENU_TOP
MENU_BODY_TOP_NO_TITLE = widgets.STATUS_BAR_HEIGHT + widgets.TITLE_GAP
DESCRIPTION_GAP = 8

current_renderer: Optional["MenuRenderer"] = None


def _paint_region(region: Region, painter: Callable[[object], None]) -> None:
    with service.acquire_canvas() as canvas:
        painter(canvas)
        canvas.mark_dirty(region)
    service.submit_region(region)


def _clear_rect(x1: int, y1: int, x2: int, y2: int) -> None:
    widgets.clear_area(Region(x1, y1, x2, y2))


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
        
        # Draw everything in a single canvas operation to ensure atomicity
        log.info(">>> MenuRenderer.draw() acquiring canvas for all menu drawing")
        with service.acquire_canvas() as canvas:
            draw = canvas.draw
            
            # Draw title if present
            if self.title:
                log.info(f">>> MenuRenderer.draw() drawing title: '{self.title}'")
                title_text = f"[ {self.title} ]"
                title_top = MENU_BODY_TOP_WITH_TITLE - widgets.TITLE_HEIGHT
                title_region = Region(0, title_top, 128, title_top + widgets.TITLE_HEIGHT)
                draw.rectangle(title_region.to_box(), fill=0, outline=0)
                draw.text((0, title_top - 1), title_text, font=widgets.FONT_18, fill=255)
                canvas.mark_dirty(title_region)
            
            # Draw all menu entries
            log.info(f">>> MenuRenderer.draw() drawing {len(self.entries)} entries")
            for idx, entry in enumerate(self.entries):
                top = self._row_top(idx)
                entry_region = Region(0, top, 128, top + self.row_height)
                is_selected = (idx == self.selected_index)
                fill, fg = (0, 255) if is_selected else (255, 0)
                draw.rectangle(entry_region.to_box(), fill=fill, outline=fill)
                text = f"    {entry.label}"
                draw.text((0, top - 1), text, font=widgets.FONT_18, fill=fg)
                canvas.mark_dirty(entry_region)
                
                # Draw arrow for selected entry
                if is_selected:
                    arrow_region = Region(0, top, self.arrow_width, top + self.row_height)
                    draw.rectangle(arrow_region.to_box(), fill=255, outline=255)
                    draw.polygon(
                        [
                            (2, top + 2),
                            (2, top + self.row_height - 2),
                            (self.arrow_width - 3, top + (self.row_height // 2)),
                        ],
                        fill=0,
                    )
                    canvas.mark_dirty(arrow_region)
            
            # Draw description if present
            if self.description:
                log.info(">>> MenuRenderer.draw() drawing description")
                desc_top = self._row_top(len(self.entries)) + DESCRIPTION_GAP
                desc_region = Region(0, desc_top, 128, 296)
                draw.rectangle(desc_region.to_box(), fill=255, outline=255)
                wrapped = self._wrap_text(self.description, max_width=desc_region.x2 - desc_region.x1 - 10)
                for idx, line in enumerate(wrapped[:9]):
                    y_pos = desc_top + 2 + (idx * 16)
                    draw.text((5, y_pos), line, font=self._description_font, fill=0)
                canvas.mark_dirty(desc_region)
        
        log.info(">>> MenuRenderer.draw() canvas released, EXITING")

    def change_selection(self, new_index: int) -> None:
        if not self.entries:
            return
        new_index = max(0, min(new_index, self.max_index()))
        if new_index == self.selected_index:
            return
        self._draw_entry(self.selected_index, selected=False)
        self._draw_arrow(self.selected_index, False)
        self.selected_index = new_index
        self._draw_entry(self.selected_index, selected=True)
        self._draw_arrow(self.selected_index, True)

    def _row_top(self, idx: int) -> int:
        return self.body_top + (idx * self.row_height)

    def _draw_entry(self, idx: int, selected: bool) -> None:
        if idx < 0 or idx >= len(self.entries):
            return
        text = f"    {self.entries[idx].label}"
        widgets.draw_menu_entry(self._row_top(idx), text, selected=selected)

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
        service.submit_region(region)

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
    # This functiion receives key presses
    log.info("in menu.py keyPressed: " + str(id))
    global menuitem
    global curmenu
    global selection
    global event_key
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
    log.info(">>> doMenu: ensuring service is initialized")
    service.init()
    log.info(">>> doMenu: service.init() complete, calling widgets.clear_screen()")
    widgets.clear_screen()
    log.info(">>> doMenu: widgets.clear_screen() complete (it awaited completion), waiting briefly before menu drawing")
    # Small delay to ensure e-paper display has fully completed the clear operation
    time.sleep(0.1)
    log.info(">>> doMenu: proceeding with menu drawing")
    
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
    log.info(">>> doMenu: renderer.draw() complete, menu content is in framebuffer")
    menuitem = (initial_index + 1) if ordered_menu else 1
    
    # Draw status bar directly to framebuffer (don't submit region yet)
    log.info(">>> doMenu: drawing status bar to framebuffer")
    status_text = statusbar.build()
    with service.acquire_canvas() as canvas:
        draw = canvas.draw
        status_region = Region(0, 0, 128, widgets.STATUS_BAR_HEIGHT)
        draw.rectangle(status_region.to_box(), fill=255, outline=255)
        draw.text((2, -1), status_text, font=widgets.STATUS_FONT, fill=0)
        canvas.mark_dirty(status_region)
        # Draw battery icon
        from DGTCentaurMods.display.epaper_service.widgets import _draw_battery_icon_to_canvas
        _draw_battery_icon_to_canvas(canvas, top_padding=1)
    
    log.info(">>> doMenu: status bar drawn to framebuffer, submitting full refresh to display menu")
    # Submit full refresh to display everything (menu + status bar)
    service.submit_full(await_completion=True)
    log.info(">>> doMenu: full refresh complete, about to BLOCK on event_key.wait()")
    try:
        event_key.wait()
        log.info(">>> doMenu: event_key.wait() RETURNED - selection made")
    except KeyboardInterrupt:
        log.info(">>> doMenu: KeyboardInterrupt caught")
        event_key.clear()
        return "SHUTDOWN"
    event_key.clear()
    log.info(f">>> doMenu: returning selection='{selection}'")
    return selection

def changedCallback(piece_event, field, time_in_seconds):
    log.info(f"changedCallback: {piece_event} {field} {time_in_seconds}")
    board.printChessState()


# Turn Leds off, beep, clear DGT Centaur Serial
service.init()
statusbar = widgets.status_bar()
update = centaur.UpdateSystem()
log.info("Setting checking for updates in 5 mins.")
threading.Timer(300, update.main).start()
# Subscribe to board events. First parameter is the function for key presses. The second is the function for
# field activity
board.subscribeEvents(keyPressed, changedCallback, timeout=900)
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
    log.info(">>> show_welcome() calling service.init()")
    service.init()
    log.info(">>> show_welcome() service.init() complete")
    log.info(">>> show_welcome() calling widgets.welcome_screen()")
    widgets.welcome_screen(status_text=statusbar.build() if 'statusbar' in globals() else "READY")
    log.info(">>> show_welcome() widgets.welcome_screen() complete")
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
    log.info(">>> show_welcome() EXITING, idle=False")


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
        widgets.loading_screen()
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
        service.init()
        log.info(">>> service.init() complete")
        widgets.clear_screen()
        log.info(">>> widgets.clear_screen() complete")
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
    
    widgets.clear_screen()
    widgets.write_text(0, "Pair Now use")
    widgets.write_text(1, "any passcode if")
    widgets.write_text(2, "prompted.")
    widgets.write_text(4, "Times out in")
    widgets.write_text(5, "one minute.")
    
    def on_device_detected():
        """Callback when pairing device is detected"""
        widgets.write_text(8, "Pairing...")
    
    # Create Bluetooth controller instance and start pairing with 60 second timeout
    bluetooth_controller = BluetoothController()
    paired = bluetooth_controller.start_pairing(
        timeout=60, 
        on_device_detected=on_device_detected
    )
    
    # Show result
    widgets.clear_screen()
    if paired:
        widgets.write_text(0, "Paired!")
        time.sleep(2)
    else:
        widgets.write_text(0, "Pairing timeout")
        time.sleep(2)
    widgets.clear_screen()
    
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
    widgets.clear_screen()
    widgets.write_text(0, "Discovering...")
    widgets.write_text(1, "Chromecasts...")
    time.sleep(1)
    
    try:
        chromecasts = pychromecast.get_chromecasts()
    except Exception as e:
        widgets.clear_screen()
        widgets.write_text(0, "Discovery failed")
        widgets.write_text(1, str(e)[:20])
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
        widgets.clear_screen()
        widgets.write_text(0, "No Chromecasts")
        widgets.write_text(1, "found")
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
    widgets.clear_screen()
    widgets.write_text(0, "Streaming to:")
    # Truncate long names to fit on screen (20 chars per line)
    if len(result) > 20:
        widgets.write_text(1, result[:20])
        if len(result) > 40:
            widgets.write_text(2, result[20:40])
        else:
            widgets.write_text(2, result[20:])
    else:
        widgets.write_text(1, result)
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
        widgets.loading_screen()
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
            widgets.write_text(0, "Centaur not found")
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
                                            widgets.write_text(0, f"Connecting to")
                                            widgets.write_text(1, selected_network)
                                            # Connect to the network
                                            if connect_to_wifi(selected_network, password):
                                                widgets.write_text(3, "Connected!")
                                            else:
                                                widgets.write_text(3, "Connection failed!")
                                            time.sleep(2)
                                        else:
                                            widgets.write_text(0, "No password provided")
                                            time.sleep(2)

                                else:
                                    widgets.write_text(0, "No networks found")
                                    time.sleep(2)
                            else:
                                widgets.write_text(0, "Scan failed")
                                time.sleep(2)
                        except Exception as e:
                            widgets.write_text(0, f"Error: {str(e)[:20]}")
                            time.sleep(2)
                    if result == "wps":
                        if network.check_network():
                            selection = ""
                            curmenu = None
                            IP = network.check_network()
                            widgets.clear_screen()
                            widgets.write_text(0, "Network is up.")
                            widgets.write_text(1, "Press OK to")
                            widgets.write_text(2, "disconnect")
                            widgets.write_text(4, IP)
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
                                widgets.clear_screen()
                                widgets.write_text(0, "Press WPS button")
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
                        widgets.clear_screen()
                        widgets.write_text(0, "Waiting for")
                        widgets.write_text(1, "network...")
                        while not network.check_network() and time.time() < timeout:
                            time.sleep(1)
                        if not network.check_network():
                            widgets.write_text(1, "Failed to restore...")
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
                service.init()
                widgets.clear_screen()
                time.sleep(5)
                service.shutdown()
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
                    widgets.write_text(1, "No ongoing games!")
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
        widgets.clear_screen()
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
        widgets.write_text(1, "Get support:")
        widgets.write_text(9, "DGTCentaur")
        widgets.write_text(10, "      Mods")
        widgets.write_text(11, "Ver:" + version)        
        qr = Image.open(AssetManager.get_resource_path("qr-support.png")).resize((128, 128))
        widgets.draw_image(qr, 0, 42)
        timeout = time.time() + 15
        while selection == "" and time.time() < timeout:
            if selection == "BTNTICK" or selection == "BTNBACK":
                break
        widgets.clear_screen()        
