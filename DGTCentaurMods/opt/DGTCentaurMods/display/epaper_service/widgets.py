from __future__ import annotations

import time
import threading
from typing import Iterable, Optional

from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.board import board
from DGTCentaurMods.display.ui_components import AssetManager

from . import service
from .regions import Region

ROW_HEIGHT = 20  # legacy row height used by much of the codebase
STATUS_BAR_HEIGHT = 16
STATUS_FONT = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 14)
TITLE_GAP = 8
TITLE_HEIGHT = 24
TITLE_TOP = STATUS_BAR_HEIGHT + TITLE_GAP
MENU_TOP = TITLE_TOP + TITLE_HEIGHT
MENU_ROW_HEIGHT = 24

FONT_18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
CHESS_FONT = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
LOGO = Image.open(AssetManager.get_resource_path("logo_mods_screen.jpg"))
QR = Image.open(AssetManager.get_resource_path("qr-support.png")).resize((128, 128))
_STANDBY_SNAPSHOT: Optional[Image.Image] = None


def draw_status_bar(text: str) -> None:
    """
    Draw status bar with text and battery icon atomically.
    
    Only refreshes the status bar region (top 16 pixels), not the whole screen.
    """
    region = Region(0, 0, 128, STATUS_BAR_HEIGHT)
    with service.acquire_canvas() as canvas:
        # Draw status bar background and text
        canvas.draw.rectangle(region.to_box(), fill=255, outline=255)
        canvas.draw.text((2, -1), text, font=STATUS_FONT, fill=0)
        # Draw battery icon in same canvas operation (atomic)
        _draw_battery_icon_to_canvas(canvas, top_padding=1)
        canvas.mark_dirty(region)
    # Only refresh the status bar region (top 16 pixels)
    service.submit_region(region, await_completion=False)


def write_text_at(top: int, text: str, *, inverted: bool = False, height: int = ROW_HEIGHT) -> None:
    region = Region(0, top, 128, top + height)
    with service.acquire_canvas() as canvas:
        draw = canvas.draw
        fill, fg = (0, 255) if inverted else (255, 0)
        draw.rectangle(region.to_box(), fill=fill, outline=fill)
        draw.text((0, top - 1), text, font=FONT_18, fill=fg)
        canvas.mark_dirty(region)
    service.submit_region(region)


def write_text(row: int, text: str, *, inverted: bool = False) -> None:
    write_text_at(row * ROW_HEIGHT, text, inverted=inverted, height=ROW_HEIGHT)


def write_menu_title(title: str) -> None:
    write_text_at(TITLE_TOP, title, inverted=True, height=TITLE_HEIGHT)


def draw_menu_entry(top: int, text: str, *, selected: bool = False) -> None:
    write_text_at(top, text, inverted=selected, height=MENU_ROW_HEIGHT)


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
    from DGTCentaurMods.board.logging import log
    log.info(">>> widgets.clear_screen() ENTERED")
    width, height = service.size
    log.info(f">>> widgets.clear_screen() size={width}x{height}")
    region = Region.full(width, height)
    log.info(">>> widgets.clear_screen() acquiring canvas")
    with service.acquire_canvas() as canvas:
        canvas.draw.rectangle(region.to_box(), fill=255, outline=255)
        canvas.mark_dirty(region)
    log.info(">>> widgets.clear_screen() canvas released, calling service.submit_full(await_completion=True)")
    service.submit_full(await_completion=True)
    log.info(">>> widgets.clear_screen() service.submit_full() complete, EXITING")


def draw_board(fen: str, top: int = 40, *, flip: bool = False) -> None:
    from DGTCentaurMods.board.logging import log
    log.info(f">>> widgets.draw_board() ENTERED fen='{fen}', top={top}, flip={flip}")
    ordered = _expand_fen(fen.split()[0])
    region = Region(0, top, 128, top + 128)
    log.info(f">>> widgets.draw_board() region={region}, acquiring canvas")
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
    log.info(">>> widgets.draw_board() canvas released, calling service.submit_region(await_completion=False)")
    service.submit_region(region, await_completion=False)
    log.info(">>> widgets.draw_board() service.submit_region() queued, EXITING")


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
    """
    Display shutdown screen with logo and QR code.
    
    All 4 agents agreed: Must await completion to ensure screen displays
    before system powers off.
    """
    region = Region(0, 0, 128, 296)
    with service.acquire_canvas() as canvas:
        canvas.image.paste(LOGO, (0, 0))
        canvas.image.paste(QR, (0, 160))
        canvas.mark_dirty(region)
    service.submit_full(await_completion=True)


class StatusBar:
    """Simple helper that prints time + battery indicator."""

    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def build(self) -> str:
        clock = time.strftime("%H:%M")
        return clock

    def print_once(self) -> None:
        draw_status_bar(self.build())

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
        """
        Status bar update loop.
        
        Per Phase 2 fix: Sleep first before printing to avoid immediate refresh
        on start that interferes with menu display. This prevents the statusbar
        from submitting a partial refresh immediately when start() is called,
        which was causing race conditions with menu full refreshes.
        """
        # Sleep first to avoid immediate refresh on start
        # This prevents interference with menu display when statusbar.start() is called
        time.sleep(30)
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


def welcome_screen(status_text: str = "READY") -> None:
    from DGTCentaurMods.board.logging import log
    log.info(f">>> widgets.welcome_screen() ENTERED with status_text='{status_text}'")
    region = Region(0, 0, 128, 296)
    log.info(f">>> widgets.welcome_screen() region={region}, acquiring canvas")
    with service.acquire_canvas() as canvas:
        draw = canvas.draw
        # Draw status bar
        status_region = Region(0, 0, 128, STATUS_BAR_HEIGHT)
        draw.rectangle(status_region.to_box(), fill=255, outline=255)
        draw.text((2, -1), status_text, font=STATUS_FONT, fill=0)
        # Draw battery icon
        _draw_battery_icon_to_canvas(canvas, top_padding=1)
        # Draw welcome content
        welcome_region = Region(0, STATUS_BAR_HEIGHT, 128, 296)
        draw.rectangle(welcome_region.to_box(), fill=255, outline=255)
        canvas.image.paste(LOGO, (0, STATUS_BAR_HEIGHT + 4))
        draw.text((0, STATUS_BAR_HEIGHT + 180), "   Press [>||]", font=FONT_18, fill=0)
        canvas.mark_dirty(region)
    log.info(">>> widgets.welcome_screen() canvas released, calling service.submit_full(await_completion=True)")
    service.submit_full(await_completion=True)
    log.info(">>> widgets.welcome_screen() service.submit_full() complete, EXITING")


def standby_screen(show: bool) -> None:
    global _STANDBY_SNAPSHOT
    if show:
        _STANDBY_SNAPSHOT = service.snapshot()
        loading_screen()
    else:
        if _STANDBY_SNAPSHOT is not None:
            service.blit(_STANDBY_SNAPSHOT, 0, 0)
            _STANDBY_SNAPSHOT = None


def _draw_battery_icon(top_padding: int = 2) -> None:
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
    draw_image(image, 98, top_padding)


def _draw_battery_icon_to_canvas(canvas, top_padding: int = 2) -> None:
    """Draw battery icon directly to canvas (for use within canvas context)."""
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
    canvas.image.paste(image, (98, top_padding))


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
    # Invert the formula: (rank + file) % 2 == 1 for dark squares
    # This corrects the color inversion issue where squares were drawn with inverted colors
    # Standard chess: a1 (rank 0, file 0 when flipped) should be dark
    return (rank + file) % 2 == 1


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

