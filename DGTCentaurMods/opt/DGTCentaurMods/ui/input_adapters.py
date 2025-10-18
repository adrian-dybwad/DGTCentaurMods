from typing import Optional
from DGTCentaurMods.board import board as boardmod

def poll_actions_from_board() -> Optional[str]:
    b = boardmod.getBoardStateNonBlocking()
    if not b:
        return None
    s = b.upper()
    # TODO: map to your real codes
    if b"UP" in s: return "UP"
    if b"DOWN" in s: return "DOWN"
    if b"BACK" in s or b"LEFT" in s: return "BACK"
    if b"OK" in s or b"\r" in s or b"RIGHT" in s: return "SELECT"
    return None
