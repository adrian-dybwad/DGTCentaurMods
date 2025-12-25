"""Update/Install menu helpers."""

import os
import time
import json
import urllib.request
import shutil
from typing import Callable, List, Optional

from universalchess.epaper.icon_menu import IconMenuEntry
from universalchess.managers.menu import MenuSelection, is_break_result
from universalchess.epaper import SplashScreen


def handle_update_menu(
    update_system,
    show_menu: Callable[[List[IconMenuEntry], int], str],
    find_entry_index: Callable[[List[IconMenuEntry], str], int],
    board,
    log,
    initial_index: int = 0,
) -> Optional[MenuSelection]:
    """Handle update settings menu."""
    def build_entries():
        status = update_system.getStatus()
        channel = update_system.getChannel()
        policy = update_system.getPolicy()

        status_icon = "checkbox_checked" if status == "enabled" else "checkbox_empty"

        entries = [
            IconMenuEntry(
                key="Status",
                label=f"Auto-Update\n{status.capitalize()}",
                icon_name=status_icon,
                enabled=True,
            ),
        ]

        if status == "enabled":
            entries.extend(
                [
                    IconMenuEntry(
                        key="Channel",
                        label=f"Channel\n{channel.capitalize()}",
                        icon_name="settings",
                        enabled=True,
                    ),
                    IconMenuEntry(
                        key="Policy",
                        label=f"Policy\n{policy.capitalize()}",
                        icon_name="settings",
                        enabled=True,
                    ),
                    IconMenuEntry(
                        key="CheckNow",
                        label="Check for\nUpdates",
                        icon_name="update",
                        enabled=True,
                    ),
                ]
            )

        entries.append(
            IconMenuEntry(
                key="InstallDeb",
                label="Install\n.local .deb",
                icon_name="update",
                enabled=True,
            )
        )

        return entries

    def handle_selection(result_key: str):
        if result_key == "Status":
            status = update_system.getStatus()
            new_status = "disabled" if status == "enabled" else "enabled"
            update_system.setStatus(new_status)
            log.info(f"[Update] Auto-update status set to {new_status}")
            return None

        if result_key == "Channel":
            options = ["stable", "beta"]
            current = update_system.getChannel()
            entries = [
                IconMenuEntry(
                    key=opt,
                    label=f"* {opt}" if opt == current else opt,
                    icon_name="checkbox_checked" if opt == current else "checkbox_empty",
                    enabled=True,
                )
                for opt in options
            ]
            channel_result = show_menu(entries, initial_index=find_entry_index(entries, current))
            if channel_result not in ["BACK", "SHUTDOWN", "HELP"]:
                update_system.setChannel(channel_result)
                log.info(f"[Update] Channel set to {channel_result}")
            return None

        if result_key == "Policy":
            options = ["always", "revision"]
            current = update_system.getPolicy()
            entries = [
                IconMenuEntry(
                    key=opt,
                    label=f"* {opt}" if opt == current else opt,
                    icon_name="checkbox_checked" if opt == current else "checkbox_empty",
                    enabled=True,
                )
                for opt in options
            ]
            policy_result = show_menu(entries, initial_index=find_entry_index(entries, current))
            if policy_result not in ["BACK", "SHUTDOWN", "HELP"]:
                update_system.setPolicy(policy_result)
                log.info(f"[Update] Policy set to {policy_result}")
            return None

        if result_key == "CheckNow":
            board.display_manager.clear_widgets(addStatusBar=False)
            promise = board.display_manager.add_widget(
                SplashScreen(board.display_manager.update, message="Checking\nfor updates...", leave_room_for_status_bar=False)
            )
            if promise:
                try:
                    promise.result(timeout=5.0)
                except Exception:
                    pass
            try:
                result = update_system.checkForUpdates()
                log.info(f"[Update] Check result: {result}")
            except Exception as e:
                log.error(f"[Update] Check failed: {e}")
            time.sleep(1)
            return None

        if result_key == "InstallDeb":
            return "InstallDeb"

        return None

    idx = initial_index
    while True:
        entries = build_entries()
        result = show_menu(entries, initial_index=idx)
        idx = find_entry_index(entries, result)
        if is_break_result(result):
            return result
        if result in ["BACK", "SHUTDOWN", "HELP"]:
            return result
        selection_result = handle_selection(result)
        if selection_result == "InstallDeb":
            return selection_result


def handle_local_deb_install(
    source_path: str,
    board,
    log,
    update_system,
    menu_manager,
) -> None:
    """Handle installing a local .deb file."""
    if not source_path or not os.path.exists(source_path):
        log.error(f"[Update] .deb file not found: {source_path}")
        board.display_manager.clear_widgets()
        promise = board.display_manager.add_widget(
            SplashScreen(board.display_manager.update, message="Install failed")
        )
        if promise:
            try:
                promise.result(timeout=2.0)
            except Exception:
                pass
        time.sleep(2)
        return

    deb_file = os.path.basename(source_path)
    board.display_manager.clear_widgets()
    promise = board.display_manager.add_widget(
        SplashScreen(board.display_manager.update, message=f"Installing\n{deb_file}")
    )
    if promise:
        try:
            promise.result(timeout=2.0)
        except Exception:
            pass
    confirm_entries = [
        IconMenuEntry(key="Install", label="Install\nNow", icon_name="play", enabled=True),
        IconMenuEntry(key="Cancel", label="Cancel", icon_name="cancel", enabled=True),
    ]
    confirm_result = menu_manager.show_menu(confirm_entries)
    if confirm_result.key == "Install":
        try:
            shutil.copy(source_path, "/tmp/dgtcentaurmods_armhf.deb")
            log.info(f"[Update] Copied {deb_file} to /tmp for installation")
            update_system.updateInstall()
        except Exception as e:
            log.error(f"[Update] Failed to prepare update: {e}")
            board.display_manager.clear_widgets()
            promise = board.display_manager.add_widget(
                SplashScreen(board.display_manager.update, message="Install\nfailed")
            )
            if promise:
                try:
                    promise.result(timeout=2.0)
                except Exception:
                    pass
            time.sleep(2)


def check_and_download_update(
    update_system,
    board,
    log,
    menu_manager,
    get_installed_version: Callable[[], str],
    read_update_source: Callable[[], str],
) -> None:
    """Check for updates from GitHub and download/install if approved."""
    update_source = read_update_source()
    url = f"https://raw.githubusercontent.com/{update_source}/master/packaging/deb-root/DEBIAN/versions"
    board.display_manager.clear_widgets()
    promise = board.display_manager.add_widget(
        SplashScreen(board.display_manager.update, message="Checking for\nupdates...")
    )
    if promise:
        try:
            promise.result(timeout=2.0)
        except Exception:
            pass

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            ver_info = json.loads(response.read().decode())

        channel = update_system.getChannel()
        if channel not in ver_info:
            log.warning(f"[Update] Channel '{channel}' not found in version info")
            board.display_manager.clear_widgets()
            promise = board.display_manager.add_widget(
                SplashScreen(board.display_manager.update, message="Channel not\nfound")
            )
            if promise:
                try:
                    promise.result(timeout=2.0)
                except Exception:
                    pass
            time.sleep(2)
            return

        release_version = ver_info[channel].get("release", "")
        ota_version = ver_info[channel].get("ota", "None")
        current_version = get_installed_version()

        if ota_version == "None" or ota_version == current_version:
            board.display_manager.clear_widgets()
            promise = board.display_manager.add_widget(
                SplashScreen(board.display_manager.update, message=f"You have the\nlatest version\n\nv{current_version}")
            )
            if promise:
                try:
                    promise.result(timeout=2.0)
                except Exception:
                    pass
            time.sleep(2)
            return

        board.display_manager.clear_widgets()
        promise = board.display_manager.add_widget(
            SplashScreen(board.display_manager.update, message=f"Update available\nv{ota_version}\n\nDownloading...")
        )
        if promise:
            try:
                promise.result(timeout=2.0)
            except Exception:
                pass

        download_url = (
            f"https://github.com/{update_source}/releases/download/v{release_version}/"
            f"dgtcentaurmods_{release_version}_armhf.deb"
        )
        try:
            urllib.request.urlretrieve(download_url, "/tmp/dgtcentaurmods_armhf.deb")
            log.info("[Update] Downloaded update to /tmp/dgtcentaurmods_armhf.deb")

            board.display_manager.clear_widgets()
            promise = board.display_manager.add_widget(
                SplashScreen(board.display_manager.update, message=f"Downloaded\nv{release_version}\n\nInstall now?")
            )
            if promise:
                try:
                    promise.result(timeout=2.0)
                except Exception:
                    pass

            confirm_entries = [
                IconMenuEntry(key="Install", label="Install\nNow", icon_name="play", enabled=True),
                IconMenuEntry(key="Later", label="Install\nLater", icon_name="cancel", enabled=True),
            ]
            confirm_result = menu_manager.show_menu(confirm_entries)
            if confirm_result.key == "Install":
                update_system.updateInstall()
        except Exception as e:
            log.error(f"[Update] Download failed: {e}")
            board.display_manager.clear_widgets()
            promise = board.display_manager.add_widget(
                SplashScreen(board.display_manager.update, message="Download\nfailed")
            )
            if promise:
                try:
                    promise.result(timeout=2.0)
                except Exception:
                    pass
            time.sleep(2)
    except Exception as e:
        log.error(f"[Update] Failed to check for updates: {e}")
        board.display_manager.clear_widgets()
        promise = board.display_manager.add_widget(
            SplashScreen(board.display_manager.update, message="Check failed\n\nNo network?")
        )
        if promise:
            try:
                promise.result(timeout=2.0)
            except Exception:
                pass
        time.sleep(2)


def install_deb_update(
    deb_file: str,
    update_system,
    board,
    log,
    menu_manager,
) -> None:
    """Install a .deb file from /home/pi."""
    source_path = f"/home/pi/{deb_file}"
    if not os.path.exists(source_path):
        log.error(f"[Update] .deb file not found: {source_path}")
        return

    board.display_manager.clear_widgets()
    promise = board.display_manager.add_widget(
        SplashScreen(board.display_manager.update, message=f"Install\n{deb_file[:20]}?")
    )
    if promise:
        try:
            promise.result(timeout=2.0)
        except Exception:
            pass

    handle_local_deb_install(
        source_path=source_path,
        board=board,
        log=log,
        update_system=update_system,
        menu_manager=menu_manager,
    )

