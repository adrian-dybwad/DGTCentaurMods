# DGTCentaurMods/ui/input_adapters.py
from typing import Optional
import time
from DGTCentaurMods.board import board as b

# Map the Centaur hex signatures to high-level actions.
# We format addr1/addr2 dynamically because the controller can change them.
def poll_actions_from_board() -> Optional[str]:
    try:
        # Clear any existing data first
        try:
            b._ser_read(100)  # Clear buffer
        except:
            pass
        
        # Ask for key events with a slightly longer timeout
        b.sendPacket(b'\x94', b'')
        resp = b._ser_read(256, timeout=0.05)  # Increased timeout
        if not resp:
            return None

        hx = resp.hex()[:-2]  # drop checksum
        a1 = f"{b.addr1:02x}"
        a2 = f"{b.addr2:02x}"

        # Debug: log the actual response for analysis
        if hx and len(hx) > 10:  # Only log if we got a meaningful response
            print(f"DEBUG: Full response: {hx}")

        # The board sends responses like: b1000606500d
        # The addresses are formatted as 060650 (0x06, 0x50)
        # We need to handle both formats: 060650 and 0650
        
        # Look for the key event marker 'b100' followed by addresses
        key_event_marker1 = f"b100{a1}{a2}"  # Format: b1000650
        key_event_marker2 = f"b100{a1}0{a2}"  # Format: b100060650 (with extra 0)
        
        key_event_start = hx.find(key_event_marker1)
        if key_event_start == -1:
            key_event_start = hx.find(key_event_marker2)
        
        if key_event_start != -1:
            # Extract the key event part
            key_event_part = hx[key_event_start:]
            print(f"DEBUG: Key event part: {key_event_part}")
            
            # The response format is much shorter: b1000606500d
            # This suggests a different protocol than expected
            # Let's try to extract the key code from the end
            if len(key_event_part) >= 12:
                # Extract the last few characters as potential key code
                key_code = key_event_part[-2:]  # Last 2 hex digits
                print(f"DEBUG: Extracted key code: {key_code}")
                
                # Map key codes to actions based on observed patterns
                # These codes might need adjustment based on actual button behavior
                if key_code == "0d":  # Based on the response b1000606500d
                    print("DEBUG: Detected key press (code 0d)")
                    # For now, let's treat any key press as UP for testing
                    return "UP"
                elif key_code == "3c":  # Based on original patterns
                    print("DEBUG: Detected UP key")
                    return "UP"
                elif key_code == "61":
                    print("DEBUG: Detected DOWN key")
                    return "DOWN"
                elif key_code == "17":
                    print("DEBUG: Detected SELECT key")
                    return "SELECT"
                elif key_code == "47":
                    print("DEBUG: Detected BACK key")
                    return "BACK"
            
            # Also check for the longer patterns in case we get them
            if "00140a050800000000" in key_event_part:  # UP pattern
                print("DEBUG: Detected UP key (long pattern)")
                return "UP"
            if "00140a050200000000" in key_event_part:  # DOWN pattern
                print("DEBUG: Detected DOWN key (long pattern)")
                return "DOWN"
            if "00140a051000000000" in key_event_part:  # SELECT pattern
                print("DEBUG: Detected SELECT key (long pattern)")
                return "SELECT"
            if "00140a050100000000" in key_event_part:  # BACK pattern
                print("DEBUG: Detected BACK key (long pattern)")
                return "BACK"

        return None
    except Exception:
        # Never blow up the UI loop on a transient read error
        time.sleep(0.01)
        return None
