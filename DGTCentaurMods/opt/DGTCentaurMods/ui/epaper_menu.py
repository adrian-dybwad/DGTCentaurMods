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
) -> Optional[str]:
    """
    E-paper list menu compatible with DGTCentaurMods epd2in9d driver.
    Uses epd.display(...) for full frames and epd.DisplayPartial(...) for updates.
    Applies the repo's standard flip pipeline before sending the buffer.
    """
    from DGTCentaurMods.display import epd2in9d
    from DGTCentaurMods.display.ui_components import AssetManager

    # --- fonts ----------------------------------------------------------------
    def load_font(sz: int):
        try:
            return ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), sz)
        except Exception:
            # fallback
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", sz)

    font = load_font(font_size)
    font_small = load_font(font_size - 2)

    # --- sanitize + sort SSIDs ------------------------------------------------
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

    # --- init display ----------------------------------------------------------
    epd = epd2in9d.EPD()
    epd.init()
    try:
        epd.Clear(0xFF)
    except Exception:
        pass

    # many drivers report width/height swapped; trust what the repo uses elsewhere:
    W, H = epd.width, epd.height  # typically 128 x 296 for 2.9" panel

    # --- helpers ---------------------------------------------------------------
    def _flip_for_panel(img: Image.Image) -> Image.Image:
        # Match the rest of the project (board.py etc.)
        return img.transpose(Image.FLIP_TOP_BOTTOM).transpose(Image.FLIP_LEFT_RIGHT)

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

    # Compute how many rows actually fit
    margin = 6
    line_h = font_size + 4
    title_h = font_size + 6
    list_top = margin + title_h
    rows = max(3, min(lines_per_page, (H - list_top - margin) // line_h))

    def _build_frame(idx: int) -> Image.Image:
        img = Image.new("1", (W, H), 255)
        draw = ImageDraw.Draw(img)

        # title
        draw.text((margin, margin), title, font=font_small, fill=0)

        # page slice
        start = (idx // rows) * rows
        slice_ = items[start : start + rows]

        # items
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
            draw.text((x, y), _truncate(it, max_px), font=font, fill=fill)
            y += line_h

        # footer
        page = (idx // rows) + 1
        pages = (len(items) + rows - 1) // rows
        footer = f"{page}/{pages}  ↑↓ select, ← back"
        fw = font_small.getlength(footer)
        draw.text((W - margin - fw, H - margin - (font_size - 2)), footer, font=font_small, fill=0)
        return img

    # --- first full frame ------------------------------------------------------
    i = max(0, min(highlight_index, len(items) - 1))
    base = _build_frame(i)
    base = _flip_for_panel(base)
    epd.display(epd.getbuffer(base))  # note: 'display', not 'DisplayPartial'

    last_i = i
    last_paint = 0.0

    # --- loop ------------------------------------------------------------------
    while True:
        act = poll_action()
        if act is None:
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

        # only repaint when changed
        now = time.time()
        if i != last_i and (now - last_paint) >= 0.05:
            frame = _build_frame(i)
            frame = _flip_for_panel(frame)
            try:
                epd.DisplayPartial(epd.getbuffer(frame))  # correct method/case for this repo
            except Exception:
                # Some variants require another full refresh
                epd.display(epd.getbuffer(frame))
            last_i = i
            last_paint = now

    # (no sleep/DevExit here intentionally; the calling code may continue using e-paper)
