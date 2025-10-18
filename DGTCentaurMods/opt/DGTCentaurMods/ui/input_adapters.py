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

        # Special case: UP button might only send board state (870006065063)
        # We need to detect this pattern and treat it as UP
        if hx == f"8700{a1}0{a2}063":
            print("DEBUG: Detected UP key (board state only)")
            return "UP"

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
            
            # The board can send multiple key events in one response
            # Example: b1000606500db10011065000140a0500
            # We need to find all key event markers and process each one
            
            # Split by key event markers to find all key events
            key_events = []
            remaining = key_event_part
            
            while remaining:
                # Look for the next key event marker
                next_marker1 = remaining.find(f"b100{a1}{a2}")
                next_marker2 = remaining.find(f"b100{a1}0{a2}")
                
                next_marker = -1
                if next_marker1 != -1 and next_marker2 != -1:
                    next_marker = min(next_marker1, next_marker2)
                elif next_marker1 != -1:
                    next_marker = next_marker1
                elif next_marker2 != -1:
                    next_marker = next_marker2
                
                if next_marker == -1:
                    break
                
                # Extract this key event
                if next_marker > 0:
                    # Skip to the start of this key event
                    remaining = remaining[next_marker:]
                
                # Find the end of this key event (start of next one or end of string)
                next_start1 = remaining[1:].find(f"b100{a1}{a2}")
                next_start2 = remaining[1:].find(f"b100{a1}0{a2}")
                
                next_start = -1
                if next_start1 != -1 and next_start2 != -1:
                    next_start = min(next_start1, next_start2) + 1
                elif next_start1 != -1:
                    next_start = next_start1 + 1
                elif next_start2 != -1:
                    next_start = next_start2 + 1
                
                if next_start == -1:
                    # This is the last key event
                    key_events.append(remaining)
                    break
                else:
                    # Extract this key event and continue
                    key_events.append(remaining[:next_start])
                    remaining = remaining[next_start:]
            
            # Process each key event
            for i, key_event in enumerate(key_events):
                print(f"DEBUG: Processing key event {i+1}: {key_event}")
                
                # Extract key code from the end
                if len(key_event) >= 12:
                    key_code = key_event[-2:]  # Last 2 hex digits
                    print(f"DEBUG: Key event {i+1} code: {key_code}")
                    
                    # Map key codes to actions
                    if key_code == "0d":  # Based on observed pattern
                        print("DEBUG: Detected key press (code 0d)")
                        return "UP"  # Temporary mapping
                    elif key_code == "3c":
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
                
                # Use the correct patterns from board.py
                # Format: b10011 + addr1 + addr2 + pattern + checksum
                # We need to match the full pattern including the checksum
                
                # BACK BUTTON: b10011 + addr1 + addr2 + 00140a0501000000007d47
                if key_event.endswith("00140a0501000000007d47"):
                    print("DEBUG: Detected BACK key (correct pattern)")
                    return "BACK"
                
                # TICK/SELECT BUTTON: b10011 + addr1 + addr2 + 00140a0510000000007d17
                if key_event.endswith("00140a0510000000007d17"):
                    print("DEBUG: Detected SELECT key (correct pattern)")
                    return "SELECT"
                
                # UP BUTTON: b10011 + addr1 + addr2 + 00140a0508000000007d3c
                if key_event.endswith("00140a0508000000007d3c"):
                    print("DEBUG: Detected UP key (correct pattern)")
                    return "UP"
                
                # DOWN BUTTON: b10010 + addr1 + addr2 + 00140a05020000000061
                if key_event.endswith("00140a05020000000061"):
                    print("DEBUG: Detected DOWN key (correct pattern)")
                    return "DOWN"
                
                # HELP BUTTON: b10010 + addr1 + addr2 + 00140a0540000000006d
                if key_event.endswith("00140a0540000000006d"):
                    print("DEBUG: Detected HELP key (correct pattern)")
                    return "HELP"
                
                # PLAY BUTTON: b10010 + addr1 + addr2 + 00140a0504000000002a
                if key_event.endswith("00140a0504000000002a"):
                    print("DEBUG: Detected PLAY key (correct pattern)")
                    return "PLAY"
                
                # Check for partial matches (in case response is truncated)
                if "00140a050100000000" in key_event:  # BACK pattern
                    print("DEBUG: Detected BACK key (partial pattern)")
                    return "BACK"
                if "00140a051000000000" in key_event:  # SELECT pattern
                    print("DEBUG: Detected SELECT key (partial pattern)")
                    return "SELECT"
                if "00140a050800000000" in key_event:  # UP pattern
                    print("DEBUG: Detected UP key (partial pattern)")
                    return "UP"
                if "00140a050200000000" in key_event:  # DOWN pattern
                    print("DEBUG: Detected DOWN key (partial pattern)")
                    return "DOWN"

        return None
    except Exception:
        # Never blow up the UI loop on a transient read error
        time.sleep(0.01)
        return None
