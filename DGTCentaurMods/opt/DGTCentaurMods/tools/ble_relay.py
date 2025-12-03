#!/usr/bin/env python3
"""
BLE Relay Tool

This tool connects to a BLE chess board and auto-detects the protocol
(Millennium, Chessnut Air, or DGT Pegasus) by probing with initial commands.

Usage:
    python3 tools/ble_relay.py [--device-name "Chessnut Air"]
    python3 tools/ble_relay.py --device-name "MILLENNIUM CHESS"
    python3 tools/ble_relay.py --device-name "DGT_PEGASUS_*"
    
Requirements:
    pip install bleak
"""

import argparse
import asyncio
import os
import signal
import sys

# Ensure we import the repo package first (not a system-installed copy)
try:
    REPO_OPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if REPO_OPT not in sys.path:
        sys.path.insert(0, REPO_OPT)
except Exception as e:
    print(f"Warning: Could not add repo path: {e}")

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.tools.clients.ble_client import BLEClient, clear_bluez_device_cache
from DGTCentaurMods.tools.clients.millennium_client import MillenniumClient
from DGTCentaurMods.tools.clients.chessnut_client import ChessnutClient
from DGTCentaurMods.tools.clients.pegasus_client import PegasusClient


class BLERelayClient:
    """BLE relay client that auto-detects Millennium, Chessnut Air, or Pegasus protocol."""
    
    def __init__(self, device_name: str = "Chessnut Air"):
        """Initialize the BLE relay client.
        
        Args:
            device_name: Name of the BLE device to connect to
        """
        self.device_name = device_name
        self.ble_client = BLEClient()
        self.detected_protocol: str | None = None
        self.write_char_uuid: str | None = None
        self._running = True
        
        # Protocol clients
        self.millennium = MillenniumClient()
        self.chessnut = ChessnutClient()
        self.pegasus = PegasusClient()
    
    def _normalize_uuid(self, uuid_str: str) -> str:
        """Normalize UUID for comparison (lowercase, with dashes)."""
        return uuid_str.lower()
    
    def _find_characteristic_uuid(self, target_uuid: str) -> str | None:
        """Find a characteristic UUID in the discovered services.
        
        Args:
            target_uuid: UUID to find (case-insensitive)
            
        Returns:
            The actual UUID string if found, None otherwise
        """
        if not self.ble_client.services:
            return None

        target_lower = target_uuid.lower()
        
        for service in self.ble_client.services:
            for char in service.characteristics:
                if char.uuid.lower() == target_lower:
                    return char.uuid
        
        return None
    
    async def _probe_millennium(self) -> bool:
        """Probe for Millennium protocol.
        
        Returns:
            True if Millennium protocol detected, False otherwise
        """
        # Find Millennium characteristics
        rx_uuid = self._find_characteristic_uuid(self.millennium.rx_uuid)
        tx_uuid = self._find_characteristic_uuid(self.millennium.tx_uuid)
        
        if not rx_uuid or not tx_uuid:
            log.info("Millennium characteristics not found")
            return False
        
        log.info(f"Found Millennium RX: {rx_uuid}")
        log.info(f"Found Millennium TX: {tx_uuid}")
        
        # Enable notifications on TX
        if not await self.ble_client.start_notify(tx_uuid, self.millennium.notification_handler):
            log.warning("Failed to enable Millennium notifications")
            return False
        
        # Send S probe command
        self.millennium.reset_response_flag()
        s_cmd = self.millennium.encode_command(self.millennium.get_probe_command())
        log.info(f"Sending Millennium S probe: {' '.join(f'{b:02x}' for b in s_cmd)}")
        
        if not await self.ble_client.write_characteristic(rx_uuid, s_cmd, response=False):
            log.warning("Failed to send Millennium probe")
            return False
        
        # Wait for response
        for _ in range(30):  # 3 seconds
            await asyncio.sleep(0.1)
            if self.millennium.got_response():
                self.write_char_uuid = rx_uuid
                self.millennium.rx_char_uuid = rx_uuid
                self.millennium.tx_char_uuid = tx_uuid
                return True
        
        log.info("No Millennium response received")
        return False
    
    async def _probe_chessnut(self) -> bool:
        """Probe for Chessnut Air protocol.
        
        Returns:
            True if Chessnut Air protocol detected, False otherwise
        """
        # Find Chessnut characteristics
        tx_uuid = self._find_characteristic_uuid(self.chessnut.op_tx_uuid)
        rx_uuid = self._find_characteristic_uuid(self.chessnut.op_rx_uuid)
        fen_uuid = self._find_characteristic_uuid(self.chessnut.fen_uuid)
        
        if not tx_uuid:
            log.info("Chessnut TX characteristic not found")
            return False
        
        log.info(f"Found Chessnut TX: {tx_uuid}")
        if rx_uuid:
            log.info(f"Found Chessnut RX: {rx_uuid}")
        if fen_uuid:
            log.info(f"Found Chessnut FEN: {fen_uuid}")
        
        # Enable notifications
        if rx_uuid:
            await self.ble_client.start_notify(rx_uuid, self.chessnut.operation_notification_handler)
        if fen_uuid:
            await self.ble_client.start_notify(fen_uuid, self.chessnut.fen_notification_handler)
        
        # Send enable reporting command
        self.chessnut.reset_response_flag()
        cmd = self.chessnut.get_enable_reporting_command()
        log.info(f"Sending Chessnut enable reporting: {' '.join(f'{b:02x}' for b in cmd)}")
        
        if not await self.ble_client.write_characteristic(tx_uuid, cmd, response=False):
            log.warning("Failed to send Chessnut probe")
            return False
        
        # Wait for response
        for _ in range(30):  # 3 seconds
            await asyncio.sleep(0.1)
            if self.chessnut.got_response():
                self.write_char_uuid = tx_uuid
                self.chessnut.op_tx_char_uuid = tx_uuid
                self.chessnut.op_rx_char_uuid = rx_uuid
                self.chessnut.fen_char_uuid = fen_uuid
                return True
        
        log.info("No Chessnut response received")
        return False
    
    async def _probe_pegasus(self) -> bool:
        """Probe for DGT Pegasus protocol.
        
        Returns:
            True if Pegasus protocol detected, False otherwise
        """
        # Find Pegasus characteristics (Nordic UART Service)
        tx_uuid = self._find_characteristic_uuid(self.pegasus.tx_uuid)
        rx_uuid = self._find_characteristic_uuid(self.pegasus.rx_uuid)
        
        if not tx_uuid or not rx_uuid:
            log.info("Pegasus characteristics not found")
            return False
        
        log.info(f"Found Pegasus TX (notify): {tx_uuid}")
        log.info(f"Found Pegasus RX (write): {rx_uuid}")
        
        # Enable notifications on TX characteristic
        await self.ble_client.start_notify(tx_uuid, self.pegasus.notification_handler)
        
        self.pegasus.reset_response_flag()
        self.write_char_uuid = rx_uuid
        self.pegasus.rx_char_uuid = rx_uuid
        self.pegasus.tx_char_uuid = tx_uuid
        
        # Send probe commands
        for probe_cmd in self.pegasus.get_probe_commands():
            log.info(f"Sending Pegasus probe: {probe_cmd.hex()}")
            if not await self.ble_client.write_characteristic(rx_uuid, probe_cmd, response=False):
                log.warning("Failed to send Pegasus probe")
                return False
            await asyncio.sleep(0.5)
        
        # Wait for response
        for _ in range(30):  # 3 seconds
            await asyncio.sleep(0.1)
            if self.pegasus.got_response():
                return True
        
        # Even if no response, if we found the characteristics, consider it detected
        log.info("Pegasus characteristics found (no probe response yet)")
        return True
    
    async def connect(self) -> bool:
        """Connect to the device and auto-detect protocol.
        
        Returns:
            True if connection and protocol detection successful, False otherwise
        """
        if not await self.ble_client.scan_and_connect(self.device_name):
            return False
        
        # Log discovered services
        self.ble_client.log_services()
        
        # Try Millennium first
        log.info("Probing for Millennium protocol...")
        if await self._probe_millennium():
            self.detected_protocol = "millennium"
            log.info("Millennium protocol detected and active")
            
            # Send full initialization sequence
            for cmd in self.millennium.get_initialization_commands():
                encoded = self.millennium.encode_command(cmd)
                log.info(f"Sending Millennium '{cmd}': {' '.join(f'{b:02x}' for b in encoded)}")
                await self.ble_client.write_characteristic(self.write_char_uuid, encoded, response=False)
                await asyncio.sleep(0.5)
            
            return True
        
        # Try Chessnut Air
        log.info("Probing for Chessnut Air protocol...")
        if await self._probe_chessnut():
            self.detected_protocol = "chessnut_air"
            log.info("Chessnut Air protocol detected and active")
            
            # Check MTU
            if self.ble_client.mtu_size:
                self.chessnut.check_mtu(self.ble_client.mtu_size)
            
            return True
        
        # Try DGT Pegasus
        log.info("Probing for DGT Pegasus protocol...")
        if await self._probe_pegasus():
            self.detected_protocol = "pegasus"
            log.info("DGT Pegasus protocol detected and active")
            return True
        
        log.warning("No supported protocol detected")
        return False
        
    async def disconnect(self):
        """Disconnect from the device."""
        await self.ble_client.disconnect()
    
    async def run(self):
        """Main run loop - keeps connection alive and sends periodic commands."""
        log.info(f"Running with {self.detected_protocol} protocol")
        log.info("Press Ctrl+C to exit")
        
        while self._running and self.ble_client.is_connected:
            # Use shorter sleep intervals to respond to stop signal faster
            for _ in range(100):  # 10 seconds total (100 * 0.1s)
                if not self._running:
                    break
                await asyncio.sleep(0.1)
            
            if not self._running:
                break
        
            # Send periodic status command
            if self.detected_protocol == "millennium" and self.write_char_uuid:
                s_cmd = self.millennium.encode_command(self.millennium.get_status_command())
                log.info("Sending periodic Millennium S command")
                await self.ble_client.write_characteristic(self.write_char_uuid, s_cmd, response=False)
            elif self.detected_protocol == "chessnut_air" and self.write_char_uuid:
                log.info("Sending periodic Chessnut enable reporting")
                await self.ble_client.write_characteristic(
                    self.write_char_uuid,
                    self.chessnut.get_enable_reporting_command(),
                    response=False
                )
            elif self.detected_protocol == "pegasus" and self.write_char_uuid:
                log.info("Sending periodic Pegasus board request")
                await self.ble_client.write_characteristic(
                    self.write_char_uuid,
                    self.pegasus.get_board_command(),
                    response=False
                )
    
    def stop(self):
        """Signal the client to stop."""
        self._running = False
        self.ble_client.stop()


class GatttoolRelayClient:
    """BLE relay client using gatttool backend.
    
    Useful for devices where bleak fails due to BlueZ dual-mode handling.
    """
    
    def __init__(self, device_name: str = "Chessnut Air"):
        """Initialize the gatttool relay client.
        
        Args:
            device_name: Name of the BLE device to connect to
        """
        self.device_name = device_name
        self.device_address: str | None = None
        self.gatttool_client = None
        self.detected_protocol: str | None = None
        self.write_handle: int | None = None
        self.read_handle: int | None = None
        self._running = True
        
        # Protocol clients
        self.millennium = MillenniumClient()
        self.chessnut = ChessnutClient()
        self.pegasus = PegasusClient()
    
    async def scan_for_device(self) -> str | None:
        """Scan for device by name using hcitool lescan.
        
        Returns:
            Device address if found, None otherwise
        """
        import re
        import subprocess
        
        log.info(f"Scanning for device: {self.device_name} (using LE scan)")
        
        target_upper = self.device_name.upper()
        
        try:
            # Use hcitool lescan which specifically scans for BLE devices
            # Run for up to 10 seconds
            process = subprocess.Popen(
                ['sudo', 'hcitool', 'lescan'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            found_address = None
            start_time = asyncio.get_event_loop().time()
            timeout = 10.0
            
            while asyncio.get_event_loop().time() - start_time < timeout:
                # Check if process has output
                import select
                ready, _, _ = select.select([process.stdout], [], [], 0.5)
                if ready:
                    line = process.stdout.readline()
                    if line:
                        line = line.strip()
                        if target_upper in line.upper():
                            # Parse: "34:81:F4:ED:78:34 MILLENNIUM CHESS"
                            match = re.match(r'([0-9A-Fa-f:]+)\s+', line)
                            if match:
                                found_address = match.group(1)
                                log.info(f"Found device at {found_address}")
                            break
                await asyncio.sleep(0.1)
        
            # Kill the scan process
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
            
            if found_address:
                return found_address
            
            log.warning(f"Device '{self.device_name}' not found via LE scan")
            return None
                
        except Exception as e:
            log.error(f"Scan error: {e}")
            return None
                
    async def connect(self) -> bool:
        """Connect to the device using gatttool.
        
        Returns:
            True if connected and protocol detected, False otherwise
        """
        from DGTCentaurMods.tools.clients.gatttool_client import GatttoolClient
        
        # Scan for device if address not known
        if not self.device_address:
            self.device_address = await self.scan_for_device()
            if not self.device_address:
                return False
        
        self.gatttool_client = GatttoolClient()
        
        # Connect and discover services in one session
        if not await self.gatttool_client.connect_and_discover(self.device_address):
            log.error("Failed to connect and discover services")
            return False
        
        # Probe for Millennium protocol
        log.info("Probing for Millennium protocol...")
        mill_rx = self.gatttool_client.find_characteristic_by_uuid(self.millennium.rx_uuid)
        mill_tx = self.gatttool_client.find_characteristic_by_uuid(self.millennium.tx_uuid)
        
        if mill_rx and mill_tx:
            log.info(f"Found Millennium RX: handle {mill_rx['value_handle']:04x}")
            log.info(f"Found Millennium TX: handle {mill_tx['value_handle']:04x}")
                                        
            # Enable notifications on TX
            await self.gatttool_client.enable_notifications(
                mill_tx['value_handle'], self.millennium.gatttool_notification_handler
            )
            
            # Send probe command
            s_cmd = self.millennium.encode_command(self.millennium.get_probe_command())
            log.info(f"Sending Millennium S probe: {s_cmd.hex()}")
            await self.gatttool_client.write_characteristic(
                mill_rx['value_handle'], s_cmd, response=False
            )
            
            await asyncio.sleep(2)
            
            self.detected_protocol = "millennium"
            self.write_handle = mill_rx['value_handle']
            self.read_handle = mill_tx['value_handle']
            log.info("Millennium protocol active")
            return True
        
        # Probe for Chessnut Air
        log.info("Probing for Chessnut Air protocol...")
        fen_rx = self.gatttool_client.find_characteristic_by_uuid(self.chessnut.fen_uuid)
        op_tx = self.gatttool_client.find_characteristic_by_uuid(self.chessnut.op_tx_uuid)
        
        if fen_rx and op_tx:
            log.info(f"Found Chessnut FEN RX: handle {fen_rx['value_handle']:04x}")
            log.info(f"Found Chessnut OP TX: handle {op_tx['value_handle']:04x}")
            
            await self.gatttool_client.enable_notifications(
                fen_rx['value_handle'], self.chessnut.gatttool_notification_handler
            )
            
            # Send enable reporting
            cmd = self.chessnut.get_enable_reporting_command()
            log.info(f"Sending Chessnut enable reporting: {cmd.hex()}")
            await self.gatttool_client.write_characteristic(
                op_tx['value_handle'], cmd, response=False
            )
            
            await asyncio.sleep(2)
            
            self.detected_protocol = "chessnut_air"
            self.write_handle = op_tx['value_handle']
            self.read_handle = fen_rx['value_handle']
            log.info("Chessnut Air protocol active")
            return True
        
        # Probe for Pegasus
        log.info("Probing for DGT Pegasus protocol...")
        peg_rx = self.gatttool_client.find_characteristic_by_uuid(self.pegasus.rx_uuid)
        peg_tx = self.gatttool_client.find_characteristic_by_uuid(self.pegasus.tx_uuid)
        
        if peg_rx and peg_tx:
            log.info(f"Found Pegasus RX (write): handle {peg_rx['value_handle']:04x}")
            log.info(f"Found Pegasus TX (notify): handle {peg_tx['value_handle']:04x}")
            
            await self.gatttool_client.enable_notifications(
                peg_tx['value_handle'], self.pegasus.gatttool_notification_handler
            )
            
            # Send probe commands
            for probe_cmd in self.pegasus.get_probe_commands():
                log.info(f"Sending Pegasus probe: {probe_cmd.hex()}")
                await self.gatttool_client.write_characteristic(
                    peg_rx['value_handle'], probe_cmd, response=False
                )
                await asyncio.sleep(0.5)
            
            await asyncio.sleep(2)
            
            self.detected_protocol = "pegasus"
            self.write_handle = peg_rx['value_handle']
            self.read_handle = peg_tx['value_handle']
            log.info("DGT Pegasus protocol active")
            return True
        
        log.error("No supported protocol detected")
        return False
    
    async def run(self):
        """Run the relay loop."""
        log.info("Running gatttool relay loop (Ctrl+C to exit)...")
        
        last_periodic = asyncio.get_event_loop().time()
        
        while self._running and self.gatttool_client and self.gatttool_client.is_connected:
            await asyncio.sleep(0.1)
            
            # Send periodic commands
            now = asyncio.get_event_loop().time()
            if now - last_periodic > 5.0:
                last_periodic = now
                
                if self.detected_protocol == "millennium" and self.write_handle:
                    s_cmd = self.millennium.encode_command(self.millennium.get_status_command())
                    log.info("Sending periodic Millennium S command")
                    await self.gatttool_client.write_characteristic(
                        self.write_handle, s_cmd, response=False
                    )
                elif self.detected_protocol == "chessnut_air" and self.write_handle:
                    cmd = self.chessnut.get_enable_reporting_command()
                    log.info("Sending periodic Chessnut enable reporting")
                    await self.gatttool_client.write_characteristic(
                        self.write_handle, cmd, response=False
                    )
                elif self.detected_protocol == "pegasus" and self.write_handle:
                    cmd = self.pegasus.get_board_command()
                    log.info("Sending periodic Pegasus board request")
                    await self.gatttool_client.write_characteristic(
                        self.write_handle, cmd, response=False
                    )
    
    async def disconnect(self):
        """Disconnect from the device."""
        if self.gatttool_client:
            await self.gatttool_client.disconnect()
    
    def stop(self):
        """Signal the client to stop."""
        self._running = False
        if self.gatttool_client:
            self.gatttool_client.stop()


async def async_main(device_name: str, use_gatttool: bool = False, device_address: str | None = None):
    """Async main entry point.
    
    Args:
        device_name: Name of the BLE device to connect to
        use_gatttool: If True, use gatttool backend instead of bleak
        device_address: Optional MAC address to skip scanning
    """
    client = None
    fallback_to_gatttool = False
    
    if use_gatttool:
        log.info("Using gatttool backend (requested)")
        client = GatttoolRelayClient(device_name)
        if device_address:
            client.device_address = device_address
            log.info(f"Using provided address: {device_address}")
    else:
        log.info("Using bleak backend")
        client = BLERelayClient(device_name)
    
    # Set up signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, client.stop)
    
    try:
        if await client.connect():
            await client.run()
        else:
            # Check if bleak connected but found no services (BlueZ GATT bug)
            if not use_gatttool and hasattr(client, 'ble_client') and client.ble_client.is_connected:
                services = client.ble_client.services
                service_count = len(list(services)) if services else 0
                if service_count == 0:
                    log.warning("BlueZ connected but no GATT services discovered")
                    log.info("This is a known BlueZ issue with some dual-mode devices")
                    log.info("Falling back to gatttool backend...")
                    fallback_to_gatttool = True
                    
                    # Get the address from the bleak client for gatttool
                    if not device_address and client.ble_client.device_address:
                        device_address = client.ble_client.device_address
            
            if not fallback_to_gatttool:
                log.error("Failed to connect or detect protocol")
    finally:
        await client.disconnect()
    
    # Fallback to gatttool if bleak failed due to BlueZ GATT issue
    if fallback_to_gatttool and device_address:
        log.info("=" * 50)
        log.info("Attempting gatttool fallback...")
        log.info("=" * 50)
        
        # Power cycle the Bluetooth adapter to clear any stale state from bleak
        log.info("Power cycling Bluetooth adapter...")
        import subprocess
        try:
            subprocess.run(['sudo', 'rfkill', 'block', 'bluetooth'], 
                          capture_output=True, timeout=5)
            await asyncio.sleep(2)
            subprocess.run(['sudo', 'rfkill', 'unblock', 'bluetooth'], 
                          capture_output=True, timeout=5)
            await asyncio.sleep(2)
            subprocess.run(['sudo', 'systemctl', 'restart', 'bluetooth'], 
                          capture_output=True, timeout=10)
            await asyncio.sleep(3)
            log.info("Bluetooth adapter reset complete")
        except Exception as e:
            log.warning(f"Failed to reset Bluetooth adapter: {e}")
        
        client = GatttoolRelayClient(device_name)
        client.device_address = device_address
        
        # Re-register signal handlers for new client
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, client.stop)
        
        try:
            if await client.connect():
                await client.run()
            else:
                log.error("Gatttool fallback also failed")
        finally:
            await client.disconnect()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='BLE Relay Tool - Auto-detects Millennium, Chessnut Air, or DGT Pegasus protocol',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This tool connects to a BLE chess board and auto-detects the protocol
(Millennium, Chessnut Air, or DGT Pegasus) by probing with initial commands.

For dual-mode devices where bleak fails, use --use-gatttool to use the
gatttool backend instead.

Requirements:
    pip install bleak (for bleak backend)
    gatttool (for gatttool backend, part of bluez package)
        """
    )
    parser.add_argument(
        '--device-name',
        default='Chessnut Air',
        help='Name of the BLE device to connect to (default: Chessnut Air)'
    )
    parser.add_argument(
        '--use-gatttool',
        action='store_true',
        help='Use gatttool backend instead of bleak (useful for dual-mode devices)'
    )
    parser.add_argument(
        '--clear-cache',
        action='store_true',
        help='Clear BlueZ cache for the device before connecting'
    )
    parser.add_argument(
        '--device-address',
        help='MAC address of the device (used with --clear-cache to clear cache before scanning)'
    )
    args = parser.parse_args()
    
    log.info("BLE Relay Tool")
    log.info("=" * 50)
    
    # Check bleak version
    try:
        import bleak
        log.info(f"bleak version: {bleak.__version__}")
    except AttributeError:
        log.info("bleak version: unknown")
    
    # Clear cache if requested
    if args.clear_cache:
        if args.device_address:
            log.info(f"Clearing BlueZ cache for device: {args.device_address}")
            clear_bluez_device_cache(args.device_address)
        else:
            log.info("Clearing all BlueZ device cache...")
            import glob
            cache_pattern = "/var/lib/bluetooth/*/cache/*"
            cache_files = glob.glob(cache_pattern)
            if cache_files:
                for cache_file in cache_files:
                    try:
                        os.remove(cache_file)
                        log.info(f"Removed: {cache_file}")
                    except PermissionError:
                        log.warning(f"Permission denied: {cache_file} (try running with sudo)")
                    except Exception as e:
                        log.warning(f"Failed to remove {cache_file}: {e}")
                
                # Restart bluetooth
                import subprocess
                try:
                    log.info("Restarting bluetooth service...")
                    subprocess.run(["sudo", "systemctl", "restart", "bluetooth"], 
                                   capture_output=True, timeout=10)
                    import time
                    time.sleep(2)
                    log.info("Bluetooth service restarted")
                except Exception as e:
                    log.warning(f"Failed to restart bluetooth: {e}")
            else:
                log.info("No cache files found")
    
    # Run the async main
    try:
        asyncio.run(async_main(
            args.device_name, 
            use_gatttool=args.use_gatttool,
            device_address=args.device_address
        ))
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as e:
        log.error(f"Fatal error: {e}")
        import traceback
        log.error(traceback.format_exc())
        sys.exit(1)
    
    log.info("Exiting")


if __name__ == "__main__":
    main()
