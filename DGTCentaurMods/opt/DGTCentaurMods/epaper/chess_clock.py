"""
Chess clock widget displaying game time for both players.

This widget observes the ChessClockState and renders its state. The widget is a
thin display layer - all timer logic is in the clock service which persists
across widget creation/destruction.

Layout:
- Timed mode: Remaining time for white and black players with turn indicator
- Untimed mode (compact): Just "White Turn" or "Black Turn" text
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
from .text import TextWidget, Justify
from typing import Optional

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

# Import state (lightweight) - NOT service
from DGTCentaurMods.state import get_chess_clock as get_clock_state


class ChessClockWidget(Widget):
    """
    Widget displaying chess clock times or turn indicator.
    
    This is a view-only widget that reads state from ChessClock. It does not
    manage its own timer - the clock handles countdown and state persistence.
    
    Has two display modes:
    - Timed mode: Shows remaining time for both players with turn indicator
    - Compact/untimed mode: Shows "White Turn" or "Black Turn" centered
    
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
    
    def __init__(self, x: int, y: int, width: int, height: int, update_callback,
                 timed_mode: bool = True, flip: bool = False,
                 white_name: str = "", black_name: str = ""):
        """
        Initialize chess clock widget.
        
        The widget connects to the ChessClock to observe clock state.
        
        Args:
            x: X position
            y: Y position
            width: Widget width
            height: Widget height
            update_callback: Callback to trigger display updates. Must not be None.
            timed_mode: Whether to show times (True) or just turn indicator (False)
            flip: If True, show Black on top (matching flipped board perspective)
            white_name: Optional name for white player (for display only, service has authoritative names)
            black_name: Optional name for black player (for display only, service has authoritative names)
        """
        super().__init__(x, y, width, height, update_callback)
        
        # Display mode and configuration
        self._timed_mode = timed_mode
        self._flip = flip
        self._white_name = white_name
        self._black_name = black_name
        
        # Get clock state reference (lightweight state object, not service)
        self._clock = get_clock_state()
        
        # Register for state change notifications
        self._clock.on_state_change(self._on_clock_state_change)
        self._clock.on_tick(self._on_clock_tick)
        
        # Legacy callback for flag events (forwarded from state)
        # on_flag(color: str) where color is 'white' or 'black'
        self._on_flag_callback: Optional[callable] = None
        
        # Create TextWidgets for timed mode - use parent handler for child updates
        # White label (left aligned, after indicator)
        self._white_label = TextWidget(20, 0, 40, 16, self._handle_child_update,
                                        text="White", font_size=10, 
                                        justify=Justify.LEFT, transparent=True)
        # White player name (smaller, under the label)
        self._white_name_text = TextWidget(20, 0, 60, 12, self._handle_child_update,
                                           text="", font_size=8,
                                           justify=Justify.LEFT, transparent=True)
        # White time (right aligned)
        self._white_time_text = TextWidget(60, 0, 64, 20, self._handle_child_update,
                                           text="00:00", font_size=16,
                                           justify=Justify.RIGHT, transparent=True)
        # Black label
        self._black_label = TextWidget(20, 0, 40, 16, self._handle_child_update,
                                       text="Black", font_size=10,
                                       justify=Justify.LEFT, transparent=True)
        # Black player name (smaller, under the label)
        self._black_name_text = TextWidget(20, 0, 60, 12, self._handle_child_update,
                                           text="", font_size=8,
                                           justify=Justify.LEFT, transparent=True)
        # Black time
        self._black_time_text = TextWidget(60, 0, 64, 20, self._handle_child_update,
                                           text="00:00", font_size=16,
                                           justify=Justify.RIGHT, transparent=True)
        
        # Create TextWidgets for compact mode
        # Turn indicator text (color)
        self._turn_text = TextWidget(0, 0, width, 20, self._handle_child_update,
                                     text="White's Turn", font_size=16,
                                     justify=Justify.CENTER, transparent=True)
        # Player name text (below turn indicator)
        self._turn_name_text = TextWidget(0, 0, width, 14, self._handle_child_update,
                                          text="", font_size=10,
                                          justify=Justify.CENTER, transparent=True)
        
        # Track last state to avoid unnecessary updates
        self._last_white_time = None
        self._last_black_time = None
        self._last_active = None
        self._last_timed_mode = None
    
    def _handle_child_update(self, full: bool = False, immediate: bool = False):
        """Handle update requests from child widgets by forwarding to parent callback."""
        return self._update_callback(full, immediate)
    
    def _on_clock_state_change(self) -> None:
        """Called when ChessClock state changes."""
        self.invalidate_cache()
        self.request_update(full=False)
    
    def _on_clock_tick(self) -> None:
        """Called every second when clock is running."""
        self.invalidate_cache()
        self.request_update(full=False)
    
    def stop(self) -> None:
        """Called when widget is removed from display.
        
        Unregisters callbacks from clock state. Does NOT stop the clock -
        the service continues running independently.
        """
        self._clock.remove_observer(self._on_clock_state_change)
        self._clock.remove_observer(self._on_clock_tick)
        log.debug("[ChessClockWidget] Unregistered from ChessClockState")
    
    # -------------------------------------------------------------------------
    # Properties (read from ChessClock)
    # -------------------------------------------------------------------------
    
    @property
    def timed_mode(self) -> bool:
        """Whether the widget is in timed mode (showing clocks) or compact mode."""
        return self._timed_mode
    
    @timed_mode.setter
    def timed_mode(self, value: bool) -> None:
        """Set timed mode."""
        if self._timed_mode != value:
            self._timed_mode = value
            self.invalidate_cache()
            self.request_update(full=False)
    
    @property
    def white_time(self) -> int:
        """White's remaining time in seconds (from service)."""
        return self._clock.white_time
    
    @property
    def black_time(self) -> int:
        """Black's remaining time in seconds (from service)."""
        return self._clock.black_time
    
    @property
    def active_color(self) -> Optional[str]:
        """Which player's clock is active (from service)."""
        return self._clock.active_color
    
    @property
    def white_name(self) -> str:
        """White player's name (configured at widget creation)."""
        return self._white_name
    
    @property
    def black_name(self) -> str:
        """Black player's name (configured at widget creation)."""
        return self._black_name
    
    @property
    def on_flag(self) -> Optional[callable]:
        """Callback for when time expires."""
        return self._on_flag_callback
    
    @on_flag.setter
    def on_flag(self, callback: Optional[callable]) -> None:
        """Set flag callback. Registers with ChessClock."""
        self._on_flag_callback = callback
        if callback:
            self._clock.on_flag(callback)
    
    # -------------------------------------------------------------------------
    # Legacy methods (delegate to clock service for backward compatibility)
    # These methods require the service for lifecycle control.
    # -------------------------------------------------------------------------
    
    def _get_service(self):
        """Get the clock service (lazy import to avoid circular imports)."""
        from DGTCentaurMods.services import get_chess_clock_service
        return get_chess_clock_service()
    
    def set_player_names(self, white_name: str, black_name: str) -> None:
        """Set both player names. Deprecated - configure via service."""
        log.debug("[ChessClockWidget] set_player_names is deprecated, use service")
    
    def set_times(self, white_seconds: int, black_seconds: int) -> None:
        """Set the clock times for both players. Delegates to clock state."""
        self._clock.set_times(white_seconds, black_seconds)
    
    def set_active(self, color: Optional[str]) -> None:
        """Set which player's clock is active. Delegates to clock state."""
        self._clock.set_active(color)
    
    def start(self, active_color: str = 'white') -> None:
        """Start the clock. Delegates to clock service."""
        self._get_service().start(active_color)
    
    def pause(self) -> None:
        """Pause the clock. Delegates to clock service."""
        self._get_service().pause()
    
    def resume(self, active_color: str) -> None:
        """Resume the clock. Delegates to clock service."""
        self._get_service().resume(active_color)
    
    def switch_turn(self) -> None:
        """Switch which player's clock is running. Delegates to clock service."""
        self._get_service().switch_turn()
    
    def get_final_times(self) -> tuple:
        """Get the current times for both players."""
        return (self._clock.white_time, self._clock.black_time)
    
    # -------------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------------
    
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
    
    def render(self, sprite: Image.Image) -> None:
        """
        Render the chess clock widget onto the sprite image.
        
        Reads state from ChessClock and renders it.
        """
        draw = ImageDraw.Draw(sprite)
        
        # Draw background
        self.draw_background_on_sprite(sprite)
        
        # Draw 1px border around widget extent
        draw.rectangle([(0, 0), (self.width - 1, self.height - 1)], fill=None, outline=0)
        
        if self._timed_mode:
            self._render_timed_mode(sprite, draw)
        else:
            self._render_compact_mode(sprite, draw)
    
    def _render_timed_mode(self, sprite: Image.Image, draw: ImageDraw.Draw) -> None:
        """
        Render timed mode: stacked layout matching board orientation.
        
        Reads times and active color from ChessClock.
        """
        section_height = (self.height - 4) // 2  # -4 for top/middle separators
        
        # Get state from service
        white_time = self._clock.white_time
        black_time = self._clock.black_time
        active_color = self._clock.active_color
        white_name = self._clock.white_name
        black_name = self._clock.black_name
        
        # Determine which color goes on top based on flip setting
        if self._flip:
            top_color = 'white'
            bottom_color = 'black'
            top_label = self._white_label
            bottom_label = self._black_label
            top_name_widget = self._white_name_text
            bottom_name_widget = self._black_name_text
            top_name = white_name
            bottom_name = black_name
            top_time_widget = self._white_time_text
            bottom_time_widget = self._black_time_text
            top_time = white_time
            bottom_time = black_time
        else:
            top_color = 'black'
            bottom_color = 'white'
            top_label = self._black_label
            bottom_label = self._white_label
            top_name_widget = self._black_name_text
            bottom_name_widget = self._white_name_text
            top_name = black_name
            bottom_name = white_name
            top_time_widget = self._black_time_text
            bottom_time_widget = self._white_time_text
            top_time = black_time
            bottom_time = white_time
        
        # === TOP SECTION ===
        top_y = 4
        
        # Indicator circle (larger for visibility)
        indicator_size = 12
        indicator_y = top_y + (section_height - indicator_size) // 2
        if active_color == top_color:
            draw.ellipse([(4, indicator_y), (4 + indicator_size, indicator_y + indicator_size)], 
                        fill=0, outline=0)
        else:
            draw.ellipse([(4, indicator_y), (4 + indicator_size, indicator_y + indicator_size)], 
                        fill=255, outline=0)
        
        # Top label using TextWidget - draw directly onto sprite
        top_label.draw_on(sprite, 20, top_y)
        
        # Top player name (if set) - drawn below the color label
        if top_name:
            display_name = top_name[:10] if len(top_name) > 10 else top_name
            top_name_widget.set_text(display_name)
            top_name_widget.draw_on(sprite, 20, top_y + 12)
        
        # Top time using TextWidget - draw directly onto sprite
        top_time_widget.set_text(self._format_time(top_time))
        top_time_widget.draw_on(sprite, self.width - 68, top_y + 6)
        
        # Horizontal separator
        separator_y = self.height // 2
        draw.line([(0, separator_y), (self.width, separator_y)], fill=0, width=1)
        
        # === BOTTOM SECTION ===
        bottom_y = separator_y + 4
        
        # Indicator circle
        indicator_y = bottom_y + (section_height - indicator_size) // 2
        if active_color == bottom_color:
            draw.ellipse([(4, indicator_y), (4 + indicator_size, indicator_y + indicator_size)], 
                        fill=0, outline=0)
        else:
            draw.ellipse([(4, indicator_y), (4 + indicator_size, indicator_y + indicator_size)], 
                        fill=255, outline=0)
        
        # Bottom label using TextWidget - draw directly onto sprite
        bottom_label.draw_on(sprite, 20, bottom_y)
        
        # Bottom player name (if set) - drawn below the color label
        if bottom_name:
            display_name = bottom_name[:10] if len(bottom_name) > 10 else bottom_name
            bottom_name_widget.set_text(display_name)
            bottom_name_widget.draw_on(sprite, 20, bottom_y + 12)
        
        # Bottom time using TextWidget - draw directly onto sprite
        bottom_time_widget.set_text(self._format_time(bottom_time))
        bottom_time_widget.draw_on(sprite, self.width - 68, bottom_y + 6)
    
    def _render_compact_mode(self, sprite: Image.Image, draw: ImageDraw.Draw) -> None:
        """
        Render compact mode: large centered turn indicator.
        
        Reads active color from ChessClock.
        """
        # Get state from service
        active_color = self._clock.active_color
        white_name = self._clock.white_name
        black_name = self._clock.black_name
        
        # Determine text and player name
        if active_color == 'black':
            turn_text = "Black's Turn"
            player_name = black_name
        else:
            # Default to white if None or 'white'
            turn_text = "White's Turn"
            player_name = white_name
        
        # Large indicator circle at top center
        indicator_size = 28
        indicator_x = (self.width - indicator_size) // 2
        indicator_y = 8
        
        if active_color == 'black':
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
        text_y = indicator_y + indicator_size + 4
        self._turn_text.draw_on(sprite, 0, text_y)
        
        # Player name below turn text (if set)
        if player_name:
            display_name = player_name[:15] if len(player_name) > 15 else player_name
            self._turn_name_text.set_text(display_name)
            name_y = text_y + 18
            self._turn_name_text.draw_on(sprite, 0, name_y)
