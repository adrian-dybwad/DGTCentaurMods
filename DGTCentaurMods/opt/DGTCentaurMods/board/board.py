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

from __future__ import annotations

import serial
import sys
import os
from DGTCentaurMods.display import epd2in9d, epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board.settings import Settings
from DGTCentaurMods.board import centaur
import time
from PIL import Image, ImageDraw, ImageFont
import pathlib
import socket
import queue
import logging
from typing import Optional

try:
    logging.basicConfig(level=logging.DEBUG, filename="/home/pi/debug.log", filemode="w")
except:
    logging.basicConfig(level=logging.DEBUG)

#
# Useful constants
#
SOUND_GENERAL = 1
SOUND_FACTORY = 2
SOUND_POWER_OFF = 3
SOUND_POWER_ON = 4
SOUND_WRONG = 5
SOUND_WRONG_MOVE = 6
BTNBACK = 1
BTNTICK = 2
BTNUP = 3
BTNDOWN = 4
BTNHELP = 5
BTNPLAY = 6
BTNLONGPLAY = 7

import threading
from serial import SerialException

SER_LOCK = threading.RLock()

def _ser_read(n, timeout=None):
    """Thread-safe, resilient read."""
    with SER_LOCK:
        if timeout is not None:
            old_to = ser.timeout
            ser.timeout = timeout
        try:
            return ser.read(n)
        except SerialException:
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            time.sleep(0.05)
            return b""
        finally:
            if timeout is not None:
                ser.timeout = old_to

def _ser_write(b):
    with SER_LOCK:
        try:
            ser.write(b)
        except SerialException:
            time.sleep(0.05)  # brief backoff

def _ser_drain():
    """Drain any pending bytes (best-effort)."""
    with SER_LOCK:
        try:
            ser.read(100000)
        except Exception:
            pass

# Get the config
dev = Settings.read('system', 'developer', 'False')

# Various setup
if dev == "True":
    logging.debug("Developer mode is: %s", dev)
    # Enable virtual serial port (developer convenience)
    os.system("socat -d -d pty,raw,echo=0 pty,raw,echo=0 &")
    time.sleep(10)
    # Then redirect
    ser = serial.Serial("/dev/pts/2", baudrate=1000000, timeout=0.2)
else:
    # Be robust if the device is not immediately ready.
    try:
        ser = serial.Serial("/dev/serial0", baudrate=1000000, timeout=0.2)
        try:
            # POSIX only; prevents another fd on same TTY
            ser.exclusive = True
        except Exception:
            pass
        ser.isOpen()
    except Exception:
        try:
            if 'ser' in globals() and getattr(ser, 'is_open', False):
                ser.close()
        except Exception:
            pass
        ser = serial.Serial("/dev/serial0", baudrate=1000000, timeout=0.2)

font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
time.sleep(2)

# Battery related
chargerconnected = 0
batterylevel = -1
batterylastchecked = 0

# But the address might not be that :( Here we send an initial 0x4d to ask the board to provide its address
logging.debug("Detecting board adress")
try:
    _ser_read(1000)
except:
    _ser_read(1000)
tosend = bytearray(b'\x4d')
_ser_write(tosend)
try:
    _ser_read(1000)
except:
    _ser_read(1000)
logging.debug('Sent payload 1')
tosend = bytearray(b'\x4e')
_ser_write(tosend)
try:
    _ser_read(1000)
except:
    _ser_read(1000)
logging.debug('Sent payload 2')
logging.debug('Serial is open. Waiting for response.')
resp = ""
# This is the most common address of the board
addr1 = 0x00
addr2 = 0x00
timeout = time.time() + 60
while len(resp) < 4 and time.time() < timeout:
    if dev == "True":
        break
    tosend = bytearray(b'\x87\x00\x00\x07')
    _ser_write(tosend)
    try:
        resp = _ser_read(1000)
    except:
        resp = _ser_read(1000)
    if len(resp) > 3:
        addr1 = resp[3]
        addr2 = resp[4]
        logging.debug("Discovered new address:%s%s", hex(addr1), hex(addr2))
        break
else:
    logging.debug('FATAL: No response from serial')
    sys.exit(1)

def checksum(barr):
    csum = 0
    for c in bytes(barr):
        csum += c
    barr_csum = (csum % 128)
    return barr_csum

def buildPacket(command, data):
    # pass command and data as bytes
    tosend = bytearray(command + addr1.to_bytes(1, byteorder='big') + addr2.to_bytes(1, byteorder='big') + data)
    tosend.append(checksum(tosend))
    return tosend

def sendPacket(command, data):
    tosend = buildPacket(command, data)
    _ser_write(tosend)

def clearSerial():
    logging.debug('Checking and clear the serial line.')
    resp1 = resp2 = b""
    while dev == "False":
        sendPacket(b'\x83', b'')
        expect1 = buildPacket(b'\x85\x00\x06', b'')
        resp1 = _ser_read(256)
        sendPacket(b'\x94', b'')
        expect2 = buildPacket(b'\xb1\x00\x06', b'')
        resp2 = _ser_read(256)
        if expect1 == resp1 and expect2 == resp2:
            logging.debug('Board is idle. Serial is clear.')
            return True
        logging.debug('  Attempting to clear serial')
        time.sleep(0.05)

# ---------------------------------------------------------------------------
# Non-blocking helpers (safe to use alongside existing request/response code)
# ---------------------------------------------------------------------------

def getBoardStateNonBlocking(max_bytes: int = 256) -> Optional[bytes]:
    """
    Non-blocking peek at incoming data from the board.
    Returns bytes (or None if nothing immediately available).
    Temporarily sets serial timeout to 0 and restores it.
    """
    if ser is None:
        return None
    try:
        prev = ser.timeout
        ser.timeout = 0  # non-blocking
        data = _ser_read(max_bytes) or b""
        return data if data else None
    except Exception:
        return None
    finally:
        try:
            ser.timeout = prev
        except Exception:
            pass

def _map_bytes_to_action(b: bytes) -> Optional[str]:
    """
    Convert raw bytes into abstract key actions for menus.
    Adjust to match your observed protocol if needed.
    """
    if not b:
        return None
    s = b.upper()
    # Heuristics / examples; adapt as required
    if b"UP" in s or b"\x55" in s:
        return "UP"
    if b"DOWN" in s or b"\x44" in s:
        return "DOWN"
    if b"LEFT" in s:
        return "LEFT"
    if b"RIGHT" in s:
        return "RIGHT"
    if b"BACK" in s:
        return "BACK"
    if b"OK" in s or b"\r" in s or b"\n" in s:
        return "OK"
    return None

def poll_action_from_board() -> Optional[str]:
    """
    Non-blocking action poller for UI code (e.g., e-paper menus).
    Returns one of {"UP","DOWN","LEFT","RIGHT","OK","BACK"} or None.
    """
    chunk = getBoardStateNonBlocking()
    if not chunk:
        return None
    return _map_bytes_to_action(chunk)

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

def doMenu(items, fast = 0):
    # Draw a menu, let the user navigate and return the value
    # or "BACK" if the user backed out
    # pass a menu like: menu = {'Lichess': 'Lichess', 'Centaur': 'DGT
    # Centaur', 'Shutdown': 'Shutdown', 'Reboot': 'Reboot'}
    selected = 1
    buttonPress = 0
    first = 1
    global initialised
    #if initialised == 0 and fast == 0:
    #    epd.Clear(0xff)
    connected = 0
    if fast == 0:
        connected = checkInternetSocket()
    quickselect = 0
    quickselectpossible = -1
    res = getBoardState()
    if res[32] == 0 and res[33] == 0 and res[34] == 0 and res[35] == 0 and res[36]==0 and res[37] == 0 and res[38] == 0 and res[39] == 0:
        # If the 4th rank is empty then enable quick select mode. Then we can choose a menu option by placing and releasing a piece
        quickselect = 1
    image = Image.new('1', (epd.width, epd.height), 255)
    while (buttonPress != 2):
        time.sleep(0.05)
        draw = ImageDraw.Draw(image)
        if first == 1:
            rpos = 20
            draw.rectangle([(0,0),(127,295)], fill=255, outline=255)
            for k, v in items.items():
                draw.text((20, rpos), str(v), font=font18, fill=0)
                rpos = rpos + 20
            draw.rectangle([(-1, 0), (17, 294)], fill=255, outline=0)
            draw.polygon([(2, (selected * 20) + 2), (2, (selected * 20) + 18),
                          (18, (selected * 20) + 10)], fill=0)
            # Draw an image representing internet connectivity
            wifion = Image.open(AssetManager.get_resource_path("wifiontiny.bmp"))
            wifioff = Image.open(AssetManager.get_resource_path("wifiofftiny.bmp"))
            if connected == True:
                wifidispicon = wifion.resize((20,16))
                image.paste(wifidispicon, (105, 5))
            else:
                wifidispicon = wifioff.resize((20, 16))
                image.paste(wifidispicon, (105, 5))
            image = image.transpose(Image.FLIP_TOP_BOTTOM)
            image = image.transpose(Image.FLIP_LEFT_RIGHT)

        draw.rectangle([(110,0),(128,294)],fill=255,outline=0)
        draw.polygon([(128 - 2, 276 - (selected * 20) + 2), (128 - 2, 276 - (selected * 20) + 18),
                      (128 - 18, 276 - (selected * 20) + 10)], fill=0)

        if first == 1 and initialised == 0:
            if fast == 0:
                epd.init()
                epd.display(epd.getbuffer(image))
            first = 0
            epd.DisplayRegion(0,295,epd.getbuffer(image))
            time.sleep(2)
            initialised = 1
        else:
            if first == 1 and initialised == 1:
                first = 0
                epd.DisplayRegion(0, 295, epd.getbuffer(image))
                time.sleep(2)
            else:
                sl = 295 - (selected * 20) - 40
                epd.DisplayRegion(sl,sl + 60,epd.getbuffer(image.crop((0,sl,127,sl+60))))

        # Next we wait for either the up/down/back or tick buttons to get
        # pressed
        timeout_local = time.time() + 60 * 15
        while buttonPress == 0:
            _ser_read(1000000)
            sendPacket(b'\x83', b'')
            expect = buildPacket(b'\x85\x00', b'')
            resp = _ser_read(10000)
            resp = bytearray(resp)
            sendPacket(b'\x94', b'')
            expect = buildPacket(b'\xb1\x00', b'')
            resp = _ser_read(10000)
            resp = bytearray(resp)
            if (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0501000000007d47"):
                buttonPress = 1
            if (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0510000000007d17"):
                buttonPress = 2
            if (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0508000000007d3c"):
                buttonPress = 3
            if (resp.hex()[:-2] == "b10010" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a05020000000061"):
                buttonPress = 4
            # check for quickselect
            if quickselect == 1 and quickselectpossible < 1:
                res = getBoardState()
                if res[32] > 0:
                    quickselectpossible = 1
                if res[33] > 0:
                    quickselectpossible = 2
                if res[34] > 0:
                    quickselectpossible = 3
                if res[35] > 0:
                    quickselectpossible = 4
                if res[36] > 0:
                    quickselectpossible = 5
                if res[37] > 0:
                    quickselectpossible = 6
                if res[38] > 0:
                    quickselectpossible = 7
                if res[39] > 0:
                    quickselectpossible = 8
                if quickselectpossible > 0:
                    beep(SOUND_GENERAL)
            if quickselect == 1 and quickselectpossible > 0:
                res = getBoardState()
                if res[32] == 0 and res[33] == 0 and res[34] == 0 and res[35] == 0 and res[36] == 0 and res[37] == 0 and res[38] == 0 and res[39] == 0:
                    # Quickselect possible has been chosen
                    c = 1
                    r = ""
                    for k, v in items.items():
                        if (c == quickselectpossible):
                            selected = 99999
                            return k
                        c = c + 1

            # Also allow non-blocking bytes to drive the menu if available
            try:
                act = poll_action_from_board()
                if act == "UP" and selected > 1:
                    buttonPress = 3
                elif act == "DOWN" and selected < len(items):
                    buttonPress = 4
                elif act in ("OK", "RIGHT"):
                    buttonPress = 2
                elif act in ("BACK", "LEFT"):
                    buttonPress = 1
            except Exception:
                pass

            if time.time() > timeout_local:
                epd.Clear(0xff)
                return "BACK"

        sendPacket(b'\xb1\x00\x08', b'\x4c\x08')
        if (buttonPress == 2):
            # Tick, so return the key for this menu item
            c = 1
            r = ""
            for k, v in items.items():
                if (c == selected):
                    selected = 99999
                    return k
                c = c + 1
        if (buttonPress == 4 and selected < len(items)):
            selected = selected + 1
        if (buttonPress == 3 and selected > 1):
            selected = selected - 1
        if (buttonPress == 1):
            epd.Clear(0xff)
            return "BACK"
        buttonPress = 0

#
# Board control - functions related to making the board do something
#

def clearBoardData():
    # Don't crash if the port claims ready but returns nothing
    try:
        _ser_read(100000)  # dump junk
        sendPacket(b'\x83', b'')
        _ser_read(100000)
    except Exception:
        time.sleep(0.05)

def beep(beeptype):
    # Ask the centaur to make a beep sound
    if centaur.get_sound() == "off":
        return
    if (beeptype == SOUND_GENERAL):
        sendPacket(b'\xb1\x00\x08',b'\x4c\x08')
    if (beeptype == SOUND_FACTORY):
        sendPacket(b'\xb1\x00\x08', b'\x4c\x40')
    if (beeptype == SOUND_POWER_OFF):
        sendPacket(b'\xb1\x00\x0a', b'\x4c\x08\x48\x08')
    if (beeptype == SOUND_POWER_ON):
        sendPacket(b'\xb1\x00\x0a', b'\x48\x08\x4c\x08')
    if (beeptype == SOUND_WRONG):
        sendPacket(b'\xb1\x00\x0a', b'\x4e\x0c\x48\x10')
    if (beeptype == SOUND_WRONG_MOVE):
        sendPacket(b'\xb1\x00\x08', b'\x48\x08')

def ledsOff():
    # Switch the LEDs off on the centaur
    sendPacket(b'\xb0\x00\x07', b'\x00')

def ledArray(inarray, speed = 3, intensity=5):
    # Lights all the leds in the given inarray with the given speed and intensity
    tosend = bytearray(b'\xb0\x00\x0c' + addr1.to_bytes(1, byteorder='big') + addr2.to_bytes(1, byteorder='big') + b'\x05')
    tosend.append(speed)
    tosend.append(0)
    tosend.append(intensity)
    for i in range(0, len(inarray)):
        tosend.append(rotateField(inarray[i]))
    tosend[2] = len(tosend) + 1
    tosend.append(checksum(tosend))
    _ser_write(tosend)

def ledFromTo(lfrom, lto, intensity=5):
    # Light up a from and to LED for move indication
    # Note the call to this function is 0 for a1 and runs to 63 for h8
    # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
    tosend = bytearray(b'\xb0\x00\x0c' + addr1.to_bytes(1, byteorder='big') + addr2.to_bytes(1, byteorder='big') + b'\x05\x03\x00\x05\x3d\x31\x0d')
    # Recalculate lfrom to the different indexing system
    tosend[8] = intensity
    tosend[9] = rotateField(lfrom)
    # Same for lto
    tosend[10] = rotateField(lto)
    # Wipe checksum byte and append the new checksum.
    tosend.pop()
    tosend.append(checksum(tosend))
    _ser_write(tosend)
    #_ser_read(100000)

def led(num, intensity=5):
    # Flashes a specific led
    # Note the call to this function is 0 for a1 and runs to 63 for h8
    # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
    tcount = 0
    success = 0
    while tcount < 5 and success == 0:
        try:
            tosend = bytearray(b'\xb0\x00\x0b' + addr1.to_bytes(1, byteorder='big') + addr2.to_bytes(1, byteorder='big') + b'\x05\x0a\x01\x01\x3d\x5f')
            # Recalculate num to the different indexing system
            # Last bit is the checksum
            tosend[8] = intensity
            tosend[9] = rotateField(num)
            # Wipe checksum byte and append the new checksum.
            tosend.pop()
            tosend.append(checksum(tosend))
            _ser_write(tosend)
            success = 1
        except:
            time.sleep(0.1)
            tcount = tcount + 1

def ledFlash():
    # Flashes the last led lit by led(num) above
    sendPacket(b'\xb0\x00\x0a', b'\x05\x0a\x00\x01')

def shutdown():
    update = centaur.UpdateSystem()
    beep(SOUND_POWER_OFF)
    package = '/tmp/dgtcentaurmods_armhf.deb'
    if os.path.exists(package):
        ledArray([0,1,2,3,4,5,6,7],6)
        epaper.clearScreen()
        update.updateInstall()
        return
    logging.debug('Normal shutdown')
    epaper.clearScreen()
    time.sleep(1)
    ledFromTo(7,7)
    epaper.writeText(3, "     Shutting")
    epaper.writeText(4, "       down")
    time.sleep(3)
    epaper.stopEpaper()
    os.system("sudo poweroff")

def sleep():
    """
    Sleep the controller.
    """
    sendPacket(b'\xb2\x00\x07', b'\x0a')

#
# Board response - functions related to get something from the board
#

def waitMove():
    # Wait for a player to lift a piece and set it down somewhere different
    lifted = -1
    placed = -1
    moves = []
    while placed == -1:
        _ser_read(100000)
        sendPacket(b'\x83', b'')
        expect = buildPacket(b'\x85\x00\x06', b'')
        resp = _ser_read(10000)
        resp = bytearray(resp)
        if (bytearray(resp) != expect):
            if (resp[0] == 133 and resp[1] == 0):
                for x in range(0, len(resp) - 1):
                    if (resp[x] == 64):
                        fieldHex = resp[x + 1]
                        newsquare = rotateFieldHex(fieldHex)
                        lifted = newsquare
                        moves.append((newsquare+1) * -1)
                    if (resp[x] == 65):
                        fieldHex = resp[x + 1]
                        newsquare = rotateFieldHex(fieldHex)
                        placed = newsquare
                        moves.append(newsquare + 1)
        sendPacket(b'\x94', b'')
        expect = buildPacket(b'\xb1\x00\x06', b'')
        resp = _ser_read(10000)
        resp = bytearray(resp)
    return moves

def poll():
    # Keep polling the board to get data from it
    _ser_read(100000)
    sendPacket(b'\x83', b'')
    expect = buildPacket(b'\x85\x00\x06', b'')
    resp = _ser_read(10000)
    resp = bytearray(resp)
    if (bytearray(resp) != expect):
        if (resp[0] == 133 and resp[1] == 0):
            for x in range(0, len(resp) - 1):
                if (resp[x] == 64):
                    fieldHex = resp[x + 1]
                    newsquare = rotateFieldHex(fieldHex)
                if (resp[x] == 65):
                    fieldHex = resp[x + 1]
                    newsquare = rotateFieldHex(fieldHex)
    sendPacket(b'\x94', b'')
    expect = buildPacket(b'\xb1\x00\x06', b'')
    resp = _ser_read(10000)
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

def getText(title):
    """
    Enter text using the board as a virtual keyboard.
    Pauses events; robust against short/partial serial reads.
    BACK deletes, TICK confirms, UP/DOWN switch pages.
    """
    global screenbuffer
    try:
        try:
            pauseEvents()
        except Exception:
            pass

        clearstate = [0] * 64
        printableascii = (
            " !\"#$%&'()*+,-./0123456789:;<=>?@"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
            "abcdefghijklmnopqrstuvwxyz{|}~"
            + (" " * (64 * 2 - 95))
        )
        charpage = 1
        typed = ""
        changed = True

        res = getBoardState()
        if not isinstance(res, list) or len(res) != 64:
            res = [0] * 64
        if res != clearstate:
            writeTextToBuffer(0, "Remove board")
            writeText(1, "pieces")
            deadline = time.time() + 20
            while time.time() < deadline:
                time.sleep(0.4)
                res = getBoardState()
                if isinstance(res, list) and len(res) == 64 and res == clearstate:
                    break

        clearSerial()

        def _render():
            nonlocal typed, charpage
            global screenbuffer
            image = Image.new('1', (128, 296), 255)
            draw = ImageDraw.Draw(image)
            draw.text((0, 20), title, font=font18, fill=0)
            draw.rectangle([(0, 39), (128, 61)], outline=0, fill=255)
            tt = typed[-11:] if len(typed) > 11 else typed
            draw.text((0, 40), tt, font=font18, fill=0)
            page_start = (charpage - 1) * 64
            lchars = [printableascii[i] for i in range(page_start, page_start + 64)]
            for row in range(8):
                for col in range(8):
                    ch = lchars[row * 8 + col]
                    draw.text((col * 16, 80 + row * 20), ch, font=font18, fill=0)
            screenbuffer = image.copy()
            img = image.transpose(Image.FLIP_TOP_BOTTOM).transpose(Image.FLIP_LEFT_RIGHT)
            epd.DisplayPartial(epd.getbuffer(img))

        def _read_fields_and_type():
            nonlocal typed, charpage
            try:
                sendPacket(b'\x83', b'')
                resp = _ser_read(10000)
                if len(resp) >= 2 and resp[0] == 133 and resp[1] == 0:
                    i = 0
                    while i < len(resp) - 1:
                        tag = resp[i]
                        if tag == 65:  # placed
                            fieldHex = resp[i + 1]
                            if 0 <= fieldHex < 64:
                                base = (charpage - 1) * 64
                                ch = printableascii[base + fieldHex]
                                typed += ch
                                beep(SOUND_GENERAL)
                                return True
                            i += 2
                        elif tag == 64:  # lifted
                            i += 2
                        else:
                            i += 1
            except Exception:
                pass
            return False

        def _read_buttons():
            try:
                sendPacket(b'\x94', b'')
                resp = _ser_read(10000)
                if len(resp) < 6:
                    return 0
                hx = resp.hex()[:-2]
                a1 = "{:02x}".format(addr1)
                a2 = "{:02x}".format(addr2)
                if hx == ("b10011" + a1 + a2 + "00140a0501000000007d47"):
                    return BTNBACK
                if hx == ("b10011" + a1 + a2 + "00140a0510000000007d17"):
                    return BTNTICK
                if hx == ("b10011" + a1 + a2 + "00140a0508000000007d3c"):
                    return BTNUP
                if hx == ("b10010" + a1 + a2 + "00140a05020000000061"):
                    return BTNDOWN
            except Exception:
                pass
            return 0

        _render()
        last_draw = 0.0
        while True:
            typed_changed = _read_fields_and_type()
            btn = _read_buttons()

            if btn == BTNBACK:
                if typed:
                    typed = typed[:-1]
                    beep(SOUND_GENERAL)
                    changed = True
                else:
                    beep(SOUND_WRONG)
            elif btn == BTNTICK:
                beep(SOUND_GENERAL)
                clearScreen()
                time.sleep(0.2)
                return typed
            elif btn == BTNUP and charpage != 1:
                charpage = 1
                beep(SOUND_GENERAL)
                changed = True
            elif btn == BTNDOWN and charpage != 2:
                charpage = 2
                beep(SOUND_GENERAL)
                changed = True

            if changed or typed_changed or (time.time() - last_draw) > 0.2:
                _render()
                last_draw = time.time()
                changed = False

            time.sleep(0.05)

    finally:
        try:
            unPauseEvents()
        except Exception:
            pass

def getBoardState(field=None, retries=6, sleep_between=0.12):
    """
    Query the board and return a 64-length list of 0/1 occupancy flags.
    Robust against short reads; retries a few times and falls back to zeros.
    If 'field' is given (0..63), returns just that square.
    """
    needed = 6 + 64 * 2  # header + 128 bytes payload
    for _ in range(retries):
        try:
            # clear any junk first
            try:
                ser.reset_input_buffer()
            except Exception:
                _ser_read(10000)

            # request snapshot
            sendPacket(b'\xf0\x00\x07', b'\x7f')

            # read at least 'needed' bytes; serial timeout keeps this bounded
            resp = _ser_read(needed)

            if len(resp) < needed:
                time.sleep(sleep_between)
                continue

            payload = resp[6:6+128]
            boarddata = [0] * 64
            upperlimit = 32000
            lowerlimit = 300
            # payload is 64 words (big-endian 16-bit)
            for i in range(0, 128, 2):
                tval = (payload[i] << 8) | payload[i+1]
                boarddata[i // 2] = 1 if (lowerlimit <= tval <= upperlimit) else 0

            if field is not None:
                return boarddata[field]
            return boarddata

        except Exception:
            # transient read/parse error—retry
            time.sleep(sleep_between)

    # Final fallback so callers (like getText) never crash
    if field is not None:
        return 0
    return [0] * 64

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
    timeout_local = time.time() + 5
    while len(resp) < 7 and time.time() < timeout_local:
        sendPacket(bytearray([152]), b'')
        try:
            resp = _ser_read(1000)
        except:
            pass
        if len(resp) >= 7 and resp[0] == 181:
            vall = (resp[5] >> 5) & 7
            if vall == 1:
                return 1
            else:
                return 0
    return -1

def getBatteryLevel():
    # Returns a number 0 - 20 representing battery level of the board
    resp = ""
    timeout_local = time.time() + 5
    while len(resp) < 7 and time.time() < timeout_local:
        sendPacket(bytearray([152]), b'')
        try:
            resp = _ser_read(1000)
        except:
            pass
    if len(resp) < 7:
        return -1
    else:
        if resp[0] == 181:
            vall = resp[5] & 31
            return vall

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

# Start of event-driven helpers
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

            buttonPress = 0
            if not standby:
                #Hold fields activity on standby
                if fieldcallback != None:
                    try:
                        sendPacket(b'\x83', b'')
                        expect = bytearray(b'\x85\x00\x06' + addr1.to_bytes(1, byteorder='big') + addr2.to_bytes(1, byteorder='big'))
                        expect.append(checksum(expect))
                        resp = _ser_read(10000)
                        resp = bytearray(resp)
                        if (bytearray(resp) != expect):
                            if (resp[0] == 133 and resp[1] == 0):
                                for x in range(0, len(resp) - 1):
                                    if (resp[x] == 64):
                                        fieldHex = resp[x + 1]
                                        newsquare = rotateFieldHex(fieldHex)
                                        fieldcallback(newsquare + 1)
                                        to = time.time() + tout
                                    if (resp[x] == 65):
                                        fieldHex = resp[x + 1]
                                        newsquare = rotateFieldHex(fieldHex)
                                        fieldcallback((newsquare + 1) * -1)
                                        to = time.time() + tout
                    except:
                        pass

            try:
                sendPacket(b'\x94', b'')
                expect = bytearray(b'\xb1\x00\x06' + addr1.to_bytes(1, byteorder='big') + addr2.to_bytes(1, byteorder='big'))
                expect.append(checksum(expect))
                resp = _ser_read(10000)
                resp = bytearray(resp)
                if not standby:
                    #Disable these buttons on standby
                    if (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0501000000007d47"):
                        to = time.time() + tout
                        buttonPress = BTNBACK  # BACK
                    if (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0510000000007d17"):
                        to = time.time() + tout
                        buttonPress = BTNTICK  # TICK
                    if (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0508000000007d3c"):
                        to = time.time() + tout
                        buttonPress = BTNUP  # UP
                    if (resp.hex()[:-2] == "b10010" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a05020000000061"):
                        to = time.time() + tout
                        buttonPress = BTNDOWN  # DOWN
                    if (resp.hex()[:-2] == "b10010" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0540000000006d"):
                        to = time.time() + tout
                        buttonPress = BTNHELP   # HELP
                if (resp.hex()[:-2] == "b10010" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0504000000002a"):
                    breaktime = time.time() + 0.5
                    beep(SOUND_GENERAL)
                    while time.time() < breaktime:
                        sendPacket(b'\x94', b'')
                        expect = bytearray(b'\xb1\x00\x06' + addr1.to_bytes(1, byteorder='big') + addr2.to_bytes(1, byteorder='big'))
                        expect.append(checksum(expect))
                        resp = _ser_read(1000)
                        resp = bytearray(resp)
                        if resp.hex().startswith("b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0500040"):
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
                                clearSerial()
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
            except:
                pass
            try:
                # Sending 152 to the controller provides us with battery information
                # Do this every 15 seconds and fill in the globals
                if time.time() - batterylastchecked > 15:
                    resp = ""
                    timeout_batt = time.time() + 4
                    while len(resp) < 7 and time.time() < timeout_batt:
                        sendPacket(bytearray([152]), b'')
                        try:
                            resp = _ser_read(1000)
                        except:
                            pass
                    if len(resp) >= 7 and resp[0] == 181:
                        batterylastchecked = time.time()
                        batterylevel = resp[5] & 31
                        vall = (resp[5] >> 5) & 7
                        if vall == 1 or vall == 2:
                            chargerconnected = 1
                        else:
                            chargerconnected = 0
            except:
                pass
            time.sleep(0.05)
            if buttonPress != 0:
                to = time.time() + tout
                keycallback(buttonPress)
        else:
            # If pauseEvents() hold timeout in the thread
            to = time.time() + 100000
            events_paused = True

        if time.time() - loopstart > 30:
            to = time.time() + tout
        time.sleep(0.05)
    else:
        # Timeout reached, while loop breaks. Shutdown.
        logging.debug('Timeout. Shutting doen')
        shutdown()

def subscribeEvents(keycallback, fieldcallback, timeout=100000):
    # Called by any program wanting to subscribe to events
    # Arguments are firstly the callback function for key presses, secondly for piece lifts and places
    clearSerial()
    eventsthreadpointer = threading.Thread(target=eventsThread, args=([keycallback, fieldcallback, timeout]))
    eventsthreadpointer.daemon = True
    eventsthreadpointer.start()

def pauseEvents():
    global eventsrunning
    eventsrunning = 0
    time.sleep(0.5)

def unPauseEvents():
    global eventsrunning
    eventsrunning = 1
