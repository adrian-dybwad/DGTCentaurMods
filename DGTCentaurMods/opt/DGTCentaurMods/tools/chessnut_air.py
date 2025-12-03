#!/usr/bin/env python3
"""
Chessnut Air BLE Tool

This tool connects to a BLE device called "Chessnut Air" and logs all data received.
It uses the generic BLEClient class for BLE communication and the ChessnutClient
for protocol handling.

Usage:
    python3 tools/chessnut_air.py [--device-name "Chessnut Air"]
    
Requirements:
    pip install bleak
"""

import argparse
import asyncio
import signal
import sys
import os

# Ensure we import the repo package first (not a system-installed copy)
try:
    REPO_OPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if REPO_OPT not in sys.path:
        sys.path.insert(0, REPO_OPT)
except Exception as e:
    print(f"Warning: Could not add repo path: {e}")

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.tools.clients.ble_client import BLEClient
from DGTCentaurMods.tools.clients.chessnut_client import ChessnutClient


class ChessnutAirTool:
    """Tool for connecting to and monitoring a Chessnut Air chess board."""
    
    def __init__(
        self,
        device_name: str = "Chessnut Air",
        stale_connection_mode: str = "disconnect"
    ):
        """Initialize the Chessnut Air tool.
        
        Args:
            device_name: Name of the BLE device to connect to
            stale_connection_mode: How to handle stale connections ("disconnect" or "reuse")
        """
        self.device_name = device_name
        self.ble_client = BLEClient(stale_connection_mode=stale_connection_mode)
        self.chessnut = ChessnutClient(
            on_fen=self._on_fen,
            on_battery=self._on_battery
        )
    
    def _on_fen(self, fen: str):
        """Handle FEN position updates.
        
        Args:
            fen: FEN position string
        """
        log.info(f"Position updated: {fen}")
    
    def _on_battery(self, percent: int, is_charging: bool):
        """Handle battery updates.
        
        Args:
            percent: Battery percentage (0-100)
            is_charging: True if charging
        """
        status = "Charging" if is_charging else "Not charging"
        log.info(f"Battery: {percent}% ({status})")
    
    async def connect(self) -> bool:
        """Connect to the Chessnut Air device.
        
        Returns:
            True if connection successful, False otherwise
        """
        if not await self.ble_client.scan_and_connect(self.device_name):
            return False
        
        # Check MTU size
        if self.ble_client.mtu_size:
            self.chessnut.check_mtu(self.ble_client.mtu_size)
        
        # Log discovered services
        self.ble_client.log_services()
        
        # Enable notifications on FEN characteristic
        log.info("Enabling notifications on FEN characteristic...")
        await self.ble_client.start_notify(
            self.chessnut.fen_uuid,
            self.chessnut.fen_notification_handler
        )
        
        # Enable notifications on Operation RX characteristic
        log.info("Enabling notifications on Operation RX characteristic...")
        await self.ble_client.start_notify(
            self.chessnut.op_rx_uuid,
            self.chessnut.operation_notification_handler
        )
        
        # Send enable reporting command
        log.info("Sending enable reporting command...")
        await self.ble_client.write_characteristic(
            self.chessnut.op_tx_uuid,
            self.chessnut.get_enable_reporting_command(),
            response=False
        )
        
        await asyncio.sleep(0.5)
        
        # Send battery level command
        log.info("Sending battery level command...")
        await self.ble_client.write_characteristic(
            self.chessnut.op_tx_uuid,
            self.chessnut.get_battery_command(),
            response=False
        )
        
        log.info("Connection established. Waiting for data...")
        log.info("Move pieces on the board to see FEN updates")
        
        return True
        
    async def disconnect(self):
        """Disconnect from the device."""
        await self.ble_client.disconnect()
    
    async def run(self):
        """Main run loop - keeps connection alive and processes notifications."""
        await self.ble_client.run_with_reconnect(self.device_name)
    
    def stop(self):
        """Signal the client to stop."""
        self.ble_client.stop()


async def async_main(device_name: str, stale_connection_mode: str = "disconnect"):
    """Async main entry point.
    
    Args:
        device_name: Name of the BLE device to connect to
        stale_connection_mode: How to handle stale connections ("disconnect" or "reuse")
    """
    tool = ChessnutAirTool(device_name, stale_connection_mode=stale_connection_mode)
        
    # Set up signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, tool.stop)
    
    try:
        if await tool.connect():
            await tool.run()
    finally:
        await tool.disconnect()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Chessnut Air BLE Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This tool uses the bleak library for BLE communication, which properly handles
MTU negotiation required by Chessnut Air (needs 500 bytes for full FEN data).

Requirements:
    pip install bleak
        """
    )
    parser.add_argument(
        '--device-name',
        default='Chessnut Air',
        help='Name of the BLE device to connect to (default: Chessnut Air)'
    )
    parser.add_argument(
        '--reuse-connection',
        action='store_true',
        help='Attempt to reuse existing BLE connections instead of disconnecting them'
    )
    args = parser.parse_args()
    
    log.info("Chessnut Air BLE Tool")
    log.info("=" * 50)
    
    # Check bleak version
    try:
        import bleak
        log.info(f"bleak version: {bleak.__version__}")
    except AttributeError:
        log.info("bleak version: unknown")
    
    # Determine stale connection mode
    stale_mode = "reuse" if args.reuse_connection else "disconnect"
    
    # Run the async main
    try:
        asyncio.run(async_main(args.device_name, stale_connection_mode=stale_mode))
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
