#!/usr/bin/env python3
"""
Minimal BLE peripheral sniffer for debugging HIARCS connection issues.

This uses the same thirdparty modules and structure as game/millennium.py
which is known to work with HIARCS.

The purpose is to log all incoming BLE writes to understand what HIARCS
expects from a Millennium ChessLink board.
"""

import argparse
import time
import threading
import sys
import signal

import dbus
import dbus.service
import dbus.mainloop.glib

try:
    from gi.repository import GObject
except ImportError:
    import gobject as GObject

# Use the same thirdparty modules as game/millennium.py
from DGTCentaurMods.thirdparty.advertisement import Advertisement
from DGTCentaurMods.thirdparty.service import Application, Service, Characteristic, NotSupportedException
from DGTCentaurMods.thirdparty.bletools import BleTools

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

# Millennium ChessLink UUIDs (same as game/millennium.py)
MILLENNIUM_SERVICE_UUID = "49535343-FE7D-4AE5-8FA9-9FAFD205E455"
MILLENNIUM_TX_UUID = "49535343-1E4D-4BD9-BA61-23C647249616"  # Peripheral TX -> App RX
MILLENNIUM_RX_UUID = "49535343-8841-43F4-A8D4-ECBE34729BB3"  # App TX -> Peripheral RX

# Global state
device_name = "MILLENNIUM CHESS"


def log(msg):
    """Simple logging with timestamp."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def odd_par(b):
    """Calculate odd parity for a byte (same as game/millennium.py)."""
    byte = b & 127
    par = 1
    for _ in range(7):
        bit = byte & 1
        byte = byte >> 1
        par = par ^ bit
    if par == 1:
        byte = b | 128
    else:
        byte = b & 127
    return byte


class SnifferAdvertisement(Advertisement):
    """BLE advertisement - same structure as game/millennium.py"""
    
    def __init__(self, index):
        Advertisement.__init__(self, index, "peripheral")
        self.add_local_name(device_name)
        self.include_tx_power = True
        # NOTE: Do NOT advertise service UUID in advertisement packet
        # Real Millennium Chess board does not include service UUIDs in advertisement
        log(f"BLE Advertisement initialized with name: {device_name}")
    
    def register_ad_callback(self):
        log("BLE advertisement registered successfully")
    
    def register_ad_error_callback(self, error):
        log(f"Failed to register BLE advertisement: {error}")
    
    def register(self):
        try:
            bus = BleTools.get_bus()
            adapter = BleTools.find_adapter(bus)
            log(f"Found Bluetooth adapter: {adapter}")
            
            ad_manager = dbus.Interface(
                bus.get_object("org.bluez", adapter),
                "org.bluez.LEAdvertisingManager1")
            
            options = {
                "MinInterval": dbus.UInt16(0x0014),  # 20ms
                "MaxInterval": dbus.UInt16(0x0098),  # 152.5ms
            }
            
            log(f"Registering advertisement at path: {self.get_path()}")
            ad_manager.RegisterAdvertisement(
                self.get_path(),
                options,
                reply_handler=self.register_ad_callback,
                error_handler=self.register_ad_error_callback)
        except Exception as e:
            log(f"Exception during BLE advertisement registration: {e}")
            import traceback
            log(traceback.format_exc())


class SnifferService(Service):
    """BLE UART service - same structure as game/millennium.py"""
    tx_obj = None
    
    def __init__(self, index):
        Service.__init__(self, index, MILLENNIUM_SERVICE_UUID, True)
        self.add_characteristic(SnifferTXCharacteristic(self))
        self.add_characteristic(SnifferRXCharacteristic(self))
        log(f"Service created: {MILLENNIUM_SERVICE_UUID}")


class SnifferRXCharacteristic(Characteristic):
    """RX characteristic - receives commands from BLE client"""
    
    def __init__(self, service):
        # Same flags as game/millennium.py
        flags = ["write", "write-without-response"]
        Characteristic.__init__(self, MILLENNIUM_RX_UUID, flags, service)
        log(f"RX Characteristic created: {MILLENNIUM_RX_UUID}")
        log(f"  Flags: {flags}")
    
    def WriteValue(self, value, options):
        """Log all incoming writes from the client."""
        global kill
        if kill:
            return
        
        try:
            bytes_data = bytearray()
            for i in range(len(value)):
                bytes_data.append(value[i])
            
            hex_str = ' '.join(f'{b:02x}' for b in bytes_data)
            ascii_str = ''.join(chr(b & 127) if 32 <= (b & 127) < 127 else '.' for b in bytes_data)
            
            log(f"RX WriteValue: {len(bytes_data)} bytes")
            log(f"  Hex: {hex_str}")
            log(f"  ASCII (stripped parity): {ascii_str}")
            log(f"  Options: {dict(options) if options else '{}'}")
            
            # Parse as Millennium command
            if len(bytes_data) > 0:
                cmd = chr(bytes_data[0] & 127)
                log(f"  Command: '{cmd}' (0x{bytes_data[0]:02x})")
                
                # Respond to known commands
                self._handle_command(cmd, bytes_data)
                
        except Exception as e:
            log(f"Error in WriteValue: {e}")
            import traceback
            log(traceback.format_exc())
    
    def _handle_command(self, cmd, data):
        """Handle known Millennium commands and send responses."""
        if cmd == 'V':
            # Version request
            log("  -> Responding with version: v3130")
            self._send_response("v3130")
        elif cmd == 'I':
            # Identity request
            log("  -> Responding with identity: i0055mm")
            self._send_response("i0055mm\n")
        elif cmd == 'S':
            # Status request - send initial board state
            log("  -> Responding with board state")
            # Starting position: RNBKQBNR/PPPPPPPP/8/8/8/8/pppppppp/rnbkqbnr
            board_state = "sRNBQKBNRPPPPPPPP................................pppppppprnbqkbnr"
            self._send_response(board_state)
        elif cmd == 'T':
            # Reset
            log("  -> Responding with reset ack: t")
            self._send_response("t")
        elif cmd == 'X':
            # Extinguish LEDs
            log("  -> Responding with LED ack: x")
            self._send_response("x")
        elif cmd == 'W':
            # Write E2ROM - format: W + 2 hex addr + 2 hex value + 2 checksum = 7 bytes
            if len(data) >= 5:
                h1 = data[1] & 127
                h2 = data[2] & 127
                h3 = data[3] & 127
                h4 = data[4] & 127
                addr_str = chr(h1) + chr(h2)
                val_str = chr(h3) + chr(h4)
                log(f"  -> Write E2ROM: addr={addr_str} value={val_str}")
                # Echo back the write confirmation
                self._send_response('w' + chr(h1) + chr(h2) + chr(h3) + chr(h4))
            else:
                log(f"  -> Write E2ROM: incomplete data ({len(data)} bytes)")
        elif cmd == 'R':
            # Read E2ROM - format: R + 2 hex addr + 2 checksum = 5 bytes
            if len(data) >= 3:
                h1 = data[1] & 127
                h2 = data[2] & 127
                addr_str = chr(h1) + chr(h2)
                log(f"  -> Read E2ROM: addr={addr_str}")
                # Return 00 as value
                self._send_response(chr(h1) + chr(h2) + '00')
            else:
                log(f"  -> Read E2ROM: incomplete data ({len(data)} bytes)")
        elif cmd == 'L':
            # LED pattern command
            log(f"  -> LED pattern command ({len(data)} bytes)")
            self._send_response("l")
        else:
            log(f"  -> Unknown command, no response")
    
    def _send_response(self, txt):
        """Send a Millennium protocol response via TX characteristic."""
        if SnifferService.tx_obj is None:
            log("  -> Cannot send: TX not initialized")
            return
        if not SnifferService.tx_obj.notifying:
            log("  -> Cannot send: notifications not enabled")
            return
        
        # Build response with parity and checksum (same as game/millennium.py)
        cs = 0
        tosend = bytearray()
        for ch in txt:
            tosend.append(odd_par(ord(ch)))
            cs = cs ^ ord(ch)
        h = "0x{:02x}".format(cs)
        h1 = h[2:3]
        h2 = h[3:4]
        tosend.append(odd_par(ord(h1)))
        tosend.append(odd_par(ord(h2)))
        
        log(f"  -> Sending: {tosend.hex()}")
        SnifferService.tx_obj.updateValue(tosend)


class SnifferTXCharacteristic(Characteristic):
    """TX characteristic - sends responses to BLE client via notifications.
    
    This matches game/millennium.py exactly:
    - Only "notify" flag (no "read")
    - Removes Value property from get_properties()
    - Raises NotSupportedException if ReadValue is called
    """
    
    def __init__(self, service):
        # Same flags as game/millennium.py - ONLY notify, no read
        flags = ["notify"]
        Characteristic.__init__(self, MILLENNIUM_TX_UUID, flags, service)
        self.notifying = False
        log(f"TX Characteristic created: {MILLENNIUM_TX_UUID}")
        log(f"  Flags: {flags}")
    
    def get_properties(self):
        """Override to ensure no Value property is exposed (matches real Millennium Chess board)."""
        props = Characteristic.get_properties(self)
        # Ensure no 'Value' property is in the properties dict
        if 'Value' in props.get(GATT_CHRC_IFACE, {}):
            del props[GATT_CHRC_IFACE]['Value']
            log("TX: Removed 'Value' property to match real board")
        return props
    
    @dbus.service.method("org.freedesktop.DBus.Properties",
                         in_signature='s',
                         out_signature='a{sv}')
    def GetAll(self, interface):
        """Override GetAll to ensure Value property is never returned."""
        if interface != GATT_CHRC_IFACE:
            from DGTCentaurMods.thirdparty.service import InvalidArgsException
            raise InvalidArgsException()
        
        props = self.get_properties()[GATT_CHRC_IFACE]
        if 'Value' in props:
            del props['Value']
        return props
    
    def ReadValue(self, options):
        """Real Millennium Chess board does NOT support ReadValue for TX characteristic."""
        log("TX ReadValue called - raising NotSupportedException (matches real board)")
        raise NotSupportedException()
    
    def StartNotify(self):
        """Called when BLE client subscribes to notifications."""
        log("TX StartNotify: Client subscribing to notifications")
        SnifferService.tx_obj = self
        self.notifying = True
        log("TX StartNotify: Notifications enabled")
        return self.notifying
    
    def StopNotify(self):
        """Called when BLE client unsubscribes from notifications."""
        if not self.notifying:
            return
        log("TX StopNotify: Client unsubscribed")
        self.notifying = False
        return self.notifying
    
    def updateValue(self, value):
        """Update the characteristic value and notify subscribers."""
        if not self.notifying:
            return
        send = dbus.Array(signature=dbus.Signature('y'))
        for i in range(len(value)):
            send.append(dbus.Byte(value[i]))
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': send}, [])


mainloop = None


def signal_handler(signum, frame):
    """Handle termination signals."""
    global mainloop
    log(f"Received signal {signum}, exiting...")
    if mainloop:
        mainloop.quit()
    else:
        sys.exit(0)


def main():
    global device_name, mainloop
    
    parser = argparse.ArgumentParser(description="BLE Sniffer for Millennium ChessLink protocol")
    parser.add_argument("--name", default="MILLENNIUM CHESS", help="BLE device name")
    args = parser.parse_args()
    
    device_name = args.name
    
    log("=" * 60)
    log("BLE Sniffer - Millennium ChessLink Protocol")
    log(f"Device name: {device_name}")
    log("Using same structure as game/millennium.py")
    log("=" * 60)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize D-Bus main loop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    mainloop = GObject.MainLoop()
    
    # Initialize BLE application (same as game/millennium.py)
    app = Application()
    app.add_service(SnifferService(0))
    
    # Register the application
    try:
        app.register()
        log("BLE application registered")
    except Exception as e:
        log(f"Failed to register BLE application: {e}")
        import traceback
        log(traceback.format_exc())
        return
    
    # Register advertisement
    adv = SnifferAdvertisement(0)
    try:
        adv.register()
    except Exception as e:
        log(f"Failed to register advertisement: {e}")
        import traceback
        log(traceback.format_exc())
    
    log("")
    log("Waiting for BLE connections...")
    log("Connect with HIARCS or other app to see incoming commands")
    log("")
    
    # Run main loop
    try:
        mainloop.run()
    except KeyboardInterrupt:
        log("Keyboard interrupt")
    except Exception as e:
        log(f"Error in main loop: {e}")
        import traceback
        log(traceback.format_exc())
    
    log("Exiting")


if __name__ == "__main__":
    main()
