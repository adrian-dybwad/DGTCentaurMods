#!/usr/bin/env python3
"""
Bluetooth Classic SPP Relay with BLE Support

This relay connects to a target device via Bluetooth Classic SPP (RFCOMM)
and relays data between that device and a client connected to this relay.
Also provides BLE service matching millennium.py for host connections.

BLE Implementation:
- Uses direct D-Bus/BlueZ GATT implementation (no thirdparty dependencies)
- Matches the working millennium_sniffer.py implementation
- Supports BLE without pairing (like real Millennium board)
- Supports RFCOMM with pairing (Serial Port Profile)

Usage:
    python3 tools/universal_relay.py
"""

import argparse
import sys
import os
import time
import threading
import signal
import subprocess
import socket
import psutil
import bluetooth
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board.bluetooth_controller import BluetoothController
from DGTCentaurMods.games.universal import Universal

# Global state
running = True
kill = 0
shadow_target_connected = False
client_connected = False
ble_connected = False
universal = None  # Universal instance
_last_message = None  # Last message sent via sendMessage
relay_mode = False  # Whether relay mode is enabled (connects to relay target)
shadow_target = "MILLENNIUM CHESS"  # Default target device name (can be overridden via --shadow-target)
mainloop = None  # GLib mainloop for BLE

# Socket references
shadow_target_sock = None
server_sock = None
client_sock = None

# BLE references
ble_app = None

# Thread references
shadow_target_to_client_thread = None
shadow_target_to_client_thread_started = False

# ============================================================================
# BlueZ D-Bus Constants
# ============================================================================

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

# ============================================================================
# BLE UUID Definitions
# ============================================================================

# Device Information Service UUIDs (standard BLE - 0x180A)
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

# Millennium ChessLink BLE UUIDs
MILLENNIUM_UUIDS = {
    "service": "49535343-fe7d-4ae5-8fa9-9fafd205e455",
    "config": "49535343-6daa-4d02-abf6-19569aca69fe",
    "notify1": "49535343-aca3-481c-91ec-d85e28a60318",
    "tx": "49535343-1e4d-4bd9-ba61-23c647249616",
    "rx": "49535343-8841-43f4-a8d4-ecbe34729bb3",
    "notify2": "49535343-026e-3a9b-954c-97daef17e26e",
}

# Nordic UART Service BLE UUIDs (used by Pegasus)
NORDIC_UUIDS = {
    "service": "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
    "rx": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
    "tx": "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
}

# Chessnut Air BLE UUIDs
CHESSNUT_UUIDS = {
    "service": "1b7e8261-2877-41c3-b46e-cf057c562023",
    "fen": "1b7e8262-2877-41c3-b46e-cf057c562023",
    "op_tx": "1b7e8272-2877-41c3-b46e-cf057c562023",
    "op_rx": "1b7e8273-2877-41c3-b46e-cf057c562023"
}

# ============================================================================
# Helper Functions
# ============================================================================

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
    """Configure Bluetooth adapter for BLE operation without pairing.
    
    The real Millennium board operates without requiring pairing for BLE.
    RFCOMM/SPP still requires pairing.
    
    Settings applied via btmgmt:
    - Disable bondable mode (prevents new BLE pairing requests)
    - Enable LE advertising and connectable mode
    """
    commands = [
        # Disable bondable mode - prevents new pairing requests for BLE
        ['sudo', 'btmgmt', 'bondable', 'off'],
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
                stdout = result.stdout.strip()
                if stdout:
                    log.info(f"btmgmt: {cmd_str} - {stdout}")
                else:
                    log.info(f"btmgmt: {cmd_str} - OK")
            else:
                stderr = result.stderr.strip() if result.stderr else "unknown error"
                stdout = result.stdout.strip() if result.stdout else ""
                log.warning(f"btmgmt: {cmd_str} - {stderr or stdout or 'failed'}")
        except FileNotFoundError:
            log.warning(f"btmgmt not found - skipping security configuration")
            break
        except subprocess.TimeoutExpired:
            log.warning(f"btmgmt command timed out: {' '.join(cmd)}")
        except Exception as e:
            log.warning(f"btmgmt error: {e}")


# ============================================================================
# NoInputNoOutput Agent for auto-accepting connections
# ============================================================================

class NoInputNoOutputAgent(dbus.service.Object):
    """Bluetooth agent that auto-accepts connections without user interaction.
    
    This agent handles pairing negotiation for BLE connections, auto-accepting
    without requiring user confirmation. For RFCOMM, pairing is handled separately.
    """
    
    AGENT_PATH = "/org/bluez/universal_relay_agent"
    CAPABILITY = "NoInputNoOutput"
    
    def __init__(self, bus):
        self.bus = bus
        dbus.service.Object.__init__(self, bus, self.AGENT_PATH)
    
    @dbus.service.method(AGENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        log.info("Agent released")
    
    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        """Auto-authorize all service access requests."""
        log.info(f"AuthorizeService: {device} -> {uuid} (auto-authorized)")
    
    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='s')
    def RequestPinCode(self, device):
        """Return empty PIN (no PIN required)."""
        log.info(f"RequestPinCode: {device} (returning empty)")
        return ""
    
    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        """Return 0 passkey (no passkey required)."""
        log.info(f"RequestPasskey: {device} (returning 0)")
        return dbus.UInt32(0)
    
    @dbus.service.method(AGENT_IFACE, in_signature='ouq', out_signature='')
    def DisplayPasskey(self, device, passkey, entered):
        log.info(f"DisplayPasskey: {device} passkey={passkey}")
    
    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def DisplayPinCode(self, device, pincode):
        log.info(f"DisplayPinCode: {device} pin={pincode}")
    
    @dbus.service.method(AGENT_IFACE, in_signature='ou', out_signature='')
    def RequestConfirmation(self, device, passkey):
        """Auto-confirm all pairing requests."""
        log.info(f"RequestConfirmation: {device} passkey={passkey} (auto-confirmed)")
    
    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        """Auto-authorize all connection requests."""
        log.info(f"RequestAuthorization: {device} (auto-authorized)")
    
    @dbus.service.method(AGENT_IFACE, in_signature='', out_signature='')
    def Cancel(self):
        log.info("Agent request cancelled")


# ============================================================================
# BLE Advertisement
# ============================================================================

class Advertisement(dbus.service.Object):
    """BLE Advertisement matching real Millennium ChessLink board.
    
    The real board advertises with LocalName and TxPower only - no Appearance.
    It does not require pairing for BLE connections.
    """
    
    PATH_BASE = '/org/bluez/universal_relay/advertisement'

    def __init__(self, bus, index, name, service_uuids=None):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = 'peripheral'
        self.local_name = name
        self.include_tx_power = True
        self.service_uuids = service_uuids or []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        properties['LocalName'] = dbus.String(self.local_name)
        properties['IncludeTxPower'] = dbus.Boolean(True)
        # Real Millennium board advertises TxPower = 0
        properties['TxPower'] = dbus.Int16(0)
        # Do NOT include Appearance - real Millennium board doesn't advertise it
        if self.service_uuids:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
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
        log.info(f"Advertisement released: {self.path}")


# ============================================================================
# GATT Application
# ============================================================================

class Application(dbus.service.Object):
    """GATT Application container for services"""
    
    def __init__(self, bus):
        self.path = '/org/bluez/universal_relay'
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


# ============================================================================
# GATT Service Base Class
# ============================================================================

class Service(dbus.service.Object):
    """GATT Service base class"""
    
    PATH_BASE = '/org/bluez/universal_relay/service'

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


# ============================================================================
# GATT Characteristic Base Class
# ============================================================================

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
        log.debug(f"ReadValue called on {self.uuid}")
        return []

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        log.debug(f"WriteValue called on {self.uuid}")

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        log.debug(f"StartNotify called on {self.uuid}")

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        log.debug(f"StopNotify called on {self.uuid}")

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


# ============================================================================
# Helper Characteristic Classes
# ============================================================================

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


# ============================================================================
# Device Information Service (0x180A)
# ============================================================================

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
        self.add_characteristic(ReadOnlyCharacteristic(
            bus, 8, PNP_ID_UUID, self, bytes([0x01, 0x0D, 0x00, 0x00, 0x00, 0x01, 0x00])))
        
        log.info(f"Device Info Service created: {DEVICE_INFO_SERVICE_UUID}")


# ============================================================================
# Millennium ChessLink Service Characteristics
# ============================================================================

class ConfigCharacteristic(Characteristic):
    """Config characteristic - 49535343-6daa-4d02-abf6-19569aca69fe"""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, MILLENNIUM_UUIDS["config"],
                                ['read', 'write'], service)
        self.value = bytes.fromhex("00240024000000F401")

    def ReadValue(self, options):
        log.debug(f"Config ReadValue: {self.value.hex()}")
        return dbus.Array([dbus.Byte(b) for b in self.value], signature='y')

    def WriteValue(self, value, options):
        self.value = bytes([int(b) for b in value])
        log.debug(f"Config WriteValue: {self.value.hex()}")


class Notify1Characteristic(Characteristic):
    """Notify1 characteristic - 49535343-aca3-481c-91ec-d85e28a60318"""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, MILLENNIUM_UUIDS["notify1"],
                                ['write', 'notify'], service)
        self.notifying = False

    def WriteValue(self, value, options):
        data = bytes([int(b) for b in value])
        log.debug(f"Notify1 WriteValue: {data.hex()}")

    def StartNotify(self):
        log.debug("Notify1 StartNotify")
        self.notifying = True

    def StopNotify(self):
        log.debug("Notify1 StopNotify")
        self.notifying = False


class TXCharacteristic(Characteristic):
    """TX characteristic - 49535343-1e4d-4bd9-ba61-23c647249616
    
    This is the main characteristic for sending data TO the client via notifications.
    Real board has: READ, WRITE, WRITE_WITHOUT_RESPONSE, NOTIFY
    """
    
    tx_instance = None
    
    def __init__(self, bus, index, service):
        # Match real board flags exactly
        Characteristic.__init__(self, bus, index, MILLENNIUM_UUIDS["tx"],
                                ['read', 'write', 'write-without-response', 'notify'], service)
        self.notifying = False
        self.value = bytes.fromhex("0000000000")
        self._cached_value = bytearray([0])
        TXCharacteristic.tx_instance = self
        log.info(f"TX Characteristic created: {MILLENNIUM_UUIDS['tx']}")

    def ReadValue(self, options):
        global ble_connected, universal, relay_mode
        
        log.info("TX Characteristic ReadValue called by BLE client")
        
        # If Universal is not initialized, treat ReadValue as a connection event
        if universal is None:
            log.info("ReadValue triggered before StartNotify - initializing connection")
            TXCharacteristic.tx_instance = self
            
            try:
                universal = Universal(
                    sendMessage_callback=sendMessage,
                    client_type=Universal.CLIENT_MILLENNIUM,
                    compare_mode=relay_mode
                )
                log.info(f"[Universal] Instantiated for BLE (ReadValue) with client_type=MILLENNIUM")
            except Exception as e:
                log.error(f"[Universal] Error instantiating: {e}")
                import traceback
                traceback.print_exc()
            
            ble_connected = True
        
        log.debug(f"TX ReadValue: {len(self._cached_value)} bytes")
        return dbus.Array([dbus.Byte(b) for b in self._cached_value], signature='y')

    def WriteValue(self, value, options):
        data = bytes([int(b) for b in value])
        log.debug(f"TX WriteValue: {data.hex()}")

    def StartNotify(self):
        global ble_connected, universal, relay_mode
        
        log.info("=" * 60)
        log.info("TX Characteristic StartNotify called - BLE client subscribing")
        log.info("=" * 60)
        
        TXCharacteristic.tx_instance = self
        self.notifying = True
        
        # Create Universal instance for this connection
        try:
            universal = Universal(
                sendMessage_callback=sendMessage,
                client_type=Universal.CLIENT_MILLENNIUM,
                compare_mode=relay_mode
            )
            log.info(f"[Universal] Instantiated for BLE with client_type=MILLENNIUM, compare_mode={relay_mode}")
        except Exception as e:
            log.error(f"[Universal] Error instantiating: {e}")
            import traceback
            traceback.print_exc()
        
        ble_connected = True
        log.info("BLE notifications enabled successfully")

    def StopNotify(self):
        global ble_connected, universal
        
        if not self.notifying:
            return
        
        log.info("=" * 60)
        log.info("BLE CLIENT DISCONNECTED")
        log.info("=" * 60)
        
        self.notifying = False
        ble_connected = False
        universal = None
        log.info("[Universal] Instance reset - ready for new connection")

    def send_notification(self, data):
        """Send data to client via notification."""
        if not self.notifying:
            log.debug("send_notification: Not notifying, skipping")
            return
        
        self._cached_value = bytearray(data)
        value = dbus.Array([dbus.Byte(b) for b in data], signature='y')
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])
        log.debug(f"TX notification sent: {len(data)} bytes")


class RXCharacteristic(Characteristic):
    """RX characteristic - 49535343-8841-43f4-a8d4-ecbe34729bb3
    
    This is where the client writes commands TO the device.
    """
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, MILLENNIUM_UUIDS["rx"],
                                ['write', 'write-without-response'], service)
        log.info(f"RX Characteristic created: {MILLENNIUM_UUIDS['rx']}")

    def WriteValue(self, value, options):
        global kill, ble_connected, shadow_target_connected, shadow_target_sock
        global relay_mode, shadow_target, universal
        
        if kill:
            return
        
        try:
            bytes_data = bytearray([int(b) for b in value])
            hex_str = ' '.join(f'{b:02x}' for b in bytes_data)
            ascii_str = ''.join(chr(b & 127) if 32 <= (b & 127) < 127 else '.' for b in bytes_data)
            
            log.info(f"BLE RX: {len(bytes_data)} bytes")
            log.info(f"  Hex: {hex_str}")
            log.info(f"  ASCII: {ascii_str}")
            
            # Process through Universal
            if universal is not None:
                for byte_val in bytes_data:
                    universal.receive_data(byte_val)
                log.debug(f"Processed {len(bytes_data)} bytes through universal parser")
            else:
                log.warning("universal is None - data not processed")
            
            # Forward to shadow target if in relay mode
            if relay_mode and shadow_target_connected and shadow_target_sock is not None:
                try:
                    data_to_send = bytes(bytes_data)
                    log.info(f"BLE -> SHADOW TARGET: {len(data_to_send)} bytes")
                    shadow_target_sock.send(data_to_send)
                except (bluetooth.BluetoothError, OSError) as e:
                    log.error(f"Error sending to {shadow_target}: {e}")
                    shadow_target_connected = False
            
            ble_connected = True
            
        except Exception as e:
            log.error(f"Error in RX WriteValue: {e}")
            import traceback
            log.error(traceback.format_exc())


class Notify2Characteristic(Characteristic):
    """Notify2 characteristic - 49535343-026e-3a9b-954c-97daef17e26e"""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, MILLENNIUM_UUIDS["notify2"],
                                ['write', 'notify'], service)
        self.notifying = False

    def WriteValue(self, value, options):
        data = bytes([int(b) for b in value])
        log.debug(f"Notify2 WriteValue: {data.hex()}")

    def StartNotify(self):
        log.debug("Notify2 StartNotify")
        self.notifying = True

    def StopNotify(self):
        log.debug("Notify2 StopNotify")
        self.notifying = False


class MillenniumService(Service):
    """Millennium ChessLink service - matches real board with 5 characteristics"""
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, MILLENNIUM_UUIDS["service"], True)
        
        # Add all 5 characteristics in same order as real board
        self.add_characteristic(ConfigCharacteristic(bus, 0, self))
        self.add_characteristic(Notify1Characteristic(bus, 1, self))
        self.add_characteristic(TXCharacteristic(bus, 2, self))
        self.add_characteristic(RXCharacteristic(bus, 3, self))
        self.add_characteristic(Notify2Characteristic(bus, 4, self))
        
        log.info(f"Millennium Service created: {MILLENNIUM_UUIDS['service']}")


# ============================================================================
# Nordic UART Service Characteristics (for Pegasus)
# ============================================================================

class NordicTXCharacteristic(Characteristic):
    """Nordic TX characteristic (6E400003) - notifications FROM device to client.
    
    This characteristic sends data TO the connected Pegasus client via notifications.
    Real Pegasus board has only 'notify' flag (no 'read').
    """
    
    nordic_tx_instance = None
    
    def __init__(self, bus, index, service):
        # Real Pegasus has only 'notify' - no 'read'
        Characteristic.__init__(self, bus, index, NORDIC_UUIDS["tx"],
                                ['notify'], service)
        self.notifying = False
        self.value = bytes([0])
        NordicTXCharacteristic.nordic_tx_instance = self
        log.info(f"Nordic TX Characteristic created: {NORDIC_UUIDS['tx']}")

    def StartNotify(self):
        global ble_connected, universal, relay_mode
        
        log.info("=" * 60)
        log.info("Nordic TX StartNotify called - Pegasus BLE client subscribing")
        log.info("=" * 60)
        
        NordicTXCharacteristic.nordic_tx_instance = self
        self.notifying = True
        
        # Create Universal instance for this connection
        try:
            universal = Universal(
                sendMessage_callback=sendMessage,
                client_type=Universal.CLIENT_PEGASUS,
                compare_mode=relay_mode
            )
            log.info(f"[Universal] Instantiated for Pegasus BLE with client_type=PEGASUS, compare_mode={relay_mode}")
        except Exception as e:
            log.error(f"[Universal] Error instantiating: {e}")
            import traceback
            traceback.print_exc()
        
        ble_connected = True
        log.info("Nordic BLE notifications enabled successfully")

    def StopNotify(self):
        global ble_connected, universal
        
        if not self.notifying:
            return
        
        log.info("=" * 60)
        log.info("PEGASUS BLE CLIENT DISCONNECTED")
        log.info("=" * 60)
        
        self.notifying = False
        ble_connected = False
        universal = None
        log.info("[Universal] Instance reset - ready for new connection")

    def send_notification(self, data):
        """Send data to Pegasus client via notification."""
        if not self.notifying:
            log.debug("Nordic send_notification: Not notifying, skipping")
            return
        
        value = dbus.Array([dbus.Byte(b) for b in data], signature='y')
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])
        log.debug(f"Nordic TX notification sent: {len(data)} bytes")


class NordicRXCharacteristic(Characteristic):
    """Nordic RX characteristic (6E400002) - receives commands FROM Pegasus client.
    
    The client writes commands here, and this characteristic processes them
    and sends responses via the Nordic TX characteristic.
    """
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, NORDIC_UUIDS["rx"],
                                ['write', 'write-without-response'], service)
        log.info(f"Nordic RX Characteristic created: {NORDIC_UUIDS['rx']}")

    def WriteValue(self, value, options):
        global kill, ble_connected, shadow_target_connected, shadow_target_sock
        global relay_mode, shadow_target, universal
        
        if kill:
            return
        
        try:
            bytes_data = bytearray([int(b) for b in value])
            hex_str = ' '.join(f'{b:02x}' for b in bytes_data)
            ascii_str = ''.join(chr(b & 127) if 32 <= (b & 127) < 127 else '.' for b in bytes_data)
            
            log.info(f"Nordic BLE RX: {len(bytes_data)} bytes")
            log.info(f"  Hex: {hex_str}")
            log.info(f"  ASCII: {ascii_str}")
            
            # Process through Universal (Pegasus protocol)
            if universal is not None:
                for byte_val in bytes_data:
                    universal.receive_data(byte_val)
                log.debug(f"Processed {len(bytes_data)} bytes through universal parser (Pegasus)")
            else:
                log.warning("universal is None - data not processed")
            
            # Forward to shadow target if in relay mode
            if relay_mode and shadow_target_connected and shadow_target_sock is not None:
                try:
                    data_to_send = bytes(bytes_data)
                    log.info(f"Nordic BLE -> SHADOW TARGET: {len(data_to_send)} bytes")
                    shadow_target_sock.send(data_to_send)
                except (bluetooth.BluetoothError, OSError) as e:
                    log.error(f"Error sending to {shadow_target}: {e}")
                    shadow_target_connected = False
            
            ble_connected = True
            
        except Exception as e:
            log.error(f"Error in Nordic RX WriteValue: {e}")
            import traceback
            log.error(traceback.format_exc())


class NordicUARTService(Service):
    """Nordic UART Service - used by Pegasus clients.
    
    Real Pegasus board uses Nordic UART Service (NUS) for BLE communication.
    """
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, NORDIC_UUIDS["service"], True)
        
        # Add TX characteristic (notify FROM device) - index 0
        self.add_characteristic(NordicTXCharacteristic(bus, 0, self))
        # Add RX characteristic (write TO device) - index 1
        self.add_characteristic(NordicRXCharacteristic(bus, 1, self))
        
        log.info(f"Nordic UART Service created: {NORDIC_UUIDS['service']}")


# ============================================================================
# sendMessage callback for Universal
# ============================================================================

def sendMessage(data):
    """Send a message via BLE (Millennium or Nordic) or BT classic.
    
    Args:
        data: Message data bytes (already formatted with messageType, length, payload)
    """
    global _last_message, relay_mode, shadow_target

    tosend = bytearray(data)
    _last_message = tosend
    log.info(f"[sendMessage] tosend={' '.join(f'{b:02x}' for b in tosend)}")
    
    # In relay mode, messages are forwarded to the relay target, so don't send back to client
    if relay_mode:
        log.debug(f"[sendMessage] Relay mode enabled - not sending to client")
        return
    
    # Send via Millennium BLE if connected
    if TXCharacteristic.tx_instance is not None and TXCharacteristic.tx_instance.notifying:
        try:
            log.info(f"[sendMessage] Sending {len(tosend)} bytes via Millennium BLE")
            TXCharacteristic.tx_instance.send_notification(tosend)
        except Exception as e:
            log.error(f"[sendMessage] Error sending via Millennium BLE: {e}")
    
    # Send via Nordic (Pegasus) BLE if connected
    if NordicTXCharacteristic.nordic_tx_instance is not None and NordicTXCharacteristic.nordic_tx_instance.notifying:
        try:
            log.info(f"[sendMessage] Sending {len(tosend)} bytes via Nordic BLE (Pegasus)")
            NordicTXCharacteristic.nordic_tx_instance.send_notification(tosend)
        except Exception as e:
            log.error(f"[sendMessage] Error sending via Nordic BLE: {e}")
    
    # Send via BT classic if connected
    global client_connected, client_sock
    if client_connected and client_sock is not None:
        try:
            client_sock.send(bytes(tosend))
        except Exception as e:
            log.error(f"[sendMessage] Error sending via BT classic: {e}")


# ============================================================================
# Bluetooth Classic SPP Functions
# ============================================================================

def find_shadow_target_device(shadow_target="MILLENNIUM CHESS"):
    """Find the device by name."""
    log.info(f"Looking for {shadow_target} device...")
    
    # First, try to find in paired devices using bluetoothctl
    try:
        result = subprocess.run(['bluetoothctl', 'devices'], 
                              capture_output=True, timeout=5, text=True)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Device' in line:
                    parts = line.strip().split(' ', 2)
                    if len(parts) >= 3:
                        addr = parts[1]
                        name = parts[2]
                        log.info(f"Paired device: {name} ({addr})")
                        if name and shadow_target.upper() in name.upper():
                            log.info(f"Found {shadow_target} in paired devices: {addr}")
                            return addr
    except Exception as e:
        log.debug(f"Could not check paired devices: {e}")
    
    # If not found in paired devices, do a discovery scan
    log.info(f"Scanning for {shadow_target} device...")
    devices = bluetooth.discover_devices(duration=8, lookup_names=True, flush_cache=True)
    
    for addr, name in devices:
        log.info(f"Found device: {name} ({addr})")
        if name and shadow_target.upper() in name.upper():
            log.info(f"Found {shadow_target} at address: {addr}")
            return addr
    
    log.warning(f"{shadow_target} device not found in scan")
    return None


def find_shadow_target_service(device_addr):
    """Find the RFCOMM service on the SHADOW TARGET device"""
    log.info(f"Discovering services on {device_addr}...")
    
    services = bluetooth.find_service(address=device_addr)
    
    for service in services:
        log.info(f"Service: {service.get('name', 'Unknown')} - "
                 f"Protocol: {service.get('protocol', 'Unknown')} - "
                 f"Port: {service.get('port', 'Unknown')}")
        
        if service.get('protocol') == 'RFCOMM':
            port = service.get('port')
            if port is not None:
                log.info(f"Found RFCOMM service on port {port}")
                return port
    
    log.warning(f"No RFCOMM service found on {device_addr}")
    return None


def connect_to_shadow_target(shadow_target="MILLENNIUM CHESS"):
    """Connect to the target device."""
    global shadow_target_sock, shadow_target_connected
    global shadow_target_to_client_thread, shadow_target_to_client_thread_started
    
    try:
        device_addr = find_shadow_target_device(shadow_target=shadow_target)
        if not device_addr:
            log.error(f"Could not find SHADOW TARGET '{shadow_target}'")
            return False
        
        port = find_shadow_target_service(device_addr)
        if port is None:
            log.info("Trying common RFCOMM ports...")
            for common_port in [1, 2, 3, 4, 5]:
                try:
                    log.info(f"Attempting connection on port {common_port}...")
                    sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
                    sock.connect((device_addr, common_port))
                    shadow_target_sock = sock
                    shadow_target_connected = True
                    log.info(f"Connected to {device_addr} on port {common_port}")
                    if not shadow_target_to_client_thread_started:
                        shadow_target_to_client_thread = threading.Thread(target=shadow_target_to_client, daemon=True)
                        shadow_target_to_client_thread.start()
                        shadow_target_to_client_thread_started = True
                    return True
                except Exception as e:
                    log.debug(f"Failed on port {common_port}: {e}")
                    try:
                        sock.close()
                    except:
                        pass
            log.error(f"Could not connect to {device_addr} on any common port")
            return False
        
        log.info(f"Connecting to {device_addr}:{port}...")
        shadow_target_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        shadow_target_sock.connect((device_addr, port))
        shadow_target_connected = True
        log.info(f"Connected to SHADOW TARGET successfully")
        if not shadow_target_to_client_thread_started:
            shadow_target_to_client_thread = threading.Thread(target=shadow_target_to_client, daemon=True)
            shadow_target_to_client_thread.start()
            shadow_target_to_client_thread_started = True
        return True
        
    except Exception as e:
        log.error(f"Error connecting to SHADOW TARGET: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def shadow_target_to_client():
    """Relay data from SHADOW TARGET to client."""
    global running, shadow_target_sock, client_sock, shadow_target_connected, client_connected
    global _last_message, shadow_target, universal
    
    log.info(f"Starting SHADOW TARGET -> Client relay thread")
    try:
        while running and not kill:
            try:
                if not shadow_target_connected or shadow_target_sock is None:
                    time.sleep(0.1)
                    continue
                
                data = shadow_target_sock.recv(1024)
                if len(data) > 0:
                    data_bytes = bytearray(data)
                    log.info(f"SHADOW TARGET -> Client: {' '.join(f'{b:02x}' for b in data_bytes)}")
                    
                    if universal is not None and universal.compare_mode:
                        match, emulator_response = universal.compare_with_shadow(bytes(data_bytes))
                        if match is False:
                            log.error("[Relay] MISMATCH: Emulator response differs from shadow host")
                        elif match is True:
                            log.info("[Relay] MATCH: Emulator response matches shadow host")
                    
                    if client_connected and client_sock is not None:
                        client_sock.send(data)
                    
                    if TXCharacteristic.tx_instance is not None:
                        TXCharacteristic.tx_instance.send_notification(data_bytes)

            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error in relay: {e}")
                shadow_target_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error in relay: {e}")
                break
    except Exception as e:
        log.error(f"Relay thread error: {e}")
    finally:
        log.info("SHADOW TARGET -> Client relay thread stopped")
        shadow_target_connected = False


def client_to_shadow_target():
    """Relay data from client to SHADOW TARGET"""
    global running, shadow_target_sock, client_sock, shadow_target_connected, client_connected, universal
    
    log.info("Starting Client -> SHADOW TARGET relay thread")
    try:
        while running and not kill:
            try:
                if not client_connected or client_sock is None:
                    time.sleep(0.1)
                    continue
                
                if not shadow_target_connected or shadow_target_sock is None:
                    time.sleep(0.1)
                    continue
                
                data = client_sock.recv(1024)
                if len(data) == 0:
                    log.info("RFCOMM client disconnected")
                    client_connected = False
                    universal = None
                    break
                
                data_bytes = bytearray(data)
                log.info(f"Client -> SHADOW TARGET: {' '.join(f'{b:02x}' for b in data_bytes)}")
                
                if universal is not None:
                    for byte_val in data_bytes:
                        universal.receive_data(byte_val)
                
                if shadow_target_sock is not None: 
                    shadow_target_sock.send(data)
                    
            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error: {e}")
                client_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error: {e}")
                break
    except Exception as e:
        log.error(f"Thread error: {e}")
    finally:
        log.info("Client -> SHADOW TARGET relay thread stopped")
        client_connected = False


def client_reader():
    """Read data from RFCOMM client in server-only mode."""
    global running, client_sock, client_connected, universal
    
    log.info("Starting Client reader thread (server-only mode)")
    try:
        while running and not kill:
            try:
                if not client_connected or client_sock is None:
                    time.sleep(0.1)
                    continue
                
                data = client_sock.recv(1024)
                if len(data) == 0:
                    log.info("RFCOMM client disconnected")
                    client_connected = False
                    universal = None
                    break
                
                data_bytes = bytearray(data)
                log.info(f"Client -> Server: {' '.join(f'{b:02x}' for b in data_bytes)}")
                
                if universal is not None:
                    for byte_val in data_bytes:
                        universal.receive_data(byte_val)
                else:
                    log.warning("universal is None - data not processed")
                    
            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error: {e}")
                client_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error: {e}")
                break
    except Exception as e:
        log.error(f"Thread error: {e}")
    finally:
        log.info("Client reader thread stopped")
        client_connected = False


def cleanup():
    """Clean up connections and resources"""
    global kill, running, shadow_target_sock, client_sock, server_sock
    global shadow_target_connected, client_connected, ble_app, mainloop
    global universal
    
    try:
        log.info("Cleaning up...")
        kill = 1
        running = False
        universal = None
        
        if client_sock:
            try:
                client_sock.close()
            except:
                pass
        
        if shadow_target_sock:
            try:
                shadow_target_sock.close()
            except:
                pass
        
        if server_sock:
            try:
                server_sock.close()
            except:
                pass
        
        if mainloop:
            try:
                mainloop.quit()
            except:
                pass
        
        shadow_target_connected = False
        client_connected = False
        
        log.info("Cleanup completed")
    except Exception as e:
        log.error(f"Error in cleanup: {e}")


def signal_handler(signum, frame):
    """Handle termination signals"""
    log.info(f"Received signal {signum}, cleaning up...")
    cleanup()
    sys.exit(0)


def main():
    """Main entry point"""
    global server_sock, client_sock, shadow_target_sock
    global shadow_target_connected, client_connected, running, kill
    global ble_app, mainloop, shadow_target_to_client_thread, shadow_target_to_client_thread_started
    global relay_mode, shadow_target, universal
    
    parser = argparse.ArgumentParser(description="Bluetooth Classic SPP Relay with BLE")
    parser.add_argument("--local-name", type=str, default="MILLENNIUM CHESS",
                       help="Local name for BLE advertisement")
    parser.add_argument("--shadow-target", type=str, default="MILLENNIUM CHESS",
                       help="Name of the target device to connect to in relay mode")
    parser.add_argument("--port", type=int, default=None,
                       help="RFCOMM port for server (default: auto-assign)")
    parser.add_argument("--device-name", type=str, default="MILLENNIUM CHESS",
                       help="Bluetooth device name")
    parser.add_argument("--relay", action="store_true",
                       help="Enable relay mode - connect to shadow_target and relay data")
    parser.add_argument("--no-ble", action="store_true",
                       help="Disable BLE (GATT) server")
    parser.add_argument("--no-rfcomm", action="store_true",
                       help="Disable RFCOMM server")
    
    args = parser.parse_args()
    
    log.info("=" * 60)
    log.info("Universal Relay Starting")
    log.info("=" * 60)
    log.info(f"Device name: {args.device_name}")
    log.info(f"BLE: {'Disabled' if args.no_ble else 'Enabled'}")
    log.info(f"RFCOMM: {'Disabled' if args.no_rfcomm else 'Enabled'}")
    log.info(f"Relay mode: {'Enabled' if args.relay else 'Disabled'}")
    if args.relay:
        log.info(f"Shadow target: {args.shadow_target}")
    log.info("=" * 60)
    
    relay_mode = args.relay
    shadow_target = args.shadow_target
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Configure adapter security settings BEFORE D-Bus setup
    if not args.no_ble:
        log.info("Configuring adapter security...")
        configure_adapter_security()
    
    # Initialize D-Bus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    mainloop = GLib.MainLoop()
    
    adapter = find_adapter(bus)
    if not adapter:
        log.error("No Bluetooth adapter found")
        return
    log.info(f"Found Bluetooth adapter: {adapter}")
    
    # Configure adapter properties
    adapter_props = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter),
        DBUS_PROP_IFACE)
    
    # Set adapter name/alias
    try:
        adapter_props.Set("org.bluez.Adapter1", "Alias", dbus.String(args.device_name))
        log.info(f"Adapter Alias set to '{args.device_name}'")
    except dbus.exceptions.DBusException as e:
        log.warning(f"Could not set Alias: {e}")
    
    # Ensure adapter is powered on
    try:
        powered = adapter_props.Get("org.bluez.Adapter1", "Powered")
        if not powered:
            adapter_props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
            log.info("Adapter powered on")
    except dbus.exceptions.DBusException as e:
        log.warning(f"Could not check/set Powered: {e}")
    
    # Make adapter discoverable
    try:
        adapter_props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(True))
        adapter_props.Set("org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(0))
        log.info("Adapter Discoverable set to True (infinite timeout)")
    except dbus.exceptions.DBusException as e:
        log.warning(f"Could not set Discoverable: {e}")
    
    # For BLE: disable pairing requirement (like real Millennium board)
    if not args.no_ble:
        try:
            adapter_props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(False))
            log.info("Adapter Pairable set to False (BLE - no pairing required)")
        except dbus.exceptions.DBusException as e:
            log.warning(f"Could not set Pairable: {e}")
    
    # Register NoInputNoOutput agent
    agent = NoInputNoOutputAgent(bus)
    agent_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, '/org/bluez'),
        AGENT_MANAGER_IFACE)
    
    try:
        agent_manager.UnregisterAgent(agent.AGENT_PATH)
    except dbus.exceptions.DBusException:
        pass
    
    try:
        agent_manager.RegisterAgent(agent.AGENT_PATH, agent.CAPABILITY)
        agent_manager.RequestDefaultAgent(agent.AGENT_PATH)
        log.info(f"Agent registered with capability: {agent.CAPABILITY}")
    except dbus.exceptions.DBusException as e:
        log.warning(f"Could not register agent: {e}")
    
    # Setup BLE if enabled
    if not args.no_ble:
        ble_app = Application(bus)
        ble_app.add_service(DeviceInfoService(bus, 0))
        ble_app.add_service(MillenniumService(bus, 1))
        ble_app.add_service(NordicUARTService(bus, 2))  # For Pegasus clients
        
        gatt_manager = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, adapter),
            GATT_MANAGER_IFACE)
        
        def gatt_register_success():
            log.info("GATT application registered successfully")
        
        def gatt_register_error(error):
            log.error(f"Failed to register GATT application: {error}")
        
        log.info("Registering GATT application...")
        gatt_manager.RegisterApplication(
            ble_app.get_path(), {},
            reply_handler=gatt_register_success,
            error_handler=gatt_register_error)
        
        # Create and register advertisements
        # We create two separate advertisements:
        # 1. Millennium advertisement - for ChessLink app (scans by service UUID)
        # 2. Pegasus advertisement - for DGT Pegasus app (scans by name pattern and Nordic UUID)
        # Each advertisement contains only one 128-bit UUID to stay within the 31-byte limit.
        
        ad_manager = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, adapter),
            LE_ADVERTISING_MANAGER_IFACE)
        
        # Advertisement 1: Millennium (for ChessLink app)
        adv_millennium = Advertisement(bus, 0, args.device_name, service_uuids=[MILLENNIUM_UUIDS["service"]])
        
        def adv_millennium_success():
            log.info("Millennium advertisement registered successfully")
        
        def adv_millennium_error(error):
            log.error(f"Failed to register Millennium advertisement: {error}")
        
        log.info("Registering Millennium advertisement...")
        ad_manager.RegisterAdvertisement(
            adv_millennium.get_path(), {},
            reply_handler=adv_millennium_success,
            error_handler=adv_millennium_error)
        
        # Advertisement 2: Pegasus (for DGT Pegasus app)
        # Use Pegasus-style name: DGT_PEGASUS_<serial>
        # Try to get serial from centaur if available, otherwise use default
        try:
            from DGTCentaurMods.board import board as board_module
            serial_no = board_module.getMetaProperty('serial no') or '50000'
        except Exception:
            serial_no = '50000'
        pegasus_name = f"DGT_PEGASUS_{serial_no}"
        adv_pegasus = Advertisement(bus, 1, pegasus_name, service_uuids=[NORDIC_UUIDS["service"]])
        
        def adv_pegasus_success():
            log.info("Pegasus advertisement registered successfully")
        
        def adv_pegasus_error(error):
            log.error(f"Failed to register Pegasus advertisement: {error}")
        
        log.info(f"Registering Pegasus advertisement (name: {pegasus_name})...")
        ad_manager.RegisterAdvertisement(
            adv_pegasus.get_path(), {},
            reply_handler=adv_pegasus_success,
            error_handler=adv_pegasus_error)
        
        time.sleep(1)
    
    # Setup RFCOMM if enabled
    if not args.no_rfcomm:
        # Kill any existing rfcomm processes
        os.system('sudo service rfcomm stop 2>/dev/null')
        time.sleep(1)
        
        for p in psutil.process_iter(attrs=['pid', 'name']):
            if str(p.info["name"]) == "rfcomm":
                try:
                    p.kill()
                except:
                    pass
        
        time.sleep(0.5)
        
        # Create Bluetooth controller for pairing
        bluetooth_controller = BluetoothController(device_name=args.device_name)
        bluetooth_controller.enable_bluetooth()
        bluetooth_controller.set_device_name(args.device_name)
        bluetooth_controller.start_pairing_thread()
        
        time.sleep(1)
        
        # Initialize server socket
        log.info("Setting up RFCOMM server socket...")
        server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        server_sock.bind(("", args.port if args.port else bluetooth.PORT_ANY))
        server_sock.settimeout(0.5)
        server_sock.listen(1)
        port = server_sock.getsockname()[1]
        uuid = "94f39d29-7d6d-437d-973b-fba39e49d4ee"
        
        try:
            bluetooth.advertise_service(server_sock, args.device_name, service_id=uuid,
                                      service_classes=[uuid, bluetooth.SERIAL_PORT_CLASS],
                                      profiles=[bluetooth.SERIAL_PORT_PROFILE])
            log.info(f"RFCOMM service '{args.device_name}' advertised on channel {port}")
        except Exception as e:
            log.error(f"Failed to advertise RFCOMM service: {e}")
    
    # Start GLib mainloop in a thread for BLE
    def ble_mainloop():
        try:
            mainloop.run()
        except Exception as e:
            log.error(f"Error in BLE mainloop: {e}")
    
    if not args.no_ble:
        ble_thread = threading.Thread(target=ble_mainloop, daemon=True)
        ble_thread.start()
        log.info("BLE mainloop thread started")
    
    # Connect to shadow target if relay mode
    if relay_mode:
        log.info("=" * 60)
        log.info(f"RELAY MODE - Connecting to {shadow_target}")
        log.info("=" * 60)
        
        def connect_shadow():
            time.sleep(1)
            if connect_to_shadow_target(shadow_target=shadow_target):
                log.info(f"{shadow_target} connection established")
            else:
                log.error(f"Failed to connect to {shadow_target}")
                global kill
                kill = 1
        
        shadow_thread = threading.Thread(target=connect_shadow, daemon=True)
        shadow_thread.start()
    
    log.info("")
    log.info("Waiting for connections...")
    log.info(f"Device name: {args.device_name}")
    if not args.no_ble:
        log.info("  BLE: Ready for GATT connections")
    if not args.no_rfcomm:
        log.info(f"  RFCOMM: Listening on channel {port}")
    log.info("")
    
    # Wait for RFCOMM client connection (BLE is handled via callbacks)
    connected = False
    if not args.no_rfcomm:
        while not connected and not ble_connected and not kill:
            try:
                client_sock, client_info = server_sock.accept()
                connected = True
                client_connected = True
                log.info("=" * 60)
                log.info("RFCOMM CLIENT CONNECTED")
                log.info("=" * 60)
                log.info(f"Client address: {client_info}")
                
                universal = Universal(
                    sendMessage_callback=sendMessage,
                    client_type=None,
                    compare_mode=relay_mode
                )
                log.info("[Universal] Instantiated for RFCOMM")
                
            except bluetooth.BluetoothError:
                time.sleep(0.1)
            except Exception as e:
                if running:
                    log.error(f"Error accepting connection: {e}")
                time.sleep(0.1)
    
    # Wait for shadow target connection if relay mode
    if relay_mode:
        max_wait = 30
        wait_time = 0
        while not shadow_target_connected and wait_time < max_wait and not kill:
            time.sleep(0.5)
            wait_time += 0.5
        
        if not shadow_target_connected:
            log.error("Shadow target connection timeout")
            cleanup()
            sys.exit(1)
    
    # Start appropriate relay/reader threads
    if relay_mode:
        if connected and client_sock is not None:
            client_to_shadow_target_thread = threading.Thread(target=client_to_shadow_target, daemon=True)
            client_to_shadow_target_thread.start()
    else:
        if connected and client_sock is not None:
            client_reader_thread = threading.Thread(target=client_reader, daemon=True)
            client_reader_thread.start()
    
    # Main loop
    try:
        while running and not kill:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Keyboard interrupt")
        running = False
    except Exception as e:
        log.error(f"Error in main loop: {e}")
        running = False
    
    cleanup()
    log.info("Exiting")


if __name__ == "__main__":
    main()
