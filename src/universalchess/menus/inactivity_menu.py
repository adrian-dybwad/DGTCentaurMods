"""Inactivity timeout menu helper."""

from typing import List, Callable, Optional

from universalchess.epaper.icon_menu import IconMenuEntry
from universalchess.managers.menu import MenuSelection, is_break_result


def handle_inactivity_timeout(
    board,
    log,
    menu_manager,
) -> Optional[MenuSelection]:
    """Handle inactivity timeout setting submenu."""
    timeout_options = [
        (0, "Disabled"),
        (5, "5 min"),
        (10, "10 min"),
        (15, "15 min"),
        (30, "30 min"),
        (60, "1 hour"),
    ]

    current_timeout = board.get_inactivity_timeout()

    entries: List[IconMenuEntry] = []
    for minutes, label in timeout_options:
        seconds = minutes * 60
        is_current = seconds == current_timeout
        icon = "timer_checked" if is_current else "timer"
        entries.append(IconMenuEntry(key=str(seconds), label=label, icon_name=icon, enabled=True))

    result = menu_manager.show_menu(entries)

    if result.is_break:
        return result

    if not result.is_exit():
        try:
            new_timeout = int(result.key)
            board.set_inactivity_timeout(new_timeout)
            log.info(f"[Settings] Inactivity timeout set to {new_timeout}s")
        except ValueError:
            pass

    return result

