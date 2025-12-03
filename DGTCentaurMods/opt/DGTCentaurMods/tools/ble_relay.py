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
    """BLE relay client that auto-detects Millennium, Chessnut Air, or Pegasus protocol.
    
    This is a generic client that delegates protocol-specific logic to
    the protocol client classes.
    """
    
    def __init__(
        self,
        device_name: str = "Chessnut Air",
        stale_connection_mode: str = "disconnect"
    ):
        """Initialize the BLE relay client.
        
        Args:
            device_name: Name of the BLE device to connect to
            stale_connection_mode: How to handle stale connections from previous
                                   sessions. Options:
                                   - "disconnect": Disconnect stale connections (default)
                                   - "reuse": Attempt to reuse existing connections
        """
        self.device_name = device_name
        self.ble_client = BLEClient(stale_connection_mode=stale_connection_mode)
        self.detected_protocol: str | None = None
        self._running = True
        
        # Protocol clients - protocol-specific logic is delegated to these
        self.millennium = MillenniumClient()
        self.chessnut = ChessnutClient()
        self.pegasus = PegasusClient()
        
        # The active protocol client (set after detection)
        self._active_client = None
    
    async def connect(self) -> bool:
        """Connect to the device and auto-detect protocol.
        
        Returns:
            True if connection and protocol detection successful, False otherwise
        """
        if not await self.ble_client.scan_and_connect(self.device_name):
            return False
        
        # Log discovered services
        self.ble_client.log_services()
        
        # Try each protocol client in order
        protocol_clients = [
            ("millennium", self.millennium),
            ("chessnut_air", self.chessnut),
            ("pegasus", self.pegasus),
        ]
        
        for protocol_name, client in protocol_clients:
            log.info(f"Probing for {protocol_name} protocol...")
            if await client.probe_with_bleak(self.ble_client):
                self.detected_protocol = protocol_name
                self._active_client = client
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
        
            # Send periodic commands via the active client
            if self._active_client:
                await self._active_client.send_periodic_commands_bleak(self.ble_client)
    
    def stop(self):
        """Signal the client to stop."""
        self._running = False
        self.ble_client.stop()


class GatttoolRelayClient:
    """BLE relay client using gatttool backend.
    
    Useful for devices where bleak fails due to BlueZ dual-mode handling.
    This is a generic client that delegates protocol-specific logic to
    the protocol client classes.
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
        self._running = True
        
        # Protocol clients - protocol-specific logic is delegated to these
        self.millennium = MillenniumClient()
        self.chessnut = ChessnutClient()
        self.pegasus = PegasusClient()
        
        # The active protocol client (set after detection)
        self._active_client = None
    
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
        """Connect to the device using gatttool and auto-detect protocol.
        
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
        
        # Try each protocol client in order
        protocol_clients = [
            ("millennium", self.millennium),
            ("chessnut_air", self.chessnut),
            ("pegasus", self.pegasus),
        ]
        
        for protocol_name, client in protocol_clients:
            log.info(f"Probing for {protocol_name} protocol...")
            if await client.probe_with_gatttool(self.gatttool_client):
                self.detected_protocol = protocol_name
                self._active_client = client
                return True
        
        log.error("No supported protocol detected")
        return False
    
    async def run(self):
        """Run the relay loop."""
        log.info("Running gatttool relay loop (Ctrl+C to exit)...")
        
        last_periodic = asyncio.get_event_loop().time()
        
        while self._running and self.gatttool_client and self.gatttool_client.is_connected:
            await asyncio.sleep(0.1)
            
            # Send periodic commands every 10 seconds
            now = asyncio.get_event_loop().time()
            if now - last_periodic > 10.0:
                last_periodic = now
                
                if self._active_client:
                    await self._active_client.send_periodic_commands(self.gatttool_client)
    
    async def disconnect(self):
        """Disconnect from the device."""
        if self.gatttool_client:
            await self.gatttool_client.disconnect()
    
    def stop(self):
        """Signal the client to stop."""
        self._running = False
        if self.gatttool_client:
            self.gatttool_client.stop()


async def async_main(
    device_name: str,
    use_gatttool: bool = False,
    device_address: str | None = None,
    stale_connection_mode: str = "disconnect"
):
    """Async main entry point.
    
    Args:
        device_name: Name of the BLE device to connect to
        use_gatttool: If True, use gatttool backend instead of bleak
        device_address: Optional MAC address to skip scanning
        stale_connection_mode: How to handle stale connections ("disconnect" or "reuse")
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
        log.info(f"Stale connection mode: {stale_connection_mode}")
        client = BLERelayClient(device_name, stale_connection_mode=stale_connection_mode)
    
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
    parser.add_argument(
        '--reuse-connection',
        action='store_true',
        help='Attempt to reuse existing BLE connections instead of disconnecting them'
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
    
    # Determine stale connection mode
    stale_mode = "reuse" if args.reuse_connection else "disconnect"
    
    # Run the async main
    try:
        asyncio.run(async_main(
            args.device_name, 
            use_gatttool=args.use_gatttool,
            device_address=args.device_address,
            stale_connection_mode=stale_mode
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
