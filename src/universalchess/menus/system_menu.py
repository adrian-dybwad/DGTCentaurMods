"""System menu helpers."""

from typing import Dict, List, Callable, Optional

from universalchess.epaper.icon_menu import IconMenuEntry
from universalchess.managers.menu import MenuSelection, is_break_result, is_refresh_result
from universalchess.utils.led import LED_SPEED_NORMAL, LED_INTENSITY_DEFAULT


def create_system_entries(board_module, game_settings: Dict[str, object]) -> List[IconMenuEntry]:
    """Create entries for the system submenu."""
    timeout = board_module.get_inactivity_timeout()
    if timeout == 0:
        timeout_label = "Sleep Timer\nDisabled"
        timeout_icon = "timer"
    else:
        timeout_label = f"Sleep Timer\n{timeout // 60} min"
        timeout_icon = "timer_checked"

    analysis_mode_icon = "checkbox_checked" if game_settings["analysis_mode"] else "checkbox_empty"

    return [
        IconMenuEntry(key="Display", label="Display", icon_name="display", enabled=True),
        IconMenuEntry(key="WiFi", label="WiFi", icon_name="wifi", enabled=True),
        IconMenuEntry(key="Bluetooth", label="Bluetooth", icon_name="bluetooth", enabled=True),
        IconMenuEntry(key="Accounts", label="Accounts", icon_name="account", enabled=True),
        IconMenuEntry(key="Sound", label="Sound", icon_name="sound", enabled=True),
        IconMenuEntry(key="AnalysisMode", label="Analysis\nMode", icon_name=analysis_mode_icon, enabled=True),
        IconMenuEntry(key="Engines", label="Engine\nManager", icon_name="engine", enabled=True),
        IconMenuEntry(key="Inactivity", label=timeout_label, icon_name=timeout_icon, enabled=True),
        IconMenuEntry(key="ResetSettings", label="Reset\nSettings", icon_name="cancel", enabled=True),
        IconMenuEntry(key="Shutdown", label="Shutdown", icon_name="shutdown", enabled=True),
        IconMenuEntry(key="Reboot", label="Reboot", icon_name="reboot", enabled=True),
    ]


def handle_system_menu(
    ctx,
    board,
    game_settings: Dict[str, object],
    menu_manager,
    create_entries: Callable[[], List[IconMenuEntry]],
    handle_display_settings: Callable[[], Optional[MenuSelection]],
    handle_sound_settings: Callable[[], Optional[MenuSelection]],
    handle_analysis_mode_menu: Callable[[], Optional[MenuSelection]],
    handle_engine_manager_menu: Callable[[], Optional[MenuSelection]],
    handle_wifi_settings: Callable[[], Optional[MenuSelection]],
    handle_bluetooth_settings: Callable[[], Optional[MenuSelection]],
    handle_chromecast_menu: Callable[[], Optional[MenuSelection]],
    handle_accounts_menu: Callable[[], Optional[MenuSelection]],
    handle_inactivity_timeout: Callable[[], Optional[MenuSelection]],
    handle_reset_settings: Callable[[], Optional[MenuSelection]],
    shutdown_fn: Callable[[str, bool], None],
    log,
) -> Optional[MenuSelection]:
    """Handle system submenu (display, sound, WiFi, Bluetooth, etc.)."""

    def handle_selection(result: MenuSelection):
        if result.key == "Display":
            ctx.enter_menu("Display", 0)
            sub_result = handle_display_settings()
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Sound":
            ctx.enter_menu("Sound", 0)
            sub_result = handle_sound_settings()
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "AnalysisMode":
            ctx.enter_menu("AnalysisMode", 0)
            sub_result = handle_analysis_mode_menu()
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Engines":
            ctx.enter_menu("Engines", 0)
            sub_result = handle_engine_manager_menu()
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "WiFi":
            ctx.enter_menu("WiFi", 0)
            sub_result = handle_wifi_settings()
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Bluetooth":
            ctx.enter_menu("Bluetooth", 0)
            sub_result = handle_bluetooth_settings()
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Chromecast":
            ctx.enter_menu("Chromecast", 0)
            sub_result = handle_chromecast_menu()
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Accounts":
            ctx.enter_menu("Accounts", 0)
            sub_result = handle_accounts_menu()
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Inactivity":
            ctx.enter_menu("Inactivity", 0)
            sub_result = handle_inactivity_timeout()
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "ResetSettings":
            ctx.enter_menu("ResetSettings", 0)
            sub_result = handle_reset_settings()
            ctx.leave_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Shutdown":
            ctx.clear()
            shutdown_fn("Shutdown", False)
            return result
        elif result.key == "Reboot":
            ctx.clear()
            try:
                for i in range(0, 8):
                    board.led(i, intensity=LED_INTENSITY_DEFAULT,
                              speed=LED_SPEED_NORMAL, repeat=0)
                    import time as _time
                    _time.sleep(0.2)
            except Exception:
                pass
            shutdown_fn("Rebooting", True)
            return result
        return None

    return menu_manager.run_menu_loop(
        create_entries,
        handle_selection,
        initial_index=ctx.current_index()
    )

