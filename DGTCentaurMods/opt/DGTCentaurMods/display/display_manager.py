"""
Unified e-paper display manager with clean API.

This file is part of the DGTCentaur Mods open source software
( https://github.com/EdNekebno/DGTCentaur )

DGTCentaur Mods is free software: you can redistribute
it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version.

DGTCentaur Mods is distributed in the hope that it will
be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this file.  If not, see

https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md

This and any other notices must remain intact and unaltered in any
distribution, modification, variant, or derivative of this software.
"""

import threading
import time
import os
from typing import Optional, List, Tuple
from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.display.display_types import (
    DISPLAY_WIDTH,
    DISPLAY_HEIGHT,
    ROW_HEIGHT,
    BOARD_START_ROW,
    COLOR_WHITE,
    COLOR_BLACK,
    UpdateMode,
    DisplayState,
    SLEEP_TIMEOUT_COUNT,
    BatteryLevel
)
from DGTCentaurMods.display.hardware_driver import HardwareDriver
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.display.chess_board_renderer import ChessBoardRenderer
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board import board


class DisplayManager:
    """
    Unified e-paper display manager with clean API.
    
    Singleton pattern ensures single instance across application.
    Manages the display buffer, update thread, and all drawing operations.
    """
    
    _instance: Optional['DisplayManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Implement singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(DisplayManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize display manager (only once)."""
        # Prevent re-initialization
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = False
        self.state = DisplayState.UNINITIALIZED
        
        # Display buffer
        self.buffer: Image.Image = Image.new('1', (DISPLAY_WIDTH, DISPLAY_HEIGHT), COLOR_WHITE)
        self._last_buffer_bytes: bytes = b''
        
        # Hardware drivers
        self.driver = HardwareDriver()
        
        # Chess board renderer
        self.board_renderer = ChessBoardRenderer()
        
        # Update thread control
        self._update_thread: Optional[threading.Thread] = None
        self._stop_thread = False
        self._update_paused = False
        
        # Display settings
        self._inverted = False
        self._disabled = False
        self._update_mode = UpdateMode.PARTIAL
        self._first_update = True
        
        # Sleep management
        self._sleep_counter = 0
        self._is_sleeping = False
        
        # Fonts
        self.font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
    
    def initialize(self, mode: UpdateMode = UpdateMode.PARTIAL) -> None:
        """
        Initialize the display hardware and start update thread.
        
        Args:
            mode: Update mode (PARTIAL or FULL)
        """
        if self.state != DisplayState.UNINITIALIZED and self.state != DisplayState.DISABLED:
            log.debug("Display already initialized, restarting...")
            self.shutdown()
        
        log.debug("Initializing display manager...")
        
        # Stop existing thread if any
        if self._update_thread and self._update_thread.is_alive():
            self._stop_thread = True
            self._update_thread.join(timeout=2.0)
        
        # Reset state
        self._update_mode = mode
        self._stop_thread = False
        self._update_paused = False
        self._first_update = True
        self._sleep_counter = 0
        self._is_sleeping = False
        
        # Initialize hardware
        self.driver.reset()
        self.driver.init()
        
        # Clear buffer
        self.buffer = Image.new('1', (DISPLAY_WIDTH, DISPLAY_HEIGHT), COLOR_WHITE)
        self._last_buffer_bytes = b''
        
        # Start update thread
        self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self._update_thread.start()
        
        self.state = DisplayState.INITIALIZED
        self._initialized = True
        log.debug("Display manager initialized")
    
    def shutdown(self) -> None:
        """Shutdown the display manager and update thread."""
        log.debug("Shutting down display manager...")
        self._stop_thread = True
        
        if self._update_thread and self._update_thread.is_alive():
            self._update_thread.join(timeout=2.0)
        
        # Put display to sleep
        try:
            self.driver.sleep_display()
        except Exception as e:
            log.error(f"Error putting display to sleep: {e}")
        
        self.state = DisplayState.UNINITIALIZED
        log.debug("Display manager shut down")
    
    def _compute_changed_region(self, prev_bytes: bytes, curr_bytes: bytes) -> Tuple[int, int]:
        """
        Compute the row range that has changed between two buffer states.
        
        Args:
            prev_bytes: Previous buffer state
            curr_bytes: Current buffer state
            
        Returns:
            Tuple of (start_row, end_row) indices [0, 295]
        """
        if not prev_bytes or not curr_bytes or len(prev_bytes) != len(curr_bytes):
            return 0, 295
        
        total = len(curr_bytes)
        start_row, end_row = 0, 295
        
        # Find first differing byte
        for i in range(total):
            if prev_bytes[i] != curr_bytes[i]:
                start_row = max(0, (i // 16) - 1)
                break
        
        # Find last differing byte
        for i in range(total - 1, -1, -1):
            if prev_bytes[i] != curr_bytes[i]:
                end_row = min(295, (i // 16) + 1)
                break
        
        # Sanity check
        if start_row >= end_row:
            return 0, 295
        
        return start_row, end_row
    
    def _update_loop(self) -> None:
        """
        Main update loop thread.
        
        Monitors buffer changes and updates the physical display.
        Runs continuously until shutdown.
        """
        log.debug("Display update thread started")
        
        # Initial display
        self.driver.display(self.buffer)
        log.debug("Initial display sent")
        
        while not self._stop_thread:
            try:
                # Get current buffer state
                buffer_copy = self.buffer.copy()
                
                if not self._update_paused:
                    # Convert to bytes for comparison
                    current_bytes = self.driver.get_buffer(buffer_copy)
                    
                    # Check if buffer has changed
                    if current_bytes != self._last_buffer_bytes:
                        log.debug("Display change detected, updating screen")
                        self._sleep_counter = 0
                        
                        # Wake display if sleeping
                        if self._is_sleeping:
                            self.driver.reset()
                            self._is_sleeping = False
                        
                        # Save to web view
                        try:
                            paths.write_epaper_static_jpg(buffer_copy)
                        except Exception as e:
                            log.error(f"Error saving display image: {e}")
                        
                        # Prepare image for display (flip if not inverted)
                        display_image = buffer_copy.copy()
                        if not self._inverted:
                            display_image = display_image.transpose(Image.FLIP_TOP_BOTTOM)
                            display_image = display_image.transpose(Image.FLIP_LEFT_RIGHT)
                        
                        # Update display based on mode
                        if self._update_mode == UpdateMode.PARTIAL or self._first_update:
                            log.debug("Using display_partial")
                            self.driver.display_partial(display_image)
                            self._first_update = False
                        else:
                            # Region update for maximum efficiency
                            start_row, end_row = self._compute_changed_region(
                                self._last_buffer_bytes,
                                current_bytes
                            )
                            log.info(f"Using display_region: rows {start_row} to {end_row}")
                            
                            # Crop to changed region
                            region_image = buffer_copy.crop((0, start_row + 1, DISPLAY_WIDTH, end_row))
                            region_image = region_image.transpose(Image.FLIP_TOP_BOTTOM)
                            region_image = region_image.transpose(Image.FLIP_LEFT_RIGHT)
                            
                            self.driver.display_region(296 - end_row, 295 - start_row, region_image)
                        
                        self._last_buffer_bytes = current_bytes
                
                # Sleep management
                self._sleep_counter += 1
                if self._sleep_counter >= SLEEP_TIMEOUT_COUNT and not self._is_sleeping:
                    log.debug("Display sleep timeout, putting display to sleep")
                    self._is_sleeping = True
                    try:
                        self.driver.sleep_display()
                    except Exception as e:
                        log.error(f"Error putting display to sleep: {e}")
                
                time.sleep(0.1)
            
            except Exception as e:
                log.error(f"Error in display update loop: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)  # Backoff on error
        
        log.debug("Display update thread stopped")
    
    # === Buffer Management ===
    
    def get_buffer(self) -> Image.Image:
        """
        Get a copy of the current display buffer.
        
        Returns:
            Copy of the current PIL Image buffer
        """
        return self.buffer.copy()
    
    def clear(self) -> None:
        """Clear the entire display to white."""
        with self._lock:
            draw = ImageDraw.Draw(self.buffer)
            draw.rectangle([(0, 0), (DISPLAY_WIDTH, DISPLAY_HEIGHT)], fill=COLOR_WHITE, outline=COLOR_WHITE)
        
        # Force a full update
        if not self._update_paused:
            try:
                self.driver.display_region(0, 295, self.buffer)
                self.driver.clear()
                self._first_update = False
            except Exception as e:
                log.error(f"Error clearing display: {e}")
    
    def refresh(self) -> None:
        """Force an immediate display refresh."""
        # Force buffer update by changing last bytes
        self._last_buffer_bytes = b''
    
    # === Drawing Operations ===
    
    def draw_text(self, row: int, text: str, inverted: bool = False) -> None:
        """
        Draw text on a specific row.
        
        Args:
            row: Row number (0-14)
            text: Text string to display
            inverted: If True, draw white text on black background
        """
        if self._disabled:
            return
        
        with self._lock:
            # Create text image
            text_image = Image.new('1', (DISPLAY_WIDTH, ROW_HEIGHT), COLOR_WHITE)
            draw = ImageDraw.Draw(text_image)
            
            if inverted:
                text_image = Image.new('1', (DISPLAY_WIDTH, ROW_HEIGHT), COLOR_BLACK)
                draw = ImageDraw.Draw(text_image)
                draw.text((0, 0), text, font=self.font18, fill=COLOR_WHITE)
            else:
                draw.text((0, 0), text, font=self.font18, fill=COLOR_BLACK)
            
            # Clear area and paste text
            y_pos = row * ROW_HEIGHT
            self._clear_area(0, y_pos, DISPLAY_WIDTH - 1, y_pos + ROW_HEIGHT)
            self.buffer.paste(text_image, (0, y_pos))
    
    def draw_menu_title(self, title: str) -> None:
        """
        Draw a menu title (inverted text on row 1).
        
        Args:
            title: Title text to display
        """
        if self._disabled:
            return
        
        with self._lock:
            text_image = Image.new('1', (DISPLAY_WIDTH, ROW_HEIGHT), COLOR_BLACK)
            draw = ImageDraw.Draw(text_image)
            draw.text((4, -2), title, font=self.font18, fill=COLOR_WHITE)
            self.buffer.paste(text_image, (0, ROW_HEIGHT))
    
    def draw_image(self, x: int, y: int, image: Image.Image) -> None:
        """
        Draw an image at the specified position.
        
        Args:
            x: X coordinate
            y: Y coordinate
            image: PIL Image to draw
        """
        if self._disabled:
            return
        
        with self._lock:
            self.buffer.paste(image, (x, y))
    
    def draw_rectangle(self, x1: int, y1: int, x2: int, y2: int, fill: int, outline: int) -> None:
        """
        Draw a rectangle.
        
        Args:
            x1, y1: Top-left corner
            x2, y2: Bottom-right corner
            fill: Fill color (0 or 255)
            outline: Outline color (0 or 255)
        """
        if self._disabled:
            return
        
        with self._lock:
            draw = ImageDraw.Draw(self.buffer)
            draw.rectangle([(x1, y1), (x2, y2)], fill=fill, outline=outline)
    
    def _clear_area(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """
        Clear an area of the screen (internal).
        
        Args:
            x1, y1: Top-left corner
            x2, y2: Bottom-right corner
        """
        draw = ImageDraw.Draw(self.buffer)
        draw.rectangle([(x1, y1), (x2, y2)], fill=COLOR_WHITE, outline=COLOR_WHITE)
    
    # === Chess Board Drawing ===
    
    def draw_board(self, pieces: List[str], start_row: int = BOARD_START_ROW, flip: bool = False) -> None:
        """
        Draw a chess board from piece list.
        
        Args:
            pieces: List/string of 64 pieces
            start_row: Starting row for the board (default 2)
            flip: If True, flip board for black's perspective
        """
        if self._disabled:
            return
        
        try:
            board_image = self.board_renderer.render_board(pieces, flip=flip)
            y_pos = (start_row * ROW_HEIGHT) + 8
            self.draw_image(0, y_pos, board_image)
        except Exception as e:
            log.error(f"Error drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def draw_fen(self, fen: str, start_row: int = BOARD_START_ROW, flip: bool = False) -> None:
        """
        Draw a chess board from FEN string.
        
        Args:
            fen: FEN notation string
            start_row: Starting row for the board (default 2)
            flip: If True, flip board for black's perspective
        """
        if self._disabled:
            return
        
        try:
            board_image = self.board_renderer.render_fen(fen, flip=flip)
            y_pos = (start_row * ROW_HEIGHT) + 8
            self.draw_image(0, y_pos, board_image)
        except Exception as e:
            log.error(f"Error drawing FEN: {e}")
            import traceback
            traceback.print_exc()
    
    # === Special UI Elements ===
    
    def draw_promotion_options(self, row: int) -> None:
        """
        Draw promotion piece selection UI.
        
        Args:
            row: Row to draw the options on
        """
        if self._disabled:
            return
        
        log.debug("Drawing promotion options")
        
        with self._lock:
            offset = row * ROW_HEIGHT
            draw = ImageDraw.Draw(self.buffer)
            draw.text((0, offset + 0), "    Q    R    N    B", font=self.font18, fill=COLOR_BLACK)
            
            # Draw arrows and symbols
            draw.polygon([(2, offset + 18), (18, offset + 18), (10, offset + 3)], fill=COLOR_BLACK)
            draw.polygon([(35, offset + 3), (51, offset + 3), (43, offset + 18)], fill=COLOR_BLACK)
            
            # Return arrow
            o = 66
            draw.line((0 + o, offset + 16, 16 + o, offset + 16), fill=COLOR_BLACK, width=5)
            draw.line((14 + o, offset + 16, 14 + o, offset + 5), fill=COLOR_BLACK, width=5)
            draw.line((16 + o, offset + 6, 4 + o, offset + 6), fill=COLOR_BLACK, width=5)
            draw.polygon([(8 + o, offset + 2), (8 + o, offset + 10), (0 + o, offset + 6)], fill=COLOR_BLACK)
            
            # Checkmark
            o = 97
            draw.line((6 + o, offset + 16, 16 + o, offset + 4), fill=COLOR_BLACK, width=5)
            draw.line((2 + o, offset + 10, 8 + o, offset + 16), fill=COLOR_BLACK, width=5)
    
    def draw_resign_draw_menu(self, row: int) -> None:
        """
        Draw resign/draw offer UI.
        
        Args:
            row: Row to draw the options on
        """
        if self._disabled:
            return
        
        with self._lock:
            offset = row * ROW_HEIGHT
            draw = ImageDraw.Draw(self.buffer)
            draw.text((0, offset + 0), "    DRW    RESI", font=self.font18, fill=COLOR_BLACK)
            draw.polygon([(2, offset + 18), (18, offset + 18), (10, offset + 3)], fill=COLOR_BLACK)
            draw.polygon([(35 + 25, offset + 3), (51 + 25, offset + 3), (43 + 25, offset + 18)], fill=COLOR_BLACK)
    
    def draw_battery_indicator(self) -> None:
        """Draw battery level indicator."""
        if self._disabled:
            return
        
        battery_indicator = "battery1"
        if board.batterylevel >= BatteryLevel.LOW:
            battery_indicator = "battery2"
        if board.batterylevel >= BatteryLevel.MEDIUM:
            battery_indicator = "battery3"
        if board.batterylevel >= BatteryLevel.HIGH:
            battery_indicator = "battery4"
        
        if board.chargerconnected > 0:
            battery_indicator = "batteryc"
            if board.batterylevel == BatteryLevel.FULL:
                battery_indicator = "batterycf"
        
        if board.batterylevel >= 0:
            try:
                img = Image.open(AssetManager.get_resource_path(battery_indicator + ".bmp"))
                self.draw_image(98, 2, img)
            except Exception as e:
                log.error(f"Error drawing battery indicator: {e}")
    
    # === Screen Templates ===
    
    def show_loading_screen(self) -> None:
        """Display loading screen with logo."""
        self._show_logo_screen("     Loading", "")
    
    def show_welcome_screen(self) -> None:
        """Display welcome screen."""
        self._show_logo_screen("     Press", "      to start")
        
        # Draw checkmark
        with self._lock:
            draw = ImageDraw.Draw(self.buffer)
            x, y = 75, 200
            draw.line((6 + x, y + 16, 16 + x, y + 4), fill=COLOR_BLACK, width=5)
            draw.line((2 + x, y + 10, 8 + x, y + 16), fill=COLOR_BLACK, width=5)
    
    def show_standby_screen(self, show: bool) -> None:
        """
        Show or hide standby screen.
        
        Args:
            show: If True, display standby screen. If False, restore previous buffer.
        """
        standby_file = '/tmp/epapersave.bmp'
        
        if show:
            # Save current buffer
            log.debug('Saving buffer for standby')
            try:
                self.buffer.save(standby_file)
            except Exception as e:
                log.error(f"Error saving buffer: {e}")
            
            # Show standby screen
            self.clear()
            self.draw_status_bar()
            
            try:
                filename = AssetManager.get_resource_path("logo_mods_screen.jpg")
                logo = Image.open(filename)
                self.draw_image(0, 20, logo)
            except Exception as e:
                log.error(f"Error loading logo: {e}")
            
            self.draw_text(10, "   Press [>||]")
            self.draw_text(11, "   to power on")
        else:
            # Restore previous buffer
            log.debug('Restoring buffer from standby')
            try:
                if os.path.exists(standby_file):
                    restore = Image.open(standby_file)
                    with self._lock:
                        self.buffer = restore.copy()
                    os.remove(standby_file)
            except Exception as e:
                log.error(f"Error restoring buffer: {e}")
    
    def _show_logo_screen(self, line1: str, line2: str) -> None:
        """
        Internal method to show logo with two lines of text.
        
        Args:
            line1: First line of text
            line2: Second line of text
        """
        self.clear()
        self.draw_status_bar()
        
        try:
            filename = AssetManager.get_resource_path("logo_mods_screen.jpg")
            logo = Image.open(filename)
            self.draw_image(0, 20, logo)
        except Exception as e:
            log.error(f"Error loading logo: {e}")
        
        if line1:
            self.draw_text(10, line1)
        if line2:
            self.draw_text(11, line2)
    
    def draw_status_bar(self) -> None:
        """Draw status bar with time and battery."""
        clock_time = time.strftime("%H:%M")
        self.draw_text(0, clock_time)
        self.draw_battery_indicator()
    
    # === State Control ===
    
    def pause(self) -> None:
        """Pause display updates."""
        self._update_paused = True
        self.state = DisplayState.PAUSED
        log.debug("Display updates paused")
    
    def resume(self) -> None:
        """Resume display updates."""
        self._update_paused = False
        if self._initialized:
            self.state = DisplayState.INITIALIZED
        log.debug("Display updates resumed")
    
    def set_inverted(self, inverted: bool) -> None:
        """
        Set display inversion state.
        
        Args:
            inverted: If True, don't flip display output
        """
        self._inverted = inverted
        log.debug(f"Display inverted set to: {inverted}")
    
    def enable(self) -> None:
        """Enable display drawing operations."""
        self._disabled = False
        log.debug("Display enabled")
    
    def disable(self) -> None:
        """Disable display drawing operations."""
        self._disabled = True
        self.state = DisplayState.DISABLED
        log.debug("Display disabled")
    
    def set_update_mode(self, mode: UpdateMode) -> None:
        """
        Set the display update mode.
        
        Args:
            mode: UpdateMode.PARTIAL or UpdateMode.FULL
        """
        self._update_mode = mode
        log.debug(f"Display update mode set to: {mode.name}")
    
    def quick_clear(self) -> None:
        """Quick clear assuming screen is in partial mode."""
        try:
            self.driver.clear()
        except Exception as e:
            log.error(f"Error in quick clear: {e}")


# Create singleton instance
display_manager = DisplayManager()

