"""
Base class for game controllers.

A GameController determines how the game is controlled - whether moves come
from local players (human/engine) or from an external app (Bluetooth).
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from universalchess.managers.game import GameManager


class GameController(ABC):
    """Abstract base class for game controllers.
    
    Controllers manage how moves are submitted to the game. Only one controller
    should be active at a time:
    
    - LocalController: Moves come from PlayerManager (human + engine players)
    - RemoteController: Moves come from external Bluetooth app
    
    The active controller receives field/key events and routes them appropriately.
    """
    
    def __init__(self, game_manager: 'GameManager'):
        """Initialize the controller.
        
        Args:
            game_manager: The GameManager instance for game state.
        """
        self._game_manager = game_manager
        self._active = False
    
    @property
    def is_active(self) -> bool:
        """Whether this controller is currently active."""
        return self._active
    
    @abstractmethod
    def start(self) -> None:
        """Start controlling the game.
        
        Called when this controller becomes active. Should initialize any
        resources needed and begin processing events.
        """
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop controlling the game.
        
        Called when this controller is deactivated. Should clean up any
        pending operations but not necessarily release all resources
        (controller may be reactivated later).
        """
        pass
    
    @abstractmethod
    def on_field_event(self, piece_event: int, field: int, time_seconds: float) -> None:
        """Handle piece lift/place event from the physical board.
        
        Args:
            piece_event: 0 = lift, 1 = place
            field: Board field index (0-63)
            time_seconds: Event timestamp
        """
        pass
    
    @abstractmethod
    def on_key_event(self, key) -> None:
        """Handle key press from the physical board.
        
        Args:
            key: Key identifier (board.Key enum value)
        """
        pass
