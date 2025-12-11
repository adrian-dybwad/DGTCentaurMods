# DGT Centaur board control functions
#
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

#import serial
from DGTCentaurMods.epaper import Manager, SplashScreen
from DGTCentaurMods.board.async_centaur import AsyncCentaur, command, Key
from DGTCentaurMods.board.sync_centaur import SyncCentaur, command, Key
import sys
import os
from DGTCentaurMods.board.settings import Settings
from DGTCentaurMods.board import centaur
import time
from typing import Optional
from concurrent.futures import Future

from DGTCentaurMods.board.logging import log, logging

# Battery related - move to battery widget
chargerconnected = 0
batterylevel = -1
batterylastchecked = 0

# Board meta properties (extracted from DGT_SEND_TRADEMARK response)
board_meta_properties: Optional[dict] = None

#_get_display_manager()  # Initialize display

# Global display manager
display_manager: Optional[Manager] = None

def init_display() -> Future:
    """Get or create the global display manager."""
    global display_manager
    
    if display_manager is None:
        display_manager = Manager()
        return display_manager.initialize()
    return None


# Re-export commonly used command names for backward-compatible usage in this module
SOUND_GENERAL = command.SOUND_GENERAL
SOUND_FACTORY = command.SOUND_FACTORY
SOUND_POWER_OFF = command.SOUND_POWER_OFF
SOUND_POWER_ON = command.SOUND_POWER_ON
SOUND_WRONG = command.SOUND_WRONG
SOUND_WRONG_MOVE = command.SOUND_WRONG_MOVE

command_name = command

# Get the config
dev = Settings.read('system', 'developer', 'False')

# Board initialization with retry logic
# If the board fails to initialize, we retry up to MAX_INIT_RETRIES times
MAX_INIT_RETRIES = 3
INIT_TIMEOUT_SECONDS = 10  # Shorter timeout per attempt for faster retry

controller = None

# Import init callback module for status updates during initialization
from DGTCentaurMods.board import init_callback


def _create_controller():
    """Create a new SyncCentaur controller instance."""
    return SyncCentaur(developer_mode=False)


def _init_board_with_retry():
    """Initialize the board controller with retry logic.
    
    If the board fails to initialize within the timeout, the controller is
    cleaned up and a new one is created. This handles cases where the board
    communication hangs during discovery.
    
    Returns:
        SyncCentaur: The initialized controller
    """
    global controller
    
    for attempt in range(1, MAX_INIT_RETRIES + 1):
        log.info(f"[board] Initializing board controller (attempt {attempt}/{MAX_INIT_RETRIES})...")
        
        # Update status callback if provided
        if attempt == 1:
            init_callback.notify("Board init...")
        else:
            init_callback.notify(f"Board retry {attempt}...")
        
        # Create new controller if needed
        if controller is None:
            controller = _create_controller()
        
        # Wait for board to become ready with timeout
        ready = controller.wait_ready(timeout=INIT_TIMEOUT_SECONDS)
        
        if ready:
            log.info(f"[board] Board initialized successfully on attempt {attempt}")
            return controller
        
        # Initialization failed - cleanup and retry
        log.warning(f"[board] Board initialization timed out on attempt {attempt}/{MAX_INIT_RETRIES}")
        
        if attempt < MAX_INIT_RETRIES:
            log.info("[board] Cleaning up and retrying...")
            try:
                controller.cleanup(leds_off=False)
            except Exception as e:
                log.debug(f"[board] Error during cleanup: {e}")
            controller = None
            time.sleep(0.5)  # Brief pause before retry
    
    # All retries exhausted - log error but continue with last controller
    log.error(f"[board] Board initialization failed after {MAX_INIT_RETRIES} attempts")
    log.warning("[board] Continuing with potentially uninitialized board - functionality may be limited")
    return controller


# Initialize the controller with retry logic
controller = _init_board_with_retry()

# But the address might not be that :( Here we send an initial 0x4d to ask the board to provide its address

def _extract_and_store_board_meta():
    """
    Extract and store board meta properties when board becomes ready.
    Sets global board_meta_properties dictionary.
    """
    global board_meta_properties
    
    if board_meta_properties is not None:
        # Already extracted
        return
    
    if controller is None or not controller.ready:
        log.warning("[board._extract_and_store_board_meta] Controller not ready, skipping metadata extraction")
        return
    
    _board_meta = controller.request_response(command.DGT_SEND_TRADEMARK)

    if _board_meta is None:
        log.warning("[board._extract_and_store_board_meta] Failed to get board metadata")
        return

    log.info(f"[board._extract_and_store_board_meta] Board metadata: {' '.join(f'{b:02x}' for b in _board_meta)}")
    
    # Decode bytes to string
    try:
        meta_text = _board_meta.decode('utf-8', errors='ignore')
    except (AttributeError, UnicodeDecodeError):
        log.error("[board._extract_and_store_board_meta] Failed to decode board metadata")
        return
    log.info(f"[board._extract_and_store_board_meta] Board metadata: {meta_text}")
    # Split into lines
    lines = [line.strip() for line in meta_text.strip().split('\n') if line.strip()]
    
    # First two lines are trademark (tm)
    if len(lines) < 2:
        log.warning("[board._extract_and_store_board_meta] Board metadata has fewer than 2 lines")
        return
    
    # Initialize properties dictionary
    board_meta_properties = {}
    
    # Add first two lines as 'tm' property (join with newline)
    board_meta_properties['tm'] = '\n'.join(lines[:2])
    
    # Parse remaining lines as colon-separated key:value pairs
    # Lines can contain multiple key:value pairs separated by commas
    for line in lines[2:]:
        # Split by comma first to handle multiple key:value pairs per line
        parts = [part.strip() for part in line.split(',')]
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)  # Split on first colon only
                board_meta_properties[key.strip()] = value.strip()
            else:
                # Part without colon - store as key with empty value
                board_meta_properties[part] = ""
    
    log.debug(f"[board._extract_and_store_board_meta] Extracted {len(board_meta_properties)} properties")

def cleanup(leds_off: bool = True):
    controller.cleanup(leds_off=True)
    #display_manager.shutdown()
    #display_manager = None

def wait_for_key_up(timeout=None, accept=None):
    """Wait for a key up event from the board"""
    return controller.wait_for_key_up(timeout=timeout, accept=accept)


def run_background(start_key_polling=False):
    controller.run_background(start_key_polling=start_key_polling)
    
#
# Board control - functions related to making the board do something
#

def beep(beeptype):
    if centaur.get_sound() == "off":
        log.warning("Beep disabled")
        return
    # Ask the centaur to make a beep sound
    controller.beep(beeptype)

def ledsOff():
    # Switch the LEDs off on the centaur
    controller.ledsOff()

def ledArray(inarray, speed = 3, intensity=5, repeat=1):
    # Lights all the leds in the given inarray with the given speed and intensity
    inarray = list[int](inarray.copy())
    inarray.reverse()
    for i in range(0, len(inarray)):
        inarray[i] = rotateField(inarray[i])
    controller.ledArray(inarray, speed, intensity, repeat)

def ledFromTo(lfrom, lto, intensity=5, speed=3, repeat=1):
    # Light up a from and to LED for move indication
    # Note the call to this function is 0 for a1 and runs to 63 for h8
    # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
    controller.ledFromTo(rotateField(lfrom), rotateField(lto), intensity, speed, repeat)

def led(num, intensity=5, speed=3, repeat=1):
    # Flashes a specific led
    # Note the call to this function is 0 for a1 and runs to 63 for h8
    # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
    controller.led(rotateField(num), intensity, speed, repeat)

def ledFlash(speed=3, repeat=1, intensity=5):
    # Flashes the last led lit by led(num) above
    controller.ledFlash(speed, repeat, intensity)

def sendCustomBeep(data: bytes):
    """
    Send a custom beep pattern using SOUND_GENERAL command.
    
    Args:
        data: Custom beep pattern bytes (e.g., b'\x50\x08\x00\x08\x59\x08\x00')
    """
    controller.sendCommand(command.SOUND_GENERAL, data)

def sendCustomLedArray(data: bytes):
    """
    Send a custom LED array command using LED_CMD.
    
    Args:
        data: Custom LED array data bytes (e.g., b'\x05\x12\x00\x05' followed by square indices)
    """
    controller.sendCommand(command.LED_CMD, data)

def shutdown_countdown(countdown_seconds: int = 3) -> bool:
    """
    Display a shutdown countdown with option to cancel.
    
    Shows a modal splash screen counting down from countdown_seconds to 0.
    The modal widget takes over the display, ignoring all other widgets.
    User can press BACK button to cancel the shutdown.
    
    Args:
        countdown_seconds: Number of seconds to count down (default 5)
    
    Returns:
        True if countdown completed (proceed with shutdown)
        False if user cancelled (pressed BACK)
    """
    global display_manager
    
    log.info(f"[board.shutdown_countdown] Starting {countdown_seconds}s countdown")
    beep(SOUND_POWER_OFF)
    
    # Create countdown splash (SplashScreen is modal - only it will be rendered)
    countdown_splash = None
    try:
        if display_manager is not None:
            # U+25C0 is left-pointing triangle for BACK button
            countdown_splash = SplashScreen(message=f"Shutdown in\n  {countdown_seconds}")
            display_manager.add_widget(countdown_splash)
    except Exception as e:
        log.debug(f"Failed to show countdown splash: {e}")
    
    # Drain any pending key events before starting countdown
    while controller.get_next_key(timeout=0.0) is not None:
        pass
    
    # Countdown loop - releasing PLAY button (PLAY key-up) cancels
    for remaining in range(countdown_seconds, 0, -1):
        # Update display
        try:
            if countdown_splash is not None:
                countdown_splash.set_message(f"Shutdown in\n  {remaining}")
        except Exception as e:
            log.debug(f"Failed to update countdown: {e}")
        
        # Wait 1 second, checking for PLAY release every 100ms
        for _ in range(10):
            time.sleep(0.1)
            key = controller.get_next_key(timeout=0.0)
            if key == Key.PLAY:
                # PLAY key-up means button was released - cancel shutdown
                log.info("[board.shutdown_countdown] Cancelled (PLAY released)")
                beep(SOUND_GENERAL)
                # Remove modal widget to restore normal widget rendering
                try:
                    if display_manager is not None and countdown_splash is not None:
                        display_manager.remove_widget(countdown_splash)
                except Exception:
                    pass
                return False
    
    log.info("[board.shutdown_countdown] Countdown complete, proceeding with shutdown")
    # Don't remove countdown splash here - shutdown() will add its own modal splash
    # which automatically replaces this one, avoiding a flash of the previous UI
    return True


def shutdown(reboot=False, reason="unspecified"):
    """
    Shutdown the Raspberry Pi with proper cleanup and visual feedback.
    
    Args:
        reboot: If True, reboot instead of poweroff.
        reason: Human-readable reason for shutdown (for logging).
    
    If a pending update exists, installs it instead of shutting down.
    Otherwise performs clean shutdown with LED cascade pattern.
    
    Visual feedback:
    - Update install: All LEDs solid
    - Normal shutdown: Sequential LED cascade h8→h1
    - Splash screen with "Press advancement button to start" message
    """
    log.info("=" * 60)
    log.info(f"SHUTDOWN INITIATED - Reason: {reason}")
    log.info("=" * 60)

    beep(SOUND_POWER_OFF)
    
    # Display shutdown splash screen
    try:
        if display_manager is not None:
            # U+25B6 is the play triangle, U+23F8 is pause
            shutdown_splash = SplashScreen(message="Press [\u25b6]")
            display_manager.add_widget(shutdown_splash)
    except Exception as e:
        log.debug(f"Failed to show shutdown splash: {e}")
    
    # Pause events and cleanup board
    pauseEvents()
    cleanup(leds_off=False)  # LEDs handled by shutdown()
                
    update = centaur.UpdateSystem()
    package = '/tmp/dgtcentaurmods_armhf.deb'
    
    # Check for pending update
    if os.path.exists(package):
        log.debug('Update package found - installing instead of shutdown')
        beep(SOUND_POWER_OFF)
        widgets.clear_screen()
        widgets.write_text(3, "   Installing")
        widgets.write_text(4, "     update")
        
        # All LEDs for update install
        try:
            ledArray([0,1,2,3,4,5,6,7], intensity=6, repeat=0)
        except Exception:
            pass
        
        time.sleep(2)
        update.updateInstall()
        return
    
    # Normal shutdown sequence
    log.info('Normal shutdown sequence starting')
    
    # Beep power off sound
    try:
        beep(SOUND_POWER_OFF)
    except Exception:
        pass
    
    # LED cascade pattern h8→h1 (squares 7 down to 0)
    try:
        for i in range(7, -1, -1):
            led(i, repeat=1)
            time.sleep(0.2)

    except Exception as e:
        log.error(f"LED pattern failed during shutdown: {e}")
    
    # Send sleep to controller before system poweroff
    try:
        sleep_controller()
    except Exception as e:
        log.debug(f"Controller sleep failed: {e}")
    
    if display_manager is not None:
        display_manager.shutdown()

    if reboot:
        log.debug('Requesting system reboot via systemd')
        rc = os.system("sudo systemctl reboot")
        if rc != 0:
            log.error(f"sudo systemctl reboot failed with rc={rc}")
        return
    
    # Execute system poweroff via systemd (ensures shutdown hooks run as root)
    log.debug('Requesting system poweroff via systemd')
    rc = os.system("sudo systemctl poweroff")
    if rc != 0:
        log.error(f"sudo systemctl poweroff failed with rc={rc}")


def sleep_controller():
    """
    Send sleep command to DGT Centaur controller.
    
    Called during system shutdown to properly power down the controller
    before the Raspberry Pi powers off. This prevents the controller
    from remaining powered when the Pi shuts down.
    
    Visual feedback: Single LED at h8 position (square 7)
    """
    log.debug("Sending sleep command to DGT Centaur controller")
    
    # Visual feedback - single LED at h8
    try:
        ledFromTo(7, 7, repeat=0)
    except Exception as e:
        log.debug(f"LED failed during controller sleep: {e}")
    
    # Send sleep command to controller
    try:
        sleep()
        log.debug("Controller sleep command sent successfully")
    except Exception as e:
        log.debug(f"Failed to send sleep command: {e}")


def sleep():
    """
    Sleep the controller.
    """
    controller.sleep()


#
# Board response - functions related to get something from the board
#
def getBoardState(max_retries=2, retry_delay=0.1):
    """
    Get the current board state from the DGT Centaur.
    
    Args:
        max_retries: Maximum number of retry attempts on timeout or checksum failure (default: 2)
        retry_delay: Delay in seconds between retries (default: 0.1)
    
    Returns:
        bytes: Raw board state data (64 bytes) or None if all attempts fail
        
    Note:
        Retries are performed on timeout or checksum failure. This ensures
        transient communication errors don't cause permanent failures.
    """
    for attempt in range(max_retries + 1):
        raw_boarddata = controller.request_response(command.DGT_BUS_SEND_STATE)
        if raw_boarddata is not None:
            return raw_boarddata
        # None can indicate timeout or checksum failure - retry in both cases
        if attempt < max_retries:
            log.warning(f"[board.getBoardState] Attempt {attempt + 1} failed (timeout or checksum failure), retrying in {retry_delay}s...")
            time.sleep(retry_delay)
        else:
            log.error(f"[board.getBoardState] All {max_retries + 1} attempts failed (timeout or checksum failure)")
    return None

def getMetaProperty(key: str):
    """
    Get a meta property value by key from the board metadata.
    
    Args:
        key: Property key to retrieve (e.g., 'serial no', 'software version', 'tm')
    
    Returns:
        str: Property value or None if key not found or properties not yet extracted
    """
    global board_meta_properties
    
    # Ensure properties are extracted if not already
    if board_meta_properties is None:
        _extract_and_store_board_meta()
    
    if board_meta_properties is None:
        log.warning(f"[board.getMetaProperty] Board meta properties not available for key: {key}")
        return None
    
    return board_meta_properties.get(key)

def getChessState(field=None):
   # Transform: raw index i maps to chess index
    # Raw order: 0=a8, 1=b8, ..., 63=h1
    # Chess order: 0=a1, 1=b1, ..., 63=h8
    # 
    # Raw index i: row = i//8, col = i%8
    # Chess index: row = 7 - (i//8), col = i%8
    board_data_raw = getBoardState()
    if board_data_raw is None:
        log.warning("[board.getChessState] getBoardState() returned None, likely due to timeout or queue full")
        return None
    
    try:
        board_data = list[int](board_data_raw)
    except (TypeError, ValueError) as e:
        log.error(f"[board.getChessState] Failed to convert board data to list: {e}, data type: {type(board_data_raw)}")
        return None
    
    chess_state = [0] * 64
    
    if len(board_data) != 64:
        log.error(f"[board.getChessState] Invalid board data length: {len(board_data)}, expected 64")
        return None
    
    for i in range(64):
        raw_row = i // 8
        raw_col = i % 8
        chess_row = 7 - raw_row  # Invert rows
        chess_col = raw_col      # Keep columns
        chess_idx = chess_row * 8 + chess_col
        chess_state[chess_idx] = board_data[i]
    if field is not None:
        return chess_state[field]
    return chess_state

def sendCommand(command):
    resp = controller.request_response(command)
    return resp

def printChessState(state = None, loglevel = logging.INFO):
    # Helper to display board state
    if state is None:
        state = getChessState()  # Use getChessState if available, or update to use transformed state
    if state is None:
        log.warning("[board.printChessState] Cannot print board state: getChessState() returned None (likely due to timeout or communication failure)")
        return
    line = "\n"
    # Display ranks from top (rank 8) to bottom (rank 1)
    # Chess coordinates: row 7 (56-63) = rank 8, row 0 (0-7) = rank 1
    for rank in range(7, -1, -1):  # Iterate from rank 8 (row 7) down to rank 1 (row 0)
        x = rank * 8  # Starting index for this rank
        line += "\r\n"
        for y in range(0, 8):
            line += " " + str(state[x + y]) if state[x + y] != 0 else " ."
    line += "\r\n\n"
    log.log(loglevel, line)

def getBatteryLevel():
    # batterylevel: a number 0 - 20 representing battery level of the board
    # 20 is fully charged. The board dies somewhere around a low of 1
    # Sending the board a packet starting with 152 gives battery info
    global batterylevel, chargerconnected, batterylastchecked
    resp = controller.request_response(command.DGT_SEND_BATTERY_INFO)
    batterylastchecked = time.time()
    val = resp[0]
    batterylevel = val & 0x1F
    chargerconnected = 1 if ((val >> 5) & 0x07) in (1, 2) else 0    
    return batterylevel, chargerconnected

#
# Helper functions - used by other functions or useful in manipulating board data
#

def rotateField(field):
    lrow = (field // 8)
    lcol = (field % 8)
    # Rotate rows for hardware coordinate system
    newField = (7 - lrow) * 8 + lcol
    return newField

def rotateFieldHex(fieldHex):
    squarerow = (fieldHex // 8)
    squarecol = (fieldHex % 8)
    # Rotate rows for hardware coordinate system
    field = (7 - squarerow) * 8 + squarecol
    return field

def dgt_to_chess(dgt_idx):
    """Convert DGT protocol index (0=h1 to 63=a8) to chess square index (0=a1 to 63=h8)"""
    dgt_row = dgt_idx // 8
    dgt_col = dgt_idx % 8
    chess_col = 7 - dgt_col  # Flip horizontally (DGT col 0=h, chess col 7=h)
    return dgt_row * 8 + chess_col


# This section is the start of a new way of working with the board functions where those functions are
# the board returning some kind of data
import threading
import subprocess
eventsthreadpointer = ""
eventsrunning = 1

def temp():
    '''
    Get CPU temperature
    '''
    # Use subprocess.run for proper resource cleanup
    result = subprocess.run(
        ["vcgencmd", "measure_temp"],
        capture_output=True,
        text=True,
        timeout=2
    )
    if result.returncode == 0 and result.stdout:
        temp = result.stdout.split('=')[1].strip()
        return temp
    return ""

def eventsThread(keycallback, fieldcallback, tout):
    """Monitor the board for keypresses and piece lift/place events.
    
    Uses monotonic time for timeout tracking to avoid issues with system clock
    adjustments (e.g., NTP sync on Raspberry Pi startup that can jump the clock
    forward and trigger premature shutdown).
    
    Long-press PLAY (hold for 1 second) triggers immediate shutdown.
    """
    global eventsrunning
    global batterylevel
    global batterylastchecked
    global chargerconnected
    
    LONG_PRESS_DURATION = 3.0  # seconds to hold PLAY for shutdown
    
    hold_timeout = False
    events_paused = False
    to = time.monotonic() + tout
    log.debug('Timeout at %s seconds', str(tout))
    
    while time.monotonic() < to:
        loopstart = time.monotonic()
        if eventsrunning == 1:
            # Hold and restart timeout on charger attached
            if chargerconnected == 1:
                to = time.monotonic() + 100000
                hold_timeout = True
            if chargerconnected == 0 and hold_timeout:
                to = time.monotonic() + tout
                hold_timeout = False

            # Reset timeout on unPauseEvents
            if events_paused:
                to = time.monotonic() + tout
                events_paused = False

            key_pressed = None
            
            # Register piece listener if not already registered
            if fieldcallback is not None:
                try:
                    if controller._piece_listener is None:
                        def _listener(piece_event, field_hex, time_in_seconds):
                            nonlocal to
                            try:
                                field = rotateFieldHex(field_hex)
                                log.info(f"[board.events.push] piece_event={piece_event==0 and 'LIFT' or 'PLACE'} ({piece_event}) field={field} field_hex={field_hex} time_in_seconds={time_in_seconds}")
                                fieldcallback(piece_event, field, time_in_seconds)
                                to = time.monotonic() + tout
                            except Exception as e:
                                log.error(f"[board.events.push] error: {e}")
                                import traceback
                                traceback.print_exc()
                        controller._piece_listener = _listener
                except Exception as e:
                    log.error(f"Error in piece detection thread: {e}")
                    import traceback
                    traceback.print_exc()
            
            try:
                key_pressed = controller.get_next_key(timeout=0.0)

                # PLAY_DOWN starts shutdown countdown, releasing cancels
                if key_pressed == Key.PLAY_DOWN:
                    beep(SOUND_GENERAL)
                    log.info('[board.events] PLAY_DOWN detected, starting shutdown countdown')
                    if shutdown_countdown():
                        # Countdown completed without release - proceed with shutdown
                        shutdown(reason="PLAY button held during countdown")
                    else:
                        # User released button - cancelled
                        log.info('[board.events] Shutdown cancelled (button released)')
                    key_pressed = None  # Already handled
                
                # Ignore other key-down events - only key-up events go to callback
                elif key_pressed is not None and key_pressed.value >= 0x80:
                    # This is a _DOWN event (has KEY_DOWN_OFFSET), ignore it
                    key_pressed = None
                    
            except Exception as e:
                log.error(f"[board.events] error: {e}")
                import traceback
                traceback.print_exc()
            
            try:
                if time.time() - batterylastchecked > 15:
                    batterylastchecked = time.time()
                    getBatteryLevel()
            except Exception as e:
                log.error(f"[board.events] getBatteryLevel error: {e}")
                import traceback
                traceback.print_exc()
            
            time.sleep(0.05)
            
            if key_pressed is not None:
                to = time.monotonic() + tout
                log.info(f"[board.events] btn{key_pressed} pressed, sending to keycallback")
                try:
                    keycallback(key_pressed)
                except Exception as e:
                    log.error(f"[board.events] keycallback error: {sys.exc_info()[1]}")
                    import traceback
                    traceback.print_exc()
        else:
            # If pauseEvents() hold timeout in the thread
            to = time.monotonic() + 100000
            events_paused = True

        if time.monotonic() - loopstart > 30:
            to = time.monotonic() + tout
        time.sleep(0.05)
    else:
        # Timeout reached, while loop breaks. Shutdown.
        log.info(f'[board.events] Inactivity timeout reached ({tout}s with no activity)')
        shutdown(reason=f"Inactivity timeout ({tout}s with no user activity)")


def subscribeEvents(keycallback, fieldcallback, timeout=100000):
    # Called by any program wanting to subscribe to events
    # Arguments are firstly the callback function for key presses, secondly for piece lifts and places
    try:
        eventsthreadpointer = threading.Thread(target=eventsThread, args=(keycallback, fieldcallback, timeout))
        eventsthreadpointer.daemon = True
        eventsthreadpointer.start()
    except Exception as e:
        print(f"[board.subscribeEvents] error: {e}")

def pauseEvents():
    global eventsrunning
    log.info(f"[board.pauseEvents] Pausing events")
    eventsrunning = 0
    time.sleep(0.5)

def unPauseEvents():
    global eventsrunning
    log.info(f"[board.unPauseEvents] Unpausing events")
    eventsrunning = 1
    
def unsubscribeEvents(keycallback=None, fieldcallback=None):
    # Minimal compatibility wrapper for callers expecting an unsubscribe API
    # Current implementation pauses events; resume via unPauseEvents()
    log.info(f"[board.unsubscribeEvents] Unsubscribing from events")
    pauseEvents()



