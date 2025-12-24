"""LED control utilities.

Centralizes LED control with configurable speed and intensity settings.
All LED operations should go through this module to ensure consistent behavior.

Speed constants:
- LED_SPEED_SLOW (2): For hints, check/threat alerts - gentle indication
- LED_SPEED_NORMAL (3): Standard move indication
- LED_SPEED_FAST (10): Corrections, invalid selection - urgent feedback

Intensity:
- Standard intensity: Configurable via settings (default 5)
- Dim intensity: standard * 10 (used for hints to be less intrusive)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

# Speed constants
LED_SPEED_SLOW = 2      # Hints, check/threat alerts
LED_SPEED_NORMAL = 3    # Standard move indication
LED_SPEED_FAST = 10     # Corrections, invalid selection

# Default intensity
LED_INTENSITY_DEFAULT = 5


def get_led_intensity_from_settings() -> int:
    """Load LED intensity from saved settings.
    
    Returns:
        LED intensity value (1-10), defaults to LED_INTENSITY_DEFAULT if not set.
    """
    try:
        from DGTCentaurMods.utils.settings_persistence import load_section
        data = load_section("game", {"led_brightness": LED_INTENSITY_DEFAULT})
        return max(1, min(10, data.get("led_brightness", LED_INTENSITY_DEFAULT)))
    except Exception:
        return LED_INTENSITY_DEFAULT


@dataclass(frozen=True)
class LedCallbacks:
    """LED control callbacks for dependency injection.
    
    All LED operations should go through these callbacks so that
    speed and intensity can be configured centrally.
    
    Attributes:
        from_to: Light from/to squares (standard speed/intensity)
        array: Light array of squares (standard speed/intensity)
        single: Light single square (standard speed/intensity)
        off: Turn off all LEDs
        from_to_hint: Light from/to squares (slow speed, dim intensity)
        array_hint: Light array of squares (slow speed, dim intensity)
        array_fast: Flash squares urgently (fast speed, standard intensity)
    """
    # Standard operations (normal speed, standard intensity)
    from_to: Callable[[int, int, int], None]      # (from_sq, to_sq, repeat)
    array: Callable[[List[int], int], None]        # (squares, repeat)
    single: Callable[[int, int], None]             # (square, repeat)
    off: Callable[[], None]
    
    # Hint operations (slow speed, dim intensity)
    from_to_hint: Callable[[int, int, int], None]  # (from_sq, to_sq, repeat)
    array_hint: Callable[[List[int], int], None]   # (squares, repeat)
    
    # Fast operations (fast speed, standard intensity) - for corrections/errors
    array_fast: Callable[[List[int], int], None]   # (squares, repeat)
    from_to_fast: Callable[[int, int, int], None]  # (from_sq, to_sq, repeat)
    single_fast: Callable[[int, int], None]        # (square, repeat)


class LedController:
    """LED controller with configurable intensity.
    
    Wraps the board module's LED functions and applies consistent
    speed and intensity settings.
    """
    
    def __init__(self, board_module, intensity: int = LED_INTENSITY_DEFAULT):
        """Initialize LED controller.
        
        Args:
            board_module: The board module with LED functions.
            intensity: Standard intensity setting (1-10, default 5).
        """
        self._board = board_module
        self._intensity = intensity
    
    @property
    def intensity(self) -> int:
        """Get standard intensity setting."""
        return self._intensity
    
    @intensity.setter
    def intensity(self, value: int) -> None:
        """Set standard intensity setting."""
        self._intensity = max(1, min(10, value))
    
    @property
    def intensity_dim(self) -> int:
        """Get dim intensity (for hints). Standard * 10."""
        return self._intensity * 10
    
    # === Standard operations (normal speed, standard intensity) ===
    
    def from_to(self, from_sq: int, to_sq: int, repeat: int = 0) -> None:
        """Light up from/to squares - standard intensity, normal speed."""
        self._board.ledFromTo(from_sq, to_sq, 
                              intensity=self._intensity, 
                              speed=LED_SPEED_NORMAL, 
                              repeat=repeat)
    
    def array(self, squares: List[int], repeat: int = 0) -> None:
        """Light up array of squares - standard intensity, normal speed."""
        if squares:
            self._board.ledArray(squares, 
                                 speed=LED_SPEED_NORMAL, 
                                 intensity=self._intensity, 
                                 repeat=repeat)
    
    def single(self, square: int, repeat: int = 0) -> None:
        """Light up single square - standard intensity, normal speed."""
        self._board.led(square, 
                        intensity=self._intensity, 
                        speed=LED_SPEED_NORMAL, 
                        repeat=repeat)
    
    def off(self) -> None:
        """Turn off all LEDs."""
        self._board.ledsOff()
    
    # === Hint operations (slow speed, dim intensity) ===
    
    def from_to_hint(self, from_sq: int, to_sq: int, repeat: int = 2) -> None:
        """Light up from/to squares for hints - dim intensity, slow speed."""
        self._board.ledFromTo(from_sq, to_sq,
                              intensity=self.intensity_dim,
                              speed=LED_SPEED_SLOW,
                              repeat=repeat)
    
    def array_hint(self, squares: List[int], repeat: int = 0) -> None:
        """Light up array of squares for hints - dim intensity, slow speed."""
        if squares:
            self._board.ledArray(squares,
                                 speed=LED_SPEED_SLOW,
                                 intensity=self.intensity_dim,
                                 repeat=repeat)
    
    # === Fast operations (fast speed, standard intensity) ===
    
    def array_fast(self, squares: List[int], repeat: int) -> None:
        """Flash squares urgently - standard intensity, fast speed."""
        if squares:
            self._board.ledArray(squares, 
                                 speed=LED_SPEED_FAST, 
                                 intensity=self._intensity, 
                                 repeat=repeat)
    
    def from_to_fast(self, from_sq: int, to_sq: int, repeat: int = 0) -> None:
        """Light up from/to squares urgently - standard intensity, fast speed."""
        self._board.ledFromTo(from_sq, to_sq,
                              intensity=self._intensity,
                              speed=LED_SPEED_FAST,
                              repeat=repeat)
    
    def single_fast(self, square: int, repeat: int = 0) -> None:
        """Light up single square urgently - standard intensity, fast speed."""
        self._board.led(square,
                        intensity=self._intensity,
                        speed=LED_SPEED_FAST,
                        repeat=repeat)
    
    # === Create callbacks dataclass ===
    
    def get_callbacks(self) -> LedCallbacks:
        """Create LedCallbacks dataclass with bound methods."""
        return LedCallbacks(
            from_to=self.from_to,
            array=self.array,
            single=self.single,
            off=self.off,
            from_to_hint=self.from_to_hint,
            array_hint=self.array_hint,
            array_fast=self.array_fast,
            from_to_fast=self.from_to_fast,
            single_fast=self.single_fast,
        )


__all__ = [
    "LED_SPEED_SLOW",
    "LED_SPEED_NORMAL", 
    "LED_SPEED_FAST",
    "LED_INTENSITY_DEFAULT",
    "LedCallbacks",
    "LedController",
    "get_led_intensity_from_settings",
]

