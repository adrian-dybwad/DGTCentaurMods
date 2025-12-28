"""Display settings menu helpers."""

from typing import Any, Callable, Dict, Optional, List, Union

from universalchess.epaper.icon_menu import IconMenuEntry
from universalchess.managers.menu import is_break_result, is_refresh_result


def handle_display_settings(
    game_settings: Dict[str, Any],
    show_menu: Callable[[List[IconMenuEntry]], str],
    save_game_setting: Callable[[str, Any], None],
    log,
    board,
) -> Optional[str]:
    """Handle the Display settings submenu.

    Shows checkboxes for each widget that can be shown/hidden during game,
    and LED brightness setting.

    Args:
        game_settings: Dict with current game settings (show_board, show_clock, led_brightness, etc.)
        show_menu: Callback to show menu and get result
        save_game_setting: Callback to save a game setting
        log: Logger instance
        board: Board module

    Returns:
        Break result if user triggered a break action, None otherwise
    """
    while True:
        # Get current LED brightness (default 5)
        led_brightness = game_settings.get("led_brightness", 5)
        
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
            IconMenuEntry(
                key="led_brightness",
                label=f"LED: {led_brightness}",
                icon_name="star",
                enabled=True,
            ),
        ]

        result = show_menu(entries)

        if is_refresh_result(result):
            continue

        if is_break_result(result):
            return result

        if result == "BACK":
            return None

        if result == "led_brightness":
            # Cycle through brightness: 1-2-3-4-5-6-7-8-9-10-1...
            new_brightness = (led_brightness % 10) + 1
            game_settings["led_brightness"] = new_brightness
            save_game_setting("led_brightness", new_brightness)
            log.info(f"[Display] LED brightness changed to {new_brightness}")
            board.beep(board.SOUND_GENERAL, event_type="key_press")
        elif result in game_settings and isinstance(game_settings[result], bool):
            new_value = not game_settings[result]
            game_settings[result] = new_value
            save_game_setting(result, new_value)
            log.info(f"[Display] {result} changed to {new_value}")
            board.beep(board.SOUND_GENERAL, event_type="key_press")

