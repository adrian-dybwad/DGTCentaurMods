"""Helpers for building Hand+Brain mode menu entries."""

from typing import List

from DGTCentaurMods.epaper.icon_menu import IconMenuEntry


def build_hand_brain_mode_entries(current_mode: str) -> List[IconMenuEntry]:
    """Return checkbox menu entries for hand-brain mode selection.
    
    Reverse mode must remain a checkbox entry so the active mode is visually clear.
    """
    return [
        IconMenuEntry(
            key="normal",
            label="Normal",
            icon_name="checkbox_checked" if current_mode == 'normal' else "checkbox_empty",
            enabled=True
        ),
        IconMenuEntry(
            key="reverse",
            label="Reverse",
            icon_name="checkbox_checked" if current_mode == 'reverse' else "checkbox_empty",
            enabled=True
        ),
    ]

