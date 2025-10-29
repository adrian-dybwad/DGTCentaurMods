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
from DGTCentaurMods.board.async_centaur import AsyncCentaur, DGT_BUS_SEND_CHANGES, DGT_BUS_POLL_KEYS, DGT_SEND_BATTERY_INFO, SOUND_GENERAL, SOUND_FACTORY, SOUND_POWER_OFF, SOUND_POWER_ON, SOUND_WRONG, SOUND_WRONG_MOVE, DGT_BUS_SEND_SNAPSHOT, Key
import sys
import os
from DGTCentaurMods.display import epd2in9d, epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board.settings import Settings
from DGTCentaurMods.board import centaur
import time
from PIL import Image, ImageDraw, ImageFont
import inspect
import pathlib
import socket
import queue
import logging

try:
    logging.basicConfig(level=logging.DEBUG, filename="/home/pi/debug.log", filemode="w")
except:
    logging.basicConfig(level=logging.DEBUG)


# Get the config
dev = Settings.read('system', 'developer', 'False')
asyncserial = AsyncCentaur(developer_mode=False)
# Various setup

font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
time.sleep(2)


# Battery related
chargerconnected = 0
batterylevel = -1
batterylastchecked = 0

# But the address might not be that :( Here we send an initial 0x4d to ask the board to provide its address

asyncserial.wait_ready()

# Screen functions - deprecated, use epaper.py if possible
#

screenbuffer = Image.new('1', (128, 296), 255)
initialised = 0
epd = epd2in9d.EPD()

def initScreen():
    global screenbuffer
    global initialised
    epd.init()
    epd.Clear(0xff)
    screenbuffer = Image.new('1', (128, 296), 255)
    initialised = 0
    time.sleep(4)

def clearScreen():
    epd.Clear(0xff)

def clearScreenBuffer():
    global screenbuffer
    screenbuffer = Image.new('1', (128, 296), 255)

def sleepScreen():
    epd.sleep()

def drawBoard(pieces):
    global screenbuffer
    chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
    image = screenbuffer.copy()
    for x in range(0,64):
        pos = (x - 63) * -1
        row = 50 + (16 * (pos // 8))
        col = (x % 8) * 16
        px = 0
        r = x // 8
        c = x % 8
        py = 0
        if (r // 2 == r / 2 and c // 2 == c / 2):
            py = py + 16
        if (r //2 != r / 2 and c // 2 != c / 2):
            py = py + 16
        if pieces[x] == "P":
            px = 16
        if pieces[x] == "R":
            px = 32
        if pieces[x] == "N":
            px = 48
        if pieces[x] == "B":
            px = 64
        if pieces[x] == "Q":
            px = 80
        if pieces[x] == "K":
            px = 96
        if pieces[x] == "p":
            px = 112
        if pieces[x] == "r":
            px = 128
        if pieces[x] == "n":
            px = 144
        if pieces[x] == "b":
            px = 160
        if pieces[x] == "q":
            px = 176
        if pieces[x] == "k":
            px = 192
        piece = chessfont.crop((px, py, px+16, py+16))
        image.paste(piece,(col, row))
    screenbuffer = image.copy()
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    image = image.transpose(Image.FLIP_LEFT_RIGHT)
    epd.DisplayPartial(epd.getbuffer(image))
    time.sleep(0.1)

def writeText(row, txt):
    # Writes some text on the screen at the given row
    rpos = row * 20
    global screenbuffer
    image = screenbuffer.copy()
    draw = ImageDraw.Draw(image)
    draw.rectangle([(0,rpos),(128,rpos+20)],fill=255)
    draw.text((0, rpos), txt, font=font18, fill=0)
    screenbuffer = image.copy()
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    image = image.transpose(Image.FLIP_LEFT_RIGHT)
    epd.DisplayPartial(epd.getbuffer(image))
    time.sleep(0.5)

def writeTextToBuffer(row, txt):
    # Writes some text on the screen at the given row
    # Writes only to the screen buffer. Script can later call displayScreenBufferPartial to show it
    global screenbuffer
    nimage = screenbuffer.copy()
    image = Image.new('1', (128, 20), 255)
    draw = ImageDraw.Draw(image)
    draw.text((0,0), txt, font=font18, fill=0)
    nimage.paste(image, (0, (row * 20)))
    screenbuffer = nimage.copy()

def promotionOptionsToBuffer(row):
    # Draws the promotion options to the screen buffer
    global screenbuffer
    nimage = screenbuffer.copy()
    image = Image.new('1', (128, 20), 255)
    draw = ImageDraw.Draw(image)
    draw.text((0, 0), "    Q    R    N    B", font=font18, fill=0)
    draw.polygon([(2, 18), (18, 18), (10, 3)], fill=0)
    draw.polygon([(35, 3), (51, 3), (43, 18)], fill=0)
    o = 66
    draw.line((0+o,16,16+o,16), fill=0, width=5)
    draw.line((14+o,16,14+o,5), fill=0, width=5)
    draw.line((16+o,6,4+o,6), fill=0, width=5)
    draw.polygon([(8+o, 2), (8+o, 10), (0+o, 6)], fill=0)
    o = 97
    draw.line((6+o,16,16+o,4), fill=0, width=5)
    draw.line((2+o,10, 8+o,16), fill=0, width=5)
    nimage.paste(image, (0, (row * 20)))
    screenbuffer = nimage.copy()

def displayScreenBufferPartial():
    global screenbuffer
    image = screenbuffer.copy()
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    image = image.transpose(Image.FLIP_LEFT_RIGHT)
    epd.DisplayPartial(epd.getbuffer(image))
    time.sleep(0.1)

def cleanup(leds_off: bool = True):
    asyncserial.cleanup(leds_off=True)

def wait_for_key_up(timeout=None, accept=None):
    """Wait for a key up event from the board"""
    return asyncserial.wait_for_key_up(timeout=timeout, accept=accept)


def run_background(start_key_polling=False):
    asyncserial.run_background(start_key_polling=start_key_polling)
    
#
# Board control - functions related to making the board do something
#

def poll_piece_detection():
    asyncserial.poll_piece_detection()

def clearBoardData():
    asyncserial.clearBoardData()

def beep(beeptype):
    if centaur.get_sound() == "off":
        return
    # Ask the centaur to make a beep sound
    asyncserial.beep(beeptype)

def ledsOff():
    # Switch the LEDs off on the centaur
    asyncserial.ledsOff()

def ledArray(inarray, speed = 3, intensity=5):
    # Lights all the leds in the given inarray with the given speed and intensity
    asyncserial.ledArray(inarray, speed, intensity)

def ledFromTo(lfrom, lto, intensity=5):
    # Light up a from and to LED for move indication
    # Note the call to this function is 0 for a1 and runs to 63 for h8
    # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
    asyncserial.ledFromTo(lfrom, lto, intensity)

def led(num, intensity=5):
    # Flashes a specific led
    # Note the call to this function is 0 for a1 and runs to 63 for h8
    # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
    asyncserial.led(num, intensity)

def ledFlash():
    # Flashes the last led lit by led(num) above
    asyncserial.ledFlash()

def shutdown():
    """
    Shutdown the Raspberry Pi with proper cleanup and visual feedback.
    
    If a pending update exists, installs it instead of shutting down.
    Otherwise performs clean shutdown with LED cascade pattern.
    
    Visual feedback:
    - Update install: All LEDs solid
    - Normal shutdown: Sequential LED cascade h8→h1
    """
    update = centaur.UpdateSystem()
    package = '/tmp/dgtcentaurmods_armhf.deb'
    
    # Check for pending update
    if os.path.exists(package):
        logging.debug('Update package found - installing instead of shutdown')
        beep(SOUND_POWER_OFF)
        epaper.clearScreen()
        epaper.writeText(3, "   Installing")
        epaper.writeText(4, "     update")
        
        # All LEDs for update install
        try:
            ledArray([0,1,2,3,4,5,6,7], intensity=6)
        except Exception:
            pass
        
        time.sleep(2)
        update.updateInstall()
        return
    
    # Normal shutdown sequence
    logging.debug('Normal shutdown sequence starting')
    
    # Beep power off sound
    try:
        beep(SOUND_POWER_OFF)
    except Exception:
        pass
    
    # Display shutdown message
    epaper.clearScreen()
    epaper.writeText(3, "     Shutting")
    epaper.writeText(4, "       down")
    
    # LED cascade pattern h8→h1 (squares 7 down to 0)
    try:
        for i in range(7, -1, -1):
            led(i, intensity=5)
            time.sleep(0.2)
        # All LEDs off at end
        ledsOff()
    except Exception as e:
        logging.debug(f"LED pattern failed during shutdown: {e}")
    
    time.sleep(2)
    
    # Properly stop e-paper
    try:
        epaper.stopEpaper()
    except Exception as e:
        logging.debug(f"E-paper stop failed: {e}")
    
    time.sleep(1)
    
    # Send sleep to controller before system poweroff
    try:
        sleep_controller()
    except Exception as e:
        logging.debug(f"Controller sleep failed: {e}")
    
    # Execute system poweroff via systemd (ensures shutdown hooks run as root)
    logging.debug('Requesting system poweroff via systemd')
    rc = os.system("systemctl poweroff")
    if rc != 0:
        logging.error(f"systemctl poweroff failed with rc={rc}")


def sleep_controller():
    """
    Send sleep command to DGT Centaur controller.
    
    Called during system shutdown to properly power down the controller
    before the Raspberry Pi powers off. This prevents the controller
    from remaining powered when the Pi shuts down.
    
    Visual feedback: Single LED at h8 position (square 7)
    """
    logging.debug("Sending sleep command to DGT Centaur controller")
    
    # Visual feedback - single LED at h8
    try:
        ledFromTo(7, 7)
    except Exception as e:
        logging.debug(f"LED failed during controller sleep: {e}")
    
    # Send sleep command to controller
    try:
        sleep()
        logging.debug("Controller sleep command sent successfully")
    except Exception as e:
        logging.debug(f"Failed to send sleep command: {e}")


def sleep():
    """
    Sleep the controller.
    """
    asyncserial.sleep()


#
# Board response - functions related to get something from the board
#

def poll():
    # We need to continue poll the board to get data from it
    # Perhaps there's a packet length in here somewhere but
    # I haven't noticed it yet, therefore we need to process
    # the data as it comes
    ser.read(100000)
    sendPacket(b'\x83', b'')
    expect = buildPacket(b'\x85\x00\x06', b'')
    resp = ser.read(10000)
    resp = bytearray(resp)
    if (bytearray(resp) != expect):
        if (resp[0] == 133 and resp[1] == 0):
            for x in range(0, len(resp) - 1):
                if (resp[x] == 64):
                    # Calculate the square to 0(a1)-63(h8) so that
                    # all functions match
                    fieldHex = resp[x + 1]
                    newsquare = rotateFieldHex(fieldHex)
                if (resp[x] == 65):
                    # Calculate the square to 0(a1)-63(h8) so that
                    # all functions match
                    fieldHex = resp[x + 1]
                    newsquare = rotateFieldHex(fieldHex)
    sendPacket(b'\x94', b'')
    expect = buildPacket(b'\xb1\x00\x06', b'')
    resp = ser.read(10000)
    resp = bytearray(resp)
    if (resp != expect):
        if (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0501000000007d47"):
            logging.debug("BACK BUTTON")
        if (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0510000000007d17"):
            logging.debug("TICK BUTTON")
        if (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0508000000007d3c"):
            logging.debug("UP BUTTON")
        if (resp.hex()[:-2] == "b10010" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a05020000000061"):
            logging.debug("DOWN BUTTON")
        if (resp.hex()[:-2] == "b10010" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0540000000006d"):
            logging.debug("HELP BUTTON")
        if (resp.hex()[:-2] == "b10010" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0504000000002a"):
            logging.debug("PLAY BUTTON")


def getBoardState():
    """
    Query the board and return a 64-length list of 0/1 occupancy flags.
    Robust against short reads; retries at both application and protocol level.
    
    Args:
        field: Optional square index (0-63) to query specific square
        retries: Number of application-level retry attempts
        sleep_between: Delay between application-level retries
        timeout: Timeout in seconds for each request (default 3.0)
        protocol_retries: Number of protocol-level retries (default 1)
    """
    # Local constants for snapshot framing and a clear board fallback
    SNAPSHOT_HEADER_LEN = 6
    SNAPSHOT_PAYLOAD_BYTES = 64 * 2
    SNAPSHOT_TOTAL_LEN = SNAPSHOT_HEADER_LEN + SNAPSHOT_PAYLOAD_BYTES
    BOARD_CLEAR_STATE = [0] * 64

    try:
        # Request a raw snapshot (header + payload)
        resp = asyncserial.request_response(
            DGT_BUS_SEND_SNAPSHOT, timeout=2.0, raw_len=SNAPSHOT_TOTAL_LEN + 1
        )

        resp = bytearray(resp)
        payload = resp[SNAPSHOT_HEADER_LEN:SNAPSHOT_TOTAL_LEN]

        print(f"DEBUG: resp: {resp}")
        print(f"DEBUG: payload: {payload}")
        # resp = asyncserial.request_response(DGT_BUS_SEND_SNAPSHOT, timeout=timeout, retries=protocol_retries)
        # Check if request timed out
        # if resp is None:
        #     print("Error getting board state")
        #     print("Request timeout - no response from board")
        #     time.sleep(sleep_between)
        #     continue

        boarddata = BOARD_CLEAR_STATE.copy()
        upperlimit = 32000
        lowerlimit = 300
        # payload is 64 words (big-endian 16-bit)
        for i in range(0, 128, 2):
            tval = (payload[i] << 8) | payload[i+1]
            boarddata[i // 2] = 1 if (lowerlimit <= tval <= upperlimit) else 0

        if field is not None:
            return boarddata[field]
        return boarddata

    except Exception as e:
        print("Error getting board state")
        print(e)
        # transient read/parse error—retry

    # Final fallback so callers (like getText) never crash
    if field is not None:
        return 0
    return BOARD_CLEAR_STATE

def printBoardState():
    # Helper to display board state
    state = getBoardState()
    for x in range(0,64,8):
        print("+---+---+---+---+---+---+---+---+")
        for y in range(0,8):
            print("| " + str(state[x+y]) + " ", end='')
        print("|\r")
    print("+---+---+---+---+---+---+---+---+")

def getChargingState():
    # Returns if the board is plugged into the charger or not
    # 0 = not plugged in, 1 = plugged in, -1 = error in checking
    resp = ""
    timeout = time.time() + 5
    while len(resp) < 7 and time.time() < timeout:
        # Sending the board a packet starting with 152 gives battery info
        sendPacket(bytearray([152]), b'')
        try:
            resp = ser.read(1000)
        except:
            pass
        if len(resp) < 7:
            pass
        else:  
            if resp[0] == 181:
                vall = (resp[5] >> 5) & 7
                if vall == 1:
                    return 1
                else:
                    return 0
    return - 1

def getBatteryLevel():
    # batterylevel: a number 0 - 20 representing battery level of the board
    # 20 is fully charged. The board dies somewhere around a low of 1
    # Sending the board a packet starting with 152 gives battery info
    global batterylevel, chargerconnected, batterylastchecked
    resp = asyncserial.request_response(DGT_SEND_BATTERY_INFO)
    batterylastchecked = time.time()
    val = resp[0]
    batterylevel = val & 0x1F
    chargerconnected = 1 if ((val >> 5) & 0x07) in (1, 2) else 0    


#
# Miscellaneous functions - do they belong in this file?
#

def checkInternetSocket(host="8.8.8.8", port=53, timeout=1):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error as ex:
        logging.debug(ex)
        return False

#
# Helper functions - used by other functions or useful in manipulating board data
#

def rotateField(field):
    lrow = (field // 8)
    lcol = (field % 8)
    newField = (7 - lrow) * 8 + lcol
    return newField

def rotateFieldHex(fieldHex):
    squarerow = (fieldHex // 8)
    squarecol = (fieldHex % 8)
    field = (7 - squarerow) * 8 + squarecol
    return field

def convertField(field):
    square = chr((ord('a') + (field % 8))) + chr(ord('1') + (field // 8))
    return square


# This section is the start of a new way of working with the board functions where those functions are
# the board returning some kind of data
import threading
eventsthreadpointer = ""
eventsrunning = 1

def temp():
    '''
    Get CPU temperature
    '''
    temp = os.popen("vcgencmd measure_temp | cut -d'=' -f2").read().strip()
    return temp

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
    logging.debug('Timeout at %s seconds', str(tout))
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
                        if asyncserial._piece_listener == None:
                            def _listener(piece_event, field_hex, square, time_in_seconds):
                                nonlocal to
                                try:
                                    print(f"[board.events.push] piece_event={piece_event==0 and 'LIFT' or 'PLACE'} field_hex={field_hex} square={square} time_in_seconds={time_in_seconds}")
                                    fieldcallback(piece_event, field_hex, square, time_in_seconds)
                                    to = time.time() + tout
                                except Exception as e:
                                    print(f"[board.events.push] error: {e}")
                            asyncserial._piece_listener = _listener
                            asyncserial.poll_piece_detection()
                    except Exception as e:
                        print("Error in piece detection")   
                        print(f"Error: {e}")

            try:

                key_pressed = asyncserial.get_and_reset_last_key()

                if key_pressed is not None:
                    print("name: " + key_pressed.name)
                    print("value: " + str(key_pressed.value))

                if key_pressed == Key.PLAY:
                    breaktime = time.time() + 0.5
                    beep(SOUND_GENERAL)
                    while time.time() < breaktime:
                        key_pressed = asyncserial.get_and_reset_last_key()
                        if key_pressed == Key.PLAY:
                            logging.debug('Play btn pressed. Stanby is: %s', standby)
                            if standby == False:
                                logging.debug('Calling standbyScreen()')
                                epaper.standbyScreen(True)
                                standby = True
                                logging.debug('Starting shutdown countdown')
                                sd = threading.Timer(600,shutdown)
                                sd.start()
                                to = time.time() + 100000
                                break
                            else:
                                epaper.standbyScreen(False)
                                logging.debug('Cancel shutdown')
                                sd.cancel()
                                standby = False
                                to = time.time() + tout
                                break
                            break
                    else:
                        beep(SOUND_POWER_OFF)
                        shutdown()
            except Exception as e:
                print(f"[board.events] error: {e}")
                print(f"[board.events] error: {sys.exc_info()[1]}")
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
                print(f"[board.events] btn{key_pressed} pressed, sending to keycallback")
                # Bridge callbacks: two-arg expects (id, name), one-arg expects (id)
                try:
                    keycallback(key_pressed)
                except Exception as e:
                    print(f"[board.events] keycallback error: {sys.exc_info()[1]}")
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
        print("Timeout. Shutting down board")
        print("----------------------------------------")
        logging.debug('Timeout. Shutting down board')
        shutdown()


def subscribeEvents(keycallback, fieldcallback, timeout=100000):
    # Called by any program wanting to subscribe to events
    # Arguments are firstly the callback function for key presses, secondly for piece lifts and places
    try:
        print(f"[board.subscribeEvents] Subscribing to events")
        print(f"[board.subscribeEvents] Keycallback: {keycallback}")
        print(f"[board.subscribeEvents] Fieldcallback: {fieldcallback}")
        print(f"[board.subscribeEvents] Timeout: {timeout}")
        eventsthreadpointer = threading.Thread(target=eventsThread, args=(keycallback, fieldcallback, timeout))
        eventsthreadpointer.daemon = True
        eventsthreadpointer.start()
    except Exception as e:
        print(f"[board.subscribeEvents] error: {e}")
        print(f"[board.subscribeEvents] error: {sys.exc_info()[1]}")

def pauseEvents():
    global eventsrunning
    print(f"[board.pauseEvents] Pausing events")
    eventsrunning = 0
    time.sleep(0.5)

def unPauseEvents():
    global eventsrunning
    print(f"[board.unPauseEvents] Unpausing events")
    eventsrunning = 1
    
def unsubscribeEvents(keycallback=None, fieldcallback=None):
    # Minimal compatibility wrapper for callers expecting an unsubscribe API
    # Current implementation pauses events; resume via unPauseEvents()
    print(f"[board.unsubscribeEvents] Unsubscribing from events")
    pauseEvents()