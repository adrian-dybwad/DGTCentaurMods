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
        
        # Sync initial state
        self._sync_visibility()
    
    def _on_service_state_changed(self) -> None:
        """Called by the service when its state changes."""
        self._sync_visibility()
        self._last_rendered = None
        self.request_update(full=False)
    
    def _sync_visibility(self) -> None:
        """Sync widget visibility with service state."""
        from DGTCentaurMods.services import get_chromecast_service
        service = get_chromecast_service()
        self.visible = service.is_active
    
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
        
        Args:
            draw: ImageDraw object
            draw_x: X offset on target image
            draw_y: Y offset on target image
            filled: If True, draw filled icon (streaming). If False, outline only.
        """
        s = self._size / 14.0  # Scale factor (14 is base size)
        
        # TV/monitor outline
        tv_left = draw_x + int(1 * s)
        tv_top = draw_y + int(2 * s)
        tv_right = draw_x + int(13 * s)
        tv_bottom = draw_y + int(10 * s)
        
        # Draw TV outline
        draw.rectangle([tv_left, tv_top, tv_right, tv_bottom], fill=255, outline=0, width=1)
        
        # Draw wireless signal arcs (bottom-left corner)
        arc_x = tv_left + int(2 * s)
        arc_y = tv_bottom - int(2 * s)
        
        if filled:
            # When streaming: filled arcs
            for i, radius in enumerate([int(2 * s), int(4 * s)]):
                if radius > 0:
                    draw.arc([arc_x - radius, arc_y - radius, 
                             arc_x + radius, arc_y + radius],
                            start=180, end=270, fill=0, width=max(1, int(1.5 * s)))
            
            # Small dot at origin
            dot_r = max(1, int(1 * s))
            draw.ellipse([arc_x - dot_r, arc_y - dot_r, arc_x + dot_r, arc_y + dot_r], fill=0)
        else:
            # When connecting/error: just outline arcs (thinner)
            for radius in [int(2 * s), int(4 * s)]:
                if radius > 0:
                    draw.arc([arc_x - radius, arc_y - radius, 
                             arc_x + radius, arc_y + radius],
                            start=180, end=270, fill=0, width=1)
    
    def draw_on(self, img: Image.Image, draw_x: int, draw_y: int) -> None:
        """Draw the Chromecast status icon based on service state."""
        from DGTCentaurMods.services import get_chromecast_service
        service = get_chromecast_service()
        
        draw = ImageDraw.Draw(img)
        
        # Clear background
        draw.rectangle([draw_x, draw_y, draw_x + self.width - 1, draw_y + self.height - 1], 
                      fill=255)
        
        # Draw icon based on service state
        if service.state == service.STATE_STREAMING:
            # Solid icon when streaming
            self._draw_cast_icon(draw, draw_x, draw_y, filled=True)
        elif service.state in (service.STATE_CONNECTING, service.STATE_RECONNECTING):
            # Outline icon when connecting
            self._draw_cast_icon(draw, draw_x, draw_y, filled=False)
        elif service.state == service.STATE_ERROR:
            # Icon with X overlay when error
            self._draw_cast_icon(draw, draw_x, draw_y, filled=False)
            # Draw small X
            s = self._size / 14.0
            x1 = draw_x + int(8 * s)
            y1 = draw_y + int(2 * s)
            x2 = draw_x + int(13 * s)
            y2 = draw_y + int(7 * s)
            draw.line([x1, y1, x2, y2], fill=0, width=1)
            draw.line([x1, y2, x2, y1], fill=0, width=1)
