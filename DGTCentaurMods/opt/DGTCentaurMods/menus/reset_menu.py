"""Reset settings menu helpers."""

from typing import Callable, Dict, List, Optional

from DGTCentaurMods.epaper.icon_menu import IconMenuEntry
from DGTCentaurMods.managers.menu import is_break_result


def handle_reset_settings(
    game_settings: Dict,
    player1_settings: Dict,
    player2_settings: Dict,
    show_menu: Callable[[List[IconMenuEntry]], str],
    load_game_settings: Callable[[], None],
    log,
    board,
    settings_section: str,
    player1_section: str,
    player2_section: str,
) -> Optional[str]:
    """Handle reset all settings to defaults.

    Shows a confirmation dialog, then clears all entries in the settings sections
    and reloads settings with defaults.

    Args:
        game_settings: Dict with current game settings
        player1_settings: Dict with player 1 settings
        player2_settings: Dict with player 2 settings
        show_menu: Callback to show menu and get result
        load_game_settings: Callback to reload game settings
        log: Logger instance
        board: Board module
        settings_section: Name of game settings section in config
        player1_section: Name of player 1 section in config
        player2_section: Name of player 2 section in config

    Returns:
        Break result if user triggered a break action, None otherwise
    """
    entries = [
        IconMenuEntry(key="confirm", label="Reset All\nSettings?", icon_name="cancel", enabled=True),
        IconMenuEntry(key="cancel", label="Cancel", icon_name="cancel", enabled=True),
    ]

    result = show_menu(entries)

    if is_break_result(result):
        return result

    if result == "confirm":
        try:
            from DGTCentaurMods.board.settings import Settings
            import configparser

            config = configparser.ConfigParser()
            config.read(Settings.configfile)

            for section in [settings_section, player1_section, player2_section]:
                if config.has_section(section):
                    for key in list(config.options(section)):
                        config.remove_option(section, key)
            Settings.write_config(config)
            log.info("[Settings] Cleared all game/player settings from centaur.ini")

            player1_settings["color"] = "white"
            player1_settings["type"] = "human"
            player1_settings["name"] = ""
            player1_settings["engine"] = "stockfish"
            player1_settings["elo"] = "Default"

            player2_settings["type"] = "engine"
            player2_settings["name"] = ""
            player2_settings["engine"] = "stockfish"
            player2_settings["elo"] = "Default"

            game_settings["time_control"] = 0
            game_settings["analysis_mode"] = True
            game_settings["analysis_engine"] = "stockfish"
            game_settings["show_board"] = True
            game_settings["show_clock"] = True
            game_settings["show_analysis"] = True
            game_settings["show_graph"] = True

            load_game_settings()

            board.beep(board.SOUND_GENERAL, event_type="key_press")
            log.info("[Settings] Settings reset to defaults")

        except Exception as e:
            log.error(f"[Settings] Error resetting settings: {e}")
            board.beep(board.SOUND_WRONG_MOVE, event_type="error")

    return None

