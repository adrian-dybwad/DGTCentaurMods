#!/usr/bin/env python3
"""
BLE Sniffer - Minimal BLE peripheral for logging client behavior

This tool creates a minimal BLE peripheral that advertises as a Millennium ChessLink
board and logs all incoming data from connected clients without responding.

Purpose: Understand what commands apps like HIARCS send when connecting.

Usage:
    python -m DGTCentaurMods.tools.ble_sniffer [--name "MILLENNIUM CHESS"]
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

# Standard BLE Service UUIDs
GAP_SERVICE_UUID = "00001800-0000-1000-8000-00805F9B34FB"  # Generic Access Profile
DEVICE_INFO_SERVICE_UUID = "0000180A-0000-1000-8000-00805F9B34FB"  # Device Information

# Standard GAP Characteristic UUIDs
GAP_DEVICE_NAME_UUID = "00002A00-0000-1000-8000-00805F9B34FB"
GAP_APPEARANCE_UUID = "00002A01-0000-1000-8000-00805F9B34FB"

# Standard Device Information Characteristic UUIDs
DEVICE_INFO_MANUFACTURER_UUID = "00002A29-0000-1000-8000-00805F9B34FB"
DEVICE_INFO_MODEL_UUID = "00002A24-0000-1000-8000-00805F9B34FB"
DEVICE_INFO_FIRMWARE_UUID = "00002A26-0000-1000-8000-00805F9B34FB"

# Millennium ChessLink BLE UUIDs
MILLENNIUM_SERVICE_UUID = "49535343-FE7D-4AE5-8FA9-9FAFD205E455"
MILLENNIUM_RX_UUID = "0000FFF1-0000-1000-8000-00805F9B34FB"  # Write TO device
MILLENNIUM_TX_UUID = "0000FFF2-0000-1000-8000-00805F9B34FB"  # Notify FROM device

# Global state
mainloop = None
kill = False


def log(msg):
    """Simple timestamped logging"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} {msg}")


class Advertisement(dbus.service.Object):
    """BLE Advertisement"""
    
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, bus, index, name):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = 'peripheral'
        self.local_name = name
        self.service_uuids = [MILLENNIUM_SERVICE_UUID]
        self.include_tx_power = True
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        properties['LocalName'] = dbus.String(self.local_name)
        properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
        properties['IncludeTxPower'] = dbus.Boolean(self.include_tx_power)
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
    """GATT Characteristic"""
    
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
                'Notifying': self.notifying,
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

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        """D-Bus signal for property changes (used for notifications)"""
        pass


class RXCharacteristic(Characteristic):
    """RX Characteristic - receives writes from client (FFF1)"""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index,
            MILLENNIUM_RX_UUID,
            ['write', 'write-without-response'],
            service)
        log(f"RX Characteristic created: {MILLENNIUM_RX_UUID}")

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        """Log all incoming writes"""
        bytes_data = bytearray(int(b) for b in value)
        
        log("=" * 70)
        log(">>> WRITE RECEIVED on RX characteristic (FFF1)")
        log(f"    Length: {len(bytes_data)} bytes")
        log(f"    Hex: {' '.join(f'{b:02x}' for b in bytes_data)}")
        log(f"    Dec: {' '.join(f'{b:3d}' for b in bytes_data)}")
        
        # Try to decode as ASCII
        try:
            ascii_str = bytes_data.decode('utf-8', errors='replace')
            printable = ''.join(c if c.isprintable() else '.' for c in ascii_str)
            log(f"    ASCII: {printable}")
        except:
            pass
        
        # Check for Millennium protocol markers
        if len(bytes_data) > 0:
            first_byte = bytes_data[0]
            # Strip parity bit
            cmd = first_byte & 0x7F
            if 0x20 <= cmd <= 0x7E:
                log(f"    Possible Millennium command: '{chr(cmd)}' (0x{cmd:02x})")
        
        log("=" * 70)
        
        # Log options if any interesting ones
        if options:
            device = options.get('device', None)
            if device:
                log(f"    Device: {device}")


class TXCharacteristic(Characteristic):
    """TX Characteristic - sends notifications to client (FFF2)"""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index,
            MILLENNIUM_TX_UUID,
            ['read', 'notify'],
            service)
        log(f"TX Characteristic created: {MILLENNIUM_TX_UUID}")
        
        # Pre-computed board state response (starting position)
        # Format: 's' + 64 chars (board) + 2 char CRC
        # Board: RNBKQBNR PPPPPPPP ........ ........ ........ ........ pppppppp rnbkqbnr
        self._board_state = self._encode_board_state()
        self._notification_thread = None
        self._client_connected = False

    def _encode_board_state(self):
        """Encode a starting position board state with Millennium odd parity framing"""
        # Starting position in Millennium format (rank 1 to rank 8, a-h)
        # White pieces uppercase, black lowercase, empty = '.'
        board = "RNBKQBNRPPPPPPPP................................pppppppprnbkqbnr"
        
        # Build response: 's' + board + CRC
        response = "s" + board
        
        # Calculate XOR CRC
        crc = 0
        for ch in response:
            crc ^= ord(ch)
        crc_hex = f"{crc:02X}"
        
        packet = response + crc_hex
        
        # Apply odd parity to each byte
        encoded = bytearray()
        for ch in packet:
            byte_val = ord(ch)
            # Count 1 bits
            ones = bin(byte_val).count('1')
            # Add parity bit in MSB if needed to make odd
            if ones % 2 == 0:
                byte_val |= 0x80
            encoded.append(byte_val)
        
        return encoded

    def _send_notification(self):
        """Send a notification with board state"""
        if not self._client_connected:
            return
        
        log(">>> SENDING NOTIFICATION (board state)")
        
        # Build dbus array
        value = dbus.Array([dbus.Byte(b) for b in self._board_state], signature='y')
        
        # Send PropertiesChanged signal
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])
        
        log(f"    Sent {len(self._board_state)} bytes via PropertiesChanged")

    def _notification_loop(self):
        """Send periodic notifications"""
        import threading
        count = 0
        while self._client_connected and count < 10:  # Send up to 10 notifications
            time.sleep(2)  # Every 2 seconds
            if self._client_connected:
                count += 1
                log(f">>> AUTO-NOTIFICATION #{count}")
                self._send_notification()
        log(">>> Auto-notification loop ended")

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        """Log read requests and return board state"""
        log("=" * 70)
        log(">>> READ REQUEST on TX characteristic (FFF2)")
        if options:
            device = options.get('device', None)
            mtu = options.get('mtu', None)
            link = options.get('link', None)
            log(f"    Device: {device}")
            log(f"    MTU: {mtu}")
            log(f"    Link: {link}")
        
        # Mark client as connected and start auto-notifications
        if not self._client_connected:
            self._client_connected = True
            self.notifying = True  # Enable notifications
            log("    Client connected - starting auto-notification thread")
            import threading
            self._notification_thread = threading.Thread(target=self._notification_loop, daemon=True)
            self._notification_thread.start()
        
        # Return board state
        log(f"    Returning board state ({len(self._board_state)} bytes)")
        log(f"    Hex: {' '.join(f'{b:02x}' for b in self._board_state[:20])}...")
        try:
            # Show ASCII (strip parity for display)
            ascii_str = ''.join(chr(b & 0x7F) for b in self._board_state)
            log(f"    ASCII: {ascii_str}")
        except:
            pass
        log("=" * 70)
        
        return dbus.Array([dbus.Byte(b) for b in self._board_state], signature='y')

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='')
    def StartNotify(self):
        """Log notification subscription"""
        log("=" * 70)
        log(">>> START NOTIFY on TX characteristic (FFF2)")
        log("    Client subscribed to notifications")
        log("=" * 70)
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='', out_signature='')
    def StopNotify(self):
        """Log notification unsubscription"""
        log("=" * 70)
        log(">>> STOP NOTIFY on TX characteristic (FFF2)")
        log("    Client unsubscribed from notifications")
        log("=" * 70)
        self.notifying = False


class ReadOnlyCharacteristic(Characteristic):
    """Simple read-only characteristic"""
    
    def __init__(self, bus, index, uuid, value, service):
        Characteristic.__init__(self, bus, index, uuid, ['read'], service)
        self._value = value.encode('utf-8') if isinstance(value, str) else value

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array([dbus.Byte(b) for b in self._value], signature='y')


class GAPService(Service):
    """Generic Access Profile Service (0x1800)"""
    
    def __init__(self, bus, index, device_name):
        Service.__init__(self, bus, index, GAP_SERVICE_UUID, True)
        # Device Name characteristic
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 0, GAP_DEVICE_NAME_UUID, device_name, self))
        # Appearance characteristic (0x0000 = Unknown)
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 1, GAP_APPEARANCE_UUID, bytes([0x00, 0x00]), self))
        log(f"GAP Service created: {GAP_SERVICE_UUID}")


class DeviceInfoService(Service):
    """Device Information Service (0x180A)"""
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, DEVICE_INFO_SERVICE_UUID, True)
        # Manufacturer Name
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 0, DEVICE_INFO_MANUFACTURER_UUID, "Millennium", self))
        # Model Number
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 1, DEVICE_INFO_MODEL_UUID, "ChessLink", self))
        # Firmware Revision
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 2, DEVICE_INFO_FIRMWARE_UUID, "1.0", self))
        log(f"Device Info Service created: {DEVICE_INFO_SERVICE_UUID}")


class MillenniumService(Service):
    """Millennium ChessLink Service"""
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, MILLENNIUM_SERVICE_UUID, True)
        self.add_characteristic(RXCharacteristic(bus, 0, self))
        self.add_characteristic(TXCharacteristic(bus, 1, self))
        log(f"Millennium Service created: {MILLENNIUM_SERVICE_UUID}")


def find_adapter(bus):
    """Find the Bluetooth adapter"""
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'),
                               DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props.keys():
            return o
    return None


def register_ad_cb():
    """Advertisement registration success callback"""
    log("=" * 70)
    log("BLE Advertisement registered successfully")
    log("Device is now discoverable")
    log("=" * 70)


def register_ad_error_cb(error):
    """Advertisement registration error callback"""
    log(f"ERROR: Failed to register advertisement: {error}")
    mainloop.quit()


def register_app_cb():
    """Application registration success callback"""
    log("GATT application registered successfully")


def register_app_error_cb(error):
    """Application registration error callback"""
    log(f"ERROR: Failed to register application: {error}")
    mainloop.quit()


def signal_handler(signum, frame):
    """Handle termination signals"""
    global kill
    log(f"Received signal {signum}, shutting down...")
    kill = True
    if mainloop:
        mainloop.quit()


def main():
    global mainloop
    
    parser = argparse.ArgumentParser(
        description="BLE Sniffer - Log all incoming BLE writes from chess apps")
    parser.add_argument(
        "--name", "-n",
        default="MILLENNIUM CHESS",
        help="Device name to advertise (default: MILLENNIUM CHESS)")
    args = parser.parse_args()
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize D-Bus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    
    # Find adapter
    adapter_path = find_adapter(bus)
    if not adapter_path:
        log("ERROR: No Bluetooth adapter found")
        sys.exit(1)
    
    log("=" * 70)
    log("BLE SNIFFER - Millennium ChessLink Protocol Logger")
    log("=" * 70)
    log(f"Adapter: {adapter_path}")
    log(f"Device name: {args.name}")
    log(f"Service UUID: {MILLENNIUM_SERVICE_UUID}")
    log(f"RX Characteristic (write): {MILLENNIUM_RX_UUID}")
    log(f"TX Characteristic (notify): {MILLENNIUM_TX_UUID}")
    log("=" * 70)
    log("")
    log("This tool will log ALL incoming BLE writes from connected clients.")
    log("Connect your chess app (HIARCS, etc.) to see what commands it sends.")
    log("")
    log("=" * 70)
    
    # Get adapter interfaces
    adapter_obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
    adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)
    
    # Power on adapter
    adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
    log("Bluetooth adapter powered on")
    
    # Create and register GATT application with all required services
    # Real Millennium board has: GAP (0x1800), Device Info (0x180A), Millennium service
    app = Application(bus)
    app.add_service(GAPService(bus, 0, args.name))  # Generic Access Profile
    app.add_service(DeviceInfoService(bus, 1))       # Device Information
    app.add_service(MillenniumService(bus, 2))       # Millennium ChessLink
    
    service_manager = dbus.Interface(adapter_obj, GATT_MANAGER_IFACE)
    service_manager.RegisterApplication(
        app.get_path(), {},
        reply_handler=register_app_cb,
        error_handler=register_app_error_cb)
    
    # Create and register advertisement
    ad = Advertisement(bus, 0, args.name)
    ad_manager = dbus.Interface(adapter_obj, LE_ADVERTISING_MANAGER_IFACE)
    ad_manager.RegisterAdvertisement(
        ad.get_path(), {},
        reply_handler=register_ad_cb,
        error_handler=register_ad_error_cb)
    
    log("")
    log("Waiting for BLE connections...")
    log("Press Ctrl+C to stop")
    log("")
    
    # Run main loop
    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass
    
    log("")
    log("Shutting down...")
    
    # Unregister
    try:
        ad_manager.UnregisterAdvertisement(ad.get_path())
    except:
        pass
    try:
        service_manager.UnregisterApplication(app.get_path())
    except:
        pass
    
    log("Done")


if __name__ == "__main__":
    main()

