#!/usr/bin/env python3
"""
BLE Sniffer - Test version using from-scratch GATT with correct UUIDs

Test 1: From-scratch GATT implementation (like original) but with correct UUIDs
"""

import argparse
import sys
import signal
import time
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# BlueZ D-Bus constants
BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'

# Millennium ChessLink BLE UUIDs - CORRECT UUIDs from game/millennium.py
MILLENNIUM_SERVICE_UUID = "49535343-FE7D-4AE5-8FA9-9FAFD205E455"
MILLENNIUM_TX_UUID = "49535343-1E4D-4BD9-BA61-23C647249616"  # Peripheral TX -> App RX
MILLENNIUM_RX_UUID = "49535343-8841-43F4-A8D4-ECBE34729BB3"  # App TX -> Peripheral RX

# Global state
mainloop = None
device_name = "MILLENNIUM CHESS"


def log(msg):
    """Simple timestamped logging"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def find_adapter(bus):
    """Find the first Bluetooth adapter"""
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'),
                               DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()
    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props:
            return o
    return None


class Advertisement(dbus.service.Object):
    """BLE Advertisement"""
    
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, bus, index, name, include_service_uuid=False):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = 'peripheral'
        self.local_name = name
        self.include_tx_power = True
        self.include_service_uuid = include_service_uuid
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        properties['LocalName'] = dbus.String(self.local_name)
        properties['IncludeTxPower'] = dbus.Boolean(self.include_tx_power)
        if self.include_service_uuid:
            properties['ServiceUUIDs'] = dbus.Array([MILLENNIUM_SERVICE_UUID], signature='s')
        return {LE_ADVERTISEMENT_IFACE: properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArguments',
                'Invalid interface: ' + interface)
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        log(f"Advertisement released: {self.path}")


class Application(dbus.service.Object):
    """GATT Application"""
    
    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
        return response


class Service(dbus.service.Object):
    """GATT Service"""
    
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    self.get_characteristic_paths(),
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        return [chrc.get_path() for chrc in self.characteristics]

    def get_characteristics(self):
        return self.characteristics


class Characteristic(dbus.service.Object):
    """GATT Characteristic base class"""

    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_CHRC_IFACE:
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArguments',
                'Invalid interface: ' + interface)
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        log(f"ReadValue called on {self.uuid}")
        return []

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        log(f"WriteValue called on {self.uuid}")

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        log(f"StartNotify called on {self.uuid}")

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        log(f"StopNotify called on {self.uuid}")

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class TXCharacteristic(Characteristic):
    """TX characteristic - notify only, no read"""
    
    tx_instance = None
    
    def __init__(self, bus, index, service):
        # Only notify flag - no read
        Characteristic.__init__(self, bus, index, MILLENNIUM_TX_UUID,
                                ['notify'], service)
        self.notifying = False
        TXCharacteristic.tx_instance = self
        log(f"TX Characteristic created: {MILLENNIUM_TX_UUID}")
        log(f"  Flags: ['notify']")

    def StartNotify(self):
        log("TX StartNotify: Client subscribing to notifications")
        self.notifying = True
        log("TX StartNotify: Notifications enabled")

    def StopNotify(self):
        log("TX StopNotify: Client unsubscribed")
        self.notifying = False

    def send_notification(self, data):
        if not self.notifying:
            return
        value = dbus.Array([dbus.Byte(b) for b in data], signature='y')
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])


class RXCharacteristic(Characteristic):
    """RX characteristic - write and write-without-response"""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, MILLENNIUM_RX_UUID,
                                ['write', 'write-without-response'], service)
        log(f"RX Characteristic created: {MILLENNIUM_RX_UUID}")
        log(f"  Flags: ['write', 'write-without-response']")

    def WriteValue(self, value, options):
        try:
            bytes_data = bytearray([int(b) for b in value])
            hex_str = ' '.join(f'{b:02x}' for b in bytes_data)
            ascii_str = ''.join(chr(b & 127) if 32 <= (b & 127) < 127 else '.' for b in bytes_data)
            
            log(f"RX WriteValue: {len(bytes_data)} bytes")
            log(f"  Hex: {hex_str}")
            log(f"  ASCII (stripped parity): {ascii_str}")
            
            if len(bytes_data) > 0:
                cmd = chr(bytes_data[0] & 127)
                log(f"  Command: '{cmd}' (0x{bytes_data[0]:02x})")
                self._handle_command(cmd, bytes_data)
        except Exception as e:
            log(f"Error in WriteValue: {e}")
            import traceback
            log(traceback.format_exc())

    def _handle_command(self, cmd, data):
        if cmd == 'V':
            log("  -> Responding with version: v3130")
            self._send_response("v3130")
        elif cmd == 'I':
            log("  -> Responding with identity: i0055mm")
            self._send_response("i0055mm\n")
        elif cmd == 'S':
            log("  -> Responding with board state")
            board_state = "sRNBQKBNRPPPPPPPP................................pppppppprnbqkbnr"
            self._send_response(board_state)
        elif cmd == 'W':
            if len(data) >= 5:
                h1, h2, h3, h4 = [data[i] & 127 for i in range(1, 5)]
                log(f"  -> Write E2ROM: addr={chr(h1)}{chr(h2)} value={chr(h3)}{chr(h4)}")
                self._send_response('w' + chr(h1) + chr(h2) + chr(h3) + chr(h4))
        elif cmd == 'L':
            log(f"  -> LED pattern command ({len(data)} bytes)")
            self._send_response("l")
        else:
            log(f"  -> Unknown command '{cmd}', no response")

    def _send_response(self, txt):
        if TXCharacteristic.tx_instance is None:
            log("  -> Cannot send: TX not initialized")
            return
        if not TXCharacteristic.tx_instance.notifying:
            log("  -> Cannot send: notifications not enabled")
            return
        
        # Build response with parity and checksum
        cs = 0
        tosend = bytearray()
        for ch in txt:
            byte = ord(ch) & 127
            par = 1
            temp = byte
            for _ in range(7):
                par ^= (temp & 1)
                temp >>= 1
            tosend.append(byte | (128 if par else 0))
            cs ^= ord(ch)
        h = f"{cs:02x}"
        for c in h:
            byte = ord(c) & 127
            par = 1
            temp = byte
            for _ in range(7):
                par ^= (temp & 1)
                temp >>= 1
            tosend.append(byte | (128 if par else 0))
        
        log(f"  -> Sending: {tosend.hex()}")
        TXCharacteristic.tx_instance.send_notification(tosend)


class MillenniumService(Service):
    """Millennium ChessLink service"""
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, MILLENNIUM_SERVICE_UUID, True)
        self.add_characteristic(TXCharacteristic(bus, 0, self))
        self.add_characteristic(RXCharacteristic(bus, 1, self))
        log(f"Service created: {MILLENNIUM_SERVICE_UUID}")


def signal_handler(signum, frame):
    global mainloop
    log(f"Received signal {signum}, exiting...")
    if mainloop:
        mainloop.quit()
    sys.exit(0)


def main():
    global mainloop, device_name
    
    parser = argparse.ArgumentParser(description="BLE Sniffer - Millennium ChessLink emulator for debugging")
    parser.add_argument("--name", default="MILLENNIUM CHESS", help="BLE device name")
    parser.add_argument("--advertise-uuid", action="store_true", 
                        help="Include service UUID in advertisement (some apps scan by UUID)")
    args = parser.parse_args()
    device_name = args.name
    
    log("=" * 60)
    log("BLE Sniffer - Millennium ChessLink")
    log(f"Device name: {device_name}")
    log(f"Advertise service UUID: {args.advertise_uuid}")
    log("=" * 60)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    mainloop = GLib.MainLoop()
    
    adapter = find_adapter(bus)
    if not adapter:
        log("ERROR: No Bluetooth adapter found")
        return
    log(f"Found Bluetooth adapter: {adapter}")
    
    # Create and register GATT application
    app = Application(bus)
    app.add_service(MillenniumService(bus, 0))
    
    gatt_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter),
        GATT_MANAGER_IFACE)
    
    log("Registering GATT application...")
    gatt_manager.RegisterApplication(
        app.get_path(), {},
        reply_handler=lambda: log("GATT application registered"),
        error_handler=lambda e: log(f"Failed to register GATT: {e}"))
    
    # Create and register advertisement
    adv = Advertisement(bus, 0, device_name, include_service_uuid=args.advertise_uuid)
    
    ad_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter),
        LE_ADVERTISING_MANAGER_IFACE)
    
    log("Registering advertisement...")
    ad_manager.RegisterAdvertisement(
        adv.get_path(), {},
        reply_handler=lambda: log("Advertisement registered"),
        error_handler=lambda e: log(f"Failed to register advertisement: {e}"))
    
    log("")
    log("Waiting for BLE connections...")
    log("Connect with HIARCS to test")
    log("")
    
    try:
        mainloop.run()
    except Exception as e:
        log(f"Error: {e}")
    
    log("Exiting")


if __name__ == "__main__":
    main()
