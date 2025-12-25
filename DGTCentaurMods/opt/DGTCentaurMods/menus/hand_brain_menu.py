"""Helpers for building Hand+Brain mode menu entries."""

from typing import List

from DGTCentaurMods.epaper.icon_menu import IconMenuEntry


def build_hand_brain_mode_entries(current_mode: str) -> List[IconMenuEntry]:
    """Return checkbox menu entries for hand-brain mode selection."""
    return [
        IconMenuEntry(
            key="normal",
            label="Normal",
            icon_name="checkbox_checked" if current_mode == "normal" else "checkbox_empty",
            enabled=True,
        ),
        IconMenuEntry(
            key="reverse",
            label="Reverse",
            icon_name="checkbox_checked" if current_mode == "reverse" else "checkbox_empty",
            enabled=True,
        ),
    ]


def build_hand_brain_mode_toggle_entry(current_mode: str) -> IconMenuEntry:
    """Return the Player menu toggle entry for Reverse mode."""
    return IconMenuEntry(
        key="HBMode",
        label="Reverse",
        icon_name="checkbox_checked" if current_mode == "reverse" else "checkbox_empty",
        enabled=True,
    )


def toggle_hand_brain_mode(current_mode: str) -> str:
    """Toggle hand-brain mode between normal and reverse."""
    return "normal" if current_mode == "reverse" else "reverse"

