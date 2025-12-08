"""
Button menu widget with large buttons and icons for e-paper display.

Provides a main menu with large, touch-friendly buttons for:
- Centaur (original DGT software, if available)
- Universal (BLE relay mode)
- Settings

Each button has an icon and label, designed for easy visibility
on the small e-paper display.
"""

from PIL import Image, ImageDraw, ImageFont
from DGTCentaurMods.epaper.framework.widget import Widget
from DGTCentaurMods.epaper.status_bar import STATUS_BAR_HEIGHT
from typing import Optional, Callable, List
from dataclasses import dataclass
import threading
import os

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

try:
    from DGTCentaurMods.asset_manager import AssetManager
except ImportError:
    AssetManager = None


# Display dimensions
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 296

# Button layout constants
BUTTON_HEIGHT = 70  # Height per button
BUTTON_MARGIN = 4   # Margin between buttons
BUTTON_PADDING = 6  # Internal padding
ICON_SIZE = 36      # Icon size in pixels
LABEL_HEIGHT = 18   # Height reserved for label text


@dataclass
class ButtonConfig:
    """Configuration for a menu button."""
    key: str          # Unique identifier returned on selection
    label: str        # Display text
    icon_name: str    # Icon identifier for rendering
    enabled: bool = True  # Whether button is enabled/visible


class ButtonMenuWidget(Widget):
    """Widget displaying large buttons with icons for menu selection.
    
    Displays a vertical list of large buttons, each with an icon and label.
    Navigation uses UP/DOWN keys, selection with TICK, back with BACK.
    
    Attributes:
        buttons: List of button configurations
        selected_index: Currently highlighted button index
    """
    
    def __init__(self, x: int, y: int, width: int, height: int,
                 buttons: List[ButtonConfig],
                 selected_index: int = 0,
                 register_callback: Optional[Callable[['ButtonMenuWidget'], None]] = None,
                 unregister_callback: Optional[Callable[[], None]] = None):
        """Initialize button menu widget.
        
        Args:
            x: X position of widget
            y: Y position of widget (absolute screen position)
            width: Widget width
            height: Widget height
            buttons: List of button configurations
            selected_index: Initial selected button index
            register_callback: Called with self when widget becomes active
            unregister_callback: Called when widget becomes inactive
        """
        super().__init__(x, y, width, height)
        self.buttons = [b for b in buttons if b.enabled]  # Filter disabled buttons
        self.selected_index = min(selected_index, max(0, len(self.buttons) - 1))
        self._register_callback = register_callback
        self._unregister_callback = unregister_callback
        
        # Selection event handling
        self._selection_event = threading.Event()
        self._selection_result: Optional[str] = None
        self._active = False
        
        # Load font
        self._font = None
        self._load_resources()
        
        log.info(f"ButtonMenuWidget: Created with {len(self.buttons)} buttons")
    
    def _load_resources(self):
        """Load fonts for rendering."""
        try:
            if AssetManager:
                self._font = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 16)
            else:
                self._font = ImageFont.load_default()
        except Exception as e:
            log.error(f"Failed to load font: {e}")
            self._font = ImageFont.load_default()
    
    def _draw_icon(self, draw: ImageDraw.Draw, icon_name: str, 
                   x: int, y: int, size: int, selected: bool):
        """Draw an icon at the specified position.
        
        Icons are drawn using simple PIL drawing primitives for e-paper
        compatibility and file independence.
        
        Args:
            draw: ImageDraw object
            icon_name: Icon identifier
            x: X position (center of icon)
            y: Y position (center of icon)
            size: Icon size in pixels
            selected: Whether this icon is in a selected button
        """
        half = size // 2
        left = x - half
        top = y - half
        right = x + half
        bottom = y + half
        
        # Line color (black for normal, white for selected)
        line_color = 255 if selected else 0
        
        if icon_name == "centaur":
            # Chess knight icon - simplified horse head silhouette
            # Head shape
            points = [
                (left + 4, bottom),           # Bottom left
                (left + 4, top + size//3),    # Left side up
                (left + 8, top + 4),          # Muzzle
                (left + size//2, top + 2),    # Top of head
                (right - 4, top + 6),         # Ear area
                (right - 2, top + size//3),   # Right side
                (right - 4, bottom),          # Bottom right
            ]
            draw.polygon(points, outline=line_color, fill=None)
            # Eye
            draw.ellipse([x - 2, y - 6, x + 2, y - 2], outline=line_color)
            # Mane lines
            draw.line([(left + size//3, top + 4), (left + size//3, top + 14)], fill=line_color, width=1)
            draw.line([(x, top + 2), (x, top + 12)], fill=line_color, width=1)
            
        elif icon_name == "universal":
            # Bluetooth-like connectivity icon
            center_x = x
            center_y = y
            
            # Central vertical line
            draw.line([(center_x, top + 4), (center_x, bottom - 4)], fill=line_color, width=2)
            
            # Top arrow (pointing right-up)
            draw.line([(center_x, top + 4), (right - 6, y - 4)], fill=line_color, width=2)
            draw.line([(right - 6, y - 4), (center_x, y)], fill=line_color, width=2)
            
            # Bottom arrow (pointing right-down)
            draw.line([(center_x, bottom - 4), (right - 6, y + 4)], fill=line_color, width=2)
            draw.line([(right - 6, y + 4), (center_x, y)], fill=line_color, width=2)
            
            # Radio waves on left
            draw.arc([left, y - 8, left + 12, y + 8], 120, 240, fill=line_color, width=1)
            draw.arc([left - 4, y - 12, left + 16, y + 12], 120, 240, fill=line_color, width=1)
            
        elif icon_name == "settings":
            # Gear/cog icon
            center_x = x
            center_y = y
            outer_r = half - 2
            inner_r = half // 2
            
            # Draw outer circle
            draw.ellipse([center_x - outer_r, center_y - outer_r, 
                         center_x + outer_r, center_y + outer_r], 
                        outline=line_color, width=2)
            
            # Draw inner circle
            draw.ellipse([center_x - inner_r, center_y - inner_r,
                         center_x + inner_r, center_y + inner_r],
                        outline=line_color, width=2)
            
            # Draw gear teeth (8 teeth)
            import math
            tooth_len = 6
            for i in range(8):
                angle = i * (360 / 8) * (math.pi / 180)
                # Inner point
                ix = center_x + int(outer_r * math.cos(angle))
                iy = center_y + int(outer_r * math.sin(angle))
                # Outer point
                ox = center_x + int((outer_r + tooth_len) * math.cos(angle))
                oy = center_y + int((outer_r + tooth_len) * math.sin(angle))
                draw.line([(ix, iy), (ox, oy)], fill=line_color, width=2)
        
        else:
            # Default: simple square placeholder
            draw.rectangle([left + 4, top + 4, right - 4, bottom - 4], 
                          outline=line_color, width=2)
    
    def render(self) -> Image.Image:
        """Render the button menu.
        
        Returns:
            PIL Image with rendered buttons
        """
        img = Image.new("1", (self.width, self.height), 255)  # White background
        draw = ImageDraw.Draw(img)
        
        # Calculate button positions
        total_buttons = len(self.buttons)
        available_height = self.height - (BUTTON_MARGIN * (total_buttons + 1))
        button_height = min(BUTTON_HEIGHT, available_height // total_buttons)
        
        for idx, button in enumerate(self.buttons):
            is_selected = (idx == self.selected_index)
            
            # Calculate button bounds
            button_y = BUTTON_MARGIN + idx * (button_height + BUTTON_MARGIN)
            button_left = BUTTON_MARGIN
            button_right = self.width - BUTTON_MARGIN
            button_bottom = button_y + button_height
            
            # Draw button background
            if is_selected:
                # Selected: filled black rectangle with white text
                draw.rectangle([button_left, button_y, button_right, button_bottom],
                              fill=0, outline=0)
            else:
                # Unselected: white with black border
                draw.rectangle([button_left, button_y, button_right, button_bottom],
                              fill=255, outline=0, width=2)
            
            # Draw icon
            icon_x = button_left + BUTTON_PADDING + ICON_SIZE // 2
            icon_y = button_y + (button_height - LABEL_HEIGHT) // 2
            self._draw_icon(draw, button.icon_name, icon_x, icon_y, ICON_SIZE, is_selected)
            
            # Draw label
            text_x = icon_x + ICON_SIZE // 2 + BUTTON_PADDING
            text_y = button_y + button_height - LABEL_HEIGHT - 4
            text_color = 255 if is_selected else 0
            draw.text((text_x, text_y), button.label, font=self._font, fill=text_color)
        
        return img
    
    def set_selection(self, index: int) -> None:
        """Set the current selection index.
        
        Args:
            index: New selection index
        """
        new_index = max(0, min(index, len(self.buttons) - 1))
        if new_index != self.selected_index:
            self.selected_index = new_index
            self._last_rendered = None
            self.request_update(full=False)
    
    def handle_key(self, key_id) -> bool:
        """Handle key press events.
        
        Args:
            key_id: Key identifier from board
            
        Returns:
            True if key was handled, False otherwise
        """
        if not self._active:
            return False
        
        # Import Key enum for comparison
        try:
            from DGTCentaurMods.board import board
            Key = board.Key
        except ImportError:
            return False
        
        if key_id == Key.UP:
            # Wrap around: if at top, go to bottom
            if self.selected_index > 0:
                self.set_selection(self.selected_index - 1)
            else:
                self.set_selection(len(self.buttons) - 1)
            return True
            
        elif key_id == Key.DOWN:
            # Wrap around: if at bottom, go to top
            if self.selected_index < len(self.buttons) - 1:
                self.set_selection(self.selected_index + 1)
            else:
                self.set_selection(0)
            return True
            
        elif key_id == Key.TICK:
            # Selection confirmed
            if self.buttons:
                self._selection_result = self.buttons[self.selected_index].key
            else:
                self._selection_result = "BACK"
            self._selection_event.set()
            return True
            
        elif key_id == Key.BACK:
            self._selection_result = "BACK"
            self._selection_event.set()
            return True
            
        elif key_id == Key.HELP:
            self._selection_result = "HELP"
            self._selection_event.set()
            return True
        
        return False
    
    def wait_for_selection(self, initial_index: int = 0) -> str:
        """Block and wait for user selection via key presses.
        
        Args:
            initial_index: Initial selection index
            
        Returns:
            Selected button key, "BACK", or "HELP"
        """
        # Set initial selection
        self.set_selection(initial_index)
        
        # Activate key handling
        self._active = True
        self._selection_result = None
        self._selection_event.clear()
        
        # Register this widget as active
        if self._register_callback:
            try:
                self._register_callback(self)
                log.info(f"ButtonMenuWidget: Registered as active, initial_index={initial_index}")
            except Exception as e:
                log.error(f"Error registering button menu widget: {e}")
        
        try:
            # Wait for selection event
            log.info("ButtonMenuWidget: Waiting for selection...")
            self._selection_event.wait()
            result = self._selection_result or "BACK"
            log.info(f"ButtonMenuWidget: Selection result='{result}'")
            return result
        finally:
            self._active = False
            if self._unregister_callback:
                try:
                    self._unregister_callback()
                except Exception as e:
                    log.error(f"Error unregistering button menu widget: {e}")
    
    def stop(self) -> None:
        """Stop the widget and release any blocked waits."""
        self._active = False
        self._selection_result = "BACK"
        self._selection_event.set()
        super().stop()


def create_main_menu_buttons(centaur_available: bool = True) -> List[ButtonConfig]:
    """Create the standard main menu button configuration.
    
    Args:
        centaur_available: Whether DGT Centaur software is available
        
    Returns:
        List of ButtonConfig for main menu
    """
    buttons = []
    
    if centaur_available:
        buttons.append(ButtonConfig(
            key="Centaur",
            label="Centaur",
            icon_name="centaur",
            enabled=True
        ))
    
    buttons.append(ButtonConfig(
        key="Universal",
        label="Universal",
        icon_name="universal",
        enabled=True
    ))
    
    buttons.append(ButtonConfig(
        key="Settings",
        label="Settings",
        icon_name="settings",
        enabled=True
    ))
    
    return buttons


def create_settings_buttons() -> List[ButtonConfig]:
    """Create buttons for the settings submenu.
    
    Returns:
        List of ButtonConfig for settings menu
    """
    return [
        ButtonConfig(key="Sound", label="Sound", icon_name="settings", enabled=True),
        ButtonConfig(key="Shutdown", label="Shutdown", icon_name="settings", enabled=True),
        ButtonConfig(key="Reboot", label="Reboot", icon_name="settings", enabled=True),
    ]


# Global references for menu management
_active_menu_widget: Optional[ButtonMenuWidget] = None
_display_manager = None

CENTAUR_SOFTWARE = "/home/pi/centaur/centaur"


def _key_callback(key_id):
    """Handle key press events from the board.
    
    Routes key events to the active menu widget.
    """
    global _active_menu_widget
    
    if _active_menu_widget is not None:
        handled = _active_menu_widget.handle_key(key_id)
        if handled:
            return
    
    # Handle LONG_PLAY for shutdown from anywhere
    from DGTCentaurMods.board import board
    if key_id == board.Key.LONG_PLAY:
        _shutdown("Long Press Shutdown")


def _field_callback(piece_event, field, time_in_seconds):
    """Handle piece movement events (not used in menu)."""
    pass


def _register_menu(widget):
    """Register a menu widget as active."""
    global _active_menu_widget
    _active_menu_widget = widget


def _unregister_menu():
    """Unregister the active menu widget."""
    global _active_menu_widget
    _active_menu_widget = None


def _shutdown(message, reboot=False):
    """Shutdown the system with a message displayed on screen."""
    from DGTCentaurMods.board import board
    from DGTCentaurMods.epaper import SplashScreen
    
    global _display_manager
    
    if _display_manager:
        _display_manager.clear_widgets(addStatusBar=False)
        promise = _display_manager.add_widget(SplashScreen(message=message))
        if promise:
            try:
                promise.result(timeout=10.0)
            except Exception:
                pass
    
    board.shutdown(reboot=reboot)


def _show_button_menu(buttons: List[ButtonConfig], title: str = None) -> str:
    """Display a button menu and wait for selection.
    
    Args:
        buttons: List of button configurations to display
        title: Optional title (not currently used in ButtonMenuWidget)
    
    Returns:
        Selected button key, "BACK", or "HELP"
    """
    global _display_manager, _active_menu_widget
    
    # Clear existing widgets and add fresh status bar
    _display_manager.clear_widgets()
    
    # Create button menu widget
    menu_widget = ButtonMenuWidget(
        x=0,
        y=STATUS_BAR_HEIGHT,
        width=DISPLAY_WIDTH,
        height=DISPLAY_HEIGHT - STATUS_BAR_HEIGHT,
        buttons=buttons,
        selected_index=0,
        register_callback=_register_menu,
        unregister_callback=_unregister_menu
    )
    
    # Add widget to display
    _display_manager.add_widget(menu_widget)
    
    # Wait for selection using the widget's blocking method
    result = menu_widget.wait_for_selection(initial_index=0)
    
    return result


def _run_centaur():
    """Launch the original DGT Centaur software.
    
    This hands over control to the Centaur software and exits.
    Same behavior as menu.py's Centaur option.
    """
    import sys
    import time
    from DGTCentaurMods.board import board
    from DGTCentaurMods.epaper import SplashScreen
    
    global _display_manager
    
    # Show loading screen
    _display_manager.clear_widgets(addStatusBar=False)
    promise = _display_manager.add_widget(SplashScreen(message="     Loading"))
    if promise:
        try:
            promise.result(timeout=10.0)
        except Exception:
            pass
    
    # Pause events and cleanup
    board.pauseEvents()
    board.cleanup(leds_off=True)
    time.sleep(1)
    
    if os.path.exists(CENTAUR_SOFTWARE):
        # Ensure file is executable
        try:
            os.chmod(CENTAUR_SOFTWARE, 0o755)
        except Exception as e:
            log.warning(f"Could not set execute permissions on centaur: {e}")
        
        # Change to centaur directory and run
        os.chdir("/home/pi/centaur")
        os.system("sudo ./centaur")
    else:
        log.error(f"Centaur executable not found at {CENTAUR_SOFTWARE}")
        return False
    
    # Once Centaur starts, we cannot return - stop the service and exit
    time.sleep(3)
    os.system("sudo systemctl stop DGTCentaurMods.service")
    sys.exit()


def _run_universal():
    """Run the Universal BLE relay script.
    
    Runs universal.py as a subprocess, similar to how menu.py runs external scripts.
    """
    import sys
    import pathlib
    import subprocess
    import signal
    import time
    from DGTCentaurMods.board import board
    from DGTCentaurMods.epaper import SplashScreen
    
    global _display_manager
    
    process = None
    interrupted = False
    
    def signal_handler(signum, frame):
        """Handle Ctrl+C by terminating the subprocess."""
        nonlocal process, interrupted
        if interrupted:
            if process is not None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
            os._exit(130)
            return
        
        interrupted = True
        if process is not None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except Exception:
                try:
                    process.terminate()
                except Exception:
                    pass
    
    original_handler = signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Show loading screen
        _display_manager.clear_widgets(addStatusBar=False)
        promise = _display_manager.add_widget(SplashScreen(message="     Loading"))
        if promise:
            try:
                promise.result(timeout=10.0)
            except Exception:
                pass
        
        board.pauseEvents()
        board.cleanup(leds_off=True)
        
        # Path to universal.py
        script_path = str((pathlib.Path(__file__).parent / "universal.py").resolve())
        log.info(f"Running universal.py: {script_path}")
        
        cmd = [sys.executable, script_path]
        
        # Start process in its own process group
        process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        
        try:
            result = process.wait()
            return result
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt caught, subprocess should already be terminated")
            if process is not None:
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
            return 130
    finally:
        signal.signal(signal.SIGINT, original_handler)
        log.info("Reinitializing after universal.py...")
        
        # Reinitialize display
        promise = board.init_display()
        if promise:
            try:
                promise.result(timeout=10.0)
            except Exception as e:
                log.warning(f"Error initializing display: {e}")
        
        # Restart board communication
        board.run_background(start_key_polling=True)
        board.unPauseEvents()


def _handle_settings():
    """Handle the Settings submenu.
    
    Displays settings options and handles their selection.
    """
    from DGTCentaurMods.board import board, centaur
    import time
    
    global _display_manager
    
    while True:
        buttons = create_settings_buttons()
        result = _show_button_menu(buttons, "Settings")
        
        if result == "BACK":
            return
        
        if result == "Sound":
            # Sound toggle submenu
            sound_buttons = [
                ButtonConfig(key="On", label="On", icon_name="settings", enabled=True),
                ButtonConfig(key="Off", label="Off", icon_name="settings", enabled=True),
            ]
            sound_result = _show_button_menu(sound_buttons, "Sound")
            if sound_result == "On":
                centaur.set_sound("on")
                board.beep(board.SOUND_GENERAL)
            elif sound_result == "Off":
                centaur.set_sound("off")
        
        elif result == "Shutdown":
            _shutdown("     Shutdown")
        
        elif result == "Reboot":
            # LED cascade pattern for reboot
            try:
                for i in range(0, 8):
                    board.led(i, repeat=0)
                    time.sleep(0.2)
            except Exception:
                pass
            _shutdown("     Rebooting", reboot=True)


if __name__ == "__main__":
    """Entry point for running button_menu as a standalone module.
    
    Usage: python -m DGTCentaurMods.button_menu
    
    Displays the main menu with large buttons and handles:
    - Centaur: Launches the original DGT Centaur software
    - Universal: Runs the BLE relay mode (universal.py)
    - Settings: Opens settings submenu (Sound, Shutdown, Reboot)
    
    Navigation:
    - UP/DOWN: Move selection
    - TICK: Confirm selection
    - BACK: Go back / exit
    - LONG_PLAY: Shutdown
    """
    import sys
    from DGTCentaurMods.board import board
    from DGTCentaurMods.board.sync_centaur import command
    from DGTCentaurMods.epaper import SplashScreen
    
    # Initialize display
    promise = board.init_display()
    if promise:
        try:
            promise.result(timeout=10.0)
        except Exception as e:
            log.warning(f"Error initializing display: {e}")
    
    _display_manager = board.display_manager
    
    # Subscribe to board events
    board.subscribeEvents(_key_callback, _field_callback, timeout=900)
    
    # Send initialization commands (same as menu.py)
    board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F4)
    board.sendCommand(command.DGT_BUS_SEND_96)
    board.sendCommand(command.DGT_BUS_SEND_STATE)
    board.sendCommand(command.DGT_BUS_SEND_CHANGES)
    board.sendCommand(command.DGT_BUS_POLL_KEYS)
    
    # Check if Centaur software is available
    centaur_available = os.path.exists(CENTAUR_SOFTWARE)
    
    log.info("Button menu started")
    
    try:
        while True:
            # Create main menu buttons
            buttons = create_main_menu_buttons(centaur_available=centaur_available)
            
            # Show main menu and get selection
            result = _show_button_menu(buttons, "Main Menu")
            
            log.info(f"Main menu selection: {result}")
            
            if result == "BACK":
                # Show welcome/idle screen and wait for TICK
                board.beep(board.SOUND_POWER_OFF)
                _display_manager.clear_widgets()
                promise = _display_manager.add_widget(SplashScreen(message="   Press [OK]"))
                if promise:
                    try:
                        promise.result(timeout=10.0)
                    except Exception:
                        pass
                # Wait for TICK to return to menu
                board.wait_for_key_up(accept=board.Key.TICK)
                continue
            
            if result == "Centaur":
                _run_centaur()
                # Note: _run_centaur() exits the process, so we won't reach here
            
            elif result == "Universal":
                _run_universal()
                # After universal.py exits, continue to main menu
            
            elif result == "Settings":
                _handle_settings()
                # After settings, continue to main menu
            
            elif result == "HELP":
                # Could show about/help screen here
                pass
                
    except KeyboardInterrupt:
        log.info("Button menu interrupted by Ctrl+C")
    finally:
        try:
            board.cleanup(leds_off=True)
            board.pauseEvents()
        except Exception:
            pass
        
        if _display_manager:
            try:
                _display_manager.shutdown()
            except Exception:
                pass
