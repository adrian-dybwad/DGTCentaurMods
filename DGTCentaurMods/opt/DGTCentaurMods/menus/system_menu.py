"""System menu helpers."""

from typing import Dict, List

from DGTCentaurMods.epaper.icon_menu import IconMenuEntry


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

