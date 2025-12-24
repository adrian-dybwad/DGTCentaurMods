"""Sound settings menu helpers."""

from typing import Optional

from DGTCentaurMods.epaper.icon_menu import IconMenuEntry
from DGTCentaurMods.managers.menu import MenuSelection


def handle_sound_settings(
    menu_manager,
    board,
) -> Optional[MenuSelection]:
    """Handle sound settings submenu.

    Shows individual sound settings with toggle checkboxes.

    Args:
        menu_manager: Menu manager instance
        board: Board module

    Returns:
        Break result if interrupted, None otherwise
    """
    from DGTCentaurMods.epaper import sound_settings

    def build_entries():
        settings = sound_settings.get_sound_settings()
        return [
            IconMenuEntry(
                key="piece_event",
                label="Piece Events",
                icon_name="timer_checked" if settings["piece_event"] else "timer",
                enabled=True,
                selectable=True,
                height_ratio=0.8,
                layout="horizontal",
                font_size=14,
            ),
            IconMenuEntry(
                key="game_event",
                label="Game Events",
                icon_name="timer_checked" if settings["game_event"] else "timer",
                enabled=True,
                selectable=True,
                height_ratio=0.8,
                layout="horizontal",
                font_size=14,
            ),
            IconMenuEntry(
                key="error",
                label="Errors",
                icon_name="timer_checked" if settings["error"] else "timer",
                enabled=True,
                selectable=True,
                height_ratio=0.8,
                layout="horizontal",
                font_size=14,
            ),
            IconMenuEntry(
                key="key_press",
                label="Key Press",
                icon_name="timer_checked" if settings["key_press"] else "timer",
                enabled=True,
                selectable=True,
                height_ratio=0.8,
                layout="horizontal",
                font_size=14,
            ),
            IconMenuEntry(
                key="enabled",
                label="Sound Enabled",
                icon_name="timer_checked" if settings["enabled"] else "timer",
                enabled=True,
                selectable=True,
                height_ratio=0.8,
                layout="horizontal",
                font_size=14,
                bold=True,
            ),
        ]

    def handle_selection(result: MenuSelection):
        if result.key in sound_settings.SOUND_SETTINGS:
            new_value = sound_settings.toggle_sound_setting(result.key)
            if new_value and result.key == "enabled":
                board.beep(board.SOUND_GENERAL)
        return None

    return menu_manager.run_menu_loop(build_entries, handle_selection, initial_index=4)

