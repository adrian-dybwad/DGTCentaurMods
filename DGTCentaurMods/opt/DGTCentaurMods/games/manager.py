"""
Chess game manager with event-driven architecture.

Provides complete chess game state management, automatic turn tracking,
misplaced piece guidance, and hardware abstraction through board.py.

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

import chess
import threading
import time
import sys
import inspect
from typing import Callable, Optional, List, Tuple
from enum import Enum
import numpy as np
from scipy.optimize import linear_sum_assignment

from DGTCentaurMods.board import board
from DGTCentaurMods.db import models
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log

# Constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
MIN_UCI_MOVE_LENGTH = 4

# Starting position state (1 = piece present, 0 = empty)
STARTING_STATE = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')


class GameEvent(Enum):
    """Game event types."""
    NEW_GAME = 1
    WHITE_TURN = 2
    BLACK_TURN = 3
    MOVE_MADE = 4
    GAME_OVER = 5
    TAKEBACK = 6
    REQUEST_DRAW = 7
    RESIGN = 8


class GameManager:
    """
    Manages chess game state with event-driven architecture.
    
    Provides hardware abstraction, automatic turn tracking, misplaced piece
    guidance, and opponent move guidance even during correction mode.
    """
    
    def __init__(self):
        """Initialize the game manager."""
        self._board = chess.Board()
        self._board_states: List[bytearray] = []
        self._kill_event = threading.Event()
        self._running = False
        
        # Move tracking
        self._source_square: Optional[int] = None
        self._legal_squares: List[int] = []
        self._opponent_source_square: Optional[int] = None
        
        # Forced move (computer move)
        self._forced_move: Optional[str] = None
        self._forced_move_active = False
        
        # Correction mode
        self._correction_mode = False
        self._correction_expected_state: Optional[bytearray] = None
        self._correction_just_exited = False
        
        # Event subscribers
        self._event_callbacks: List[Callable[[GameEvent, dict], None]] = []
        self._move_callbacks: List[Callable[[str], None]] = []
        self._key_callbacks: List[Callable[[board.Key], None]] = []
        self._takeback_callbacks: List[Callable[[], None]] = []
        
        # Database
        self._session = None
        self._game_db_id: Optional[int] = None
        
        # Game metadata
        self._game_info = {
            'source': '',
            'event': '',
            'site': '',
            'round': '',
            'white': '',
            'black': ''
        }
        
        # Thread
        self._game_thread: Optional[threading.Thread] = None
        
    def subscribe_event(self, callback: Callable[[GameEvent, dict], None]):
        """
        Subscribe to game events.
        
        Args:
            callback: Function that receives (event, data) where event is GameEvent
                     and data is a dict with event-specific information
        """
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)
    
    def unsubscribe_event(self, callback: Callable[[GameEvent, dict], None]):
        """Unsubscribe from game events."""
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)
    
    def subscribe_move(self, callback: Callable[[str], None]):
        """
        Subscribe to move events.
        
        Args:
            callback: Function that receives UCI move string (e.g., "e2e4")
        """
        if callback not in self._move_callbacks:
            self._move_callbacks.append(callback)
    
    def subscribe_key(self, callback: Callable[[board.Key], None]):
        """
        Subscribe to key press events.
        
        Args:
            callback: Function that receives board.Key enum value
        """
        if callback not in self._key_callbacks:
            self._key_callbacks.append(callback)
    
    def subscribe_takeback(self, callback: Callable[[], None]):
        """
        Subscribe to takeback events.
        
        Args:
            callback: Function called when a takeback is detected
        """
        if callback not in self._takeback_callbacks:
            self._takeback_callbacks.append(callback)
    
    def _notify_event(self, event: GameEvent, data: dict = None):
        """Notify all event subscribers."""
        if data is None:
            data = {}
        for callback in self._event_callbacks:
            try:
                callback(event, data)
            except Exception as e:
                log.error(f"[GameManager] Error in event callback: {e}")
                import traceback
                traceback.print_exc()
    
    def _notify_move(self, move: str):
        """Notify all move subscribers."""
        for callback in self._move_callbacks:
            try:
                callback(move)
            except Exception as e:
                log.error(f"[GameManager] Error in move callback: {e}")
                import traceback
                traceback.print_exc()
    
    def _notify_key(self, key: board.Key):
        """Notify all key subscribers."""
        for callback in self._key_callbacks:
            try:
                callback(key)
            except Exception as e:
                log.error(f"[GameManager] Error in key callback: {e}")
                import traceback
                traceback.print_exc()
    
    def _notify_takeback(self):
        """Notify all takeback subscribers."""
        for callback in self._takeback_callbacks:
            try:
                callback()
            except Exception as e:
                log.error(f"[GameManager] Error in takeback callback: {e}")
                import traceback
                traceback.print_exc()
    
    def set_game_info(self, source: str, event: str = "", site: str = "", 
                     round: str = "", white: str = "", black: str = ""):
        """
        Set game metadata for database logging.
        
        Args:
            source: Source identifier (e.g., "uci", "lichess")
            event: Event name
            site: Site name
            round: Round number
            white: White player name
            black: Black player name
        """
        self._game_info = {
            'source': source,
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
    
    def _uci_to_squares(self, uci_move: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Convert UCI move string to square indices.
        
        Args:
            uci_move: UCI move string (e.g., "e2e4")
        
        Returns:
            Tuple of (from_square, to_square) as integers (0-63), or (None, None) if invalid
        """
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return None, None
        try:
            from_sq = ((ord(uci_move[1:2]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[0:1]) - ord("a"))
            to_sq = ((ord(uci_move[3:4]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[2:3]) - ord("a"))
            return from_sq, to_sq
        except (IndexError, ValueError):
            return None, None
    
    def _validate_board_state(self, current: bytearray, expected: bytearray) -> bool:
        """
        Validate board state by comparing piece presence.
        
        Args:
            current: Current board state
            expected: Expected board state
        
        Returns:
            True if states match, False otherwise
        """
        if current is None or expected is None:
            return False
        if len(current) != BOARD_SIZE or len(expected) != BOARD_SIZE:
            return False
        return bytearray(current) == bytearray(expected)
    
    def _calculate_legal_squares(self, field: int) -> List[int]:
        """
        Calculate legal destination squares for a piece at the given field.
        
        Args:
            field: Source square index (0-63)
        
        Returns:
            List of legal destination square indices, including the source square
        """
        legal_squares = [field]  # Include source square
        for move in self._board.legal_moves:
            if move.from_square == field:
                legal_squares.append(move.to_square)
        return legal_squares
    
    def _provide_correction_guidance(self, current_state: bytearray, expected_state: bytearray):
        """
        Provide LED guidance to correct misplaced pieces using Hungarian algorithm.
        
        Args:
            current_state: Current board state
            expected_state: Expected board state
        """
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
        missing_origins = []
        wrong_locations = []
        
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
            n_wrong = len(wrong_locations)
            n_missing = len(missing_origins)
            
            if n_wrong == 1 and n_missing == 1:
                from_idx = wrong_locations[0]
                to_idx = missing_origins[0]
            else:
                # Create cost matrix based on Manhattan distances
                costs = np.zeros((n_wrong, n_missing))
                for i, wl in enumerate(wrong_locations):
                    for j, mo in enumerate(missing_origins):
                        costs[i, j] = _dist(wl, mo)
                
                # Find optimal assignment
                row_ind, col_ind = linear_sum_assignment(costs)
                
                # Guide the first pair
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
        log.warning(f"[GameManager] Entered correction mode (forced_move={self._forced_move})")
    
    def _exit_correction_mode(self):
        """Exit correction mode and resume normal game flow."""
        self._correction_mode = False
        self._correction_expected_state = None
        self._correction_just_exited = True
        log.warning("[GameManager] Exited correction mode")
        
        # Reset move state variables
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
        """
        Check if a takeback is in progress by comparing current state to previous state.
        
        Returns:
            True if takeback detected, False otherwise
        """
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
                    log.error(f"[GameManager] Error removing move from database: {e}")
            
            # Pop move from board
            self._board.pop()
            paths.write_fen_log(self._board.fen())
            board.beep(board.SOUND_GENERAL)
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            current = bytearray(board.getChessState())
            if not self._validate_board_state(current, self._board_states[-1] if self._board_states else None):
                log.info("[GameManager] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            self._notify_takeback()
            return True
        
        return False
    
    def _handle_promotion(self, field: int, piece_name: str, forced: bool = False) -> str:
        """
        Handle pawn promotion by prompting user for piece choice.
        
        Args:
            field: Target square index
            piece_name: Piece symbol ("P" for white, "p" for black)
            forced: Whether this is a forced move (no user prompt)
        
        Returns:
            Promotion piece suffix ("q", "r", "b", "n") or empty string
        """
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
                return "q"  # Default to queen on timeout/other
        return ""
    
    def _reset_move_state(self):
        """Reset move-related state variables after a move is completed."""
        self._legal_squares = []
        self._source_square = None
        self._opponent_source_square = None
        board.ledsOff()
    
    def _key_callback(self, key: board.Key):
        """Handle key press events."""
        self._notify_key(key)
    
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
        
        log.info(f"[GameManager] piece_event={'LIFT' if lift else 'PLACE'} field={field} fieldname={field_name} color_at={'White' if piece_color == chess.WHITE else 'Black' if piece_color == chess.BLACK else 'None'}")
        
        # Check if piece color matches current turn (handle None case for empty squares)
        if piece_color is None:
            # Empty square - can't determine if it's valid piece
            if place:
                # On place, check if we have a source square (move in progress)
                if self._source_square is not None:
                    # This is a valid move placement
                    pass
                else:
                    # No source square, might be stale event
                    if not self._correction_just_exited:
                        log.info(f"[GameManager] Ignoring PLACE event on empty square {field} (no source square)")
                        return
            else:
                # Lift from empty square - shouldn't happen but ignore it
                log.warning(f"[GameManager] LIFT event on empty square {field}")
                return
        
        vpiece = (self._board.turn == chess.WHITE) == (piece_color == chess.WHITE)
        
        # Handle lift events
        if lift:
            self._correction_just_exited = False
            
            if vpiece and self._source_square is None:
                # Generate legal squares for this piece
                self._legal_squares = self._calculate_legal_squares(field)
                self._source_square = field
                log.info(f"[GameManager] Lifted piece at {field_name}, legal squares: {[chess.square_name(sq) for sq in self._legal_squares]}")
            
            # Track opposing side lifts
            if not vpiece:
                self._opponent_source_square = field
                log.info(f"[GameManager] Opponent piece lifted at {field_name}")
        
        # Handle opponent piece placement back
        if place and not vpiece and self._opponent_source_square is not None and field == self._opponent_source_square:
            board.ledsOff()
            self._opponent_source_square = None
            log.info(f"[GameManager] Opponent piece placed back at {field_name}")
            return
        
        # Handle forced move
        if self._forced_move_active and lift and vpiece:
            if field_name != self._forced_move[0:2]:
                # Wrong piece lifted for forced move
                self._legal_squares = [field]
                log.warning(f"[GameManager] Wrong piece lifted for forced move. Expected {self._forced_move[0:2]}, got {field_name}")
            else:
                # Correct piece, limit legal squares to target
                target = self._forced_move[2:4]
                target_sq = chess.parse_square(target)
                self._legal_squares = [target_sq]
                log.info(f"[GameManager] Correct piece lifted for forced move {self._forced_move}")
        
        # Ignore stale PLACE events without corresponding LIFT (but allow if we have source square)
        if place and self._source_square is None and self._opponent_source_square is None:
            if self._correction_just_exited:
                # Ignore stale events immediately after correction exit
                if not (self._forced_move_active and self._forced_move and len(self._forced_move) >= MIN_UCI_MOVE_LENGTH):
                    log.info(f"[GameManager] Ignoring stale PLACE event after correction exit for field {field}")
                    self._correction_just_exited = False
                    return
            else:
                log.info(f"[GameManager] Ignoring stale PLACE event for field {field} (no corresponding LIFT, source_square={self._source_square})")
                return
        
        # Handle placement events
        if place:
            # Ensure we have a board state for validation
            if not self._board_states:
                log.warning("[GameManager] No board states available, collecting current state")
                current_state = bytearray(board.getChessState())
                if len(current_state) == BOARD_SIZE:
                    self._board_states.append(current_state)
            
            # Check if we have a source square (move in progress)
            if self._source_square is None:
                # No source square - this shouldn't happen if we got past the stale event check
                log.warning(f"[GameManager] PLACE event without source square at {field_name}")
                return
            
            # Check if placement is legal
            if field not in self._legal_squares:
                board.beep(board.SOUND_WRONG_MOVE)
                log.warning(f"[GameManager] Piece placed on illegal square {field_name}. Legal squares: {[chess.square_name(sq) for sq in self._legal_squares]}")
                is_takeback = self._check_takeback()
                if not is_takeback:
                    self._enter_correction_mode()
                    current_state = bytearray(board.getChessState())
                    if self._board_states:
                        self._provide_correction_guidance(current_state, self._board_states[-1])
                return
            
            # Legal placement - process the move
            log.info(f"[GameManager] Making move")
            if field == self._source_square:
                # Piece placed back on source
                board.ledsOff()
                self._source_square = None
                self._legal_squares = []
            else:
                # Valid move
                from_name = chess.square_name(self._source_square)
                to_name = chess.square_name(field)
                piece_name = str(self._board.piece_at(self._source_square))
                promotion_suffix = self._handle_promotion(field, piece_name, self._forced_move_active)
                
                if self._forced_move_active:
                    mv = self._forced_move
                else:
                    mv = from_name + to_name + promotion_suffix
                
                # Make the move
                try:
                    move = chess.Move.from_uci(mv)
                    self._board.push(move)
                    paths.write_fen_log(self._board.fen())
                    
                    # Log to database
                    if self._session and self._game_db_id:
                        gamemove = models.GameMove(
                            gameid=self._game_db_id,
                            move=mv,
                            fen=str(self._board.fen())
                        )
                        self._session.add(gamemove)
                        self._session.commit()
                    
                    # Collect board state
                    self._board_states.append(bytearray(board.getChessState()))
                    
                    # Reset move state
                    self._reset_move_state()
                    self._forced_move_active = False
                    self._forced_move = None
                    
                    # Notify move
                    self._notify_move(mv)
                    board.beep(board.SOUND_GENERAL)
                    board.led(field)
                    
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
                        
                        # Update database
                        if self._session and self._game_db_id:
                            try:
                                game = self._session.query(models.Game).filter(
                                    models.Game.id == self._game_db_id
                                ).first()
                                if game:
                                    game.result = result_str
                                    self._session.commit()
                            except Exception as e:
                                log.error(f"[GameManager] Error updating game result: {e}")
                        
                        self._notify_event(GameEvent.GAME_OVER, {
                            'result': result_str,
                            'termination': termination
                        })
                
                except ValueError as e:
                    log.error(f"[GameManager] Invalid move: {mv}, error: {e}")
                    board.beep(board.SOUND_WRONG_MOVE)
                    self._enter_correction_mode()
    
    def _correction_field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """
        Handle field events during correction mode.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63)
            time_in_seconds: Time of the event
        """
        current_state = bytearray(board.getChessState())
        
        # Check if board is in starting position (new game detection)
        if len(current_state) == BOARD_SIZE:
            if bytearray(current_state) == STARTING_STATE:
                log.info("[GameManager] Starting position detected while in correction mode - triggering new game")
                board.ledsOff()
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                self.reset_game()
                return
        
        # Check if board now matches expected state
        if self._validate_board_state(current_state, self._correction_expected_state):
            log.info("[GameManager] Board corrected, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            return
        
        # Still incorrect, update guidance
        self._provide_correction_guidance(current_state, self._correction_expected_state)
    
    def reset_game(self):
        """Reset the game to starting position."""
        try:
            log.info("[GameManager] Resetting game to starting position")
            
            # Reset move state
            self._reset_move_state()
            self._forced_move_active = False
            self._forced_move = None
            
            # Reset board
            self._board.reset()
            paths.write_fen_log(self._board.fen())
            
            board.beep(board.SOUND_GENERAL)
            time.sleep(0.3)
            board.beep(board.SOUND_GENERAL)
            board.ledsOff()
            
            # Collect initial board state (ensure we always have at least one state)
            current_state = bytearray(board.getChessState())
            if len(current_state) == BOARD_SIZE:
                self._board_states = [current_state]
                log.info("[GameManager] Collected board state after reset")
            else:
                log.warning(f"[GameManager] Invalid board state length: {len(current_state)}")
                # Keep existing state if available, otherwise use starting state
                if not self._board_states:
                    self._board_states = [STARTING_STATE]
            
            # Notify new game
            self._notify_event(GameEvent.NEW_GAME)
            self._notify_event(GameEvent.WHITE_TURN)
            
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
                    
                    # Get game ID
                    from sqlalchemy import func
                    self._game_db_id = self._session.query(func.max(models.Game.id)).scalar()
                    
                    # Log initial position
                    gamemove = models.GameMove(
                        gameid=self._game_db_id,
                        move='',
                        fen=str(self._board.fen())
                    )
                    self._session.add(gamemove)
                    self._session.commit()
                except Exception as e:
                    log.error(f"[GameManager] Error logging new game: {e}")
        
        except Exception as e:
            log.error(f"[GameManager] Error resetting game: {e}")
            import traceback
            traceback.print_exc()
    
    def _game_thread(self):
        """Main game thread that subscribes to board events."""
        board.ledsOff()
        log.info("[GameManager] Subscribing to board events")
        
        # Collect initial board state BEFORE subscribing to events
        # This ensures we have a baseline for move detection
        try:
            initial_state = bytearray(board.getChessState())
            if len(initial_state) == BOARD_SIZE:
                self._board_states.append(initial_state)
                log.info("[GameManager] Collected initial board state")
        except Exception as e:
            log.warning(f"[GameManager] Could not collect initial board state: {e}")
        
        try:
            board.subscribeEvents(self._key_callback, self._field_callback)
        except Exception as e:
            log.error(f"[GameManager] Error subscribing to events: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # Small delay to ensure board is ready
        time.sleep(0.2)
        
        # Check for starting position and reset if needed
        current_state = bytearray(board.getChessState())
        if len(current_state) == BOARD_SIZE and bytearray(current_state) == STARTING_STATE:
            log.info("[GameManager] Starting position detected, resetting game")
            self.reset_game()
        else:
            # Not in starting position - still need to ensure we have a board state
            if not self._board_states:
                log.warning("[GameManager] No board state collected, collecting current state")
                self._board_states.append(current_state)
        
        # Main loop
        while not self._kill_event.is_set():
            time.sleep(0.1)
    
    def start(self):
        """Start the game manager."""
        if self._running:
            log.warning("[GameManager] Already running")
            return
        
        # Initialize database session
        try:
            from sqlalchemy.orm import sessionmaker
            Session = sessionmaker(bind=models.engine)
            self._session = Session()
        except Exception as e:
            log.error(f"[GameManager] Error creating database session: {e}")
        
        # Set source from calling file
        try:
            self._game_info['source'] = inspect.getsourcefile(sys._getframe(1))
        except:
            self._game_info['source'] = "unknown"
        
        self._running = True
        self._kill_event.clear()
        
        # Start game thread
        self._game_thread = threading.Thread(target=self._game_thread, daemon=True)
        self._game_thread.start()
        
        log.info("[GameManager] Started")
    
    def stop(self):
        """Stop the game manager."""
        if not self._running:
            return
        
        log.info("[GameManager] Stopping")
        self._kill_event.set()
        self._running = False
        
        board.ledsOff()
        
        # Clean up database session
        if self._session:
            try:
                self._session.close()
                self._session = None
            except Exception as e:
                log.error(f"[GameManager] Error closing database session: {e}")
        
        if self._game_thread:
            self._game_thread.join(timeout=2.0)
        
        log.info("[GameManager] Stopped")
    
    def set_forced_move(self, uci_move: str, forced: bool = True):
        """
        Set a forced move (computer move) that the player must make.
        
        Args:
            uci_move: UCI move string (e.g., "e2e4")
            forced: Whether this move is forced (default True)
        """
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return
        
        self._forced_move = uci_move
        self._forced_move_active = forced
        
        # Light up LEDs to indicate the move
        from_sq, to_sq = self._uci_to_squares(uci_move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
            log.info(f"[GameManager] Set forced move: {uci_move}")
    
    def clear_forced_move(self):
        """Clear any pending forced move."""
        self._forced_move = None
        self._forced_move_active = False
        board.ledsOff()
    
    def resign(self, side: int):
        """
        Resign the game.
        
        Args:
            side: 1 for white, 2 for black
        """
        result_str = "0-1" if side == 1 else "1-0"
        
        # Update database
        if self._session and self._game_db_id:
            try:
                game = self._session.query(models.Game).filter(
                    models.Game.id == self._game_db_id
                ).first()
                if game:
                    game.result = result_str
                    self._session.commit()
            except Exception as e:
                log.error(f"[GameManager] Error updating resignation: {e}")
        
        self._notify_event(GameEvent.RESIGN, {'result': result_str})
    
    def draw(self):
        """Offer/accept a draw."""
        result_str = "1/2-1/2"
        
        # Update database
        if self._session and self._game_db_id:
            try:
                game = self._session.query(models.Game).filter(
                    models.Game.id == self._game_db_id
                ).first()
                if game:
                    game.result = result_str
                    self._session.commit()
            except Exception as e:
                log.error(f"[GameManager] Error updating draw: {e}")
        
        self._notify_event(GameEvent.REQUEST_DRAW, {'result': result_str})

