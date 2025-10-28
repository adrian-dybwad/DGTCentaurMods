# DGT Centaur Pegasus Emulation
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

import dbus
from DGTCentaurMods.thirdparty.advertisement import Advertisement
from DGTCentaurMods.thirdparty.service import Application, Service, Characteristic, Descriptor
from DGTCentaurMods.board import *
from DGTCentaurMods.display.ui_components import AssetManager
import time
import threading
import os
import pathlib
from DGTCentaurMods.board import *
from DGTCentaurMods.display import epaper
from PIL import Image, ImageDraw

kill = 0
bt_connected = False
events_resubscribed = False
 


epaper.initEpaper()

# Initialization handled by async_centaur.py - no manual polling needed

statusbar = epaper.statusBar()
statusbar.start()

def displayLogo():
    filename = str(AssetManager.get_resource_path("logo_mods_screen.jpg"))
    lg = Image.open(filename)
    lg = lg.resize((48,112))
    return epaper.epaperbuffer.paste(lg,(0,20))

statusbar.print()
epaper.writeText(1,"           PEGASUS")
epaper.writeText(2,"              MODE")
epaper.writeText(10,"PCS-REVII-081500")
epaper.writeText(11,"Use back button")
epaper.writeText(12,"to exit mode")
epaper.writeText(13,"Await Connect")
displayLogo()

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
NOTIFY_TIMEOUT = 5000
DGT_MSG_BOARD_DUMP = 134
DGT_MSG_FIELD_UPDATE = 142
DGT_MSG_UNKNOWN_143 = 143
DGT_MSG_UNKNOWN_144 = 144
DGT_MSG_SERIALNR = 145
DGT_MSG_TRADEMARK = 146
DGT_MSG_VERSION = 147
DGT_MSG_HARDWARE_VERSION = 150
DGT_MSG_BATTERY_STATUS = 160
DGT_MSG_LONG_SERIALNR = 162
DGT_MSG_UNKNOWN_163 = 163
DGT_MSG_LOCK_STATE = 164
DGT_MSG_DEVKEY_STATE = 165

# Global event callbacks so we can subscribe even before notifications are enabled
def pegasus_key_callback(*args):
    """Handle key events regardless of notification state."""
    try:
        keycode = None
        keyname = None
        if len(args) == 1:
            keycode = args[0]
        elif len(args) >= 2:
            keycode, keyname = args[0], args[1]
        print(f"[Pegasus] Key event: code={keycode} name={keyname}")
        if (keyname == 'BACK') or (keycode == board.BTNBACK):
            print("[Pegasus] Back button pressed -> exit")
            app.quit()
    except Exception as e:
        print(f"[Pegasus] key callback error: {e}")

def pegasus_field_callback(*args):
    """Handle field events; forward to client only if TX notifications are on."""
    try:
        # Accept either signed int or (field, piece_event)
        if len(args) == 1:
            signed_field = int(args[0])
            piece_event = 0x40 if signed_field >= 0 else 0x41
            idx = abs(signed_field) - 1
        else:
            idx = int(args[0])
            piece_event = int(args[1])
        if idx < 0:
            idx = 0
        if idx > 63:
            idx = 63
        print(f"[Pegasus] Field event idx={idx} evt={hex(piece_event)}")
        tx = UARTService.tx_obj
        if tx is not None and getattr(tx, 'notifying', False):
            try:
                # Send unrotated idx to match board dump indexing expected by app
                evt = 0 if piece_event == 0x40 else 1
                msg = bytearray([idx, evt])
                print(f"[Pegasus] FIELD_UPDATE idx={idx} event={evt}")
                tx.sendMessage(DGT_MSG_FIELD_UPDATE, msg)
                # Flash LED on place to mirror app feedback
                if piece_event == 0x41:
                    try:
                        board.led(idx)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[Pegasus] field send error: {e}")
    except Exception as e:
        print(f"[Pegasus] field callback error: {e}")

# Subscribe immediately so key/back works even before BLE notifications are enabled
try:
    board.subscribeEvents(pegasus_key_callback, pegasus_field_callback, timeout=100000)
    print("[Pegasus] Subscribed to board events")
except Exception as e:
    print(f"[Pegasus] Failed to subscribe events: {e}")

class UARTAdvertisement(Advertisement):
    def __init__(self, index):
        Advertisement.__init__(self, index, "peripheral")
        self.add_local_name("PCS-REVII-081500")
        #self.add_local_name("DGT_PEGASUS_EMULATION")
        self.include_tx_power = True
        self.add_service_uuid("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")

class UARTService(Service):

    tx_obj = None

    UART_SVC_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"

    def __init__(self, index):
        Service.__init__(self, index, self.UART_SVC_UUID, True)
        self.add_characteristic(UARTTXCharacteristic(self))
        self.add_characteristic(UARTRXCharacteristic(self))

class UARTRXCharacteristic(Characteristic):
    UARTRX_CHARACTERISTIC_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

    def __init__(self, service):

        Characteristic.__init__(
                self, self.UARTRX_CHARACTERISTIC_UUID,
                ["write"], service)

    def sendMessage(self, msgtype, data):
        # Send a message of the given type
        tosend = bytearray()
        # First the message type, then the length
        tosend.append(msgtype)
        lo = (len(data)+3) & 127
        hi = ((len(data)+3) >> 7) & 127
        tosend.append(hi)
        tosend.append(lo)
        for x in range(0, len(data)):
            tosend.append(data[x])
        try:
            preview = ' '.join(f'{b:02x}' for b in tosend[:16])
            print(f"[Pegasus TX] type={msgtype} len={len(data)} total={len(tosend)} {preview}...")
        except Exception:
            pass
        UARTService.tx_obj.updateValue(tosend)

    def WriteValue(self, value, options):
        # When the remote device writes data, it comes here
        global bt_connected
        print("Received")
        print(value)
        # Consider any write as an active connection from the client
        if not bt_connected:
            bt_connected = True
            epaper.writeText(13, "              ")
            epaper.writeText(13, "Connected")
            try:
                board.beep(board.SOUND_GENERAL)
            except Exception:
                pass
        bytes = bytearray()
        for i in range(0,len(value)):
            bytes.append(value[i])
        print(len(bytes))
        print(bytes)
        processed = 0
        if len(bytes) == 1 and bytes[0] == ord('B'):
            bs = board.getBoardState()
            self.sendMessage(DGT_MSG_BOARD_DUMP, bs)
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('D'):
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('E'):
            self.sendMessage(DGT_MSG_SERIALNR, [ord('A'),ord('B'),ord('C'),ord('D'),ord('E')])
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('F'):
            self.sendMessage(DGT_MSG_UNKNOWN_144, [0])
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('G'):
            # Return a DGT_MSG_TRADEMARK but it must contain
            # Digital Game Technology\r\nCopyright (c)
            tm = b'Digital Game Technology\r\nCopyright (c) 2021 DGT\r\nsoftware version: 1.00, build: 210722\r\nhardware version: 1.00, serial no: PXXXXXXXXX'
            self.sendMessage(DGT_MSG_TRADEMARK, tm)
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('H'):
            self.sendMessage(DGT_MSG_HARDWARE_VERSION,[1,0])
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('I'):
            self.sendMessage(DGT_MSG_UNKNOWN_143, [])
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('L'):
            self.sendMessage(DGT_MSG_BATTERY_STATUS, [0x58,0,0,0,0,0,0,0,2])
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('M'):
            self.sendMessage(DGT_MSG_VERSION, [1,0])
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('U'):
            self.sendMessage(DGT_MSG_LONG_SERIALNR, [ord('A'),ord('B'),ord('C'),ord('D'),ord('E'),ord('F'),ord('G'),ord('H'),ord('I'),ord('J')])
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('V'):
            self.sendMessage(DGT_MSG_UNKNOWN_163, [0])
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('Y'):
            self.sendMessage(DGT_MSG_LOCK_STATE, [0])
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('Z'):
            self.sendMessage(DGT_MSG_DEVKEY_STATE, [0])
            processed = 1
        if len(bytes) == 1 and bytes[0] == ord('@'):
            # This looks like some sort of reset, but it is used mid game after a piece has been moved sometimes.
            # Maybe it does something with LEDs as it was followed by a switching off leds
            # Let's report the battery status here - 0x58 (or presumably higher as there is rounding) = 100%
            # As I can't read centaur battery percentage here - fake it
            self.sendMessage(DGT_MSG_BATTERY_STATUS, [0x58,0,0,0,0,0,0,0,2])
            processed=1
        if bytes[0] == 99:
            # This registers the board with a developer key. No clue what this actually does
            msg = b'\x01' # Guessing, this isn't checked
            self.sendMessage(DGT_MSG_DEVKEY_STATE, msg)
            processed=1
        if len(bytes) == 4:
            if bytes[0] == 96 and bytes[1] == 2 and bytes[2] == 0 and bytes[3] == 0:
                # ledsOff
                print("leds off")
                board.ledsOff()
                # Let's report the battery status here - 0x58 (or presumably higher as there is rounding) = 100%
                # As I can't read centaur battery percentage here - fake it
                self.sendMessage(DGT_MSG_BATTERY_STATUS, [0x58,0,0,0,0,0,0,0,2])
                processed=1
        if processed == 0 and bytes[0] == 96:
            # LEDS control from mobile app
            # Format: 96, [len-2], 5, speed, mode, intensity, fields..., 0
            print(f"[Pegasus RX LED] raw: {' '.join(f'{b:02x}' for b in bytes)}")
            if bytes[2] == 5:
                ledspeed = int(bytes[3])
                mode = int(bytes[4])
                intensity_in = int(bytes[5])
                fields_hw = []
                for x in range(6, len(bytes)-1):
                    fields_hw.append(int(bytes[x]))
                # Map Pegasus/firmware index to board API index
                def hw_to_board(i):
                    return (7 - (i // 8)) * 8 + (i % 8)
                fields_board = [hw_to_board(f) for f in fields_hw]
                print(f"[Pegasus RX LED] speed={ledspeed} mode={mode} intensity={intensity_in} hw={fields_hw} -> board={fields_board}")
                # Normalize intensity to 1..10 for board.* helpers
                intensity = max(1, min(10, intensity_in))
                try:
                    if len(fields_board) == 0:
                        board.ledsOff()
                        print("[Pegasus RX LED] ledsOff()")
                    elif len(fields_board) == 1:
                        board.led(fields_board[0], intensity=intensity)
                        print(f"[Pegasus RX LED] led({fields_board[0]}, intensity={intensity})")
                    else:
                        # Use first two as from/to; extras are ignored for now
                        fb, tb = fields_board[0], fields_board[1]
                        board.ledFromTo(fb, tb, intensity=intensity)
                        print(f"[Pegasus RX LED] ledFromTo({fb},{tb}, intensity={intensity})")
                        if mode == 1:
                            time.sleep(0.5)
                            board.ledsOff()
                except Exception as e:
                    print(f"[Pegasus RX LED] error driving LEDs: {e}")
                processed = 1
        if processed==0:
            print("Un-coded command")
            UARTService.tx_obj.updateValue(bytes)


class UARTTXCharacteristic(Characteristic):
    UARTTX_CHARACTERISTIC_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

    def __init__(self, service):

        Characteristic.__init__(
                self, self.UARTTX_CHARACTERISTIC_UUID,
                ["read", "notify"], service)
        self.notifying = False

    def on_key_event(self, *args):
        """Callback when key is pressed (supports 1-arg id or 2-arg id,name)"""
        keycode = None
        keyname = None
        if len(args) == 1:
            keycode = args[0]
        elif len(args) >= 2:
            keycode, keyname = args[0], args[1]
        print(f"Key event: code={keycode} name={keyname}")
        if (keyname == 'BACK') or (keycode == board.BTNBACK):
            print("Back button pressed")
            app.quit()

    def on_field_event(self, field):
        """Callback when piece is lifted (0x40) or placed (0x41)"""
        print(f"Field event: {field}")
        piece_event = 0x40 if field >= 0 else 0x41
        # Convert legacy signed value to 0..63 index
        field = abs(field) - 1
        if field < 0:
            field = 0
        if field > 63:
            field = 63
        print(f"Field: {field}")
        print(f"Piece event: {piece_event}")
        if self.notifying:
            msg = bytearray()
            msg.append(field)
            # piece_event is 0x40 for lift, 0x41 for place
            # Pegasus protocol uses 0 for lift, 1 for place
            msg.append(0 if piece_event == 0x40 else 1)
            self.sendMessage(DGT_MSG_FIELD_UPDATE, msg)

    def sendMessage(self, msgtype, data):
        # Send a message of the given type
        tosend = bytearray()
        # First the message type, then the length
        tosend.append(msgtype)
        lo = (len(data)+3) & 127
        hi = ((len(data)+3) >> 7) & 127
        tosend.append(hi)
        tosend.append(lo)
        for x in range(0, len(data)):
            tosend.append(data[x])
        UARTService.tx_obj.updateValue(tosend)

    def StartNotify(self):
        print("started notifying")
        epaper.writeText(13, "              ")
        epaper.writeText(13, "Connected")
        board.clearBoardData()
        board.beep(board.SOUND_GENERAL)
        UARTService.tx_obj = self
        self.notifying = True
        board.ledsOff()
        # Ensure event thread is running in case it was paused earlier
        try:
            board.unPauseEvents()
            print("[Pegasus] Events unpaused")
        except Exception as e:
            print(f"[Pegasus] unPauseEvents failed: {e}")
        # Re-subscribe after notify to guarantee active callbacks in this process
        global events_resubscribed
        try:
            if not events_resubscribed:
                board.subscribeEvents(pegasus_key_callback, pegasus_field_callback, timeout=100000)
                events_resubscribed = True
                print("[Pegasus] Events re-subscribed post-notify")
        except Exception as e:
            print(f"[Pegasus] post-notify subscribe failed: {e}")
        # Send initial board dump so client can sync
        try:
            bs = board.getBoardState()
            self.sendMessage(DGT_MSG_BOARD_DUMP, bs)
            print(f"[Pegasus] Sent BOARD_DUMP len={len(bs)}")
        except Exception as e:
            print(f"[Pegasus] BOARD_DUMP failed: {e}")
        
        
        # TODO: Let's report the battery status here - 0x58 (or presumably higher as there is rounding) = 100%
        # As I can't read centaur battery percentage here - fake it
        #msg = b'\x58'
        #self.sendMessage(DGT_MSG_BATTERY_STATUS, msg)
        return self.notifying

    def StopNotify(self):
        if not self.notifying:
            return
        self.notifying = False
        
        # Note: board.subscribeEvents creates a daemon thread that will be cleaned up
        # automatically when the process exits. No explicit cleanup needed.
        
        return self.notifying

    def updateValue(self,value):
        if not self.notifying:
            return
        try:
            preview = ' '.join(f'{int(b):02x}' for b in value[:16])
            print(f"[Pegasus TX] GATT notify len={len(value)} {preview}...")
        except Exception:
            pass
        send = dbus.Array(signature=dbus.Signature('y'))
        for i in range(0,len(value)):
            send.append(dbus.Byte(value[i]))
        self.PropertiesChanged( GATT_CHRC_IFACE, { 'Value': send }, [])

    def ReadValue(self, options):
        value = 1
        return value

app = Application()
app.add_service(UARTService(0))
app.register()

adv = UARTAdvertisement(0)
adv.register()

try:
    app.run()
except KeyboardInterrupt:
    app.quit()
