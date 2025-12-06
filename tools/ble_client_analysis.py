#!/usr/bin/env python3
"""
BLE Client Analysis Tool for Millennium Chess Devices

This tool scans for and compares multiple "MILLENNIUM CHESS" BLE devices.
It performs deep analysis including:
- Advertisement data comparison
- Service and characteristic enumeration
- Connection testing as a Millennium client
- Protocol communication testing

Designed to identify differences between multiple BLE devices advertising
as "MILLENNIUM CHESS" (e.g., original board vs relay/proxy).

Usage:
    python3 tools/ble_client_analysis.py
    python3 tools/ble_client_analysis.py --scan-time 15
    python3 tools/ble_client_analysis.py --connect-timeout 20
    python3 tools/ble_client_analysis.py --list-all
    python3 tools/ble_client_analysis.py --name "CHESS"
    python3 tools/ble_client_analysis.py --address AA:BB:CC:DD:EE:FF --address 11:22:33:44:55:66

Requirements:
    pip install bleak
"""

import asyncio
import argparse
import sys
import json
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


# Millennium ChessLink BLE UUIDs
MILLENNIUM_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
MILLENNIUM_TX_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"  # READ/NOTIFY from board
MILLENNIUM_RX_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"  # WRITE to board

# Target device name
MILLENNIUM_DEVICE_NAME = "MILLENNIUM CHESS"

# Millennium protocol commands
CMD_GET_VERSION = bytes([0x4d, 0x00])  # M\x00 - Get version
CMD_GET_BOARD = bytes([0x73, 0x00])    # s\x00 - Get board state
CMD_LED_OFF = bytes([0x4c, 0x00])      # L\x00 - LED off


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
    has_millennium_service: bool = False
    has_tx_characteristic: bool = False
    has_rx_characteristic: bool = False
    
    # Protocol responses
    version_response: Optional[bytes] = None
    board_response: Optional[bytes] = None
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
            "has_millennium_service": self.has_millennium_service,
            "has_tx_characteristic": self.has_tx_characteristic,
            "has_rx_characteristic": self.has_rx_characteristic,
            "version_response": self.version_response.hex() if self.version_response else None,
            "board_response": self.board_response.hex() if self.board_response else None,
            "protocol_errors": self.protocol_errors,
            "connect_time": self.connect_time,
        }


class MillenniumAnalyzer:
    """Analyzer for Millennium Chess BLE devices."""
    
    def __init__(self, scan_time: float = 10.0, connect_timeout: float = 15.0,
                 device_name_filter: str = MILLENNIUM_DEVICE_NAME,
                 target_addresses: list[str] = None):
        """Initialize the analyzer.
        
        Args:
            scan_time: Time to scan for devices in seconds
            connect_timeout: Connection timeout in seconds
            device_name_filter: Device name to search for (case-insensitive partial match)
            target_addresses: Optional list of specific device addresses to analyze
        """
        self.scan_time = scan_time
        self.connect_timeout = connect_timeout
        self.device_name_filter = device_name_filter
        self.target_addresses = [addr.upper() for addr in (target_addresses or [])]
        self.devices: dict[str, tuple[BLEDevice, AdvertisementData]] = {}
        self.analyses: list[DeviceAnalysis] = []
    
    async def list_all_devices(self) -> list[tuple[BLEDevice, AdvertisementData]]:
        """Scan and list all BLE devices.
        
        Returns:
            List of (device, advertisement_data) tuples sorted by RSSI
        """
        print(f"\n{'='*60}")
        print("SCANNING FOR ALL BLE DEVICES")
        print(f"{'='*60}")
        print(f"Scan time: {self.scan_time} seconds")
        print()
        
        all_devices: dict[str, tuple[BLEDevice, AdvertisementData]] = {}
        
        def detection_callback(device: BLEDevice, advertisement_data: AdvertisementData):
            if device.address not in all_devices:
                all_devices[device.address] = (device, advertisement_data)
            else:
                # Update if better RSSI
                _, old_ad = all_devices[device.address]
                if (advertisement_data.rssi or -100) > (old_ad.rssi or -100):
                    all_devices[device.address] = (device, advertisement_data)
        
        scanner = BleakScanner(detection_callback=detection_callback)
        
        await scanner.start()
        await asyncio.sleep(self.scan_time)
        await scanner.stop()
        
        # Sort by RSSI (strongest first)
        sorted_devices = sorted(
            all_devices.values(),
            key=lambda x: x[1].rssi or -100,
            reverse=True
        )
        
        print(f"Found {len(sorted_devices)} device(s):\n")
        print(f"{'Address':<40} {'Name':<30} {'RSSI':>6}")
        print("-" * 80)
        
        for device, ad_data in sorted_devices:
            name = device.name or ad_data.local_name or "(no name)"
            rssi = ad_data.rssi or "N/A"
            # Highlight potential Millennium devices
            highlight = " <-- MILLENNIUM?" if "chess" in name.lower() or "millennium" in name.lower() else ""
            print(f"{device.address:<40} {name[:30]:<30} {rssi:>6}{highlight}")
            
            # Show service UUIDs if present
            if ad_data.service_uuids:
                for uuid in ad_data.service_uuids:
                    millennium_marker = " <-- MILLENNIUM SERVICE!" if uuid.lower() == MILLENNIUM_SERVICE_UUID.lower() else ""
                    print(f"    Service: {uuid}{millennium_marker}")
        
        return sorted_devices
    
    async def scan_for_devices(self) -> list[tuple[BLEDevice, AdvertisementData]]:
        """Scan for devices matching the filter criteria.
        
        Returns:
            List of (device, advertisement_data) tuples
        """
        # If specific addresses provided, scan for those
        if self.target_addresses:
            return await self._scan_for_addresses()
        
        print(f"\n{'='*60}")
        print(f"SCANNING FOR '{self.device_name_filter}' DEVICES")
        print(f"{'='*60}")
        print(f"Scan time: {self.scan_time} seconds")
        print(f"Looking for devices with name containing '{self.device_name_filter}'...")
        print()
        
        filter_upper = self.device_name_filter.upper()
        
        def detection_callback(device: BLEDevice, advertisement_data: AdvertisementData):
            name = device.name or advertisement_data.local_name or ""
            if filter_upper in name.upper():
                if device.address not in self.devices:
                    print(f"  Found: {name} at {device.address} (RSSI: {advertisement_data.rssi} dBm)")
                    self.devices[device.address] = (device, advertisement_data)
                else:
                    # Update if better RSSI
                    _, old_ad = self.devices[device.address]
                    if (advertisement_data.rssi or -100) > (old_ad.rssi or -100):
                        self.devices[device.address] = (device, advertisement_data)
        
        scanner = BleakScanner(detection_callback=detection_callback)
        
        await scanner.start()
        await asyncio.sleep(self.scan_time)
        await scanner.stop()
        
        print(f"\nFound {len(self.devices)} matching device(s)")
        return list(self.devices.values())
    
    async def _scan_for_addresses(self) -> list[tuple[BLEDevice, AdvertisementData]]:
        """Scan for specific device addresses.
        
        Returns:
            List of (device, advertisement_data) tuples
        """
        print(f"\n{'='*60}")
        print("SCANNING FOR SPECIFIC DEVICES")
        print(f"{'='*60}")
        print(f"Scan time: {self.scan_time} seconds")
        print(f"Target addresses: {', '.join(self.target_addresses)}")
        print()
        
        def detection_callback(device: BLEDevice, advertisement_data: AdvertisementData):
            addr_upper = device.address.upper()
            if addr_upper in self.target_addresses:
                name = device.name or advertisement_data.local_name or "(no name)"
                if device.address not in self.devices:
                    print(f"  Found: {name} at {device.address} (RSSI: {advertisement_data.rssi} dBm)")
                    self.devices[device.address] = (device, advertisement_data)
                else:
                    # Update if better RSSI
                    _, old_ad = self.devices[device.address]
                    if (advertisement_data.rssi or -100) > (old_ad.rssi or -100):
                        self.devices[device.address] = (device, advertisement_data)
        
        scanner = BleakScanner(detection_callback=detection_callback)
        
        await scanner.start()
        await asyncio.sleep(self.scan_time)
        await scanner.stop()
        
        found = set(d[0].address.upper() for d in self.devices.values())
        missing = set(self.target_addresses) - found
        if missing:
            print(f"\nWarning: Could not find devices: {', '.join(missing)}")
        
        print(f"\nFound {len(self.devices)} of {len(self.target_addresses)} target device(s)")
        return list(self.devices.values())
    
    def analyze_advertisement(self, device: BLEDevice, ad_data: AdvertisementData) -> DeviceAnalysis:
        """Analyze advertisement data from a device.
        
        Args:
            device: BLE device
            ad_data: Advertisement data
            
        Returns:
            DeviceAnalysis with advertisement info populated
        """
        analysis = DeviceAnalysis(
            address=device.address,
            name=device.name or "Unknown",
            rssi=ad_data.rssi,
            scan_time=datetime.now()
        )
        
        # Extract advertisement details
        analysis.local_name = ad_data.local_name
        analysis.manufacturer_data = dict(ad_data.manufacturer_data)
        analysis.service_uuids = list(ad_data.service_uuids) if ad_data.service_uuids else []
        analysis.service_data = dict(ad_data.service_data) if ad_data.service_data else {}
        analysis.tx_power = ad_data.tx_power
        
        return analysis
    
    async def connect_and_analyze(self, device: BLEDevice, analysis: DeviceAnalysis) -> DeviceAnalysis:
        """Connect to device and perform deep analysis.
        
        Args:
            device: BLE device to connect to
            analysis: Existing analysis to update
            
        Returns:
            Updated DeviceAnalysis
        """
        print(f"\n  Connecting to {device.address}...")
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            async with BleakClient(device, timeout=self.connect_timeout) as client:
                analysis.connected = True
                analysis.connect_time = asyncio.get_event_loop().time() - start_time
                
                # Get MTU
                try:
                    analysis.mtu_size = client.mtu_size
                    print(f"    MTU size: {analysis.mtu_size}")
                except AttributeError:
                    print("    MTU size: Not available")
                
                # Enumerate services
                print(f"    Discovering services...")
                services = client.services
                
                for service in services:
                    service_info = {
                        "uuid": service.uuid,
                        "characteristics": []
                    }
                    
                    # Check if this is the Millennium service
                    if service.uuid.lower() == MILLENNIUM_SERVICE_UUID.lower():
                        analysis.has_millennium_service = True
                        print(f"    Found Millennium service: {service.uuid}")
                    
                    for char in service.characteristics:
                        char_info = {
                            "uuid": char.uuid,
                            "properties": list(char.properties),
                            "handle": char.handle
                        }
                        service_info["characteristics"].append(char_info)
                        
                        # Check for TX/RX characteristics
                        char_uuid_lower = char.uuid.lower()
                        if char_uuid_lower == MILLENNIUM_TX_UUID.lower():
                            analysis.has_tx_characteristic = True
                            print(f"      TX characteristic: {char.uuid} [{', '.join(char.properties)}]")
                        elif char_uuid_lower == MILLENNIUM_RX_UUID.lower():
                            analysis.has_rx_characteristic = True
                            print(f"      RX characteristic: {char.uuid} [{', '.join(char.properties)}]")
                    
                    analysis.services.append(service_info)
                
                print(f"    Total services: {len(analysis.services)}")
                
                # If Millennium service found, try protocol commands
                if analysis.has_millennium_service and analysis.has_tx_characteristic and analysis.has_rx_characteristic:
                    await self._test_protocol(client, analysis)
                else:
                    print("    Skipping protocol test - missing required characteristics")
                
        except asyncio.TimeoutError:
            analysis.connection_error = "Connection timeout"
            print(f"    Connection timed out after {self.connect_timeout}s")
        except Exception as e:
            analysis.connection_error = str(e)
            print(f"    Connection error: {e}")
        
        return analysis
    
    async def _test_protocol(self, client: BleakClient, analysis: DeviceAnalysis):
        """Test Millennium protocol communication.
        
        Args:
            client: Connected BleakClient
            analysis: Analysis to update with results
        """
        print(f"    Testing Millennium protocol...")
        
        response_queue = asyncio.Queue()
        
        def notification_handler(sender, data: bytearray):
            asyncio.get_event_loop().call_soon_threadsafe(
                response_queue.put_nowait, bytes(data)
            )
        
        try:
            # Enable notifications on TX characteristic
            await client.start_notify(MILLENNIUM_TX_UUID, notification_handler)
            print(f"      Notifications enabled on TX characteristic")
            
            # Test 1: Get version
            print(f"      Sending version command (0x{CMD_GET_VERSION.hex()})...")
            await client.write_gatt_char(MILLENNIUM_RX_UUID, CMD_GET_VERSION, response=False)
            
            try:
                response = await asyncio.wait_for(response_queue.get(), timeout=3.0)
                analysis.version_response = response
                print(f"      Version response: {response.hex()} ({response!r})")
            except asyncio.TimeoutError:
                analysis.protocol_errors.append("Version command timeout")
                print(f"      Version command timed out")
            
            # Small delay between commands
            await asyncio.sleep(0.3)
            
            # Test 2: Get board state
            print(f"      Sending board state command (0x{CMD_GET_BOARD.hex()})...")
            await client.write_gatt_char(MILLENNIUM_RX_UUID, CMD_GET_BOARD, response=False)
            
            try:
                response = await asyncio.wait_for(response_queue.get(), timeout=3.0)
                analysis.board_response = response
                print(f"      Board response: {response.hex()}")
                if len(response) >= 8:
                    print(f"      Board response (first 8 bytes): {response[:8].hex()}")
            except asyncio.TimeoutError:
                analysis.protocol_errors.append("Board state command timeout")
                print(f"      Board state command timed out")
            
            # Stop notifications
            await client.stop_notify(MILLENNIUM_TX_UUID)
            
        except Exception as e:
            analysis.protocol_errors.append(f"Protocol test error: {e}")
            print(f"      Protocol test error: {e}")
    
    async def analyze_all(self) -> list[DeviceAnalysis]:
        """Scan and analyze all MILLENNIUM CHESS devices.
        
        Returns:
            List of DeviceAnalysis results
        """
        # Scan for devices
        devices = await self.scan_for_devices()
        
        if not devices:
            print("\nNo MILLENNIUM CHESS devices found.")
            return []
        
        # Analyze each device
        print(f"\n{'='*60}")
        print("ANALYZING DEVICES")
        print(f"{'='*60}")
        
        for device, ad_data in devices:
            print(f"\n--- Device: {device.address} ---")
            
            # Analyze advertisement
            analysis = self.analyze_advertisement(device, ad_data)
            
            # Connect and do deep analysis
            analysis = await self.connect_and_analyze(device, analysis)
            
            self.analyses.append(analysis)
            
            # Small delay between devices to avoid BLE congestion
            if len(devices) > 1:
                await asyncio.sleep(2)
        
        return self.analyses
    
    def compare_devices(self) -> dict:
        """Compare analyzed devices and identify differences.
        
        Returns:
            Dictionary containing comparison results
        """
        if len(self.analyses) < 2:
            return {"error": "Need at least 2 devices to compare"}
        
        comparison = {
            "device_count": len(self.analyses),
            "devices": {},
            "differences": [],
            "similarities": []
        }
        
        # Convert all analyses to dicts
        for analysis in self.analyses:
            comparison["devices"][analysis.address] = analysis.to_dict()
        
        # Compare key attributes
        keys_to_compare = [
            "rssi",
            "local_name",
            "manufacturer_data",
            "service_uuids",
            "tx_power",
            "connected",
            "mtu_size",
            "has_millennium_service",
            "has_tx_characteristic",
            "has_rx_characteristic",
            "version_response",
            "board_response",
        ]
        
        base_analysis = self.analyses[0]
        base_dict = base_analysis.to_dict()
        
        for key in keys_to_compare:
            base_value = base_dict.get(key)
            all_same = True
            
            for other_analysis in self.analyses[1:]:
                other_dict = other_analysis.to_dict()
                other_value = other_dict.get(key)
                
                if base_value != other_value:
                    all_same = False
                    comparison["differences"].append({
                        "attribute": key,
                        "values": {
                            a.address: a.to_dict().get(key) for a in self.analyses
                        }
                    })
                    break
            
            if all_same:
                comparison["similarities"].append({
                    "attribute": key,
                    "value": base_value
                })
        
        # Compare services structure
        service_uuids_by_device = {}
        for analysis in self.analyses:
            service_uuids_by_device[analysis.address] = set(
                s["uuid"] for s in analysis.services
            )
        
        # Find common and unique services
        if len(service_uuids_by_device) >= 2:
            all_services = set()
            for services in service_uuids_by_device.values():
                all_services.update(services)
            
            common_services = set.intersection(*service_uuids_by_device.values())
            
            comparison["service_comparison"] = {
                "common_services": list(common_services),
                "all_services": list(all_services),
                "unique_per_device": {
                    addr: list(services - common_services)
                    for addr, services in service_uuids_by_device.items()
                }
            }
        
        return comparison
    
    def print_single_device_report(self, analysis: DeviceAnalysis):
        """Print detailed report for a single device.
        
        Args:
            analysis: DeviceAnalysis for the device
        """
        print(f"\n{'='*60}")
        print("SINGLE DEVICE ANALYSIS REPORT")
        print(f"{'='*60}")
        
        print(f"\n--- Basic Information ---")
        print(f"  Address: {analysis.address}")
        print(f"  Name: {analysis.name}")
        print(f"  RSSI: {analysis.rssi} dBm")
        print(f"  Local Name: {analysis.local_name}")
        print(f"  TX Power: {analysis.tx_power}")
        
        print(f"\n--- Advertisement Data ---")
        if analysis.manufacturer_data:
            print(f"  Manufacturer Data:")
            for mfg_id, data in analysis.manufacturer_data.items():
                hex_data = data.hex() if isinstance(data, bytes) else str(data)
                print(f"    0x{mfg_id:04x}: {hex_data}")
        else:
            print(f"  Manufacturer Data: None")
        
        if analysis.service_uuids:
            print(f"  Advertised Service UUIDs:")
            for uuid in analysis.service_uuids:
                millennium_marker = " <-- MILLENNIUM SERVICE" if uuid.lower() == MILLENNIUM_SERVICE_UUID.lower() else ""
                print(f"    - {uuid}{millennium_marker}")
        else:
            print(f"  Advertised Service UUIDs: None")
        
        print(f"\n--- Connection Status ---")
        print(f"  Connected: {analysis.connected}")
        print(f"  Connection Time: {analysis.connect_time:.2f}s" if analysis.connect_time else "  Connection Time: N/A")
        print(f"  MTU Size: {analysis.mtu_size}")
        if analysis.connection_error:
            print(f"  Connection Error: {analysis.connection_error}")
        
        print(f"\n--- GATT Services ({len(analysis.services)}) ---")
        for service in analysis.services:
            millennium_marker = " <-- MILLENNIUM SERVICE" if service['uuid'].lower() == MILLENNIUM_SERVICE_UUID.lower() else ""
            print(f"  Service: {service['uuid']}{millennium_marker}")
            for char in service['characteristics']:
                props = ', '.join(char['properties'])
                tx_marker = " <-- TX (notifications)" if char['uuid'].lower() == MILLENNIUM_TX_UUID.lower() else ""
                rx_marker = " <-- RX (commands)" if char['uuid'].lower() == MILLENNIUM_RX_UUID.lower() else ""
                print(f"    Char: {char['uuid']} [{props}]{tx_marker}{rx_marker}")
        
        print(f"\n--- Millennium Protocol Status ---")
        print(f"  Has Millennium Service: {analysis.has_millennium_service}")
        print(f"  Has TX Characteristic: {analysis.has_tx_characteristic}")
        print(f"  Has RX Characteristic: {analysis.has_rx_characteristic}")
        
        if analysis.version_response:
            print(f"\n--- Protocol Responses ---")
            print(f"  Version Response (hex): {analysis.version_response.hex()}")
            try:
                decoded = analysis.version_response.decode('utf-8', errors='replace')
                print(f"  Version Response (ascii): {decoded}")
            except:
                pass
        
        if analysis.board_response:
            print(f"  Board Response (hex): {analysis.board_response.hex()}")
            try:
                decoded = analysis.board_response.decode('utf-8', errors='replace')
                print(f"  Board Response (ascii): {decoded}")
                # Try to parse board state
                if decoded.startswith('s') and len(decoded) >= 65:
                    board_str = decoded[1:65]  # 64 squares
                    print(f"  Board State (parsed):")
                    for rank in range(8):
                        rank_str = board_str[rank*8:(rank+1)*8]
                        print(f"    {8-rank}: {' '.join(rank_str)}")
            except:
                pass
        
        if analysis.protocol_errors:
            print(f"\n--- Protocol Errors ---")
            for error in analysis.protocol_errors:
                print(f"  - {error}")
    
    def print_comparison_report(self, comparison: dict):
        """Print a formatted comparison report.
        
        Args:
            comparison: Comparison results dictionary
        """
        # If only one device, print single device report
        if len(self.analyses) == 1:
            self.print_single_device_report(self.analyses[0])
            return
        
        print(f"\n{'='*60}")
        print("DEVICE COMPARISON REPORT")
        print(f"{'='*60}")
        
        if "error" in comparison:
            print(f"\n{comparison['error']}")
            return
        
        print(f"\nDevices analyzed: {comparison['device_count']}")
        
        # Print device summaries
        print(f"\n--- Device Summaries ---")
        for address, device_info in comparison["devices"].items():
            print(f"\n  {address}:")
            print(f"    Name: {device_info.get('name')}")
            print(f"    RSSI: {device_info.get('rssi')} dBm")
            print(f"    Connected: {device_info.get('connected')}")
            print(f"    MTU: {device_info.get('mtu_size')}")
            print(f"    Has Millennium Service: {device_info.get('has_millennium_service')}")
            print(f"    Services count: {len(device_info.get('services', []))}")
            if device_info.get('version_response'):
                print(f"    Version Response: {device_info.get('version_response')}")
            if device_info.get('connection_error'):
                print(f"    Connection Error: {device_info.get('connection_error')}")
        
        # Print differences
        print(f"\n--- Key Differences ---")
        if comparison["differences"]:
            for diff in comparison["differences"]:
                print(f"\n  {diff['attribute']}:")
                for addr, value in diff["values"].items():
                    print(f"    {addr}: {value}")
        else:
            print("  No significant differences found")
        
        # Print similarities
        print(f"\n--- Similarities ---")
        if comparison["similarities"]:
            for sim in comparison["similarities"][:10]:  # Limit output
                print(f"  {sim['attribute']}: {sim['value']}")
            if len(comparison["similarities"]) > 10:
                print(f"  ... and {len(comparison['similarities']) - 10} more")
        
        # Print service comparison
        if "service_comparison" in comparison:
            sc = comparison["service_comparison"]
            print(f"\n--- Service Comparison ---")
            print(f"  Common services: {len(sc['common_services'])}")
            for uuid in sc["common_services"]:
                print(f"    - {uuid}")
            
            print(f"\n  Unique services per device:")
            for addr, unique in sc["unique_per_device"].items():
                if unique:
                    print(f"    {addr}:")
                    for uuid in unique:
                        print(f"      - {uuid}")
                else:
                    print(f"    {addr}: (none)")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="BLE Analysis Tool for Millennium Chess Devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Scan for MILLENNIUM CHESS devices (default)
    python3 ble_client_analysis.py
    
    # List all BLE devices (to find device addresses)
    python3 ble_client_analysis.py --list-all
    
    # Scan for devices with custom name filter
    python3 ble_client_analysis.py --name "CHESS"
    
    # Analyze specific devices by address
    python3 ble_client_analysis.py --address AA:BB:CC:DD:EE:FF --address 11:22:33:44:55:66
    
    # Longer scan time
    python3 ble_client_analysis.py --scan-time 15
    
    # Output as JSON
    python3 ble_client_analysis.py --json
        """
    )
    parser.add_argument(
        "--scan-time",
        type=float,
        default=10.0,
        help="Time to scan for devices in seconds (default: 10)"
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=15.0,
        help="Connection timeout in seconds (default: 15)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    parser.add_argument(
        "--no-connect",
        action="store_true",
        help="Only scan, don't connect to devices"
    )
    parser.add_argument(
        "--list-all",
        action="store_true",
        help="List all BLE devices (useful for finding device addresses)"
    )
    parser.add_argument(
        "--name",
        type=str,
        default=MILLENNIUM_DEVICE_NAME,
        help=f"Device name filter (case-insensitive partial match, default: '{MILLENNIUM_DEVICE_NAME}')"
    )
    parser.add_argument(
        "--address",
        type=str,
        action="append",
        dest="addresses",
        help="Specific device address to analyze (can be specified multiple times)"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("MILLENNIUM CHESS BLE DEVICE ANALYZER")
    print("=" * 60)
    print(f"Scan time: {args.scan_time}s")
    print(f"Connect timeout: {args.connect_timeout}s")
    
    analyzer = MillenniumAnalyzer(
        scan_time=args.scan_time,
        connect_timeout=args.connect_timeout,
        device_name_filter=args.name,
        target_addresses=args.addresses
    )
    
    # List all devices mode
    if args.list_all:
        await analyzer.list_all_devices()
        print(f"\n{'='*60}")
        print("Use --address <ADDRESS> to analyze specific devices")
        print("Use --name <NAME> to filter by device name")
        print(f"{'='*60}")
        return 0
    
    print(f"Connect to devices: {not args.no_connect}")
    if args.addresses:
        print(f"Target addresses: {', '.join(args.addresses)}")
    else:
        print(f"Name filter: '{args.name}'")
    
    if args.no_connect:
        # Scan only
        devices = await analyzer.scan_for_devices()
        for device, ad_data in devices:
            analysis = analyzer.analyze_advertisement(device, ad_data)
            analyzer.analyses.append(analysis)
    else:
        # Full analysis
        await analyzer.analyze_all()
    
    # Generate comparison
    comparison = analyzer.compare_devices()
    
    if args.json:
        print("\n" + json.dumps(comparison, indent=2, default=str))
    else:
        analyzer.print_comparison_report(comparison)
    
    # Summary
    print(f"\n{'='*60}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*60}")
    print(f"Devices found: {len(analyzer.analyses)}")
    
    connected_count = sum(1 for a in analyzer.analyses if a.connected)
    print(f"Devices connected: {connected_count}")
    
    millennium_count = sum(1 for a in analyzer.analyses if a.has_millennium_service)
    print(f"Devices with Millennium service: {millennium_count}")
    
    protocol_ok_count = sum(1 for a in analyzer.analyses 
                           if a.version_response and not a.protocol_errors)
    print(f"Devices responding to protocol: {protocol_ok_count}")
    
    if len(analyzer.analyses) >= 2:
        diff_count = len(comparison.get("differences", []))
        print(f"Key differences found: {diff_count}")
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
