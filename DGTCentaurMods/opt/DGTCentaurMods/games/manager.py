"""
Chess game manager with complete state management and event-driven architecture.

This module provides a clean, class-based implementation for managing chess games
on the DGT Centaur board. It handles game state, turn tracking, move validation,
misplaced piece correction, and opponent move guidance.
"""

from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log
import chess
import threading
import time
from typing import Callable, Optional, List, Tuple
from scipy.optimize import linear_sum_assignment
import numpy as np

# Event constants
EVENT_NEW_GAME = 1
EVENT_WHITE_TURN = 2
EVENT_BLACK_TURN = 3
EVENT_REQUEST_DRAW = 4
EVENT_RESIGN_GAME = 5

# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
MIN_UCI_MOVE_LENGTH = 4

# Starting position: pieces on ranks 1-2 (squares 0-15) and ranks 7-8 (squares 48-63)
STARTING_STATE = bytearray(
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 1 (squares 0-7)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 2 (squares 8-15)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 3 (squares 16-23)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 4 (squares 24-31)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 5 (squares 32-39)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 6 (squares 40-47)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 7 (squares 48-55)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 8 (squares 56-63)
)
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class GameManager:
    """
    Manages chess game state, board events, and provides event-driven notifications.
    
    Features:
    - Complete chess game state management using python-chess
    - Automatic turn tracking
    - Event-driven notifications to subscribers
    - Board event subscription
    - Hardware abstraction (LEDs, beeps)
    - Misplaced piece guidance
    - Opponent move guidance even during misplaced piece corrections
    """
    
    def __init__(self):
        """Initialize the game manager."""
        self._board = chess.Board()
        self._kill = False
        self._running = False
        
        # Event subscribers
        self._event_callbacks: List[Callable] = []
        self._move_callbacks: List[Callable] = []
        self._key_callbacks: List[Callable] = []
        
        # Move state
        self._source_square: Optional[int] = None
        self._legal_squares: List[int] = []
        self._opponent_source_square: Optional[int] = None
        
        # Forced move (computer move)
        self._forced_move: Optional[str] = None
        self._forced_move_active = False
        
        # Board state history for validation and takeback detection
        self._board_states: List[bytearray] = []
        
        # Correction mode for misplaced pieces
        self._correction_mode = False
        self._correction_expected_state: Optional[bytearray] = None
        self._correction_just_exited = False
        
        # Threading
        self._event_thread: Optional[threading.Thread] = None
        
    def subscribe_event(self, callback: Callable):
        """Subscribe to game events (NEW_GAME, WHITE_TURN, BLACK_TURN, etc.)."""
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)
    
    def unsubscribe_event(self, callback: Callable):
        """Unsubscribe from game events."""
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)
    
    def subscribe_move(self, callback: Callable):
        """Subscribe to move events (receives UCI move strings)."""
        if callback not in self._move_callbacks:
            self._move_callbacks.append(callback)
    
    def unsubscribe_move(self, callback: Callable):
        """Unsubscribe from move events."""
        if callback in self._move_callbacks:
            self._move_callbacks.remove(callback)
    
    def subscribe_key(self, callback: Callable):
        """Subscribe to key press events."""
        if callback not in self._key_callbacks:
            self._key_callbacks.append(callback)
    
    def unsubscribe_key(self, callback: Callable):
        """Unsubscribe from key press events."""
        if callback in self._key_callbacks:
            self._key_callbacks.remove(callback)
    
    def _notify_event(self, event: int):
        """Notify all event subscribers."""
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as e:
                log.error(f"Error in event callback: {e}")
    
    def _notify_move(self, move: str):
        """Notify all move subscribers."""
        for callback in self._move_callbacks:
            try:
                callback(move)
            except Exception as e:
                log.error(f"Error in move callback: {e}")
    
    def _notify_key(self, key):
        """Notify all key subscribers."""
        for callback in self._key_callbacks:
            try:
                callback(key)
            except Exception as e:
                log.error(f"Error in key callback: {e}")
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self._board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self._board.fen()
    
    def is_starting_position(self, state: Optional[bytearray] = None) -> bool:
        """Check if board state matches starting position."""
        if state is None:
            state = bytearray(board.getChessState())
        return bytearray(state) == STARTING_STATE
    
    def _collect_board_state(self):
        """Collect current board state for history."""
        state = bytearray(board.getChessState())
        self._board_states.append(state)
        # Limit history size to prevent memory leak
        if len(self._board_states) > 100:
            self._board_states.pop(0)
    
    def _reset_move_state(self):
        """Reset move-related state variables."""
        self._source_square = None
        self._legal_squares = []
        self._opponent_source_square = None
        board.ledsOff()
    
    def _calculate_legal_squares(self, square: int) -> List[int]:
        """Calculate legal destination squares for a piece at the given square."""
        legal_squares = [square]  # Include source square
        for move in self._board.legal_moves:
            if move.from_square == square:
                legal_squares.append(move.to_square)
        return legal_squares
    
    def _uci_to_squares(self, uci_move: str) -> Tuple[Optional[int], Optional[int]]:
        """Convert UCI move string to square indices."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return None, None
        from_sq = ((ord(uci_move[1]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[0]) - ord("a"))
        to_sq = ((ord(uci_move[3]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[2]) - ord("a"))
        return from_sq, to_sq
    
    def _validate_board_state(self, current: bytearray, expected: bytearray) -> bool:
        """Validate board state matches expected state."""
        if current is None or expected is None:
            return False
        if len(current) != BOARD_SIZE or len(expected) != BOARD_SIZE:
            return False
        return bytearray(current) == bytearray(expected)
    
    def _provide_correction_guidance(self, current_state: bytearray, expected_state: bytearray):
        """Provide LED guidance to correct misplaced pieces using Hungarian algorithm."""
        if current_state is None or expected_state is None:
            return
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return
        
        def _rc(idx):
            """Convert square index to (row, col)."""
            return (idx // BOARD_WIDTH), (idx % BOARD_WIDTH)
        
        def _dist(a, b):
            """Manhattan distance between two squares."""
            ar, ac = _rc(a)
            br, bc = _rc(b)
            return abs(ar - br) + abs(ac - bc)
        
        # Find misplaced pieces
        missing_origins = []  # Squares that should have pieces but don't
        wrong_locations = []  # Squares that have pieces but shouldn't
        
        for i in range(BOARD_SIZE):
            if expected_state[i] == 1 and current_state[i] == 0:
                missing_origins.append(i)
            elif expected_state[i] == 0 and current_state[i] == 1:
                wrong_locations.append(i)
        
        if len(missing_origins) == 0 and len(wrong_locations) == 0:
            # Board is correct
            board.ledsOff()
            return
        
        log.warning(f"[GameManager] Found {len(wrong_locations)} wrong pieces, {len(missing_origins)} missing pieces")
        
        # Guide one piece at a time
        if len(wrong_locations) > 0 and len(missing_origins) > 0:
            n_wrong = len(wrong_locations)
            n_missing = len(missing_origins)
            
            if n_wrong == 1 and n_missing == 1:
                # Simple case
                from_idx = wrong_locations[0]
                to_idx = missing_origins[0]
            else:
                # Use Hungarian algorithm for optimal pairing
                costs = np.zeros((n_wrong, n_missing))
                for i, wl in enumerate(wrong_locations):
                    for j, mo in enumerate(missing_origins):
                        costs[i, j] = _dist(wl, mo)
                
                row_ind, col_ind = linear_sum_assignment(costs)
                from_idx = wrong_locations[row_ind[0]]
                to_idx = missing_origins[col_ind[0]]
            
            board.ledsOff()
            board.ledFromTo(from_idx, to_idx, intensity=5)
            log.warning(f"[GameManager] Guiding piece from {chess.square_name(from_idx)} to {chess.square_name(to_idx)}")
        else:
            # Only pieces missing or only extra pieces
            if len(missing_origins) > 0:
                board.ledsOff()
                for idx in missing_origins:
                    board.led(idx, intensity=5)
                log.warning(f"[GameManager] Pieces missing at: {[chess.square_name(sq) for sq in missing_origins]}")
            elif len(wrong_locations) > 0:
                board.ledsOff()
                for idx in wrong_locations:
                    board.led(idx, intensity=5)
                log.warning(f"[GameManager] Extra pieces at: {[chess.square_name(sq) for sq in wrong_locations]}")
    
    def _enter_correction_mode(self):
        """Enter correction mode to guide user in fixing board state."""
        self._correction_mode = True
        self._correction_expected_state = self._board_states[-1] if self._board_states else None
        self._correction_just_exited = False
        log.warning(f"[GameManager] Entered correction mode")
    
    def _exit_correction_mode(self):
        """Exit correction mode and restore forced move LEDs if needed."""
        self._correction_mode = False
        self._correction_expected_state = None
        self._correction_just_exited = True
        log.warning("[GameManager] Exited correction mode")
        
        # Reset move state
        self._source_square = None
        self._legal_squares = []
        self._opponent_source_square = None
        
        # Restore forced move LEDs if pending
        if self._forced_move_active and self._forced_move and len(self._forced_move) >= MIN_UCI_MOVE_LENGTH:
            from_sq, to_sq = self._uci_to_squares(self._forced_move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
                log.info(f"[GameManager] Restored forced move LEDs: {self._forced_move}")
    
    def _check_takeback(self) -> bool:
        """Check if a takeback is in progress by comparing current state to previous state."""
        if len(self._board_states) < 2:
            return False
        
        current_state = bytearray(board.getChessState())
        previous_state = self._board_states[-2]
        
        if self._validate_board_state(current_state, previous_state):
            # Takeback detected
            board.ledsOff()
            self._board_states.pop()  # Remove last state
            self._board.pop()  # Undo last move
            board.beep(board.SOUND_GENERAL)
            log.info("[GameManager] Takeback detected")
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            current = bytearray(board.getChessState())
            expected = self._board_states[-1] if self._board_states else None
            if not self._validate_board_state(current, expected):
                log.info("[GameManager] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            return True
        return False
    
    def _handle_promotion(self, field: int, piece_name: str, forced: bool) -> str:
        """Handle pawn promotion by prompting user for piece choice."""
        is_white_promotion = (field // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
        is_black_promotion = (field // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        if not forced:
            # Prompt user for promotion choice
            from DGTCentaurMods.display import epaper
            screenback = epaper.epaperbuffer.copy()
            epaper.promotionOptions(13)
            key = board.wait_for_key_up(timeout=60)
            epaper.epaperbuffer = screenback.copy()
            
            if key == board.Key.BACK:
                return "n"  # Knight
            elif key == board.Key.TICK:
                return "b"  # Bishop
            elif key == board.Key.UP:
                return "q"  # Queen
            elif key == board.Key.DOWN:
                return "r"  # Rook
            else:
                return "q"  # Default to queen
        return "q"  # Default to queen for forced moves
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """Handle field events (piece lift/place)."""
        if self._kill:
            return
        
        lift = (piece_event == 0)
        place = (piece_event == 1)
        
        field_name = chess.square_name(field)
        piece_color = self._board.color_at(field)
        
        log.info(f"[GameManager.field_callback] piece_event={'LIFT' if lift else 'PLACE'} field={field} fieldname={field_name} color_at={'White' if piece_color else 'Black'}")
        
        # Check if piece belongs to current player
        vpiece = (self._board.turn == chess.WHITE) == (piece_color == True)
        
        # Handle correction mode
        if self._correction_mode:
            current_state = bytearray(board.getChessState())
            
            # Check for starting position (new game)
            if self.is_starting_position(current_state):
                log.info("[GameManager] Starting position detected in correction mode - triggering new game")
                board.ledsOff()
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                self._reset_game()
                return
            
            # Check if board is now correct
            if self._validate_board_state(current_state, self._correction_expected_state):
                log.info("[GameManager] Board corrected, exiting correction mode")
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                return
            
            # Still incorrect, update guidance
            self._provide_correction_guidance(current_state, self._correction_expected_state)
            return
        
        # Normal game flow
        
        # Handle lift events
        if lift:
            self._correction_just_exited = False  # Clear flag on valid lift
            
            if vpiece:
                # Current player's piece lifted
                if self._source_square is None:
                    # Generate legal squares for this piece
                    self._legal_squares = self._calculate_legal_squares(field)
                    self._source_square = field
                    
                    # If opponent piece was lifted first, ensure that square is in legal squares if it's a capture
                    # (It should already be included in legal_squares from _calculate_legal_squares)
                    
                    # Handle forced move
                    if self._forced_move_active and self._forced_move:
                        forced_from, _ = self._uci_to_squares(self._forced_move)
                        if field != forced_from:
                            # Wrong piece lifted for forced move
                            self._legal_squares = [field]  # Can only put back
                        else:
                            # Correct piece, limit to target square
                            _, forced_to = self._uci_to_squares(self._forced_move)
                            self._legal_squares = [forced_to]
            else:
                # Opponent's piece lifted
                # This could be:
                # 1. Opponent piece lifted first (before player's piece) - track it
                # 2. Capture: player's piece already lifted, now lifting opponent piece
                # In case 2, the legal squares already include capture squares
                if self._source_square is None:
                    # Opponent piece lifted first - track it
                    # When player lifts their piece, legal squares will include this square if it's a valid capture
                    self._opponent_source_square = field
                else:
                    # Player already has a piece lifted - this is likely a capture
                    # Legal squares already calculated include capture squares
                    # Track opponent square for reference
                    self._opponent_source_square = field
        
        # Handle place events
        if place:
            # Ignore stale place events without corresponding lift
            if self._source_square is None and self._opponent_source_square is None:
                if self._correction_just_exited:
                    # Check if this is forced move source square
                    if self._forced_move_active and self._forced_move and len(self._forced_move) >= MIN_UCI_MOVE_LENGTH:
                        forced_source = chess.parse_square(self._forced_move[0:2])
                        if field != forced_source:
                            log.info(f"[GameManager] Ignoring stale PLACE event after correction exit for field {field}")
                            self._correction_just_exited = False
                            return
                    else:
                        log.info(f"[GameManager] Ignoring stale PLACE event after correction exit for field {field}")
                        self._correction_just_exited = False
                        return
                elif not self._forced_move_active:
                    log.info(f"[GameManager] Ignoring stale PLACE event for field {field} (no corresponding LIFT)")
                    return
            
            # Handle opponent piece placed back (not a capture)
            if not vpiece and self._opponent_source_square is not None and field == self._opponent_source_square:
                # Opponent piece placed back on original square
                board.ledsOff()
                self._opponent_source_square = None
                return
            
            # Handle capture: opponent piece lifted and placed on different square
            # This is handled as part of the normal move flow below
            
            # Handle illegal placement
            if self._source_square is not None and field not in self._legal_squares:
                board.beep(board.SOUND_WRONG_MOVE)
                log.warning(f"[GameManager] Piece placed on illegal square {field}")
                
                # Check for takeback
                if not self._check_takeback():
                    # Enter correction mode
                    self._enter_correction_mode()
                    current_state = bytearray(board.getChessState())
                    expected_state = self._board_states[-1] if self._board_states else None
                    if expected_state:
                        self._provide_correction_guidance(current_state, expected_state)
                return
            
            # Handle legal placement
            if self._source_square is not None and field in self._legal_squares:
                if field == self._source_square:
                    # Piece placed back on source
                    self._reset_move_state()
                else:
                    # Valid move
                    from_name = chess.square_name(self._source_square)
                    to_name = chess.square_name(field)
                    piece_name = str(self._board.piece_at(self._source_square))
                    promotion_suffix = self._handle_promotion(field, piece_name, self._forced_move_active)
                    
                    if self._forced_move_active:
                        move_str = self._forced_move
                    else:
                        move_str = from_name + to_name + promotion_suffix
                    
                    # Make the move
                    move = chess.Move.from_uci(move_str)
                    self._board.push(move)
                    self._collect_board_state()
                    self._reset_move_state()
                    
                    # Clear forced move
                    self._forced_move_active = False
                    self._forced_move = None
                    
                    # Notify subscribers
                    self._notify_move(move_str)
                    board.beep(board.SOUND_GENERAL)
                    board.led(field)
                    
                    # Check game outcome
                    outcome = self._board.outcome(claim_draw=True)
                    if outcome is None:
                        # Game continues, switch turn
                        if self._board.turn == chess.WHITE:
                            self._notify_event(EVENT_WHITE_TURN)
                        else:
                            self._notify_event(EVENT_BLACK_TURN)
                    else:
                        # Game over
                        board.beep(board.SOUND_GENERAL)
                        result_str = str(self._board.result())
                        termination = str(outcome.termination)
                        self._notify_event(termination)
                        log.info(f"[GameManager] Game over: {result_str} ({termination})")
    
    def _key_callback(self, key_pressed):
        """Handle key press events."""
        if self._kill:
            return
        
        # Notify subscribers
        self._notify_key(key_pressed)
    
    def _reset_game(self):
        """Reset game to starting position."""
        log.info("[GameManager] Resetting game to starting position")
        self._board.reset()
        self._reset_move_state()
        self._board_states = []
        self._collect_board_state()
        self._forced_move_active = False
        self._forced_move = None
        board.ledsOff()
        board.beep(board.SOUND_GENERAL)
        time.sleep(0.3)
        board.beep(board.SOUND_GENERAL)
        self._notify_event(EVENT_NEW_GAME)
        self._notify_event(EVENT_WHITE_TURN)
    
    def _event_thread_func(self):
        """Main event thread that monitors board state and handles new game detection."""
        log.info("[GameManager] Event thread started")
        
        # Check for starting position on startup
        initial_state = bytearray(board.getChessState())
        if self.is_starting_position(initial_state):
            log.info("[GameManager] Starting position detected on startup")
            self._reset_game()
        
        while not self._kill:
            try:
                # Check for starting position during game
                if not self._correction_mode and len(self._board_states) > 0:
                    current_state = bytearray(board.getChessState())
                    if self.is_starting_position(current_state):
                        # Check if it's different from last known state
                        if len(self._board_states) == 0 or not self._validate_board_state(current_state, self._board_states[-1]):
                            log.info("[GameManager] Starting position detected during game")
                            self._reset_game()
                
                time.sleep(0.1)
            except Exception as e:
                log.error(f"[GameManager] Error in event thread: {e}")
                time.sleep(0.1)
        
        log.info("[GameManager] Event thread exiting")
    
    def set_forced_move(self, move: str, active: bool = True):
        """
        Set a forced move (computer move) that the player must make.
        
        Args:
            move: UCI move string (e.g., "e2e4")
            active: Whether the forced move is active
        """
        if len(move) < MIN_UCI_MOVE_LENGTH:
            return
        
        self._forced_move = move
        self._forced_move_active = active
        
        # Light up LEDs to guide the move
        from_sq, to_sq = self._uci_to_squares(move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
            log.info(f"[GameManager] Forced move set: {move}")
    
    def clear_forced_move(self):
        """Clear any pending forced move."""
        self._forced_move = None
        self._forced_move_active = False
        board.ledsOff()
    
    def start(self):
        """Start the game manager and subscribe to board events."""
        if self._running:
            log.warning("[GameManager] Already running")
            return
        
        self._kill = False
        self._running = True
        
        log.info("[GameManager] Starting game manager")
        
        # Subscribe to board events
        try:
            board.subscribeEvents(self._key_callback, self._field_callback)
        except Exception as e:
            log.error(f"[GameManager] Error subscribing to board events: {e}")
            self._running = False
            return
        
        # Start event monitoring thread
        self._event_thread = threading.Thread(target=self._event_thread_func, daemon=True)
        self._event_thread.start()
        
        log.info("[GameManager] Game manager started")
    
    def stop(self):
        """Stop the game manager and clean up."""
        log.info("[GameManager] Stopping game manager")
        self._kill = True
        self._running = False
        
        board.ledsOff()
        
        # Wait for thread to finish
        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=1.0)
        
        log.info("[GameManager] Game manager stopped")

