"""
Clock widget displaying current time.
"""

from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from .framework.widget import Widget
import os
import threading
import time
from typing import Optional

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class ClockWidget(Widget):
    """Clock widget displaying current time with automatic updates."""
    
    def __init__(self, x: int, y: int, width: int = 128, height: int = 24, 
                 font_size: int = None, font_path: str = None,
                 show_seconds: bool = True):
        super().__init__(x, y, width, height)
        self.show_seconds = show_seconds
        # Set format based on show_seconds
        if show_seconds:
            self.format = "%H:%M:%S"
        else:
            self.format = "%H:%M"
        # Override format if explicitly provided
        if format:
            self.format = format
        self.font_size = font_size
        self.font_path = font_path
        self._font = None
        self._load_font()
        
        # Background update thread
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_rendered_time: Optional[str] = None
        self._start_update_loop()
    
    def _start_update_loop(self) -> None:
        """Start the background update loop."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._update_loop, name="clock-widget", daemon=True)
        self._thread.start()
    
    def _stop_update_loop(self) -> None:
        """Stop the background update loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None
    
    def _update_loop(self) -> None:
        """Background loop that checks time every 0.1 seconds and triggers updates."""
        while self._running:
            try:
                now = datetime.now()
                current_time_str = now.strftime(self.format)
                
                # Check if time has changed
                if current_time_str != self._last_rendered_time:
                    self._last_rendered_time = current_time_str
                    # Invalidate cache and request update
                    self._last_rendered = None
                    self.request_update(full=False)
                
                # Sleep for 0.1 seconds
                time.sleep(0.1)
            except Exception as e:
                log.error(f"Error in clock update loop: {e}")
                time.sleep(0.1)
    
    def set_show_seconds(self, show_seconds: bool) -> None:
        """Set whether to show seconds in the time display."""
        if self.show_seconds != show_seconds:
            self.show_seconds = show_seconds
            if show_seconds:
                self.format = "%H:%M:%S"
            else:
                self.format = "%H:%M"
            self._last_rendered_time = None  # Force update
            self._last_rendered = None
    
    def _load_font(self):
        """Load font with fallbacks."""
        if self._font is not None:
            return self._font
        
        # If font_path and font_size are specified, use them
        if self.font_path and self.font_size:
            if os.path.exists(self.font_path):
                try:
                    self._font = ImageFont.truetype(self.font_path, self.font_size)
                    return self._font
                except:
                    pass
        
        # Try default font paths if font_size is specified
        if self.font_size:
            font_paths = [
                '/opt/DGTCentaurMods/resources/Font.ttc',
                'resources/Font.ttc',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            ]
            for path in font_paths:
                if os.path.exists(path):
                    try:
                        self._font = ImageFont.truetype(path, self.font_size)
                        return self._font
                    except:
                        pass
        
        # Fallback to default font
        self._font = ImageFont.load_default()
        return self._font
    
    def render(self) -> Image.Image:
        """Render current time."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        now = datetime.now()
        time_str = now.strftime(self.format)
        
        # Update last rendered time
        self._last_rendered_time = time_str
        
        # Use cached font or load it
        if self._font is None:
            self._load_font()
        
        draw.text((0, -1), time_str, font=self._font, fill=0)
        return img
