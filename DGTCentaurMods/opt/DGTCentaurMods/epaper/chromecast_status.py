"""
Chromecast status widget.

Displays the Chromecast streaming status in the status bar.
The actual streaming is managed by the ChromecastService; this widget
just observes the service state and renders the appropriate icon.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
from typing import Optional

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class ChromecastStatusWidget(Widget):
    """Chromecast status indicator widget.
    
    Observes the ChromecastService and displays:
    - No icon when idle (hidden)
    - Outline icon when connecting/reconnecting
    - Filled icon when streaming
    - Icon with X when error
    
    Args:
        x: X position in status bar
        y: Y position in status bar
        size: Icon size in pixels (default 16)
    """
    
    def __init__(self, x: int, y: int, size: int = 16):
        super().__init__(x, y, size, size)
        self._size = size
        
        # Start hidden - becomes visible when service is active
        self.visible = False
        
        # Cache last known state to detect changes
        self._last_state: Optional[int] = None
        
        # Register as observer of the service
        from DGTCentaurMods.services import get_chromecast_service
        self._service = get_chromecast_service()
        self._service.add_observer(self._on_service_state_changed)
        
        # Sync initial state from service (handles case where service is already streaming)
        self._sync_state()
    
    def _on_service_state_changed(self) -> None:
        """Called by the service when its state changes."""
        self._sync_state()
        self._last_rendered = None
        self.request_update(full=False)
    
    def _sync_state(self) -> None:
        """Sync widget state with service state.
        
        Updates visibility and caches the current state for rendering.
        Called on init and when service notifies of state changes.
        """
        from DGTCentaurMods.services import get_chromecast_service
        service = get_chromecast_service()
        self.visible = service.is_active
        self._last_state = service.state
    
    def stop(self) -> None:
        """Stop the widget (unregister from service).
        
        Note: This does NOT stop the service itself, just removes this
        widget as an observer.
        """
        try:
            self._service.remove_observer(self._on_service_state_changed)
        except Exception as e:
            log.debug(f"[ChromecastStatusWidget] Error removing observer: {e}")
    
    def _draw_cast_icon(self, draw: ImageDraw.Draw, draw_x: int, draw_y: int, 
                        filled: bool = True) -> None:
        """Draw a Chromecast-style cast icon.
        
        The icon has 1px horizontal margin on left and right, no vertical margin.
        
        Args:
            draw: ImageDraw object
            draw_x: X offset on target image
            draw_y: Y offset on target image
            filled: If True, draw filled icon (streaming). If False, outline only.
        """
        # 1px margin on left and right only
        margin_h = 1
        icon_x = draw_x + margin_h
        icon_w = self._size - 2 * margin_h
        icon_h = self._size  # Full height, no vertical margin
        
        # TV/monitor outline - positioned as fractions of icon dimensions
        # TV spans from ~7% to ~93% horizontally, ~12% to ~75% vertically
        tv_left = icon_x + max(1, icon_w // 14)
        tv_top = draw_y + max(1, icon_h // 8)
        tv_right = icon_x + icon_w - max(1, icon_w // 14)
        tv_bottom = draw_y + icon_h - max(2, icon_h // 4)
        
        # Draw TV outline
        draw.rectangle([tv_left, tv_top, tv_right, tv_bottom], fill=255, outline=0, width=1)
        
        # Draw wireless signal arcs (bottom-left corner of TV)
        # Arc origin is offset from TV corner
        arc_x = tv_left + max(1, icon_w // 7)
        arc_y = tv_bottom - max(1, icon_h // 8)
        
        # Arc radii as fractions of icon width
        small_radius = max(1, icon_w // 7)
        large_radius = max(2, icon_w // 4)
        
        if filled:
            # When streaming: filled arcs with thicker lines
            for radius in [small_radius, large_radius]:
                draw.arc([arc_x - radius, arc_y - radius, 
                         arc_x + radius, arc_y + radius],
                        start=180, end=270, fill=0, width=max(1, icon_w // 10))
            
            # Small dot at origin
            dot_r = max(1, icon_w // 14)
            draw.ellipse([arc_x - dot_r, arc_y - dot_r, arc_x + dot_r, arc_y + dot_r], fill=0)
        else:
            # When connecting/error: just outline arcs (thinner)
            for radius in [small_radius, large_radius]:
                draw.arc([arc_x - radius, arc_y - radius, 
                         arc_x + radius, arc_y + radius],
                        start=180, end=270, fill=0, width=1)
    
    def draw_on(self, img: Image.Image, draw_x: int, draw_y: int) -> None:
        """Draw the Chromecast status icon based on cached state."""
        from DGTCentaurMods.services import ChromecastService
        
        draw = ImageDraw.Draw(img)
        
        # Clear background
        draw.rectangle([draw_x, draw_y, draw_x + self.width - 1, draw_y + self.height - 1], 
                      fill=255)
        
        # Draw icon based on cached state
        if self._last_state == ChromecastService.STATE_STREAMING:
            # Solid icon when streaming
            self._draw_cast_icon(draw, draw_x, draw_y, filled=True)
        elif self._last_state in (ChromecastService.STATE_CONNECTING, ChromecastService.STATE_RECONNECTING):
            # Outline icon when connecting
            self._draw_cast_icon(draw, draw_x, draw_y, filled=False)
        elif self._last_state == ChromecastService.STATE_ERROR:
            # Icon with X overlay when error
            self._draw_cast_icon(draw, draw_x, draw_y, filled=False)
            # Draw small X in upper-right of icon area (with 1px horizontal margin)
            margin_h = 1
            icon_x = draw_x + margin_h
            icon_w = self._size - 2 * margin_h
            icon_h = self._size
            # X spans roughly 60%-90% horizontally, 10%-45% vertically
            x1 = icon_x + (icon_w * 3) // 5
            y1 = draw_y + icon_h // 8
            x2 = icon_x + icon_w - 1
            y2 = draw_y + (icon_h * 7) // 16
            draw.line([x1, y1, x2, y2], fill=0, width=1)
            draw.line([x1, y2, x2, y1], fill=0, width=1)
