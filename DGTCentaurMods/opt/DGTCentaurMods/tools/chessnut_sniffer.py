#!/usr/bin/env python3
"""
Chessnut Sniffer - Chessnut Air BLE emulator

Emulates a real Chessnut Air chess board for testing and development.
Uses BLE (Bluetooth Low Energy) only - Chessnut Air does not support RFCOMM.

BLE Service structure:
- Custom Chessnut Service with three characteristics:
  - FEN RX (1b7e8262): Notify - sends FEN/board state to client
  - Operation TX (1b7e8272): Write - receives commands from client
  - Operation RX (1b7e8273): Notify - sends command responses to client

Protocol:
- Commands are 3+ bytes: [command, length, payload...]
- FEN notification: 36 bytes [0x01, 0x24, 32_bytes_position, 0x00, 0x00]
- Battery response: 4 bytes [0x2a, 0x02, battery_level, 0x00]

Based on official Chessnut eBoards API:
https://github.com/chessnutech/Chessnut_eBoards
"""

import argparse
import sys
import signal
import time
import subprocess
import os
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

# Chessnut Air Service UUIDs
# Real board has TWO services:
# - FEN Service (1b7e8261) contains FEN RX characteristic
# - Operation Service (1b7e8271) contains OP TX and OP RX characteristics
CHESSNUT_FEN_SERVICE_UUID = "1b7e8261-2877-41c3-b46e-cf057c562023"
CHESSNUT_OP_SERVICE_UUID = "1b7e8271-2877-41c3-b46e-cf057c562023"
CHESSNUT_FEN_RX_UUID = "1b7e8262-2877-41c3-b46e-cf057c562023"   # Notify - FEN data
CHESSNUT_OP_TX_UUID = "1b7e8272-2877-41c3-b46e-cf057c562023"   # Write - commands
CHESSNUT_OP_RX_UUID = "1b7e8273-2877-41c3-b46e-cf057c562023"   # Notify - responses

# Chessnut command bytes
CMD_ENABLE_REPORTING = 0x21
CMD_BATTERY_REQUEST = 0x29
CMD_LED_CONTROL = 0x0a

# Chessnut response bytes
RESP_FEN_DATA = 0x01
RESP_BATTERY = 0x2a

# Global state
mainloop = None
device_name = "Chessnut Air"


def log(msg):
    """Simple timestamped logging."""
    timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"
    print(f"[{timestamp}] {msg}", flush=True)


def find_adapter(bus):
    """Find the first Bluetooth adapter."""
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'),
                               DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()
    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props:
            return o
    return None


class Application(dbus.service.Object):
    """GATT Application - container for GATT services."""
    
    def __init__(self, bus):
        self.path = '/org/bluez/chessnut'
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
    """GATT Service base class."""
    
    PATH_BASE = '/org/bluez/chessnut/service'

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
        return [c.get_path() for c in self.characteristics]

    def get_characteristics(self):
        return self.characteristics


class Characteristic(dbus.service.Object):
    """GATT Characteristic base class."""

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

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return []

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        pass

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        self.notifying = False

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def send_notification(self, value):
        """Send a notification with the given value."""
        if not self.notifying:
            return
        self.PropertiesChanged(
            GATT_CHRC_IFACE,
            {'Value': dbus.Array(value, signature='y')},
            []
        )


class FENCharacteristic(Characteristic):
    """FEN RX Characteristic (1b7e8262) - Notify FEN/board state to client.
    
    Sends 36-byte FEN notifications:
    - Bytes 0-1: Header [0x01, 0x24]
    - Bytes 2-33: Position data (32 bytes, 2 squares per byte)
    - Bytes 34-35: Reserved [0x00, 0x00]
    
    Square order: h8 -> g8 -> ... -> a8 -> h7 -> ... -> a1
    Each byte: lower nibble = first square, upper nibble = second square
    
    Piece encoding:
        0 = empty
        1 = black queen (q)
        2 = black king (k)
        3 = black bishop (b)
        4 = black pawn (p)
        5 = black knight (n)
        6 = white rook (R)
        7 = white pawn (P)
        8 = black rook (r)
        9 = white bishop (B)
        10 = white knight (N)
        11 = white queen (Q)
        12 = white king (K)
    """
    
    # Class variable to hold instance for cross-characteristic access
    fen_instance = None
    
    def __init__(self, bus, index, service):
        # Notify only - matches real Chessnut Air
        Characteristic.__init__(self, bus, index, CHESSNUT_FEN_RX_UUID,
                                ['notify'], service)
        FENCharacteristic.fen_instance = self
        self._reporting_enabled = False

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        log("FEN notifications enabled")
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        log("FEN notifications disabled")
        self.notifying = False
        self._reporting_enabled = False

    def enable_reporting(self):
        """Enable reporting and send initial FEN."""
        self._reporting_enabled = True
        self.send_fen_notification()

    def send_fen_notification(self):
        """Send FEN notification with current board state.
        
        Real Chessnut Air sends 38 bytes:
        - Bytes 0-1: Header [0x01, 0x24]
        - Bytes 2-33: Position data (32 bytes)
        - Bytes 34-37: Extra data [0x44, 0x01, 0x00, 0x00] (status/checksum?)
        """
        if not self.notifying:
            log("Cannot send FEN - notifications not enabled")
            return
        
        # Build starting position FEN bytes
        position_bytes = self._get_starting_position_bytes()
        
        # Build 38-byte notification (matches real Chessnut Air)
        notification = bytearray([RESP_FEN_DATA, 0x24])  # Header
        notification.extend(position_bytes)  # 32 bytes position
        notification.extend([0x44, 0x01, 0x00, 0x00])  # Extra bytes from real board
        
        hex_str = ' '.join(f'{b:02x}' for b in notification)
        log(f"TX [FEN] ({len(notification)} bytes): {hex_str}")
        log("  -> Starting position: rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")
        
        self.send_notification(notification)

    def _get_starting_position_bytes(self):
        """Get 32-byte position data for starting position.
        
        Returns:
            32 bytes representing starting chess position
        """
        # Piece codes for Chessnut format
        EMPTY = 0
        # Black pieces
        B_QUEEN = 1
        B_KING = 2
        B_BISHOP = 3
        B_PAWN = 4
        B_KNIGHT = 5
        B_ROOK = 8
        # White pieces
        W_ROOK = 6
        W_PAWN = 7
        W_BISHOP = 9
        W_KNIGHT = 10
        W_QUEEN = 11
        W_KING = 12
        
        # Board as 8x8 array (rank 8 first, file a first)
        # Starting position
        board = [
            # Rank 8: black pieces (a8 to h8)
            [B_ROOK, B_KNIGHT, B_BISHOP, B_QUEEN, B_KING, B_BISHOP, B_KNIGHT, B_ROOK],
            # Rank 7: black pawns
            [B_PAWN, B_PAWN, B_PAWN, B_PAWN, B_PAWN, B_PAWN, B_PAWN, B_PAWN],
            # Ranks 6-3: empty
            [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
            [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
            [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
            [EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
            # Rank 2: white pawns
            [W_PAWN, W_PAWN, W_PAWN, W_PAWN, W_PAWN, W_PAWN, W_PAWN, W_PAWN],
            # Rank 1: white pieces (a1 to h1)
            [W_ROOK, W_KNIGHT, W_BISHOP, W_QUEEN, W_KING, W_BISHOP, W_KNIGHT, W_ROOK],
        ]
        
        # Convert to 32-byte Chessnut format
        # Square order: h8 -> g8 -> f8 -> ... -> a8 -> h7 -> ... -> a1
        # Each byte: lower nibble = first square (even col), upper nibble = second square (odd col)
        result = bytearray(32)
        
        for row in range(8):  # rank 8 to rank 1
            for col in range(7, -1, -1):  # file h to a (7 to 0)
                piece = board[row][col]
                byte_idx = (row * 8 + (7 - col)) // 2
                
                if (7 - col) % 2 == 0:
                    # Lower nibble (even position in output)
                    result[byte_idx] = (result[byte_idx] & 0xF0) | (piece & 0x0F)
                else:
                    # Upper nibble (odd position in output)
                    result[byte_idx] = (result[byte_idx] & 0x0F) | ((piece & 0x0F) << 4)
        
        return bytes(result)


class OperationTXCharacteristic(Characteristic):
    """Operation TX Characteristic (1b7e8272) - Write commands from client.
    
    Receives commands from the client:
    - 0x21: Enable reporting
    - 0x29: Battery request
    - 0x0a: LED control
    
    Command format: [command, length, payload...]
    """
    
    def __init__(self, bus, index, service, fen_char, op_rx_char):
        # Write and write-without-response - matches real Chessnut Air
        Characteristic.__init__(self, bus, index, CHESSNUT_OP_TX_UUID,
                                ['write', 'write-without-response'], service)
        self.fen_char = fen_char
        self.op_rx_char = op_rx_char

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        """Handle write from client."""
        try:
            bytes_data = bytearray([int(b) for b in value])
            hex_str = ' '.join(f'{b:02x}' for b in bytes_data)
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in bytes_data)
            
            log(f"RX [OP TX] ({len(bytes_data)} bytes): {hex_str}")
            log(f"  ASCII: {ascii_str}")
            
            self._handle_command(bytes_data)
        except Exception as e:
            log(f"Error handling write: {e}")
            import traceback
            traceback.print_exc()

    def _handle_command(self, data):
        """Handle a Chessnut command.
        
        Args:
            data: Command bytes [command, length, payload...]
        """
        if len(data) < 2:
            log("  -> Invalid command (too short)")
            return
        
        cmd = data[0]
        length = data[1]
        payload = data[2:2+length] if len(data) > 2 else []
        
        if cmd == CMD_ENABLE_REPORTING:
            log("  -> Enable reporting command")
            if self.fen_char:
                self.fen_char.enable_reporting()
        
        elif cmd == CMD_BATTERY_REQUEST:
            log("  -> Battery request command")
            if self.op_rx_char:
                self.op_rx_char.send_battery_response()
        
        elif cmd == CMD_LED_CONTROL:
            log(f"  -> LED control command: {' '.join(f'{b:02x}' for b in payload)}")
            # LED control is acknowledged but not implemented in sniffer
        
        else:
            log(f"  -> Unknown command 0x{cmd:02x}")


class OperationRXCharacteristic(Characteristic):
    """Operation RX Characteristic (1b7e8273) - Notify responses to client.
    
    Sends command responses:
    - Battery response: [0x2a, 0x02, battery_level, 0x00]
    """
    
    # Class variable to hold instance for cross-characteristic access
    op_rx_instance = None
    
    def __init__(self, bus, index, service):
        # Notify only - matches real Chessnut Air
        Characteristic.__init__(self, bus, index, CHESSNUT_OP_RX_UUID,
                                ['notify'], service)
        OperationRXCharacteristic.op_rx_instance = self
        self._battery_level = 85  # Simulated battery level

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        log("Operation RX notifications enabled")
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        log("Operation RX notifications disabled")
        self.notifying = False

    def send_battery_response(self):
        """Send battery level response."""
        if not self.notifying:
            log("Cannot send battery - notifications not enabled")
            return
        
        # Battery response format: [0x2a, 0x02, battery_level, 0x00]
        # battery_level bit 7 = charging flag, bits 0-6 = percentage
        battery_byte = self._battery_level & 0x7F
        # Not charging
        
        response = bytes([RESP_BATTERY, 0x02, battery_byte, 0x00])
        
        hex_str = ' '.join(f'{b:02x}' for b in response)
        log(f"TX [OP RX] ({len(response)} bytes): {hex_str}")
        log(f"  -> Battery: {self._battery_level}% (not charging)")
        
        self.send_notification(response)


class ChessnutFENService(Service):
    """Chessnut Air FEN GATT Service (1b7e8261).
    
    Contains one characteristic:
    - FEN RX (1b7e8262): Notify - FEN/board state
    """
    
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, CHESSNUT_FEN_SERVICE_UUID, True)
        
        # Add FEN characteristic (notify)
        self.fen_char = FENCharacteristic(bus, 0, self)
        self.add_characteristic(self.fen_char)


class ChessnutOperationService(Service):
    """Chessnut Air Operation GATT Service (1b7e8271).
    
    Contains two characteristics:
    - Operation TX (1b7e8272): Write - commands from client
    - Operation RX (1b7e8273): Notify - responses to client
    """
    
    def __init__(self, bus, index, fen_char):
        Service.__init__(self, bus, index, CHESSNUT_OP_SERVICE_UUID, True)
        
        # Add Operation RX characteristic (notify) - must be created before TX
        self.op_rx_char = OperationRXCharacteristic(bus, 1, self)
        self.add_characteristic(self.op_rx_char)
        
        # Add Operation TX characteristic (write) - receives commands
        self.op_tx_char = OperationTXCharacteristic(bus, 0, self, 
                                                     fen_char, self.op_rx_char)
        self.add_characteristic(self.op_tx_char)


class Advertisement(dbus.service.Object):
    """BLE Advertisement for Chessnut Air.
    
    Real Chessnut Air uses manufacturer data (company ID 17488 = 0x4450)
    instead of service UUIDs in the advertisement. This avoids the 31-byte
    packet limit issue with multiple 128-bit UUIDs. Services are discovered
    after connection.
    
    Manufacturer data from real board: 4353b953056400003e9751101b00
    """
    
    PATH_BASE = '/org/bluez/chessnut/advertisement'
    
    # Chessnut company ID (17488 = 0x4450, little-endian)
    CHESSNUT_COMPANY_ID = 0x4450

    def __init__(self, bus, index, name):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.name = name
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        # Manufacturer data from real Chessnut Air
        # 4353b953056400003e9751101b00
        manufacturer_data = bytes.fromhex('4353b953056400003e9751101b00')
        
        properties = {
            'Type': 'peripheral',
            'LocalName': dbus.String(self.name),
            'Discoverable': dbus.Boolean(True),
            'Includes': dbus.Array(['tx-power'], signature='s'),
            # Use manufacturer data like the real Chessnut Air
            'ManufacturerData': dbus.Dictionary({
                dbus.UInt16(self.CHESSNUT_COMPANY_ID): dbus.Array(
                    [dbus.Byte(b) for b in manufacturer_data], signature='y'
                )
            }, signature='qv'),
        }
        return {LE_ADVERTISEMENT_IFACE: properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException(
                'org.freedesktop.DBus.Error.InvalidArgs',
                'Unknown interface: ' + interface)
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        log("Advertisement released")


class NoInputNoOutputAgent(dbus.service.Object):
    """Bluetooth agent that doesn't require any user input.
    
    This allows BLE connections without pairing prompts.
    """
    
    AGENT_PATH = "/org/bluez/chessnut/agent"

    def __init__(self, bus):
        dbus.service.Object.__init__(self, bus, self.AGENT_PATH)

    @dbus.service.method(AGENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        log("Agent released")

    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        log(f"AuthorizeService: {device} -> {uuid}")

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='s')
    def RequestPinCode(self, device):
        log(f"RequestPinCode: {device}")
        return ""

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        log(f"RequestPasskey: {device}")
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_IFACE, in_signature='ouq', out_signature='')
    def DisplayPasskey(self, device, passkey, entered):
        log(f"DisplayPasskey: {device} passkey={passkey}")

    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def DisplayPinCode(self, device, pincode):
        log(f"DisplayPinCode: {device} pin={pincode}")

    @dbus.service.method(AGENT_IFACE, in_signature='ou', out_signature='')
    def RequestConfirmation(self, device, passkey):
        log(f"RequestConfirmation: {device} passkey={passkey}")

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        log(f"RequestAuthorization: {device}")

    @dbus.service.method(AGENT_IFACE, in_signature='', out_signature='')
    def Cancel(self):
        log("Agent cancelled")


def register_agent(bus):
    """Register NoInputNoOutput agent to avoid pairing prompts."""
    try:
        agent_manager = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, '/org/bluez'),
            AGENT_MANAGER_IFACE
        )
        agent = NoInputNoOutputAgent(bus)
        agent_manager.RegisterAgent(NoInputNoOutputAgent.AGENT_PATH, "NoInputNoOutput")
        agent_manager.RequestDefaultAgent(NoInputNoOutputAgent.AGENT_PATH)
        log("Agent registered")
        return agent
    except Exception as e:
        log(f"Warning: Could not register agent: {e}")
        return None


def setup_adapter(bus, adapter_path, name):
    """Configure the Bluetooth adapter."""
    try:
        adapter_props = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, adapter_path),
            DBUS_PROP_IFACE
        )
        
        # Set adapter properties
        adapter_props.Set("org.bluez.Adapter1", "Alias", dbus.String(name))
        adapter_props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
        adapter_props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(True))
        adapter_props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
        
        log(f"Adapter configured: {name}")
    except Exception as e:
        log(f"Warning: Could not configure adapter: {e}")


def main():
    global mainloop, device_name
    
    parser = argparse.ArgumentParser(description='Chessnut Air BLE Emulator')
    parser.add_argument("--name", default=None, 
                        help="Bluetooth device name (default: Chessnut Air)")
    args = parser.parse_args()
    
    device_name = args.name if args.name else "Chessnut Air"
    
    log("=" * 60)
    log("Chessnut Air Sniffer/Emulator")
    log("=" * 60)
    log(f"Device name: {device_name}")
    log("")
    
    # Set up D-Bus main loop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    
    # Find adapter
    adapter_path = find_adapter(bus)
    if not adapter_path:
        log("ERROR: No Bluetooth adapter found")
        sys.exit(1)
    log(f"Using adapter: {adapter_path}")
    
    # Configure adapter
    setup_adapter(bus, adapter_path, device_name)
    
    # Register agent
    agent = register_agent(bus)
    
    # Create application
    app = Application(bus)
    
    # Add Chessnut FEN service (index 0)
    fen_service = ChessnutFENService(bus, 0)
    app.add_service(fen_service)
    
    # Add Chessnut Operation service (index 1) - needs reference to FEN char
    op_service = ChessnutOperationService(bus, 1, fen_service.fen_char)
    app.add_service(op_service)
    
    # Register GATT application
    gatt_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter_path),
        GATT_MANAGER_IFACE
    )
    
    def register_app_cb():
        log("GATT application registered")
    
    def register_app_error_cb(error):
        log(f"Failed to register GATT application: {error}")
        mainloop.quit()
    
    gatt_manager.RegisterApplication(
        app.get_path(), {},
        reply_handler=register_app_cb,
        error_handler=register_app_error_cb
    )
    
    # Register advertisement
    ad_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter_path),
        LE_ADVERTISING_MANAGER_IFACE
    )
    
    adv = Advertisement(bus, 0, device_name)
    
    def register_ad_cb():
        log("Advertisement registered")
        log("")
        log("=" * 60)
        log("SNIFFER READY")
        log("=" * 60)
        log(f"Device name: {device_name}")
        log(f"Manufacturer ID: 0x4450 (Chessnut)")
        log(f"FEN Service: {CHESSNUT_FEN_SERVICE_UUID}")
        log(f"OP Service: {CHESSNUT_OP_SERVICE_UUID}")
        log("Connect with the Chessnut app or any BLE client")
        log("Press Ctrl+C to stop")
        log("=" * 60)
        log("")
    
    def register_ad_error_cb(error):
        log(f"Failed to register advertisement: {error}")
        mainloop.quit()
    
    ad_manager.RegisterAdvertisement(
        adv.get_path(), {},
        reply_handler=register_ad_cb,
        error_handler=register_ad_error_cb
    )
    
    # Set up signal handlers
    def signal_handler(sig, frame):
        log("Shutting down...")
        mainloop.quit()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run main loop
    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except Exception as e:
        log(f"Error in main loop: {e}")
    
    log("Sniffer stopped")


if __name__ == "__main__":
    main()
