"""
Chess clock widget displaying game time for both players.

This widget is positioned directly below the board (y=200) and displays:
- Timed mode: Remaining time for white and black players with turn indicator
- Untimed mode (compact): Just "White Turn" or "Black Turn" text

The widget height is 36 pixels, leaving room for the analysis widget below.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
import os
import sys
import threading
import time
from typing import Optional

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

# Import AssetManager for font loading
try:
    from DGTCentaurMods.managers.asset import AssetManager
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from managers.asset import AssetManager
    except ImportError:
        AssetManager = None


class ChessClockWidget(Widget):
    """
    Widget displaying chess clock times or turn indicator.
    
    Has two modes:
    - Timed mode: Shows remaining time for both players with turn indicator
    - Compact/untimed mode: Shows "White Turn" or "Black Turn" centered
    
    Layout (36 pixels height, 128 pixels width):
    Timed mode:
    - Left side: White time with indicator
    - Right side: Black time with indicator
    
    Compact mode:
    - Centered text: "White Turn" or "Black Turn"
    """
    
    # Position directly below the board
    DEFAULT_Y = 200
    DEFAULT_HEIGHT = 36
    
    def __init__(self, x: int = 0, y: int = None, width: int = 128, height: int = None,
                 timed_mode: bool = True):
        """
        Initialize chess clock widget.
        
        Args:
            x: X position (default 0)
            y: Y position (default 200, directly below board)
            width: Widget width (default 128)
            height: Widget height (default 36)
            timed_mode: Whether to show times (True) or just turn indicator (False)
        """
        if y is None:
            y = self.DEFAULT_Y
        if height is None:
            height = self.DEFAULT_HEIGHT
            
        super().__init__(x, y, width, height)
        
        # Mode
        self._timed_mode = timed_mode
        
        # Time state (in seconds)
        self._white_time = 0
        self._black_time = 0
        self._active_color: Optional[str] = None  # None, 'white', or 'black'
        self._is_running = False
        
        # Update thread
        self._update_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Fonts
        self._font_time = self._load_font(16)  # For time display
        self._font_label = self._load_font(10)  # For "White"/"Black" labels
        self._font_turn = self._load_font(14)  # For "White Turn"/"Black Turn"
        
        # Track last state to avoid unnecessary updates
        self._last_white_time = None
        self._last_black_time = None
        self._last_active = None
        self._last_timed_mode = None
    
    def _load_font(self, size: int):
        """Load font with fallbacks."""
        if AssetManager is not None:
            try:
                font_path = AssetManager.get_resource_path("Font.ttc")
                if font_path and os.path.exists(font_path):
                    return ImageFont.truetype(font_path, size)
            except Exception:
                pass
        
        # Fallback paths
        font_paths = [
            '/opt/DGTCentaurMods/resources/Font.ttc',
            'resources/Font.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()
    
    @property
    def timed_mode(self) -> bool:
        """Whether the widget is in timed mode (showing clocks) or compact mode."""
        return self._timed_mode
    
    @timed_mode.setter
    def timed_mode(self, value: bool) -> None:
        """Set timed mode."""
        if self._timed_mode != value:
            self._timed_mode = value
            self._last_rendered = None
            self.request_update(full=False)
    
    @property
    def white_time(self) -> int:
        """White's remaining time in seconds."""
        return self._white_time
    
    @property
    def black_time(self) -> int:
        """Black's remaining time in seconds."""
        return self._black_time
    
    @property
    def active_color(self) -> Optional[str]:
        """Which player's clock is active ('white', 'black', or None)."""
        return self._active_color
    
    def set_times(self, white_seconds: int, black_seconds: int) -> None:
        """
        Set the clock times for both players.
        
        Args:
            white_seconds: White's remaining time in seconds
            black_seconds: Black's remaining time in seconds
        """
        changed = False
        
        if self._white_time != white_seconds:
            self._white_time = white_seconds
            changed = True
        
        if self._black_time != black_seconds:
            self._black_time = black_seconds
            changed = True
        
        if changed:
            self._last_rendered = None
            self.request_update(full=False)
    
    def set_active(self, color: Optional[str]) -> None:
        """
        Set which player's clock is active (running).
        
        Args:
            color: 'white', 'black', or None (both stopped)
        """
        if self._active_color != color:
            self._active_color = color
            self._last_rendered = None
            self.request_update(full=False)
    
    def start(self, active_color: str = 'white') -> None:
        """
        Start the clock running.
        
        Args:
            active_color: Which player's clock starts running ('white' or 'black')
        """
        if self._is_running:
            return
        
        self._active_color = active_color
        self._is_running = True
        self._stop_event.clear()
        
        self._update_thread = threading.Thread(
            target=self._clock_loop,
            name="chess-clock-widget",
            daemon=True
        )
        self._update_thread.start()
        log.info(f"[ChessClockWidget] Started, active: {active_color}")
    
    def pause(self) -> None:
        """Pause the clock (both players' time stops counting)."""
        self._active_color = None
        self._last_rendered = None
        self.request_update(full=False)
    
    def switch_turn(self) -> None:
        """Switch which player's clock is running."""
        if self._active_color == 'white':
            self._active_color = 'black'
        elif self._active_color == 'black':
            self._active_color = 'white'
        
        self._last_rendered = None
        self.request_update(full=False)
    
    def stop(self) -> None:
        """Stop the clock completely and cleanup."""
        self._is_running = False
        self._stop_event.set()
        
        if self._update_thread:
            self._update_thread.join(timeout=1.0)
            self._update_thread = None
        
        log.info("[ChessClockWidget] Stopped")
    
    def get_final_times(self) -> tuple[int, int]:
        """
        Get the final times for both players.
        
        Used when game ends to pass times to GameOverWidget.
        
        Returns:
            Tuple of (white_seconds, black_seconds)
        """
        return (self._white_time, self._black_time)
    
    def _clock_loop(self) -> None:
        """Background thread that decrements the active player's time."""
        last_tick = time.monotonic()
        
        while self._is_running and not self._stop_event.is_set():
            # Wait for 1 second (interruptible)
            if self._stop_event.wait(timeout=1.0):
                break
            
            # Only decrement in timed mode
            if not self._timed_mode:
                continue
            
            # Calculate elapsed time since last tick
            now = time.monotonic()
            elapsed = now - last_tick
            last_tick = now
            
            # Decrement active player's time
            if self._active_color == 'white' and self._white_time > 0:
                self._white_time = max(0, self._white_time - int(elapsed))
                self._last_rendered = None
                self.request_update(full=False)
                
                if self._white_time == 0:
                    log.info("[ChessClockWidget] White's time expired (flag)")
                    
            elif self._active_color == 'black' and self._black_time > 0:
                self._black_time = max(0, self._black_time - int(elapsed))
                self._last_rendered = None
                self.request_update(full=False)
                
                if self._black_time == 0:
                    log.info("[ChessClockWidget] Black's time expired (flag)")
    
    def _format_time(self, seconds: int) -> str:
        """
        Format time in seconds to display string.
        
        Returns MM:SS for times under an hour, H:MM:SS for longer times.
        Returns "FLAG" if time is 0.
        
        Args:
            seconds: Time in seconds
            
        Returns:
            Formatted time string
        """
        if seconds <= 0:
            return "FLAG"
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"
    
    def render(self) -> Image.Image:
        """
        Render the chess clock widget.
        
        Timed mode layout (side by side):
        - Left: [indicator] White  MM:SS
        - Right: [indicator] Black  MM:SS
        
        Compact mode layout (centered):
        - [indicator] White Turn  or  [indicator] Black Turn
        """
        # Check cache
        if self._last_rendered is not None:
            if (self._last_white_time == self._white_time and
                self._last_black_time == self._black_time and
                self._last_active == self._active_color and
                self._last_timed_mode == self._timed_mode):
                return self._last_rendered
        
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        # Draw separator line at top
        draw.line([(0, 0), (self.width, 0)], fill=0, width=1)
        
        if self._timed_mode:
            self._render_timed_mode(draw)
        else:
            self._render_compact_mode(draw)
        
        # Cache state
        self._last_white_time = self._white_time
        self._last_black_time = self._black_time
        self._last_active = self._active_color
        self._last_timed_mode = self._timed_mode
        self._last_rendered = img
        
        return img
    
    def _render_timed_mode(self, draw: ImageDraw.Draw) -> None:
        """
        Render timed mode: both clocks side by side.
        
        Layout:
        |[o] White  05:23 | [o] Black  04:17|
        """
        half_width = self.width // 2
        center_y = (self.height - 2) // 2  # -2 for top separator
        
        # === WHITE SIDE (left half) ===
        # Indicator circle
        indicator_size = 8
        indicator_y = center_y - indicator_size // 2 + 2
        if self._active_color == 'white':
            draw.ellipse([(4, indicator_y), (4 + indicator_size, indicator_y + indicator_size)], 
                        fill=0, outline=0)
        else:
            draw.ellipse([(4, indicator_y), (4 + indicator_size, indicator_y + indicator_size)], 
                        fill=255, outline=0)
        
        # "W" label (compact)
        draw.text((16, 4), "W", font=self._font_label, fill=0)
        
        # White time
        white_time_str = self._format_time(self._white_time)
        draw.text((16, 16), white_time_str, font=self._font_time, fill=0)
        
        # Vertical separator
        draw.line([(half_width, 2), (half_width, self.height - 2)], fill=0, width=1)
        
        # === BLACK SIDE (right half) ===
        black_x = half_width + 4
        
        # Indicator circle
        if self._active_color == 'black':
            draw.ellipse([(black_x, indicator_y), (black_x + indicator_size, indicator_y + indicator_size)], 
                        fill=0, outline=0)
        else:
            draw.ellipse([(black_x, indicator_y), (black_x + indicator_size, indicator_y + indicator_size)], 
                        fill=255, outline=0)
        
        # "B" label (compact)
        draw.text((black_x + 12, 4), "B", font=self._font_label, fill=0)
        
        # Black time
        black_time_str = self._format_time(self._black_time)
        draw.text((black_x + 12, 16), black_time_str, font=self._font_time, fill=0)
    
    def _render_compact_mode(self, draw: ImageDraw.Draw) -> None:
        """
        Render compact mode: centered turn indicator text.
        
        Layout:
        |        [o] White Turn        |
        or
        |        [o] Black Turn        |
        """
        # Determine text
        if self._active_color == 'black':
            turn_text = "Black Turn"
        else:
            # Default to white if None or 'white'
            turn_text = "White Turn"
        
        # Calculate text width for centering
        text_bbox = draw.textbbox((0, 0), turn_text, font=self._font_turn)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        
        # Total width including indicator
        indicator_size = 10
        gap = 6
        total_width = indicator_size + gap + text_width
        
        # Center everything
        start_x = (self.width - total_width) // 2
        center_y = (self.height + 2) // 2  # +2 for top separator offset
        
        # Draw indicator
        indicator_y = center_y - indicator_size // 2
        if self._active_color == 'black':
            # Filled circle for black
            draw.ellipse([(start_x, indicator_y), 
                         (start_x + indicator_size, indicator_y + indicator_size)], 
                        fill=0, outline=0)
        else:
            # Empty circle for white
            draw.ellipse([(start_x, indicator_y), 
                         (start_x + indicator_size, indicator_y + indicator_size)], 
                        fill=255, outline=0)
        
        # Draw text
        text_x = start_x + indicator_size + gap
        text_y = center_y - text_height // 2 - 2
        draw.text((text_x, text_y), turn_text, font=self._font_turn, fill=0)
