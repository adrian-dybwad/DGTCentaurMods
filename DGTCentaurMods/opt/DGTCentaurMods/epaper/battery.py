"""
Battery level indicator widget.

The widget manages its own state by polling the board controller every 5 seconds.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
import threading
import time

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

# Polling interval for battery status (seconds)
BATTERY_POLL_INTERVAL = 5


class BatteryWidget(Widget):
    """Battery level indicator using bitmap icons.
    
    Manages its own state by polling the board controller every 5 seconds.
    Automatically starts polling when added to display and stops when removed.
    """
    
    def __init__(self, x: int, y: int, level: int = None, charger_connected: bool = False):
        super().__init__(x, y, 16, 16)
        self.level = level
        self.charger_connected = charger_connected
        self._poll_thread = None
        self._stop_event = threading.Event()
    
    def start(self) -> None:
        """Start the battery polling thread."""
        if self._poll_thread is None or not self._poll_thread.is_alive():
            self._stop_event.clear()
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
            log.debug("BatteryWidget polling thread started")
    
    def stop(self) -> None:
        """Stop the battery polling thread."""
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
            self._poll_thread = None
            log.debug("BatteryWidget polling thread stopped")
    
    def _poll_loop(self) -> None:
        """Background thread that polls battery status every 5 seconds."""
        while not self._stop_event.is_set():
            try:
                self._fetch_battery_status()
            except Exception as e:
                log.debug(f"Error in battery poll loop: {e}")
            
            # Wait for next poll interval, but check stop event frequently
            for _ in range(BATTERY_POLL_INTERVAL * 10):
                if self._stop_event.is_set():
                    return
                time.sleep(0.1)
    
    def _fetch_battery_status(self) -> None:
        """Fetch battery status directly from the board controller.
        
        Requests battery info from the controller and updates widget state.
        Also updates board.chargerconnected and board.batterylevel globals
        for use by eventsThread (timeout hold on charger).
        Only requests a display update if values have changed.
        """
        try:
            from DGTCentaurMods.board.sync_centaur import command
            from DGTCentaurMods.board import board
            
            controller = board.controller
            if controller is None:
                return
            
            resp = controller.request_response(command.DGT_SEND_BATTERY_INFO)
            if resp is None or len(resp) == 0:
                return
            
            val = resp[0]
            new_level = val & 0x1F
            new_charger = ((val >> 5) & 0x07) in (1, 2)
            
            # Update board globals for eventsThread timeout hold logic
            board.batterylevel = new_level
            board.chargerconnected = 1 if new_charger else 0
            
            changed = False
            if self.level != new_level:
                self.level = new_level
                changed = True
            if self.charger_connected != new_charger:
                self.charger_connected = new_charger
                changed = True
            
            if changed:
                log.debug(f"Battery status changed: level={self.level}, charger={self.charger_connected}")
                self._last_rendered = None
                self.request_update(full=False)
                
        except Exception as e:
            log.debug(f"Error fetching battery status: {e}")
    
    def set_level(self, level: int) -> None:
        """Set battery level (0-20, where 20 is fully charged)."""
        if self.level != level:
            self.level = max(0, min(20, level))
            self._last_rendered = None
            self.request_update(full=False)
    
    def set_charger_connected(self, connected: bool) -> None:
        """Set charger connection status."""
        if self.charger_connected != connected:
            self.charger_connected = connected
            self._last_rendered = None
            self.request_update(full=False)
    
    def render(self) -> Image.Image:
        """Render battery indicator with level bars and charging flash icon.
        
        When charging, displays a lightning bolt overlay. The bolt is drawn with
        XOR effect - white over black level bars and black over white background,
        ensuring visibility at any charge level.
        """
        # Widget is 16x16, battery icon is approximately 14x10
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        batterylevel = self.level if self.level is not None else 10
        
        # Battery dimensions (fits in 16x16 with some padding)
        # Main body: 12 pixels wide, 10 pixels tall
        body_left = 1
        body_top = 3
        body_right = 12
        body_bottom = 12
        
        # Battery terminal (small nub on right)
        term_left = body_right
        term_top = 5
        term_right = 14
        term_bottom = 10
        
        # Draw battery outline
        draw.rectangle([body_left, body_top, body_right, body_bottom], outline=0, width=1)
        draw.rectangle([term_left, term_top, term_right, term_bottom], fill=0)
        
        # Calculate fill width based on level (0-20)
        inner_left = body_left + 1
        inner_top = body_top + 1
        inner_right = body_right - 1
        inner_bottom = body_bottom - 1
        inner_width = inner_right - inner_left
        
        fill_width = int((batterylevel / 20.0) * inner_width)
        
        # Draw level bars
        if fill_width > 0:
            draw.rectangle([inner_left, inner_top, inner_left + fill_width, inner_bottom], fill=0)
        
        # Draw charging lightning bolt if connected
        if self.charger_connected:
            # Create a mask for the lightning bolt shape
            bolt_mask = Image.new("1", (self.width, self.height), 0)
            bolt_draw = ImageDraw.Draw(bolt_mask)
            
            # Lightning bolt polygon - classic zigzag shape
            # Centered in battery body, sized to fit
            cx = (body_left + body_right) // 2  # center x
            
            # Bolt shape: top triangle pointing down-left, bottom triangle pointing down-right
            bolt_polygon = [
                (cx + 2, body_top + 1),    # top right
                (cx - 1, body_top + 4),    # middle left point
                (cx + 0, body_top + 4),    # middle center
                (cx + 1, body_top + 4),    # middle right of center bar
                (cx - 2, body_bottom - 1), # bottom left
                (cx + 1, body_top + 5),    # lower middle right
                (cx + 0, body_top + 5),    # lower middle center
            ]
            
            bolt_draw.polygon(bolt_polygon, fill=1)
            
            # XOR the bolt onto the image
            for y in range(self.height):
                for x in range(self.width):
                    if bolt_mask.getpixel((x, y)) == 1:
                        current = img.getpixel((x, y))
                        img.putpixel((x, y), 255 if current == 0 else 0)
        
        return img
