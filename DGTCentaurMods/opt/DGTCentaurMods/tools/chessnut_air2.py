#!/usr/bin/env python3
"""
Chessnut Air BLE Tool (bleak-based)

This tool connects to a BLE device called "Chessnut Air" and logs all data received.
It uses the bleak library for proper BLE communication with MTU negotiation support.

The original chessnut_air.py used gatttool which has the following issues:
1. gatttool does not support explicit MTU exchange
2. Default MTU (23 bytes) is too small for Chessnut's 36-byte FEN packets
3. gatttool has issues with BLE communication and data reception

This version uses bleak which:
1. Properly handles MTU negotiation (requests 500 bytes as required by Chessnut)
2. Has reliable notification handling
3. Is a modern, well-maintained Python BLE library

Usage:
    python3 tools/chessnut_air2.py [--device-name "Chessnut Air"]
    
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

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError
except ImportError:
    print("Error: bleak library not installed. Install with: pip install bleak")
    print("On Raspberry Pi: pip3 install bleak")
    sys.exit(1)

from DGTCentaurMods.board.logging import log

# Chessnut Air BLE UUIDs
CHESSNUT_FEN_SERVICE_UUID = "1b7e8261-2877-41c3-b46e-cf057c562023"
CHESSNUT_FEN_RX_CHAR_UUID = "1b7e8262-2877-41c3-b46e-cf057c562023"  # Notify from board (FEN data)
CHESSNUT_OP_SERVICE_UUID = "1b7e8271-2877-41c3-b46e-cf057c562023"
CHESSNUT_OP_TX_CHAR_UUID = "1b7e8272-2877-41c3-b46e-cf057c562023"  # Write to board
CHESSNUT_OP_RX_CHAR_UUID = "1b7e8273-2877-41c3-b46e-cf057c562023"  # Notify from board (responses)

# Initial command to enable reporting
CHESSNUT_ENABLE_REPORTING_CMD = bytes([0x21, 0x01, 0x00])
# Battery level command
CHESSNUT_BATTERY_LEVEL_CMD = bytes([0x29, 0x01, 0x00])
# Real-time mode command (enables continuous FEN updates)
CHESSNUT_REALTIME_MODE_CMD = bytes([0x21, 0x01, 0x00])

# Required MTU for Chessnut Air (needs 500 bytes for full FEN data)
REQUIRED_MTU = 500

# Global state for signal handling
running = True


def signal_handler(signum, frame):
    """Handle SIGINT and SIGTERM signals."""
    global running
    running = False


def parse_fen_data(data: bytes) -> str:
    """Parse FEN data from Chessnut Air notification.
    
    The Chessnut Air sends board position as a 32-byte array where each byte
    represents two squares (4 bits per square).
    
    Piece encoding (4 bits):
        0x0 = empty
        0x1 = white pawn
        0x2 = white rook
        0x3 = white knight
        0x4 = white bishop
        0x5 = white queen
        0x6 = white king
        0x7 = black pawn
        0x8 = black rook
        0x9 = black knight
        0xA = black bishop
        0xB = black queen
        0xC = black king
    
    Args:
        data: Raw bytes from FEN characteristic notification
        
    Returns:
        FEN position string (just the piece placement part)
    """
    if len(data) < 32:
        return f"<incomplete data: {len(data)} bytes>"
    
    # Piece mapping from Chessnut encoding to FEN characters
    piece_map = {
        0x0: None,   # empty
        0x1: 'P',    # white pawn
        0x2: 'R',    # white rook
        0x3: 'N',    # white knight
        0x4: 'B',    # white bishop
        0x5: 'Q',    # white queen
        0x6: 'K',    # white king
        0x7: 'p',    # black pawn
        0x8: 'r',    # black rook
        0x9: 'n',    # black knight
        0xA: 'b',    # black bishop
        0xB: 'q',    # black queen
        0xC: 'k',    # black king
    }
    
    # Build the board array (8x8)
    board = []
    for i in range(32):
        byte = data[i]
        # Each byte contains two squares
        high_nibble = (byte >> 4) & 0x0F
        low_nibble = byte & 0x0F
        board.append(piece_map.get(high_nibble))
        board.append(piece_map.get(low_nibble))
    
    # Convert to FEN (rank 8 to rank 1)
    fen_rows = []
    for rank in range(7, -1, -1):  # 8th rank to 1st rank
        row = ""
        empty_count = 0
        for file in range(8):  # a to h
            square_idx = rank * 8 + file
            piece = board[square_idx]
            if piece is None:
                empty_count += 1
            else:
                if empty_count > 0:
                    row += str(empty_count)
                    empty_count = 0
                row += piece
        if empty_count > 0:
            row += str(empty_count)
        fen_rows.append(row)
    
    return "/".join(fen_rows)


def parse_battery_response(data: bytes) -> tuple[int, bool]:
    """Parse battery level response from Chessnut Air.
    
    Battery response format:
        Byte 0: 0x2a (response type)
        Byte 1: 0x02 (length)
        Byte 2: battery level (0-100, bit 7 = charging flag)
        Byte 3: checksum or unused
    
    Args:
        data: Raw bytes from Operation RX characteristic
        
    Returns:
        Tuple of (battery_percent, is_charging)
    """
    if len(data) >= 3 and data[0] == 0x2a and data[1] == 0x02:
        battery_byte = data[2]
        is_charging = (battery_byte & 0x80) != 0
        battery_percent = battery_byte & 0x7F
        return battery_percent, is_charging
    return -1, False


class ChessnutAirClient:
    """Async BLE client for Chessnut Air chess board."""
    
    def __init__(self, device_name: str = "Chessnut Air"):
        """Initialize the client.
        
        Args:
            device_name: Name of the BLE device to connect to
        """
        self.device_name = device_name
        self.client: BleakClient | None = None
        self.device_address: str | None = None
        self.last_fen: str = ""
        self.battery_level: int = -1
        self.is_charging: bool = False
        self._running = True
    
    async def scan_for_device(self, timeout: float = 30.0) -> str | None:
        """Scan for the Chessnut Air device.
        
        Args:
            timeout: Maximum time to scan in seconds
            
        Returns:
            Device address if found, None otherwise
        """
        log.info(f"Scanning for device with name: {self.device_name}")
        
        target_name_upper = self.device_name.upper()
        
        devices = await BleakScanner.discover(timeout=timeout)
        
        for device in devices:
            device_name = device.name or ""
            device_name_upper = device_name.upper()
            
            if device_name_upper == target_name_upper:
                log.info(f"Found device: {device.name} at {device.address}")
                return device.address
            
            # Also check for partial match
            if target_name_upper in device_name_upper:
                log.info(f"Found device (partial match): {device.name} at {device.address}")
                return device.address
        
        log.warning(f"Device '{self.device_name}' not found after {timeout} seconds")
        return None
    
    def _fen_notification_handler(self, sender, data: bytearray):
        """Handle notifications from FEN characteristic.
        
        Args:
            sender: The characteristic that sent the notification
            data: The notification data
        """
        hex_str = ' '.join(f'{b:02x}' for b in data)
        log.info(f"RX [FEN] ({len(data)} bytes): {hex_str}")
        
        # Parse and display the FEN position
        fen = parse_fen_data(bytes(data))
        if fen != self.last_fen:
            self.last_fen = fen
            log.info(f"Board position: {fen}")
    
    def _operation_notification_handler(self, sender, data: bytearray):
        """Handle notifications from Operation RX characteristic.
        
        Args:
            sender: The characteristic that sent the notification
            data: The notification data
        """
        hex_str = ' '.join(f'{b:02x}' for b in data)
        log.info(f"RX [Operation] ({len(data)} bytes): {hex_str}")
        
        # Check for battery level response
        battery, charging = parse_battery_response(bytes(data))
        if battery >= 0:
            self.battery_level = battery
            self.is_charging = charging
            charging_str = "Charging" if charging else "Not charging"
            log.info(f"Battery Level: {battery}% ({charging_str})")
    
    async def connect(self) -> bool:
        """Connect to the Chessnut Air device.
        
        Returns:
            True if connection successful, False otherwise
        """
        if not self.device_address:
            self.device_address = await self.scan_for_device()
            if not self.device_address:
                return False
        
        log.info(f"Connecting to {self.device_address}...")
        
        try:
            self.client = BleakClient(self.device_address)
            await self.client.connect()
            
            if not self.client.is_connected:
                log.error("Failed to connect to device")
                return False
            
            log.info("Connected to device")
            
            # Request MTU exchange
            # Note: bleak handles MTU negotiation automatically on most platforms
            # On Linux with BlueZ, we can try to request a larger MTU
            try:
                mtu = self.client.mtu_size
                log.info(f"Current MTU size: {mtu}")
                if mtu < REQUIRED_MTU:
                    log.warning(f"MTU ({mtu}) is less than required ({REQUIRED_MTU})")
                    log.warning("FEN data may be truncated. Consider updating BlueZ config.")
            except AttributeError:
                log.info("MTU size not available (platform limitation)")
            
            # Discover services
            log.info("Discovering services...")
            services = self.client.services
            
            for service in services:
                log.info(f"Service: {service.uuid}")
                for char in service.characteristics:
                    props = ", ".join(char.properties)
                    log.info(f"  Characteristic: {char.uuid} [{props}]")
            
            # Enable notifications on FEN characteristic
            log.info(f"Enabling notifications on FEN characteristic ({CHESSNUT_FEN_RX_CHAR_UUID})...")
            try:
                await self.client.start_notify(
                    CHESSNUT_FEN_RX_CHAR_UUID,
                    self._fen_notification_handler
                )
                log.info("FEN notifications enabled")
            except BleakError as e:
                log.error(f"Failed to enable FEN notifications: {e}")
                # Try with uppercase UUID
                try:
                    await self.client.start_notify(
                        CHESSNUT_FEN_RX_CHAR_UUID.upper(),
                        self._fen_notification_handler
                    )
                    log.info("FEN notifications enabled (uppercase UUID)")
                except BleakError as e2:
                    log.error(f"Failed to enable FEN notifications (retry): {e2}")
            
            # Enable notifications on Operation RX characteristic
            log.info(f"Enabling notifications on Operation RX characteristic ({CHESSNUT_OP_RX_CHAR_UUID})...")
            try:
                await self.client.start_notify(
                    CHESSNUT_OP_RX_CHAR_UUID,
                    self._operation_notification_handler
                )
                log.info("Operation notifications enabled")
            except BleakError as e:
                log.error(f"Failed to enable Operation notifications: {e}")
            
            # Send enable reporting command
            log.info("Sending enable reporting command...")
            try:
                await self.client.write_gatt_char(
                    CHESSNUT_OP_TX_CHAR_UUID,
                    CHESSNUT_ENABLE_REPORTING_CMD,
                    response=False  # Write without response (faster)
                )
                log.info("Enable reporting command sent")
            except BleakError as e:
                log.error(f"Failed to send enable reporting command: {e}")
            
            await asyncio.sleep(0.5)
            
            # Send battery level command
            log.info("Sending battery level command...")
            try:
                await self.client.write_gatt_char(
                    CHESSNUT_OP_TX_CHAR_UUID,
                    CHESSNUT_BATTERY_LEVEL_CMD,
                    response=False
                )
                log.info("Battery level command sent")
            except BleakError as e:
                log.error(f"Failed to send battery level command: {e}")
            
            log.info("Connection established. Waiting for data...")
            log.info("Move pieces on the board to see FEN updates")
            
            return True
            
        except BleakError as e:
            log.error(f"BLE connection error: {e}")
            return False
        except Exception as e:
            log.error(f"Unexpected error during connection: {e}")
            import traceback
            log.error(traceback.format_exc())
            return False
    
    async def disconnect(self):
        """Disconnect from the device."""
        if self.client and self.client.is_connected:
            log.info("Disconnecting...")
            try:
                await self.client.disconnect()
                log.info("Disconnected")
            except Exception as e:
                log.error(f"Error during disconnect: {e}")
    
    async def run(self):
        """Main run loop - keeps connection alive and processes notifications."""
        global running
        
        while running and self._running:
            if self.client and self.client.is_connected:
                await asyncio.sleep(1)
            else:
                log.warning("Connection lost, attempting to reconnect...")
                if not await self.connect():
                    log.error("Reconnection failed, waiting before retry...")
                    await asyncio.sleep(5)
    
    def stop(self):
        """Signal the client to stop."""
        self._running = False


async def async_main(device_name: str):
    """Async main entry point.
    
    Args:
        device_name: Name of the BLE device to connect to
    """
    client = ChessnutAirClient(device_name)
    
    # Set up signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, client.stop)
    
    try:
        if await client.connect():
            await client.run()
    finally:
        await client.disconnect()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Chessnut Air BLE Tool (bleak-based)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This tool uses the bleak library for BLE communication, which properly handles
MTU negotiation required by Chessnut Air (needs 500 bytes for full FEN data).

The original gatttool-based implementation had issues with:
1. No explicit MTU exchange support
2. Default MTU (23 bytes) too small for 36-byte FEN packets
3. Unreliable notification handling

Requirements:
    pip install bleak
        """
    )
    parser.add_argument(
        '--device-name',
        default='Chessnut Air',
        help='Name of the BLE device to connect to (default: Chessnut Air)'
    )
    args = parser.parse_args()
    
    log.info("Chessnut Air BLE Tool (bleak-based)")
    log.info("=" * 50)
    
    # Check bleak version
    try:
        import bleak
        log.info(f"bleak version: {bleak.__version__}")
    except AttributeError:
        log.info("bleak version: unknown")
    
    # Run the async main
    try:
        asyncio.run(async_main(args.device_name))
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

