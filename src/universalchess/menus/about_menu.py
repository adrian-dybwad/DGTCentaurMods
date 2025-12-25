"""About menu helpers."""

from typing import Callable, Optional, List

from universalchess.epaper.icon_menu import IconMenuEntry
from universalchess.managers.menu import MenuSelection, is_break_result


def build_about_entries(
    get_installed_version: Callable[[], str],
    update_system,
) -> List[IconMenuEntry]:
    """Build about menu entries with current update status."""
    version = get_installed_version()
    version_label = f"Version\n{version}" if version else "Version\nUnknown"

    update_status = update_system.getStatus()
    update_label = f"Updates\n{update_status.capitalize()}"
    update_icon = "checkbox_checked" if update_status == "enabled" else "checkbox_empty"

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
    """Display support QR code screen using AboutWidget."""
    from PIL import Image
    from universalchess.epaper.about_widget import AboutWidget

    version = get_installed_version()

    qr_img = None
    try:
        qr_path = get_resource_path("qr-support.png")
        if qr_path:
            qr_img = Image.open(qr_path)
    except Exception as e:
        log.debug(f"[About] Failed to load QR image: {e}")

    board.display_manager.clear_widgets(addStatusBar=False)

    about_widget = AboutWidget(board.display_manager.update, qr_image=qr_img, version=version)
    set_active_about_widget(about_widget)

    promise = board.display_manager.add_widget(about_widget)
    if promise:
        try:
            promise.result(timeout=2.0)
        except Exception:
            pass

    try:
        about_widget.wait_for_dismiss(timeout=30.0)
    finally:
        clear_active_about_widget()


def handle_about_menu(
    ctx,
    menu_manager,
    board,
    log,
    get_installed_version: Callable[[], str],
    get_resource_path: Callable[[str], Optional[str]],
    update_system,
    handle_update_menu: Callable,
    show_menu: Callable,
    find_entry_index: Callable,
    set_active_about_widget: Callable,
    clear_active_about_widget: Callable,
) -> Optional[MenuSelection]:
    """Handle About menu - show version info and update options."""

    def build_entries():
        return build_about_entries(get_installed_version, update_system)

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
                update_system=update_system,
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

