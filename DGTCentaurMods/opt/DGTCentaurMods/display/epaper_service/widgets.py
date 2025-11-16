from __future__ import annotations

import time
import threading
from typing import Iterable, Optional

from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.board import board
from DGTCentaurMods.display.ui_components import AssetManager

from . import service
from .regions import Region

ROW_HEIGHT = 20
STATUS_BAR_HEIGHT = 20
TITLE_GAP = 4
TITLE_HEIGHT = 20
TITLE_TOP = STATUS_BAR_HEIGHT + TITLE_GAP
MENU_FIRST_ROW_TOP = TITLE_TOP + TITLE_HEIGHT

FONT_18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
CHESS_FONT = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
LOGO = Image.open(AssetManager.get_resource_path("logo_mods_screen.jpg"))
QR = Image.open(AssetManager.get_resource_path("qr-support.png")).resize((128, 128))
_STANDBY_SNAPSHOT: Optional[Image.Image] = None


def write_text_at(top: int, text: str, *, inverted: bool = False) -> None:
    region = Region(0, top, 128, top + ROW_HEIGHT)
    with service.acquire_canvas() as canvas:
        draw = canvas.draw
        fill, fg = (0, 255) if inverted else (255, 0)
        draw.rectangle(region.to_box(), fill=fill, outline=fill)
        draw.text((0, top - 1), text, font=FONT_18, fill=fg)
        canvas.mark_dirty(region)
    service.submit_region(region)


def write_text(row: int, text: str, *, inverted: bool = False) -> None:
    write_text_at(row * ROW_HEIGHT, text, inverted=inverted)


def write_menu_title(title: str) -> None:
    write_text_at(TITLE_TOP, title, inverted=True)


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


def draw_board(fen: str, top: int = 40, *, flip: bool = False) -> None:
    ordered = _expand_fen(fen.split()[0])
    region = Region(0, top, 128, top + 128)
    with service.acquire_canvas() as canvas:
        draw = canvas.draw
        draw.rectangle(region.to_box(), fill=255, outline=255)
        for idx, symbol in enumerate(ordered):
            rank = idx // 8
            file = idx % 8
            dest_rank = rank if not flip else 7 - rank
            dest_file = file if not flip else 7 - file
            px = _piece_x(symbol)
            square_index = dest_rank * 8 + dest_file
            py = 16 if _is_dark_square(square_index) else 0
            piece = CHESS_FONT.crop((px, py, px + 16, py + 16))
            x = dest_file * 16
            y = top + (dest_rank * 16)
            canvas.image.paste(piece, (x, y))
        draw.rectangle(region.to_box(), fill=None, outline=0)
        canvas.mark_dirty(region)
    service.submit_region(region)


def draw_fen(fen: str, start_row: int = 2, *, flip: bool = False) -> None:
    draw_board(fen, top=((start_row * 20) + 8), flip=flip)


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

    def print(self) -> None:
        self.print_once()

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
        canvas.draw.rectangle(region.to_box(), fill=255, outline=255)
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


def _expand_fen(fen: str) -> list[str]:
    rows = fen.split("/")
    expanded: list[str] = []
    for row in rows:
        for char in row:
            if char.isdigit():
                expanded.extend([" "] * int(char))
            else:
                expanded.append(char)
    if len(expanded) != 64:
        raise ValueError(f"Invalid FEN: {fen}")
    return expanded

