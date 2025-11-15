"""
Chess Game Manager

Provides complete chess game state management with automatic turn tracking,
event-driven notifications, hardware abstraction, and misplaced piece guidance.

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
import inspect
import sys
import threading
import time
from typing import Optional, Callable, List, Tuple
from enum import IntEnum
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import func
from scipy.optimize import linear_sum_assignment
import numpy as np

from DGTCentaurMods.board import board
from DGTCentaurMods.db import models
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log


# Event constants
class GameEvent(IntEnum):
    """Game event types."""
    NEW_GAME = 1
    BLACK_TURN = 2
    WHITE_TURN = 3
    REQUEST_DRAW = 4
    RESIGN_GAME = 5


# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
INVALID_SQUARE = -1

# Move constants
MIN_UCI_MOVE_LENGTH = 4

# Game constants
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class ChessGameManager:
    """
    Manages chess game state with automatic turn tracking and event-driven notifications.
    
    Provides hardware abstraction and misplaced piece guidance that works even
    when misplaced pieces occur before opponent moves are completed.
    """
    
    def __init__(self):
        """Initialize the chess game manager."""
        # Chess board state
        self._board = chess.Board()
        self._board_states: List[bytearray] = []
        self._starting_state = self._compute_starting_state()
        
        # Move tracking state
        self._source_square: int = INVALID_SQUARE
        self._other_source_square: int = INVALID_SQUARE  # Opponent piece tracking
        self._legal_squares: List[int] = []
        self._pending_computer_move: Optional[str] = None
        self._force_move: bool = False
        
        # Correction mode state
        self._correction_mode: bool = False
        self._correction_expected_state: Optional[bytearray] = None
        self._pending_opponent_move_after_correction: Optional[str] = None
        
        # Game state
        self._game_db_id: int = -1
        self._session: Optional[Session] = None
        self._source: str = ""
        self._showing_promotion: bool = False
        
        # Game metadata
        self._game_info_event: str = ""
        self._game_info_site: str = ""
        self._game_info_round: str = ""
        self._game_info_white: str = ""
        self._game_info_black: str = ""
        
        # Callbacks
        self._event_callback: Optional[Callable[[GameEvent], None]] = None
        self._move_callback: Optional[Callable[[str], None]] = None
        self._key_callback: Optional[Callable] = None
        self._takeback_callback: Optional[Callable[[], None]] = None
        
        # Threading
        self._running: bool = False
        self._game_thread: Optional[threading.Thread] = None
    
    def _compute_starting_state(self) -> bytearray:
        """Compute the starting board state bytearray."""
        state = bytearray(BOARD_SIZE)
        # White pieces (ranks 1-2, squares 0-15)
        for i in range(16):
            state[i] = 1
        # Black pieces (ranks 7-8, squares 48-63)
        for i in range(48, 64):
            state[i] = 1
        return state
    
    def subscribe(
        self,
        event_callback: Callable[[GameEvent], None],
        move_callback: Callable[[str], None],
        key_callback: Optional[Callable] = None,
        takeback_callback: Optional[Callable[[], None]] = None
    ) -> None:
        """
        Subscribe to game manager events.
        
        Args:
            event_callback: Called with GameEvent when game events occur
            move_callback: Called with UCI move string when valid moves are made
            key_callback: Optional callback for key presses
            takeback_callback: Optional callback for takeback events
        """
        self._event_callback = event_callback
        self._move_callback = move_callback
        self._key_callback = key_callback
        self._takeback_callback = takeback_callback
        
        # Initialize board states
        self._board_states = []
        self._collect_board_state()
        
        # Get source file for database logging
        self._source = inspect.getsourcefile(sys._getframe(1)) or ""
        
        # Create database session
        SessionFactory = sessionmaker(bind=models.engine)
        self._session = SessionFactory()
        
        # Start game thread
        self._running = True
        self._game_thread = threading.Thread(target=self._game_thread_loop, daemon=True)
        self._game_thread.start()
    
    def unsubscribe(self) -> None:
        """Unsubscribe from game manager and clean up resources."""
        self._running = False
        board.ledsOff()
        
        # Clean up database session
        if self._session is not None:
            try:
                self._session.close()
                self._session = None
            except Exception:
                self._session = None
    
    def set_game_info(
        self,
        event: str = "",
        site: str = "",
        round: str = "",
        white: str = "",
        black: str = ""
    ) -> None:
        """
        Set game metadata for database logging.
        
        Args:
            event: Event name
            site: Site name
            round: Round number
            white: White player name
            black: Black player name
        """
        self._game_info_event = event
        self._game_info_site = site
        self._game_info_round = round
        self._game_info_white = white
        self._game_info_black = black
    
    def set_computer_move(self, move: str, forced: bool = True) -> None:
        """
        Set a computer move that the player is expected to make.
        
        Args:
            move: UCI move string (e.g., "e2e4", "g7g8q")
            forced: Whether this is a forced move (LEDs will indicate it)
        """
        if len(move) < MIN_UCI_MOVE_LENGTH:
            return
        
        self._pending_computer_move = move
        self._force_move = forced
        
        # If not in correction mode, light up LEDs immediately
        if not self._correction_mode:
            from_sq, to_sq = self._uci_to_squares(move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
    
    def clear_computer_move(self) -> None:
        """Clear any pending computer move."""
        self._pending_computer_move = None
        self._force_move = False
    
    def resign_game(self, side_resigning: int) -> None:
        """
        Handle game resignation.
        
        Args:
            side_resigning: 1 for white, 2 for black
        """
        result_str = "0-1" if side_resigning == 1 else "1-0"
        self._update_game_result(result_str, "Termination.RESIGN")
    
    def draw_game(self) -> None:
        """Handle game draw."""
        self._update_game_result("1/2-1/2", "Termination.DRAW")
    
    def get_result(self) -> str:
        """
        Get the result of the last game from the database.
        
        Returns:
            Result string or "Unknown" if not found
        """
        if self._session is None:
            return "Unknown"
        
        from sqlalchemy import select
        gamedata = self._session.execute(
            select(
                models.Game.created_at,
                models.Game.source,
                models.Game.event,
                models.Game.site,
                models.Game.round,
                models.Game.white,
                models.Game.black,
                models.Game.result,
                models.Game.id
            ).order_by(models.Game.id.desc())
        ).first()
        
        if gamedata is not None:
            return str(gamedata.result)
        return "Unknown"
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self._board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self._board.fen()
    
    def reset_move_state(self) -> None:
        """Reset all move-related state variables."""
        self._force_move = False
        self._pending_computer_move = None
        self._source_square = INVALID_SQUARE
        self._legal_squares = []
        self._other_source_square = INVALID_SQUARE
    
    def _game_thread_loop(self) -> None:
        """Main game thread loop that subscribes to board events."""
        board.ledsOff()
        log.info("[games.manager] Subscribing to board events")
        
        try:
            board.subscribeEvents(self._key_callback_wrapper, self._field_callback_wrapper)
        except Exception as e:
            log.error(f"[games.manager] Error subscribing to events: {e}")
            import traceback
            traceback.print_exc()
            return
        
        while self._running:
            time.sleep(0.1)
    
    def _key_callback_wrapper(self, key_pressed) -> None:
        """Wrapper for key callback."""
        if self._key_callback is not None:
            self._key_callback(key_pressed)
    
    def _field_callback_wrapper(self, piece_event: int, field: int, time_in_seconds: float) -> None:
        """
        Wrapper for field callback that handles correction mode interception.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63)
            time_in_seconds: Time of the event
        """
        # Check for starting position (new game detection)
        current_state = board.getChessState()
        if current_state is not None and len(current_state) == BOARD_SIZE:
            if bytearray(current_state) == self._starting_state:
                log.info("[games.manager] Starting position detected - triggering new game")
                board.ledsOff()
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                self._reset_game()
                return
        
        # Handle correction mode
        if self._correction_mode:
            self._handle_correction_mode_event(piece_event, field, current_state)
            return
        
        # Normal game flow
        self._field_callback(piece_event, field, time_in_seconds)
    
    def _handle_correction_mode_event(
        self,
        piece_event: int,
        field: int,
        current_state: Optional[bytearray]
    ) -> None:
        """
        Handle events during correction mode.
        
        Provides guidance for misplaced pieces and exits when board is correct.
        Also handles opponent move guidance even if misplaced pieces occur.
        """
        if current_state is None or self._correction_expected_state is None:
            return
        
        # Check if board is now correct
        if self._validate_board_state(current_state, self._correction_expected_state):
            log.info("[games.manager] Board corrected, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            
            # If there was a pending opponent move, restore it
            if self._pending_opponent_move_after_correction:
                self.set_computer_move(self._pending_opponent_move_after_correction, forced=True)
                self._pending_opponent_move_after_correction = None
            return
        
        # Still incorrect, update guidance
        self._provide_correction_guidance(current_state, self._correction_expected_state)
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float) -> None:
        """
        Handle field events (piece lift/place) in normal game flow.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63)
            time_in_seconds: Time of the event
        """
        field_name = chess.square_name(field)
        piece_color = self._board.color_at(field)
        
        log.info(
            f"[games.manager] piece_event={'LIFT' if piece_event == 0 else 'PLACE'} "
            f"field={field} ({field_name}) color={'White' if piece_color else 'Black'}"
        )
        
        lift = (piece_event == 0)
        place = (piece_event == 1)
        
        # Determine if piece belongs to current player
        is_current_player_piece = (
            (self._board.turn == chess.WHITE) == (piece_color == True)
        )
        
        # Handle piece lift
        if lift:
            if is_current_player_piece:
                # Current player's piece lifted
                if field not in self._legal_squares and self._source_square < 0:
                    # Calculate legal moves for this piece
                    self._legal_squares = self._calculate_legal_squares(field)
                    self._source_square = field
                
                # Handle forced move
                if self._force_move and self._pending_computer_move:
                    if field_name != self._pending_computer_move[0:2]:
                        # Wrong piece lifted for forced move
                        self._legal_squares = [field]
                    else:
                        # Correct piece, limit to target square
                        target = self._pending_computer_move[2:4]
                        target_sq = chess.parse_square(target)
                        self._legal_squares = [target_sq]
            else:
                # Opponent piece lifted - track it
                self._other_source_square = field
        
        # Handle piece place
        if place:
            # If opponent piece placed back on original square, clear tracking
            if not is_current_player_piece and self._other_source_square >= 0:
                if field == self._other_source_square:
                    board.ledsOff()
                    self._other_source_square = INVALID_SQUARE
                    return
            
            # Ignore place events without corresponding lift
            if self._source_square < 0 and self._other_source_square < 0:
                log.debug(f"[games.manager] Ignoring stale PLACE event for field {field}")
                return
            
            # Check if move is legal
            if is_current_player_piece and field in self._legal_squares:
                if field == self._source_square:
                    # Piece placed back on source square
                    board.ledsOff()
                    self._source_square = INVALID_SQUARE
                    self._legal_squares = []
                else:
                    # Execute the move
                    self._execute_move(field)
            else:
                # Illegal move
                board.beep(board.SOUND_WRONG_MOVE)
                log.warning(f"[games.manager] Illegal move: piece placed on {field}")
                
                # Check for takeback
                if not self._check_takeback():
                    # Enter correction mode
                    self._enter_correction_mode()
                    # If there's a pending opponent move, save it for after correction
                    if self._pending_computer_move:
                        self._pending_opponent_move_after_correction = self._pending_computer_move
                        self.clear_computer_move()
    
    def _execute_move(self, target_square: int) -> None:
        """
        Execute a valid move.
        
        Args:
            target_square: Target square index (0-63)
        """
        from_name = chess.square_name(self._source_square)
        to_name = chess.square_name(target_square)
        piece_name = str(self._board.piece_at(self._source_square))
        
        # Handle promotion
        promotion_suffix = self._handle_promotion(target_square, piece_name)
        
        # Determine move string
        if self._force_move and self._pending_computer_move:
            move_str = self._pending_computer_move
        else:
            move_str = from_name + to_name + promotion_suffix
        
        # Make the move
        self._board.push(chess.Move.from_uci(move_str))
        paths.write_fen_log(self._board.fen())
        
        # Save to database
        if self._session is not None:
            gamemove = models.GameMove(
                gameid=self._game_db_id,
                move=move_str,
                fen=str(self._board.fen())
            )
            self._session.add(gamemove)
            self._session.commit()
        
        # Collect board state
        self._collect_board_state()
        self.reset_move_state()
        
        # Notify callback
        if self._move_callback is not None:
            self._move_callback(move_str)
        
        board.beep(board.SOUND_GENERAL)
        board.led(target_square)
        
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
    
    def _handle_promotion(self, field: int, piece_name: str) -> str:
        """
        Handle pawn promotion by prompting user for piece choice.
        
        Args:
            field: Target square index
            piece_name: Piece symbol ("P" for white, "p" for black)
        
        Returns:
            Promotion piece suffix ("q", "r", "b", "n") or empty string
        """
        is_white_promotion = (
            (field // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
        )
        is_black_promotion = (
            (field // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
        )
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        
        # For forced moves, default to queen
        if self._force_move:
            return "q"
        
        # Prompt user for promotion choice
        from DGTCentaurMods.display import epaper
        screen_back = epaper.epaperbuffer.copy()
        self._showing_promotion = True
        epaper.promotionOptions(13)
        
        key = board.wait_for_key_up(timeout=60)
        self._showing_promotion = False
        epaper.epaperbuffer = screen_back.copy()
        
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
    
    def _check_takeback(self) -> bool:
        """
        Check if current board state matches previous state (takeback detection).
        
        Returns:
            True if takeback detected, False otherwise
        """
        if self._takeback_callback is None or len(self._board_states) <= 1:
            return False
        
        current_state = board.getChessState()
        previous_state = self._board_states[-2]
        
        if self._validate_board_state(current_state, previous_state):
            log.info("[games.manager] Takeback detected")
            board.ledsOff()
            self._board_states = self._board_states[:-1]
            
            # Remove last move from database
            if self._session is not None:
                last_move = self._session.query(models.GameMove).order_by(
                    models.GameMove.id.desc()
                ).first()
                if last_move is not None:
                    self._session.delete(last_move)
                    self._session.commit()
            
            self._board.pop()
            paths.write_fen_log(self._board.fen())
            board.beep(board.SOUND_GENERAL)
            
            if self._takeback_callback is not None:
                self._takeback_callback()
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            current = board.getChessState()
            if not self._validate_board_state(current, self._board_states[-1] if self._board_states else None):
                log.info("[games.manager] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            return True
        
        return False
    
    def _enter_correction_mode(self) -> None:
        """Enter correction mode to guide user in fixing board state."""
        self._correction_mode = True
        self._correction_expected_state = (
            self._board_states[-1] if self._board_states else None
        )
        log.warning(
            f"[games.manager] Entered correction mode "
            f"(force_move={self._force_move}, pending_move={self._pending_computer_move})"
        )
    
    def _exit_correction_mode(self) -> None:
        """Exit correction mode and resume normal game flow."""
        self._correction_mode = False
        self._correction_expected_state = None
        log.info("[games.manager] Exited correction mode")
        
        # Reset move state
        self._source_square = INVALID_SQUARE
        self._legal_squares = []
        self._other_source_square = INVALID_SQUARE
    
    def _provide_correction_guidance(
        self,
        current_state: bytearray,
        expected_state: bytearray
    ) -> None:
        """
        Provide LED guidance to correct misplaced pieces using Hungarian algorithm.
        
        Args:
            current_state: Current board state from getChessState()
            expected_state: Expected board state
        """
        if current_state is None or expected_state is None:
            return
        
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return
        
        # Helper functions for distance calculation
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
            board.ledsOff()
            return
        
        log.warning(
            f"[games.manager] Found {len(wrong_locations)} wrong pieces, "
            f"{len(missing_origins)} missing pieces"
        )
        
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
            log.warning(
                f"[games.manager] Guiding piece from {chess.square_name(from_idx)} "
                f"to {chess.square_name(to_idx)}"
            )
        else:
            # Only pieces missing or only extra pieces
            if len(missing_origins) > 0:
                board.ledsOff()
                for idx in missing_origins:
                    board.led(idx, intensity=5)
                log.warning(
                    f"[games.manager] Pieces missing at: "
                    f"{[chess.square_name(sq) for sq in missing_origins]}"
                )
            elif len(wrong_locations) > 0:
                board.ledsOff()
                for idx in wrong_locations:
                    board.led(idx, intensity=5)
                log.warning(
                    f"[games.manager] Extra pieces at: "
                    f"{[chess.square_name(sq) for sq in wrong_locations]}"
                )
    
    def _collect_board_state(self) -> None:
        """Collect and store the current board state."""
        log.debug("[games.manager] Collecting board state")
        self._board_states.append(bytearray(board.getChessState()))
    
    def _validate_board_state(
        self,
        current_state: Optional[bytearray],
        expected_state: Optional[bytearray]
    ) -> bool:
        """
        Validate board state by comparing piece presence.
        
        Args:
            current_state: Current board state from getChessState()
            expected_state: Expected board state to compare against
        
        Returns:
            True if states match, False otherwise
        """
        if current_state is None or expected_state is None:
            return False
        
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return False
        
        return bytearray(current_state) == bytearray(expected_state)
    
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
        
        from_num = (
            ((ord(uci_move[1:2]) - ord("1")) * BOARD_WIDTH) +
            (ord(uci_move[0:1]) - ord("a"))
        )
        to_num = (
            ((ord(uci_move[3:4]) - ord("1")) * BOARD_WIDTH) +
            (ord(uci_move[2:3]) - ord("a"))
        )
        return from_num, to_num
    
    def _switch_turn(self) -> None:
        """Switch turn and trigger appropriate event callback."""
        if self._event_callback is not None:
            if self._board.turn == chess.WHITE:
                self._event_callback(GameEvent.WHITE_TURN)
            else:
                self._event_callback(GameEvent.BLACK_TURN)
    
    def _update_game_result(self, result_str: str, termination: str) -> None:
        """
        Update game result in database and trigger event callback.
        
        Args:
            result_str: Result string (e.g., "1-0", "0-1", "1/2-1/2")
            termination: Termination string for event callback
        """
        if self._session is not None:
            game = self._session.query(models.Game).filter(
                models.Game.id == self._game_db_id
            ).first()
            if game is not None:
                game.result = result_str
                self._session.flush()
                self._session.commit()
            else:
                log.warning(
                    f"[games.manager] Game with id {self._game_db_id} not found "
                    "in database, cannot update result"
                )
        
        # Always trigger callback, even if DB update failed
        if self._event_callback is not None:
            self._event_callback(termination)
    
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
    
    def _reset_game(self) -> None:
        """Reset the game to starting position."""
        try:
            log.info("[games.manager] Resetting game to starting position")
            self.reset_move_state()
            self._board.reset()
            paths.write_fen_log(self._board.fen())
            
            board.beep(board.SOUND_GENERAL)
            time.sleep(0.3)
            board.beep(board.SOUND_GENERAL)
            board.ledsOff()
            
            if self._event_callback is not None:
                self._event_callback(GameEvent.NEW_GAME)
                self._event_callback(GameEvent.WHITE_TURN)
            
            # Log a new game in the database
            if self._session is not None:
                game = models.Game(
                    source=self._source,
                    event=self._game_info_event,
                    site=self._game_info_site,
                    round=self._game_info_round,
                    white=self._game_info_white,
                    black=self._game_info_black
                )
                log.info(f"[games.manager] Created new game: {game}")
                self._session.add(game)
                self._session.commit()
                
                # Get the max game id as that is this game id
                self._game_db_id = self._session.query(func.max(models.Game.id)).scalar()
                
                # Make an entry in GameMove for this start state
                gamemove = models.GameMove(
                    gameid=self._game_db_id,
                    move='',
                    fen=str(self._board.fen())
                )
                self._session.add(gamemove)
                self._session.commit()
            
            self._board_states = []
            self._collect_board_state()
        except Exception as e:
            log.error(f"[games.manager] Error resetting game: {e}")
            import traceback
            traceback.print_exc()

