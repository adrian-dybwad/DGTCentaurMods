#!/usr/bin/env python3
# Universal Bluetooth Relay
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

"""
Universal Bluetooth Relay with BLE and RFCOMM Support

This relay connects to a target device via Bluetooth Classic SPP (RFCOMM)
and relays data between that device and a client connected to this relay.
Also provides BLE service matching millennium.py for host connections.

BLE Implementation:
- Uses direct D-Bus/BlueZ GATT implementation (no thirdparty dependencies)
- Matches the working millennium_sniffer.py implementation
- Supports BLE without pairing (like real Millennium board)
- Supports RFCOMM with pairing (Serial Port Profile)

Usage:
    python3 universal.py
"""

import argparse
import sys
import os
import time
import threading
import signal
import subprocess
import socket
import random
import psutil
import bluetooth
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import chess

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board import board
from DGTCentaurMods.epaper import ChessBoardWidget, SplashScreen
from DGTCentaurMods.bluetooth_controller import BluetoothController
from DGTCentaurMods.game_handler import GameHandler

# Global state
running = True
kill = 0
shadow_target_connected = False
client_connected = False
ble_connected = False
ble_client_type = None  # Track which BLE client type is connected: 'millennium' or 'pegasus'
game_handler = None  # GameHandler instance
_last_message = None  # Last message sent via sendMessage
relay_mode = False  # Whether relay mode is enabled (connects to relay target)
shadow_target = "MILLENNIUM CHESS"  # Default target device name (can be overridden via --shadow-target)
mainloop = None  # GLib mainloop for BLE
chess_board_widget = None  # ChessBoardWidget for e-paper display

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
# Real board has 4 services:
# 1. FEN Service (1b7e8261) - contains FEN RX characteristic (notify)
# 2. Operation Service (1b7e8271) - contains OP TX (write) and OP RX (notify)
# 3. Unknown Service (1b7e8281) - contains write and notify characteristics
# 4. OTA Service (9e5d1e47) - firmware update service
CHESSNUT_UUIDS = {
    # Service 1: FEN
    "fen_service": "1b7e8261-2877-41c3-b46e-cf057c562023",
    "fen_rx": "1b7e8262-2877-41c3-b46e-cf057c562023",
    # Service 2: Operation
    "op_service": "1b7e8271-2877-41c3-b46e-cf057c562023",
    "op_tx": "1b7e8272-2877-41c3-b46e-cf057c562023",
    "op_rx": "1b7e8273-2877-41c3-b46e-cf057c562023",
    # Service 3: Unknown
    "unk_service": "1b7e8281-2877-41c3-b46e-cf057c562023",
    "unk_tx": "1b7e8282-2877-41c3-b46e-cf057c562023",
    "unk_rx": "1b7e8283-2877-41c3-b46e-cf057c562023",
    # Service 4: OTA
    "ota_service": "9e5d1e47-5c13-43a0-8635-82ad38a1386f",
    "ota_char1": "e3dd50bf-f7a7-4e99-838e-570a086c666b",
    "ota_char2": "92e86c7a-d961-4091-b74f-2409e72efe36",
    "ota_char3": "347f7608-2e2d-47eb-913b-75d4edc4de3b",
}

# Chessnut manufacturer data for advertisement
# Company ID: 0x4450 (17488)
# Payload from real board: 4353b953056400003e9751101b00
CHESSNUT_MANUFACTURER_ID = 0x4450
CHESSNUT_MANUFACTURER_DATA = bytes.fromhex("4353b953056400003e9751101b00")

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
    
    AGENT_PATH = "/org/bluez/universal_agent"
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
    """BLE Advertisement for universal relay.
    
    Advertises services for discovery by chess apps:
    - Millennium/Pegasus: Uses ServiceUUIDs
    - Chessnut: Uses ManufacturerData (company ID 0x4450)
    
    BLE advertisement packets are limited to 31 bytes. To fit all required data:
    - Primary advertisement: LocalName + ServiceUUIDs (for Pegasus)
    - Scan response: ManufacturerData (for Chessnut)
    
    This uses BlueZ's ScanResponseManufacturerData property.
    """
    
    PATH_BASE = '/org/bluez/universal/advertisement'

    def __init__(self, bus, index, name, service_uuids=None, scan_rsp_uuids=None, 
                 manufacturer_data=None, scan_rsp_manufacturer_data=None):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = 'peripheral'
        self.local_name = name
        self.include_tx_power = True
        self.service_uuids = service_uuids or []
        self.scan_rsp_uuids = scan_rsp_uuids or []
        self.manufacturer_data = manufacturer_data  # Dict of {company_id: bytes} for primary adv
        self.scan_rsp_manufacturer_data = scan_rsp_manufacturer_data  # Dict for scan response
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        properties['LocalName'] = dbus.String(self.local_name)
        properties['IncludeTxPower'] = dbus.Boolean(True)
        properties['TxPower'] = dbus.Int16(0)
        
        # Primary service UUIDs in advertisement data
        if self.service_uuids:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
        
        # Additional service UUIDs in scan response
        if self.scan_rsp_uuids:
            properties['ScanResponseServiceUUIDs'] = dbus.Array(self.scan_rsp_uuids, signature='s')
        
        # Manufacturer data in primary advertisement
        if self.manufacturer_data:
            mfr_dict = {}
            for company_id, data in self.manufacturer_data.items():
                mfr_dict[dbus.UInt16(company_id)] = dbus.Array([dbus.Byte(b) for b in data], signature='y')
            properties['ManufacturerData'] = dbus.Dictionary(mfr_dict, signature='qv')
        
        # Manufacturer data in scan response (allows fitting more data)
        if self.scan_rsp_manufacturer_data:
            mfr_dict = {}
            for company_id, data in self.scan_rsp_manufacturer_data.items():
                mfr_dict[dbus.UInt16(company_id)] = dbus.Array([dbus.Byte(b) for b in data], signature='y')
            properties['ScanResponseManufacturerData'] = dbus.Dictionary(mfr_dict, signature='qv')
        
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
        self.path = '/org/bluez/universal'
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
    
    PATH_BASE = '/org/bluez/universal/service'

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
        global ble_connected, game_handler, relay_mode
        
        log.info("TX Characteristic ReadValue called by BLE client")
        
        # Treat ReadValue as a connection event
        if not ble_connected:
            log.info("ReadValue triggered - Millennium BLE client connecting")
            TXCharacteristic.tx_instance = self
            game_handler.on_app_connected()
            ble_connected = True
        
        log.debug(f"TX ReadValue: {len(self._cached_value)} bytes")
        return dbus.Array([dbus.Byte(b) for b in self._cached_value], signature='y')

    def WriteValue(self, value, options):
        data = bytes([int(b) for b in value])
        log.debug(f"TX WriteValue: {data.hex()}")

    def StartNotify(self):
        global ble_connected, ble_client_type, game_handler, relay_mode
        
        log.info("=" * 60)
        log.info("TX Characteristic StartNotify called - Millennium BLE client subscribing")
        log.info("=" * 60)
        
        # Reset other protocol states
        if NordicTXCharacteristic.nordic_tx_instance is not None:
            NordicTXCharacteristic.nordic_tx_instance.notifying = False
        
        TXCharacteristic.tx_instance = self
        self.notifying = True
        ble_client_type = 'millennium'
        
        # Notify GameHandler that an app connected
        game_handler.on_app_connected()
        
        ble_connected = True
        log.info("Millennium BLE notifications enabled successfully")

    def StopNotify(self):
        global ble_connected, ble_client_type, game_handler
        
        if not self.notifying:
            return
        
        log.info("=" * 60)
        log.info("MILLENNIUM BLE CLIENT DISCONNECTED")
        log.info("=" * 60)
        
        self.notifying = False
        ble_connected = False
        ble_client_type = None
        game_handler.on_app_disconnected()
        log.info("[GameHandler] App disconnected - standalone engine may resume")

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
        global relay_mode, shadow_target, game_handler
        
        if kill:
            return
        
        try:
            bytes_data = bytearray([int(b) for b in value])
            hex_str = ' '.join(f'{b:02x}' for b in bytes_data)
            ascii_str = ''.join(chr(b & 127) if 32 <= (b & 127) < 127 else '.' for b in bytes_data)
            
            log.info(f"BLE RX: {len(bytes_data)} bytes")
            log.info(f"  Hex: {hex_str}")
            log.info(f"  ASCII: {ascii_str}")
            
            # Notify app connection on first RX data (Millennium)
            if not ble_connected:
                log.info("[GameHandler] First RX data from Millennium")
                # Reset any stale Pegasus state
                if NordicTXCharacteristic.nordic_tx_instance is not None:
                    NordicTXCharacteristic.nordic_tx_instance.notifying = False
                ble_client_type = 'millennium'
                game_handler.on_app_connected()
            
            # Process through GameHandler
            for byte_val in bytes_data:
                game_handler.receive_data(byte_val)
            log.debug(f"Processed {len(bytes_data)} bytes through game handler parser")
            
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
        global ble_connected, ble_client_type, game_handler, relay_mode
        
        log.info("=" * 60)
        log.info("Nordic TX StartNotify called - Pegasus BLE client subscribing")
        log.info("=" * 60)
        
        # Reset other protocol states
        if TXCharacteristic.tx_instance is not None:
            TXCharacteristic.tx_instance.notifying = False
        
        NordicTXCharacteristic.nordic_tx_instance = self
        self.notifying = True
        ble_client_type = 'pegasus'
        
        # Notify GameHandler that an app connected
        game_handler.on_app_connected()
        
        ble_connected = True
        log.info("Pegasus BLE notifications enabled successfully")

    def StopNotify(self):
        global ble_connected, ble_client_type, game_handler
        
        if not self.notifying:
            return
        
        log.info("=" * 60)
        log.info("PEGASUS BLE CLIENT DISCONNECTED")
        log.info("=" * 60)
        
        self.notifying = False
        ble_connected = False
        ble_client_type = None
        game_handler.on_app_disconnected()
        log.info("[GameHandler] App disconnected - standalone engine may resume")

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
        global relay_mode, shadow_target, game_handler
        
        if kill:
            return
        
        try:
            bytes_data = bytearray([int(b) for b in value])
            hex_str = ' '.join(f'{b:02x}' for b in bytes_data)
            ascii_str = ''.join(chr(b & 127) if 32 <= (b & 127) < 127 else '.' for b in bytes_data)
            
            log.info(f"Nordic BLE RX: {len(bytes_data)} bytes")
            log.info(f"  Hex: {hex_str}")
            log.info(f"  ASCII: {ascii_str}")
            
            # Notify app connection on first RX data (Pegasus)
            if not ble_connected:
                log.info("[GameHandler] First RX data from Pegasus")
                # Reset any stale Millennium state
                if TXCharacteristic.tx_instance is not None:
                    TXCharacteristic.tx_instance.notifying = False
                ble_client_type = 'pegasus'
                game_handler.on_app_connected()
            
            # Process through GameHandler (Pegasus protocol)
            for byte_val in bytes_data:
                game_handler.receive_data(byte_val)
            log.debug(f"Processed {len(bytes_data)} bytes through game handler parser (Pegasus)")
            
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
# Chessnut Air Service Characteristics
# ============================================================================

class ChessnutFENCharacteristic(Characteristic):
    """Chessnut FEN RX Characteristic (1b7e8262) - Notify FEN/board state to client.
    
    Sends 38-byte FEN notifications:
    - Bytes 0-1: Header [0x01, 0x24]
    - Bytes 2-33: Position data (32 bytes, 2 squares per byte)
    - Bytes 34-37: Uptime counter (little-endian uint16) + [0x00, 0x00]
    """
    
    fen_instance = None
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, CHESSNUT_UUIDS["fen_rx"],
                                ['notify'], service)
        self.notifying = False
        ChessnutFENCharacteristic.fen_instance = self
        log.info(f"Chessnut FEN Characteristic created: {CHESSNUT_UUIDS['fen_rx']}")

    def StartNotify(self):
        log.info("Chessnut FEN StartNotify")
        self.notifying = True

    def StopNotify(self):
        log.info("Chessnut FEN StopNotify")
        self.notifying = False

    def send_notification(self, data):
        """Send FEN notification to client."""
        if not self.notifying:
            return
        value = dbus.Array([dbus.Byte(b) for b in data], signature='y')
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])
        log.debug(f"Chessnut FEN notification sent: {len(data)} bytes")


class ChessnutOperationTXCharacteristic(Characteristic):
    """Chessnut Operation TX Characteristic (1b7e8272) - Receives commands from client.
    
    Commands are written here by the client:
    - 0x0b: Init/config (no response)
    - 0x21: Enable reporting
    - 0x27: Haptic control (no response)
    - 0x29: Battery request
    - 0x31: Sound control (no response)
    - 0x0a: LED control
    """
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, CHESSNUT_UUIDS["op_tx"],
                                ['write', 'write-without-response'], service)
        log.info(f"Chessnut OP TX Characteristic created: {CHESSNUT_UUIDS['op_tx']}")

    def WriteValue(self, value, options):
        global kill, ble_connected, game_handler, relay_mode
        
        if kill:
            return
        
        try:
            bytes_data = bytearray([int(b) for b in value])
            hex_str = ' '.join(f'{b:02x}' for b in bytes_data)
            
            log.info(f"Chessnut OP TX RX: {len(bytes_data)} bytes")
            log.info(f"  Hex: {hex_str}")
            
            # Notify app connection on first RX data (Chessnut)
            if not ble_connected:
                log.info("[GameHandler] First RX data from Chessnut")
                # Reset any stale Millennium/Pegasus state
                if TXCharacteristic.tx_instance is not None:
                    TXCharacteristic.tx_instance.notifying = False
                if NordicTXCharacteristic.nordic_tx_instance is not None:
                    NordicTXCharacteristic.nordic_tx_instance.notifying = False
                ble_client_type = 'chessnut'
                game_handler.on_app_connected()
            
            # Process through GameHandler (Chessnut protocol)
            for byte_val in bytes_data:
                game_handler.receive_data(byte_val)
            log.debug(f"Processed {len(bytes_data)} bytes through game handler parser (Chessnut)")
            
            ble_connected = True
            
        except Exception as e:
            log.error(f"Error in Chessnut OP TX WriteValue: {e}")
            import traceback
            log.error(traceback.format_exc())


class ChessnutOperationRXCharacteristic(Characteristic):
    """Chessnut Operation RX Characteristic (1b7e8273) - Notify responses to client.
    
    Sends command responses:
    - Battery response: [0x2a, 0x02, battery_level, 0x00]
    """
    
    op_rx_instance = None
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, CHESSNUT_UUIDS["op_rx"],
                                ['notify'], service)
        self.notifying = False
        ChessnutOperationRXCharacteristic.op_rx_instance = self
        log.info(f"Chessnut OP RX Characteristic created: {CHESSNUT_UUIDS['op_rx']}")

    def StartNotify(self):
        global ble_connected, ble_client_type, game_handler, relay_mode
        
        log.info("=" * 60)
        log.info("Chessnut OP RX StartNotify called - Chessnut BLE client subscribing")
        log.info("=" * 60)
        
        # Reset other protocol states but keep existing Universal if it's already Chessnut
        if TXCharacteristic.tx_instance is not None:
            TXCharacteristic.tx_instance.notifying = False
        if NordicTXCharacteristic.nordic_tx_instance is not None:
            NordicTXCharacteristic.nordic_tx_instance.notifying = False
        
        ChessnutOperationRXCharacteristic.op_rx_instance = self
        self.notifying = True
        ble_client_type = 'chessnut'
        
        # Notify GameHandler that an app connected
        game_handler.on_app_connected()
        
        ble_connected = True
        log.info("Chessnut BLE notifications enabled successfully")

    def StopNotify(self):
        global ble_connected, ble_client_type, game_handler
        
        if not self.notifying:
            return
        
        log.info("=" * 60)
        log.info("CHESSNUT BLE CLIENT DISCONNECTED")
        log.info("=" * 60)
        
        self.notifying = False
        ble_connected = False
        ble_client_type = None
        game_handler.on_app_disconnected()
        log.info("[GameHandler] App disconnected - standalone engine may resume")

    def send_notification(self, data):
        """Send notification to client."""
        if not self.notifying:
            return
        value = dbus.Array([dbus.Byte(b) for b in data], signature='y')
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])
        log.debug(f"Chessnut OP RX notification sent: {len(data)} bytes")


class ChessnutUnknownTXCharacteristic(Characteristic):
    """Chessnut Unknown TX Characteristic (1b7e8282) - Write."""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, CHESSNUT_UUIDS["unk_tx"],
                                ['write', 'write-without-response'], service)

    def WriteValue(self, value, options):
        bytes_data = bytearray([int(b) for b in value])
        hex_str = ' '.join(f'{b:02x}' for b in bytes_data)
        log.info(f"Chessnut UNK TX RX: {hex_str}")


class ChessnutUnknownRXCharacteristic(Characteristic):
    """Chessnut Unknown RX Characteristic (1b7e8283) - Notify."""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, CHESSNUT_UUIDS["unk_rx"],
                                ['notify'], service)
        self.notifying = False

    def StartNotify(self):
        self.notifying = True

    def StopNotify(self):
        self.notifying = False


class ChessnutOTAChar1(Characteristic):
    """Chessnut OTA Characteristic 1 - Write/Notify/Indicate."""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, CHESSNUT_UUIDS["ota_char1"],
                                ['write', 'notify', 'indicate'], service)
        self.notifying = False

    def WriteValue(self, value, options):
        bytes_data = bytearray([int(b) for b in value])
        log.info(f"Chessnut OTA1 RX: {' '.join(f'{b:02x}' for b in bytes_data)}")

    def StartNotify(self):
        self.notifying = True

    def StopNotify(self):
        self.notifying = False


class ChessnutOTAChar2(Characteristic):
    """Chessnut OTA Characteristic 2 - Write."""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, CHESSNUT_UUIDS["ota_char2"],
                                ['write'], service)

    def WriteValue(self, value, options):
        bytes_data = bytearray([int(b) for b in value])
        log.info(f"Chessnut OTA2 RX: {' '.join(f'{b:02x}' for b in bytes_data)}")


class ChessnutOTAChar3(Characteristic):
    """Chessnut OTA Characteristic 3 - Read."""
    
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, CHESSNUT_UUIDS["ota_char3"],
                                ['read'], service)

    def ReadValue(self, options):
        log.info("Chessnut OTA3 Read request")
        return dbus.Array([dbus.Byte(0x00)], signature='y')


class ChessnutFENService(Service):
    """Chessnut Air FEN Service (1b7e8261).
    
    Contains one characteristic:
    - FEN RX (1b7e8262): Notify - FEN/board state
    """
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, CHESSNUT_UUIDS["fen_service"], True)
        self.fen_char = ChessnutFENCharacteristic(bus, 0, self)
        self.add_characteristic(self.fen_char)
        log.info(f"Chessnut FEN Service created: {CHESSNUT_UUIDS['fen_service']}")


class ChessnutOperationService(Service):
    """Chessnut Air Operation Service (1b7e8271).
    
    Contains two characteristics:
    - Operation TX (1b7e8272): Write - commands from client
    - Operation RX (1b7e8273): Notify - responses to client
    """
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, CHESSNUT_UUIDS["op_service"], True)
        self.add_characteristic(ChessnutOperationTXCharacteristic(bus, 0, self))
        self.op_rx_char = ChessnutOperationRXCharacteristic(bus, 1, self)
        self.add_characteristic(self.op_rx_char)
        log.info(f"Chessnut Operation Service created: {CHESSNUT_UUIDS['op_service']}")


class ChessnutUnknownService(Service):
    """Chessnut Air Unknown Service (1b7e8281)."""
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, CHESSNUT_UUIDS["unk_service"], True)
        self.add_characteristic(ChessnutUnknownTXCharacteristic(bus, 0, self))
        self.add_characteristic(ChessnutUnknownRXCharacteristic(bus, 1, self))
        log.info(f"Chessnut Unknown Service created: {CHESSNUT_UUIDS['unk_service']}")


class ChessnutOTAService(Service):
    """Chessnut Air OTA Service (9e5d1e47)."""
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, CHESSNUT_UUIDS["ota_service"], True)
        self.add_characteristic(ChessnutOTAChar1(bus, 0, self))
        self.add_characteristic(ChessnutOTAChar2(bus, 1, self))
        self.add_characteristic(ChessnutOTAChar3(bus, 2, self))
        log.info(f"Chessnut OTA Service created: {CHESSNUT_UUIDS['ota_service']}")


# ============================================================================
# sendMessage callback for GameHandler
# ============================================================================

def sendMessage(data, message_type=None):
    """Send a message via BLE (Millennium, Nordic, or Chessnut) or BT classic.
    
    Args:
        data: Message data bytes (already formatted with messageType, length, payload)
        message_type: Optional message type hint for Chessnut ('fen' or 'op_rx')
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
    
    # Send via Chessnut BLE if connected
    # Chessnut uses two notification characteristics: FEN (0x01 header) and OP RX (0x2a battery)
    if ble_client_type == 'chessnut':
        try:
            # Route based on first byte (response type)
            if len(tosend) > 0 and tosend[0] == 0x01:
                # FEN notification goes to FEN characteristic
                if ChessnutFENCharacteristic.fen_instance is not None and ChessnutFENCharacteristic.fen_instance.notifying:
                    log.info(f"[sendMessage] Sending {len(tosend)} bytes via Chessnut FEN")
                    ChessnutFENCharacteristic.fen_instance.send_notification(tosend)
            else:
                # Other responses (battery, etc.) go to OP RX characteristic
                if ChessnutOperationRXCharacteristic.op_rx_instance is not None and ChessnutOperationRXCharacteristic.op_rx_instance.notifying:
                    log.info(f"[sendMessage] Sending {len(tosend)} bytes via Chessnut OP RX")
                    ChessnutOperationRXCharacteristic.op_rx_instance.send_notification(tosend)
        except Exception as e:
            log.error(f"[sendMessage] Error sending via Chessnut BLE: {e}")
    
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
    
    # First, try to find in known devices using BluetoothController
    controller = BluetoothController()
    addr = controller.find_device_by_name(shadow_target)
    if addr:
        return addr
    
    # If not found in known devices, do a discovery scan
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
    global _last_message, shadow_target, game_handler
    
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
                    
                    if game_handler is not None and game_handler.compare_mode:
                        match, emulator_response = game_handler.compare_with_shadow(bytes(data_bytes))
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
    global running, shadow_target_sock, client_sock, shadow_target_connected, client_connected, game_handler
    
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
                    game_handler.on_app_disconnected()
                    break
                
                data_bytes = bytearray(data)
                log.info(f"Client -> SHADOW TARGET: {' '.join(f'{b:02x}' for b in data_bytes)}")
                
                for byte_val in data_bytes:
                    game_handler.receive_data(byte_val)
                
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
    global running, client_sock, client_connected, game_handler
    
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
                    game_handler.on_app_disconnected()
                    break
                
                data_bytes = bytearray(data)
                log.info(f"Client -> Server: {' '.join(f'{b:02x}' for b in data_bytes)}")
                
                for byte_val in data_bytes:
                    game_handler.receive_data(byte_val)
                    
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
    global game_handler
    
    try:
        log.info("Cleaning up...")
        kill = 1
        running = False
        
        # Clean up game handler and UCI engine
        if game_handler is not None:
            game_handler.cleanup()
        
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
    global relay_mode, shadow_target, game_handler
    
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
    parser.add_argument("--standalone-engine", type=str, default="stockfish_pi",
                       help="UCI engine for standalone play when no app connected (e.g., stockfish_pi, maia, ct800)")
    parser.add_argument("--engine-elo", type=str, default="Default",
                       help="ELO level from engine's .uci file (e.g., 1350, 1700, 2000, Default)")
    parser.add_argument("--player-color", type=str, default="white", choices=["white", "black", "random"],
                       help="Which color the human plays in standalone engine mode")
    
    args = parser.parse_args()
    
    global chess_board_widget
    
    # Initialize display and show splash screen
    log.info("Initializing display...")
    promise = board.init_display()
    if promise:
        try:
            promise.result(timeout=10.0)
        except Exception as e:
            log.warning(f"Error initializing display: {e}")
    
    # Show loading splash screen
    splash = SplashScreen(message="Universal Relay")
    future = board.display_manager.add_widget(splash)
    if future:
        try:
            future.result(timeout=5.0)
        except Exception as e:
            log.warning(f"Error displaying splash screen: {e}")
    
    log.info("=" * 60)
    log.info("Universal Relay Starting")
    log.info("=" * 60)
    log.info("")
    log.info("Configuration:")
    log.info(f"  Device name:       {args.device_name}")
    log.info(f"  BLE:               {'Disabled' if args.no_ble else 'Enabled'}")
    log.info(f"  RFCOMM:            {'Disabled' if args.no_rfcomm else 'Enabled'}")
    log.info(f"  Relay mode:        {'Enabled' if args.relay else 'Disabled'}")
    if args.relay:
        log.info(f"  Shadow target:     {args.shadow_target}")
    log.info("")
    log.info("Standalone Engine:")
    log.info(f"  Engine:            {args.standalone_engine}")
    log.info(f"  ELO:               {args.engine_elo}")
    log.info(f"  Player color:      {args.player_color}")
    log.info("")
    log.info("=" * 60)
    
    relay_mode = args.relay
    shadow_target = args.shadow_target
    
    # Determine player color for standalone engine
    if args.player_color == "random":
        fallback_player_color = chess.WHITE if random.randint(0, 1) == 0 else chess.BLACK
    else:
        fallback_player_color = chess.WHITE if args.player_color == "white" else chess.BLACK
    
    # Create GameHandler at startup (with standalone engine if configured)
    # This allows standalone play against engine when no app is connected
    game_handler = GameHandler(
        sendMessage_callback=sendMessage,
        client_type=None,
        compare_mode=relay_mode,
        standalone_engine_name=args.standalone_engine,
        player_color=fallback_player_color,
        engine_elo=args.engine_elo
    )
    log.info(f"[GameHandler] Created with standalone engine: {args.standalone_engine} @ {args.engine_elo}")
    
    # Initialize chess board widget for e-paper display
    # Clear splash and show chess board
    board.display_manager.clear_widgets()
    
    # Create chess board widget at y=16 (below status bar)
    # Start with initial position
    STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    chess_board_widget = ChessBoardWidget(0, 16, STARTING_FEN)
    future = board.display_manager.add_widget(chess_board_widget)
    if future:
        try:
            future.result(timeout=5.0)
        except Exception as e:
            log.warning(f"Error displaying chess board widget: {e}")
    log.info("Chess board widget initialized")
    
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
        
        # Add services for all supported protocols
        # Service indices: 0=DeviceInfo, 1=Millennium, 2=Nordic, 3-6=Chessnut
        ble_app.add_service(DeviceInfoService(bus, 0))
        ble_app.add_service(MillenniumService(bus, 1))
        ble_app.add_service(NordicUARTService(bus, 2))  # For Pegasus clients
        
        # Add all 4 Chessnut services
        ble_app.add_service(ChessnutFENService(bus, 3))
        ble_app.add_service(ChessnutOperationService(bus, 4))
        ble_app.add_service(ChessnutUnknownService(bus, 5))
        ble_app.add_service(ChessnutOTAService(bus, 6))
        
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
        
        # Create and register advertisement
        # Uses ManufacturerData for Chessnut (company ID 0x4450)
        # Nordic/Millennium apps discover by LocalName
        
        ad_manager = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, adapter),
            LE_ADVERTISING_MANAGER_IFACE)
        
        # Register TWO advertisements:
        # 1. Nordic UUID advertisement (for Pegasus app) - LocalName "DGT PEGASUS"
        # 2. Chessnut ManufacturerData advertisement (for Chessnut app) - LocalName "Chessnut Air"
        # 3. Millennium advertisement (for Millennium app) - LocalName "MILLENNIUM CHESS"
        #
        # BlueZ supports multiple advertisements on adapters that support it.
        
        adv1_registered = [False]
        adv2_registered = [False]
        adv3_registered = [False]
        adv_error = [None]
        
        # Advertisement 1: Nordic UUID for Pegasus
        adv1 = Advertisement(
            bus, 0, "DGT PEGASUS",
            service_uuids=[NORDIC_UUIDS["service"]]
        )
        
        def adv1_register_success():
            log.info("Advertisement 1 registered (LocalName 'DGT PEGASUS' + Nordic UUID)")
            adv1_registered[0] = True
        
        def adv1_register_error(error):
            log.error(f"Failed to register advertisement 1: {error}")
            adv_error[0] = str(error)
        
        # Advertisement 2: ManufacturerData for Chessnut
        adv2 = Advertisement(
            bus, 1, "Chessnut Air",
            manufacturer_data={CHESSNUT_MANUFACTURER_ID: CHESSNUT_MANUFACTURER_DATA}
        )
        
        def adv2_register_success():
            log.info("Advertisement 2 registered (LocalName 'Chessnut Air' + ManufacturerData)")
            adv2_registered[0] = True
        
        def adv2_register_error(error):
            log.error(f"Failed to register advertisement 2: {error}")
            adv_error[0] = str(error)
        
        # Advertisement 3: Millennium (LocalName only, no UUID or ManufacturerData)
        adv3 = Advertisement(
            bus, 2, "MILLENNIUM CHESS"
        )
        
        def adv3_register_success():
            log.info("Advertisement 3 registered (LocalName 'MILLENNIUM CHESS')")
            adv3_registered[0] = True
        
        def adv3_register_error(error):
            log.error(f"Failed to register advertisement 3: {error}")
            adv_error[0] = str(error)
        
        log.info(f"Registering advertisements...")
        log.info(f"  Adv 1: LocalName 'DGT PEGASUS' + Nordic UUID (for Pegasus)")
        log.info(f"  Adv 2: LocalName 'Chessnut Air' + ManufacturerData 0x{CHESSNUT_MANUFACTURER_ID:04x} (for Chessnut)")
        log.info(f"  Adv 3: LocalName 'MILLENNIUM CHESS' (for Millennium)")
        
        ad_manager.RegisterAdvertisement(
            adv1.get_path(), {},
            reply_handler=adv1_register_success,
            error_handler=adv1_register_error)
        
        ad_manager.RegisterAdvertisement(
            adv2.get_path(), {},
            reply_handler=adv2_register_success,
            error_handler=adv2_register_error)
        
        ad_manager.RegisterAdvertisement(
            adv3.get_path(), {},
            reply_handler=adv3_register_success,
            error_handler=adv3_register_error)
        
        # Give D-Bus time to process registrations
        time.sleep(1)
        
        # Pump the GLib mainloop to process D-Bus callbacks
        # The mainloop isn't running yet, so we need to iterate manually
        context = mainloop.get_context()
        start_time = time.time()
        timeout = 5.0  # 5 second timeout
        
        while time.time() - start_time < timeout:
            # Process pending events
            while context.pending():
                context.iteration(False)
            
            # Check if all registered or if there's an error
            if adv_error[0] is not None:
                break
            if adv1_registered[0] and adv2_registered[0] and adv3_registered[0]:
                break
            
            time.sleep(0.1)
        
        # Check if any advertisement registration failed
        if adv_error[0] is not None:
            log.error("Cannot continue without proper advertisements.")
            log.error("All three apps (Chessnut, Pegasus, Millennium) require specific advertisement data.")
            sys.exit(1)
        
        if not adv1_registered[0] or not adv2_registered[0] or not adv3_registered[0]:
            log.error("Advertisement registration did not complete in time.")
            log.error(f"  Adv 1 (Pegasus): {'OK' if adv1_registered[0] else 'FAILED'}")
            log.error(f"  Adv 2 (Chessnut): {'OK' if adv2_registered[0] else 'FAILED'}")
            log.error(f"  Adv 3 (Millennium): {'OK' if adv3_registered[0] else 'FAILED'}")
            sys.exit(1)
        
        log.info("All three advertisements registered successfully")
    
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
                
                # Notify GameHandler that an app connected
                game_handler.on_app_connected()
                log.info("[GameHandler] RFCOMM app connected")
                
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
