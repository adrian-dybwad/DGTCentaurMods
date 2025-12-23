"""Player menu helpers."""

from typing import Dict, List

from DGTCentaurMods.epaper.icon_menu import IconMenuEntry
from DGTCentaurMods.menus.hand_brain_menu import build_hand_brain_mode_toggle_entry


def _player_type_label(player_type: str) -> str:
    labels = {
        "human": "Human",
        "engine": "Engine",
        "lichess": "Lichess",
        "hand_brain": "H+B",
    }
    return labels.get(player_type, player_type.capitalize())


def build_player1_menu_entries(player1_settings: Dict[str, str]) -> List[IconMenuEntry]:
    """Build Player 1 menu entries."""
    p1_color = player1_settings["color"].capitalize()
    p1_type = _player_type_label(player1_settings["type"])

    entries: List[IconMenuEntry] = [
        IconMenuEntry(
            key="Color",
            label=f"Color\n{p1_color}",
            icon_name="white_piece" if player1_settings["color"] == "white" else "black_piece",
            enabled=True,
        ),
        IconMenuEntry(
            key="Type",
            label=f"Type\n{p1_type}",
            icon_name="universal_logo",
            enabled=True,
        ),
    ]

    if player1_settings["type"] == "human":
        name_display = player1_settings["name"] or "Human"
        entries.append(
            IconMenuEntry(
                key="Name",
                label=f"Name\n{name_display}",
                icon_name="universal_logo",
                enabled=True,
            )
        )

    if player1_settings["type"] == "hand_brain":
        entries.append(build_hand_brain_mode_toggle_entry(player1_settings["hand_brain_mode"]))

    if player1_settings["type"] in ("human", "engine", "hand_brain"):
        entries.append(
            IconMenuEntry(
                key="Engine",
                label=f"Engine\n{player1_settings['engine']}",
                icon_name="engine",
                enabled=True,
            )
        )
        entries.append(
            IconMenuEntry(
                key="ELO",
                label=f"ELO\n{player1_settings['elo']}",
                icon_name="elo",
                enabled=True,
            )
        )

    if player1_settings["type"] == "lichess":
        entries.append(
            IconMenuEntry(
                key="LichessSettings",
                label="Lichess\nSettings",
                icon_name="lichess",
                enabled=True,
            )
        )

    return entries


def build_player2_menu_entries(player2_settings: Dict[str, str]) -> List[IconMenuEntry]:
    """Build Player 2 menu entries."""
    p2_type = _player_type_label(player2_settings["type"])

    entries: List[IconMenuEntry] = [
        IconMenuEntry(
            key="Type",
            label=f"Type\n{p2_type}",
            icon_name="universal_logo",
            enabled=True,
        ),
    ]

    if player2_settings["type"] == "human":
        name_display = player2_settings["name"] or "Human"
        entries.append(
            IconMenuEntry(
                key="Name",
                label=f"Name\n{name_display}",
                icon_name="universal_logo",
                enabled=True,
            )
        )

    if player2_settings["type"] == "hand_brain":
        entries.append(build_hand_brain_mode_toggle_entry(player2_settings["hand_brain_mode"]))

    if player2_settings["type"] in ("human", "engine", "hand_brain"):
        entries.append(
            IconMenuEntry(
                key="Engine",
                label=f"Engine\n{player2_settings['engine']}",
                icon_name="engine",
                enabled=True,
            )
        )
        entries.append(
            IconMenuEntry(
                key="ELO",
                label=f"ELO\n{player2_settings['elo']}",
                icon_name="elo",
                enabled=True,
            )
        )

    if player2_settings["type"] == "lichess":
        entries.append(
            IconMenuEntry(
                key="LichessSettings",
                label="Lichess\nSettings",
                icon_name="lichess",
                enabled=True,
            )
        )

    return entries


def handle_player1_menu(
    ctx,
    player1_settings: Dict[str, str],
    show_menu,
    find_entry_index,
    is_break_result,
    board,
    log,
    save_player1_setting,
    handle_color_selection,
    handle_type_selection,
    handle_name_input,
    handle_engine_selection,
    handle_elo_selection,
    handle_lichess_menu,
    toggle_hand_brain_mode_fn,
) -> str:
    """Handle Player 1 configuration submenu."""
    while True:
        entries = build_player1_menu_entries(player1_settings)

        result = show_menu(entries, initial_index=ctx.current_index())
        ctx.update_index(find_entry_index(entries, result))

        if is_break_result(result):
            return result

        if result == "BACK":
            return None

        if result == "Color":
            ctx.enter_menu("Color", 0)
            color_result = handle_color_selection()
            ctx.leave_menu()
            if is_break_result(color_result):
                return color_result

        elif result == "Type":
            ctx.enter_menu("Type", 0)
            type_result = handle_type_selection()
            ctx.leave_menu()
            if is_break_result(type_result):
                return type_result

        elif result == "Name":
            ctx.enter_menu("Name", 0)
            name_result = handle_name_input()
            ctx.leave_menu()
            if is_break_result(name_result):
                return name_result

        elif result == "HBMode":
            old_mode = player1_settings["hand_brain_mode"]
            new_mode = toggle_hand_brain_mode_fn(old_mode)
            save_player1_setting("hand_brain_mode", new_mode)
            log.info(f"[Settings] Player1 hand_brain_mode toggled: {old_mode} -> {new_mode}")
            board.beep(board.SOUND_GENERAL, event_type='key_press')
            continue

        elif result == "Engine":
            ctx.enter_menu("Engine", 0)
            engine_result = handle_engine_selection()
            ctx.leave_menu()
            if is_break_result(engine_result):
                return engine_result

        elif result == "ELO":
            ctx.enter_menu("ELO", 0)
            elo_result = handle_elo_selection()
            ctx.leave_menu()
            if is_break_result(elo_result):
                return elo_result

        elif result == "LichessSettings":
            ctx.enter_menu("LichessSettings", 0)
            lichess_result = handle_lichess_menu()
            ctx.leave_menu()
            if is_break_result(lichess_result):
                return lichess_result


def handle_player2_menu(
    ctx,
    player2_settings: Dict[str, str],
    show_menu,
    find_entry_index,
    is_break_result,
    board,
    log,
    save_player2_setting,
    handle_type_selection,
    handle_name_input,
    handle_engine_selection,
    handle_elo_selection,
    handle_lichess_menu,
    toggle_hand_brain_mode_fn,
) -> str:
    """Handle Player 2 configuration submenu."""
    while True:
        entries = build_player2_menu_entries(player2_settings)

        result = show_menu(entries, initial_index=ctx.current_index())
        ctx.update_index(find_entry_index(entries, result))

        if is_break_result(result):
            return result

        if result == "BACK":
            return None

        if result == "Type":
            ctx.enter_menu("Type", 0)
            type_result = handle_type_selection()
            ctx.leave_menu()
            if is_break_result(type_result):
                return type_result

        elif result == "Name":
            ctx.enter_menu("Name", 0)
            name_result = handle_name_input()
            ctx.leave_menu()
            if is_break_result(name_result):
                return name_result

        elif result == "HBMode":
            old_mode = player2_settings["hand_brain_mode"]
            new_mode = toggle_hand_brain_mode_fn(old_mode)
            save_player2_setting("hand_brain_mode", new_mode)
            log.info(f"[Settings] Player2 hand_brain_mode toggled: {old_mode} -> {new_mode}")
            board.beep(board.SOUND_GENERAL, event_type='key_press')
            continue

        elif result == "Engine":
            ctx.enter_menu("Engine", 0)
            engine_result = handle_engine_selection()
            ctx.leave_menu()
            if is_break_result(engine_result):
                return engine_result

        elif result == "ELO":
            ctx.enter_menu("ELO", 0)
            elo_result = handle_elo_selection()
            ctx.leave_menu()
            if is_break_result(elo_result):
                return elo_result

        elif result == "LichessSettings":
            ctx.enter_menu("LichessSettings", 0)
            lichess_result = handle_lichess_menu()
            ctx.leave_menu()
            if is_break_result(lichess_result):
                return lichess_result

