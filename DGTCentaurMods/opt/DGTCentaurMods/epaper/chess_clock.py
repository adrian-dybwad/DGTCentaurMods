"""
Chess clock widget displaying game time for both players.

This widget is positioned directly below the board (y=200) and displays:
- Timed mode: Remaining time for white and black players with turn indicator
- Untimed mode (compact): Just "White Turn" or "Black Turn" text

The widget height is 36 pixels, leaving room for the analysis widget below.
"""

from PIL import Image, ImageDraw, ImageFont
from .framework.widget import Widget
from .text import TextWidget, Justify
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


class ChessClockWidget(Widget):
    """
    Widget displaying chess clock times or turn indicator.
    
    Has two modes:
    - Timed mode: Shows remaining time for both players with turn indicator
    - Compact/untimed mode: Shows "White Turn" or "Black Turn" centered
    
    Uses TextWidget for all text rendering.
    
    Layout (72 pixels height, 128 pixels width):
    Timed mode:
    - Top section: [indicator] White  MM:SS
    - Separator line
    - Bottom section: [indicator] Black  MM:SS
    
    Compact mode:
    - Large indicator circle
    - Centered text: "White's Turn" or "Black's Turn"
    """
    
    # Position directly below the board (board is at y=16, height=128)
    DEFAULT_Y = 144
    DEFAULT_HEIGHT = 72
    
    def __init__(self, x: int = 0, y: int = None, width: int = 128, height: int = None,
                 timed_mode: bool = True, flip: bool = False):
        """
        Initialize chess clock widget.
        
        Args:
            x: X position (default 0)
            y: Y position (default 144, directly below board)
            width: Widget width (default 128)
            height: Widget height (default 72)
            timed_mode: Whether to show times (True) or just turn indicator (False)
            flip: If True, show Black on top (matching flipped board perspective)
        """
        if y is None:
            y = self.DEFAULT_Y
        if height is None:
            height = self.DEFAULT_HEIGHT
            
        super().__init__(x, y, width, height)
        
        # Mode
        self._timed_mode = timed_mode
        self._flip = flip
        
        # Time state (in seconds)
        self._white_time = 0
        self._black_time = 0
        self._active_color: Optional[str] = None  # None, 'white', or 'black'
        self._is_running = False
        
        # Update thread
        self._update_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Callback for when time expires (flag)
        # on_flag(color: str) where color is 'white' or 'black'
        self.on_flag = None
        
        # Create TextWidgets for timed mode
        # White label (left aligned, after indicator)
        self._white_label = TextWidget(x=20, y=0, width=40, height=16, 
                                        text="White", font_size=10, 
                                        justify=Justify.LEFT, transparent=True)
        # White time (right aligned)
        self._white_time_text = TextWidget(x=60, y=0, width=64, height=20,
                                           text="00:00", font_size=16,
                                           justify=Justify.RIGHT, transparent=True)
        # Black label
        self._black_label = TextWidget(x=20, y=0, width=40, height=16,
                                       text="Black", font_size=10,
                                       justify=Justify.LEFT, transparent=True)
        # Black time
        self._black_time_text = TextWidget(x=60, y=0, width=64, height=20,
                                           text="00:00", font_size=16,
                                           justify=Justify.RIGHT, transparent=True)
        
        # Create TextWidget for compact mode (turn indicator text)
        self._turn_text = TextWidget(x=0, y=0, width=width, height=20,
                                     text="White's Turn", font_size=16,
                                     justify=Justify.CENTER, transparent=True)
        
        # Track last state to avoid unnecessary updates
        self._last_white_time = None
        self._last_black_time = None
        self._last_active = None
        self._last_timed_mode = None
    
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
    
    def resume(self, active_color: str) -> None:
        """Resume the clock after a pause.
        
        Unlike start(), this doesn't create a new thread - just sets the active color
        so the existing clock thread resumes counting down.
        
        Args:
            active_color: Which player's clock should resume ('white' or 'black')
        """
        if not self._is_running:
            # Clock was stopped, not just paused - need to start fresh
            self.start(active_color)
            return
        
        self._active_color = active_color
        self._last_rendered = None
        self.request_update(full=False)
        log.info(f"[ChessClockWidget] Resumed, active: {active_color}")
    
    def switch_turn(self) -> None:
        """Switch which player's clock is running.
        
        If active_color is None (clock not started), defaults to white.
        """
        if self._active_color == 'white':
            self._active_color = 'black'
        elif self._active_color == 'black':
            self._active_color = 'white'
        else:
            # None or invalid - default to white
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
                    self._is_running = False  # Stop the clock
                    if self.on_flag:
                        try:
                            self.on_flag('white')
                        except Exception as e:
                            log.error(f"[ChessClockWidget] Error in on_flag callback: {e}")
                    
            elif self._active_color == 'black' and self._black_time > 0:
                self._black_time = max(0, self._black_time - int(elapsed))
                self._last_rendered = None
                self.request_update(full=False)
                
                if self._black_time == 0:
                    log.info("[ChessClockWidget] Black's time expired (flag)")
                    self._is_running = False  # Stop the clock
                    if self.on_flag:
                        try:
                            self.on_flag('black')
                        except Exception as e:
                            log.error(f"[ChessClockWidget] Error in on_flag callback: {e}")
    
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
    
    def draw_on(self, img: Image.Image, draw_x: int, draw_y: int) -> None:
        """
        Draw the chess clock widget onto the target image.
        
        Timed mode layout (side by side):
        - Left: [indicator] White  MM:SS
        - Right: [indicator] Black  MM:SS
        
        Compact mode layout (centered):
        - [indicator] White Turn  or  [indicator] Black Turn
        """
        draw = ImageDraw.Draw(img)
        
        # Draw background
        self.draw_background(img, draw_x, draw_y)
        
        # DEBUG: Draw 1px border around widget extent
        draw.rectangle([(draw_x, draw_y), (draw_x + self.width - 1, draw_y + self.height - 1)], fill=None, outline=0)
        
        if self._timed_mode:
            self._render_timed_mode(img, draw, draw_x, draw_y)
        else:
            self._render_compact_mode(img, draw, draw_x, draw_y)
    
    def _render_timed_mode(self, img: Image.Image, draw: ImageDraw.Draw, draw_x: int, draw_y: int) -> None:
        """
        Render timed mode: stacked layout matching board orientation.
        
        Uses TextWidget for labels and times.
        When flip=False (default): White on top, Black on bottom
        When flip=True: Black on top, White on bottom (matching flipped board)
        
        Layout (72 pixels height):
        - Top section: [indicator] [TopColor]  MM:SS
        - Separator line
        - Bottom section: [indicator] [BottomColor]  MM:SS
        """
        section_height = (self.height - 4) // 2  # -4 for top/middle separators
        
        # Determine which color goes on top based on flip setting
        # The top clock matches the top of the board, bottom clock matches bottom
        # flip=False: Black on top (opponent), White on bottom (player)
        # flip=True: White on top (opponent), Black on bottom (player)
        if self._flip:
            top_color = 'white'
            bottom_color = 'black'
            top_label = self._white_label
            bottom_label = self._black_label
            top_time_widget = self._white_time_text
            bottom_time_widget = self._black_time_text
            top_time = self._white_time
            bottom_time = self._black_time
        else:
            top_color = 'black'
            bottom_color = 'white'
            top_label = self._black_label
            bottom_label = self._white_label
            top_time_widget = self._black_time_text
            bottom_time_widget = self._white_time_text
            top_time = self._black_time
            bottom_time = self._white_time
        
        # === TOP SECTION ===
        top_y = draw_y + 4
        
        # Indicator circle (larger for visibility)
        indicator_size = 12
        indicator_y = top_y + (section_height - indicator_size) // 2
        if self._active_color == top_color:
            draw.ellipse([(draw_x + 4, indicator_y), (draw_x + 4 + indicator_size, indicator_y + indicator_size)], 
                        fill=0, outline=0)
        else:
            draw.ellipse([(draw_x + 4, indicator_y), (draw_x + 4 + indicator_size, indicator_y + indicator_size)], 
                        fill=255, outline=0)
        
        # Top label using TextWidget - draw directly onto image
        top_label.draw_on(img, draw_x + 20, top_y + 2)
        
        # Top time using TextWidget - draw directly onto image
        top_time_widget.set_text(self._format_time(top_time))
        top_time_widget.draw_on(img, draw_x + self.width - 68, top_y + 8)
        
        # Horizontal separator
        separator_y = draw_y + self.height // 2
        draw.line([(draw_x, separator_y), (draw_x + self.width, separator_y)], fill=0, width=1)
        
        # === BOTTOM SECTION ===
        bottom_y = separator_y + 4
        
        # Indicator circle
        indicator_y = bottom_y + (section_height - indicator_size) // 2
        if self._active_color == bottom_color:
            draw.ellipse([(draw_x + 4, indicator_y), (draw_x + 4 + indicator_size, indicator_y + indicator_size)], 
                        fill=0, outline=0)
        else:
            draw.ellipse([(draw_x + 4, indicator_y), (draw_x + 4 + indicator_size, indicator_y + indicator_size)], 
                        fill=255, outline=0)
        
        # Bottom label using TextWidget - draw directly onto image
        bottom_label.draw_on(img, draw_x + 20, bottom_y + 2)
        
        # Bottom time using TextWidget - draw directly onto image
        bottom_time_widget.set_text(self._format_time(bottom_time))
        bottom_time_widget.draw_on(img, draw_x + self.width - 68, bottom_y + 8)
    
    def _render_compact_mode(self, img: Image.Image, draw: ImageDraw.Draw, draw_x: int, draw_y: int) -> None:
        """
        Render compact mode: large centered turn indicator.
        
        Uses TextWidget for turn text.
        
        Layout (72 pixels height):
        - Large indicator circle (filled for black, empty for white)
        - "White's Turn" or "Black's Turn" text below
        """
        # Determine text
        if self._active_color == 'black':
            turn_text = "Black's Turn"
        else:
            # Default to white if None or 'white'
            turn_text = "White's Turn"
        
        # Large indicator circle at top center
        indicator_size = 28
        indicator_x = draw_x + (self.width - indicator_size) // 2
        indicator_y = draw_y + 8
        
        if self._active_color == 'black':
            # Filled circle for black
            draw.ellipse([(indicator_x, indicator_y), 
                         (indicator_x + indicator_size, indicator_y + indicator_size)], 
                        fill=0, outline=0)
        else:
            # Empty circle for white (with thick border)
            draw.ellipse([(indicator_x, indicator_y), 
                         (indicator_x + indicator_size, indicator_y + indicator_size)], 
                        fill=255, outline=0, width=2)
        
        # Turn text below indicator using TextWidget (centered) - draw directly
        self._turn_text.set_text(turn_text)
        text_y = indicator_y + indicator_size + 6
        self._turn_text.draw_on(img, draw_x, text_y)
