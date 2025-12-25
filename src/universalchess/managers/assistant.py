# Assistant Manager
#
# This file is part of the Universal-Chess project
# ( https://github.com/adrian-dybwad/Universal-Chess )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Provides a unified interface for assistant management. The game coordinator
# (main.py) works with this manager without needing to know the specific
# assistant type (Hand+Brain, hint, etc.).
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Callable

import chess

from universalchess.board.logging import log
from universalchess.assistants import (
    Assistant,
    Suggestion,
    SuggestionType,
    create_hand_brain_assistant,
    create_hint_assistant,
)


class AssistantType(Enum):
    """Types of assistants supported by the manager."""
    NONE = auto()        # No assistant
    HAND_BRAIN = auto()  # Suggests which piece type to move
    HINT = auto()        # On-demand move hints


@dataclass
class AssistantManagerConfig:
    """Configuration for creating an assistant.
    
    This is the unified configuration that the game coordinator passes
    to the AssistantManager. The manager determines the assistant type
    and creates the appropriate implementation.
    
    Attributes:
        assistant_type: Type of assistant to create.
        engine_name: Name of UCI engine for analysis.
        elo_section: ELO section from .uci config file.
        time_limit: Time limit for assistant analysis in seconds.
    """
    assistant_type: AssistantType = AssistantType.NONE
    
    # Engine configuration for assistants that use an engine
    engine_name: str = "stockfish"
    elo_section: str = "Default"
    time_limit: float = 2.0


class AssistantManager:
    """Manages assistant lifecycle and provides unified interface.
    
    The game coordinator creates an AssistantManager with configuration,
    then interacts with it through a standard interface without needing
    to know the specific assistant type.
    
    This follows the Facade pattern - hiding assistant implementation
    details behind a simple interface.
    
    Example:
        # In main.py
        config = AssistantManagerConfig(
            assistant_type=AssistantType.HAND_BRAIN,
            engine_name="stockfish"
        )
        assistant_mgr = AssistantManager(
            config,
            suggestion_callback=on_suggestion,
            status_callback=lambda msg: log.info(msg)
        )
        assistant_mgr.start()
        
        # When it's the player's turn:
        assistant_mgr.request_suggestion(board, player_color)
        
        # On cleanup:
        assistant_mgr.stop()
    """
    
    def __init__(
        self,
        config: AssistantManagerConfig,
        suggestion_callback: Optional[Callable[[Suggestion], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        """Initialize the assistant manager.
        
        Args:
            config: Configuration specifying assistant type and parameters.
            suggestion_callback: Called when assistant has a suggestion ready.
            status_callback: Called with status messages (e.g., "Analyzing...").
        """
        self._config = config
        self._assistant: Optional[Assistant] = None
        self._suggestion_callback = suggestion_callback
        self._status_callback = status_callback
        
        if config.assistant_type != AssistantType.NONE:
            self._create_assistant()
            self._wire_callbacks()
    
    def _create_assistant(self) -> None:
        """Create the appropriate assistant based on configuration."""
        if self._config.assistant_type == AssistantType.HAND_BRAIN:
            self._assistant = create_hand_brain_assistant(
                engine_name=self._config.engine_name,
                elo_section=self._config.elo_section,
                time_limit=self._config.time_limit
            )
            log.info(f"[AssistantManager] Created Hand+Brain assistant: "
                    f"{self._config.engine_name} @ {self._config.elo_section}")
            
        elif self._config.assistant_type == AssistantType.HINT:
            self._assistant = create_hint_assistant(
                engine_name=self._config.engine_name,
                time_limit=self._config.time_limit
            )
            log.info(f"[AssistantManager] Created hint assistant: {self._config.engine_name}")
        
        else:
            log.debug("[AssistantManager] No assistant configured")
    
    def _wire_callbacks(self) -> None:
        """Wire all callbacks to the assistant.
        
        Called after assistant creation and when callbacks are set.
        """
        if not self._assistant:
            return
        
        if self._suggestion_callback:
            self._assistant.set_suggestion_callback(self._suggestion_callback)
        if self._status_callback:
            self._assistant.set_status_callback(self._status_callback)
    
    # =========================================================================
    # Callback Setters - Can also be called after construction
    # =========================================================================
    
    def set_suggestion_callback(self, callback: Callable[[Suggestion], None]) -> None:
        """Set callback for when assistant provides a suggestion.
        
        Args:
            callback: Function(suggestion) called when suggestion is ready.
        """
        self._suggestion_callback = callback
        if self._assistant:
            self._assistant.set_suggestion_callback(callback)
    
    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for assistant status messages.
        
        Args:
            callback: Function(message) for status updates (e.g., "Analyzing...").
        """
        self._status_callback = callback
        if self._assistant:
            self._assistant.set_status_callback(callback)
    
    # =========================================================================
    # Lifecycle Methods
    # =========================================================================
    
    def start(self) -> bool:
        """Start the assistant.
        
        Returns:
            True if assistant started successfully (or no assistant configured).
        """
        if not self._assistant:
            return True  # No assistant is a valid state
        
        return self._assistant.start()
    
    def stop(self) -> None:
        """Stop the assistant and release resources."""
        if self._assistant:
            self._assistant.stop()
    
    def on_new_game(self) -> None:
        """Notify assistant of new game."""
        if self._assistant:
            self._assistant.on_new_game()
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notify assistant of takeback.
        
        Args:
            board: Current board position after takeback.
        """
        if self._assistant:
            self._assistant.on_takeback(board)
    
    # =========================================================================
    # Suggestion Methods
    # =========================================================================
    
    def request_suggestion(self, board: chess.Board, for_color: chess.Color) -> None:
        """Request a suggestion from the assistant.
        
        The suggestion will be delivered asynchronously via the callback.
        
        Args:
            board: Current board position.
            for_color: The color to provide suggestions for.
        """
        if self._assistant:
            self._assistant.get_suggestion(board, for_color)
    
    def clear_suggestion(self) -> None:
        """Clear any current suggestion.
        
        Called when it's no longer the player's turn or when a move is made.
        """
        if self._assistant:
            self._assistant.clear_suggestion()
    
    # =========================================================================
    # Properties
    # =========================================================================
    
    @property
    def is_active(self) -> bool:
        """Check if assistant is active."""
        return self._assistant.is_active if self._assistant else False
    
    @property
    def is_enabled(self) -> bool:
        """Check if an assistant is configured."""
        return self._assistant is not None
    
    @property
    def auto_suggest(self) -> bool:
        """Check if assistant provides automatic suggestions.
        
        Hand+Brain auto-suggests on player's turn.
        Hint only suggests on request.
        """
        return self._assistant.auto_suggest if self._assistant else False
    
    @property
    def is_hand_brain(self) -> bool:
        """Check if assistant is Hand+Brain mode."""
        return self._config.assistant_type == AssistantType.HAND_BRAIN
    
    @property
    def is_hint(self) -> bool:
        """Check if assistant is hint mode."""
        return self._config.assistant_type == AssistantType.HINT
    
    def get_info(self) -> dict:
        """Get information about the current assistant."""
        if self._assistant:
            return self._assistant.get_info()
        return {'type': 'none', 'name': 'None'}
