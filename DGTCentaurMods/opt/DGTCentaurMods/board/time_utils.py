"""
Time utility functions for DGT Centaur board communication.

This module provides functions for extracting, decoding, and formatting
time information from board payloads.
"""

# Constants
SUBSEC_DIVISOR = 256.0  # 1 tick = 1/256 s


def _extract_time_from_payload(payload: bytes) -> bytes:
    """
    Extract time bytes prefix from payload.
    
    Returns all bytes before the first event marker (0x40 for lift, 0x41 for place).
    The board payload layout is:
        [optional time bytes ...] [events ...]
    where events are pairs of bytes starting with 0x40 or 0x41,
    followed by the field hex.
    
    Args:
        payload: The raw payload bytes from the board
        
    Returns:
        Time bytes (all bytes before first 0x40/0x41 marker)
    """
    out = bytearray()
    for b in payload:
        if b in (0x40, 0x41):
            break
        out.append(b)
    return bytes(out)


def decode_time(payload: bytes) -> float:
    """
    Decode a time packet from payload bytes.
    
    This function first extracts time bytes from the payload (removing event markers),
    then decodes them according to the time encoding rules.
    
    Rules:
      - Extract time bytes using extract_time_from_payload (removes event markers)
      - Search for b'\x7c\x03' header marker in the time bytes
      - If header marker found, treat bytes after it as time bytes and add 1 second
      - Otherwise, the whole extracted time bytes are used
      - Time bytes are hierarchical: b0=subsec (1/256 s), b1=sec, b2=min, b3=hour
    
    Args:
        payload: The raw payload bytes from the board
        
    Returns:
        Time value in seconds (float)
    """
    # Extract time bytes (removes event markers)
    time_bytes = _extract_time_from_payload(payload)
    
    if len(time_bytes) == 0:
        return 0.0

    # Search for header marker \x7c\x03
    header_marker = b"\x7c\x03"
    result = 0.0
    
    if len(time_bytes) >= 2:
        # Find the header marker in the time bytes
        try:
            marker_pos = time_bytes.index(header_marker)
            # Take bytes after the marker
            time_bytes = time_bytes[marker_pos + len(header_marker):]
            # Add 1 second if header marker is present
            result = 1.0
        except ValueError:
            # Header marker not found, use entire time bytes as-is
            pass

    # Pull fields if present
    b0 = time_bytes[0] if len(time_bytes) > 0 else 0
    b1 = time_bytes[1] if len(time_bytes) > 1 else 0
    b2 = time_bytes[2] if len(time_bytes) > 2 else 0
    b3 = time_bytes[3] if len(time_bytes) > 3 else 0

    result += (b0 / SUBSEC_DIVISOR) + b1 + (60 * b2) + (3600 * b3)
    
    return result


def format_time_display(time_in_seconds: float) -> str:
    """
    Format time in seconds as human-readable time string.
    
    Args:
        time_in_seconds: Time value in seconds (float)
    
    Returns:
        Formatted time string:
        - ss.ss format if < 60 seconds (e.g., "45.23")
        - mm:ss.ss format if >= 60 seconds and < 3600 seconds (e.g., "5:23.45")
        - hh:mm:ss.ss format if >= 3600 seconds (e.g., "1:05:23.45")
    """
    if time_in_seconds < 60:
        # ss.ss format
        return f"{time_in_seconds:.2f}"
    elif time_in_seconds < 3600:
        # mm:ss.ss format
        minutes = int(time_in_seconds // 60)
        seconds = time_in_seconds % 60
        return f"{minutes}:{seconds:05.2f}"
    else:
        # hh:mm:ss.ss format
        hours = int(time_in_seconds // 3600)
        remaining = time_in_seconds % 3600
        minutes = int(remaining // 60)
        seconds = remaining % 60
        return f"{hours}:{minutes:02d}:{seconds:05.2f}"


# For backward compatibility, provide private versions that point to public ones
_decode_time = decode_time
_format_time_display = format_time_display
