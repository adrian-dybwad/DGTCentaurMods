# Chess game manager with event-driven architecture
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

from DGTCentaurMods.board import board
from DGTCentaurMods.board.sync_centaur import Key
from DGTCentaurMods.db import models
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
from scipy.optimize import linear_sum_assignment
import threading
import time
import chess
import numpy as np
from typing import Callable, Optional, List, Tuple
from enum import IntEnum
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log


# Event constants
class GameEvent(IntEnum):
    NEW_GAME = 1
    BLACK_TURN = 2
    WHITE_TURN = 3
    REQUEST_DRAW = 4
    RESIGN_GAME = 5
    MOVE_COMPLETED = 6
    GAME_OVER = 7
    TAKEBACK = 8


# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
MIN_UCI_MOVE_LENGTH = 4
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
STARTING_STATE = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')


class GameManager:
    """
    Event-driven chess game manager that handles board state, move validation,
    and provides guidance for misplaced pieces.
    """
    
    def __init__(self):
        self._board = chess.Board()
        self._board_states: List[bytearray] = []
        self._event_callbacks: List[Callable[[GameEvent, Optional[str]], None]] = []
        self._move_callbacks: List[Callable[[str], None]] = []
        self._key_callbacks: List[Callable[[Key], None]] = []
        self._takeback_callbacks: List[Callable[[], None]] = []
        
        # Move tracking state
        self._source_square: Optional[int] = None
        self._opponent_source_square: Optional[int] = None
        self._legal_squares: List[int] = []
        self._forced_move: Optional[str] = None
        self._is_forced_move: bool = False
        
        # Correction mode state
        self._correction_mode: bool = False
        self._correction_expected_state: Optional[bytearray] = None
        
        # Game metadata
        self._game_info = {
            'event': '',
            'site': '',
            'round': '',
            'white': '',
            'black': ''
        }
        
        # Database
        self._session: Optional[sessionmaker] = None
        self._game_db_id: Optional[int] = None
        
        # Threading
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        
    def subscribe(
        self,
        event_callback: Optional[Callable[[GameEvent, Optional[str]], None]] = None,
        move_callback: Optional[Callable[[str], None]] = None,
        key_callback: Optional[Callable[[Key], None]] = None,
        takeback_callback: Optional[Callable[[], None]] = None
    ):
        """
        Subscribe to game events.
        
        Args:
            event_callback: Called with (GameEvent, optional_termination_string)
            move_callback: Called with move string (UCI format)
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
    
    def set_game_info(self, event: str = '', site: str = '', round: str = '', 
                     white: str = '', black: str = ''):
        """Set game metadata for database logging."""
        self._game_info = {
            'event': event,
            'site': site,
            'round': round,
            'white': white,
            'black': black
        }
    
    def start(self):
        """Start the game manager and subscribe to board events."""
        if self._running:
            return
        
        # Initialize database session
        Session = sessionmaker(bind=models.engine)
        self._session = Session()
        
        # Collect initial board state
        self._collect_board_state()
        
        # Check if board is in starting position
        current_state = board.getChessState()
        if self._is_starting_position(current_state):
            self._reset_game()
        
        # Subscribe to board events
        self._running = True
        board.subscribeEvents(self._key_callback, self._field_callback, timeout=100000)
        
        log.info("[GameManager] Started and subscribed to board events")
    
    def stop(self):
        """Stop the game manager and clean up resources."""
        self._running = False
        board.ledsOff()
        board.pauseEvents()
        
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        
        log.info("[GameManager] Stopped")
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self._board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self._board.fen()
    
    def set_forced_move(self, move: str, forced: bool = True):
        """
        Set a forced move that the player must make.
        
        Args:
            move: UCI move string (e.g., "e2e4")
            forced: Whether the move is forced (default True)
        """
        if len(move) < MIN_UCI_MOVE_LENGTH:
            return
        
        self._forced_move = move
        self._is_forced_move = forced
        
        # Light up LEDs to guide the move
        from_sq, to_sq = self._uci_to_squares(move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
            log.info(f"[GameManager] Forced move set: {move}")
    
    def clear_forced_move(self):
        """Clear any pending forced move."""
        self._forced_move = None
        self._is_forced_move = False
    
    def _key_callback(self, key: Key):
        """Handle key press events from the board."""
        for callback in self._key_callbacks:
            try:
                callback(key)
            except Exception as e:
                log.error(f"[GameManager] Error in key callback: {e}")
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """
        Handle piece lift/place events from the board.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63, a1=0, h8=63)
            time_in_seconds: Timestamp of the event
        """
        if not self._running:
            return
        
        is_lift = (piece_event == 0)
        is_place = (piece_event == 1)
        
        # Handle correction mode
        if self._correction_mode:
            self._handle_correction_mode_event(is_lift, is_place, field)
            return
        
        # Check for starting position (new game detection)
        current_state = board.getChessState()
        if self._is_starting_position(current_state):
            self._reset_game()
            return
        
        # Normal game flow
        piece_color = self._board.color_at(field)
        is_current_player_piece = (self._board.turn == chess.WHITE) == (piece_color == True)
        
        if is_lift:
            self._handle_piece_lift(field, is_current_player_piece)
        elif is_place:
            self._handle_piece_place(field, is_current_player_piece)
    
    def _handle_piece_lift(self, field: int, is_current_player_piece: bool):
        """Handle piece lift event."""
        if is_current_player_piece:
            # Current player's piece lifted
            if self._source_square is None:
                self._legal_squares = self._calculate_legal_squares(field)
                self._source_square = field
                log.info(f"[GameManager] Piece lifted at {chess.square_name(field)}")
        else:
            # Opponent's piece lifted
            self._opponent_source_square = field
            log.info(f"[GameManager] Opponent piece lifted at {chess.square_name(field)}")
    
    def _handle_piece_place(self, field: int, is_current_player_piece: bool):
        """Handle piece place event."""
        # Handle opponent piece returned to original square
        if not is_current_player_piece and self._opponent_source_square is not None:
            if field == self._opponent_source_square:
                board.ledsOff()
                self._opponent_source_square = None
                return
        
        # Handle forced move validation
        if self._is_forced_move and self._forced_move:
            if is_current_player_piece and self._source_square is not None:
                expected_source = chess.parse_square(self._forced_move[0:2])
                if self._source_square != expected_source:
                    # Wrong piece lifted for forced move
                    self._legal_squares = [field]  # Only allow placing back
                    return
                else:
                    # Correct piece, limit to target square
                    target = chess.parse_square(self._forced_move[2:4])
                    self._legal_squares = [target]
        
        # Validate move
        if self._source_square is None:
            # No corresponding lift - ignore stale place events
            return
        
        if field not in self._legal_squares:
            # Illegal move
            board.beep(board.SOUND_WRONG_MOVE)
            log.warning(f"[GameManager] Illegal move attempted: {chess.square_name(self._source_square)} -> {chess.square_name(field)}")
            
            # Check for takeback
            if self._check_takeback():
                return
            
            # Enter correction mode
            self._enter_correction_mode()
            return
        
        # Legal move
        if field == self._source_square:
            # Piece placed back on source
            board.ledsOff()
            self._reset_move_state()
        else:
            # Execute the move
            self._execute_move(self._source_square, field)
    
    def _execute_move(self, from_square: int, to_square: int):
        """Execute a legal move."""
        from_name = chess.square_name(from_square)
        to_name = chess.square_name(to_square)
        piece = self._board.piece_at(from_square)
        
        # Handle promotion
        promotion_suffix = self._handle_promotion(to_square, piece, self._is_forced_move)
        
        # Build move string
        if self._is_forced_move and self._forced_move:
            move_str = self._forced_move
        else:
            move_str = from_name + to_name + promotion_suffix
        
        # Make the move
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
        self._collect_board_state()
        
        # Reset move state
        self._reset_move_state()
        self.clear_forced_move()
        
        # Notify callbacks
        for callback in self._move_callbacks:
            try:
                callback(move_str)
            except Exception as e:
                log.error(f"[GameManager] Error in move callback: {e}")
        
        board.beep(board.SOUND_GENERAL)
        board.led(to_square)
        
        # Check game outcome
        outcome = self._board.outcome(claim_draw=True)
        if outcome is None:
            # Game continues - switch turn
            self._switch_turn()
        else:
            # Game over
            board.beep(board.SOUND_GENERAL)
            result_str = str(self._board.result())
            termination = str(outcome.termination)
            self._update_game_result(result_str, termination)
    
    def _handle_promotion(self, field: int, piece: Optional[chess.Piece], forced: bool) -> str:
        """
        Handle pawn promotion.
        
        Returns:
            Promotion suffix ("q", "r", "b", "n") or empty string
        """
        if piece is None:
            return ""
        
        piece_name = str(piece)
        is_white_promotion = (field // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
        is_black_promotion = (field // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        
        if forced:
            # For forced moves, default to queen
            return "q"
        
        # Wait for user selection via key press
        return self._wait_for_promotion_choice()
    
    def _wait_for_promotion_choice(self) -> str:
        """
        Wait for user to select promotion piece via button press.
        
        Returns:
            Promotion piece suffix ("q", "r", "b", "n")
        """
        from DGTCentaurMods.display import epaper
        
        # Show promotion options on display
        screen_back = epaper.epaperbuffer.copy()
        epaper.promotionOptions(13)
        
        # Wait for key press
        key = board.wait_for_key_up(timeout=60)
        
        # Restore screen
        epaper.epaperbuffer = screen_back.copy()
        
        # Map keys to promotion pieces
        if key == Key.BACK:
            return "n"  # Knight
        elif key == Key.TICK:
            return "b"  # Bishop
        elif key == Key.UP:
            return "q"  # Queen
        elif key == Key.DOWN:
            return "r"  # Rook
        else:
            return "q"  # Default to queen on timeout/other
    
    def _switch_turn(self):
        """Switch turn and emit appropriate event."""
        if self._board.turn == chess.WHITE:
            self._emit_event(GameEvent.WHITE_TURN)
        else:
            self._emit_event(GameEvent.BLACK_TURN)
    
    def _check_takeback(self) -> bool:
        """Check if a takeback is in progress."""
        if len(self._board_states) < 2:
            return False
        
        current_state = board.getChessState()
        previous_state = self._board_states[-2]
        
        if bytearray(current_state) == bytearray(previous_state):
            # Takeback detected
            board.ledsOff()
            self._board_states.pop()
            
            # Remove last move from database
            if self._session:
                last_move = self._session.query(models.GameMove).order_by(models.GameMove.id.desc()).first()
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
                    log.error(f"[GameManager] Error in takeback callback: {e}")
            
            # Verify board state after takeback
            time.sleep(0.2)
            current = board.getChessState()
            if not self._validate_board_state(current, self._board_states[-1] if self._board_states else None):
                log.warning("[GameManager] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            return True
        
        return False
    
    def _enter_correction_mode(self):
        """Enter correction mode to guide user in fixing board state."""
        self._correction_mode = True
        self._correction_expected_state = self._board_states[-1] if self._board_states else None
        log.warning("[GameManager] Entered correction mode")
    
    def _exit_correction_mode(self):
        """Exit correction mode and resume normal game flow."""
        self._correction_mode = False
        expected_state = self._correction_expected_state
        self._correction_expected_state = None
        
        # Reset move state
        self._reset_move_state()
        
        # Restore forced move LEDs if needed
        if self._is_forced_move and self._forced_move:
            from_sq, to_sq = self._uci_to_squares(self._forced_move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
        
        log.info("[GameManager] Exited correction mode")
    
    def _handle_correction_mode_event(self, is_lift: bool, is_place: bool, field: int):
        """Handle events while in correction mode."""
        current_state = board.getChessState()
        
        # Check for starting position
        if self._is_starting_position(current_state):
            log.info("[GameManager] Starting position detected in correction mode - resetting game")
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
        
        # Still incorrect - provide guidance
        self._provide_correction_guidance(current_state, self._correction_expected_state)
    
    def _provide_correction_guidance(self, current_state: bytearray, expected_state: bytearray):
        """
        Provide LED guidance to correct misplaced pieces using Hungarian algorithm.
        """
        if current_state is None or expected_state is None:
            return
        
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return
        
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
        
        # Guide one piece at a time using Hungarian algorithm
        if len(wrong_locations) > 0 and len(missing_origins) > 0:
            if len(wrong_locations) == 1 and len(missing_origins) == 1:
                # Simple case
                from_idx = wrong_locations[0]
                to_idx = missing_origins[0]
            else:
                # Use Hungarian algorithm for optimal pairing
                costs = np.zeros((len(wrong_locations), len(missing_origins)))
                for i, wl in enumerate(wrong_locations):
                    for j, mo in enumerate(missing_origins):
                        costs[i, j] = self._manhattan_distance(wl, mo)
                
                row_ind, col_ind = linear_sum_assignment(costs)
                from_idx = wrong_locations[row_ind[0]]
                to_idx = missing_origins[col_ind[0]]
            
            board.ledsOff()
            board.ledFromTo(from_idx, to_idx, intensity=5)
            log.warning(f"[GameManager] Guiding piece from {chess.square_name(from_idx)} to {chess.square_name(to_idx)}")
        else:
            # Only pieces missing or only extra pieces
            board.ledsOff()
            if len(missing_origins) > 0:
                for idx in missing_origins:
                    board.led(idx, intensity=5)
            elif len(wrong_locations) > 0:
                for idx in wrong_locations:
                    board.led(idx, intensity=5)
    
    def _manhattan_distance(self, a: int, b: int) -> float:
        """Calculate Manhattan distance between two squares."""
        ar, ac = a // BOARD_WIDTH, a % BOARD_WIDTH
        br, bc = b // BOARD_WIDTH, b % BOARD_WIDTH
        return abs(ar - br) + abs(ac - bc)
    
    def _validate_board_state(self, current: bytearray, expected: Optional[bytearray]) -> bool:
        """Validate that current board state matches expected state."""
        if current is None or expected is None:
            return False
        if len(current) != BOARD_SIZE or len(expected) != BOARD_SIZE:
            return False
        return bytearray(current) == bytearray(expected)
    
    def _is_starting_position(self, state: Optional[bytearray]) -> bool:
        """Check if board is in starting position."""
        if state is None or len(state) != BOARD_SIZE:
            return False
        return bytearray(state) == STARTING_STATE
    
    def _reset_game(self):
        """Reset game to starting position."""
        log.info("[GameManager] Resetting game to starting position")
        
        self._reset_move_state()
        self.clear_forced_move()
        self._board.reset()
        paths.write_fen_log(self._board.fen())
        
        board.beep(board.SOUND_GENERAL)
        time.sleep(0.3)
        board.beep(board.SOUND_GENERAL)
        board.ledsOff()
        
        # Emit events
        self._emit_event(GameEvent.NEW_GAME)
        self._emit_event(GameEvent.WHITE_TURN)
        
        # Log new game to database
        if self._session:
            game = models.Game(
                source=self._game_info.get('event', 'games.manager'),
                event=self._game_info.get('event', ''),
                site=self._game_info.get('site', ''),
                round=self._game_info.get('round', ''),
                white=self._game_info.get('white', ''),
                black=self._game_info.get('black', '')
            )
            self._session.add(game)
            self._session.commit()
            
            self._game_db_id = self._session.query(func.max(models.Game.id)).scalar()
            
            # Log initial position
            gamemove = models.GameMove(
                gameid=self._game_db_id,
                move='',
                fen=str(self._board.fen())
            )
            self._session.add(gamemove)
            self._session.commit()
        
        self._board_states = []
        self._collect_board_state()
    
    def _calculate_legal_squares(self, field: int) -> List[int]:
        """Calculate legal destination squares for a piece at the given field."""
        legal_squares = [field]  # Include source square
        
        for move in self._board.legal_moves:
            if move.from_square == field:
                legal_squares.append(move.to_square)
        
        return legal_squares
    
    def _reset_move_state(self):
        """Reset move-related state variables."""
        self._legal_squares = []
        self._source_square = None
        self._opponent_source_square = None
        board.ledsOff()
    
    def _collect_board_state(self):
        """Collect and store current board state."""
        state = board.getChessState()
        if state:
            self._board_states.append(bytearray(state))
            log.debug("[GameManager] Collected board state")
    
    def _uci_to_squares(self, uci_move: str) -> Tuple[Optional[int], Optional[int]]:
        """Convert UCI move string to square indices."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return None, None
        
        from_num = ((ord(uci_move[1:2]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[0:1]) - ord("a"))
        to_num = ((ord(uci_move[3:4]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[2:3]) - ord("a"))
        return from_num, to_num
    
    def _emit_event(self, event: GameEvent, termination: Optional[str] = None):
        """Emit an event to all subscribers."""
        for callback in self._event_callbacks:
            try:
                callback(event, termination)
            except Exception as e:
                log.error(f"[GameManager] Error in event callback: {e}")
    
    def _update_game_result(self, result_str: str, termination: str):
        """Update game result in database and emit event."""
        if self._session and self._game_db_id:
            game = self._session.query(models.Game).filter(models.Game.id == self._game_db_id).first()
            if game:
                game.result = result_str
                self._session.flush()
                self._session.commit()
        
        self._emit_event(GameEvent.GAME_OVER, termination)
    
    def resign(self, side_resigning: int):
        """
        Handle game resignation.
        
        Args:
            side_resigning: 1 for white, 2 for black
        """
        result_str = "0-1" if side_resigning == 1 else "1-0"
        self._update_game_result(result_str, "Termination.RESIGN")
    
    def draw(self):
        """Handle game draw."""
        self._update_game_result("1/2-1/2", "Termination.DRAW")

