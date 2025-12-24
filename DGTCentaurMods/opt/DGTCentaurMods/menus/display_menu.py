"""Display settings menu helpers."""

from typing import Callable, Dict, Optional, List

from DGTCentaurMods.epaper.icon_menu import IconMenuEntry
from DGTCentaurMods.managers.menu import is_break_result


def handle_display_settings(
    game_settings: Dict[str, bool],
    show_menu: Callable[[List[IconMenuEntry]], str],
    save_game_setting: Callable[[str, bool], None],
    log,
    board,
) -> Optional[str]:
    """Handle the Display settings submenu.

    Shows checkboxes for each widget that can be shown/hidden during game.

    Args:
        game_settings: Dict with current game settings (show_board, show_clock, etc.)
        show_menu: Callback to show menu and get result
        save_game_setting: Callback to save a game setting
        log: Logger instance
        board: Board module

    Returns:
        Break result if user triggered a break action, None otherwise
    """
    while True:
        entries = [
            IconMenuEntry(
                key="show_board",
                label="Board",
                icon_name="checkbox_checked" if game_settings["show_board"] else "checkbox_empty",
                enabled=True,
            ),
            IconMenuEntry(
                key="show_clock",
                label="Clock",
                icon_name="checkbox_checked" if game_settings["show_clock"] else "checkbox_empty",
                enabled=True,
            ),
            IconMenuEntry(
                key="show_analysis",
                label="Analysis",
                icon_name="checkbox_checked" if game_settings["show_analysis"] else "checkbox_empty",
                enabled=True,
            ),
            IconMenuEntry(
                key="show_graph",
                label="Graph",
                icon_name="checkbox_checked" if game_settings["show_graph"] else "checkbox_empty",
                enabled=game_settings["show_analysis"],
            ),
        ]

        result = show_menu(entries)

        if is_break_result(result):
            return result

        if result == "BACK":
            return None

        if result in game_settings and isinstance(game_settings[result], bool):
            new_value = not game_settings[result]
            game_settings[result] = new_value
            save_game_setting(result, new_value)
            log.info(f"[Display] {result} changed to {new_value}")
            board.beep(board.SOUND_GENERAL, event_type="key_press")

