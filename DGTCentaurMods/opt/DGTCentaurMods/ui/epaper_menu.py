from typing import Iterable, Optional, Callable, List
from PIL import Image, ImageDraw, ImageFont
import time
import signal
import sys
import os
from DGTCentaurMods.board.logging import log

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle CTRL+C gracefully"""
    global shutdown_requested
    print("\nShutdown requested...")
    shutdown_requested = True
    # Force exit immediately
    os._exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

ActionPoller = Callable[[], Optional[str]]  # "UP"/"DOWN"/"SELECT"/"BACK"/None

def select_from_list_epaper(
    options: Iterable[str],
    title: str = "Select Wi-Fi",
    poll_action: ActionPoller = lambda: None,
    highlight_index: int = 0,
    lines_per_page: int = 7,
    font_size: int = 18,
    timeout_seconds: float = 300.0,  # 5 minute timeout
) -> Optional[str]:
    from DGTCentaurMods.display.ui_components import AssetManager

    # ----- fonts --------------------------------------------------------------
    def load_font(sz: int):
        try:
            return ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), sz)
        except Exception:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", sz)

    font = load_font(font_size)
    font_small = load_font(font_size - 2)

    # ----- sanitize list ------------------------------------------------------
    items: List[str] = []
    seen = set()
    for s in options:
        s = (s or "").strip() or "<hidden>"
        k = s.casefold()
        if k not in seen:
            items.append(s)
            seen.add(k)
    items.sort(key=str.casefold)
    if not items:
        return None

    # ----- init panel ---------------------------------------------------------
    # Use the existing display system instead of creating a new instance
    try:
        from DGTCentaurMods.display import epaper
        epaper.initEpaper()
        epaper.clearScreen()
        # Give the display time to initialize properly
        time.sleep(0.2)
    except Exception as e:
        log.error(f"Failed to initialize epaper display: {e}")
        return None

    # Hardcode the working canvas (matches other code paths)
    W, H = 128, 296

    # Some panels ignore first draw after Clear; push a solid white frame twice
    # No need for _kick() when using the existing display system

    # ----- layout helpers -----------------------------------------------------
    margin = 6
    line_h = font_size + 4
    title_h = font_size + 6
    list_top = margin + title_h
    rows = max(3, min(lines_per_page, (H - list_top - margin) // line_h))

    def _truncate(text: str, max_px: int) -> str:
        if font.getlength(text) <= max_px:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi) // 2
            t = text[:mid] + "…"
            if font.getlength(t) <= max_px:
                lo = mid + 1
            else:
                hi = mid
        return text[:max(0, lo - 1)] + "…"

    def _frame(idx: int) -> Image.Image:
        img = Image.new("1", (W, H), 255)
        draw = ImageDraw.Draw(img)

        # Title
        draw.text((margin, margin), title, font=font_small, fill=0)

        # Slice
        start = (idx // rows) * rows
        sl = items[start : start + rows]

        # Items
        x = margin
        y = list_top
        max_px = W - margin * 2 - 6
        for i, it in enumerate(sl):
            sel = (start + i) == idx
            if sel:
                draw.rectangle([x - 2, y - 2, W - margin, y + line_h - 2], fill=0)
                fill = 255
            else:
                fill = 0
            draw.text((x, y), _truncate(it, max_px), font=font, fill=fill)
            y += line_h

        # Footer
        page = (idx // rows) + 1
        pages = (len(items) + rows - 1) // rows
        footer = f"{page}/{pages}  ↑↓ select, ← back"
        fw = font_small.getlength(footer)
        draw.text((W - margin - fw, H - margin - (font_size - 2)), footer, font=font_small, fill=0)
        return img

    # ----- first full paint ---------------------------------------------------
    i = max(0, min(highlight_index, len(items) - 1))
    base = _frame(i)
    # Use the existing epaper system to display the frame
    epaper.epaperbuffer.paste(base, (0, 0))
    # Don't call refresh() - let the background thread handle updates

    # ----- loop ---------------------------------------------------------------
    last_i = i
    last_paint = 0.0
    start_time = time.time()

    # Check if poll_action is working at all
    test_attempts = 0
    max_test_attempts = 10
    while test_attempts < max_test_attempts:
        try:
            act = poll_action()
            if act is not None:
                break  # Polling is working
        except Exception as e:
            log.error(f"Error in poll_action test: {e}")
        test_attempts += 1
        time.sleep(0.1)
    
    if test_attempts >= max_test_attempts:
        log.warning("Poll action not responding, using fallback selection")
        # Fallback: return first item after a delay
        time.sleep(2.0)
        return items[0] if items else None

    while True:
        # Check for shutdown request
        if shutdown_requested:
            log.info("Menu selection cancelled by user")
            return None
            
        # Check for timeout
        if time.time() - start_time > timeout_seconds:
            log.warning("select_from_list_epaper timed out")
            return None
        
        try:
            act = poll_action()
        except Exception as e:
            log.error(f"Error in poll_action: {e}")
            time.sleep(0.1)
            continue
            
        if act is None:
            time.sleep(0.01)  # Reduced sleep for better responsiveness
            continue

        if act == "UP" and i > 0:
            i -= 1
        elif act == "DOWN" and i < len(items) - 1:
            i += 1
        elif act == "BACK":
            return None
        elif act == "SELECT":
            return items[i]
        else:
            continue

        now = time.time()
        if i != last_i and (now - last_paint) >= 0.05:  # Reduced delay for better responsiveness
            frame = _frame(i)
            try:
                # Use the existing epaper system to update the display
                epaper.epaperbuffer.paste(frame, (0, 0))
                # Don't call refresh() - let the background thread handle updates
                # The epaperUpdate thread will automatically detect changes and update
                # Reduced delay for better responsiveness
                time.sleep(0.01)
            except Exception as e:
                log.error(f"Failed to update epaper display: {e}")
            last_i = i
            last_paint = now
