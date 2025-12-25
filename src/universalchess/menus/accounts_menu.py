"""Accounts (Lichess token) menu helper."""

from typing import Callable

from universalchess.epaper.icon_menu import IconMenuEntry
from universalchess.managers.menu import MenuSelection, is_break_result


def mask_token(token: str) -> str:
    """Mask a token for display."""
    if not token:
        return "Not set"
    if len(token) <= 8:
        return token[:2] + "..." + token[-2:] if len(token) > 4 else "****"
    return token[:6] + "..." + token[-4:]


def handle_accounts_menu(
    menu_manager,
    get_lichess_api: Callable[[], str],
    handle_lichess_token_fn: Callable[[], MenuSelection],
) -> MenuSelection:
    """Handle Accounts submenu for online service credentials."""

    def build_entries():
        token = get_lichess_api()
        masked = mask_token(token)
        return [
            IconMenuEntry(
                key="Lichess",
                label=f"Lichess\n{masked}",
                icon_name="lichess",
                enabled=True,
                font_size=12,
                max_height=47,
            ),
        ]

    def handle_selection(result: MenuSelection):
        if result.key == "Lichess":
            sub_result = handle_lichess_token_fn()
            if is_break_result(sub_result):
                return sub_result
        return None

    return menu_manager.run_menu_loop(build_entries, handle_selection)

