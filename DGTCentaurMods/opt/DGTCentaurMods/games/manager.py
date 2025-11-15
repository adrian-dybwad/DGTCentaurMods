"""
Chess Game Manager - Event-driven game state management.

This module provides complete chess game state management with automatic turn tracking,
event-driven notifications, board event subscription, misplaced piece guidance, and
opponent move handling.

This file is part of the DGTCentaur Mods open source software
( https://github.com/EdNekebno/DGTCentaur )

DGTCentaur Mods is free software: you can redistribute
it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version.

DGTCentaur Mods is distributed in the hope that it will
be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this file.  If not, see

https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md

This and any other notices must remain intact and unaltered in any
distribution, modification, variant, or derivative of this software.
"""

import threading
import time
import chess
import inspect
import sys
from typing import Optional, Callable, List, Tuple
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
EVENT_BLACK_TURN = 2
EVENT_WHITE_TURN = 3
EVENT_REQUEST_DRAW = 4
EVENT_RESIGN_GAME = 5

# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
MIN_UCI_MOVE_LENGTH = 4

# Game constants
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
STARTING_STATE = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')


class GameManager:
    """
    Manages chess game state with event-driven notifications.
    
    Provides complete game state management, automatic turn tracking,
    board event subscription, misplaced piece guidance, and opponent move handling.
    """
    
    def __init__(self):
        """Initialize the game manager."""
        self._kill = False
        self._cboard = chess.Board()
        self._board_states: List[bytearray] = []
        self._session: Optional[sessionmaker] = None
        self._game_db_id: Optional[int] = None
        
        # Move tracking state
        self._source_square: Optional[int] = None
        self._legal_squares: List[int] = []
        self._opponent_source_square: Optional[int] = None
        
        # Forced move state (for computer moves)
        self._forced_move: bool = False
        self._computer_move: Optional[str] = None
        
        # Correction mode state
        self._correction_mode: bool = False
        self._correction_expected_state: Optional[bytearray] = None
        self._correction_just_exited: bool = False  # Flag to suppress stale events after correction mode exits
        
        # Game info
        self._game_info = {
            'event': '',
            'site': '',
            'round': '',
            'white': '',
            'black': '',
            'source': ''
        }
        
        # Event callbacks
        self._event_callbacks: List[Callable] = []
        self._move_callbacks: List[Callable] = []
        self._key_callbacks: List[Callable] = []
        self._takeback_callbacks: List[Callable] = []
        
        # Threading
        self._game_thread: Optional[threading.Thread] = None
        
    def subscribe_event(self, callback: Callable) -> None:
        """Subscribe to game events (NEW_GAME, TURN, etc.)."""
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)
            log.info(f"[GameManager] Event callback subscribed: {callback}")
    
    def subscribe_move(self, callback: Callable) -> None:
        """Subscribe to move events."""
        if callback not in self._move_callbacks:
            self._move_callbacks.append(callback)
            log.info(f"[GameManager] Move callback subscribed: {callback}")
    
    def subscribe_key(self, callback: Callable) -> None:
        """Subscribe to key press events."""
        if callback not in self._key_callbacks:
            self._key_callbacks.append(callback)
            log.info(f"[GameManager] Key callback subscribed: {callback}")
    
    def subscribe_takeback(self, callback: Callable) -> None:
        """Subscribe to takeback events."""
        if callback not in self._takeback_callbacks:
            self._takeback_callbacks.append(callback)
            log.info(f"[GameManager] Takeback callback subscribed: {callback}")
    
    def _notify_event(self, event: int) -> None:
        """Notify all event subscribers."""
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as e:
                log.error(f"[GameManager] Error in event callback {callback}: {e}")
    
    def _notify_move(self, move: str) -> None:
        """Notify all move subscribers."""
        for callback in self._move_callbacks:
            try:
                callback(move)
            except Exception as e:
                log.error(f"[GameManager] Error in move callback {callback}: {e}")
    
    def _notify_key(self, key) -> None:
        """Notify all key subscribers."""
        for callback in self._key_callbacks:
            try:
                callback(key)
            except Exception as e:
                log.error(f"[GameManager] Error in key callback {callback}: {e}")
    
    def _notify_takeback(self) -> None:
        """Notify all takeback subscribers."""
        for callback in self._takeback_callbacks:
            try:
                callback()
            except Exception as e:
                log.error(f"[GameManager] Error in takeback callback {callback}: {e}")
    
    def set_game_info(self, event: str = '', site: str = '', round: str = '',
                     white: str = '', black: str = '') -> None:
        """Set game metadata for database logging."""
        self._game_info['event'] = event
        self._game_info['site'] = site
        self._game_info['round'] = round
        self._game_info['white'] = white
        self._game_info['black'] = black
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self._cboard
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self._cboard.fen()
    
    def _collect_board_state(self) -> None:
        """Collect and store current board state."""
        state = board.getChessState()
        if state:
            self._board_states.append(bytearray(state))
            log.debug(f"[GameManager] Collected board state (total: {len(self._board_states)})")
    
    def _is_starting_position(self, state: Optional[bytearray] = None) -> bool:
        """Check if board is in starting position."""
        if state is None:
            state = board.getChessState()
        if state is None or len(state) != BOARD_SIZE:
            return False
        return bytearray(state) == STARTING_STATE
    
    def _board_state_from_fen(self, fen: str) -> Optional[bytearray]:
        """Convert FEN string to bytearray board state (piece presence only)."""
        try:
            board_obj = chess.Board(fen)
            state = bytearray(BOARD_SIZE)
            for square in range(BOARD_SIZE):
                if board_obj.piece_at(square) is not None:
                    state[square] = 1
            return state
        except Exception as e:
            log.error(f"[GameManager] Error converting FEN to board state: {e}")
            return None
    
    def _validate_board_state(self, current: bytearray, expected: bytearray) -> bool:
        """Validate that current board state matches expected."""
        if current is None or expected is None:
            return False
        if len(current) != BOARD_SIZE or len(expected) != BOARD_SIZE:
            return False
        return bytearray(current) == bytearray(expected)
    
    def _uci_to_squares(self, uci_move: str) -> Tuple[Optional[int], Optional[int]]:
        """Convert UCI move string to square indices."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return None, None
        try:
            from_square = ((ord(uci_move[1:2]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[0:1]) - ord("a"))
            to_square = ((ord(uci_move[3:4]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[2:3]) - ord("a"))
            return from_square, to_square
        except (IndexError, ValueError):
            return None, None
    
    def _calculate_legal_squares(self, field: int) -> List[int]:
        """Calculate legal destination squares for a piece at the given field."""
        legal_squares = [field]  # Include source square
        for move in self._cboard.legal_moves:
            if move.from_square == field:
                legal_squares.append(move.to_square)
        return legal_squares
    
    def _reset_move_state(self) -> None:
        """Reset move-related state variables."""
        self._source_square = None
        self._legal_squares = []
        self._opponent_source_square = None
        board.ledsOff()
    
    def _enter_correction_mode(self) -> None:
        """Enter correction mode to guide user in fixing board state."""
        self._correction_mode = True
        self._correction_expected_state = self._board_states[-1] if self._board_states else None
        self._correction_just_exited = False  # Clear flag when entering correction mode
        log.warning(f"[GameManager] Entered correction mode")
    
    def _exit_correction_mode(self) -> None:
        """Exit correction mode and resume normal game flow."""
        self._correction_mode = False
        self._correction_expected_state = None
        self._correction_just_exited = True  # Set flag to suppress stale events immediately after exit
        log.warning("[GameManager] Exited correction mode")
        
        # Reset move state to ensure clean state after correction
        self._source_square = None
        self._legal_squares = []
        self._opponent_source_square = None
        
        # Restore forced move LEDs if pending
        if self._forced_move and self._computer_move and len(self._computer_move) >= MIN_UCI_MOVE_LENGTH:
            from_sq, to_sq = self._uci_to_squares(self._computer_move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
                log.info(f"[GameManager] Restored forced move LEDs: {self._computer_move}")
    
    def _provide_correction_guidance(self, current_state: bytearray, expected_state: bytearray) -> None:
        """Provide LED guidance to correct misplaced pieces using Hungarian algorithm."""
        if current_state is None or expected_state is None:
            return
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return
        
        def _rc(idx: int) -> Tuple[int, int]:
            """Convert square index to (row, col)."""
            return (idx // BOARD_WIDTH), (idx % BOARD_WIDTH)
        
        def _dist(a: int, b: int) -> int:
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
                        costs[i, j] = _dist(wl, mo)
                
                row_ind, col_ind = linear_sum_assignment(costs)
                from_idx = wrong_locations[row_ind[0]]
                to_idx = missing_origins[col_ind[0]]
            
            board.ledsOff()
            board.ledFromTo(from_idx, to_idx, intensity=5)
            log.warning(f"[GameManager] Guiding piece from {chess.square_name(from_idx)} to {chess.square_name(to_idx)}")
        elif len(missing_origins) > 0:
            board.ledsOff()
            for idx in missing_origins:
                board.led(idx, intensity=5)
            log.warning(f"[GameManager] Pieces missing at: {[chess.square_name(sq) for sq in missing_origins]}")
        elif len(wrong_locations) > 0:
            board.ledsOff()
            for idx in wrong_locations:
                board.led(idx, intensity=5)
            log.warning(f"[GameManager] Extra pieces at: {[chess.square_name(sq) for sq in wrong_locations]}")
    
    def _check_takeback(self) -> bool:
        """Check if a takeback is in progress by comparing current state to previous state."""
        if len(self._takeback_callbacks) == 0 or len(self._board_states) < 2:
            return False
        
        current_state = board.getChessState()
        if current_state is None:
            return False
        
        previous_state = self._board_states[-2]
        if self._validate_board_state(bytearray(current_state), previous_state):
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
                    log.error(f"[GameManager] Error removing move from database: {e}")
            
            # Pop move from board
            self._cboard.pop()
            paths.write_fen_log(self._cboard.fen())
            board.beep(board.SOUND_GENERAL)
            self._notify_takeback()
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            current = board.getChessState()
            if current and not self._validate_board_state(bytearray(current), self._board_states[-1] if self._board_states else None):
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
        return "q"  # Default to queen for forced moves
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float) -> None:
        """Handle field events (piece lift/place)."""
        # Check for starting position on every field event (not just in correction mode)
        current_state = board.getChessState()
        if current_state is not None and len(current_state) == BOARD_SIZE:
            if bytearray(current_state) == STARTING_STATE:
                # Always trigger new game when starting position is detected
                # (either fresh start or reset during active game)
                log.info("[GameManager] Starting position detected in field callback - triggering new game")
                board.ledsOff()
                board.beep(board.SOUND_GENERAL)
                time.sleep(0.3)
                board.beep(board.SOUND_GENERAL)
                self._reset_game()
                return
        
        field_name = chess.square_name(field)
        is_lift = (piece_event == 0)
        is_place = (piece_event == 1)
        
        # For lift events, check piece at the square
        # For place events, check piece at source square (if we have one) or current square
        if is_lift:
            piece_color = self._cboard.color_at(field)
        else:
            # For place events, check the source square if we have one
            if self._source_square is not None:
                piece_color = self._cboard.color_at(self._source_square)
            elif self._opponent_source_square is not None:
                piece_color = self._cboard.color_at(self._opponent_source_square)
            else:
                piece_color = self._cboard.color_at(field)
        
        # Check if piece belongs to current player (only if piece_color is not None)
        is_current_player_piece = False
        if piece_color is not None:
            is_current_player_piece = (self._cboard.turn == chess.WHITE) == (piece_color == True)
        
        log.info(f"[GameManager.field_callback] event={'LIFT' if is_lift else 'PLACE'} field={field} ({field_name}) "
                 f"piece_color={'White' if piece_color == True else 'Black' if piece_color == False else 'None'} "
                 f"turn={'White' if self._cboard.turn else 'Black'} "
                 f"is_current_player={is_current_player_piece}")
        
        # Handle lift events
        if is_lift:
            if is_current_player_piece:
                # Current player lifting their piece
                if field not in self._legal_squares and self._source_square is None:
                    self._legal_squares = self._calculate_legal_squares(field)
                    self._source_square = field
                    log.info(f"[GameManager] Player lifted piece at {field_name}, legal squares: {[chess.square_name(sq) for sq in self._legal_squares]}")
                
                # Handle forced move
                if self._forced_move and self._computer_move and len(self._computer_move) >= MIN_UCI_MOVE_LENGTH:
                    expected_source = chess.parse_square(self._computer_move[0:2])
                    if field == expected_source:
                        # Correct piece lifted for forced move
                        target = chess.parse_square(self._computer_move[2:4])
                        self._legal_squares = [target]
                        log.info(f"[GameManager] Forced move: correct piece lifted, limiting to target {chess.square_name(target)}")
                    else:
                        # Wrong piece lifted for forced move
                        self._legal_squares = [field]
                        log.warning(f"[GameManager] Forced move: wrong piece lifted at {field_name}, expected {self._computer_move[0:2]}")
            else:
                # Opponent piece lifted
                self._opponent_source_square = field
                log.info(f"[GameManager] Opponent piece lifted at {field_name}")
        
        # Handle place events
        if is_place:
            # Handle opponent piece placement back (check opponent source square first)
            if self._opponent_source_square is not None and field == self._opponent_source_square:
                board.ledsOff()
                self._opponent_source_square = None
                log.info(f"[GameManager] Opponent piece placed back at {field_name}")
                return
            
            # Handle opponent move completion (opponent placed piece on different square)
            # Only process if this is actually an opponent piece (not current player)
            if self._opponent_source_square is not None and field != self._opponent_source_square and not is_current_player_piece:
                # Opponent placed piece on a different square - detect the move
                log.info(f"[GameManager] Opponent move detected: {chess.square_name(self._opponent_source_square)} to {field_name}")
                time.sleep(0.3)  # Give board time to settle
                current_state = board.getChessState()
                
                if current_state and self._board_states:
                    # Try to find the move that matches the board state
                    try:
                        # Get all legal moves for opponent
                        opponent_board = self._cboard.copy()
                        legal_moves = list(opponent_board.legal_moves)
                        
                        # Try each legal move to see which one matches the board state
                        detected_move = None
                        for move in legal_moves:
                            if move.from_square == self._opponent_source_square:
                                test_board = self._cboard.copy()
                                test_board.push(move)
                                test_state = self._board_state_from_fen(test_board.fen())
                                
                                if test_state and self._validate_board_state(bytearray(current_state), test_state):
                                    detected_move = move
                                    break
                        
                        if detected_move:
                            # Valid opponent move detected
                            self._cboard.push(detected_move)
                            paths.write_fen_log(self._cboard.fen())
                            
                            # Log move to database
                            if self._session and self._game_db_id:
                                try:
                                    game_move = models.GameMove(
                                        gameid=self._game_db_id,
                                        move=detected_move.uci(),
                                        fen=str(self._cboard.fen())
                                    )
                                    self._session.add(game_move)
                                    self._session.commit()
                                except Exception as e:
                                    log.error(f"[GameManager] Error logging opponent move to database: {e}")
                            
                            self._collect_board_state()
                            self._opponent_source_square = None
                            self._notify_move(detected_move.uci())
                            board.beep(board.SOUND_GENERAL)
                            board.led(field)
                            
                            log.info(f"[GameManager] Opponent move processed: {detected_move.uci()}")
                            
                            # Check game outcome
                            outcome = self._cboard.outcome(claim_draw=True)
                            if outcome is None:
                                # Switch turn
                                if self._cboard.turn == chess.WHITE:
                                    self._notify_event(EVENT_WHITE_TURN)
                                else:
                                    self._notify_event(EVENT_BLACK_TURN)
                            else:
                                # Game over
                                board.beep(board.SOUND_GENERAL)
                                result_str = str(self._cboard.result())
                                termination = str(outcome.termination)
                                self._update_game_result(result_str, termination)
                        else:
                            # Could not detect valid move - enter correction mode
                            log.warning(f"[GameManager] Could not detect valid opponent move, entering correction mode")
                            self._enter_correction_mode()
                            if self._board_states:
                                self._provide_correction_guidance(bytearray(current_state), self._board_states[-1])
                    except Exception as e:
                        log.error(f"[GameManager] Error detecting opponent move: {e}")
                        import traceback
                        traceback.print_exc()
                        # Enter correction mode on error
                        self._enter_correction_mode()
                        if self._board_states:
                            self._provide_correction_guidance(bytearray(current_state), self._board_states[-1])
                
                return
            
            # Only process player moves if we have a source square (piece was lifted)
            # But first check for stale events
            if self._source_square is None:
                # Check if this might be a stale event after correction mode
                if self._correction_just_exited:
                    # After correction mode exits, ignore stale PLACE events
                    if self._forced_move and self._computer_move and len(self._computer_move) >= MIN_UCI_MOVE_LENGTH:
                        forced_source = chess.parse_square(self._computer_move[0:2])
                        if field != forced_source:
                            log.info(f"[GameManager] Ignoring stale PLACE event after correction exit for field {field}")
                            self._correction_just_exited = False
                            return
                    else:
                        log.info(f"[GameManager] Ignoring stale PLACE event after correction exit for field {field}")
                        self._correction_just_exited = False
                        return
                
                # For forced moves, allow PLACE on source square even without LIFT (piece might already be lifted)
                if self._forced_move and self._computer_move and len(self._computer_move) >= MIN_UCI_MOVE_LENGTH:
                    forced_source = chess.parse_square(self._computer_move[0:2])
                    if field == forced_source:
                        # This is the forced move source - set it up
                        self._source_square = field
                        target = chess.parse_square(self._computer_move[2:4])
                        self._legal_squares = [target]
                        log.info(f"[GameManager] Forced move: setting up source square {field_name} -> {chess.square_name(target)}")
                    else:
                        log.info(f"[GameManager] Ignoring PLACE event for field {field} - no source square and not forced move source")
                        return
                else:
                    # No source square and not a forced move - this is a stale event
                    log.info(f"[GameManager] Ignoring PLACE event for field {field} - no corresponding LIFT")
                    return
            
            # Clear the flag once we process a valid event (LIFT)
            if is_lift:
                self._correction_just_exited = False
            
            # Check if move is legal
            if field not in self._legal_squares:
                board.beep(board.SOUND_WRONG_MOVE)
                log.warning(f"[GameManager] Piece placed on illegal square {field_name}")
                
                # Check for takeback first
                if not self._check_takeback():
                    # Guide misplaced piece
                    self._enter_correction_mode()
                    current_state = board.getChessState()
                    if current_state and self._board_states:
                        self._provide_correction_guidance(bytearray(current_state), self._board_states[-1])
                return
            
            # Legal move
            if field == self._source_square:
                # Piece placed back on source square
                board.ledsOff()
                self._reset_move_state()
                log.info(f"[GameManager] Piece placed back at source {field_name}")
            else:
                # Make the move
                from_name = chess.square_name(self._source_square)
                to_name = chess.square_name(field)
                piece_name = str(self._cboard.piece_at(self._source_square))
                promotion_suffix = self._handle_promotion(field, piece_name, self._forced_move)
                
                if self._forced_move and self._computer_move:
                    move_str = self._computer_move
                else:
                    move_str = from_name + to_name + promotion_suffix
                
                try:
                    move = chess.Move.from_uci(move_str)
                    self._cboard.push(move)
                    paths.write_fen_log(self._cboard.fen())
                    
                    # Log move to database
                    if self._session and self._game_db_id:
                        try:
                            game_move = models.GameMove(
                                gameid=self._game_db_id,
                                move=move_str,
                                fen=str(self._cboard.fen())
                            )
                            self._session.add(game_move)
                            self._session.commit()
                        except Exception as e:
                            log.error(f"[GameManager] Error logging move to database: {e}")
                    
                    self._collect_board_state()
                    self._reset_move_state()
                    self._forced_move = False
                    self._computer_move = None
                    
                    self._notify_move(move_str)
                    board.beep(board.SOUND_GENERAL)
                    board.led(field)
                    
                    log.info(f"[GameManager] Move made: {move_str}")
                    
                    # Check game outcome
                    outcome = self._cboard.outcome(claim_draw=True)
                    if outcome is None:
                        # Switch turn
                        if self._cboard.turn == chess.WHITE:
                            self._notify_event(EVENT_WHITE_TURN)
                        else:
                            self._notify_event(EVENT_BLACK_TURN)
                    else:
                        # Game over
                        board.beep(board.SOUND_GENERAL)
                        result_str = str(self._cboard.result())
                        termination = str(outcome.termination)
                        self._update_game_result(result_str, termination)
                        
                except ValueError as e:
                    log.error(f"[GameManager] Invalid move {move_str}: {e}")
                    board.beep(board.SOUND_WRONG_MOVE)
                    self._reset_move_state()
    
    def _correction_field_callback(self, piece_event: int, field: int, time_in_seconds: float) -> None:
        """Handle field events during correction mode."""
        current_state = board.getChessState()
        if current_state is None:
            return
        
        # Check if board is in starting position (new game detection)
        if len(current_state) == BOARD_SIZE:
            if bytearray(current_state) == STARTING_STATE:
                log.info("[GameManager] Starting position detected while in correction mode - triggering new game")
                board.ledsOff()
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                self._reset_game()
                return
        
        # Check if board matches expected state
        if self._correction_expected_state and self._validate_board_state(bytearray(current_state), self._correction_expected_state):
            log.info("[GameManager] Board corrected, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            return
        
        # Still incorrect, update guidance
        if self._correction_expected_state:
            self._provide_correction_guidance(bytearray(current_state), self._correction_expected_state)
    
    def _key_callback(self, key_pressed) -> None:
        """Handle key press events."""
        self._notify_key(key_pressed)
    
    def _reset_game(self) -> None:
        """Reset game to starting position."""
        try:
            log.info("[GameManager] Resetting game to starting position")
            self._reset_move_state()
            self._forced_move = False
            self._computer_move = None
            self._cboard.reset()
            paths.write_fen_log(self._cboard.fen())
            board.beep(board.SOUND_GENERAL)
            time.sleep(0.3)
            board.beep(board.SOUND_GENERAL)
            board.ledsOff()
            
            self._notify_event(EVENT_NEW_GAME)
            self._notify_event(EVENT_WHITE_TURN)
            
            # Log new game to database
            if self._session:
                try:
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
                    
                    # Log initial board state
                    gamemove = models.GameMove(
                        gameid=self._game_db_id,
                        move='',
                        fen=str(self._cboard.fen())
                    )
                    self._session.add(gamemove)
                    self._session.commit()
                except Exception as e:
                    log.error(f"[GameManager] Error logging new game to database: {e}")
            
            self._board_states = []
            self._collect_board_state()
            
        except Exception as e:
            log.error(f"[GameManager] Error resetting game: {e}")
            import traceback
            traceback.print_exc()
    
    def _update_game_result(self, result_str: str, termination: str) -> None:
        """Update game result in database and notify subscribers."""
        if self._session and self._game_db_id:
            try:
                game = self._session.query(models.Game).filter(models.Game.id == self._game_db_id).first()
                if game:
                    game.result = result_str
                    self._session.commit()
            except Exception as e:
                log.error(f"[GameManager] Error updating game result: {e}")
        
        # Notify subscribers of termination
        self._notify_event(termination)
    
    def set_computer_move(self, move: str, forced: bool = True) -> None:
        """Set a computer move that the player is expected to make."""
        if len(move) < MIN_UCI_MOVE_LENGTH:
            return
        
        self._computer_move = move
        self._forced_move = forced
        
        # Light up LEDs to indicate the move
        from_sq, to_sq = self._uci_to_squares(move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
            log.info(f"[GameManager] Computer move set: {move}")
    
    def reset_move_state(self) -> None:
        """Reset all move-related state variables."""
        self._forced_move = False
        self._computer_move = None
        self._reset_move_state()
    
    def _field_callback_wrapper(self, piece_event: int, field: int, time_in_seconds: float) -> None:
        """Wrapper for field callback that handles correction mode routing."""
        if self._correction_mode:
            self._correction_field_callback(piece_event, field, time_in_seconds)
        else:
            self._field_callback(piece_event, field, time_in_seconds)
    
    def _game_thread(self) -> None:
        """Main game thread that subscribes to board events."""
        board.ledsOff()
        log.info("[GameManager] Starting game thread, subscribing to board events")
        
        try:
            board.subscribeEvents(self._key_callback, self._field_callback_wrapper)
        except Exception as e:
            log.error(f"[GameManager] Error subscribing to board events: {e}")
            return
        
        # Check for starting position on startup
        time.sleep(0.5)  # Give board time to initialize
        current_state = board.getChessState()
        if current_state and self._is_starting_position(bytearray(current_state)):
            log.info("[GameManager] Starting position detected on startup")
            self._reset_game()
        
        while not self._kill:
            time.sleep(0.1)
            
            # Periodically check for starting position during active game
            # Check more frequently - if starting position detected, always reset
            if not self._correction_mode:
                current_state = board.getChessState()
                if current_state and self._is_starting_position(bytearray(current_state)):
                    # Only trigger if we have board states (game was active) to avoid reset loops
                    # If board_states is empty, field callback will handle it
                    if len(self._board_states) > 0:
                        log.info("[GameManager] Starting position detected during active game")
                        self._reset_game()
    
    def start(self) -> None:
        """Start the game manager."""
        if self._game_thread and self._game_thread.is_alive():
            log.warning("[GameManager] Game thread already running")
            return
        
        # Initialize database session
        try:
            Session = sessionmaker(bind=models.engine)
            self._session = Session()
            self._game_info['source'] = inspect.getsourcefile(sys._getframe(1)) or 'unknown'
        except Exception as e:
            log.error(f"[GameManager] Error initializing database session: {e}")
        
        # Collect initial board state before starting thread
        self._board_states = []
        self._collect_board_state()
        
        self._kill = False
        self._game_thread = threading.Thread(target=self._game_thread, daemon=True)
        self._game_thread.start()
        log.info("[GameManager] Game manager started")
    
    def stop(self) -> None:
        """Stop the game manager."""
        log.info("[GameManager] Stopping game manager")
        self._kill = True
        board.ledsOff()
        
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        
        if self._game_thread:
            self._game_thread.join(timeout=2.0)
        
        log.info("[GameManager] Game manager stopped")
    
    def resign_game(self, side_resigning: int) -> None:
        """Handle game resignation (1=white, 2=black)."""
        result_str = "0-1" if side_resigning == 1 else "1-0"
        self._update_game_result(result_str, "Termination.RESIGN")
    
    def draw_game(self) -> None:
        """Handle game draw."""
        self._update_game_result("1/2-1/2", "Termination.DRAW")


# Global instance for backward compatibility
_manager_instance: Optional[GameManager] = None


def get_manager() -> GameManager:
    """Get or create the global game manager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = GameManager()
    return _manager_instance


def subscribe_game(event_callback: Callable, move_callback: Callable,
                  key_callback: Callable, takeback_callback: Optional[Callable] = None) -> None:
    """Subscribe to game manager events (backward compatibility function)."""
    gm = get_manager()
    gm.subscribe_event(event_callback)
    gm.subscribe_move(move_callback)
    gm.subscribe_key(key_callback)
    if takeback_callback:
        gm.subscribe_takeback(takeback_callback)
    gm.start()


def unsubscribe_game() -> None:
    """Unsubscribe from game manager (backward compatibility function)."""
    global _manager_instance
    if _manager_instance:
        _manager_instance.stop()
        _manager_instance = None

