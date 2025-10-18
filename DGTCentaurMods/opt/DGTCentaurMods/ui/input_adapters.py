# DGTCentaurMods/ui/input_adapters.py
from typing import Optional
import time
from DGTCentaurMods.board import board as b

# Map the Centaur hex signatures to high-level actions.
# We format addr1/addr2 dynamically because the controller can change them.
def poll_actions_from_board() -> Optional[str]:
    try:
        # Keepalive: ask for board state (even if we ignore it) to keep the MCU chatty
        b.sendPacket(b'\x83', b'')
        _ = b._ser_read(256)  # ignore warm-up payload

        # Ask for key events
        b.sendPacket(b'\x94', b'')
        resp = b.getBoardStateNonBlocking(max_bytes=256) or b._ser_read(256, timeout=0.01)
        if not resp:
            return None

        hx = resp.hex()[:-2]  # drop checksum
        a1 = f"{b.addr1:02x}"
        a2 = f"{b.addr2:02x}"

        # Match the 4 button patterns used elsewhere in the code
        if hx == ("b10011" + a1 + a2 + "00140a0508000000007d3c"):  # UP
            return "UP"
        if hx == ("b10010" + a1 + a2 + "00140a05020000000061"):    # DOWN
            return "DOWN"
        if hx == ("b10011" + a1 + a2 + "00140a0510000000007d17"):  # TICK
            return "SELECT"
        if hx == ("b10011" + a1 + a2 + "00140a0501000000007d47"):  # BACK
            return "BACK"

        return None
    except Exception:
        # Never blow up the UI loop on a transient read error
        time.sleep(0.01)
        return None
