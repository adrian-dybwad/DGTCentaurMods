#!/usr/bin/env python3
"""
BLE Client Analysis Tool for Chessnut Air Devices

This tool scans for and analyzes Chessnut Air BLE devices.
It performs deep analysis including:
- Advertisement data comparison
- Service and characteristic enumeration
- Connection testing as a Chessnut client
- Protocol communication testing

Based on official Chessnut eBoards API:
https://github.com/chessnutech/Chessnut_eBoards

Usage:
    python3 tools/chessnut_ble_client_analysis.py
    python3 tools/chessnut_ble_client_analysis.py --scan-time 15
    python3 tools/chessnut_ble_client_analysis.py --connect-timeout 20
    python3 tools/chessnut_ble_client_analysis.py --list-all
    python3 tools/chessnut_ble_client_analysis.py --name "Chessnut"
    python3 tools/chessnut_ble_client_analysis.py --address AA:BB:CC:DD:EE:FF

Requirements:
    pip install bleak
"""

import asyncio
import argparse
import sys
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
except ImportError:
    print("Error: bleak library not installed.")
    print("Install with: pip install bleak")
    sys.exit(1)


# Chessnut Air Service UUIDs
# Real board has TWO services, not one:
# - FEN Service (1b7e8261) contains FEN RX characteristic
# - Operation Service (1b7e8271) contains OP TX and OP RX characteristics
CHESSNUT_FEN_SERVICE_UUID = "1b7e8261-2877-41c3-b46e-cf057c562023"
CHESSNUT_OP_SERVICE_UUID = "1b7e8271-2877-41c3-b46e-cf057c562023"
CHESSNUT_FEN_RX_UUID = "1b7e8262-2877-41c3-b46e-cf057c562023"   # Notify - FEN data
CHESSNUT_OP_TX_UUID = "1b7e8272-2877-41c3-b46e-cf057c562023"   # Write - commands
CHESSNUT_OP_RX_UUID = "1b7e8273-2877-41c3-b46e-cf057c562023"   # Notify - responses

# Target device name
CHESSNUT_DEVICE_NAME = "Chessnut"

# Chessnut Air Commands (from sniffer capture and EasyLinkSDK)
CMD_INIT = bytes([0x0b, 0x04, 0x03, 0xe8, 0x00, 0xc8])  # Init/config
CMD_ENABLE_REPORTING = bytes([0x21, 0x01, 0x00])  # Enable reporting
CMD_HAPTIC_ON = bytes([0x27, 0x01, 0x01])         # Haptic on
CMD_HAPTIC_OFF = bytes([0x27, 0x01, 0x00])        # Haptic off
CMD_BATTERY_REQUEST = bytes([0x29, 0x01, 0x00])   # Battery request
CMD_SOUND = bytes([0x31, 0x01, 0x00])             # Sound control

# Commands to probe for version/file info (need to discover correct format)
# Based on EasyLinkSDK: cl_get_mcu_version, cl_get_ble_version, cl_get_file_count
CMD_MCU_VERSION = bytes([0x38, 0x01, 0x00])       # Probe: MCU version request
CMD_BLE_VERSION = bytes([0x39, 0x01, 0x00])       # Probe: BLE version request  
CMD_FILE_COUNT = bytes([0x3a, 0x01, 0x00])        # Probe: File count request
CMD_FILE_MODE = bytes([0x3b, 0x01, 0x00])         # Probe: Switch to file mode

# Alternative probes - try different command IDs
# 0x39 responded with 0x23 0x01 0x01 - possibly a mode/status confirmation
PROBE_COMMANDS = [
    # Lower range - possibly version/info commands
    (bytes([0x22, 0x01, 0x00]), "0x22 (after enable reporting 0x21)"),
    (bytes([0x23, 0x01, 0x00]), "0x23 (response type we saw)"),
    (bytes([0x24, 0x01, 0x00]), "0x24"),
    (bytes([0x25, 0x01, 0x00]), "0x25"),
    (bytes([0x26, 0x01, 0x00]), "0x26"),
    (bytes([0x28, 0x01, 0x00]), "0x28 (before battery 0x29)"),
    (bytes([0x2b, 0x01, 0x00]), "0x2b (after battery resp 0x2a)"),
    (bytes([0x2c, 0x01, 0x00]), "0x2c"),
    (bytes([0x2d, 0x01, 0x00]), "0x2d"),
    (bytes([0x2e, 0x01, 0x00]), "0x2e"),
    (bytes([0x2f, 0x01, 0x00]), "0x2f"),
    (bytes([0x30, 0x01, 0x00]), "0x30 (before sound 0x31)"),
    (bytes([0x32, 0x01, 0x00]), "0x32 (after sound 0x31)"),
    (bytes([0x33, 0x01, 0x00]), "0x33"),
    (bytes([0x34, 0x01, 0x00]), "0x34"),
    (bytes([0x35, 0x01, 0x00]), "0x35"),
    (bytes([0x36, 0x01, 0x00]), "0x36"),
    (bytes([0x37, 0x01, 0x00]), "0x37"),
    # Higher range
    (bytes([0x50, 0x01, 0x00]), "0x50"),
    (bytes([0x51, 0x01, 0x00]), "0x51"),
    (bytes([0x52, 0x01, 0x00]), "0x52"),
    (bytes([0x60, 0x01, 0x00]), "0x60"),
    (bytes([0x61, 0x01, 0x00]), "0x61"),
    (bytes([0x70, 0x01, 0x00]), "0x70"),
    (bytes([0x71, 0x01, 0x00]), "0x71"),
    (bytes([0x80, 0x01, 0x00]), "0x80"),
    (bytes([0x81, 0x01, 0x00]), "0x81"),
]

# Chessnut Air Response Types
RESP_FEN_DATA = 0x01    # FEN notification
RESP_BATTERY = 0x2a     # Battery response


@dataclass
class DeviceAnalysis:
    """Analysis results for a single BLE device."""
    
    address: str
    name: str
    rssi: int
    
    # Advertisement data
    local_name: Optional[str] = None
    manufacturer_data: dict = field(default_factory=dict)
    service_uuids: list = field(default_factory=list)
    service_data: dict = field(default_factory=dict)
    tx_power: Optional[int] = None
    
    # Connection results
    connected: bool = False
    connection_error: Optional[str] = None
    mtu_size: Optional[int] = None
    
    # Services discovered
    services: list = field(default_factory=list)
    has_fen_service: bool = False
    has_op_service: bool = False
    has_fen_characteristic: bool = False
    has_op_tx_characteristic: bool = False
    has_op_rx_characteristic: bool = False
    
    # Protocol responses
    fen_response: Optional[bytes] = None
    battery_response: Optional[bytes] = None
    protocol_errors: list = field(default_factory=list)
    
    # Timing
    scan_time: Optional[datetime] = None
    connect_time: Optional[float] = None
    
    def to_dict(self) -> dict:
        """Convert analysis to dictionary for comparison."""
        return {
            "address": self.address,
            "name": self.name,
            "rssi": self.rssi,
            "local_name": self.local_name,
            "manufacturer_data": {k: v.hex() if isinstance(v, bytes) else str(v) 
                                  for k, v in self.manufacturer_data.items()},
            "service_uuids": self.service_uuids,
            "service_data": {k: v.hex() if isinstance(v, bytes) else str(v) 
                            for k, v in self.service_data.items()},
            "tx_power": self.tx_power,
            "connected": self.connected,
            "connection_error": self.connection_error,
            "mtu_size": self.mtu_size,
            "services": self.services,
            "has_fen_service": self.has_fen_service,
            "has_op_service": self.has_op_service,
            "has_fen_characteristic": self.has_fen_characteristic,
            "has_op_tx_characteristic": self.has_op_tx_characteristic,
            "has_op_rx_characteristic": self.has_op_rx_characteristic,
            "fen_response": self.fen_response.hex() if self.fen_response else None,
            "battery_response": self.battery_response.hex() if self.battery_response else None,
            "protocol_errors": self.protocol_errors,
            "connect_time": self.connect_time,
        }


class ChessnutAnalyzer:
    """Analyzer for Chessnut Air BLE devices."""
    
    def __init__(self, scan_time: float = 10.0, connect_timeout: float = 15.0,
                 device_name_filter: str = CHESSNUT_DEVICE_NAME,
                 target_addresses: list[str] = None):
        """Initialize the analyzer.
        
        Args:
            scan_time: Time to scan for devices in seconds
            connect_timeout: Connection timeout in seconds
            device_name_filter: Filter devices by name (case-insensitive substring)
            target_addresses: List of specific addresses to connect to
        """
        self.scan_time = scan_time
        self.connect_timeout = connect_timeout
        self.device_name_filter = device_name_filter.lower() if device_name_filter else None
        self.target_addresses = [a.upper() for a in target_addresses] if target_addresses else None
        self.analyses: list[DeviceAnalysis] = []
        self._notification_data: dict[str, bytes] = {}
        self._notification_events: dict[str, asyncio.Event] = {}
    
    def _log(self, msg: str):
        """Log with timestamp."""
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] {msg}")
    
    def _matches_filter(self, device: BLEDevice, adv: AdvertisementData) -> bool:
        """Check if device matches our filter criteria."""
        if self.target_addresses:
            return device.address.upper() in self.target_addresses
        
        if self.device_name_filter:
            name = (device.name or "").lower()
            local_name = (adv.local_name or "").lower()
            return (self.device_name_filter in name or 
                    self.device_name_filter in local_name)
        
        return True
    
    async def scan(self) -> list[tuple[BLEDevice, AdvertisementData]]:
        """Scan for Chessnut Air devices.
        
        Returns:
            List of (device, advertisement_data) tuples
        """
        self._log(f"Scanning for BLE devices ({self.scan_time}s)...")
        
        devices = []
        
        def detection_callback(device: BLEDevice, adv: AdvertisementData):
            if self._matches_filter(device, adv):
                # Check if we already have this device
                for d, _ in devices:
                    if d.address == device.address:
                        return
                devices.append((device, adv))
                self._log(f"  Found: {device.name or 'Unknown'} ({device.address})")
        
        scanner = BleakScanner(detection_callback=detection_callback)
        await scanner.start()
        await asyncio.sleep(self.scan_time)
        await scanner.stop()
        
        self._log(f"Found {len(devices)} matching device(s)")
        return devices
    
    async def analyze_device(self, device: BLEDevice, adv: AdvertisementData) -> DeviceAnalysis:
        """Perform deep analysis on a single device.
        
        Args:
            device: BLE device
            adv: Advertisement data
            
        Returns:
            DeviceAnalysis with results
        """
        analysis = DeviceAnalysis(
            address=device.address,
            name=device.name or "Unknown",
            rssi=adv.rssi if hasattr(adv, 'rssi') else -100,
            local_name=adv.local_name,
            manufacturer_data=dict(adv.manufacturer_data) if adv.manufacturer_data else {},
            service_uuids=[str(u) for u in adv.service_uuids] if adv.service_uuids else [],
            service_data=dict(adv.service_data) if adv.service_data else {},
            tx_power=adv.tx_power,
            scan_time=datetime.now()
        )
        
        self._log(f"\n{'='*60}")
        self._log(f"Analyzing: {analysis.name} ({analysis.address})")
        self._log(f"{'='*60}")
        
        # Log advertisement info
        self._log(f"RSSI: {analysis.rssi} dBm")
        if analysis.local_name:
            self._log(f"Local Name: {analysis.local_name}")
        if analysis.tx_power:
            self._log(f"TX Power: {analysis.tx_power}")
        if analysis.service_uuids:
            self._log(f"Advertised Services: {analysis.service_uuids}")
        if analysis.manufacturer_data:
            for mid, data in analysis.manufacturer_data.items():
                self._log(f"Manufacturer Data [{mid}]: {data.hex()}")
        
        # Connect and discover services
        self._log("\nConnecting...")
        start_time = asyncio.get_event_loop().time()
        
        try:
            async with BleakClient(device, timeout=self.connect_timeout) as client:
                analysis.connected = True
                analysis.connect_time = asyncio.get_event_loop().time() - start_time
                self._log(f"Connected in {analysis.connect_time:.2f}s")
                
                # Get MTU if available
                if hasattr(client, 'mtu_size'):
                    analysis.mtu_size = client.mtu_size
                    self._log(f"MTU Size: {analysis.mtu_size}")
                
                # Enumerate services
                await self._enumerate_services(client, analysis)
                
                # If Chessnut services found, test protocol
                if analysis.has_fen_service and analysis.has_op_service:
                    await self._test_protocol(client, analysis)
                
        except asyncio.TimeoutError:
            analysis.connection_error = "Connection timeout"
            self._log(f"ERROR: {analysis.connection_error}")
        except Exception as e:
            analysis.connection_error = str(e)
            self._log(f"ERROR: {analysis.connection_error}")
        
        self.analyses.append(analysis)
        return analysis
    
    async def _enumerate_services(self, client: BleakClient, analysis: DeviceAnalysis):
        """Enumerate all services and characteristics."""
        self._log("\nServices:")
        
        for service in client.services:
            service_info = {
                "uuid": str(service.uuid),
                "characteristics": []
            }
            
            uuid_lower = str(service.uuid).lower()
            is_fen_service = uuid_lower == CHESSNUT_FEN_SERVICE_UUID.lower()
            is_op_service = uuid_lower == CHESSNUT_OP_SERVICE_UUID.lower()
            
            marker = ""
            if is_fen_service:
                marker = " <-- CHESSNUT FEN SERVICE"
                analysis.has_fen_service = True
            elif is_op_service:
                marker = " <-- CHESSNUT OPERATION SERVICE"
                analysis.has_op_service = True
            
            self._log(f"  Service: {service.uuid}{marker}")
            
            for char in service.characteristics:
                char_info = {
                    "uuid": str(char.uuid),
                    "properties": char.properties
                }
                service_info["characteristics"].append(char_info)
                
                char_uuid_lower = str(char.uuid).lower()
                
                # Check for Chessnut characteristics
                char_marker = ""
                if char_uuid_lower == CHESSNUT_FEN_RX_UUID.lower():
                    analysis.has_fen_characteristic = True
                    char_marker = " <-- FEN RX (notify)"
                elif char_uuid_lower == CHESSNUT_OP_TX_UUID.lower():
                    analysis.has_op_tx_characteristic = True
                    char_marker = " <-- OP TX (write)"
                elif char_uuid_lower == CHESSNUT_OP_RX_UUID.lower():
                    analysis.has_op_rx_characteristic = True
                    char_marker = " <-- OP RX (notify)"
                
                self._log(f"    Characteristic: {char.uuid}")
                self._log(f"      Properties: {char.properties}{char_marker}")
            
            analysis.services.append(service_info)
    
    async def _test_protocol(self, client: BleakClient, analysis: DeviceAnalysis):
        """Test Chessnut protocol commands."""
        self._log("\n" + "-"*40)
        self._log("Testing Chessnut Protocol")
        self._log("-"*40)
        
        # Set up notification handlers
        self._notification_events["fen"] = asyncio.Event()
        self._notification_events["op_rx"] = asyncio.Event()
        
        def fen_handler(sender, data: bytearray):
            self._notification_data["fen"] = bytes(data)
            self._notification_events["fen"].set()
        
        def op_rx_handler(sender, data: bytearray):
            self._notification_data["op_rx"] = bytes(data)
            self._notification_events["op_rx"].set()
        
        # Enable notifications
        try:
            if analysis.has_fen_characteristic:
                await client.start_notify(CHESSNUT_FEN_RX_UUID, fen_handler)
                self._log("Enabled FEN notifications")
            if analysis.has_op_rx_characteristic:
                await client.start_notify(CHESSNUT_OP_RX_UUID, op_rx_handler)
                self._log("Enabled OP RX notifications")
        except Exception as e:
            analysis.protocol_errors.append(f"Notification setup failed: {e}")
            self._log(f"ERROR enabling notifications: {e}")
            return
        
        await asyncio.sleep(0.5)
        
        # Send enable reporting command
        self._log("\nSending ENABLE_REPORTING command...")
        try:
            self._notification_events["fen"].clear()
            hex_cmd = ' '.join(f'{b:02x}' for b in CMD_ENABLE_REPORTING)
            self._log(f"  TX: {hex_cmd}")
            
            await client.write_gatt_char(CHESSNUT_OP_TX_UUID, CMD_ENABLE_REPORTING, response=False)
            
            # Wait for FEN response
            try:
                await asyncio.wait_for(self._notification_events["fen"].wait(), timeout=3.0)
                fen_data = self._notification_data.get("fen")
                if fen_data:
                    analysis.fen_response = fen_data
                    hex_str = ' '.join(f'{b:02x}' for b in fen_data)
                    self._log(f"  RX FEN ({len(fen_data)} bytes): {hex_str}")
                    self._parse_fen_response(fen_data)
            except asyncio.TimeoutError:
                analysis.protocol_errors.append("No FEN response to enable reporting")
                self._log("  No FEN response received")
        except Exception as e:
            analysis.protocol_errors.append(f"Enable reporting failed: {e}")
            self._log(f"  ERROR: {e}")
        
        await asyncio.sleep(0.3)
        
        # Send INIT command (like the app does)
        self._log("\nSending INIT command...")
        try:
            hex_cmd = ' '.join(f'{b:02x}' for b in CMD_INIT)
            self._log(f"  TX: {hex_cmd}")
            await client.write_gatt_char(CHESSNUT_OP_TX_UUID, CMD_INIT, response=False)
            await asyncio.sleep(0.2)
        except Exception as e:
            self._log(f"  ERROR: {e}")
        
        # Send battery request
        self._log("\nSending BATTERY_REQUEST command...")
        try:
            self._notification_events["op_rx"].clear()
            hex_cmd = ' '.join(f'{b:02x}' for b in CMD_BATTERY_REQUEST)
            self._log(f"  TX: {hex_cmd}")
            
            await client.write_gatt_char(CHESSNUT_OP_TX_UUID, CMD_BATTERY_REQUEST, response=False)
            
            # Wait for battery response
            try:
                await asyncio.wait_for(self._notification_events["op_rx"].wait(), timeout=3.0)
                battery_data = self._notification_data.get("op_rx")
                if battery_data:
                    analysis.battery_response = battery_data
                    hex_str = ' '.join(f'{b:02x}' for b in battery_data)
                    self._log(f"  RX Battery ({len(battery_data)} bytes): {hex_str}")
                    self._parse_battery_response(battery_data)
            except asyncio.TimeoutError:
                analysis.protocol_errors.append("No battery response")
                self._log("  No battery response received")
        except Exception as e:
            analysis.protocol_errors.append(f"Battery request failed: {e}")
            self._log(f"  ERROR: {e}")
        
        await asyncio.sleep(0.2)
        
        # Send SOUND command
        self._log("\nSending SOUND command...")
        try:
            hex_cmd = ' '.join(f'{b:02x}' for b in CMD_SOUND)
            self._log(f"  TX: {hex_cmd}")
            await client.write_gatt_char(CHESSNUT_OP_TX_UUID, CMD_SOUND, response=False)
            await asyncio.sleep(0.2)
        except Exception as e:
            self._log(f"  ERROR: {e}")
        
        # Send HAPTIC commands
        self._log("\nSending HAPTIC_ON command...")
        try:
            hex_cmd = ' '.join(f'{b:02x}' for b in CMD_HAPTIC_ON)
            self._log(f"  TX: {hex_cmd}")
            await client.write_gatt_char(CHESSNUT_OP_TX_UUID, CMD_HAPTIC_ON, response=False)
            await asyncio.sleep(0.5)
        except Exception as e:
            self._log(f"  ERROR: {e}")
        
        self._log("\nSending HAPTIC_OFF command...")
        try:
            hex_cmd = ' '.join(f'{b:02x}' for b in CMD_HAPTIC_OFF)
            self._log(f"  TX: {hex_cmd}")
            await client.write_gatt_char(CHESSNUT_OP_TX_UUID, CMD_HAPTIC_OFF, response=False)
            await asyncio.sleep(0.2)
        except Exception as e:
            self._log(f"  ERROR: {e}")
        
        # Probe for unknown commands (version, file count, etc.)
        self._log("\n" + "=" * 40)
        self._log("PROBING FOR UNKNOWN COMMANDS")
        self._log("=" * 40)
        
        for cmd, description in PROBE_COMMANDS:
            self._log(f"\nProbing {description}...")
            try:
                self._notification_events["op_rx"].clear()
                hex_cmd = ' '.join(f'{b:02x}' for b in cmd)
                self._log(f"  TX: {hex_cmd}")
                
                await client.write_gatt_char(CHESSNUT_OP_TX_UUID, cmd, response=False)
                
                # Wait for response
                try:
                    await asyncio.wait_for(self._notification_events["op_rx"].wait(), timeout=1.0)
                    response_data = self._notification_data.get("op_rx")
                    if response_data:
                        hex_str = ' '.join(f'{b:02x}' for b in response_data)
                        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in response_data)
                        self._log(f"  RX ({len(response_data)} bytes): {hex_str}")
                        self._log(f"  ASCII: {ascii_str}")
                except asyncio.TimeoutError:
                    self._log("  No response (timeout)")
            except Exception as e:
                self._log(f"  ERROR: {e}")
            
            await asyncio.sleep(0.1)
        
        # Stop notifications
        try:
            if analysis.has_fen_characteristic:
                await client.stop_notify(CHESSNUT_FEN_RX_UUID)
            if analysis.has_op_rx_characteristic:
                await client.stop_notify(CHESSNUT_OP_RX_UUID)
        except Exception:
            pass
    
    def _parse_fen_response(self, data: bytes):
        """Parse and display FEN response."""
        if len(data) < 34:
            self._log(f"  [FEN too short: {len(data)} bytes]")
            return
        
        # Piece mapping from official Chessnut docs
        piece_map = [
            '.',   # 0: empty
            'q',   # 1: black queen
            'k',   # 2: black king
            'b',   # 3: black bishop
            'p',   # 4: black pawn
            'n',   # 5: black knight
            'R',   # 6: white rook
            'P',   # 7: white pawn
            'r',   # 8: black rook
            'B',   # 9: white bishop
            'N',   # 10: white knight
            'Q',   # 11: white queen
            'K',   # 12: white king
        ]
        
        self._log("  [Board State]")
        
        # Build FEN from position data
        fen = ""
        empty = 0
        
        for row in range(8):
            row_str = f"    {8-row} |"
            for col in range(7, -1, -1):
                index = (row * 8 + col) // 2 + 2  # +2 for header
                
                if col % 2 == 0:
                    piece_val = data[index] & 0x0F
                else:
                    piece_val = (data[index] >> 4) & 0x0F
                
                piece = piece_map[piece_val] if piece_val < len(piece_map) else '?'
                row_str += f" {piece}"
                
                # Build FEN
                if piece == '.':
                    empty += 1
                else:
                    if empty > 0:
                        fen += str(empty)
                        empty = 0
                    fen += piece
            
            if empty > 0:
                fen += str(empty)
                empty = 0
            if row < 7:
                fen += '/'
            
            self._log(row_str)
        
        self._log("      +----------------")
        self._log("        a b c d e f g h")
        self._log(f"  FEN: {fen}")
    
    def _parse_battery_response(self, data: bytes):
        """Parse and display battery response."""
        if len(data) >= 3 and data[0] == RESP_BATTERY and data[1] == 0x02:
            battery_byte = data[2]
            is_charging = (battery_byte & 0x80) != 0
            battery_percent = battery_byte & 0x7F
            status = "Charging" if is_charging else "Not charging"
            self._log(f"  [Battery: {battery_percent}% - {status}]")
        else:
            self._log(f"  [Unknown battery format]")
    
    async def run(self, list_all: bool = False) -> list[DeviceAnalysis]:
        """Run the full analysis.
        
        Args:
            list_all: If True, list all BLE devices without filtering
            
        Returns:
            List of device analyses
        """
        if list_all:
            self.device_name_filter = None
            self.target_addresses = None
        
        devices = await self.scan()
        
        if not devices:
            self._log("\nNo matching devices found.")
            return []
        
        for device, adv in devices:
            await self.analyze_device(device, adv)
            await asyncio.sleep(1.0)  # Small delay between devices
        
        return self.analyses
    
    def print_summary(self):
        """Print summary of all analyzed devices."""
        self._log("\n" + "="*60)
        self._log("ANALYSIS SUMMARY")
        self._log("="*60)
        
        for analysis in self.analyses:
            self._log(f"\n{analysis.name} ({analysis.address})")
            self._log(f"  Connected: {'Yes' if analysis.connected else 'No'}")
            if analysis.connection_error:
                self._log(f"  Error: {analysis.connection_error}")
            self._log(f"  FEN Service: {'Yes' if analysis.has_fen_service else 'No'}")
            self._log(f"  OP Service: {'Yes' if analysis.has_op_service else 'No'}")
            if analysis.has_fen_service or analysis.has_op_service:
                self._log(f"  FEN Char: {'Yes' if analysis.has_fen_characteristic else 'No'}")
                self._log(f"  OP TX Char: {'Yes' if analysis.has_op_tx_characteristic else 'No'}")
                self._log(f"  OP RX Char: {'Yes' if analysis.has_op_rx_characteristic else 'No'}")
            if analysis.fen_response:
                self._log(f"  FEN Response: {len(analysis.fen_response)} bytes")
            if analysis.battery_response:
                self._log(f"  Battery Response: {len(analysis.battery_response)} bytes")
            if analysis.protocol_errors:
                self._log(f"  Protocol Errors: {len(analysis.protocol_errors)}")
                for err in analysis.protocol_errors:
                    self._log(f"    - {err}")


async def main():
    parser = argparse.ArgumentParser(
        description='Chessnut Air BLE Analysis Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Scan for any device with "Chessnut" in the name
    python3 tools/chessnut_ble_client_analysis.py
    
    # List all BLE devices
    python3 tools/chessnut_ble_client_analysis.py --list-all
    
    # Connect to specific address
    python3 tools/chessnut_ble_client_analysis.py --address AA:BB:CC:DD:EE:FF
    
    # Custom scan time
    python3 tools/chessnut_ble_client_analysis.py --scan-time 20
"""
    )
    parser.add_argument('--scan-time', type=float, default=10.0,
                        help='Time to scan for devices (default: 10s)')
    parser.add_argument('--connect-timeout', type=float, default=15.0,
                        help='Connection timeout (default: 15s)')
    parser.add_argument('--name', type=str, default=CHESSNUT_DEVICE_NAME,
                        help=f'Filter by device name substring (default: {CHESSNUT_DEVICE_NAME})')
    parser.add_argument('--address', type=str, action='append',
                        help='Specific device address(es) to analyze')
    parser.add_argument('--list-all', action='store_true',
                        help='List all BLE devices without filtering')
    
    args = parser.parse_args()
    
    print("="*60)
    print("Chessnut Air BLE Analysis Tool")
    print("="*60)
    print()
    
    analyzer = ChessnutAnalyzer(
        scan_time=args.scan_time,
        connect_timeout=args.connect_timeout,
        device_name_filter=args.name,
        target_addresses=args.address
    )
    
    await analyzer.run(list_all=args.list_all)
    analyzer.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
