# DGTCentaurMods/ui/epaper_menu.py
from PIL import Image, ImageDraw, ImageFont

def select_from_list_epaper(
    options,
    title="Select Wi-Fi",
    poll_action=lambda: None,
    highlight_index=0,
    lines_per_page=7,
    font_size=18,
    rotation=270,              # <— try 0/90/180/270; many Waveshare 2.9" need 270
):
    from DGTCentaurMods.display import epd2in9d
    from DGTCentaurMods.display.ui_components import AssetManager

    def _load_font(size):
        from PIL import ImageFont
        try:
            return ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), size)
        except Exception:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)

    font = _load_font(font_size)
    font_small = _load_font(font_size - 2)

    epd = epd2in9d.EPD()
    epd.init()

    # Use the panel's native geometry (no guessing)
    W, H = epd.width, epd.height  # as reported by driver
    imgW, imgH = W, H             # we draw in native, then rotate at flush()

    def flush(pil_img):
        # rotate before sending to panel
        if rotation:
            pil_img = pil_img.rotate(rotation, expand=True)
        epd.display(epd.getbuffer(pil_img))

    # layout in native space
    margin = 6
    line_h = font_size + 4
    title_h = font_size + 6
    list_top = margin + title_h
    usable_rows = max(3, min(lines_per_page, (imgH - list_top - margin) // line_h))

    # ... keep your _truncate(...) from before ...

    def render(idx, items):
        page_start = (idx // usable_rows) * usable_rows
        page_items = items[page_start: page_start + usable_rows]

        img = Image.new("1", (imgW, imgH), 255)
        draw = ImageDraw.Draw(img)

        draw.text((margin, margin), title, font=font_small, fill=0)

        x = margin
        y = list_top
        max_px = imgW - margin*2 - 6
        for i, item in enumerate(page_items):
            is_sel = (page_start + i) == idx
            if is_sel:
                draw.rectangle([x-2, y-2, imgW - margin, y + line_h - 2], fill=0)
                fill = 255
            else:
                fill = 0
            draw.text((x, y), _truncate(item, max_px), font=font, fill=fill)
            y += line_h

        page = (idx // usable_rows) + 1
        pages = (len(items) + usable_rows - 1) // usable_rows
        footer = f"{page}/{pages}  ↑↓ select, ← back"
        fw = font_small.getlength(footer)
        draw.text((imgW - margin - fw, imgH - margin - (font_size - 2)), footer, font=font_small, fill=0)

        flush(img)

    # sanitize options
    xs = []
    seen = set()
    for s in options:
        s = (s or "").strip() or "<hidden>"
        if s.lower() not in seen:
            xs.append(s); seen.add(s.lower())
    xs.sort(key=str.casefold)

    i = max(0, min(highlight_index, len(xs) - 1))
    render(i, xs)

    try:
        while True:
            act = poll_action()
            if act is None:
                continue
            if act == "UP" and i > 0:
                i -= 1; render(i, xs)
            elif act == "DOWN" and i < len(xs)-1:
                i += 1; render(i, xs)
            elif act == "SELECT":
                try: epd.sleep()
                except: pass
                return xs[i]
            elif act == "BACK":
                try: epd.sleep()
                except: pass
                return None
    finally:
        try: epd.sleep()
        except: pass
