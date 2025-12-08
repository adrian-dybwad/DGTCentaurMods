"""
Button menu for the DGT Centaur board.

Provides a main menu with large icon buttons for:
- Centaur (original DGT software, if available)
- Universal (BLE relay mode)
- Settings

Uses the IconMenuWidget from the epaper framework for reusable
menu functionality with keyboard navigation.
"""

from DGTCentaurMods.epaper import IconMenuWidget, IconMenuEntry, SplashScreen
from DGTCentaurMods.epaper.status_bar import STATUS_BAR_HEIGHT
from typing import Optional, List
import os

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# Display dimensions
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 296

# Path to original DGT Centaur software
CENTAUR_SOFTWARE = "/home/pi/centaur/centaur"

# Global references for menu management
_active_menu_widget: Optional[IconMenuWidget] = None
_display_manager = None


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


def _shutdown(message, reboot=False):
    """Shutdown the system with a message displayed on screen."""
    from DGTCentaurMods.board import board
    
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


def create_main_menu_entries(centaur_available: bool = True) -> List[IconMenuEntry]:
    """Create the standard main menu entry configuration.
    
    Args:
        centaur_available: Whether DGT Centaur software is available
        
    Returns:
        List of IconMenuEntry for main menu
    """
    entries = []
    
    if centaur_available:
        entries.append(IconMenuEntry(
            key="Centaur",
            label="Centaur",
            icon_name="centaur",
            enabled=True
        ))
    
    entries.append(IconMenuEntry(
        key="Universal",
        label="Universal",
        icon_name="universal",
        enabled=True
    ))
    
    entries.append(IconMenuEntry(
        key="Settings",
        label="Settings",
        icon_name="settings",
        enabled=True
    ))
    
    return entries


def create_settings_entries() -> List[IconMenuEntry]:
    """Create entries for the settings submenu.
    
    Returns:
        List of IconMenuEntry for settings menu
    """
    return [
        IconMenuEntry(key="Sound", label="Sound", icon_name="sound", enabled=True),
        IconMenuEntry(key="Shutdown", label="Shutdown", icon_name="shutdown", enabled=True),
        IconMenuEntry(key="Reboot", label="Reboot", icon_name="reboot", enabled=True),
    ]


def _show_icon_menu(entries: List[IconMenuEntry]) -> str:
    """Display an icon menu and wait for selection.
    
    Args:
        entries: List of menu entry configurations to display
    
    Returns:
        Selected entry key, "BACK", "HELP", or "SHUTDOWN"
    """
    global _display_manager, _active_menu_widget
    
    # Clear existing widgets and add fresh status bar
    _display_manager.clear_widgets()
    
    # Create menu widget
    menu_widget = IconMenuWidget(
        x=0,
        y=STATUS_BAR_HEIGHT,
        width=DISPLAY_WIDTH,
        height=DISPLAY_HEIGHT - STATUS_BAR_HEIGHT,
        entries=entries,
        selected_index=0
    )
    
    # Register as active menu for key routing
    _active_menu_widget = menu_widget
    menu_widget.activate()
    
    # Add widget to display
    _display_manager.add_widget(menu_widget)
    
    try:
        # Wait for selection using the widget's blocking method
        result = menu_widget.wait_for_selection(initial_index=0)
        return result
    finally:
        _active_menu_widget = None


def _run_centaur():
    """Launch the original DGT Centaur software.
    
    This hands over control to the Centaur software and exits.
    """
    import sys
    import time
    from DGTCentaurMods.board import board
    
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
    
    Runs universal.py as a subprocess.
    """
    import sys
    import pathlib
    import subprocess
    import signal
    import time
    from DGTCentaurMods.board import board
    
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
        entries = create_settings_entries()
        result = _show_icon_menu(entries)
        
        if result == "BACK":
            return
        
        if result == "SHUTDOWN":
            _shutdown("     Shutdown")
            return
        
        if result == "Sound":
            # Sound toggle submenu
            sound_entries = [
                IconMenuEntry(key="On", label="On", icon_name="sound", enabled=True),
                IconMenuEntry(key="Off", label="Off", icon_name="cancel", enabled=True),
            ]
            sound_result = _show_icon_menu(sound_entries)
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
    
    Displays the main menu with large icon buttons and handles:
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
    
    # Send initialization commands
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
            # Create main menu entries
            entries = create_main_menu_entries(centaur_available=centaur_available)
            
            # Show main menu and get selection
            result = _show_icon_menu(entries)
            
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
            
            if result == "SHUTDOWN":
                _shutdown("     Shutdown")
            
            elif result == "Centaur":
                _run_centaur()
                # Note: _run_centaur() exits the process
            
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
