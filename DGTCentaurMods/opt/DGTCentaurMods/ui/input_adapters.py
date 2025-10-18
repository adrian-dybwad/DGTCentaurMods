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

        # The board sends combined responses like: 870006065063b10011065000140a050800000000
        # We need to extract the key event part (after the board state part)
        
        # Look for the key event marker 'b100' followed by addresses
        key_event_marker = f"b100{a1}{a2}"
        key_event_start = hx.find(key_event_marker)
        
        if key_event_start != -1:
            # Extract the key event part
            key_event_part = hx[key_event_start:]
            print(f"DEBUG: Key event part: {key_event_part}")
            
            # Match the 4 button patterns used elsewhere in the code
            if key_event_part == ("b10011" + a1 + a2 + "00140a0508000000007d3c"):  # UP
                print("DEBUG: Detected UP key")
                return "UP"
            if key_event_part == ("b10010" + a1 + a2 + "00140a05020000000061"):    # DOWN
                print("DEBUG: Detected DOWN key")
                return "DOWN"
            if key_event_part == ("b10011" + a1 + a2 + "00140a0510000000007d17"):  # TICK
                print("DEBUG: Detected SELECT key")
                return "SELECT"
            if key_event_part == ("b10011" + a1 + a2 + "00140a0501000000007d47"):  # BACK
                print("DEBUG: Detected BACK key")
                return "BACK"
            
            # Check for partial matches (the response might be truncated)
            if "00140a050800000000" in key_event_part:  # UP pattern
                print("DEBUG: Detected UP key (partial match)")
                return "UP"
            if "00140a050200000000" in key_event_part:  # DOWN pattern
                print("DEBUG: Detected DOWN key (partial match)")
                return "DOWN"
            if "00140a051000000000" in key_event_part:  # SELECT pattern
                print("DEBUG: Detected SELECT key (partial match)")
                return "SELECT"
            if "00140a050100000000" in key_event_part:  # BACK pattern
                print("DEBUG: Detected BACK key (partial match)")
                return "BACK"

        return None
    except Exception:
        # Never blow up the UI loop on a transient read error
        time.sleep(0.01)
        return None
