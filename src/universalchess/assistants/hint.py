# Hint Assistant
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Provides move hints on demand. Used when the player presses the
# HELP button to get a suggestion for the current position.
#
# Also supports predefined hints from positions.ini for puzzles.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

import threading
from dataclasses import dataclass
from typing import Optional, Tuple

import chess

from universalchess.board.logging import log
from .base import Assistant, AssistantConfig, Suggestion, SuggestionType


@dataclass
class HintConfig(AssistantConfig):
    """Configuration for hint assistant.
    
    Attributes:
        name: Display name.
        time_limit_seconds: Time limit for dynamic hint computation (when backed by an engine/analysis service).
        auto_suggest: Always False for hints (only on request).
        engine_name: Name of the engine to use for dynamic hints.
        elo_section: ELO section from the engine's .uci config file.
        predefined_hint: Optional predefined hint move (for puzzles).
    """
    name: str = "Hint"
    auto_suggest: bool = False  # Only provide hints on request
    engine_name: str = "stockfish"
    elo_section: str = "Default"
    predefined_hint: Optional[chess.Move] = None


class HintAssistant(Assistant):
    """On-demand hint assistant.
    
    Provides move hints when requested. Two modes:
    
    1. Predefined hints: For puzzles/positions with known solutions.
       Set via set_predefined_hint() or HintConfig.predefined_hint.
    
    2. Dynamic hints: Queries an analysis engine for the best move.
       Requires set_analysis_callback() to connect to analysis widget.
    
    This assistant is NOT auto-suggest - it only provides suggestions
    when explicitly requested via get_suggestion() (e.g., HELP button).
    """
    
    def __init__(self, config: Optional[HintConfig] = None):
        """Initialize the hint assistant.
        
        Args:
            config: Configuration for the assistant.
        """
        super().__init__(config or HintConfig())
        self._hint_config: HintConfig = self._config
        
        # Predefined hint (for puzzles)
        self._predefined_hint: Optional[chess.Move] = self._hint_config.predefined_hint
        self._predefined_from_sq: Optional[int] = None
        self._predefined_to_sq: Optional[int] = None
        
        # Analysis callback for dynamic hints
        self._analysis_callback = None
        
        # Current hint state
        self._current_hint: Optional[chess.Move] = None
        self._pending_hint: Optional[Tuple[int, int]] = None  # (from_sq, to_sq)
    
    @property
    def has_predefined_hint(self) -> bool:
        """Whether a predefined hint is set."""
        return self._predefined_hint is not None or self._predefined_from_sq is not None
    
    @property
    def current_hint(self) -> Optional[chess.Move]:
        """The current hint move, if any."""
        return self._current_hint
    
    def set_predefined_hint(self, from_sq: int, to_sq: int) -> None:
        """Set a predefined hint from square indices.
        
        Used for puzzles where the solution is known.
        
        Args:
            from_sq: Source square index (0-63).
            to_sq: Target square index (0-63).
        """
        self._predefined_from_sq = from_sq
        self._predefined_to_sq = to_sq
        log.info(f"[HintAssistant] Predefined hint set: {from_sq} -> {to_sq}")
    
    def set_predefined_move(self, move: chess.Move) -> None:
        """Set a predefined hint from a chess.Move.
        
        Args:
            move: The hint move.
        """
        self._predefined_hint = move
        self._predefined_from_sq = move.from_square
        self._predefined_to_sq = move.to_square
        log.info(f"[HintAssistant] Predefined hint set: {move.uci()}")
    
    def clear_predefined_hint(self) -> None:
        """Clear any predefined hint."""
        self._predefined_hint = None
        self._predefined_from_sq = None
        self._predefined_to_sq = None
        log.debug("[HintAssistant] Predefined hint cleared")
    
    def set_pending_hint(self, from_sq: int, to_sq: int) -> None:
        """Set a pending hint to show after correction mode.
        
        Used when loading a position with a hint - the hint is shown
        after the player sets up the position correctly.
        
        Args:
            from_sq: Source square index.
            to_sq: Target square index.
        """
        self._pending_hint = (from_sq, to_sq)
        log.debug(f"[HintAssistant] Pending hint set: {from_sq} -> {to_sq}")
    
    def get_pending_hint(self) -> Optional[Tuple[int, int]]:
        """Get and clear the pending hint.
        
        Returns:
            Tuple of (from_sq, to_sq) or None.
        """
        hint = self._pending_hint
        self._pending_hint = None
        return hint
    
    def set_analysis_callback(self, callback) -> None:
        """Set callback to get hints from analysis engine.
        
        The callback should return the current best move from analysis.
        Signature: callback(board: chess.Board) -> Optional[chess.Move]
        
        Args:
            callback: Function to get best move from analysis.
        """
        self._analysis_callback = callback
    
    def start(self) -> bool:
        """Start the hint assistant.
        
        Always succeeds - hints are either predefined or from analysis.
        
        Returns:
            True always.
        """
        log.info("[HintAssistant] Hint assistant started")
        self._active = True
        return True
    
    def stop(self) -> None:
        """Stop the hint assistant."""
        log.info("[HintAssistant] Hint assistant stopped")
        self._active = False
        self._current_hint = None
    
    def get_suggestion(self, board: chess.Board, for_color: chess.Color) -> Optional[Suggestion]:
        """Get a hint for the current position.
        
        Priority:
        1. Predefined hint (if set and legal)
        2. Analysis engine hint (if callback set)
        
        Args:
            board: Current chess position.
            for_color: Which color to provide hints for (used for context,
                      hints are provided for the side to move).
        
        Returns:
            Suggestion with the hint move, or None if no hint available.
        """
        if not self._active:
            return None
        
        if board.is_game_over():
            return None
        
        # Try predefined hint first
        if self._predefined_from_sq is not None and self._predefined_to_sq is not None:
            try:
                # Construct move from squares
                from_sq = self._predefined_from_sq
                to_sq = self._predefined_to_sq
                
                # Check if it's a valid move
                for move in board.legal_moves:
                    if move.from_square == from_sq and move.to_square == to_sq:
                        self._current_hint = move
                        log.info(f"[HintAssistant] Predefined hint: {move.uci()}")
                        return Suggestion.hint_move(move)
                
                log.warning(f"[HintAssistant] Predefined hint not legal: {from_sq} -> {to_sq}")
            except Exception as e:
                log.warning(f"[HintAssistant] Error with predefined hint: {e}")
        
        # Try predefined move
        if self._predefined_hint is not None:
            if self._predefined_hint in board.legal_moves:
                self._current_hint = self._predefined_hint
                log.info(f"[HintAssistant] Predefined hint: {self._predefined_hint.uci()}")
                return Suggestion.hint_move(self._predefined_hint)
            else:
                log.warning(f"[HintAssistant] Predefined hint not legal: {self._predefined_hint.uci()}")
        
        # Try analysis callback
        if self._analysis_callback:
            try:
                hint_move = self._analysis_callback(board)
                if hint_move and hint_move in board.legal_moves:
                    self._current_hint = hint_move
                    log.info(f"[HintAssistant] Analysis hint: {hint_move.uci()}")
                    return Suggestion.hint_move(hint_move)
            except Exception as e:
                log.warning(f"[HintAssistant] Error getting analysis hint: {e}")
        
        log.info("[HintAssistant] No hint available")
        return None
    
    def on_player_move(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that the player made a move.
        
        Clears the current hint.
        """
        self._current_hint = None
        # Clear predefined hint after it's been used
        if self._predefined_hint is not None or self._predefined_from_sq is not None:
            self.clear_predefined_hint()
    
    def on_new_game(self) -> None:
        """Notification that a new game is starting."""
        log.info("[HintAssistant] New game")
        self._current_hint = None
        self.clear_predefined_hint()
        self._pending_hint = None
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notification that a takeback occurred."""
        self._current_hint = None
    
    def get_info(self) -> dict:
        """Get information about this assistant."""
        info = super().get_info()
        info.update({
            'type': 'hint',
            'has_predefined': self.has_predefined_hint,
            'engine_name': self._hint_config.engine_name,
            'elo_section': self._hint_config.elo_section,
            'description': 'Provides move hints on request',
        })
        return info


def create_hint_assistant(
    predefined_hint: Optional[chess.Move] = None,
    engine_name: str = "stockfish",
    elo_section: str = "Default",
    time_limit: float = 2.0,
) -> HintAssistant:
    """Factory function to create a hint assistant.
    
    Args:
        predefined_hint: Optional predefined hint move.
        engine_name: Engine name for dynamic hints.
        elo_section: Engine ELO section for dynamic hints.
        time_limit: Time limit (seconds) for dynamic hint computation.
    
    Returns:
        Configured HintAssistant instance.
    """
    config = HintConfig(
        name="Hint",
        predefined_hint=predefined_hint,
        engine_name=engine_name,
        elo_section=elo_section,
        time_limit_seconds=time_limit,
    )
    
    return HintAssistant(config)
