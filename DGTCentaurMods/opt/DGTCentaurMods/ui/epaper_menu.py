from typing import Iterable, Optional, Callable, List
from PIL import Image, ImageDraw, ImageFont
import time
import logging

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
    from DGTCentaurMods.display import epd2in9d
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
    try:
        epd = epd2in9d.EPD()
        epd.init()
        try:
            epd.Clear(0xFF)
        except Exception as e:
            logging.warning(f"Failed to clear epaper display: {e}")
    except Exception as e:
        logging.error(f"Failed to initialize epaper display: {e}")
        return None

    # Hardcode the working canvas (matches other code paths)
    W, H = 128, 296

    def _flip(img: Image.Image) -> Image.Image:
        return img.transpose(Image.FLIP_TOP_BOTTOM).transpose(Image.FLIP_LEFT_RIGHT)

    # Some panels ignore first draw after Clear; push a solid white frame twice
    def _kick():
        blank = Image.new("1", (W, H), 255)
        epd.display(epd.getbuffer(_flip(blank)))
        time.sleep(0.15)
        epd.display(epd.getbuffer(_flip(blank)))
        time.sleep(0.05)

    _kick()

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
    epd.display(epd.getbuffer(_flip(base)))
    # Some panels still need a second identical full draw
    time.sleep(0.1)
    epd.display(epd.getbuffer(_flip(base)))

    # ----- loop ---------------------------------------------------------------
    last_i = i
    last_paint = 0.0
    start_time = time.time()

    while True:
        # Check for timeout
        if time.time() - start_time > timeout_seconds:
            logging.warning("select_from_list_epaper timed out")
            return None
        
        try:
            act = poll_action()
        except Exception as e:
            logging.error(f"Error in poll_action: {e}")
            time.sleep(0.1)
            continue
            
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

        now = time.time()
        if i != last_i and (now - last_paint) >= 0.05:
            frame = _frame(i)
            try:
                epd.DisplayPartial(epd.getbuffer(_flip(frame)))
            except Exception as e:
                # Fallback: full update
                logging.warning(f"DisplayPartial failed, falling back to full update: {e}")
                try:
                    epd.display(epd.getbuffer(_flip(frame)))
                except Exception as e2:
                    logging.error(f"Both DisplayPartial and display failed: {e2}")
            last_i = i
            last_paint = now
