# Hand+Brain Assistant
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Implements the "Brain" part of Hand+Brain mode. The engine suggests
# which piece type to move, and the player chooses which specific piece
# of that type to move and where.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

import configparser
import os
import pathlib
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, List

import chess
import chess.engine

from DGTCentaurMods.board.logging import log
from .base import Assistant, AssistantConfig, Suggestion, SuggestionType


@dataclass
class HandBrainConfig(AssistantConfig):
    """Configuration for Hand+Brain assistant.
    
    The Brain uses a chess engine to analyze the position and suggests
    which piece type should be moved.
    
    Attributes:
        name: Display name for the assistant.
        time_limit_seconds: Maximum time for engine analysis.
        auto_suggest: Always True for Hand+Brain (suggestions are automatic).
        engine_name: Name of the engine to use for analysis.
        engine_path: Full path to engine. If None, searches standard locations.
        elo_section: ELO section from .uci config file.
    """
    name: str = "Brain"
    auto_suggest: bool = True  # Always auto-suggest in Hand+Brain
    engine_name: str = "stockfish"
    engine_path: Optional[str] = None
    elo_section: str = "Default"


class HandBrainAssistant(Assistant):
    """Hand+Brain mode assistant.
    
    In Hand+Brain mode, the "Brain" (engine) suggests which piece type
    to move by analyzing the position. The "Hand" (player) then chooses
    which specific piece of that type to move and where.
    
    For example, if the engine's best move is Nf3, the Brain says "Knight"
    and highlights all the player's knights. The player then decides which
    knight to move and to which square.
    
    Thread Safety:
    - start() initializes the engine in a background thread
    - get_suggestion() runs engine analysis in a background thread
    - Suggestions are delivered via callback when ready
    """
    
    def __init__(self, config: Optional[HandBrainConfig] = None):
        """Initialize the Hand+Brain assistant.
        
        Args:
            config: Configuration for the assistant.
        """
        super().__init__(config or HandBrainConfig())
        self._brain_config: HandBrainConfig = self._config
        
        # Engine process
        self._engine: Optional[chess.engine.SimpleEngine] = None
        
        # Threading
        self._init_thread: Optional[threading.Thread] = None
        self._think_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._thinking = False
        
        # UCI options
        self._uci_options: Dict[str, str] = {}
        
        # Current suggestion (for display persistence)
        self._current_piece: Optional[str] = None
        self._current_squares: List[int] = []
    
    @property
    def engine_name(self) -> str:
        """Name of the analysis engine."""
        return self._brain_config.engine_name
    
    @property
    def current_piece(self) -> Optional[str]:
        """Currently suggested piece type (K, Q, R, B, N, P)."""
        return self._current_piece
    
    @property
    def current_squares(self) -> List[int]:
        """Squares containing the suggested piece type."""
        return self._current_squares.copy()
    
    def start(self) -> bool:
        """Initialize and start the Brain (engine).
        
        Returns:
            True if initialization started, False on immediate error.
        """
        if self._active:
            log.warning("[HandBrain] Already active")
            return True
        
        self._report_status(f"Loading {self.engine_name}...")
        
        # Find engine path
        engine_path = self._resolve_engine_path()
        if not engine_path:
            self._error_message = f"Engine not found: {self.engine_name}"
            log.error(f"[HandBrain] {self._error_message}")
            return False
        
        # Load UCI options from config file
        # UCI files are in config/engines/ or defaults/engines/, not next to binaries
        uci_file_path = self._resolve_uci_file_path()
        if uci_file_path:
            self._load_uci_options(uci_file_path)
        
        # Start engine initialization in background
        def _init_engine():
            try:
                log.info(f"[HandBrain] Starting engine: {engine_path}")
                engine = chess.engine.SimpleEngine.popen_uci(str(engine_path))
                
                if self._uci_options:
                    log.info(f"[HandBrain] Configuring with options: {self._uci_options}")
                    engine.configure(self._uci_options)
                
                with self._lock:
                    self._engine = engine
                    self._active = True
                
                log.info(f"[HandBrain] Brain ready: {self.engine_name}")
                self._report_status("Brain ready")
                
            except Exception as e:
                log.error(f"[HandBrain] Failed to initialize: {e}")
                self._error_message = str(e)
        
        self._init_thread = threading.Thread(
            target=_init_engine,
            name="brain-init",
            daemon=True
        )
        self._init_thread.start()
        
        return True
    
    def stop(self) -> None:
        """Stop the Brain and release resources."""
        log.info("[HandBrain] Stopping Brain")
        
        # Wait for init thread
        if self._init_thread and self._init_thread.is_alive():
            self._init_thread.join(timeout=1.0)
        
        # Close engine
        with self._lock:
            if self._engine:
                try:
                    self._engine.quit()
                    log.info("[HandBrain] Engine closed")
                except Exception as e:
                    log.debug(f"[HandBrain] Error closing engine: {e}")
                self._engine = None
            self._active = False
        
        self._current_piece = None
        self._current_squares = []
    
    def get_suggestion(self, board: chess.Board, for_color: chess.Color) -> Optional[Suggestion]:
        """Compute and return a piece type suggestion.
        
        Analyzes the position and determines which piece type should
        be moved based on the engine's best move.
        
        Args:
            board: Current chess position.
            for_color: Which color to provide suggestions for.
        
        Returns:
            None (suggestion delivered asynchronously via callback).
        """
        if not self._active:
            log.debug("[HandBrain] Not active, no suggestion")
            return None
        
        # Only suggest when it's the requested color's turn
        if board.turn != for_color:
            # Clear suggestion when it's not the requested color's turn
            self._clear_current_suggestion()
            return None
        
        if board.is_game_over():
            return None
        
        if self._thinking:
            log.debug("[HandBrain] Already thinking")
            return None
        
        with self._lock:
            if not self._engine:
                log.debug("[HandBrain] Engine not ready")
                return None
        
        self._thinking = True
        
        def _think():
            try:
                log.info("[HandBrain] Brain analyzing...")
                
                # Re-apply UCI options
                with self._lock:
                    if self._engine and self._uci_options:
                        self._engine.configure(self._uci_options)
                
                board_copy = board.copy()
                time_limit = self._brain_config.time_limit_seconds
                
                with self._lock:
                    if self._engine:
                        result = self._engine.play(
                            board_copy,
                            chess.engine.Limit(time=time_limit)
                        )
                        move = result.move
                    else:
                        move = None
                
                if move:
                    # Extract piece type from the best move
                    source_square = move.from_square
                    piece = board_copy.piece_at(source_square)
                    
                    if piece:
                        piece_symbol = piece.symbol().upper()
                        piece_type = piece.piece_type
                        piece_color = piece.color
                        
                        # Find all squares with same piece type and color
                        squares_with_piece = []
                        for sq in range(64):
                            p = board_copy.piece_at(sq)
                            if p and p.piece_type == piece_type and p.color == piece_color:
                                squares_with_piece.append(sq)
                        
                        log.info(f"[HandBrain] Suggests: {piece_symbol} (squares: {squares_with_piece})")
                        
                        # Store current suggestion
                        self._current_piece = piece_symbol
                        self._current_squares = squares_with_piece
                        
                        # Create and deliver suggestion
                        suggestion = Suggestion.piece(piece_symbol, squares_with_piece)
                        self._report_suggestion(suggestion)
                        
            except Exception as e:
                log.error(f"[HandBrain] Error analyzing: {e}")
                import traceback
                traceback.print_exc()
            finally:
                self._thinking = False
        
        self._think_thread = threading.Thread(
            target=_think,
            name="brain-think",
            daemon=True
        )
        self._think_thread.start()
        
        return None  # Suggestion delivered via callback
    
    def on_player_move(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that the player made a move.
        
        Clears the current suggestion since the move is complete.
        """
        log.debug(f"[HandBrain] Player moved: {move.uci()}")
        self._clear_current_suggestion()
    
    def on_opponent_move(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that the opponent made a move.
        
        Triggers analysis for the player's response.
        """
        log.debug(f"[HandBrain] Opponent moved: {move.uci()}")
        # Suggestion for player's turn will be triggered by get_suggestion
    
    def on_new_game(self) -> None:
        """Notification that a new game is starting."""
        log.info("[HandBrain] New game")
        self._clear_current_suggestion()
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notification that a takeback occurred."""
        log.debug("[HandBrain] Takeback - clearing suggestion")
        self._clear_current_suggestion()
    
    def clear_suggestion(self) -> None:
        """Clear the current suggestion display."""
        self._clear_current_suggestion()
        super().clear_suggestion()
    
    def get_info(self) -> dict:
        """Get information about this assistant."""
        info = super().get_info()
        info.update({
            'type': 'hand_brain',
            'engine': self.engine_name,
            'current_piece': self._current_piece,
            'description': 'Hand+Brain mode - engine suggests piece type',
        })
        return info
    
    def _clear_current_suggestion(self) -> None:
        """Clear the current piece suggestion."""
        self._current_piece = None
        self._current_squares = []
    
    def _resolve_engine_path(self) -> Optional[pathlib.Path]:
        """Find the engine executable.
        
        Uses paths.get_engine_path() which checks installed location first,
        then falls back to development location.
        """
        if self._brain_config.engine_path:
            path = pathlib.Path(self._brain_config.engine_path)
            if path.exists():
                return path
            log.warning(f"[HandBrain] Configured path not found: {path}")
        
        from DGTCentaurMods.paths import get_engine_path
        engine_path = get_engine_path(self._brain_config.engine_name)
        if engine_path:
            return pathlib.Path(engine_path)
        
        log.error(f"[HandBrain] Engine not found: {self._brain_config.engine_name}")
        return None
    
    def _resolve_uci_file_path(self) -> Optional[str]:
        """Find the UCI configuration file for this engine.
        
        Searches in:
        1. /opt/DGTCentaurMods/config/engines/ (production)
        2. defaults/engines/ relative to this module (development)
        
        Returns:
            Path to UCI file, or None if not found.
        """
        engine_name = self._brain_config.engine_name
        
        # Check production location
        prod_path = pathlib.Path(f"/opt/DGTCentaurMods/config/engines/{engine_name}.uci")
        if prod_path.exists():
            return str(prod_path)
        
        # Check development location
        dev_path = pathlib.Path(__file__).parent.parent / "defaults" / "engines" / f"{engine_name}.uci"
        if dev_path.exists():
            return str(dev_path)
        
        log.debug(f"[HandBrain] No UCI config found for {engine_name}")
        return None
    
    def _load_uci_options(self, uci_file_path: str) -> None:
        """Load UCI options from configuration file."""
        if not os.path.exists(uci_file_path):
            log.warning(f"[HandBrain] UCI file not found: {uci_file_path}")
            return
        
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(uci_file_path)
        
        section = self._brain_config.elo_section
        
        if config.has_section(section):
            log.info(f"[HandBrain] Loading UCI options from section: {section}")
            for key, value in config.items(section):
                self._uci_options[key] = value
            
            non_uci_fields = ['Description']
            self._uci_options = {
                k: v for k, v in self._uci_options.items()
                if k not in non_uci_fields
            }
        else:
            log.warning(f"[HandBrain] Section '{section}' not found")
            if config.has_section("DEFAULT"):
                for key, value in config.items("DEFAULT"):
                    if key not in ['Description']:
                        self._uci_options[key] = value


def create_hand_brain_assistant(
    engine_name: str = "stockfish",
    elo_section: str = "Default",
    time_limit: float = 2.0
) -> HandBrainAssistant:
    """Factory function to create a Hand+Brain assistant.
    
    Args:
        engine_name: Engine for analysis.
        elo_section: ELO section from .uci config file.
        time_limit: Maximum analysis time in seconds.
    
    Returns:
        Configured HandBrainAssistant instance.
    """
    config = HandBrainConfig(
        name="Brain",
        time_limit_seconds=time_limit,
        engine_name=engine_name,
        elo_section=elo_section,
    )
    
    return HandBrainAssistant(config)
