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
            print(f"DEBUG: Key response: {hx}")

        # Match the 4 button patterns used elsewhere in the code
        if hx == ("b10011" + a1 + a2 + "00140a0508000000007d3c"):  # UP
            return "UP"
        if hx == ("b10010" + a1 + a2 + "00140a05020000000061"):    # DOWN
            return "DOWN"
        if hx == ("b10011" + a1 + a2 + "00140a0510000000007d17"):  # TICK
            return "SELECT"
        if hx == ("b10011" + a1 + a2 + "00140a0501000000007d47"):  # BACK
            return "BACK"

        # Try to parse the actual response we're getting
        # The response b1000606500d suggests a different format
        if hx.startswith("b100" + a1 + a2):
            # This looks like a key event response, but with different data
            # Let's try to extract the key code from the end
            if len(hx) >= 12:
                key_code = hx[-2:]  # Last 2 hex digits
                print(f"DEBUG: Detected key code: {key_code}")
                
                # Map key codes to actions (these might need adjustment based on actual board behavior)
                if key_code == "3c":  # Based on the original patterns
                    return "UP"
                elif key_code == "61":
                    return "DOWN"
                elif key_code == "17":
                    return "SELECT"
                elif key_code == "47":
                    return "BACK"

        return None
    except Exception:
        # Never blow up the UI loop on a transient read error
        time.sleep(0.01)
        return None
