# DGTCentaurMods/ui/input_adapters.py
from typing import Optional
import time
import logging
from DGTCentaurMods.board import board as b

# Map the Centaur hex signatures to high-level actions.
# We format addr1/addr2 dynamically because the controller can change them.
def poll_actions_from_board() -> Optional[str]:
    try:
        # Clear any existing data first
        try:
            b._ser_read(100)  # Clear buffer
        except Exception as e:
            logging.debug(f"Failed to clear buffer: {e}")
            return None
        
        # Ask for key events - don't change timeout to avoid port reconfiguration
        b.sendPacket(b'\x94', b'')
        resp = b._ser_read(256)  # Use default timeout to avoid port locking issues
        if not resp:
            return None

        hx = resp.hex()[:-2]  # drop checksum
        a1 = f"{b.addr1:02x}"
        a2 = f"{b.addr2:02x}"

        # Debug: log the actual response for analysis (but limit output)
        if hx and len(hx) > 10:  # Only log if we got a meaningful response
            # Truncate very long responses to avoid spam
            display_hx = hx[:100] + "..." if len(hx) > 100 else hx
            print(f"DEBUG: Response: {display_hx}")

        # Special case: UP button might only send board state (870006065063)
        if hx == f"8700{a1}0{a2}063":
            print("DEBUG: Detected UP key (board state only)")
            return "UP"

        # Look for specific button patterns from the debug output
        if f"b10011{a1}{a2}00140a0508000000007d3c" in hx:
            print("DEBUG: Detected UP button")
            return "UP"
        elif f"b10010{a1}{a2}00140a05020000000061" in hx:
            print("DEBUG: Detected DOWN button")
            return "DOWN"
        elif f"b10011{a1}{a2}00140a0510000000007d17" in hx:
            print("DEBUG: Detected SELECT button")
            return "SELECT"
        elif f"b10011{a1}{a2}00140a0501000000007d47" in hx:
            print("DEBUG: Detected BACK button")
            return "BACK"
        
        # Fallback: look for simpler patterns
        if f"b100{a1}0{a2}0d" in hx:
            print("DEBUG: Detected key press (0d pattern) - treating as SELECT")
            return "SELECT"
        
        # Look for other patterns
        if f"b100{a1}0{a2}" in hx:
            # Extract the last few characters to determine the key
            key_part = hx[hx.rfind(f"b100{a1}0{a2}"):]
            if len(key_part) >= 12:
                key_code = key_part[-2:]
                print(f"DEBUG: Detected key code: {key_code}")
                
                # Map based on observed patterns
                if key_code == "0d":
                    return "SELECT"
                elif key_code == "3c":
                    return "UP"
                elif key_code == "61":
                    return "DOWN"
                elif key_code == "17":
                    return "SELECT"
                elif key_code == "47":
                    return "BACK"

        return None
    except Exception as e:
        # Never blow up the UI loop on a transient read error
        logging.debug(f"Error in poll_actions_from_board: {e}")
        time.sleep(0.01)
        return None
