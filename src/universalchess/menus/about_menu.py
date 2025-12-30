"""About menu helpers."""

from typing import Callable, Optional, List

from universalchess.epaper.icon_menu import IconMenuEntry
from universalchess.managers.menu import MenuSelection, is_break_result
from universalchess.services.update_service import get_update_service


def build_about_entries(
    get_installed_version: Callable[[], str],
) -> List[IconMenuEntry]:
    """Build about menu entries with current update status.
    
    Args:
        get_installed_version: Function returning installed version string
        
    Returns:
        List of menu entries
    """
    version = get_installed_version()
    version_label = f"Version\n{version}" if version else "Version\nUnknown"
    
    update_service = get_update_service()
    status = update_service.get_status_dict()
    
    # Determine update status label
    if status["has_pending_update"]:
        update_label = "Updates\nReady!"
        update_icon = "update"
    elif status["available_version"]:
        update_label = f"Updates\nv{status['available_version']}"
        update_icon = "update"
    elif status["auto_update"]:
        update_label = "Updates\nAuto"
        update_icon = "checkbox_checked"
    else:
        update_label = "Updates\nManual"
        update_icon = "checkbox_empty"

    return [
        IconMenuEntry(
            key="Version",
            label=version_label,
            icon_name="info",
            enabled=True,
            selectable=False,
        ),
        IconMenuEntry(
            key="Updates",
            label=update_label,
            icon_name=update_icon,
            enabled=True,
        ),
    ]


def handle_about_menu(
    ctx,
    menu_manager,
    board,
    log,
    get_installed_version: Callable[[], str],
    handle_update_menu: Callable,
    show_menu: Callable,
    find_entry_index: Callable,
) -> Optional[MenuSelection]:
    """Handle About menu - show version info and update options.
    
    Args:
        ctx: Menu context
        menu_manager: Menu manager instance
        board: Board instance
        log: Logger instance
        get_installed_version: Function returning installed version
        handle_update_menu: Function to handle update submenu
        show_menu: Function to display menu
        find_entry_index: Function to find entry index
        
    Returns:
        MenuSelection if breaking out, None otherwise
    """
    def build_entries():
        return build_about_entries(get_installed_version)

    def handle_selection(result: MenuSelection):
        if result.key == "Version":
            # Version is display-only, not selectable
            return None
        elif result.key == "Updates":
            ctx.enter_menu("Updates", 0)
            sub_result = handle_update_menu(
                show_menu=show_menu,
                find_entry_index=find_entry_index,
                board=board,
                log=log,
                initial_index=ctx.current_index(),
            )
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        return None

    return menu_manager.run_menu_loop(build_entries, handle_selection, initial_index=ctx.current_index())
