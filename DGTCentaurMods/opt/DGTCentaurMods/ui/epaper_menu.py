# DGTCentaurMods/ui/epaper_menu.py

from PIL import Image, ImageDraw, ImageFont
from DGTCentaurMods.display import epd2in9d
from DGTCentaurMods.display.ui_components import AssetManager
import os
from typing import Callable, Iterable, List, Optional

# ----- font loader with safe fallback -----
def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), size)
    except Exception:
        # Debian/RPi default
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)

# Action names your input poller should return
# "UP", "DOWN", "SELECT", "BACK", or None (no input yet)
InputPoller = Callable[[], Optional[str]]

def select_from_list_epaper(
    options: Iterable[str],
    title: str = "Select Wi-Fi",
    poll_action: InputPoller = lambda: None,
    highlight_index: int = 0,
    lines_per_page: int = 7,
    font_size: int = 18,
) -> Optional[str]:
    """
    Render a scrollable list of options on the e-paper display and navigate
    with a simple input poller. Returns the selected string or None if cancelled.

    poll_action(): must return one of {"UP","DOWN","SELECT","BACK"} or None
    when no input is available on that tick.
    """

    # sanitize & sort (skip empty SSIDs, or label them "<hidden>")
    clean: List[str] = []
    for s in options:
        s = (s or "").strip()
        clean.append(s if s else "<hidden>")
    clean = sorted(set(clean), key=str.casefold)
    if not clean:
        return None

    font = _load_font(font_size)
    font_small = _load_font(font_size - 2)

    # init display
    epd = epd2in9d.EPD()
    epd.init()
    width, height = epd.height, epd.width  # epd2in9d uses rotated coords
    # You can swap depending on your driver’s orientation:
    # width, height = epd.width, epd.height

    # simple theming
    margin = 6
    line_h = font_size + 4
    list_top = margin + (font_size + 6)  # leave room for title
    usable_rows = max(3, min(lines_per_page, (height - list_top - margin) // line_h))

    def _truncate(text: str, max_px: int) -> str:
        if font.getlength(text) <= max_px:
            return text
        ell = "…"
        # binary-shrink
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi) // 2
            test = text[:mid] + ell
            if font.getlength(test) <= max_px:
                lo = mid + 1
            else:
                hi = mid
        return text[:max(0, lo - 1)] + ell

    def render(idx: int) -> None:
        page_start = (idx // usable_rows) * usable_rows
        page_items = clean[page_start: page_start + usable_rows]
        img = Image.new("1", (width, height), 255)  # 1-bit white
        draw = ImageDraw.Draw(img)

        # title
        draw.text((margin, margin), title, font=font_small, fill=0)

        # items
        x = margin
        y = list_top
        max_text_px = width - margin*2 - 6
        for i, item in enumerate(page_items):
            is_sel = (page_start + i) == idx
            # selection bar
            if is_sel:
                draw.rectangle([x-2, y-2, width - margin, y + line_h - 2], fill=0, outline=0)
                fill_text = 255
            else:
                fill_text = 0
            draw.text((x, y), _truncate(item, max_text_px), font=font, fill=fill_text)
            y += line_h

        # footer / page indicator
        page = (idx // usable_rows) + 1
        pages = (len(clean) + usable_rows - 1) // usable_rows
        footer = f"{page}/{pages}  ↑↓ select, ← back"
        fw = font_small.getlength(footer)
        draw.text((width - margin - fw, height - margin - (font_size - 2)), footer, font=font_small, fill=0)

        # push to panel
        epd.display(epd.getbuffer(img))

    # initial paint
    i = max(0, min(highlight_index, len(clean) - 1))
    render(i)

    try:
        idle_ticks = 0
        while True:
            act = poll_action()
            if act is None:
                # small idle refresh throttle (optional)
                idle_ticks += 1
                if idle_ticks % 1000 == 0:
                    # partial refresh to mitigate ghosting (if supported)
                    render(i)
                continue

            idle_ticks = 0

            if act == "UP":
                if i > 0:
                    i -= 1
                    render(i)
            elif act == "DOWN":
                if i < len(clean) - 1:
                    i += 1
                    render(i)
            elif act == "SELECT":
                # clean up display state (optional: sleep)
                try:
                    epd.sleep()
                except Exception:
                    pass
                return clean[i]
            elif act == "BACK":
                try:
                    epd.sleep()
                except Exception:
                    pass
                return None
            # ignore unknowns and keep polling
    finally:
        try:
            epd.sleep()
        except Exception:
            pass
