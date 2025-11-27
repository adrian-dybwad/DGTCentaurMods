# Millennium Game
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log
import chess


class PacketParser:
    """Parses packets with odd parity framing and XOR CRC checksum.
    
    Packet format:
    - All payload characters are ASCII (0-127)
    - Odd parity bit is added on top (MSB) on the wire
    - Message format: <ASCII payload> <CRC_hi><CRC_lo>
    - CRC is 1-byte XOR of all ASCII characters in payload
    - CRC is sent as two ASCII hex digits (also with odd parity on wire)
    """
    
    def __init__(self):
        """Initialize the packet parser."""
        self.buffer = []
        self.state = "WAITING_FOR_START"
    
    def _strip_parity(self, byte_value):
        """Strip odd parity bit from byte (remove MSB if set for parity).
        
        Args:
            byte_value: Raw byte value with possible odd parity bit
            
        Returns:
            ASCII character value (0-127) without parity bit
        """
        # Check if MSB is set (parity bit)
        if byte_value & 0x80:
            # Remove parity bit
            return byte_value & 0x7F
        return byte_value
    
    def _count_ones(self, byte_value):
        """Count the number of set bits in a byte.
        
        Args:
            byte_value: Byte value to count bits in
            
        Returns:
            Number of set bits
        """
        count = 0
        while byte_value:
            count += byte_value & 1
            byte_value >>= 1
        return count
    
    def _verify_parity(self, byte_value):
        """Verify that byte has odd parity (MSB set if needed).
        
        Args:
            byte_value: Byte value to verify
            
        Returns:
            True if byte has odd parity, False otherwise
        """
        # Count bits in lower 7 bits
        bit_count = self._count_ones(byte_value & 0x7F)
        # Check if parity bit matches
        has_parity_bit = (byte_value & 0x80) != 0
        # Odd parity: total bits (including parity) should be odd
        total_bits = bit_count + (1 if has_parity_bit else 0)
        return (total_bits % 2) == 1
    
    def _calculate_crc(self, payload):
        """Calculate XOR CRC of ASCII payload.
        
        Args:
            payload: List of ASCII character values (0-127)
            
        Returns:
            CRC value as integer (0-255)
        """
        if not payload:
            return 0
        crc = 0
        for char in payload:
            crc ^= char
        return crc
    
    def _hex_char_to_value(self, char_value):
        """Convert ASCII hex character to integer value.
        
        Args:
            char_value: ASCII character value (0-127) as integer
            
        Returns:
            Integer value (0-15) or None if invalid hex char
        """
        if 48 <= char_value <= 57:  # '0' to '9'
            return char_value - 48
        elif 65 <= char_value <= 70:  # 'A' to 'F'
            return char_value - 65 + 10
        elif 97 <= char_value <= 102:  # 'a' to 'f'
            return char_value - 97 + 10
        return None
    
    def receive_byte(self, byte_value):
        """Receive one byte and parse packet.
        
        Args:
            byte_value: Raw byte value from wire (with possible odd parity)
            
        Returns:
            Tuple (packet_type, payload, is_complete) where:
            - packet_type: First byte of payload (message type) or None
            - payload: List of ASCII character values or None
            - is_complete: True if packet is complete and valid, False otherwise
        """
        try:
            # Strip parity bit to get ASCII character
            ascii_char = self._strip_parity(byte_value)
            
            # Verify parity is correct
            if not self._verify_parity(byte_value):
                log.warning(f"[Millennium.PacketParser] Invalid parity for byte 0x{byte_value:02X}")
            
            # Add to buffer
            self.buffer.append(ascii_char)
            
            # Need at least 3 bytes: type + CRC_hi + CRC_lo
            if len(self.buffer) < 3:
                return (None, None, False)
            
            # Check if buffer is too large (likely lost/invalid packet)
            # Reset if buffer exceeds reasonable maximum (e.g., 1000 bytes)
            if len(self.buffer) > 1000:
                log.warning(f"[Millennium.PacketParser] Buffer too large ({len(self.buffer)} bytes), resetting")
                self.buffer = []
                return (None, None, False)
            
            # Last two bytes should be CRC hex digits
            crc_hi_char = self.buffer[-2]
            crc_lo_char = self.buffer[-1]
            
            # Convert CRC hex chars to values
            crc_hi = self._hex_char_to_value(crc_hi_char)
            crc_lo = self._hex_char_to_value(crc_lo_char)
            
            if crc_hi is None or crc_lo is None:
                # Not valid hex, keep accumulating (don't reset)
                return (None, None, False)
            
            # Calculate received CRC from the hex digits
            received_crc = (crc_hi << 4) | crc_lo
            
            # Extract payload (everything except last 2 CRC bytes)
            payload = self.buffer[:-2]
            
            # Need at least 1 byte in payload (the packet type)
            if len(payload) < 1:
                return (None, None, False)
            
            # Calculate expected CRC by XORing all payload bytes
            expected_crc = self._calculate_crc(payload)
            
            # Verify CRC
            if received_crc != expected_crc:
                # CRC doesn't match, but don't reset - keep accumulating
                # The next byte might be part of the actual CRC
                # Only log if buffer is getting large (to avoid spam)
                #if len(self.buffer) > 10:
                #    log.debug(f"[Millennium.PacketParser] CRC check failed: received=0x{received_crc:02X}, expected=0x{expected_crc:02X}, buffer_len={len(self.buffer)}")
                return (None, None, False)
            
            # CRC matches! Packet is valid
            packet_type = payload[0] if payload else None
            log.info(f"[Millennium.PacketParser] Valid packet: type=0x{packet_type:02X} ({chr(packet_type) if packet_type and 32 <= packet_type < 127 else '?'}), payload_len={len(payload)}, crc=0x{received_crc:02X}")
            
            # Create a copy of payload before resetting buffer
            result_payload = payload.copy()
            
            # Reset buffer for next packet
            self.buffer = []
            
            return (packet_type, result_payload, True)
            
        except Exception as e:
            log.error(f"[Millennium.PacketParser] Error parsing byte 0x{byte_value:02X}: {e}")
            import traceback
            traceback.print_exc()
            self.buffer = []
            return (None, None, False)
    
    def reset(self):
        """Reset parser state."""
        self.buffer = []
        self.state = "WAITING_FOR_START"


def _odd_parity(byte_value):
    """Calculate odd parity for a byte and set MSB if needed.
    
    Sets MSB only if the byte has even parity (even number of set bits),
    to make the total parity odd.
    
    Args:
        byte_value: Byte value (0-127, ASCII character)
        
    Returns:
        Byte value with odd parity bit set in MSB if needed
    """
    # Ensure we only work with 7-bit values
    byte = byte_value & 127
    # Count set bits in the 7-bit value
    bit_count = 0
    temp = byte
    while temp:
        bit_count += temp & 1
        temp >>= 1
    # If even number of bits, set parity bit (MSB) to make it odd
    # If odd number of bits, don't set parity bit (already odd)
    if bit_count % 2 == 0:
        return byte_value | 128
    else:
        return byte_value & 127


def encode_millennium_command(command_text):
    """Encode a Millennium protocol command with odd parity and CRC.
    
    This function encodes a command string into the Millennium protocol format:
    - Each ASCII character gets odd parity added (MSB set if needed)
    - CRC is calculated as XOR of all ASCII characters
    - CRC is appended as two ASCII hex digits (also with odd parity)
    
    Args:
        command_text: ASCII string command to encode
        
    Returns:
        bytearray: Encoded bytes with odd parity and CRC
        
    Example:
        encoded = encode_millennium_command("V")
        log.info(f"Encoded command: {encoded.hex()}")
    """
    log.info(f"[Millennium] Encoding command: {command_text}")
    
    # Calculate XOR CRC of all ASCII characters
    crc = 0
    for char in command_text:
        crc ^= ord(char)
    
    # Convert CRC to hex string (e.g., "4D")
    crc_hex = f"{crc:02X}"
    crc_hi_char = crc_hex[0]  # First hex digit
    crc_lo_char = crc_hex[1]  # Second hex digit
    
    # Build the encoded bytearray
    encoded = bytearray()
    
    # Add command bytes with odd parity
    for char in command_text:
        encoded.append(_odd_parity(ord(char)))
    
    # Add CRC hex digits with odd parity
    encoded.append(_odd_parity(ord(crc_hi_char)))
    encoded.append(_odd_parity(ord(crc_lo_char)))
    
    #log.info(f"[Millennium] Encoded command (hex): {encoded.hex()}")
    log.info(f"[Millennium] Encoded command (bytes): {' '.join(f'{b:02x}' for b in encoded)}")
    
    return encoded


def _key_callback(key):
    """Handle key press events from the board.
    
    Args:
        key: The key that was pressed (board.Key enum value)
    """
    try:
        log.info(f"[Millennium] Key event: {key}")
    except Exception as e:
        log.error(f"[Millennium] Error in key callback: {e}")
        import traceback
        traceback.print_exc()


def _field_callback(piece_event, field, time_in_seconds):
    """Handle field events (piece lift/place) from the board.
    
    Args:
        piece_event: 0 for LIFT, 1 for PLACE
        field: Chess square index (0=a1, 63=h8)
        time_in_seconds: Time from packet
    """
    try:
        event_type = "LIFT" if piece_event == 0 else "PLACE"
        field_name = chess.square_name(field)
        log.info(f"[Millennium] Field event: {event_type} on field {field} ({field_name}), time={time_in_seconds}")
    except Exception as e:
        log.error(f"[Millennium] Error in field callback: {e}")
        import traceback
        traceback.print_exc()


def handle_s(payload):
    """Handle packet type 'S' - full board status.
    
    S / s – full board status (64 chars)
    
    Args:
        payload: List of ASCII character values in the payload
    """
    #log.info(f"[Millennium] Handling S packet: payload={payload}")
    encode_millennium_command("s")


def handle_l(payload):
    """Handle packet type 'L' - LED control.
    
    L / l – LED control (slot time + 81 LED codes)
    
    Args:
        payload: List of ASCII character values in the payload
    """
    #log.info(f"[Millennium] Handling L packet: payload={payload}")
    encode_millennium_command("l")


def handle_x(payload):
    """Handle packet type 'X' - all LEDs off.
    
    X / x – all LEDs off
    
    Args:
        payload: List of ASCII character values in the payload
    """
    #log.info(f"[Millennium] Handling X packet: payload={payload}")
    encode_millennium_command("x")


def handle_t(payload):
    """Handle packet type 'T' - reset.
    
    T – reset (no reply)
    
    Args:
        payload: List of ASCII character values in the payload
    """
    #log.info(f"[Millennium] Handling T packet: payload={payload}")
    # T command has no reply, so we don't encode a response
    #encode_millennium_command("t")


def handle_v(payload):
    """Handle packet type 'V' - firmware version.
    
    V / v – firmware version
    
    Args:
        payload: List of ASCII character values in the payload
    """
    #log.info(f"[Millennium] Handling V packet: payload={payload}")
    encode_millennium_command("v")


def handle_w(payload):
    """Handle packet type 'W' - E²ROM config write.
    
    W / w – E²ROM config
    
    Args:
        payload: List of ASCII character values in the payload
    """
    #log.info(f"[Millennium] Handling W packet: payload={payload}")
    encode_millennium_command("w")


def handle_r(payload):
    """Handle packet type 'R' - E²ROM config read.
    
    R / r – E²ROM config
    
    Args:
        payload: List of ASCII character values in the payload
    """
    #log.info(f"[Millennium] Handling R packet: payload={payload}")
    encode_millennium_command("r")


def handle_i(payload):
    """Handle packet type 'I' - identity.
    
    I / i – identity
    
    Args:
        payload: List of ASCII character values in the payload
    """
    #log.info(f"[Millennium] Handling I packet: payload={payload}")
    encode_millennium_command("i")



# Global packet parser instance
_packet_parser = PacketParser()


def receive_data(byte_value):
    """Receive one byte of data and parse packet.
    
    This function implements a packet parser that handles:
    - Odd parity stripping (MSB parity bit)
    - ASCII payload accumulation
    - XOR CRC verification (last 2 ASCII hex digits)
    
    When a valid packet is received, it automatically calls the packet handler.
    
    Args:
        byte_value: Raw byte value from wire (with possible odd parity bit)
        
    Returns:
        Tuple (packet_type, payload, is_complete) where:
        - packet_type: First byte of payload (message type) as integer, or None
        - payload: List of ASCII character values (0-127), or None
        - is_complete: True if packet is complete and CRC valid, False otherwise
        
    Example:
        # Receive bytes one at a time
        for byte in byte_stream:
            packet_type, payload, is_complete = receive_data(byte)
            if is_complete:
                # Packet handler is automatically called
                log.info(f"Received packet type {packet_type}, payload: {payload}")
    """
    packet_type, payload, is_complete = _packet_parser.receive_byte(byte_value)
    
    # Call packet handler when a valid packet is received
    if is_complete:
        packet_type_str = chr(packet_type) if packet_type and 32 <= packet_type < 127 else f"0x{packet_type:02X}"
        payload_str = ''.join(chr(b) if 32 <= b < 127 else f'\\x{b:02x}' for b in payload) if payload else "None"
        log.info(f"[Millennium.receive_data] Complete packet: type={packet_type_str} (0x{packet_type:02X}), payload_len={len(payload) if payload else 0}, payload={payload_str}")
        try:
            # Convert packet_type to character for comparison
            packet_char = chr(packet_type) if packet_type is not None else None
            
            if packet_char == 'X':
                handle_x(payload)
            elif packet_char == 'L':
                handle_l(payload)
            elif packet_char == 'R':
                handle_r(payload)
            elif packet_char == 'W':
                handle_w(payload)
            elif packet_char == 'T':
                handle_t(payload)
            elif packet_char == 'V':
                handle_v(payload)
            elif packet_char == 'I':
                handle_i(payload)
            elif packet_char == 'S':
                handle_s(payload)
            else:
                log.debug(f"[Millennium] Unhandled packet type: {packet_char} (0x{packet_type:02X})")
        except Exception as e:
            log.error(f"[Millennium] Error in packet handler: {e}")
            import traceback
            traceback.print_exc()
    

def reset_parser():
    """Reset the packet parser state.
    
    Clears any accumulated buffer and resets parser to initial state.
    Useful when starting a new communication session or recovering from errors.
    """
    _packet_parser.reset()


def subscribe():
    """Subscribe to board events and start logging."""
    try:
        log.info("[Millennium] Subscribing to board events")
        board.subscribeEvents(_key_callback, _field_callback, timeout=100000)
        log.info("[Millennium] Successfully subscribed to board events")
    except Exception as e:
        log.error(f"[Millennium] Failed to subscribe to board events: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    subscribe()
    # Keep the script running
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("[Millennium] Exiting...")

