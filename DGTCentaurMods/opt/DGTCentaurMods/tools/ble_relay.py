#!/usr/bin/env python3
"""
BLE Relay Tool

This tool connects to a BLE chess board and auto-detects the protocol
(Millennium or Chessnut Air) by probing with initial commands.

It uses the generic BLEClient class for BLE communication.

Usage:
    python3 tools/ble_relay.py [--device-name "Chessnut Air"]
    
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
from DGTCentaurMods.board.ble_client import BLEClient

# Millennium ChessLink BLE UUIDs
MILLENNIUM_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
MILLENNIUM_RX_CHAR_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"  # Write commands TO device
MILLENNIUM_TX_CHAR_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"  # Read responses FROM device

# Chessnut Air BLE UUIDs
CHESSNUT_FEN_RX_CHAR_UUID = "1b7e8262-2877-41c3-b46e-cf057c562023"  # Notify from board (FEN data)
CHESSNUT_OP_TX_CHAR_UUID = "1b7e8272-2877-41c3-b46e-cf057c562023"  # Write to board
CHESSNUT_OP_RX_CHAR_UUID = "1b7e8273-2877-41c3-b46e-cf057c562023"  # Notify from board (responses)

# Chessnut Air commands
CHESSNUT_ENABLE_REPORTING_CMD = bytes([0x21, 0x01, 0x00])


def odd_par(b: int) -> int:
    """Calculate odd parity for a byte and set MSB if needed.
    
    Args:
        b: Byte value (0-127)
    
    Returns:
        Byte with odd parity (MSB set if needed)
    """
    byte = b & 127
    par = 1
    for _ in range(7):
        bit = byte & 1
        byte = byte >> 1
        par = par ^ bit
    if par == 1:
        byte = b | 128
    else:
        byte = b & 127
    return byte


def encode_millennium_command(command_text: str) -> bytes:
    """Encode a Millennium protocol command with odd parity and XOR CRC.
    
    Uses the old Millennium protocol format with odd parity encoding.
    
    Args:
        command_text: The command string to encode (e.g., "S")
    
    Returns:
        Encoded command with odd parity and CRC appended
    """
    # Calculate CRC (XOR of all ASCII characters)
    cs = 0
    for char in command_text:
        cs = cs ^ ord(char)
    
    # Convert CRC to hex string
    h = f"0x{cs:02x}"
    h1 = h[2:3]  # First hex digit
    h2 = h[3:4]  # Second hex digit
    
    # Build encoded packet with odd parity
    tosend = bytearray()
    # Encode each character in command with odd parity
    for char in command_text:
        tosend.append(odd_par(ord(char)))
    # Encode CRC hex digits with odd parity
    tosend.append(odd_par(ord(h1)))
    tosend.append(odd_par(ord(h2)))
    
    return bytes(tosend)


def decode_odd_parity(byte_with_parity: int) -> int:
    """Decode a byte with odd parity (strip MSB).
    
    Args:
        byte_with_parity: Byte with parity bit in MSB
        
    Returns:
        Decoded byte (7 bits)
    """
    return byte_with_parity & 0x7F


class BLERelayClient:
    """BLE relay client that auto-detects Millennium or Chessnut Air protocol."""
    
    def __init__(self, device_name: str = "Chessnut Air"):
        """Initialize the BLE relay client.
        
        Args:
            device_name: Name of the BLE device to connect to
        """
        self.device_name = device_name
        self.ble_client = BLEClient()
        self.detected_protocol: str | None = None
        self.write_char_uuid: str | None = None
        self.response_buffer: bytearray = bytearray()
        self._got_response = False
        self._running = True
    
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
    
    def _millennium_notification_handler(self, sender, data: bytearray):
        """Handle notifications from Millennium TX characteristic.
        
        Args:
            sender: The characteristic that sent the notification
            data: The notification data
        """
        hex_str = ' '.join(f'{b:02x}' for b in data)
        log.info(f"RX [Millennium] ({len(data)} bytes): {hex_str}")
        
        # Skip echo-backs (single byte with 0x01 prefix)
        if len(data) == 2 and data[0] == 0x01:
            log.debug(f"Ignoring echo-back: {hex_str}")
            return
        
        # Strip 0x01 prefix if present
        if len(data) > 0 and data[0] == 0x01:
            data = data[1:]
        
        if len(data) == 0:
            return
        
        # Accumulate response
        self.response_buffer.extend(data)
        
        # Decode odd parity
        decoded = bytearray()
        for b in self.response_buffer:
            decoded.append(decode_odd_parity(b))
        
        # Check for complete response
        if len(decoded) >= 3:
            first_char = chr(decoded[0]) if decoded[0] < 128 else '?'
            
            # Check for complete responses
            complete = False
            if first_char == 'x' and len(decoded) >= 3:
                complete = True
            elif first_char == 'w' and len(decoded) >= 7:
                complete = True
            elif first_char == 's' and len(decoded) >= 67:
                complete = True
            
            if complete:
                ascii_str = decoded.decode('ascii', errors='replace')
                log.info(f"RX [Millennium DECODED]: {ascii_str}")
                self.response_buffer.clear()
                self._got_response = True
                
                if self.detected_protocol is None:
                    self.detected_protocol = "millennium"
                    log.info("Detected protocol: Millennium")
    
    def _chessnut_notification_handler(self, sender, data: bytearray):
        """Handle notifications from Chessnut characteristics.
        
        Args:
            sender: The characteristic that sent the notification
            data: The notification data
        """
        hex_str = ' '.join(f'{b:02x}' for b in data)
        log.info(f"RX [Chessnut] ({len(data)} bytes): {hex_str}")
        
        self._got_response = True
        
        if self.detected_protocol is None:
            self.detected_protocol = "chessnut_air"
            log.info("Detected protocol: Chessnut Air")
    
    async def _probe_millennium(self) -> bool:
        """Probe for Millennium protocol.
        
        Returns:
            True if Millennium protocol detected, False otherwise
        """
        # Find Millennium characteristics
        rx_uuid = self._find_characteristic_uuid(MILLENNIUM_RX_CHAR_UUID)
        tx_uuid = self._find_characteristic_uuid(MILLENNIUM_TX_CHAR_UUID)
        
        if not rx_uuid or not tx_uuid:
            log.info("Millennium characteristics not found")
            return False
        
        log.info(f"Found Millennium RX: {rx_uuid}")
        log.info(f"Found Millennium TX: {tx_uuid}")
        
        # Enable notifications on TX
        if not await self.ble_client.start_notify(tx_uuid, self._millennium_notification_handler):
            log.warning("Failed to enable Millennium notifications")
            return False
        
        # Send S probe command
        self._got_response = False
        s_cmd = encode_millennium_command("S")
        log.info(f"Sending Millennium S probe: {' '.join(f'{b:02x}' for b in s_cmd)}")
        
        if not await self.ble_client.write_characteristic(rx_uuid, s_cmd, response=False):
            log.warning("Failed to send Millennium probe")
            return False
        
        # Wait for response
        for _ in range(30):  # 3 seconds
            await asyncio.sleep(0.1)
            if self._got_response:
                self.write_char_uuid = rx_uuid
                return True
        
        log.info("No Millennium response received")
        return False
    
    async def _probe_chessnut(self) -> bool:
        """Probe for Chessnut Air protocol.
        
        Returns:
            True if Chessnut Air protocol detected, False otherwise
        """
        # Find Chessnut characteristics
        tx_uuid = self._find_characteristic_uuid(CHESSNUT_OP_TX_CHAR_UUID)
        rx_uuid = self._find_characteristic_uuid(CHESSNUT_OP_RX_CHAR_UUID)
        fen_uuid = self._find_characteristic_uuid(CHESSNUT_FEN_RX_CHAR_UUID)
        
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
            await self.ble_client.start_notify(rx_uuid, self._chessnut_notification_handler)
        if fen_uuid:
            await self.ble_client.start_notify(fen_uuid, self._chessnut_notification_handler)
        
        # Send enable reporting command
        self._got_response = False
        log.info(f"Sending Chessnut enable reporting: {' '.join(f'{b:02x}' for b in CHESSNUT_ENABLE_REPORTING_CMD)}")
        
        if not await self.ble_client.write_characteristic(tx_uuid, CHESSNUT_ENABLE_REPORTING_CMD, response=False):
            log.warning("Failed to send Chessnut probe")
            return False
        
        # Wait for response
        for _ in range(30):  # 3 seconds
            await asyncio.sleep(0.1)
            if self._got_response:
                self.write_char_uuid = tx_uuid
                return True
        
        log.info("No Chessnut response received")
        return False
    
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
            log.info("Millennium protocol detected and active")
            
            # Send full initialization sequence
            init_commands = ["W0203", "W0407", "X", "S"]
            for cmd in init_commands:
                encoded = encode_millennium_command(cmd)
                log.info(f"Sending Millennium '{cmd}': {' '.join(f'{b:02x}' for b in encoded)}")
                await self.ble_client.write_characteristic(self.write_char_uuid, encoded, response=False)
                await asyncio.sleep(0.5)
            
            return True
        
        # Try Chessnut Air
        log.info("Probing for Chessnut Air protocol...")
        if await self._probe_chessnut():
            log.info("Chessnut Air protocol detected and active")
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
                s_cmd = encode_millennium_command("S")
                log.info(f"Sending periodic Millennium S command")
                await self.ble_client.write_characteristic(self.write_char_uuid, s_cmd, response=False)
            elif self.detected_protocol == "chessnut_air" and self.write_char_uuid:
                log.info(f"Sending periodic Chessnut enable reporting")
                await self.ble_client.write_characteristic(
                    self.write_char_uuid,
                    CHESSNUT_ENABLE_REPORTING_CMD,
                    response=False
                )
    
    def stop(self):
        """Signal the client to stop."""
        self._running = False
        self.ble_client.stop()


async def async_main(device_name: str):
    """Async main entry point.
    
    Args:
        device_name: Name of the BLE device to connect to
    """
    client = BLERelayClient(device_name)
    
    # Set up signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, client.stop)
    
    try:
        if await client.connect():
            await client.run()
        else:
            log.error("Failed to connect or detect protocol")
    finally:
        await client.disconnect()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='BLE Relay Tool - Auto-detects Millennium or Chessnut Air protocol',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This tool connects to a BLE chess board and auto-detects the protocol
(Millennium or Chessnut Air) by probing with initial commands.

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
    
    log.info("BLE Relay Tool")
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
