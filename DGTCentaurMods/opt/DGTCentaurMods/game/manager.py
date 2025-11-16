"""
Chess Game Manager

Manages chess game state, board events, move validation, and game persistence.
Provides a clean interface for chess game management with proper state encapsulation.

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
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import func
from scipy.optimize import linear_sum_assignment
import numpy as np

from DGTCentaurMods.board import board
from DGTCentaurMods.display import epaper
from DGTCentaurMods.db import models
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log, logging


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
INVALID_SQUARE = -1

# Clock constants
SECONDS_PER_MINUTE = 60
CLOCK_DECREMENT_SECONDS = 2
CLOCK_DISPLAY_LINE = 13
PROMOTION_DISPLAY_LINE = 13

# Move constants
MIN_UCI_MOVE_LENGTH = 4

# Game constants
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class ChessGameManager:
    """
    Manages chess game state, board events, move validation, and persistence.
    
    Encapsulates all game state and provides a clean interface for managing
    chess games with proper separation of concerns.
    """
    
    def __init__(self):
        """Initialize the chess game manager with default state."""
        # Chess board state
        self._board = chess.Board()
        self._board_states: List[bytearray] = []
        self._starting_state = self._compute_starting_state()
        
        # Move state
        self._source_square: int = INVALID_SQUARE
        self._other_source_square: int = INVALID_SQUARE
        self._legal_squares: List[int] = []
        self._computer_move: str = ""
        self._force_move: bool = False
        
        # Correction mode state
        self._correction_mode: bool = False
        self._correction_expected_state: Optional[bytearray] = None
        self._correction_just_exited: bool = False
        
        # Game state
        self._game_db_id: int = -1
        self._session: Optional[Session] = None
        self._source: str = ""
        self._showing_promotion: bool = False
        
        # Game info
        self._game_info_event: str = ""
        self._game_info_site: str = ""
        self._game_info_round: str = ""
        self._game_info_white: str = ""
        self._game_info_black: str = ""
        
        # Menu state
        self._in_menu: int = 0
        
        # Callbacks
        self._event_callback: Optional[Callable] = None
        self._move_callback: Optional[Callable] = None
        self._key_callback: Optional[Callable] = None
        self._takeback_callback: Optional[Callable] = None
        
        # Threading
        self._kill_flag: bool = False
        self._game_thread: Optional[threading.Thread] = None
        self._clock_thread: Optional[threading.Thread] = None
        
        # Clock state
        self._white_time: int = 0
        self._black_time: int = 0
    
    def _compute_starting_state(self) -> bytearray:
        """Compute the starting board state bytearray."""
        state = bytearray(BOARD_SIZE)
        # White pieces (ranks 1-2)
        for i in range(16):
            state[i] = 1
        # Black pieces (ranks 7-8)
        for i in range(48, 64):
            state[i] = 1
        return state
    
    def subscribe(
        self,
        event_callback: Callable,
        move_callback: Callable,
        key_callback: Callable,
        takeback_callback: Optional[Callable] = None
    ) -> None:
        """
        Subscribe to game manager events.
        
        Args:
            event_callback: Callback for game events (NEW_GAME, TURN, etc.)
            move_callback: Callback for valid moves made
            key_callback: Callback for key presses
            takeback_callback: Optional callback for takeback events
        """
        self._event_callback = event_callback
        self._move_callback = move_callback
        self._key_callback = key_callback
        self._takeback_callback = takeback_callback
        
        # Initialize board states
        self._board_states = []
        self._collect_board_state()
        
        # Get source file
        self._source = inspect.getsourcefile(sys._getframe(1))
        
        # Create database session
        SessionFactory = sessionmaker(bind=models.engine)
        self._session = SessionFactory()
        
        # Start game thread
        self._kill_flag = False
        self._game_thread = threading.Thread(target=self._game_thread_loop, daemon=True)
        self._game_thread.start()
    
    def unsubscribe(self) -> None:
        """Unsubscribe from game manager and clean up resources."""
        self._kill_flag = True
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
        event: str,
        site: str,
        round: str,
        white: str,
        black: str
    ) -> None:
        """
        Set game metadata for PGN files.
        
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
    
    def set_clock(self, white_seconds: int, black_seconds: int) -> None:
        """
        Set clock times for both players.
        
        Args:
            white_seconds: White player's time in seconds
            black_seconds: Black player's time in seconds
        """
        self._white_time = white_seconds
        self._black_time = black_seconds
    
    def start_clock(self) -> None:
        """Start the clock thread that decrements time."""
        timestr = self._format_time(self._white_time, self._black_time)
        epaper.writeText(CLOCK_DISPLAY_LINE, timestr)
        self._clock_thread = threading.Thread(target=self._clock_thread_loop, daemon=True)
        self._clock_thread.start()
    
    def computer_move(self, move: str, forced: bool = True) -> None:
        """
        Set a computer move that the player is expected to make.
        
        Args:
            move: UCI move string (e.g., "e2e4", "g7g8q")
            forced: Whether this is a forced move (LEDs will indicate it)
        """
        if len(move) < MIN_UCI_MOVE_LENGTH:
            return
        
        self._computer_move = move
        self._force_move = forced
        
        # Light up LEDs to indicate the move
        from_sq, to_sq = self._uci_to_squares(move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
    
    def resign_game(self, side_resigning: int) -> None:
        """
        Handle game resignation.
        
        Args:
            side_resigning: 1 for white, 2 for black
        """
        result_str = "0-1" if side_resigning == 1 else "1-0"
        self._update_game_result(result_str, "Termination.RESIGN", "resignGame")
    
    def draw_game(self) -> None:
        """Handle game draw."""
        self._update_game_result("1/2-1/2", "Termination.DRAW", "drawGame")
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self._board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self._board.fen()
    
    def reset_move_state(self) -> None:
        """Reset all move-related state variables."""
        self._force_move = False
        self._computer_move = ""
        self._source_square = INVALID_SQUARE
        self._legal_squares = []
        self._other_source_square = INVALID_SQUARE
    
    def reset_board(self) -> None:
        """Reset the chess board to starting position."""
        self._board.reset()
    
    def set_board(self, board_obj: chess.Board) -> None:
        """
        Set the chess board state (primarily for testing).
        
        Args:
            board_obj: chess.Board instance to use
        """
        self._board = board_obj
    
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
    
    # Internal methods
    
    def _game_thread_loop(self) -> None:
        """Main game thread loop that subscribes to board events."""
        board.ledsOff()
        log.info("[manager._game_thread_loop] Subscribing to events")
        
        try:
            board.subscribeEvents(self._key_callback_wrapper, self._field_callback_wrapper)
        except Exception as e:
            log.error(f"[manager._game_thread_loop] error: {e}")
            log.error(f"[manager._game_thread_loop] error: {sys.exc_info()[1]}")
            return
        
        while not self._kill_flag:
            time.sleep(0.1)
    
    def _key_callback_wrapper(self, key_pressed) -> None:
        """Wrapper for key callback that handles menu logic."""
        if self._key_callback is not None:
            if self._in_menu == 0 and key_pressed != board.Key.HELP:
                self._key_callback(key_pressed)
            
            if self._in_menu == 0 and key_pressed == board.Key.HELP:
                self._in_menu = 1
                epaper.resignDrawMenu(14)
            
            if self._in_menu == 1 and key_pressed == board.Key.BACK:
                epaper.writeText(14, "                   ")
            
            if self._in_menu == 1 and key_pressed == board.Key.UP:
                epaper.writeText(14, "                   ")
                if self._event_callback is not None:
                    self._event_callback(EVENT_REQUEST_DRAW)
                self._in_menu = 0
            
            if self._in_menu == 1 and key_pressed == board.Key.DOWN:
                epaper.writeText(14, "                   ")
                if self._event_callback is not None:
                    self._event_callback(EVENT_RESIGN_GAME)
                self._in_menu = 0
    
    def _field_callback_wrapper(self, piece_event: int, field: int, time_in_seconds: float) -> None:
        """Wrapper for field callback that handles correction mode."""
        if not self._correction_mode:
            return self._field_callback(piece_event, field, time_in_seconds)
        
        # In correction mode: check if board matches expected state
        current_state = board.getChessState()
        
        # Check if board is in starting position (new game detection)
        if current_state is not None and len(current_state) == BOARD_SIZE:
            if bytearray(current_state) == self._starting_state:
                log.info("[manager._field_callback_wrapper] Starting position detected while in correction mode - exiting correction and triggering new game check")
                board.ledsOff()
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                self._reset_game()
                return
        
        log.info(f"[manager._field_callback_wrapper] Current state:")
        board.printChessState(current_state, logging.ERROR)
        log.info(f"[manager._field_callback_wrapper] Correction expected state:")
        board.printChessState(self._correction_expected_state)
        
        if self._validate_board_state(current_state, self._correction_expected_state):
            log.info("[manager._field_callback_wrapper] Board corrected, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            return
        
        # Still incorrect, update guidance
        self._provide_correction_guidance(current_state, self._correction_expected_state)
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float) -> None:
        """Handle field events (piece lift/place)."""
        field_name = chess.square_name(field)
        piece_color = self._board.color_at(field)
        
        log.info(f"[manager._field_callback] piece_event={piece_event} field={field} fieldname={field_name} color_at={'White' if piece_color else 'Black'} time_in_seconds={time_in_seconds}")
        
        lift = (piece_event == 0)
        place = (piece_event == 1)
        
        # Check if piece color matches current turn
        vpiece = (self._board.turn == chess.WHITE) == (piece_color == True)
        
        if lift and field not in self._legal_squares and self._source_square < 0 and vpiece:
            # Generate legal moves for this piece
            self._legal_squares = self._calculate_legal_squares(field)
            self._source_square = field
        
        # Track opposing side lifts
        if lift and not vpiece:
            self._other_source_square = field
        
        # If opponent piece is placed back on original square, turn LEDs off and reset
        if place and not vpiece and self._other_source_square >= 0 and field == self._other_source_square:
            board.ledsOff()
            self._other_source_square = INVALID_SQUARE
        
        if self._force_move and lift and vpiece:
            # Handle forced move
            if field_name != self._computer_move[0:2]:
                # Wrong piece lifted
                self._legal_squares = [field]
            else:
                # Correct piece, limit legal squares to target
                target = self._computer_move[2:4]
                target_sq = chess.parse_square(target)
                self._legal_squares = [target_sq]
        
        # Ignore stale PLACE events without corresponding LIFT
        if place and self._source_square < 0 and self._other_source_square < 0:
            if self._correction_just_exited:
                if self._force_move and self._computer_move and len(self._computer_move) >= MIN_UCI_MOVE_LENGTH:
                    forced_source = chess.parse_square(self._computer_move[0:2])
                    if field != forced_source:
                        log.info(f"[manager._field_callback] Ignoring stale PLACE event after correction exit for field {field}")
                        self._correction_just_exited = False
                        return
                else:
                    log.info(f"[manager._field_callback] Ignoring stale PLACE event after correction exit for field {field}")
                    self._correction_just_exited = False
                    return
            
            if self._force_move == 1 and self._computer_move and len(self._computer_move) >= MIN_UCI_MOVE_LENGTH:
                forced_source = chess.parse_square(self._computer_move[0:2])
                if field == forced_source:
                    log.info(f"[manager._field_callback] Ignoring stale PLACE event for forced move source field {field}")
                    self._correction_just_exited = False
                    return
            
            if not self._force_move:
                log.info(f"[manager._field_callback] Ignoring stale PLACE event for field {field}")
                self._correction_just_exited = False
                return
        
        # Clear flag once we process a valid event (LIFT)
        if lift:
            self._correction_just_exited = False
        
        if place and field not in self._legal_squares:
            board.beep(board.SOUND_WRONG_MOVE)
            log.warning(f"[manager._field_callback] Piece placed on illegal square {field}")
            is_takeback = self._check_last_board_state()
            if not is_takeback:
                self._guide_misplaced_piece(field, self._source_square, self._other_source_square, vpiece)
        
        if place and field in self._legal_squares:
            log.info(f"[manager._field_callback] Making move")
            if field == self._source_square:
                # Piece placed back on source square
                board.ledsOff()
                self._source_square = INVALID_SQUARE
                self._legal_squares = []
            else:
                # Execute the move
                from_name = chess.square_name(self._source_square)
                to_name = chess.square_name(field)
                piece_name = str(self._board.piece_at(self._source_square))
                promotion_suffix = self._handle_promotion(field, piece_name, self._force_move)
                
                if self._force_move:
                    move_str = self._computer_move
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
                
                self._collect_board_state()
                self._reset_move_state()
                
                if self._move_callback is not None:
                    self._move_callback(move_str)
                
                board.beep(board.SOUND_GENERAL)
                board.led(field)
                
                # Check game outcome
                outcome = self._board.outcome(claim_draw=True)
                if outcome is None:
                    self._switch_turn_with_event()
                else:
                    board.beep(board.SOUND_GENERAL)
                    result_str = str(self._board.result())
                    termination = str(outcome.termination)
                    self._update_game_result(result_str, termination, "fieldcallback")
    
    def _collect_board_state(self) -> None:
        """Collect and store the current board state."""
        log.info("[manager._collect_board_state] Collecting board state")
        self._board_states.append(board.getChessState())
        log.debug(f"[manager._collect_board_state] Board state: {self._board}")
    
    def _check_last_board_state(self) -> bool:
        """
        Check if current board state matches previous state (takeback detection).
        
        Returns:
            True if takeback detected, False otherwise
        """
        if self._takeback_callback is None or len(self._board_states) <= 1:
            return False
        
        log.info("[manager._check_last_board_state] Checking last board state")
        current_state = board.getChessState()
        log.info("[manager._check_last_board_state] Current board state:")
        board.printChessState(current_state)
        log.info("[manager._check_last_board_state] Last board state:")
        board.printChessState(self._board_states[len(self._board_states) - 2])
        
        if current_state == self._board_states[len(self._board_states) - 2]:
            board.ledsOff()
            self._board_states = self._board_states[:-1]
            
            # Remove last move from database
            if self._session is not None:
                last_move = self._session.query(models.GameMove).order_by(models.GameMove.id.desc()).first()
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
                log.info("[manager._check_last_board_state] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            return True
        
        return False
    
    def _validate_board_state(self, current_state: Optional[bytearray], expected_state: Optional[bytearray]) -> bool:
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
        
        from_num = ((ord(uci_move[1:2]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[0:1]) - ord("a"))
        to_num = ((ord(uci_move[3:4]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[2:3]) - ord("a"))
        return from_num, to_num
    
    def _switch_turn_with_event(self) -> None:
        """Trigger appropriate event callback based on current turn."""
        if self._event_callback is not None:
            if self._board.turn == chess.WHITE:
                self._event_callback(EVENT_WHITE_TURN)
            else:
                self._event_callback(EVENT_BLACK_TURN)
    
    def _update_game_result(self, result_str: str, termination: str, context: str) -> None:
        """
        Update game result in database and trigger event callback.
        
        Args:
            result_str: Result string (e.g., "1-0", "0-1", "1/2-1/2")
            termination: Termination string for event callback
            context: Context string for logging
        """
        if self._session is not None:
            game = self._session.query(models.Game).filter(models.Game.id == self._game_db_id).first()
            if game is not None:
                game.result = result_str
                self._session.flush()
                self._session.commit()
            else:
                log.warning(f"[manager.{context}] Game with id {self._game_db_id} not found in database, cannot update result")
        
        # Always trigger callback, even if DB update failed
        if self._event_callback is not None:
            self._event_callback(termination)
    
    def _handle_promotion(self, field: int, piece_name: str, force_move: bool) -> str:
        """
        Handle pawn promotion by prompting user for piece choice.
        
        Args:
            field: Target square index
            piece_name: Piece symbol ("P" for white, "p" for black)
            force_move: Whether this is a forced move (no user prompt)
        
        Returns:
            Promotion piece suffix ("q", "r", "b", "n") or empty string
        """
        is_white_promotion = (field // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
        is_black_promotion = (field // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        if force_move == 0:
            screen_back = epaper.epaperbuffer.copy()
            self._showing_promotion = True
            epaper.promotionOptions(PROMOTION_DISPLAY_LINE)
            promotion_choice = self._wait_for_promotion_choice()
            self._showing_promotion = False
            epaper.epaperbuffer = screen_back.copy()
            return promotion_choice
        
        return ""
    
    def _wait_for_promotion_choice(self) -> str:
        """
        Wait for user to select promotion piece via button press.
        
        Returns:
            Promotion piece suffix ("q", "r", "b", "n")
        """
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
    
    def _format_time(self, white_seconds: int, black_seconds: int) -> str:
        """
        Format time display string for clock.
        
        Args:
            white_seconds: White player's remaining seconds
            black_seconds: Black player's remaining seconds
        
        Returns:
            Formatted time string "MM:SS       MM:SS"
        """
        w_min = white_seconds // SECONDS_PER_MINUTE
        w_sec = white_seconds % SECONDS_PER_MINUTE
        b_min = black_seconds // SECONDS_PER_MINUTE
        b_sec = black_seconds % SECONDS_PER_MINUTE
        return f"{w_min:02d}:{w_sec:02d}       {b_min:02d}:{b_sec:02d}"
    
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
    
    def _reset_move_state(self) -> None:
        """Reset move-related state variables after a move is completed."""
        self._legal_squares = []
        self._source_square = INVALID_SQUARE
        board.ledsOff()
        self._force_move = False
    
    def _double_beep(self) -> None:
        """Play two beeps with a short delay between them."""
        board.beep(board.SOUND_GENERAL)
        time.sleep(0.3)
        board.beep(board.SOUND_GENERAL)
    
    def _enter_correction_mode(self) -> None:
        """Enter correction mode to guide user in fixing board state."""
        self._correction_mode = True
        self._correction_expected_state = self._board_states[-1] if self._board_states else None
        self._correction_just_exited = False
        log.warning(f"[manager._enter_correction_mode] Entered correction mode (forcemove={self._force_move}, computermove={self._computer_move})")
    
    def _exit_correction_mode(self) -> None:
        """Exit correction mode and resume normal game flow."""
        self._correction_mode = False
        self._correction_expected_state = None
        self._correction_just_exited = True
        log.warning("[manager._exit_correction_mode] Exited correction mode")
        
        # Reset move state variables
        self._source_square = INVALID_SQUARE
        self._legal_squares = []
        self._other_source_square = INVALID_SQUARE
        
        # Restore forced move LEDs if pending
        if self._force_move and self._computer_move and len(self._computer_move) >= MIN_UCI_MOVE_LENGTH:
            from_sq, to_sq = self._uci_to_squares(self._computer_move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
                log.info(f"[manager._exit_correction_mode] Restored forced move LEDs: {self._computer_move}")
    
    def _provide_correction_guidance(self, current_state: bytearray, expected_state: bytearray) -> None:
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
            """Convert square index to (row, col)"""
            return (idx // BOARD_WIDTH), (idx % BOARD_WIDTH)
        
        def _dist(a, b):
            """Manhattan distance between two squares"""
            ar, ac = _rc(a)
            br, bc = _rc(b)
            return abs(ar - br) + abs(ac - bc)
        
        # Compute diffs to find misplaced pieces
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
        
        log.warning(f"[manager._provide_correction_guidance] Found {len(wrong_locations)} wrong pieces, {len(missing_origins)} missing pieces")
        
        # Guide one piece at a time
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
            log.warning(f"[manager._provide_correction_guidance] Guiding piece from {chess.square_name(from_idx)} to {chess.square_name(to_idx)}")
        else:
            # Only pieces missing or only extra pieces
            if len(missing_origins) > 0:
                board.ledsOff()
                for idx in missing_origins:
                    board.led(idx, intensity=5)
                log.warning(f"[manager._provide_correction_guidance] Pieces missing at: {[chess.square_name(sq) for sq in missing_origins]}")
            elif len(wrong_locations) > 0:
                board.ledsOff()
                for idx in wrong_locations:
                    board.led(idx, intensity=5)
                log.warning(f"[manager._provide_correction_guidance] Extra pieces at: {[chess.square_name(sq) for sq in wrong_locations]}")
    
    def _guide_misplaced_piece(self, field: int, source_sq: int, other_source_sq: int, vpiece: bool) -> None:
        """
        Guide the user to correct misplaced pieces using LED indicators.
        
        Args:
            field: The square where the illegal piece was placed
            source_sq: The source square of the current player's piece being moved
            other_source_sq: The source square of an opponent's piece that was lifted
            vpiece: Whether the piece belongs to the current player
        """
        log.warning(f"[manager._guide_misplaced_piece] Entering correction mode for field {field}")
        self._enter_correction_mode()
        current_state = board.getChessState()
        if self._board_states and len(self._board_states) > 0:
            self._provide_correction_guidance(current_state, self._board_states[-1])
    
    def _reset_game(self) -> None:
        """Reset the game to starting position."""
        try:
            log.info("DEBUG: Detected starting position - triggering NEW_GAME")
            self.reset_move_state()
            self._board.reset()
            paths.write_fen_log(self._board.fen())
            self._double_beep()
            board.ledsOff()
            
            if self._event_callback is not None:
                self._event_callback(EVENT_NEW_GAME)
                self._event_callback(EVENT_WHITE_TURN)
            
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
                log.info(game)
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
            log.error(f"Error resetting game: {e}")
            import traceback
            traceback.print_exc()
    
    def _clock_thread_loop(self) -> None:
        """Clock thread that decrements time and updates display."""
        while not self._kill_flag:
            time.sleep(CLOCK_DECREMENT_SECONDS)
            
            if self._white_time > 0 and self._board.turn == chess.WHITE and self._board.fen() != STARTING_FEN:
                self._white_time = self._white_time - CLOCK_DECREMENT_SECONDS
            
            if self._black_time > 0 and self._board.turn == chess.BLACK:
                self._black_time = self._black_time - CLOCK_DECREMENT_SECONDS
            
            if not self._showing_promotion:
                timestr = self._format_time(self._white_time, self._black_time)
                epaper.writeText(CLOCK_DISPLAY_LINE, timestr)


# Global instance for backward compatibility
_manager_instance: Optional[ChessGameManager] = None


def subscribeGame(
    eventCallback: Callable,
    moveCallback: Callable,
    keyCallback: Callable,
    takebackCallback: Optional[Callable] = None
) -> None:
    """
    Subscribe to game manager (backward compatibility wrapper).
    
    Args:
        eventCallback: Callback for game events
        moveCallback: Callback for valid moves
        keyCallback: Callback for key presses
        takebackCallback: Optional callback for takebacks
    """
    global _manager_instance
    _manager_instance = ChessGameManager()
    _manager_instance.subscribe(eventCallback, moveCallback, keyCallback, takebackCallback)


def unsubscribeGame() -> None:
    """Unsubscribe from game manager (backward compatibility wrapper)."""
    global _manager_instance
    if _manager_instance is not None:
        _manager_instance.unsubscribe()
        _manager_instance = None


def computerMove(move: str, forced: bool = True) -> None:
    """Set computer move (backward compatibility wrapper)."""
    if _manager_instance is not None:
        _manager_instance.computer_move(move, forced)


def resignGame(sideResigning: int) -> None:
    """Resign game (backward compatibility wrapper)."""
    if _manager_instance is not None:
        _manager_instance.resign_game(sideResigning)


def drawGame() -> None:
    """Draw game (backward compatibility wrapper)."""
    if _manager_instance is not None:
        _manager_instance.draw_game()


def getBoard() -> chess.Board:
    """Get chess board (backward compatibility wrapper)."""
    if _manager_instance is not None:
        return _manager_instance.get_board()
    return chess.Board()


def getFEN() -> str:
    """Get FEN string (backward compatibility wrapper)."""
    if _manager_instance is not None:
        return _manager_instance.get_fen()
    return STARTING_FEN


def setGameInfo(event: str, site: str, round: str, white: str, black: str) -> None:
    """Set game info (backward compatibility wrapper)."""
    if _manager_instance is not None:
        _manager_instance.set_game_info(event, site, round, white, black)


def setClock(white: int, black: int) -> None:
    """Set clock (backward compatibility wrapper)."""
    if _manager_instance is not None:
        _manager_instance.set_clock(white, black)


def startClock() -> None:
    """Start clock (backward compatibility wrapper)."""
    if _manager_instance is not None:
        _manager_instance.start_clock()


def getResult() -> str:
    """Get result (backward compatibility wrapper)."""
    if _manager_instance is not None:
        return _manager_instance.get_result()
    return "Unknown"


def resetMoveState() -> None:
    """Reset move state (backward compatibility wrapper)."""
    if _manager_instance is not None:
        _manager_instance.reset_move_state()


def resetBoard() -> None:
    """Reset board (backward compatibility wrapper)."""
    if _manager_instance is not None:
        _manager_instance.reset_board()


def setBoard(boardObj: chess.Board) -> None:
    """Set board (backward compatibility wrapper)."""
    if _manager_instance is not None:
        _manager_instance.set_board(boardObj)


# Export board module and constants for backward compatibility
# This allows code like: from DGTCentaurMods.game import manager; manager.board.Key.BACK
board = board  # Re-export board module

