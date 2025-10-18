# DGTCentaurMods/ui/epaper_menu.py
from typing import Iterable, Optional, Callable, List
from PIL import Image, ImageDraw, ImageFont
import time

ActionPoller = Callable[[], Optional[str]]  # returns "UP"/"DOWN"/"SELECT"/"BACK"/None

def select_from_list_epaper(
    options: Iterable[str],
    title: str = "Select Wi-Fi",
    poll_action: ActionPoller = lambda: None,
    highlight_index: int = 0,
    lines_per_page: int = 7,
    font_size: int = 18,
    rotation: int = 270,  # 0/90/180/270 — set what looks correct on your unit
) -> Optional[str]:
    from DGTCentaurMods.display import epd2in9d
    from DGTCentaurMods.display.ui_components import AssetManager

    def load_font(sz: int):
        try:
            return ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), sz)
        except Exception:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", sz)

    font = load_font(font_size)
    font_small = load_font(font_size - 2)

    # sanitize & sort SSIDs once
    items: List[str] = []
    seen = set()
    for s in options:
        s = (s or "").strip() or "<hidden>"
        key = s.casefold()
        if key not in seen:
            items.append(s)
            seen.add(key)
    items.sort(key=str.casefold)
    if not items:
        return None

    epd = epd2in9d.EPD()
    try:
        # 1) Init once and HARD clear to full-white
        epd.init()                # FULL update mode
        try:
            epd.Clear(0xFF)       # many drivers support this
        except Exception:
            pass

        W, H = epd.width, epd.height

        # draw helpers ---------------------------------------------------------
        def truncate(text: str, max_px: int) -> str:
            # fast-fit with Pillow 10’s getlength()
            if font.getlength(text) <= max_px:
                return text
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi) // 2
                test = text[:mid] + "…"
                if font.getlength(test) <= max_px:
                    lo = mid + 1
                else:
                    hi = mid
            return text[:max(0, lo - 1)] + "…"

        def build_frame(idx: int):
            # Build a full frame (we’ll send it either as base or partial)
            img = Image.new("1", (W, H), 255)
            draw = ImageDraw.Draw(img)

            margin = 6
            line_h = font_size + 4
            title_h = font_size + 6
            list_top = margin + title_h
            rows = max(3, min(lines_per_page, (H - list_top - margin) // line_h))

            # Title
            draw.text((margin, margin), title, font=font_small, fill=0)

            # Page slice
            start = (idx // rows) * rows
            slice_ = items[start : start + rows]

            # Items
            x = margin
            y = list_top
            max_px = W - margin * 2 - 6
            for i, it in enumerate(slice_):
                sel = (start + i) == idx
                if sel:
                    draw.rectangle([x - 2, y - 2, W - margin, y + line_h - 2], fill=0)
                    fill = 255
                else:
                    fill = 0
                draw.text((x, y), truncate(it, max_px), font=font, fill=fill)
                y += line_h

            # Footer
            page = (idx // rows) + 1
            pages = (len(items) + rows - 1) // rows
            footer = f"{page}/{pages}  ↑↓ select, ← back"
            fw = font_small.getlength(footer)
            draw.text((W - margin - fw, H - margin - (font_size - 2)), footer, font=font_small, fill=0)

            if rotation:
                img = img.rotate(rotation, expand=True)

            return img
        # ----------------------------------------------------------------------

        # 2) Draw base once, then switch to partial mode
        i = max(0, min(highlight_index, len(items) - 1))
        base = build_frame(i)
        # Send base as a full frame
        epd.display(epd.getbuffer(base))

        # Try to enter partial mode (driver-specific). If not present, keep full.
        has_partial = False
        try:
            # common “partial init” symbol on many WS drivers:
            epd.init(epd.PART_UPDATE)
            has_partial = True
        except Exception:
            # fall back to full updates (slower; still works)
            pass

        last_i = i
        last_paint = 0.0

        while True:
            act = poll_action()
            if act is None:
                # small sleep to avoid 100% CPU and to keep serial responsive
                time.sleep(0.02)
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

            # only redraw when idx actually changes, and debounce a tad
            now = time.time()
            if i != last_i and (now - last_paint) >= 0.05:
                frame = build_frame(i)
                if has_partial and hasattr(epd, "displayPartial"):
                    epd.displayPartial(epd.getbuffer(frame))
                else:
                    epd.display(epd.getbuffer(frame))
                last_i = i
                last_paint = now

    finally:
        # 3) Always release the panel cleanly
        try:
            epd.sleep()
        except Exception:
            pass
        try:
            epd.DevExit()  # releases GPIO/SPI on many drivers
        except Exception:
            pass
