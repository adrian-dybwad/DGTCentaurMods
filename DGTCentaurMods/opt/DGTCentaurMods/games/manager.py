"""
Chess game manager with event-driven architecture.

Provides complete chess game state management, automatic turn tracking,
event-driven notifications, hardware abstraction, and misplaced piece guidance.
"""

import chess
import threading
import time
import inspect
import sys
from typing import Callable, Optional, List, Set
from scipy.optimize import linear_sum_assignment
import numpy as np

from DGTCentaurMods.board import board
from DGTCentaurMods.db import models
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func

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

# Starting position: pieces on ranks 1, 2, 7, 8 (squares 0-15 and 48-63)
STARTING_STATE = bytearray(
    b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
)


class GameManager:
    """
    Manages chess game state with event-driven notifications.
    
    Features:
    - Complete chess game state management
    - Automatic turn tracking
    - Event-driven notifications to subscribers
    - Hardware abstraction via board.py
    - Misplaced piece guidance
    - Opponent move guidance even with misplaced pieces
    - Starting position detection for new game
    """
    
    def __init__(self):
        self._board = chess.Board()
        self._kill = False
        self._event_callbacks: List[Callable] = []
        self._move_callbacks: List[Callable] = []
        self._key_callbacks: List[Callable] = []
        self._takeback_callbacks: List[Callable] = []
        
        # Move state
        self._source_square: Optional[int] = None
        self._legal_squares: Set[int] = set()
        self._opponent_source_square: Optional[int] = None
        
        # Forced move state
        self._forced_move: Optional[str] = None
        self._forced_move_active = False
        
        # Correction mode
        self._correction_mode = False
        self._correction_expected_state: Optional[bytearray] = None
        
        # Board state history
        self._board_states: List[bytearray] = []
        
        # Game info
        self._game_info = {
            'event': '',
            'site': '',
            'round': '',
            'white': '',
            'black': '',
            'source': ''
        }
        
        # Database
        self._session: Optional[sessionmaker] = None
        self._game_db_id: Optional[int] = None
        
        # Threading
        self._game_thread: Optional[threading.Thread] = None
        
    def subscribe(self, 
                  event_callback: Optional[Callable] = None,
                  move_callback: Optional[Callable] = None,
                  key_callback: Optional[Callable] = None,
                  takeback_callback: Optional[Callable] = None):
        """
        Subscribe to game events.
        
        Args:
            event_callback: Called with event constants (EVENT_NEW_GAME, etc.)
            move_callback: Called with UCI move string when move is made
            key_callback: Called with key press events
            takeback_callback: Called when a takeback is detected
        """
        if event_callback:
            self._event_callbacks.append(event_callback)
        if move_callback:
            self._move_callbacks.append(move_callback)
        if key_callback:
            self._key_callbacks.append(key_callback)
        if takeback_callback:
            self._takeback_callbacks.append(takeback_callback)
        
        # Initialize database session
        self._game_info['source'] = inspect.getsourcefile(sys._getframe(1)) or 'unknown'
        Session = sessionmaker(bind=models.engine)
        self._session = Session()
        
        # Check for starting position on startup
        current_state = self._get_board_state()
        if self._is_starting_position(current_state):
            log.info("[GameManager] Starting position detected on startup - starting new game")
            # Start new game immediately
            self._start_new_game()
        else:
            log.info("[GameManager] Board not in starting position on startup - waiting for pieces to be placed")
            # Don't collect board state yet - wait for starting position
            self._board_states = []
        
        # Start game thread
        self._kill = False
        self._game_thread = threading.Thread(target=self._game_thread_func, daemon=True)
        self._game_thread.start()
        
    def unsubscribe(self):
        """Stop the game manager and clean up resources."""
        self._kill = True
        board.ledsOff()
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        
    def set_game_info(self, event: str = '', site: str = '', round: str = '',
                     white: str = '', black: str = ''):
        """Set game metadata for database logging."""
        self._game_info['event'] = event
        self._game_info['site'] = site
        self._game_info['round'] = round
        self._game_info['white'] = white
        self._game_info['black'] = black
        
    def set_forced_move(self, uci_move: str):
        """
        Set a forced move that the player must make.
        
        Args:
            uci_move: UCI move string (e.g., "e2e4")
        """
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return
        
        self._forced_move = uci_move
        self._forced_move_active = True
        
        from_sq, to_sq = self._uci_to_squares(uci_move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
            log.info(f"[GameManager] Forced move set: {uci_move}")
    
    def clear_forced_move(self):
        """Clear any active forced move."""
        self._forced_move = None
        self._forced_move_active = False
        board.ledsOff()
        
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self._board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self._board.fen()
    
    def _game_thread_func(self):
        """Main game thread that subscribes to board events."""
        log.info("[GameManager] Starting game thread")
        try:
            board.subscribeEvents(self._key_callback, self._field_callback)
        except Exception as e:
            log.error(f"[GameManager] Error subscribing to events: {e}")
            return
        
        while not self._kill:
            time.sleep(0.1)
    
    def _key_callback(self, key):
        """Handle key press events."""
        for callback in self._key_callbacks:
            try:
                callback(key)
            except Exception as e:
                log.error(f"[GameManager] Key callback error: {e}")
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """
        Handle piece lift/place events.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63, a1=0, h8=63)
            time_in_seconds: Timestamp of event
        """
        if self._kill:
            return
        
        lift = (piece_event == 0)
        place = (piece_event == 1)
        
        field_name = chess.square_name(field)
        piece_color = self._board.color_at(field)
        current_turn = self._board.turn
        
        # Check if piece belongs to current player
        is_current_player_piece = (current_turn == chess.WHITE) == (piece_color == True)
        
        log.info(f"[GameManager] field_callback: event={'LIFT' if lift else 'PLACE'} "
                f"field={field}({field_name}) turn={'White' if current_turn else 'Black'} "
                f"piece={'White' if piece_color else 'Black' if piece_color is not None else 'None'}")
        
        # Check for starting position on any place event (during active game or correction mode)
        if place:
            current_state = self._get_board_state()
            if self._is_starting_position(current_state):
                if len(self._board_states) > 0:
                    log.info("[GameManager] Starting position detected during game - starting new game")
                    self._exit_correction_mode()
                    self._start_new_game()
                    return
                elif not self._board_states:
                    # Starting position on first place - start new game
                    log.info("[GameManager] Starting position detected on first place - starting new game")
                    self._start_new_game()
                    return
        
        # Handle lift events - ANY piece can be lifted first
        # Opponent pieces can be lifted even in correction mode
        if lift:
            # If opponent piece lifted, allow it even in correction mode
            if not is_current_player_piece:
                self._opponent_source_square = field
                board.led(self._opponent_source_square, intensity=3)
                # Don't block opponent moves in correction mode - allow them to proceed
                if self._correction_mode:
                    return
            
            # Current player piece lift
            if is_current_player_piece:
                # Current player lifting their piece
                if self._forced_move_active and self._forced_move:
                    # Check if correct piece for forced move
                    forced_source = chess.parse_square(self._forced_move[0:2])
                    if field == forced_source:
                        # Correct piece - limit legal squares to target
                        forced_target = chess.parse_square(self._forced_move[2:4])
                        self._legal_squares = {forced_target}
                        self._source_square = field
                    else:
                        # Wrong piece - can only put it back
                        self._legal_squares = {field}
                        self._source_square = field
                else:
                    # Normal move - calculate legal squares
                    self._legal_squares = self._calculate_legal_squares(field)
                    self._source_square = field
        
        # Handle correction mode (only blocks current player moves, opponent moves handled above)
        if self._correction_mode:
            self._handle_correction_mode(lift, place, field)
            return
        
        # Handle place events
        if place:
            # Check if opponent piece returned to original square
            if (self._opponent_source_square is not None and 
                field == self._opponent_source_square and 
                not is_current_player_piece):
                board.ledsOff()
                self._opponent_source_square = None
                return
            
            # Check if piece placed on legal square
            if self._source_square is not None and field in self._legal_squares:
                if field == self._source_square:
                    # Piece returned to original square
                    self._reset_move_state()
                else:
                    # Valid move - execute it
                    self._execute_move(field)
            else:
                # Illegal placement
                board.beep(board.SOUND_WRONG_MOVE)
                log.warning(f"[GameManager] Illegal placement: field={field}, legal={self._legal_squares}")
                
                # Check for takeback
                if self._check_takeback():
                    return
                
                # Enter correction mode
                self._enter_correction_mode()
    
    def _execute_move(self, target_square: int):
        """Execute a move from source_square to target_square."""
        if self._source_square is None:
            return
        
        from_name = chess.square_name(self._source_square)
        to_name = chess.square_name(target_square)
        piece = self._board.piece_at(self._source_square)
        piece_name = str(piece) if piece else ""
        
        # Handle promotion
        promotion_suffix = ""
        if piece:
            is_white_pawn = (target_square // BOARD_WIDTH == PROMOTION_ROW_WHITE and 
                           piece_name == "P")
            is_black_pawn = (target_square // BOARD_WIDTH == PROMOTION_ROW_BLACK and 
                           piece_name == "p")
            if is_white_pawn or is_black_pawn:
                promotion_suffix = self._handle_promotion(target_square, piece_name)
        
        # Build move string
        if self._forced_move_active and self._forced_move:
            move_str = self._forced_move
        else:
            move_str = from_name + to_name + promotion_suffix
        
        # Make the move
        try:
            move = chess.Move.from_uci(move_str)
            self._board.push(move)
            paths.write_fen_log(self._board.fen())
            
            # Log to database
            if self._session and self._game_db_id:
                gamemove = models.GameMove(
                    gameid=self._game_db_id,
                    move=move_str,
                    fen=str(self._board.fen())
                )
                self._session.add(gamemove)
                self._session.commit()
            
            # Collect board state
            self._board_states.append(bytearray(self._get_board_state()))
            
            # Notify callbacks
            for callback in self._move_callbacks:
                try:
                    callback(move_str)
                except Exception as e:
                    log.error(f"[GameManager] Move callback error: {e}")
            
            board.beep(board.SOUND_GENERAL)
            board.led(target_square)
            
            # Check game outcome
            outcome = self._board.outcome(claim_draw=True)
            if outcome is None:
                # Game continues - switch turn
                self._notify_turn_event()
            else:
                # Game over
                board.beep(board.SOUND_GENERAL)
                result_str = str(self._board.result())
                termination = str(outcome.termination)
                self._update_game_result(result_str, termination)
            
            self._reset_move_state()
            
        except Exception as e:
            log.error(f"[GameManager] Error executing move {move_str}: {e}")
            import traceback
            traceback.print_exc()
            self._reset_move_state()
    
    def _handle_promotion(self, target_square: int, piece_name: str) -> str:
        """Handle pawn promotion by prompting user."""
        board.beep(board.SOUND_GENERAL)
        
        # For now, default to queen
        # In a full implementation, this would show a menu and wait for user input
        # Using the same approach as original: wait for key press
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
    
    def _calculate_legal_squares(self, source_square: int) -> Set[int]:
        """Calculate legal destination squares for a piece."""
        legal_squares = {source_square}  # Include source for return
        
        for move in self._board.legal_moves:
            if move.from_square == source_square:
                legal_squares.add(move.to_square)
        
        return legal_squares
    
    def _reset_move_state(self):
        """Reset move-related state."""
        self._source_square = None
        self._legal_squares = set()
        self._opponent_source_square = None
        self._forced_move_active = False
        board.ledsOff()
    
    def _check_takeback(self) -> bool:
        """Check if board state matches previous move (takeback detected)."""
        if len(self._board_states) < 2:
            return False
        
        current_state = bytearray(self._get_board_state())
        previous_state = self._board_states[-2]
        
        if current_state == previous_state:
            log.info("[GameManager] Takeback detected")
            board.ledsOff()
            
            # Remove last move from history
            self._board_states.pop()
            
            # Remove from database
            if self._session and self._game_db_id:
                last_move = self._session.query(models.GameMove).filter(
                    models.GameMove.gameid == self._game_db_id
                ).order_by(models.GameMove.id.desc()).first()
                if last_move:
                    self._session.delete(last_move)
                    self._session.commit()
            
            # Pop move from board
            self._board.pop()
            paths.write_fen_log(self._board.fen())
            
            board.beep(board.SOUND_GENERAL)
            
            # Notify takeback callbacks
            for callback in self._takeback_callbacks:
                try:
                    callback()
                except Exception as e:
                    log.error(f"[GameManager] Takeback callback error: {e}")
            
            # Verify board state after takeback
            time.sleep(0.2)
            current = bytearray(self._get_board_state())
            if current != (self._board_states[-1] if self._board_states else None):
                log.warning("[GameManager] Board state incorrect after takeback")
                self._enter_correction_mode()
            
            return True
        
        return False
    
    def _enter_correction_mode(self):
        """Enter correction mode to guide user in fixing misplaced pieces."""
        self._correction_mode = True
        self._correction_expected_state = (
            self._board_states[-1] if self._board_states else None
        )
        log.warning("[GameManager] Entered correction mode")
        self._provide_correction_guidance()
    
    def _exit_correction_mode(self):
        """Exit correction mode."""
        self._correction_mode = False
        self._correction_expected_state = None
        log.info("[GameManager] Exited correction mode")
        
        # Restore forced move LEDs if active
        if self._forced_move and len(self._forced_move) >= MIN_UCI_MOVE_LENGTH:
            from_sq, to_sq = self._uci_to_squares(self._forced_move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
    
    def _handle_correction_mode(self, lift: bool, place: bool, field: int):
        """Handle events while in correction mode."""
        current_state = bytearray(self._get_board_state())
        
        # Check for starting position
        if self._is_starting_position(current_state):
            log.info("[GameManager] Starting position detected in correction mode")
            board.ledsOff()
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            self._start_new_game()
            return
        
        # Check if board is now correct
        if (self._correction_expected_state and 
            current_state == self._correction_expected_state):
            log.info("[GameManager] Board corrected")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            return
        
        # Still incorrect - update guidance
        self._provide_correction_guidance()
    
    def _provide_correction_guidance(self):
        """Provide LED guidance to correct misplaced pieces."""
        if not self._correction_expected_state:
            return
        
        current_state = bytearray(self._get_board_state())
        
        # Find misplaced pieces
        missing_squares = []
        wrong_squares = []
        
        for i in range(BOARD_SIZE):
            if self._correction_expected_state[i] == 1 and current_state[i] == 0:
                missing_squares.append(i)
            elif self._correction_expected_state[i] == 0 and current_state[i] == 1:
                wrong_squares.append(i)
        
        if not missing_squares and not wrong_squares:
            board.ledsOff()
            return
        
        # Guide one piece at a time using Hungarian algorithm
        if wrong_squares and missing_squares:
            if len(wrong_squares) == 1 and len(missing_squares) == 1:
                from_sq = wrong_squares[0]
                to_sq = missing_squares[0]
            else:
                # Use Hungarian algorithm for optimal pairing
                costs = np.zeros((len(wrong_squares), len(missing_squares)))
                for i, wl in enumerate(wrong_squares):
                    for j, mo in enumerate(missing_squares):
                        costs[i, j] = self._manhattan_distance(wl, mo)
                
                row_ind, col_ind = linear_sum_assignment(costs)
                from_sq = wrong_squares[row_ind[0]]
                to_sq = missing_squares[col_ind[0]]
            
            board.ledsOff()
            board.ledFromTo(from_sq, to_sq, intensity=5)
        elif missing_squares:
            board.ledsOff()
            for sq in missing_squares:
                board.led(sq, intensity=5)
        elif wrong_squares:
            board.ledsOff()
            for sq in wrong_squares:
                board.led(sq, intensity=5)
    
    def _manhattan_distance(self, sq1: int, sq2: int) -> float:
        """Calculate Manhattan distance between two squares."""
        r1, c1 = sq1 // BOARD_WIDTH, sq1 % BOARD_WIDTH
        r2, c2 = sq2 // BOARD_WIDTH, sq2 % BOARD_WIDTH
        return abs(r1 - r2) + abs(c1 - c2)
    
    def _is_starting_position(self, state: bytearray) -> bool:
        """Check if board state matches starting position."""
        return bytearray(state) == STARTING_STATE
    
    def _get_board_state(self) -> bytearray:
        """Get current board state from hardware."""
        return bytearray(board.getChessState())
    
    def _start_new_game(self):
        """Start a new game."""
        log.info("[GameManager] Starting new game")
        
        self._reset_move_state()
        self._board.reset()
        paths.write_fen_log(self._board.fen())
        
        board.beep(board.SOUND_GENERAL)
        time.sleep(0.3)
        board.beep(board.SOUND_GENERAL)
        board.ledsOff()
        
        # Notify event callbacks
        for callback in self._event_callbacks:
            try:
                callback(EVENT_NEW_GAME)
            except Exception as e:
                log.error(f"[GameManager] Event callback error: {e}")
        
        # Log new game to database
        if self._session:
            game = models.Game(
                source=self._game_info['source'],
                event=self._game_info['event'],
                site=self._game_info['site'],
                round=self._game_info['round'],
                white=self._game_info['white'],
                black=self._game_info['black']
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
        
        self._board_states = []
        self._board_states.append(bytearray(self._get_board_state()))
        
        # Notify white turn
        self._notify_turn_event()
    
    def _notify_turn_event(self):
        """Notify subscribers of turn change."""
        event = EVENT_WHITE_TURN if self._board.turn == chess.WHITE else EVENT_BLACK_TURN
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as e:
                log.error(f"[GameManager] Event callback error: {e}")
    
    def _update_game_result(self, result_str: str, termination: str):
        """Update game result in database and notify subscribers."""
        if self._session and self._game_db_id:
            game = self._session.query(models.Game).filter(
                models.Game.id == self._game_db_id
            ).first()
            if game:
                game.result = result_str
                self._session.commit()
        
        # Notify subscribers
        for callback in self._event_callbacks:
            try:
                callback(termination)
            except Exception as e:
                log.error(f"[GameManager] Event callback error: {e}")
    
    def _uci_to_squares(self, uci_move: str) -> tuple[Optional[int], Optional[int]]:
        """Convert UCI move string to square indices."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return None, None
        
        from_num = ((ord(uci_move[1:2]) - ord("1")) * BOARD_WIDTH) + (
            ord(uci_move[0:1]) - ord("a")
        )
        to_num = ((ord(uci_move[3:4]) - ord("1")) * BOARD_WIDTH) + (
            ord(uci_move[2:3]) - ord("a")
        )
        return from_num, to_num


# Global instance for backward compatibility (if needed)
_manager_instance: Optional[GameManager] = None


def get_manager() -> GameManager:
    """Get or create the global game manager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = GameManager()
    return _manager_instance

