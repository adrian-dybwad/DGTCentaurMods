"""
Bouncing ball widget.
"""

from PIL import Image, ImageDraw

from ..widget import Widget


class BallWidget(Widget):
    """
    Widget that displays a bouncing ball.
    
    The ball position is updated externally by calling set_position().
    """

    def __init__(self, x: int, y: int, radius: int = 5) -> None:
        """
        Initialize ball widget.
        
        Args:
            x: Initial X position (center of ball)
            y: Initial Y position (center of ball)
            radius: Ball radius in pixels (default 5)
        """
        # Widget size needs to accommodate the ball with radius
        size = radius * 2 + 2  # Add padding for movement
        super().__init__(x - radius, y - radius, size, size)
        self._center_x = x
        self._center_y = y
        self.radius = radius

    def set_position(self, x: int, y: int) -> None:
        """
        Set ball position.
        
        Args:
            x: X position (center of ball)
            y: Y position (center of ball)
        """
        self._center_x = x
        self._center_y = y
        # Update widget position to keep ball centered
        self.x = x - self.radius
        self.y = y - self.radius
        # Invalidate cache so has_changed() detects the position change
        self._last_rendered = None

    def get_center(self) -> tuple[int, int]:
        """Get ball center position."""
        return (self._center_x, self._center_y)

    def render(self) -> Image.Image:
        """Render the ball."""
        image = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(image)
        
        # Calculate ball position relative to widget
        ball_x = self._center_x - self.x
        ball_y = self._center_y - self.y
        
        # Draw circle (ball)
        bbox = (
            ball_x - self.radius,
            ball_y - self.radius,
            ball_x + self.radius,
            ball_y + self.radius
        )
        draw.ellipse(bbox, fill=0, outline=0)
        
        return image

