"""WiFi utility functions for scan/connect/password entry."""

import subprocess
import time
import re
from typing import Callable, List, Optional

from DGTCentaurMods.epaper import SplashScreen


def scan_wifi_networks(board, log) -> List[dict]:
    """Scan for available WiFi networks using iwlist."""
    networks: List[dict] = []
    board.display_manager.clear_widgets(addStatusBar=False)
    promise = board.display_manager.add_widget(
        SplashScreen(board.display_manager.update, message="Scanning...", leave_room_for_status_bar=False)
    )
    if promise:
        try:
            promise.result(timeout=5.0)
        except Exception:
            pass

    try:
        result = subprocess.run(
            ["sudo", "iwlist", "wlan0", "scan"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        log.debug(f"[WiFi] iwlist return code: {result.returncode}")
        if result.stderr:
            log.debug(f"[WiFi] iwlist stderr: {result.stderr}")

        if result.returncode == 0:
            seen_ssids = set()
            current_ssid = None
            current_signal = 0
            current_security = ""

            for line in result.stdout.split("\n"):
                line = line.strip()
                if line.startswith("Cell "):
                    if current_ssid and current_ssid not in seen_ssids:
                        seen_ssids.add(current_ssid)
                        networks.append(
                            {"ssid": current_ssid, "signal": current_signal, "security": current_security}
                        )
                    current_ssid = None
                    current_signal = 0
                    current_security = ""

                if "ESSID:" in line:
                    match = re.search(r'ESSID:"([^"]*)"', line)
                    if match:
                        current_ssid = match.group(1)

                if "Quality=" in line:
                    match = re.search(r"Quality=(\d+)/(\d+)", line)
                    if match:
                        quality = int(match.group(1))
                        max_quality = int(match.group(2))
                        current_signal = int((quality / max_quality) * 100)

                if "Encryption key:on" in line:
                    current_security = "WPA"

            if current_ssid and current_ssid not in seen_ssids:
                seen_ssids.add(current_ssid)
                networks.append({"ssid": current_ssid, "signal": current_signal, "security": current_security})

            networks.sort(key=lambda x: x["signal"], reverse=True)
            log.info(f"[WiFi] Found {len(networks)} networks")
        else:
            log.error(f"[WiFi] iwlist failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        log.error("[WiFi] Network scan timed out")
    except Exception as e:
        log.error(f"[WiFi] Error scanning networks: {e}")
    return networks


def connect_to_wifi(board, log, ssid: str, password: Optional[str] = None) -> bool:
    """Connect to a WiFi network using nmcli."""
    try:
        board.display_manager.clear_widgets(addStatusBar=False)
        promise = board.display_manager.add_widget(
            SplashScreen(board.display_manager.update, message="Connecting...", leave_room_for_status_bar=False)
        )
        if promise:
            try:
                promise.result(timeout=5.0)
            except Exception:
                pass

        if password:
            result = subprocess.run(
                ["sudo", "nmcli", "device", "wifi", "connect", ssid, "password", password],
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            result = subprocess.run(
                ["sudo", "nmcli", "device", "wifi", "connect", ssid],
                capture_output=True,
                text=True,
                timeout=30,
            )

        if result.returncode == 0:
            log.info(f"[WiFi] Connected to {ssid}")
            board.beep(board.SOUND_GENERAL, event_type="key_press")
            return True

        log.error(f"[WiFi] Failed to connect: {result.stderr}")
        board.beep(board.SOUND_WRONG, event_type="error")
        return False
    except subprocess.TimeoutExpired:
        log.error("[WiFi] Connection timed out")
        board.beep(board.SOUND_WRONG, event_type="error")
        return False
    except Exception as e:
        log.error(f"[WiFi] Error connecting: {e}")
        board.beep(board.SOUND_WRONG, event_type="error")
        return False


def get_wifi_password_from_board(
    board,
    log,
    ssid: str,
    keyboard_factory: Callable[[Callable, str, int], object],
    set_active_keyboard: Callable[[object], None],
    clear_active_keyboard: Callable[[], None],
) -> Optional[str]:
    """Display keyboard widget to collect WiFi password."""
    log.info(f"[WiFi] Opening keyboard for password entry: {ssid}")
    board.display_manager.clear_widgets(addStatusBar=False)
    keyboard = keyboard_factory(board.display_manager.update, f"Password: {ssid[:10]}", 64)
    set_active_keyboard(keyboard)
    promise = board.display_manager.add_widget(keyboard)
    if promise:
        try:
            promise.result(timeout=2.0)
        except Exception:
            pass
    try:
        result = keyboard.wait_for_input(timeout=300.0)
        log.info(f"[WiFi] Keyboard input complete, got {'password' if result else 'cancelled'}")
        return result
    finally:
        clear_active_keyboard()

