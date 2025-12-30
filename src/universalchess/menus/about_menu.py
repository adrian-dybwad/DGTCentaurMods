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
            key="Support",
            label="Support\nQR Code",
            icon_name="universal_logo",
            enabled=True,
        ),
        IconMenuEntry(
            key="Updates",
            label=update_label,
            icon_name=update_icon,
            enabled=True,
        ),
    ]


def show_support_qr(
    board,
    log,
    get_installed_version: Callable[[], str],
    get_resource_path: Callable[[str], Optional[str]],
    set_active_about_widget: Callable,
    clear_active_about_widget: Callable,
):
    """Show support QR code on the e-paper display.
    
    Args:
        board: Board instance
        log: Logger instance
        get_installed_version: Function returning installed version
        get_resource_path: Function to resolve resource paths
        set_active_about_widget: Callback to set active widget
        clear_active_about_widget: Callback to clear active widget
    """
    from universalchess.epaper.about_widget import AboutWidget
    
    version = get_installed_version()
    qr_path = get_resource_path("qr.png")
    
    if not qr_path:
        log.warning("[About] QR code image not found")
        return
    
    try:
        board.display_manager.clear_widgets()
        widget = AboutWidget(
            update_callback=board.display_manager.update,
            version=version,
            qr_image_path=qr_path,
        )
        set_active_about_widget(widget)
        promise = board.display_manager.add_widget(widget)
        if promise:
            try:
                promise.result(timeout=2.0)
            except Exception:
                pass
        
        # Wait for user to press back
        import time
        while True:
            time.sleep(0.1)
            # The widget will be dismissed by the menu system
            if not board.display_manager.has_widget(widget):
                break
    
    finally:
        clear_active_about_widget()


def handle_about_menu(
    ctx,
    menu_manager,
    board,
    log,
    get_installed_version: Callable[[], str],
    get_resource_path: Callable[[str], Optional[str]],
    handle_update_menu: Callable,
    show_menu: Callable,
    find_entry_index: Callable,
    set_active_about_widget: Callable,
    clear_active_about_widget: Callable,
) -> Optional[MenuSelection]:
    """Handle About menu - show version info and update options.
    
    Args:
        ctx: Menu context
        menu_manager: Menu manager instance
        board: Board instance
        log: Logger instance
        get_installed_version: Function returning installed version
        get_resource_path: Function to resolve resource paths
        handle_update_menu: Function to handle update submenu
        show_menu: Function to display menu
        find_entry_index: Function to find entry index
        set_active_about_widget: Callback to set active widget
        clear_active_about_widget: Callback to clear active widget
        
    Returns:
        MenuSelection if breaking out, None otherwise
    """
    def build_entries():
        return build_about_entries(get_installed_version)

    def handle_selection(result: MenuSelection):
        if result.key == "Support":
            ctx.enter_menu("Support", 0)
            show_support_qr(
                board=board,
                log=log,
                get_installed_version=get_installed_version,
                get_resource_path=get_resource_path,
                set_active_about_widget=set_active_about_widget,
                clear_active_about_widget=clear_active_about_widget,
            )
            ctx.leave_menu()
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
