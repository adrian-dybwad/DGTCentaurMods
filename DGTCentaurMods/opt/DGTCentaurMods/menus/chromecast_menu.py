"""Chromecast menu helpers."""

import time
from typing import List, Callable, Optional

from DGTCentaurMods.epaper.icon_menu import IconMenuEntry
from DGTCentaurMods.managers.menu import MenuSelection, is_break_result
from DGTCentaurMods.epaper import SplashScreen


def handle_chromecast_menu(
    show_menu: Callable[[List[IconMenuEntry]], str],
    board,
    log,
    get_chromecast_service,
) -> Optional[MenuSelection]:
    """Handle Chromecast menu - discover and stream to Chromecast devices."""
    cc_service = get_chromecast_service()

    if cc_service.is_active:
        device = cc_service.device_name or "Unknown"
        display_device = device[:16] if len(device) > 16 else device
        entries = [
            IconMenuEntry(key="STOP", label=f"Stop: {display_device}", icon_name="cast", enabled=True),
            IconMenuEntry(key="CHANGE", label="Change Device", icon_name="cast", enabled=True),
        ]
        result = show_menu(entries)
        if is_break_result(result):
            return result
        if result in ["BACK", "SHUTDOWN", "HELP"]:
            return None
        if result == "STOP":
            cc_service.stop_streaming()
            log.info("[Chromecast] Streaming stopped by user")
            board.display_manager.clear_widgets()
            promise = board.display_manager.add_widget(SplashScreen(board.display_manager.update, message="Streaming\nstopped"))
            if promise:
                try:
                    promise.result(timeout=2.0)
                except Exception:
                    pass
            time.sleep(1)
            board.beep(board.SOUND_GENERAL)
            return None

    board.display_manager.clear_widgets()
    promise = board.display_manager.add_widget(
        SplashScreen(board.display_manager.update, message="Discovering\nChromecasts...")
    )
    if promise:
        try:
            promise.result(timeout=2.0)
        except Exception:
            pass

    try:
        import pychromecast
        chromecasts, browser = pychromecast.get_chromecasts()
    except ImportError:
        log.error("[Chromecast] pychromecast library not installed")
        board.display_manager.clear_widgets()
        promise = board.display_manager.add_widget(
            SplashScreen(board.display_manager.update, message="pychromecast\nnot installed")
        )
        if promise:
            try:
                promise.result(timeout=2.0)
            except Exception:
                pass
        time.sleep(2)
        return None
    except Exception as e:
        log.error(f"[Chromecast] Discovery failed: {e}")
        board.display_manager.clear_widgets()
        promise = board.display_manager.add_widget(
            SplashScreen(board.display_manager.update, message="Discovery\nfailed")
        )
        if promise:
            try:
                promise.result(timeout=2.0)
            except Exception:
                pass
        time.sleep(2)
        return None

    cast_entries = []
    for cc in chromecasts:
        if cc.device.cast_type == "cast":
            friendly_name = cc.device.friendly_name
            cast_entries.append(
                IconMenuEntry(key=friendly_name, label=friendly_name, icon_name="cast", enabled=True)
            )

    try:
        browser.stop_discovery()
    except Exception:
        pass

    if not cast_entries:
        log.info("[Chromecast] No Chromecast devices found")
        board.display_manager.clear_widgets()
        promise = board.display_manager.add_widget(
            SplashScreen(board.display_manager.update, message="No Chromecasts\nfound")
        )
        if promise:
            try:
                promise.result(timeout=2.0)
            except Exception:
                pass
        time.sleep(2)
        return None

    log.info(f"[Chromecast] Found {len(cast_entries)} device(s)")
    result = show_menu(cast_entries)
    if is_break_result(result):
        return result
    if result in ["BACK", "SHUTDOWN", "HELP"]:
        return None

    # Start streaming to selected device
    board.display_manager.clear_widgets()
    promise = board.display_manager.add_widget(
        SplashScreen(board.display_manager.update, message="Connecting...\nPlease wait")
    )
    if promise:
        try:
            promise.result(timeout=2.0)
        except Exception:
            pass

    try:
        cc_service.start_streaming(result)
        log.info(f"[Chromecast] Streaming started on: {result}")
        board.display_manager.clear_widgets()
        promise = board.display_manager.add_widget(
            SplashScreen(board.display_manager.update, message=f"Streaming to:\n{result[:16]}")
        )
        if promise:
            try:
                promise.result(timeout=2.0)
            except Exception:
                pass
        time.sleep(1)
        board.beep(board.SOUND_GENERAL)
    except Exception as e:
        log.error(f"[Chromecast] Streaming failed: {e}")
        board.display_manager.clear_widgets()
        promise = board.display_manager.add_widget(
            SplashScreen(board.display_manager.update, message="Streaming\nfailed")
        )
        if promise:
            try:
                promise.result(timeout=2.0)
            except Exception:
                pass
        time.sleep(2)
    return None

