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

from DGTCentaurMods.board.logging import log, logging

# Global display manager
display_manager: Optional[Manager] = None

def _get_display_manager() -> Manager:
    """Get or create the global display manager."""
    global display_manager
    
    if display_manager is None:
        display_manager = Manager()
        display_manager.init()
    return display_manager

_get_display_manager()  # Initialize display

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
#controller = AsyncCentaur(developer_mode=False)
controller = SyncCentaur(developer_mode=False)
# Various setup

# Battery related
chargerconnected = 0
batterylevel = -1
batterylastchecked = 0

# But the address might not be that :( Here we send an initial 0x4d to ask the board to provide its address

controller.wait_ready()

def cleanup(leds_off: bool = True):
    controller.cleanup(leds_off=True)

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

def ledArray(inarray, speed = 3, intensity=5):
    # Lights all the leds in the given inarray with the given speed and intensity
    inarray = list[int](inarray.copy())
    inarray.reverse()
    for i in range(0, len(inarray)):
        inarray[i] = rotateField(inarray[i])
    controller.ledArray(inarray, speed, intensity)

def ledFromTo(lfrom, lto, intensity=5):
    # Light up a from and to LED for move indication
    # Note the call to this function is 0 for a1 and runs to 63 for h8
    # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
    controller.ledFromTo(rotateField(lfrom), rotateField(lto), intensity)

def led(num, intensity=5):
    # Flashes a specific led
    # Note the call to this function is 0 for a1 and runs to 63 for h8
    # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
    controller.led(rotateField(num), intensity)

def ledFlash():
    # Flashes the last led lit by led(num) above
    controller.ledFlash()

def sendCustomBeep(data: bytes):
    """
    Send a custom beep pattern using SOUND_GENERAL command.
    
    Args:
        data: Custom beep pattern bytes (e.g., b'\x50\x08\x00\x08\x59\x08\x00')
    """
    controller.sendCommand(command.SOUND_GENERAL, data)

def sendCustomLedArray(data: bytes):
    """
    Send a custom LED array command using LED_FLASH_CMD.
    
    Args:
        data: Custom LED array data bytes (e.g., b'\x05\x12\x00\x05' followed by square indices)
    """
    controller.sendCommand(command.LED_FLASH_CMD, data)

def shutdown(reboot=False):
    """
    Shutdown the Raspberry Pi with proper cleanup and visual feedback.
    
    If a pending update exists, installs it instead of shutting down.
    Otherwise performs clean shutdown with LED cascade pattern.
    
    Visual feedback:
    - Update install: All LEDs solid
    - Normal shutdown: Sequential LED cascade h8→h1
    """

    beep(SOUND_POWER_OFF)
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
            ledArray([0,1,2,3,4,5,6,7], intensity=6)
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
            led(i, intensity=5)
            time.sleep(0.2)
        # All LEDs off at end
        ledsOff()
    except Exception as e:
        log.error(f"LED pattern failed during shutdown: {e}")
    
    # Send sleep to controller before system poweroff
    try:
        sleep_controller()
    except Exception as e:
        log.debug(f"Controller sleep failed: {e}")
    
    if reboot:
        log.debug('Requesting system reboot via systemd')
        rc = os.system("systemctl reboot")
        if rc != 0:
            log.error(f"systemctl reboot failed with rc={rc}")
        return
    
    # Execute system poweroff via systemd (ensures shutdown hooks run as root)
    log.debug('Requesting system poweroff via systemd')
    rc = os.system("systemctl poweroff")
    if rc != 0:
        log.error(f"systemctl poweroff failed with rc={rc}")


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
        ledFromTo(7, 7)
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
    # This monitors the board for events
    # keypresses and pieces lifted/placed down
    global eventsrunning
    global standby
    global batterylevel
    global batterylastchecked
    global chargerconnected
    standby = False
    hold_timeout = False
    events_paused = False
    to = time.time() + tout
    log.debug('Timeout at %s seconds', str(tout))
    while time.time() < to:
        loopstart = time.time()
        if eventsrunning == 1:
            # Hold and restart timeout on charger attached
            if chargerconnected == 1:
                to = time.time() + 100000
                hold_timeout = True
            if chargerconnected == 0 and hold_timeout:
                to = time.time() + tout
                hold_timeout = False

            # Reset timeout on unPauseEvents
            if events_paused:
                to = time.time() + tout
                events_paused = False

            key_pressed = None
            if not standby:
                #Hold fields activity on standby
                if fieldcallback != None:
                    try:
                        # Prefer push model via asyncserial piece listeners
                        if controller._piece_listener == None:
                            def _listener(piece_event, field_hex, time_in_seconds):
                                nonlocal to
                                try:
                                    #Rotate the field here. The callback to boardmanager should always have a proper square index
                                    field = rotateFieldHex(field_hex)
                                    log.info(f"[board.events.push] piece_event={piece_event==0 and 'LIFT' or 'PLACE'} ({piece_event}) field={field} field_hex={field_hex} time_in_seconds={time_in_seconds}")
                                    fieldcallback(piece_event, field, time_in_seconds)
                                    to = time.time() + tout
                                except Exception as e:
                                    log.error(f"[board.events.push] error: {e}")
                                    import traceback
                                    traceback.print_exc()
                            controller._piece_listener = _listener
                    except Exception as e:
                        log.error(f"Error in piece detection thread: {e}")

            try:

                key_pressed = controller.get_and_reset_last_key()

                if key_pressed == Key.PLAY:
                    breaktime = time.time() + 0.5
                    beep(SOUND_GENERAL)
                    while time.time() < breaktime:
                        key_pressed = controller.get_and_reset_last_key()
                        if key_pressed == Key.PLAY:
                            log.debug('Play btn pressed. Stanby is: %s', standby)
                            if standby == False:
                                log.debug('Calling standbyScreen()')
                                widgets.standby_screen(True)
                                standby = True
                                print("----------------------------------------")
                                print("Starting shutdown countdown")
                                print("----------------------------------------")
                                sd = threading.Timer(600,shutdown)
                                sd.start()
                                to = time.time() + 100000
                                break
                            else:
                                widgets.standby_screen(False)
                                print("----------------------------------------")
                                print("Shutdown countdown interrupted")
                                print("----------------------------------------")
                                sd.cancel()
                                standby = False
                                to = time.time() + tout
                                break
                            break
                    else:
                        beep(SOUND_POWER_OFF)
                        print("----------------------------------------")
                        print("Starting shutdown DISABLED")
                        print("----------------------------------------")
                        #shutdown()
            except Exception as e:
                log.error(f"[board.events] error: {e}")
            try:
                # Sending 152 to the controller provides us with battery information
                # Do this every 15 seconds and fill in the globals
                if time.time() - batterylastchecked > 15:
                    # Every 15 seconds check the battery details
                    batterylastchecked = time.time()
                    getBatteryLevel()
            except:
                pass
            time.sleep(0.05)
            if standby != True and key_pressed is not None:
                to = time.time() + tout
                log.info(f"[board.events] btn{key_pressed} pressed, sending to keycallback")
                # Bridge callbacks: two-arg expects (id, name), one-arg expects (id)
                try:
                    keycallback(key_pressed)
                except Exception as e:
                    log.error(f"[board.events] keycallback error: {sys.exc_info()[1]}")
        else:
            # If pauseEvents() hold timeout in the thread
            to = time.time() + 100000
            events_paused = True

        if time.time() - loopstart > 30:
            to = time.time() + tout
        time.sleep(0.05)
    else:
        # Timeout reached, while loop breaks. Shutdown.
        print("----------------------------------------")
        print("Timeout. Shutting down board DISABLED")
        print("----------------------------------------")
        log.debug('Timeout. Shutting down board')
        #shutdown()


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



