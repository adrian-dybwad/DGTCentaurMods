# Hand+Brain Player
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# A hybrid player for Hand+Brain chess variants where human and engine
# collaborate on moves:
#
# NORMAL mode (traditional Hand+Brain):
#   - Engine suggests which piece TYPE to move
#   - Human chooses the specific move with that piece type
#
# REVERSE mode:
#   - Human suggests which piece TYPE to move (by lifting/replacing a piece)
#   - Engine chooses the best specific move with that piece type
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Dict, List, Callable

import chess
import chess.engine

from DGTCentaurMods.board.logging import log
from .base import Player, PlayerConfig, PlayerState, PlayerType


class HandBrainMode(Enum):
    """Hand+Brain mode variants.
    
    NORMAL: Engine is the "Brain" (suggests piece type), Human is the "Hand" (chooses move).
    REVERSE: Human is the "Brain" (suggests piece type), Engine is the "Hand" (chooses move).
    """
    NORMAL = auto()
    REVERSE = auto()


class HandBrainPhase(Enum):
    """State machine for hand+brain turn flow.
    
    IDLE: Not this player's turn.
    COMPUTING_SUGGESTION: (NORMAL mode) Engine computing piece type suggestion.
    WAITING_HUMAN_MOVE: (NORMAL mode) Suggestion shown, waiting for human to move.
    WAITING_PIECE_SELECTION: (REVERSE mode) Waiting for human to lift/replace a piece.
    COMPUTING_MOVE: (REVERSE mode) Engine finding best move with selected piece type.
    WAITING_EXECUTION: (REVERSE mode) Move computed, waiting for human to execute.
    """
    IDLE = auto()
    COMPUTING_SUGGESTION = auto()
    WAITING_HUMAN_MOVE = auto()
    WAITING_PIECE_SELECTION = auto()
    COMPUTING_MOVE = auto()
    WAITING_EXECUTION = auto()


@dataclass
class HandBrainConfig(PlayerConfig):
    """Configuration for Hand+Brain player.
    
    Attributes:
        name: Display name for the player.
        color: The color this player plays.
        mode: NORMAL (engine suggests) or REVERSE (human suggests).
        time_limit_seconds: Maximum time per move for engine computation.
        engine_name: Name of the engine executable.
        engine_path: Full path to engine executable.
        elo_section: Section name from .uci config for ELO settings.
        uci_options: Additional UCI options to configure.
    """
    mode: HandBrainMode = HandBrainMode.NORMAL
    time_limit_seconds: float = 2.0
    engine_name: str = "stockfish"
    engine_path: Optional[str] = None
    elo_section: str = "Default"
    uci_options: Dict[str, str] = field(default_factory=dict)


# Callback for displaying the suggested piece type in NORMAL mode
# Args: color ('white' or 'black'), piece_symbol (e.g., 'N', 'B', 'R')
BrainHintCallback = Callable[[str, str], None]


class HandBrainPlayer(Player):
    """A hybrid player for Hand+Brain chess variants.
    
    In Hand+Brain chess, a human and engine collaborate on moves:
    
    NORMAL mode (traditional):
    - Engine analyzes the position and suggests which piece TYPE to move
    - The suggestion is displayed on screen (e.g., "N" for knight)
    - Human then chooses any legal move with that piece type
    - If human moves a different piece type, the move is rejected
    
    REVERSE mode:
    - Human lifts any piece of the type they want to move, then replaces it
    - Engine then finds the best move using only that piece type
    - The computed move is displayed via LEDs
    - Human executes the engine's chosen move on the board
    
    Thread Safety:
    - start() spawns initialization thread
    - Engine computation runs in background thread
    - stop() waits for threads to complete
    """
    
    def __init__(self, config: Optional[HandBrainConfig] = None):
        """Initialize the Hand+Brain player.
        
        Args:
            config: Player configuration. If None, uses defaults.
        """
        super().__init__(config or HandBrainConfig())
        self._hb_config: HandBrainConfig = self._config
        
        # Engine process handle
        self._engine: Optional[chess.engine.SimpleEngine] = None
        
        # Threading
        self._init_thread: Optional[threading.Thread] = None
        self._think_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Turn phase state machine
        self._phase = HandBrainPhase.IDLE
        
        # Current board position for this turn
        self._current_board: Optional[chess.Board] = None
        
        # NORMAL mode state
        self._suggested_piece_type: Optional[chess.PieceType] = None
        self._brain_hint_callback: Optional[BrainHintCallback] = None
        
        # REVERSE mode state
        self._selected_piece_type: Optional[chess.PieceType] = None
        self._selection_lifted_square: Optional[int] = None
        self._pending_move: Optional[chess.Move] = None
        
        # UCI options loaded from config file
        self._uci_options: Dict[str, str] = {}
    
    @property
    def player_type(self) -> PlayerType:
        """Player type depends on mode.
        
        NORMAL mode acts like a human (player decides the move).
        REVERSE mode acts like an engine (engine decides the move).
        """
        if self._hb_config.mode == HandBrainMode.NORMAL:
            return PlayerType.HUMAN
        else:
            return PlayerType.ENGINE
    
    @property
    def mode(self) -> HandBrainMode:
        """Current Hand+Brain mode."""
        return self._hb_config.mode
    
    @property
    def engine_name(self) -> str:
        """Name of the engine."""
        return self._hb_config.engine_name
    
    @property
    def elo_section(self) -> str:
        """ELO section being used."""
        return self._hb_config.elo_section
    
    @property
    def pending_move(self) -> Optional[chess.Move]:
        """The computed move waiting to be executed (REVERSE mode only)."""
        return self._pending_move
    
    @property
    def phase(self) -> HandBrainPhase:
        """Current phase of the turn flow."""
        return self._phase
    
    def set_brain_hint_callback(self, callback: BrainHintCallback) -> None:
        """Set callback for displaying brain hints (NORMAL mode).
        
        The callback is invoked when the engine suggests a piece type.
        
        Args:
            callback: Function(color, piece_symbol) to display the hint.
        """
        self._brain_hint_callback = callback
    
    def start(self) -> bool:
        """Initialize and start the engine.
        
        Spawns a background thread to load the engine.
        
        Returns:
            True if initialization started, False on immediate error.
        """
        if self._state not in (PlayerState.UNINITIALIZED, PlayerState.STOPPED):
            log.warning(f"[HandBrain] Cannot start - already in state {self._state}")
            return False
        
        self._set_state(PlayerState.INITIALIZING)
        mode_str = "Normal" if self.mode == HandBrainMode.NORMAL else "Reverse"
        self._report_status(f"Loading {self.engine_name} ({mode_str})...")
        
        # Find engine path
        engine_path = self._resolve_engine_path()
        if not engine_path:
            self._set_state(PlayerState.ERROR, f"Engine not found: {self.engine_name}")
            return False
        
        # Load UCI options from config file
        uci_file_path = self._resolve_uci_file_path()
        if uci_file_path:
            self._load_uci_options(uci_file_path)
        
        # Start engine initialization in background
        def _init_engine():
            try:
                log.info(f"[HandBrain] Starting engine: {engine_path}")
                engine = chess.engine.SimpleEngine.popen_uci(str(engine_path))
                
                # Apply UCI options
                if self._uci_options:
                    log.info(f"[HandBrain] Configuring with options: {self._uci_options}")
                    engine.configure(self._uci_options)
                
                with self._lock:
                    self._engine = engine
                
                log.info(f"[HandBrain] Engine ready: {self.engine_name} @ {self.elo_section} ({mode_str})")
                self._report_status(f"{self.engine_name} ready")
                self._set_state(PlayerState.READY)
                
            except Exception as e:
                log.error(f"[HandBrain] Failed to initialize engine: {e}")
                self._set_state(PlayerState.ERROR, str(e))
        
        self._init_thread = threading.Thread(
            target=_init_engine,
            name=f"hb-init-{self.engine_name}",
            daemon=True
        )
        self._init_thread.start()
        
        return True
    
    def stop(self) -> None:
        """Stop the engine and release resources."""
        log.info(f"[HandBrain] Stopping: {self.engine_name}")
        
        # Wait for init thread if running
        if self._init_thread and self._init_thread.is_alive():
            self._init_thread.join(timeout=1.0)
        
        # Close engine
        with self._lock:
            if self._engine:
                try:
                    self._engine.quit()
                    log.info(f"[HandBrain] Engine closed: {self.engine_name}")
                except Exception as e:
                    log.debug(f"[HandBrain] Error closing engine: {e}")
                self._engine = None
        
        self._set_state(PlayerState.STOPPED)
    
    def _do_request_move(self, board: chess.Board) -> None:
        """Begin the turn - behavior depends on mode.
        
        NORMAL mode: Compute and display piece type suggestion, then wait for human.
        REVERSE mode: Wait for human to select piece type.
        
        Args:
            board: Current chess position.
        """
        self._current_board = board.copy()
        self._lifted_squares = []
        
        if self._hb_config.mode == HandBrainMode.NORMAL:
            self._start_normal_mode_turn()
        else:
            self._start_reverse_mode_turn()
    
    # =========================================================================
    # NORMAL Mode - Engine suggests, human moves
    # =========================================================================
    
    def _start_normal_mode_turn(self) -> None:
        """Start turn in NORMAL mode: compute piece type suggestion."""
        log.info("[HandBrain] NORMAL mode turn started - computing suggestion")
        
        self._suggested_piece_type = None
        self._phase = HandBrainPhase.COMPUTING_SUGGESTION
        self._set_state(PlayerState.THINKING)
        self._report_status("Analyzing...")
        
        board_copy = self._current_board.copy()
        
        def _compute_suggestion():
            try:
                with self._lock:
                    if not self._engine:
                        log.warning("[HandBrain] Engine not ready")
                        return
                    
                    # Re-apply UCI options before computation
                    if self._uci_options:
                        self._engine.configure(self._uci_options)
                    
                    # Get engine's best move
                    result = self._engine.play(
                        board_copy,
                        chess.engine.Limit(time=self._hb_config.time_limit_seconds)
                    )
                    best_move = result.move
                
                if best_move:
                    # Extract piece type from the best move
                    piece = board_copy.piece_at(best_move.from_square)
                    if piece:
                        self._suggested_piece_type = piece.piece_type
                        piece_symbol = piece.symbol().upper()
                        piece_name = chess.piece_name(piece.piece_type).capitalize()
                        
                        log.info(f"[HandBrain] Suggestion: {piece_name} ({piece_symbol}) from best move {best_move.uci()}")
                        
                        # Display the hint
                        if self._brain_hint_callback:
                            color_str = 'white' if board_copy.turn == chess.WHITE else 'black'
                            self._brain_hint_callback(color_str, piece_symbol)
                        
                        self._phase = HandBrainPhase.WAITING_HUMAN_MOVE
                        self._report_status(f"Move your {piece_name}")
                    else:
                        log.warning("[HandBrain] Best move has no piece at from_square")
                        self._phase = HandBrainPhase.WAITING_HUMAN_MOVE
                else:
                    log.warning("[HandBrain] Engine returned no move")
                    self._phase = HandBrainPhase.WAITING_HUMAN_MOVE
                    
            except Exception as e:
                log.error(f"[HandBrain] Error computing suggestion: {e}")
                import traceback
                traceback.print_exc()
                # Fall back to letting human move any piece
                self._phase = HandBrainPhase.WAITING_HUMAN_MOVE
            finally:
                if self._state == PlayerState.THINKING:
                    self._set_state(PlayerState.READY)
        
        self._think_thread = threading.Thread(
            target=_compute_suggestion,
            name=f"hb-suggest-{self.engine_name}",
            daemon=True
        )
        self._think_thread.start()
    
    def _handle_normal_mode_move(self, move: chess.Move) -> None:
        """Validate and submit move in NORMAL mode.
        
        Checks that the moved piece matches the suggested type.
        
        Args:
            move: The formed move from piece events.
        """
        if self._current_board is None:
            log.warning("[HandBrain] No current board for move validation")
            if self._move_callback:
                self._move_callback(move)
            return
        
        # Get the piece that was moved
        moved_piece = self._current_board.piece_at(move.from_square)
        
        if moved_piece is None:
            log.warning(f"[HandBrain] No piece at move source {chess.square_name(move.from_square)}")
            if self._move_callback:
                self._move_callback(move)
            return
        
        # If we have a suggestion, validate the piece type matches
        if self._suggested_piece_type is not None:
            if moved_piece.piece_type != self._suggested_piece_type:
                suggested_name = chess.piece_name(self._suggested_piece_type).capitalize()
                moved_name = chess.piece_name(moved_piece.piece_type).capitalize()
                log.warning(f"[HandBrain] Wrong piece type: expected {suggested_name}, got {moved_name}")
                self._report_status(f"Use {suggested_name}!")
                self._report_error("wrong_piece_type")
                return
        
        # Move is valid - submit it
        log.info(f"[HandBrain] NORMAL mode move accepted: {move.uci()}")
        if self._move_callback:
            self._move_callback(move)
    
    # =========================================================================
    # REVERSE Mode - Human suggests, engine moves
    # =========================================================================
    
    def _start_reverse_mode_turn(self) -> None:
        """Start turn in REVERSE mode: wait for human to select piece type."""
        log.info("[HandBrain] REVERSE mode turn started - waiting for piece selection")
        
        self._pending_move = None
        self._selected_piece_type = None
        self._selection_lifted_square = None
        self._phase = HandBrainPhase.WAITING_PIECE_SELECTION
        
        self._set_state(PlayerState.THINKING)
        self._report_status("Lift piece to select type")
    
    def _handle_reverse_piece_selection(
        self, event_type: str, square: int, board: chess.Board
    ) -> None:
        """Handle piece events during piece type selection phase (REVERSE mode).
        
        The human lifts a piece to indicate the type they want to move,
        then replaces it on the same square to confirm the selection.
        
        Args:
            event_type: "lift" or "place"
            square: The square index
            board: Current chess position
        """
        if event_type == "lift":
            piece = board.piece_at(square)
            if piece is None:
                log.debug(f"[HandBrain] Lift on empty square {chess.square_name(square)}")
                return
            
            # Only allow selecting our own pieces
            if piece.color != board.turn:
                log.debug("[HandBrain] Cannot select opponent's piece")
                self._report_status("Select your own piece")
                return
            
            self._selection_lifted_square = square
            piece_name = chess.piece_name(piece.piece_type).capitalize()
            log.info(f"[HandBrain] Lifted {piece_name} from {chess.square_name(square)}")
            self._report_status(f"{piece_name} - replace to confirm")
        
        elif event_type == "place":
            if self._selection_lifted_square is None:
                return
            
            if square == self._selection_lifted_square:
                # Piece replaced on same square - selection confirmed
                piece = board.piece_at(square)
                if piece is None:
                    log.warning("[HandBrain] Piece disappeared from selection square")
                    self._selection_lifted_square = None
                    return
                
                self._selected_piece_type = piece.piece_type
                piece_name = chess.piece_name(piece.piece_type).capitalize()
                log.info(f"[HandBrain] Piece type selected: {piece_name}")
                
                # Start engine computation with this piece type
                self._compute_constrained_move(piece.piece_type)
            else:
                # Piece placed on different square - reset
                log.debug("[HandBrain] Piece placed elsewhere - ignoring")
                self._selection_lifted_square = None
                self._report_status("Lift piece to select type")
    
    def _compute_constrained_move(self, piece_type: chess.PieceType) -> None:
        """Find the best move using only the specified piece type (REVERSE mode).
        
        Args:
            piece_type: The piece type that must make the move.
        """
        if self._current_board is None:
            log.error("[HandBrain] No current board for computation")
            return
        
        self._phase = HandBrainPhase.COMPUTING_MOVE
        piece_name = chess.piece_name(piece_type).capitalize()
        self._report_status(f"Finding best {piece_name} move...")
        
        # Get legal moves with this piece type
        legal_moves = self._get_legal_moves_for_piece_type(
            self._current_board, piece_type
        )
        
        if not legal_moves:
            log.info(f"[HandBrain] No legal moves with {piece_name}")
            self._report_status(f"No {piece_name} moves - select another")
            self._phase = HandBrainPhase.WAITING_PIECE_SELECTION
            self._selection_lifted_square = None
            return
        
        # If only one legal move, use it directly
        if len(legal_moves) == 1:
            move = legal_moves[0]
            log.info(f"[HandBrain] Only one {piece_name} move: {move.uci()}")
            self._set_pending_move(move)
            return
        
        # Multiple moves - use engine to find best one
        board_copy = self._current_board.copy()
        
        def _compute():
            try:
                with self._lock:
                    if not self._engine:
                        log.warning("[HandBrain] Engine not ready")
                        return
                    
                    # Re-apply UCI options before computation
                    if self._uci_options:
                        self._engine.configure(self._uci_options)
                    
                    # Use root_moves to constrain engine to only our legal moves
                    result = self._engine.play(
                        board_copy,
                        chess.engine.Limit(time=self._hb_config.time_limit_seconds),
                        root_moves=legal_moves
                    )
                    move = result.move
                
                if move:
                    log.info(f"[HandBrain] Best {piece_name} move: {move.uci()}")
                    self._set_pending_move(move)
                else:
                    log.warning("[HandBrain] Engine returned no move")
                    self._phase = HandBrainPhase.WAITING_PIECE_SELECTION
                    self._report_status("Engine error - select again")
                    
            except Exception as e:
                log.error(f"[HandBrain] Error computing move: {e}")
                import traceback
                traceback.print_exc()
                self._phase = HandBrainPhase.WAITING_PIECE_SELECTION
                self._report_status("Error - select again")
        
        self._think_thread = threading.Thread(
            target=_compute,
            name=f"hb-compute-{self.engine_name}",
            daemon=True
        )
        self._think_thread.start()
    
    def _get_legal_moves_for_piece_type(
        self, board: chess.Board, piece_type: chess.PieceType
    ) -> List[chess.Move]:
        """Get all legal moves where the moving piece is of the specified type.
        
        Args:
            board: Current position.
            piece_type: The piece type to filter by.
        
        Returns:
            List of legal moves starting with pieces of that type.
        """
        matching_moves = []
        for move in board.legal_moves:
            piece = board.piece_at(move.from_square)
            if piece and piece.piece_type == piece_type:
                matching_moves.append(move)
        return matching_moves
    
    def _set_pending_move(self, move: chess.Move) -> None:
        """Set the computed move and notify for LED display (REVERSE mode).
        
        Args:
            move: The computed best move.
        """
        self._pending_move = move
        self._phase = HandBrainPhase.WAITING_EXECUTION
        
        # Reset lifted squares for execution tracking
        self._lifted_squares = []
        
        piece_name = "piece"
        if self._selected_piece_type:
            piece_name = chess.piece_name(self._selected_piece_type).capitalize()
        
        self._report_status(f"Move {piece_name}: {move.uci()}")
        
        # Notify for LED display
        if self._pending_move_callback:
            self._pending_move_callback(move)
    
    def _handle_reverse_mode_execution(self, move: chess.Move) -> None:
        """Validate formed move matches the computed move (REVERSE mode).
        
        Args:
            move: The formed move from piece events.
        """
        log.debug(f"[HandBrain] REVERSE move formed: {move.uci()}")
        
        if self._pending_move is None:
            log.warning("[HandBrain] Move formed but no pending move")
            self._report_error("move_mismatch")
            return
        
        # Handle destination-only move (missed lift event)
        if move.from_square == move.to_square:
            if move.to_square == self._pending_move.to_square:
                log.warning("[HandBrain] MISSED LIFT RECOVERY: accepting destination-only move")
                if self._move_callback:
                    self._move_callback(self._pending_move)
                return
            else:
                log.warning("[HandBrain] Destination-only move mismatch")
                self._report_error("move_mismatch")
                return
        
        # Check if move matches (ignoring promotion)
        if (move.from_square == self._pending_move.from_square and
                move.to_square == self._pending_move.to_square):
            log.info(f"[HandBrain] REVERSE move matches: {self._pending_move.uci()}")
            if self._move_callback:
                self._move_callback(self._pending_move)
        else:
            log.warning(f"[HandBrain] Move mismatch: got {move.uci()}, expected {self._pending_move.uci()}")
            self._report_error("move_mismatch")
    
    # =========================================================================
    # Piece Event Handling (delegates based on mode and phase)
    # =========================================================================
    
    def on_piece_event(self, event_type: str, square: int, board: chess.Board) -> None:
        """Handle piece events based on current mode and phase.
        
        Args:
            event_type: "lift" or "place"
            square: The square index (0-63)
            board: Current chess position
        """
        if self._hb_config.mode == HandBrainMode.NORMAL:
            # In NORMAL mode, use standard piece event handling for human moves
            if self._phase in (HandBrainPhase.COMPUTING_SUGGESTION, HandBrainPhase.WAITING_HUMAN_MOVE):
                super().on_piece_event(event_type, square, board)
        else:
            # REVERSE mode
            if self._phase == HandBrainPhase.WAITING_PIECE_SELECTION:
                self._handle_reverse_piece_selection(event_type, square, board)
            elif self._phase == HandBrainPhase.WAITING_EXECUTION:
                super().on_piece_event(event_type, square, board)
    
    def _on_move_formed(self, move: chess.Move) -> None:
        """Called when a move is formed from piece events.
        
        Delegates to mode-specific handling.
        
        Args:
            move: The formed move.
        """
        if self._hb_config.mode == HandBrainMode.NORMAL:
            self._handle_normal_mode_move(move)
        else:
            self._handle_reverse_mode_execution(move)
    
    # =========================================================================
    # Game Event Handlers
    # =========================================================================
    
    def on_move_made(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that a move was made."""
        log.debug(f"[HandBrain] Move made: {move.uci()}")
        self._pending_move = None
        self._suggested_piece_type = None
        self._selected_piece_type = None
        self._phase = HandBrainPhase.IDLE
        self._lifted_squares = []
        if self._state == PlayerState.THINKING:
            self._set_state(PlayerState.READY)
    
    def on_new_game(self) -> None:
        """Notification that a new game is starting."""
        log.info("[HandBrain] New game - resetting")
        self._pending_move = None
        self._suggested_piece_type = None
        self._selected_piece_type = None
        self._phase = HandBrainPhase.IDLE
        self._current_board = None
        self._lifted_squares = []
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notification that a takeback occurred."""
        log.debug("[HandBrain] Takeback - resetting phase")
        self._pending_move = None
        self._suggested_piece_type = None
        self._selected_piece_type = None
        self._phase = HandBrainPhase.IDLE
    
    def clear_pending_move(self) -> None:
        """Clear any pending move (for external app takeover)."""
        if self._pending_move is not None:
            log.info(f"[HandBrain] Clearing pending move: {self._pending_move.uci()}")
            self._pending_move = None
            self._phase = HandBrainPhase.IDLE
            self._lifted_squares = []
    
    def get_info(self) -> dict:
        """Get information about this player for display."""
        info = super().get_info()
        mode_str = "Normal" if self.mode == HandBrainMode.NORMAL else "Reverse"
        info.update({
            'engine': self.engine_name,
            'elo': self.elo_section,
            'mode': mode_str,
            'description': f"H+B {mode_str} ({self.engine_name} @ {self.elo_section})",
            'phase': self._phase.name,
        })
        return info
    
    # =========================================================================
    # Engine Path Resolution
    # =========================================================================
    
    def _resolve_engine_path(self):
        """Find the engine executable."""
        import pathlib
        if self._hb_config.engine_path:
            path = pathlib.Path(self._hb_config.engine_path)
            if path.exists():
                return path
            log.warning(f"[HandBrain] Configured path not found: {path}")
        
        from DGTCentaurMods.paths import get_engine_path
        engine_path = get_engine_path(self._hb_config.engine_name)
        if engine_path:
            return pathlib.Path(engine_path)
        
        log.error(f"[HandBrain] Engine not found: {self._hb_config.engine_name}")
        return None
    
    def _resolve_uci_file_path(self):
        """Find the UCI configuration file for this engine."""
        import pathlib
        engine_name = self._hb_config.engine_name
        
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
        import configparser
        import os
        
        if not os.path.exists(uci_file_path):
            log.warning(f"[HandBrain] UCI file not found: {uci_file_path}")
            return
        
        config = configparser.ConfigParser()
        config.optionxform = str  # Preserve case for UCI option names
        config.read(uci_file_path)
        
        section = self._hb_config.elo_section
        
        if config.has_section(section):
            log.info(f"[HandBrain] Loading UCI options from section: {section}")
            for key, value in config.items(section):
                self._uci_options[key] = value
            
            # Filter out non-UCI metadata fields
            non_uci_fields = ['Description']
            self._uci_options = {
                k: v for k, v in self._uci_options.items()
                if k not in non_uci_fields
            }
        else:
            log.warning(f"[HandBrain] Section '{section}' not found in {uci_file_path}")
            if config.has_section("DEFAULT"):
                for key, value in config.items("DEFAULT"):
                    if key not in ['Description']:
                        self._uci_options[key] = value
        
        # Merge with explicitly configured options
        self._uci_options.update(self._hb_config.uci_options)


def create_hand_brain_player(
    color: chess.Color,
    mode: HandBrainMode = HandBrainMode.NORMAL,
    engine_name: str = "stockfish",
    elo_section: str = "Default",
    time_limit: float = 2.0
) -> HandBrainPlayer:
    """Factory function to create a Hand+Brain player.
    
    Args:
        color: The color this player plays (WHITE or BLACK).
        mode: NORMAL (engine suggests) or REVERSE (human suggests).
        engine_name: Name of the engine (e.g., "stockfish", "maia").
        elo_section: ELO section from .uci config file.
        time_limit: Maximum thinking time in seconds.
    
    Returns:
        Configured HandBrainPlayer instance.
    """
    mode_str = "Normal" if mode == HandBrainMode.NORMAL else "Reverse"
    config = HandBrainConfig(
        name=f"H+B {mode_str} ({engine_name})",
        color=color,
        mode=mode,
        time_limit_seconds=time_limit,
        engine_name=engine_name,
        elo_section=elo_section,
    )
    
    return HandBrainPlayer(config)
