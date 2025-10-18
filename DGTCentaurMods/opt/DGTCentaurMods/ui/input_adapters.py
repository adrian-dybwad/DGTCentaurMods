# DGTCentaurMods/ui/input_adapters.py
from typing import Optional
from DGTCentaurMods.board import board as boardmod

def poll_actions_from_board() -> Optional[str]:
    """
    Poll the Centaur controller and map to menu actions.
    Adjust this mapping to match your board’s button codes.
    Returns "UP"/"DOWN"/"SELECT"/"BACK" or None.
    """
    try:
        # Example: decode a short state/read function you already have.
        # Replace with your real non-blocking read:
        state = boardmod.getBoardStateNonBlocking()  # you might have a helper; otherwise wrap ser.read(…)
        if not state:
            return None

        # Map bytes to actions — adjust to your protocol.
        # For example only!
        s = bytes(state).upper()
        if b"UP" in s: return "UP"
        if b"DOWN" in s: return "DOWN"
        if b"LEFT" in s or b"BACK" in s: return "BACK"
        if b"RIGHT" in s or b"OK" in s or b"ENTER" in s: return "SELECT"
    except Exception:
        return None
    return None
