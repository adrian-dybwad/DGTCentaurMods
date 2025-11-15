"""
Chess game manager with event-driven architecture.

Manages complete chess game state, turn tracking, and provides guidance
for misplaced pieces and opponent moves.
"""

from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.config import paths
from DGTCentaurMods.db import models
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
import chess
import threading
import time
import numpy as np
from scipy.optimize import linear_sum_assignment
from typing import Callable, Optional, List, Set, Any
from enum import IntEnum


# Event constants
class GameEvent(IntEnum):
    """Game event types."""
    NEW_GAME = 1
    BLACK_TURN = 2
    WHITE_TURN = 3
    REQUEST_DRAW = 4
    RESIGN_GAME = 5
    MOVE_MADE = 6
    GAME_OVER = 7
    TAKEBACK = 8


# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
STARTING_STATE = bytearray(
    b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
)


class GameManager:
    """
    Event-driven chess game manager.
    
    Manages game state, turn tracking, and provides guidance for misplaced pieces.
    Subscribes to board events and notifies subscribers of game events.
    """
    
    def __init__(self):
        """Initialize the game manager."""
        self._board = chess.Board()
        self._kill = False
        self._event_subscribers: List[Callable] = []
        self._move_subscribers: List[Callable] = []
        self._key_subscribers: List[Callable] = []
        
        # Move tracking state
        self._source_square: Optional[int] = None
        self._legal_squares: Set[int] = set()
        self._opponent_source_square: Optional[int] = None
        
        # Forced move state (computer move)
        self._forced_move: Optional[str] = None
        self._is_forced_move = False
        
        # Correction mode state
        self._correction_mode = False
        self._expected_state: Optional[bytearray] = None
        self._board_states: List[bytearray] = []
        
        # Game info
        self._game_info = {
            'event': '',
            'site': '',
            'round': '',
            'white': '',
            'black': ''
        }
        self._game_db_id: Optional[int] = None
        self._session: Optional[Any] = None
        
        # Threading
        self._game_thread: Optional[threading.Thread] = None
        
    def subscribe_event(self, callback: Callable[[GameEvent], None]):
        """Subscribe to game events."""
        if callback not in self._event_subscribers:
            self._event_subscribers.append(callback)
    
    def subscribe_move(self, callback: Callable[[str], None]):
        """Subscribe to move events."""
        if callback not in self._move_subscribers:
            self._move_subscribers.append(callback)
    
    def subscribe_key(self, callback: Callable[[board.Key], None]):
        """Subscribe to key press events."""
        if callback not in self._key_subscribers:
            self._key_subscribers.append(callback)
    
    def _notify_event(self, event: GameEvent):
        """Notify all event subscribers."""
        for callback in self._event_subscribers:
            try:
                callback(event)
            except Exception as e:
                log.error(f"[GameManager] Error in event callback: {e}")
    
    def _notify_move(self, move: str):
        """Notify all move subscribers."""
        for callback in self._move_subscribers:
            try:
                callback(move)
            except Exception as e:
                log.error(f"[GameManager] Error in move callback: {e}")
    
    def _notify_key(self, key: board.Key):
        """Notify all key subscribers."""
        for callback in self._key_subscribers:
            try:
                callback(key)
            except Exception as e:
                log.error(f"[GameManager] Error in key callback: {e}")
    
    def set_game_info(self, event: str = '', site: str = '', round: str = '',
                     white: str = '', black: str = ''):
        """Set game metadata."""
        self._game_info = {
            'event': event,
            'site': site,
            'round': round,
            'white': white,
            'black': black
        }
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self._board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self._board.fen()
    
    def _is_starting_position(self, state: Optional[bytearray] = None) -> bool:
        """Check if board is in starting position."""
        if state is None:
            state = bytearray(board.getChessState())
        return bytearray(state) == STARTING_STATE
    
    def _validate_board_state(self, current: bytearray, expected: bytearray) -> bool:
        """Validate board state matches expected state."""
        if current is None or expected is None:
            return False
        if len(current) != BOARD_SIZE or len(expected) != BOARD_SIZE:
            return False
        return bytearray(current) == bytearray(expected)
    
    def _collect_board_state(self):
        """Collect and store current board state."""
        state = bytearray(board.getChessState())
        self._board_states.append(state)
        log.debug(f"[GameManager] Collected board state, total states: {len(self._board_states)}")
    
    def _check_takeback(self) -> bool:
        """Check if a takeback occurred by comparing current state to previous state."""
        if len(self._board_states) < 2:
            return False
        
        current_state = bytearray(board.getChessState())
        previous_state = self._board_states[-2]
        
        if self._validate_board_state(current_state, previous_state):
            log.info("[GameManager] Takeback detected")
            board.ledsOff()
            self._board_states.pop()
            
            # Remove last move from database
            if self._session and self._game_db_id:
                try:
                    last_move = self._session.query(models.GameMove).filter(
                        models.GameMove.gameid == self._game_db_id
                    ).order_by(models.GameMove.id.desc()).first()
                    if last_move:
                        self._session.delete(last_move)
                        self._session.commit()
                except Exception as e:
                    log.error(f"[GameManager] Error removing takeback move: {e}")
            
            # Pop move from board
            if len(self._board.move_stack) > 0:
                self._board.pop()
                paths.write_fen_log(self._board.fen())
            
            board.beep(board.SOUND_GENERAL)
            self._notify_event(GameEvent.TAKEBACK)
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            current = bytearray(board.getChessState())
            expected = self._board_states[-1] if self._board_states else None
            if not self._validate_board_state(current, expected):
                log.warning("[GameManager] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            return True
        return False
    
    def _calculate_legal_squares(self, square: int) -> Set[int]:
        """Calculate legal destination squares for a piece."""
        legal_squares = {square}  # Include source square
        for move in self._board.legal_moves:
            if move.from_square == square:
                legal_squares.add(move.to_square)
        return legal_squares
    
    def _provide_correction_guidance(self, current_state: bytearray, expected_state: bytearray):
        """
        Provide LED guidance to correct misplaced pieces using Hungarian algorithm.
        
        Computes optimal pairing between misplaced pieces for minimal movement distance.
        """
        if current_state is None or expected_state is None:
            return
        
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return
        
        def _row_col(idx: int) -> tuple[int, int]:
            """Convert square index to (row, col)."""
            return (idx // BOARD_WIDTH), (idx % BOARD_WIDTH)
        
        def _distance(a: int, b: int) -> int:
            """Manhattan distance between two squares."""
            ar, ac = _row_col(a)
            br, bc = _row_col(b)
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
            board.ledsOff()
            return
        
        log.warning(f"[GameManager] Found {len(wrong_locations)} wrong pieces, {len(missing_origins)} missing pieces")
        
        # Guide one piece at a time
        if len(wrong_locations) > 0 and len(missing_origins) > 0:
            if len(wrong_locations) == 1 and len(missing_origins) == 1:
                from_idx = wrong_locations[0]
                to_idx = missing_origins[0]
            else:
                # Use Hungarian algorithm for optimal pairing
                costs = np.zeros((len(wrong_locations), len(missing_origins)))
                for i, wl in enumerate(wrong_locations):
                    for j, mo in enumerate(missing_origins):
                        costs[i, j] = _distance(wl, mo)
                
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
        self._expected_state = self._board_states[-1] if self._board_states else None
        log.warning(f"[GameManager] Entered correction mode (forced_move={self._is_forced_move}, move={self._forced_move})")
    
    def _exit_correction_mode(self):
        """Exit correction mode and resume normal game flow."""
        self._correction_mode = False
        expected = self._expected_state
        self._expected_state = None
        log.info("[GameManager] Exited correction mode")
        
        # Reset move state variables
        self._source_square = None
        self._legal_squares = set()
        self._opponent_source_square = None
        
        # Restore forced move LEDs if pending
        if self._is_forced_move and self._forced_move and len(self._forced_move) >= 4:
            from_sq, to_sq = self._uci_to_squares(self._forced_move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
                log.info(f"[GameManager] Restored forced move LEDs: {self._forced_move}")
    
    def _uci_to_squares(self, uci_move: str) -> tuple[Optional[int], Optional[int]]:
        """Convert UCI move string to square indices."""
        if len(uci_move) < 4:
            return None, None
        from_num = ((ord(uci_move[1]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[0]) - ord("a"))
        to_num = ((ord(uci_move[3]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[2]) - ord("a"))
        return from_num, to_num
    
    def _handle_promotion(self, target_square: int, piece_name: str, is_forced: bool) -> str:
        """
        Handle pawn promotion.
        
        Returns:
            Promotion piece suffix ("q", "r", "b", "n") or empty string.
        """
        is_white_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
        is_black_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        if not is_forced:
            # Wait for user to select promotion piece
            key = board.wait_for_key_up(timeout=60)
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
        return ""
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """
        Handle field events from board.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63)
            time_in_seconds: Time of the event
        """
        if self._correction_mode:
            self._correction_field_callback(piece_event, field, time_in_seconds)
            return
        
        lift = (piece_event == 0)
        place = (piece_event == 1)
        
        field_name = chess.square_name(field)
        piece_color = self._board.color_at(field)
        
        log.info(f"[GameManager] piece_event={'LIFT' if lift else 'PLACE'} field={field} fieldname={field_name} "
                f"color={'White' if piece_color else 'Black'}")
        
        # Check if piece belongs to current player
        is_current_player_piece = (self._board.turn == chess.WHITE) == (piece_color == True)
        
        # Handle lift events
        if lift:
            if is_current_player_piece:
                if field not in self._legal_squares and self._source_square is None:
                    # Start tracking a move
                    self._legal_squares = self._calculate_legal_squares(field)
                    self._source_square = field
                    log.info(f"[GameManager] Started move from {field_name}, legal squares: {[chess.square_name(sq) for sq in self._legal_squares]}")
            else:
                # Opponent piece lifted
                self._opponent_source_square = field
                log.info(f"[GameManager] Opponent piece lifted from {field_name}")
        
        # Handle forced move
        if self._is_forced_move and lift and is_current_player_piece:
            if self._forced_move and len(self._forced_move) >= 4:
                expected_source = chess.parse_square(self._forced_move[0:2])
                if field != expected_source:
                    # Wrong piece lifted for forced move
                    self._legal_squares = {field}  # Only allow putting it back
                else:
                    # Correct piece, limit to target square
                    target = chess.parse_square(self._forced_move[2:4])
                    self._legal_squares = {target}
        
        # Handle opponent piece placement back
        if place and not is_current_player_piece and self._opponent_source_square is not None:
            if field == self._opponent_source_square:
                board.ledsOff()
                self._opponent_source_square = None
                log.info(f"[GameManager] Opponent piece returned to {field_name}")
                return
        
        # Handle place events
        if place:
            if self._source_square is None and self._opponent_source_square is None:
                # Place without corresponding lift - ignore stale events
                log.debug(f"[GameManager] Ignoring stale PLACE event for field {field}")
                return
            
            if field not in self._legal_squares:
                # Illegal placement
                board.beep(board.SOUND_WRONG_MOVE)
                log.warning(f"[GameManager] Piece placed on illegal square {field_name}")
                
                # Check for takeback
                if not self._check_takeback():
                    # Guide misplaced piece
                    self._guide_misplaced_piece(field, is_current_player_piece)
                return
            
            if field == self._source_square:
                # Piece placed back on source square
                board.ledsOff()
                self._source_square = None
                self._legal_squares = set()
                log.info(f"[GameManager] Piece returned to source square")
            else:
                # Valid move
                self._execute_move(field)
    
    def _correction_field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """Handle field events during correction mode."""
        current_state = bytearray(board.getChessState())
        
        # Check if board is in starting position (new game detection)
        if self._is_starting_position(current_state):
            log.info("[GameManager] Starting position detected in correction mode - triggering new game")
            board.ledsOff()
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            self._reset_game()
            return
        
        # Check if board matches expected state
        if self._validate_board_state(current_state, self._expected_state):
            log.info("[GameManager] Board corrected, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            return
        
        # Still incorrect, update guidance
        self._provide_correction_guidance(current_state, self._expected_state)
    
    def _guide_misplaced_piece(self, field: int, is_current_player: bool):
        """Guide user to correct misplaced piece."""
        log.warning(f"[GameManager] Entering correction mode for field {field}")
        self._enter_correction_mode()
        current_state = bytearray(board.getChessState())
        if self._board_states:
            self._provide_correction_guidance(current_state, self._board_states[-1])
    
    def _execute_move(self, target_square: int):
        """Execute a move on the board."""
        if self._source_square is None:
            return
        
        from_name = chess.square_name(self._source_square)
        to_name = chess.square_name(target_square)
        piece_name = str(self._board.piece_at(self._source_square))
        
        # Handle promotion
        promotion_suffix = self._handle_promotion(target_square, piece_name, self._is_forced_move)
        
        # Build move string
        if self._is_forced_move and self._forced_move:
            move_str = self._forced_move
        else:
            move_str = from_name + to_name + promotion_suffix
        
        # Make the move
        try:
            move = chess.Move.from_uci(move_str)
            if move not in self._board.legal_moves:
                log.error(f"[GameManager] Illegal move attempted: {move_str}")
                board.beep(board.SOUND_WRONG_MOVE)
                return
            
            self._board.push(move)
            paths.write_fen_log(self._board.fen())
            
            # Log to database
            if self._session and self._game_db_id:
                try:
                    game_move = models.GameMove(
                        gameid=self._game_db_id,
                        move=move_str,
                        fen=str(self._board.fen())
                    )
                    self._session.add(game_move)
                    self._session.commit()
                except Exception as e:
                    log.error(f"[GameManager] Error logging move to database: {e}")
            
            self._collect_board_state()
            
            # Reset move state
            self._source_square = None
            self._legal_squares = set()
            self._opponent_source_square = None
            self._is_forced_move = False
            self._forced_move = None
            
            # Notify subscribers
            self._notify_move(move_str)
            board.beep(board.SOUND_GENERAL)
            board.led(target_square)
            
            # Check game outcome
            outcome = self._board.outcome(claim_draw=True)
            if outcome is None:
                # Switch turn
                if self._board.turn == chess.WHITE:
                    self._notify_event(GameEvent.WHITE_TURN)
                else:
                    self._notify_event(GameEvent.BLACK_TURN)
            else:
                # Game over
                board.beep(board.SOUND_GENERAL)
                result_str = str(self._board.result())
                termination = str(outcome.termination)
                self._update_game_result(result_str, termination)
                self._notify_event(GameEvent.GAME_OVER)
        
        except Exception as e:
            log.error(f"[GameManager] Error executing move: {e}")
            import traceback
            traceback.print_exc()
    
    def _update_game_result(self, result_str: str, termination: str):
        """Update game result in database."""
        if self._session and self._game_db_id:
            try:
                game = self._session.query(models.Game).filter(models.Game.id == self._game_db_id).first()
                if game:
                    game.result = result_str
                    self._session.commit()
            except Exception as e:
                log.error(f"[GameManager] Error updating game result: {e}")
    
    def _key_callback(self, key: board.Key):
        """Handle key press events."""
        self._notify_key(key)
    
    def _reset_game(self):
        """Reset game to starting position."""
        try:
            log.info("[GameManager] Resetting game to starting position")
            
            # Reset board state
            self._board.reset()
            paths.write_fen_log(self._board.fen())
            
            # Reset move state
            self._source_square = None
            self._legal_squares = set()
            self._opponent_source_square = None
            self._is_forced_move = False
            self._forced_move = None
            
            board.ledsOff()
            board.beep(board.SOUND_GENERAL)
            time.sleep(0.3)
            board.beep(board.SOUND_GENERAL)
            
            # Notify subscribers
            self._notify_event(GameEvent.NEW_GAME)
            self._notify_event(GameEvent.WHITE_TURN)
            
            # Log new game to database
            if self._session:
                try:
                    game = models.Game(
                        source=self._game_info.get('event', ''),
                        event=self._game_info.get('event', ''),
                        site=self._game_info.get('site', ''),
                        round=self._game_info.get('round', ''),
                        white=self._game_info.get('white', ''),
                        black=self._game_info.get('black', '')
                    )
                    self._session.add(game)
                    self._session.commit()
                    self._game_db_id = self._session.query(func.max(models.Game.id)).scalar()
                    
                    # Log starting position
                    gamemove = models.GameMove(
                        gameid=self._game_db_id,
                        move='',
                        fen=str(self._board.fen())
                    )
                    self._session.add(gamemove)
                    self._session.commit()
                except Exception as e:
                    log.error(f"[GameManager] Error logging new game: {e}")
            
            self._board_states = []
            self._collect_board_state()
            
        except Exception as e:
            log.error(f"[GameManager] Error resetting game: {e}")
            import traceback
            traceback.print_exc()
    
    def set_forced_move(self, move: str, forced: bool = True):
        """
        Set a forced move (computer move) that the player must make.
        
        Args:
            move: UCI move string (e.g., "e2e4")
            forced: Whether this is a forced move
        """
        if len(move) < 4:
            return
        
        self._forced_move = move
        self._is_forced_move = forced
        
        # Light up LEDs to indicate the move
        from_sq, to_sq = self._uci_to_squares(move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
            log.info(f"[GameManager] Set forced move: {move}")
    
    def reset_move_state(self):
        """Reset move-related state variables."""
        self._source_square = None
        self._legal_squares = set()
        self._opponent_source_square = None
        self._is_forced_move = False
        self._forced_move = None
        board.ledsOff()
    
    def _game_thread_worker(self):
        """Main game thread that subscribes to board events."""
        board.ledsOff()
        log.info("[GameManager] Subscribing to board events")
        
        try:
            board.subscribeEvents(self._key_callback, self._field_callback)
        except Exception as e:
            log.error(f"[GameManager] Error subscribing to events: {e}")
            return
        
        # Check for starting position
        if self._is_starting_position():
            log.info("[GameManager] Starting position detected, initializing game")
            self._reset_game()
        else:
            # Collect initial board state
            self._collect_board_state()
        
        while not self._kill:
            time.sleep(0.1)
    
    def start(self):
        """Start the game manager."""
        if self._game_thread is not None and self._game_thread.is_alive():
            log.warning("[GameManager] Game thread already running")
            return
        
        # Initialize database session
        try:
            Session = sessionmaker(bind=models.engine)
            self._session = Session()
        except Exception as e:
            log.error(f"[GameManager] Error creating database session: {e}")
            self._session = None
        
        self._kill = False
        self._game_thread = threading.Thread(target=self._game_thread_worker, daemon=True)
        self._game_thread.start()
        log.info("[GameManager] Game manager started")
    
    def stop(self):
        """Stop the game manager."""
        log.info("[GameManager] Stopping game manager")
        self._kill = True
        board.ledsOff()
        
        if self._session:
            try:
                self._session.close()
                self._session = None
            except Exception as e:
                log.error(f"[GameManager] Error closing database session: {e}")
        
        if self._game_thread and self._game_thread.is_alive():
            self._game_thread.join(timeout=2.0)
        
        log.info("[GameManager] Game manager stopped")

