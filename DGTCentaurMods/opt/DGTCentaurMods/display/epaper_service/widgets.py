from __future__ import annotations

import time
import threading
from typing import Iterable, Optional

from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.board import board
from DGTCentaurMods.display.ui_components import AssetManager

from . import service
from .regions import Region

FONT_18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
CHESS_FONT = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
LOGO = Image.open(AssetManager.get_resource_path("logo_mods_screen.jpg"))
QR = Image.open(AssetManager.get_resource_path("qr-support.png")).resize((128, 128))
_STANDBY_SNAPSHOT: Optional[Image.Image] = None


def write_text(row: int, text: str, *, inverted: bool = False) -> None:
    top = row * 20
    region = Region(0, top, 128, top + 20)
    with service.acquire_canvas() as canvas:
        draw = canvas.draw
        fill, fg = (0, 255) if inverted else (255, 0)
        draw.rectangle(region.to_box(), fill=fill, outline=fill)
        draw.text((0, top - 1), text, font=FONT_18, fill=fg)
        canvas.mark_dirty(region)
    service.submit_region(region)


def write_menu_title(title: str) -> None:
    region = Region(0, 20, 128, 40)
    with service.acquire_canvas() as canvas:
        canvas.draw.rectangle(region.to_box(), fill=0, outline=0)
        canvas.draw.text((4, 20), title, font=FONT_18, fill=255)
        canvas.mark_dirty(region)
    service.submit_region(region)


def clear_area(region: Region) -> None:
    with service.acquire_canvas() as canvas:
        canvas.draw.rectangle(region.to_box(), fill=255, outline=255)
        canvas.mark_dirty(region)
    service.submit_region(region)


def draw_rectangle(x1: int, y1: int, x2: int, y2: int, fill: int, outline: int) -> None:
    region = Region(x1, y1, x2, y2)
    with service.acquire_canvas() as canvas:
        canvas.draw.rectangle(region.to_box(), fill=fill, outline=outline)
        canvas.mark_dirty(region)
    service.submit_region(region)


def clear_screen() -> None:
    width, height = service.size
    region = Region.full(width, height)
    with service.acquire_canvas() as canvas:
        canvas.draw.rectangle(region.to_box(), fill=255, outline=255)
        canvas.mark_dirty(region)
    service.submit_full()


def draw_board(fen: str, top: int = 40) -> None:
    curfen = fen.replace("/", "")
    for num in "12345678":
        curfen = curfen.replace(num, " " * int(num))
    ordered = ""
    for rank in range(8, 0, -1):
        for file in range(0, 8):
            ordered += curfen[((rank - 1) * 8) + file]
    region = Region(0, top, 128, top + 128)
    with service.acquire_canvas() as canvas:
        draw = canvas.draw
        draw.rectangle(region.to_box(), fill=255, outline=255)
        for idx in range(64):
            pos = (idx - 63) * -1
            row = top + (16 * (pos // 8))
            col = (idx % 8) * 16
            px = _piece_x(ordered[idx])
            py = 16 if _is_dark_square(idx) else 0
            piece = CHESS_FONT.crop((px, py, px + 16, py + 16))
            canvas.image.paste(piece, (col, row))
        draw.rectangle(region.to_box(), fill=None, outline=0)
        canvas.mark_dirty(region)
    service.submit_region(region)


def draw_fen(fen: str, start_row: int = 2) -> None:
    draw_board(fen, top=((start_row * 20) + 8))


def promotion_options(row: int) -> None:
    offset = row * 20
    region = Region(0, offset, 128, offset + 20)
    with service.acquire_canvas() as canvas:
        draw = canvas.draw
        draw.rectangle(region.to_box(), fill=255, outline=255)
        draw.text((0, offset), "    Q    R    N    B", font=FONT_18, fill=0)
        canvas.mark_dirty(region)
    service.submit_region(region)


def resign_draw_menu(row: int) -> None:
    offset = row * 20
    region = Region(0, offset, 128, offset + 20)
    with service.acquire_canvas() as canvas:
        draw = canvas.draw
        draw.rectangle(region.to_box(), fill=255, outline=255)
        draw.text((0, offset), "    DRW    RESI", font=FONT_18, fill=0)
        draw.polygon([(2, offset + 18), (18, offset + 18), (10, offset + 3)], fill=0)
        draw.polygon([(60, offset + 3), (76, offset + 3), (68, offset + 18)], fill=0)
        canvas.mark_dirty(region)
    service.submit_region(region)


def draw_image(image: Image.Image, x: int, y: int) -> None:
    region = Region(x, y, x + image.width, y + image.height)
    with service.acquire_canvas() as canvas:
        canvas.image.paste(image, (x, y))
        canvas.mark_dirty(region)
    service.submit_region(region)


def shutdown_screen() -> None:
    region = Region(0, 0, 128, 296)
    with service.acquire_canvas() as canvas:
        canvas.image.paste(LOGO, (0, 0))
        canvas.image.paste(QR, (0, 160))
        canvas.mark_dirty(region)
    service.submit_full()


class StatusBar:
    """Simple helper that prints time + battery indicator."""

    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def build(self) -> str:
        clock = time.strftime("%H:%M")
        return clock

    def print_once(self) -> None:
        write_text(0, self.build())
        _draw_battery_icon()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="epaper-status-bar", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None

    def _loop(self) -> None:
        while self._running:
            self.print_once()
            time.sleep(30)


def status_bar() -> StatusBar:
    return StatusBar()


def loading_screen() -> None:
    region = Region(0, 0, 128, 296)
    with service.acquire_canvas() as canvas:
        canvas.image.paste(LOGO, (0, 20))
        draw = canvas.draw
        draw.text((0, 200), "     Loading", font=FONT_18, fill=0)
        canvas.mark_dirty(region)
    service.submit_full()


def welcome_screen() -> None:
    region = Region(0, 0, 128, 296)
    with service.acquire_canvas() as canvas:
        canvas.image.paste(LOGO, (0, 20))
        draw = canvas.draw
        draw.text((0, 200), "   Press [>||]", font=FONT_18, fill=0)
        canvas.mark_dirty(region)
    service.submit_full()


def standby_screen(show: bool) -> None:
    global _STANDBY_SNAPSHOT
    if show:
        _STANDBY_SNAPSHOT = service.snapshot()
        loading_screen()
    else:
        if _STANDBY_SNAPSHOT is not None:
            service.blit(_STANDBY_SNAPSHOT, 0, 0)
            _STANDBY_SNAPSHOT = None


def _draw_battery_icon() -> None:
    indicator = "battery1"
    if board.batterylevel >= 18:
        indicator = "battery4"
    elif board.batterylevel >= 12:
        indicator = "battery3"
    elif board.batterylevel >= 6:
        indicator = "battery2"
    if board.chargerconnected > 0:
        indicator = "batteryc"
        if board.batterylevel == 20:
            indicator = "batterycf"
    path = AssetManager.get_resource_path(f"{indicator}.bmp")
    image = Image.open(path)
    draw_image(image, 98, 2)


def _piece_x(piece: str) -> int:
    mapping = {
        "P": 16,
        "R": 32,
        "N": 48,
        "B": 64,
        "Q": 80,
        "K": 96,
        "p": 112,
        "r": 128,
        "n": 144,
        "b": 160,
        "q": 176,
        "k": 192,
    }
    return mapping.get(piece, 0)


def _is_dark_square(index: int) -> bool:
    rank = index // 8
    file = index % 8
    return (rank + file) % 2 == 0

