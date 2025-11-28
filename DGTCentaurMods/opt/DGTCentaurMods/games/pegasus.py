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
from DGTCentaurMods.asset_manager import AssetManager
from DGTCentaurMods.epaper import SplashScreen, TextWidget
import time
import threading
import os
import pathlib
from DGTCentaurMods.board import *
from PIL import Image, ImageDraw
from DGTCentaurMods.board.logging import log
import signal
import sys
from DGTCentaurMods.thirdparty.bletools import BleTools

kill = 0
bt_connected = False
events_resubscribed = False
 


promise = board.init_display()
if promise:
	try:
		promise.result(timeout=10.0)
	except Exception as e:
		log.warning(f"Error initializing display: {e}")

# Initialization handled by async_centaur.py - no manual polling needed


def displayLogo():
    filename = str(AssetManager.get_resource_path("logo_mods_screen.jpg"))
    lg = Image.open(filename).resize((48, 112))
    # widgets.draw_image(lg, 0, 20)

board.display_manager.add_widget(TextWidget(0, 20, 128, 100, "PEGASUS MODE", background=3, font_size=18))

board.display_manager.add_widget(TextWidget(0, 40, 128, 100, "PCS-REVII-081500"))
board.display_manager.add_widget(TextWidget(0, 60, 128, 100, "Use back button"))
board.display_manager.add_widget(TextWidget(0, 80, 128, 100, "to exit mode"))
board.display_manager.add_widget(TextWidget(0, 100, 128, 100, "Await Connect"))

#widgets.write_text(1,"           PEGASUS")
#widgets.write_text(2,"              MODE")
#widgets.write_text(10,"PCS-REVII-081500")
#widgets.write_text(11,"Use back button")
#widgets.write_text(12,"to exit mode")
#widgets.write_text(13,"Await Connect")

board.display_manager.add_widget(SplashScreen(message="PEGASUS MODE"))
#displayLogo()

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
def _key_callback(key):
    """Handle key events regardless of notification state."""
    try:
        log.info(f"[Pegasus] Key event: {key}")
        if (key == board.Key.BACK):
            log.info("[Pegasus] Back button pressed -> exit")
            cleanup()
            app.quit()
    except Exception as e:
        log.info(f"[Pegasus] key callback error: {e}")

def _field_callback(piece_event, field, time_in_seconds):
    """Handle field events; forward to client only if TX notifications are on."""
    try:
        field_hex = board.rotateFieldHex(field)
        log.info(f"[Pegasus] piece_event={piece_event==0 and 'LIFT' or 'PLACE'} field_hex={field_hex} time_in_seconds={time_in_seconds}")
        tx = UARTService.tx_obj
        if tx is not None and getattr(tx, 'notifying', False):
            try:
                # Send unrotated idx to match board dump indexing expected by app
                msg = bytearray([field_hex, piece_event])
                log.info(f"[Pegasus] FIELD_UPDATE msg={' '.join(f'{b:02x}' for b in msg)}")
                tx.sendMessage(DGT_MSG_FIELD_UPDATE, msg)
                # Flash LED on place to mirror app feedback
                if piece_event == 1:
                    try:
                        log.info(f"[Pegasus] LEDing field {field}")
                        board.led(field)
                    except Exception:
                        pass
            except Exception as e:
                log.info(f"[Pegasus] field send error: {e}")
        else:
            log.info(f"[Pegasus] No TX object (tx={tx}) or not notifying (notifying={getattr(tx, 'notifying', False)})")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        log.info(f"[Pegasus] field callback error: {e}")

# Subscribe immediately so key/back works even before BLE notifications are enabled
try:
    board.subscribeEvents(_key_callback, _field_callback, timeout=100000)
    log.info("[Pegasus] Subscribed to board events")
except Exception as e:
    log.info(f"[Pegasus] Failed to subscribe events: {e}")

def cleanup():
    """Clean up BLE services and advertisements before exit."""
    try:
        log.info("[Pegasus] Cleaning up BLE services...")
        # Stop notifications
        if UARTService.tx_obj is not None:
            try:
                UARTService.tx_obj.StopNotify()
            except Exception as e:
                log.info(f"[Pegasus] Error stopping notify: {e}")
        
        # Unregister advertisement
        try:
            if 'adv' in globals():
                adapter = BleTools.find_adapter(adv.bus)
                ad_manager = dbus.Interface(
                    adv.bus.get_object("org.bluez", adapter),
                    "org.bluez.LEAdvertisingManager1")
                ad_manager.UnregisterAdvertisement(adv.get_path())
                log.info("[Pegasus] Advertisement unregistered")
        except Exception as e:
            log.info(f"[Pegasus] Error unregistering advertisement: {e}")
        
        # Unregister application
        try:
            if 'app' in globals():
                adapter = BleTools.find_adapter(app.bus)
                service_manager = dbus.Interface(
                    app.bus.get_object("org.bluez", adapter),
                    "org.bluez.GattManager1")
                service_manager.UnregisterApplication(app.get_path())
                log.info("[Pegasus] Application unregistered")
        except Exception as e:
            log.info(f"[Pegasus] Error unregistering application: {e}")
    except Exception as e:
        log.info(f"[Pegasus] Error in cleanup: {e}")

def signal_handler(signum, frame):
    """Handle termination signals."""
    log.info(f"[Pegasus] Received signal {signum}, cleaning up...")
    cleanup()
    try:
        if 'app' in globals():
            app.quit()
    except:
        pass
    sys.exit(0)

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

        # Accept both write and write-without-response; some clients use the latter
        Characteristic.__init__(
                self, self.UARTRX_CHARACTERISTIC_UUID,
                ["write", "write-without-response"], service)

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
            log.info(f"[Pegasus TX] type=0x{msgtype:02x} len={len(data)} total={len(tosend)} {preview}...")
        except Exception:
            pass
        UARTService.tx_obj.updateValue(tosend)

    def WriteValue(self, value, options):
        # When the remote device writes data, it comes here
        log.info(f"[Pegasus RX] len={len(value)} bytes: {' '.join(f'{b:02x}' for b in value)}")
        global bt_connected
        # Consider any write as an active connection from the client
        if not bt_connected:
            bt_connected = True
            # widgets.write_text(13, "              ")
            # widgets.write_text(13, "Connected")
            try:
                board.beep(board.SOUND_GENERAL)
            except Exception:
                pass
        bytes = bytearray()
        for i in range(0,len(value)):
            bytes.append(value[i])

        processed = 0
        if len(bytes) == 1 and (bytes[0] == ord('B') or bytes[0] == ord('b')):
            log.info("[Pegasus RX] 'B' (board dump) -> TX 0x86 BOARD_DUMP")
            try:
                log.info("[Pegasus RX] Getting board state")    
                bs = board.getBoardState()
                self.sendMessage(DGT_MSG_BOARD_DUMP, bs)
                processed = 1
            except Exception as e:
                log.info(f"[Pegasus RX] Error getting board state: {e}")
                import traceback
                traceback.print_exc()
                processed = 0
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
                log.info("leds off")
                board.ledsOff()
                # Let's report the battery status here - 0x58 (or presumably higher as there is rounding) = 100%
                # As I can't read centaur battery percentage here - fake it
                self.sendMessage(DGT_MSG_BATTERY_STATUS, [0x58,0,0,0,0,0,0,0,2])
                processed=1
        if processed == 0 and bytes[0] == 96:
            # LEDS control from mobile app
            # Format: 96, [len-2], 5, speed, mode, intensity, fields..., 0
            log.info(f"[Pegasus RX LED] raw: {' '.join(f'{b:02x}' for b in bytes)}")
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
                log.info(f"[Pegasus RX LED] speed={ledspeed} mode={mode} intensity={intensity_in} hw={fields_hw} -> board={fields_board}")
                # Normalize intensity to 1..10 for board.* helpers
                intensity = max(1, min(10, intensity_in))
                try:
                    if len(fields_board) == 0:
                        board.ledsOff()
                        log.info("[Pegasus RX LED] ledsOff()")
                    elif len(fields_board) == 1:
                        board.led(fields_board[0], intensity=intensity)
                        log.info(f"[Pegasus RX LED] led({fields_board[0]}, intensity={intensity})")
                    else:
                        # Use first two as from/to; extras are ignored for now
                        tb, fb = fields_board[0], fields_board[1]
                        board.ledFromTo(fb, tb, intensity=intensity)
                        log.info(f"[Pegasus RX LED] ledFromTo({fb},{tb}, intensity={intensity})")
                        if mode == 1:
                            time.sleep(0.5)
                            board.ledsOff()
                except Exception as e:
                    log.info(f"[Pegasus RX LED] error driving LEDs: {e}")
                processed = 1
        if processed==0:
            log.info("Un-coded command")
            UARTService.tx_obj.updateValue(bytes)


class UARTTXCharacteristic(Characteristic):
    UARTTX_CHARACTERISTIC_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

    def __init__(self, service):

        Characteristic.__init__(
                self, self.UARTTX_CHARACTERISTIC_UUID,
                ["read", "notify"], service)
        self.notifying = False

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
        log.info("[Pegasus] StartNotify begin")
        # Set tx_obj FIRST before any operations that might fail
        UARTService.tx_obj = self
        self.notifying = True
        
        # Now do operations that might fail
        try:
            # widgets.write_text(13, "              ")
            # widgets.write_text(13, "Connected")
            #board.clearBoardData()
            board.beep(board.SOUND_GENERAL)
            board.ledsOff()
        except Exception as e:
            log.info(f"[Pegasus] Error in StartNotify operations: {e}")
        # Ensure event thread is running in case it was paused earlier
        try:
            board.unPauseEvents()
            log.info("[Pegasus] Events unpaused")
        except Exception as e:
            log.info(f"[Pegasus] unPauseEvents failed: {e}")
        # Re-subscribe after notify to guarantee active callbacks in this process
        global events_resubscribed
        try:
            if not events_resubscribed:
                board.subscribeEvents(_key_callback, _field_callback, timeout=100000)
                events_resubscribed = True
                log.info("[Pegasus] Events re-subscribed post-notify")
        except Exception as e:
            log.info(f"[Pegasus] post-notify subscribe failed: {e}")
        # Do NOT send unsolicited board dump; only respond when phone requests 'B'
        
        
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
            log.info(f"[Pegasus TX] GATT notify len={len(value)} {preview}...")
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

# Register signal handlers for clean shutdown
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

try:
    app.run()
except KeyboardInterrupt:
    cleanup()
    app.quit()
except Exception as e:
    log.info(f"[Pegasus] Unexpected error: {e}")
    cleanup()
    app.quit()
