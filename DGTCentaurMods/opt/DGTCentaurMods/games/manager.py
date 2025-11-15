"""
Chess game manager with complete state management, turn tracking, and event-driven notifications.

This module provides a clean, refactored game manager that:
- Manages complete chess game state
- Tracks turns automatically
- Provides event-driven notifications
- Handles misplaced piece guidance
- Supports opponent move guidance even with misplaced pieces
- Detects starting position for new game
- Allows any piece to be lifted first (for taking pieces)
"""

from DGTCentaurMods.board import board
from DGTCentaurMods.db import models
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log
from sqlalchemy.orm import sessionmaker
from scipy.optimize import linear_sum_assignment
import threading
import time
import chess
import sys
import inspect
import numpy as np
from typing import Callable, Optional, List, Set
from enum import Enum

# Event constants
class GameEvent(Enum):
    """Game event types"""
    NEW_GAME = "NEW_GAME"
    WHITE_TURN = "WHITE_TURN"
    BLACK_TURN = "BLACK_TURN"
    MOVE_MADE = "MOVE_MADE"
    GAME_OVER = "GAME_OVER"
    TAKEBACK = "TAKEBACK"
    REQUEST_DRAW = "REQUEST_DRAW"
    RESIGN = "RESIGN"

# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
STARTING_STATE = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')


class GameManager:
    """
    Manages chess game state, turn tracking, and board events.
    
    Provides event-driven notifications to subscribers and handles
    misplaced piece guidance using LED indicators.
    """
    
    def __init__(self):
        """Initialize the game manager"""
        self._board = chess.Board()
        self._kill = False
        self._session: Optional[sessionmaker] = None
        self._game_db_id: Optional[int] = None
        
        # Move state
        self._source_square: Optional[int] = None
        self._other_source_square: Optional[int] = None  # For opponent pieces
        self._legal_squares: Set[int] = set()
        self._forced_move: Optional[str] = None  # UCI move string
        self._is_forced_move = False
        
        # Correction mode state
        self._correction_mode = False
        self._correction_expected_state: Optional[bytearray] = None
        self._correction_just_exited = False
        
        # Board state history
        self._board_states: List[bytearray] = []
        
        # Event subscribers
        self._event_subscribers: List[Callable] = []
        self._move_subscribers: List[Callable] = []
        self._key_subscribers: List[Callable] = []
        self._takeback_subscribers: List[Callable] = []
        
        # Game metadata
        self._game_source = ""
        self._game_event = ""
        self._game_site = ""
        self._game_round = ""
        self._game_white = ""
        self._game_black = ""
        
        # Threading
        self._game_thread: Optional[threading.Thread] = None
        
    def subscribe_events(self, callback: Callable):
        """Subscribe to game events (NEW_GAME, WHITE_TURN, BLACK_TURN, GAME_OVER, etc.)"""
        if callback not in self._event_subscribers:
            self._event_subscribers.append(callback)
    
    def subscribe_moves(self, callback: Callable):
        """Subscribe to move events (receives UCI move string)"""
        if callback not in self._move_subscribers:
            self._move_subscribers.append(callback)
    
    def subscribe_keys(self, callback: Callable):
        """Subscribe to key press events"""
        if callback not in self._key_subscribers:
            self._key_subscribers.append(callback)
    
    def subscribe_takeback(self, callback: Callable):
        """Subscribe to takeback events"""
        if callback not in self._takeback_subscribers:
            self._takeback_subscribers.append(callback)
    
    def _notify_event(self, event: GameEvent, *args):
        """Notify all event subscribers"""
        for callback in self._event_subscribers:
            try:
                callback(event, *args)
            except Exception as e:
                log.error(f"Error in event callback: {e}")
                import traceback
                traceback.print_exc()
    
    def _notify_move(self, move: str):
        """Notify all move subscribers"""
        for callback in self._move_subscribers:
            try:
                callback(move)
            except Exception as e:
                log.error(f"Error in move callback: {e}")
                import traceback
                traceback.print_exc()
    
    def _notify_key(self, key):
        """Notify all key subscribers"""
        for callback in self._key_subscribers:
            try:
                callback(key)
            except Exception as e:
                log.error(f"Error in key callback: {e}")
                import traceback
                traceback.print_exc()
    
    def _notify_takeback(self):
        """Notify all takeback subscribers"""
        for callback in self._takeback_subscribers:
            try:
                callback()
            except Exception as e:
                log.error(f"Error in takeback callback: {e}")
                import traceback
                traceback.print_exc()
    
    def _is_starting_position(self, state: Optional[bytearray] = None) -> bool:
        """Check if board is in starting position"""
        if state is None:
            state = bytearray(board.getChessState())
        return bytearray(state) == STARTING_STATE
    
    def _collect_board_state(self):
        """Collect and store current board state"""
        state = bytearray(board.getChessState())
        self._board_states.append(state)
        log.debug(f"[GameManager] Collected board state: {len(self._board_states)} states")
    
    def _validate_board_state(self, current: bytearray, expected: bytearray) -> bool:
        """Validate board state matches expected"""
        if current is None or expected is None:
            return False
        if len(current) != BOARD_SIZE or len(expected) != BOARD_SIZE:
            return False
        return bytearray(current) == bytearray(expected)
    
    def _calculate_legal_squares(self, square: int) -> Set[int]:
        """Calculate legal destination squares for a piece"""
        legal_squares = {square}  # Include source square
        for move in self._board.legal_moves:
            if move.from_square == square:
                legal_squares.add(move.to_square)
        return legal_squares
    
    def _uci_to_squares(self, uci_move: str) -> tuple[Optional[int], Optional[int]]:
        """Convert UCI move string to square indices"""
        if len(uci_move) < 4:
            return None, None
        from_sq = ((ord(uci_move[1]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[0]) - ord("a"))
        to_sq = ((ord(uci_move[3]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[2]) - ord("a"))
        return from_sq, to_sq
    
    def _provide_correction_guidance(self, current_state: bytearray, expected_state: bytearray):
        """
        Provide LED guidance to correct misplaced pieces using Hungarian algorithm.
        
        Computes optimal pairing between misplaced pieces for minimal movement distance.
        """
        if current_state is None or expected_state is None:
            return
        
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return
        
        def _rc(idx):
            """Convert square index to (row, col)"""
            return (idx // BOARD_WIDTH), (idx % BOARD_WIDTH)
        
        def _dist(a, b):
            """Manhattan distance between two squares"""
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
                n_wrong = len(wrong_locations)
                n_missing = len(missing_origins)
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
        """Enter correction mode to guide user in fixing board state"""
        self._correction_mode = True
        self._correction_expected_state = self._board_states[-1] if self._board_states else None
        self._correction_just_exited = False
        log.warning(f"[GameManager] Entered correction mode")
    
    def _exit_correction_mode(self):
        """Exit correction mode and resume normal game flow"""
        self._correction_mode = False
        self._correction_expected_state = None
        self._correction_just_exited = True
        log.warning("[GameManager] Exited correction mode")
        
        # Reset move state
        self._source_square = None
        self._legal_squares = set()
        self._other_source_square = None
        
        # Restore forced move LEDs if pending
        if self._is_forced_move and self._forced_move and len(self._forced_move) >= 4:
            from_sq, to_sq = self._uci_to_squares(self._forced_move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
                log.info(f"[GameManager] Restored forced move LEDs: {self._forced_move}")
    
    def _handle_promotion(self, field: int, piece_name: str, is_forced: bool) -> str:
        """Handle pawn promotion by prompting user for piece choice"""
        is_white_promotion = (field // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
        is_black_promotion = (field // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        if not is_forced:
            # Wait for user to select promotion piece via button press
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
    
    def _check_takeback(self) -> bool:
        """Check if a takeback is in progress by comparing board states"""
        if len(self._board_states) < 2:
            return False
        
        current_state = bytearray(board.getChessState())
        previous_state = self._board_states[-2]
        
        if bytearray(current_state) == bytearray(previous_state):
            # Takeback detected
            board.ledsOff()
            self._board_states.pop()  # Remove last state
            
            # Remove last move from database
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
            self._notify_takeback()
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            current = bytearray(board.getChessState())
            if not self._validate_board_state(current, self._board_states[-1] if self._board_states else None):
                log.info("[GameManager] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            return True
        return False
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """
        Handle field events (piece lift/place).
        
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
        
        log.info(f"[GameManager] piece_event={'LIFT' if lift else 'PLACE'} field={field} fieldname={field_name} color_at={'White' if piece_color else ('Black' if piece_color is False else 'None')}")
        
        # Check if piece belongs to current player (exactly like original)
        # vpiece = True if piece belongs to current player, False otherwise
        # self._board.turn is chess.WHITE (True) or chess.BLACK (False)
        # piece_color is True for white pieces, False for black pieces, None if no piece
        is_current_player_piece = (self._board.turn == chess.WHITE) == (piece_color == True)
        
        # Handle lift events
        if lift:
            self._correction_just_exited = False  # Clear flag on valid lift
            
            # Process lift if: field not in legal squares, no source square yet, and it's current player's piece
            if field not in self._legal_squares and self._source_square is None and is_current_player_piece:
                # Generate a list of places this piece can move to
                self._legal_squares = self._calculate_legal_squares(field)
                self._source_square = field
                log.info(f"[GameManager] Current player piece lifted at {field}, legal squares: {self._legal_squares}")
            
            # Track opposing side lifts so we can guide returning them if moved
            if not is_current_player_piece:
                self._other_source_square = field
                log.info(f"[GameManager] Opponent piece lifted at {field}")
            
            # Handle forced move logic
            if self._is_forced_move and self._forced_move and is_current_player_piece:
                # If this is a forced move (computer move) then the piece lifted should equal the start of forced_move
                # otherwise set legalsquares so they can just put the piece back down!
                if field_name != self._forced_move[0:2]:
                    # Forced move but wrong piece lifted
                    self._legal_squares = {field}
                else:
                    # Forced move, correct piece lifted, limit legal squares
                    target = self._forced_move[2:4]
                    tsq = chess.parse_square(target)
                    self._legal_squares = {tsq}
        
        # Handle place events
        if place:
            # If opponent piece is placed back on original square, turn LEDs off and reset
            if not is_current_player_piece and self._other_source_square is not None and field == self._other_source_square:
                board.ledsOff()
                self._other_source_square = None
                return
            
            # Ignore PLACE events without a corresponding LIFT (stale events from before reset)
            # This prevents triggering correction mode when a PLACE event arrives after reset
            # but before the piece is lifted again in the new game state
            # Allow opponent piece placement back (othersourcesq >= 0) and forced moves
            if place and self._source_square is None and self._other_source_square is None:
                # After correction mode exits, there may be stale PLACE events from the correction process
                # Ignore them unless it's a forced move source square (which we handle separately)
                if self._correction_just_exited:
                    # Check if this is the forced move source square - if so, we'll handle it below
                    # Otherwise, ignore it as a stale event from correction
                    if self._is_forced_move and self._forced_move and len(self._forced_move) >= 4:
                        forced_source = chess.parse_square(self._forced_move[0:2])
                        if field != forced_source:
                            log.info(f"[GameManager] Ignoring stale PLACE event after correction exit for field {field} (not forced move source)")
                            self._correction_just_exited = False
                            return
                    else:
                        log.info(f"[GameManager] Ignoring stale PLACE event after correction exit for field {field}")
                        self._correction_just_exited = False
                        return
                
                # For forced moves, also ignore stale PLACE events on the source square
                # (the forced move source square) before the LIFT has been processed
                if self._is_forced_move and self._forced_move and len(self._forced_move) >= 4:
                    forced_source = chess.parse_square(self._forced_move[0:2])
                    if field == forced_source:
                        log.info(f"[GameManager] Ignoring stale PLACE event for forced move source field {field} (no corresponding LIFT)")
                        self._correction_just_exited = False
                        return
                if not self._is_forced_move:
                    log.info(f"[GameManager] Ignoring stale PLACE event for field {field} (no corresponding LIFT)")
                    self._correction_just_exited = False
                    return
            
            # Check if move is illegal
            if place and field not in self._legal_squares:
                board.beep(board.SOUND_WRONG_MOVE)
                log.warning(f"[GameManager] Piece placed on illegal square {field}")
                is_takeback = self._check_takeback()
                if not is_takeback:
                    self._enter_correction_mode()
                    current_state = bytearray(board.getChessState())
                    if self._board_states:
                        self._provide_correction_guidance(current_state, self._board_states[-1])
                return
            
            # Legal move
            if place and field in self._legal_squares:
                log.info(f"[GameManager] Making move")
                if field == self._source_square:
                    # Piece has simply been placed back
                    board.ledsOff()
                    self._source_square = None
                    self._legal_squares = set()
                else:
                    # Piece has been moved
                    from_name = chess.square_name(self._source_square)
                    to_name = chess.square_name(field)
                    piece_name = str(self._board.piece_at(self._source_square))
                    promotion_suffix = self._handle_promotion(field, piece_name, self._is_forced_move)
                    
                    if self._is_forced_move:
                        move_uci = self._forced_move
                    else:
                        move_uci = from_name + to_name + promotion_suffix
                    
                    # Make the move and update fen.log
                    move = chess.Move.from_uci(move_uci)
                    self._board.push(move)
                    paths.write_fen_log(self._board.fen())
                    
                    # Log to database
                    if self._session and self._game_db_id:
                        game_move = models.GameMove(
                            gameid=self._game_db_id,
                            move=move_uci,
                            fen=str(self._board.fen())
                        )
                        self._session.add(game_move)
                        self._session.commit()
                    
                    self._collect_board_state()
                    
                    # Reset move state
                    self._source_square = None
                    self._legal_squares = set()
                    self._is_forced_move = False
                    self._forced_move = None
                    
                    # Notify move
                    self._notify_move(move_uci)
                    board.beep(board.SOUND_GENERAL)
                    # Also light up the square moved to
                    board.led(field)
                    
                    # Check the outcome
                    outcome = self._board.outcome(claim_draw=True)
                    if outcome is None:
                        # Switch the turn
                        if self._board.turn == chess.WHITE:
                            self._notify_event(GameEvent.WHITE_TURN)
                        else:
                            self._notify_event(GameEvent.BLACK_TURN)
                    else:
                        board.beep(board.SOUND_GENERAL)
                        # Update game result in database and trigger callback
                        result_str = str(self._board.result())
                        termination = str(outcome.termination)
                        
                        # Update database
                        if self._session and self._game_db_id:
                            game = self._session.query(models.Game).filter(models.Game.id == self._game_db_id).first()
                            if game:
                                game.result = result_str
                                self._session.commit()
                        
                        self._notify_event(GameEvent.GAME_OVER, result_str, termination)
    
    def _correction_field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """Handle field events during correction mode"""
        current_state = bytearray(board.getChessState())
        
        # Check if board is in starting position (new game detection)
        if self._is_starting_position(current_state):
            log.info("[GameManager] Starting position detected while in correction mode - exiting correction and triggering new game")
            board.ledsOff()
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            self._reset_game()
            return
        
        # Check if board matches expected state
        if self._validate_board_state(current_state, self._correction_expected_state):
            log.info("[GameManager] Board corrected, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            return
        
        # Still incorrect - update guidance
        self._provide_correction_guidance(current_state, self._correction_expected_state)
    
    def _key_callback(self, key_pressed):
        """Handle key press events"""
        self._notify_key(key_pressed)
    
    def _reset_game(self):
        """Reset game to starting position"""
        log.info("[GameManager] Resetting game to starting position")
        
        # Reset board
        self._board.reset()
        paths.write_fen_log(self._board.fen())
        
        # Reset state
        self._source_square = None
        self._legal_squares = set()
        self._other_source_square = None
        self._is_forced_move = False
        self._forced_move = None
        self._board_states = []
        self._collect_board_state()
        
        # Double beep for new game
        board.beep(board.SOUND_GENERAL)
        time.sleep(0.3)
        board.beep(board.SOUND_GENERAL)
        board.ledsOff()
        
        # Create new game in database
        if self._session:
            game = models.Game(
                source=self._game_source,
                event=self._game_event,
                site=self._game_site,
                round=self._game_round,
                white=self._game_white,
                black=self._game_black
            )
            self._session.add(game)
            self._session.commit()
            self._game_db_id = self._session.query(models.Game.id).order_by(models.Game.id.desc()).first()[0]
            
            # Log starting position
            game_move = models.GameMove(
                gameid=self._game_db_id,
                move='',
                fen=str(self._board.fen())
            )
            self._session.add(game_move)
            self._session.commit()
        
        # Notify new game
        self._notify_event(GameEvent.NEW_GAME)
        self._notify_event(GameEvent.WHITE_TURN)
    
    def _game_thread(self):
        """Main game thread that subscribes to board events"""
        board.ledsOff()
        log.info("[GameManager] Subscribing to board events")
        
        # Always collect initial board state (like original gamemanager)
        # This ensures we have a baseline for move detection
        self._collect_board_state()
        log.info("[GameManager] Collected initial board state")
        
        try:
            board.subscribeEvents(self._key_callback, self._field_callback)
        except Exception as e:
            log.error(f"[GameManager] Error subscribing to events: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # Check for starting position on startup
        time.sleep(0.5)  # Give board time to initialize
        if self._is_starting_position():
            log.info("[GameManager] Starting position detected on startup - starting new game")
            self._reset_game()
        else:
            # Board not in starting position - still need to initialize game if not already done
            # This handles the case where board is already set up from a previous session
            if self._game_db_id is None:
                log.info("[GameManager] Board not in starting position, but initializing game state")
                # Create game entry even if not starting position
                if self._session:
                    game = models.Game(
                        source=self._game_source,
                        event=self._game_event,
                        site=self._game_site,
                        round=self._game_round,
                        white=self._game_white,
                        black=self._game_black
                    )
                    self._session.add(game)
                    self._session.commit()
                    self._game_db_id = self._session.query(models.Game.id).order_by(models.Game.id.desc()).first()[0]
                    
                    # Log current position
                    game_move = models.GameMove(
                        gameid=self._game_db_id,
                        move='',
                        fen=str(self._board.fen())
                    )
                    self._session.add(game_move)
                    self._session.commit()
                
                # Notify that game is active (even if not starting position)
                self._notify_event(GameEvent.NEW_GAME)
                if self._board.turn == chess.WHITE:
                    self._notify_event(GameEvent.WHITE_TURN)
                else:
                    self._notify_event(GameEvent.BLACK_TURN)
        
        last_state_check = time.time()
        while not self._kill:
            time.sleep(0.1)
            
            # Check for starting position during active game (throttled to avoid excessive checks)
            if time.time() - last_state_check > 0.5:  # Check every 0.5 seconds
                last_state_check = time.time()
                if not self._correction_mode and len(self._board_states) > 0:
                    if self._is_starting_position():
                        log.info("[GameManager] Starting position detected during game - starting new game")
                        self._reset_game()
    
    def set_game_info(self, event: str = "", site: str = "", round: str = "", white: str = "", black: str = ""):
        """Set game metadata"""
        self._game_event = event
        self._game_site = site
        self._game_round = round
        self._game_white = white
        self._game_black = black
    
    def set_forced_move(self, uci_move: str, forced: bool = True):
        """
        Set a forced move that the player must make.
        
        Args:
            uci_move: UCI move string (e.g., "e2e4")
            forced: Whether this is a forced move
        """
        if len(uci_move) < 4:
            return
        
        self._forced_move = uci_move
        self._is_forced_move = forced
        
        # Light up LEDs
        from_sq, to_sq = self._uci_to_squares(uci_move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
            log.info(f"[GameManager] Set forced move: {uci_move}")
    
    def clear_forced_move(self):
        """Clear forced move state"""
        self._forced_move = None
        self._is_forced_move = False
        board.ledsOff()
    
    def get_board(self) -> chess.Board:
        """Get the current chess board"""
        return self._board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string"""
        return self._board.fen()
    
    def start(self):
        """Start the game manager"""
        if self._game_thread is not None and self._game_thread.is_alive():
            log.warning("[GameManager] Already started")
            return
        
        # Initialize database session
        source = inspect.getsourcefile(sys._getframe(1))
        self._game_source = source if source else "games.manager"
        Session = sessionmaker(bind=models.engine)
        self._session = Session()
        
        # Start game thread
        self._kill = False
        self._game_thread = threading.Thread(target=self._game_thread, daemon=True)
        self._game_thread.start()
        log.info("[GameManager] Started")
    
    def stop(self):
        """Stop the game manager"""
        log.info("[GameManager] Stopping")
        self._kill = True
        board.ledsOff()
        
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        
        if self._game_thread and self._game_thread.is_alive():
            self._game_thread.join(timeout=2.0)
        
        log.info("[GameManager] Stopped")

