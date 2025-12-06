#!/usr/bin/env python3
"""
BLE Sniffer - Millennium ChessLink emulator matching real board GATT structure

Based on nRF Connect capture of real Millennium ChessLink board.

To match real Millennium board behavior (no pairing prompt on iOS/Android),
this script configures BlueZ to:
- Disable bondable mode (no new pairings)
- Disable secure connections
- Set IO capability to NoInputNoOutput (Just Works pairing)
- Use characteristics without encryption requirements
"""

import argparse
import sys
import signal
import time
import subprocess
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
AGENT_IFACE = 'org.bluez.Agent1'
AGENT_MANAGER_IFACE = 'org.bluez.AgentManager1'

# Device Information Service UUIDs (standard BLE - 0x180A)
# Note: Generic Access Service (0x1800) is NOT defined here because BlueZ
# provides it automatically. We only register Device Info + Millennium services.
DEVICE_INFO_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
SERIAL_NUMBER_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
HARDWARE_REV_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
FIRMWARE_REV_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
SOFTWARE_REV_UUID = "00002a28-0000-1000-8000-00805f9b34fb"
SYSTEM_ID_UUID = "00002a23-0000-1000-8000-00805f9b34fb"
IEEE_REGULATORY_UUID = "00002a2a-0000-1000-8000-00805f9b34fb"
PNP_ID_UUID = "00002a50-0000-1000-8000-00805f9b34fb"

# Millennium ChessLink Service UUIDs
MILLENNIUM_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
MILLENNIUM_CONFIG_UUID = "49535343-6daa-4d02-abf6-19569aca69fe"  # READ/WRITE config
MILLENNIUM_NOTIFY1_UUID = "49535343-aca3-481c-91ec-d85e28a60318"  # WRITE/NOTIFY
MILLENNIUM_TX_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"  # READ/WRITE/WRITE_NO_RESP/NOTIFY
MILLENNIUM_RX_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"  # WRITE/WRITE_NO_RESP
MILLENNIUM_NOTIFY2_UUID = "49535343-026e-3a9b-954c-97daef17e26e"  # WRITE/NOTIFY

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


def configure_adapter_security():
    """Configure Bluetooth adapter security settings to prevent pairing prompts.
    
    The real Millennium board operates without requiring pairing. To match this:
    - Disable bondable mode (prevents creating new bonds/pairings)
    - Disable secure connections (prevents security negotiation)
    - Set IO capability to NoInputNoOutput (0x03) for "Just Works" mode
    
    These settings are applied via btmgmt which directly configures the controller.
    Must run with sudo to have permission to change adapter settings.
    """
    commands = [
        # Disable bondable mode - prevents pairing requests
        ['sudo', 'btmgmt', 'bondable', 'off'],
        # Disable secure connections - prevents security negotiation
        ['sudo', 'btmgmt', 'sc', 'off'],
        # Set IO capability to NoInputNoOutput (Just Works, no pairing UI)
        ['sudo', 'btmgmt', 'io-cap', '0x03'],
        # Enable LE (Low Energy) advertising
        ['sudo', 'btmgmt', 'le', 'on'],
        # Make adapter connectable for LE
        ['sudo', 'btmgmt', 'connectable', 'on'],
    ]
    
    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            cmd_str = ' '.join(cmd[1:])  # Skip 'sudo' in log output
            if result.returncode == 0:
                # Parse output to show the actual result
                stdout = result.stdout.strip()
                if stdout:
                    log(f"btmgmt: {cmd_str} - {stdout}")
                else:
                    log(f"btmgmt: {cmd_str} - OK")
            else:
                # Non-fatal - some commands may not be available on all BlueZ versions
                stderr = result.stderr.strip() if result.stderr else "unknown error"
                stdout = result.stdout.strip() if result.stdout else ""
                log(f"btmgmt: {cmd_str} - {stderr or stdout or 'failed'}")
        except FileNotFoundError:
            log(f"btmgmt not found - skipping security configuration")
            break
        except subprocess.TimeoutExpired:
            log(f"btmgmt command timed out: {' '.join(cmd)}")
        except Exception as e:
            log(f"btmgmt error: {e}")


class NoInputNoOutputAgent(dbus.service.Object):
    """Bluetooth agent that auto-accepts all connections without pairing prompts.
    
    This implements a "NoInputNoOutput" capability agent which:
    - Automatically authorizes all connection requests
    - Doesn't require PIN entry or confirmation
    - Matches how real Millennium board handles connections (no pairing required)
    """
    
    AGENT_PATH = "/org/bluez/millennium_agent"
    CAPABILITY = "NoInputNoOutput"
    
    def __init__(self, bus):
        self.bus = bus
        dbus.service.Object.__init__(self, bus, self.AGENT_PATH)
    
    @dbus.service.method(AGENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        log("Agent released")
    
    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        """Auto-authorize all service access requests."""
        log(f"AuthorizeService: {device} -> {uuid} (auto-authorized)")
    
    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='s')
    def RequestPinCode(self, device):
        """Return empty PIN (no PIN required)."""
        log(f"RequestPinCode: {device} (returning empty)")
        return ""
    
    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        """Return 0 passkey (no passkey required)."""
        log(f"RequestPasskey: {device} (returning 0)")
        return dbus.UInt32(0)
    
    @dbus.service.method(AGENT_IFACE, in_signature='ouq', out_signature='')
    def DisplayPasskey(self, device, passkey, entered):
        log(f"DisplayPasskey: {device} passkey={passkey}")
    
    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def DisplayPinCode(self, device, pincode):
        log(f"DisplayPinCode: {device} pin={pincode}")
    
    @dbus.service.method(AGENT_IFACE, in_signature='ou', out_signature='')
    def RequestConfirmation(self, device, passkey):
        """Auto-confirm all pairing requests."""
        log(f"RequestConfirmation: {device} passkey={passkey} (auto-confirmed)")
    
    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        """Auto-authorize all connection requests."""
        log(f"RequestAuthorization: {device} (auto-authorized)")
    
    @dbus.service.method(AGENT_IFACE, in_signature='', out_signature='')
    def Cancel(self):
        log("Agent request cancelled")


class Advertisement(dbus.service.Object):
    """BLE Advertisement matching real Millennium ChessLink board.
    
    The real board advertises with LocalName and TxPower only - no Appearance.
    It does not require pairing.
    """
    
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
        properties['IncludeTxPower'] = dbus.Boolean(True)
        # Real Millennium board advertises TxPower = 0
        properties['TxPower'] = dbus.Int16(0)
        # Do NOT include Appearance - real Millennium board doesn't advertise it
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


# =============================================================================
# Helper Characteristic Classes
# =============================================================================

class ReadOnlyCharacteristic(Characteristic):
    """Simple read-only characteristic with static value."""
    
    def __init__(self, bus, index, uuid, service, value):
        Characteristic.__init__(self, bus, index, uuid, ['read'], service)
        if isinstance(value, str):
            self.value = [dbus.Byte(ord(c)) for c in value]
        else:
            self.value = [dbus.Byte(b) for b in value]

    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')


# Note: Generic Access Service (0x1800) is NOT registered here because BlueZ
# automatically provides this service. The real Millennium board's Bluetooth chip
# also provides this internally. Only Device Info and Millennium services are
# explicitly registered to match the real board's visible service count.


# =============================================================================
# Device Information Service (0x180A)
# =============================================================================

class DeviceInfoService(Service):
    """Device Information Service (0x180A) - matches real Millennium board"""
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, DEVICE_INFO_SERVICE_UUID, True)
        
        # Add all characteristics from real board
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 0, MANUFACTURER_NAME_UUID, self, "MCHP"))
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 1, MODEL_NUMBER_UUID, self, "BT5056"))
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 2, SERIAL_NUMBER_UUID, self, "3481F4ED7834"))
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 3, HARDWARE_REV_UUID, self, "5056_SPP     "))
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 4, FIRMWARE_REV_UUID, self, "2220013"))
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 5, SOFTWARE_REV_UUID, self, "0000"))
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 6, SYSTEM_ID_UUID, self, bytes.fromhex("0000000000000000")))
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 7, IEEE_REGULATORY_UUID, self, bytes.fromhex("0001000400000000")))
        # PnP ID: Vendor ID Source (1=Bluetooth SIG), Vendor ID, Product ID, Product Version
        # Using generic values - format: [VID Source, VID Lo, VID Hi, PID Lo, PID Hi, Ver Lo, Ver Hi]
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 8, PNP_ID_UUID, self, bytes([0x01, 0x0D, 0x00, 0x00, 0x00, 0x01, 0x00])))
        
        log(f"Device Info Service created: {DEVICE_INFO_SERVICE_UUID}")


# =============================================================================
# Millennium ChessLink Service Characteristics
# =============================================================================

class ConfigCharacteristic(Characteristic):
    """Config characteristic - 49535343-6daa-4d02-abf6-19569aca69fe"""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, MILLENNIUM_CONFIG_UUID,
                                ['read', 'write'], service)
        self.value = bytes.fromhex("00240024000000F401")
        log(f"Config Characteristic created: {MILLENNIUM_CONFIG_UUID}")

    def ReadValue(self, options):
        log(f"Config ReadValue: {self.value.hex()}")
        return dbus.Array([dbus.Byte(b) for b in self.value], signature='y')

    def WriteValue(self, value, options):
        self.value = bytes([int(b) for b in value])
        log(f"Config WriteValue: {self.value.hex()}")


class Notify1Characteristic(Characteristic):
    """Notify1 characteristic - 49535343-aca3-481c-91ec-d85e28a60318"""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, MILLENNIUM_NOTIFY1_UUID,
                                ['write', 'notify'], service)
        self.notifying = False
        log(f"Notify1 Characteristic created: {MILLENNIUM_NOTIFY1_UUID}")

    def WriteValue(self, value, options):
        data = bytes([int(b) for b in value])
        log(f"Notify1 WriteValue: {data.hex()}")

    def StartNotify(self):
        log("Notify1 StartNotify")
        self.notifying = True

    def StopNotify(self):
        log("Notify1 StopNotify")
        self.notifying = False


class TXCharacteristic(Characteristic):
    """TX characteristic - 49535343-1e4d-4bd9-ba61-23c647249616
    
    Real board has: READ, WRITE, WRITE_WITHOUT_RESPONSE, NOTIFY
    """
    
    tx_instance = None
    
    def __init__(self, bus, index, service):
        # Match real board flags exactly
        Characteristic.__init__(self, bus, index, MILLENNIUM_TX_UUID,
                                ['read', 'write', 'write-without-response', 'notify'], service)
        self.notifying = False
        self.value = bytes.fromhex("0000000000")
        TXCharacteristic.tx_instance = self
        log(f"TX Characteristic created: {MILLENNIUM_TX_UUID}")
        log(f"  Flags: ['read', 'write', 'write-without-response', 'notify']")

    def ReadValue(self, options):
        log(f"TX ReadValue: {self.value.hex()}")
        return dbus.Array([dbus.Byte(b) for b in self.value], signature='y')

    def WriteValue(self, value, options):
        data = bytes([int(b) for b in value])
        log(f"TX WriteValue: {data.hex()}")

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
    """RX characteristic - 49535343-8841-43f4-a8d4-ecbe34729bb3"""
    
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
        """Handle Millennium protocol commands.
        
        Real Millennium board commands (from protocol analysis):
        - 'M' (0x4D) - Request version/status (responds with board state)
        - 's' (0x73) - Request board state 
        - 'V' (0x56) - Request version string
        - 'I' (0x49) - Request identity
        - 'R' (0x52) - Read E2ROM
        - 'W' (0x57) - Write E2ROM
        - 'L' (0x4C) - LED control (multi-packet, 167 bytes total)
        - 'X' (0x58) - Extended LED control
        
        Note: LED commands span multiple packets. Continuation packets starting
        with data bytes (not command letters) are silently ignored.
        """
        # Board state (starting position for emulator)
        board_state = "sRNBQKBNRPPPPPPPP................................pppppppprnbqkbnr"
        
        if cmd == 'M':
            # Real board responds with board state to 'M' command
            log("  -> Responding with board state (M command)")
            self._send_response(board_state)
        elif cmd == 's':
            # Lowercase 's' also requests board state
            log("  -> Responding with board state (s command)")
            self._send_response(board_state)
        elif cmd == 'S':
            # Uppercase 'S' also requests board state
            log("  -> Responding with board state (S command)")
            self._send_response(board_state)
        elif cmd == 'V':
            log("  -> Responding with version: v3130")
            self._send_response("v3130")
        elif cmd == 'I':
            log("  -> Responding with identity: i0055mm")
            self._send_response("i0055mm\n")
        elif cmd == 'R':
            # Read E2ROM - return stored value for address
            if len(data) >= 5:
                h1, h2, h3, h4 = [data[i] & 127 for i in range(1, 5)]
                addr = chr(h1) + chr(h2)
                # Return default value "00" for any address
                log(f"  -> Read E2ROM: addr={addr}")
                self._send_response('r' + addr + '00')
            else:
                log(f"  -> Read E2ROM: insufficient data")
        elif cmd == 'W':
            if len(data) >= 5:
                h1, h2, h3, h4 = [data[i] & 127 for i in range(1, 5)]
                log(f"  -> Write E2ROM: addr={chr(h1)}{chr(h2)} value={chr(h3)}{chr(h4)}")
                self._send_response('w' + chr(h1) + chr(h2) + chr(h3) + chr(h4))
        elif cmd == 'L':
            log(f"  -> LED pattern command ({len(data)} bytes)")
            self._send_response("l")
        elif cmd == 'X':
            log(f"  -> Extended LED command ({len(data)} bytes)")
            self._send_response("x")
        elif cmd in '0123456789':
            # Continuation packet from multi-packet command (like LED) - silently ignore
            pass
        else:
            log(f"  -> Unknown command '{cmd}' (0x{ord(cmd):02x}), no response")

    def _send_response(self, txt):
        """Send response to client via TX characteristic notifications.
        
        Real Millennium board sends plain ASCII without parity bits, followed
        by a 2-character hex checksum. This matches the real board's format.
        """
        if TXCharacteristic.tx_instance is None:
            log("  -> Cannot send: TX not initialized")
            return
        if not TXCharacteristic.tx_instance.notifying:
            log("  -> Cannot send: notifications not enabled")
            return
        
        # Build response with checksum (plain ASCII, no parity - matches real board)
        cs = 0
        for ch in txt:
            cs ^= ord(ch)
        
        # Append 2-char hex checksum
        response = txt + f"{cs:02x}"
        tosend = response.encode('ascii')
        
        log(f"  -> Sending: {tosend.hex()} ({response})")
        TXCharacteristic.tx_instance.send_notification(tosend)


class Notify2Characteristic(Characteristic):
    """Notify2 characteristic - 49535343-026e-3a9b-954c-97daef17e26e"""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, MILLENNIUM_NOTIFY2_UUID,
                                ['write', 'notify'], service)
        self.notifying = False
        log(f"Notify2 Characteristic created: {MILLENNIUM_NOTIFY2_UUID}")

    def WriteValue(self, value, options):
        data = bytes([int(b) for b in value])
        log(f"Notify2 WriteValue: {data.hex()}")

    def StartNotify(self):
        log("Notify2 StartNotify")
        self.notifying = True

    def StopNotify(self):
        log("Notify2 StopNotify")
        self.notifying = False


class MillenniumService(Service):
    """Millennium ChessLink service - matches real board with 5 characteristics"""
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, MILLENNIUM_SERVICE_UUID, True)
        
        # Add all 5 characteristics in same order as real board
        self.add_characteristic(ConfigCharacteristic(bus, 0, self))
        self.add_characteristic(Notify1Characteristic(bus, 1, self))
        self.add_characteristic(TXCharacteristic(bus, 2, self))
        self.add_characteristic(RXCharacteristic(bus, 3, self))
        self.add_characteristic(Notify2Characteristic(bus, 4, self))
        
        log(f"Millennium Service created: {MILLENNIUM_SERVICE_UUID}")


def signal_handler(signum, frame):
    global mainloop
    log(f"Received signal {signum}, exiting...")
    if mainloop:
        mainloop.quit()
    sys.exit(0)


def main():
    global mainloop, device_name
    
    parser = argparse.ArgumentParser(description="BLE Sniffer - Millennium ChessLink emulator matching real board")
    parser.add_argument("--name", default="MILLENNIUM CHESS", help="BLE device name")
    parser.add_argument("--advertise-uuid", action="store_true", 
                        help="Include service UUID in advertisement")
    args = parser.parse_args()
    device_name = args.name
    
    log("=" * 60)
    log("BLE Sniffer - Millennium ChessLink (Full GATT)")
    log(f"Device name: {device_name}")
    log(f"Advertise service UUID: {args.advertise_uuid}")
    log("Includes Device Info Service + full Millennium service")
    log("=" * 60)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Configure adapter security settings BEFORE D-Bus setup
    # This disables bonding and secure connections to prevent pairing prompts
    log("Configuring adapter security (matching real Millennium board)...")
    configure_adapter_security()
    
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    mainloop = GLib.MainLoop()
    
    adapter = find_adapter(bus)
    if not adapter:
        log("ERROR: No Bluetooth adapter found")
        return
    log(f"Found Bluetooth adapter: {adapter}")
    
    # Configure adapter for iOS compatibility and proper device naming
    adapter_props = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter),
        DBUS_PROP_IFACE)
    
    # Set the adapter Alias to the device name - this is what clients see as the device name
    try:
        adapter_props.Set("org.bluez.Adapter1", "Alias", dbus.String(device_name))
        log(f"Adapter Alias set to '{device_name}'")
    except dbus.exceptions.DBusException as e:
        log(f"Could not set Alias: {e}")
    
    # Ensure adapter is powered on
    try:
        powered = adapter_props.Get("org.bluez.Adapter1", "Powered")
        if not powered:
            adapter_props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
            log("Adapter powered on")
        else:
            log("Adapter already powered on")
    except dbus.exceptions.DBusException as e:
        log(f"Could not check/set Powered: {e}")
    
    # Make adapter discoverable
    try:
        adapter_props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(True))
        log("Adapter Discoverable set to True")
    except dbus.exceptions.DBusException as e:
        log(f"Could not set Discoverable: {e}")
    
    try:
        adapter_props.Set("org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(0))
        log("Adapter DiscoverableTimeout set to 0 (infinite)")
    except dbus.exceptions.DBusException as e:
        log(f"Could not set DiscoverableTimeout: {e}")
    
    # Disable pairing requirement - real Millennium board doesn't require pairing
    # This prevents the "pair request" prompt on client devices
    try:
        adapter_props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(False))
        log("Adapter Pairable set to False (no pairing required, like real board)")
    except dbus.exceptions.DBusException as e:
        log(f"Could not set Pairable: {e}")
    
    try:
        adapter_props.Set("org.bluez.Adapter1", "Privacy", dbus.Boolean(False))
        log("Adapter Privacy disabled (using public MAC address)")
    except dbus.exceptions.DBusException as e:
        log(f"Could not disable Privacy: {e}")
    
    # Note: Device Class is set in /etc/bluetooth/main.conf by postinst
    # Class = 0x200404 (Audio/Video Headphones) to match real Millennium board icon
    
    try:
        mac_address = adapter_props.Get("org.bluez.Adapter1", "Address")
        log(f"Adapter MAC address: {mac_address}")
    except dbus.exceptions.DBusException as e:
        log(f"Could not get MAC address: {e}")
    
    # Register a NoInputNoOutput agent to auto-accept connections without pairing
    # This matches the real Millennium board behavior (no pairing prompt)
    agent = NoInputNoOutputAgent(bus)
    agent_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, '/org/bluez'),
        AGENT_MANAGER_IFACE)
    
    # First, try to unregister any existing agent to avoid conflicts
    try:
        agent_manager.UnregisterAgent(agent.AGENT_PATH)
        log("Unregistered existing agent")
    except dbus.exceptions.DBusException:
        pass  # No existing agent, that's fine
    
    try:
        agent_manager.RegisterAgent(agent.AGENT_PATH, agent.CAPABILITY)
        log(f"Agent registered with capability: {agent.CAPABILITY}")
    except dbus.exceptions.DBusException as e:
        log(f"Could not register agent: {e}")
    
    try:
        agent_manager.RequestDefaultAgent(agent.AGENT_PATH)
        log("Agent set as default")
    except dbus.exceptions.DBusException as e:
        log(f"Could not set default agent: {e}")
    
    # Remove any existing paired devices to prevent pairing prompts from cached state
    # This ensures fresh connections don't trigger pairing based on old state
    try:
        adapter_iface = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, adapter),
            'org.bluez.Adapter1')
        remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'),
                                   DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        for path, interfaces in objects.items():
            if 'org.bluez.Device1' in interfaces:
                device_props = interfaces['org.bluez.Device1']
                if device_props.get('Paired', False):
                    paired_device_name = device_props.get('Name', 'Unknown')
                    log(f"Found paired device: {paired_device_name} at {path}")
                    # Optionally remove paired devices - commented out to avoid breaking other pairings
                    # adapter_iface.RemoveDevice(path)
    except dbus.exceptions.DBusException as e:
        log(f"Could not enumerate paired devices: {e}")
    
    # Create and register GATT application
    # Note: Generic Access Service (0x1800) is managed by BlueZ internally
    app = Application(bus)
    app.add_service(DeviceInfoService(bus, 0))
    app.add_service(MillenniumService(bus, 1))
    
    gatt_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter),
        GATT_MANAGER_IFACE)
    
    # Track registration status
    gatt_registered = [False]
    adv_registered = [False]
    registration_error = [None]
    
    def gatt_register_success():
        log("GATT application registered successfully")
        gatt_registered[0] = True
    
    def gatt_register_error(error):
        log(f"Failed to register GATT application: {error}")
        registration_error[0] = str(error)
    
    def adv_register_success():
        log("Advertisement registered successfully")
        adv_registered[0] = True
    
    def adv_register_error(error):
        log(f"Failed to register advertisement: {error}")
        registration_error[0] = str(error)
    
    log("Registering GATT application...")
    gatt_manager.RegisterApplication(
        app.get_path(), {},
        reply_handler=gatt_register_success,
        error_handler=gatt_register_error)
    
    # Create and register advertisement
    adv = Advertisement(bus, 0, device_name, include_service_uuid=args.advertise_uuid)
    
    ad_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter),
        LE_ADVERTISING_MANAGER_IFACE)
    
    log("Registering advertisement...")
    ad_manager.RegisterAdvertisement(
        adv.get_path(), {},
        reply_handler=adv_register_success,
        error_handler=adv_register_error)
    
    # Give D-Bus time to process registrations
    time.sleep(1)
    
    # Run one iteration of the main loop to process registration callbacks
    context = mainloop.get_context()
    while context.pending():
        context.iteration(False)
    
    log("")
    if registration_error[0]:
        log(f"WARNING: Registration failed: {registration_error[0]}")
        log("BLE service may not work correctly!")
    else:
        log("GATT and Advertisement registration initiated")
    log("")
    log("Waiting for BLE connections...")
    log(f"Device name: {device_name}")
    log("Device should now match real Millennium ChessLink GATT structure")
    log("")
    
    try:
        mainloop.run()
    except Exception as e:
        log(f"Error: {e}")
        import traceback
        log(traceback.format_exc())
    
    log("Exiting")


if __name__ == "__main__":
    main()
