# Chess game manager with improved structure and maintainability
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

"""
GameManager manages chess game state, move processing, and board interactions.

This class encapsulates game state and provides callbacks for game events,
moves, and key presses. It handles move validation, promotion, takebacks,
and correction mode for misplaced pieces.
"""

from DGTCentaurMods.board import board
from DGTCentaurMods.display import epaper
from DGTCentaurMods.db import models
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func, select
from scipy.optimize import linear_sum_assignment
import threading
import time
import chess
import sys
import inspect
import numpy as np
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log, logging
from typing import Optional, Callable, List, Tuple


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

# Starting board state (all pieces in starting position)
STARTING_BOARD_STATE = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')


class GameManager:
    """
    Manages chess game state, move processing, and board interactions.
    
    Encapsulates all game state and provides a clean interface for
    subscribing to game events, moves, and key presses.
    """
    
    def __init__(self):
        """Initialize a new GameManager instance."""
        # Callback functions
        self._event_callback: Optional[Callable] = None
        self._move_callback: Optional[Callable] = None
        self._key_callback: Optional[Callable] = None
        self._takeback_callback: Optional[Callable] = None
        
        # Game state
        self._chess_board = chess.Board()
        self._board_states: List[bytearray] = []
        self._game_db_id: Optional[int] = None
        self._database_session: Optional[sessionmaker] = None
        
        # Move state
        self._source_square = INVALID_SQUARE
        self._other_source_square = INVALID_SQUARE
        self._legal_squares: List[int] = []
        self._computer_move = ""
        self._force_move = False
        
        # Correction mode state
        self._correction_mode = False
        self._correction_expected_state: Optional[bytearray] = None
        self._correction_just_exited = False
        
        # Menu state
        self._in_menu = False
        
        # Promotion state
        self._showing_promotion = False
        
        # Clock state
        self._white_time = 0
        self._black_time = 0
        
        # Game info
        self._game_source = ""
        self._game_event = ""
        self._game_site = ""
        self._game_round = ""
        self._game_white = ""
        self._game_black = ""
        
        # Thread control
        self._kill_flag = False
        self._game_thread: Optional[threading.Thread] = None
        self._clock_thread: Optional[threading.Thread] = None
    
    def subscribe_game(
        self,
        event_callback: Callable,
        move_callback: Callable,
        key_callback: Callable,
        takeback_callback: Optional[Callable] = None
    ):
        """
        Subscribe to game events, moves, and key presses.
        
        Args:
            event_callback: Function called with game events (EVENT_NEW_GAME, etc.)
            move_callback: Function called with completed moves (UCI format)
            key_callback: Function called with key press events
            takeback_callback: Optional function called when takeback occurs
        """
        self._event_callback = event_callback
        self._move_callback = move_callback
        self._key_callback = key_callback
        self._takeback_callback = takeback_callback
        
        self._board_states = []
        self._collect_board_state()
        
        self._game_source = inspect.getsourcefile(sys._getframe(1))
        Session = sessionmaker(bind=models.engine)
        self._database_session = Session()
        
        self._kill_flag = False
        self._game_thread = threading.Thread(
            target=self._game_thread_main,
            daemon=True
        )
        self._game_thread.start()
    
    def unsubscribe_game(self):
        """Stop the game manager and clean up resources."""
        self._kill_flag = True
        board.ledsOff()
        
        if self._database_session is not None:
            try:
                self._database_session.close()
                self._database_session = None
            except Exception:
                self._database_session = None
    
    def set_game_info(
        self,
        event: str,
        site: str,
        round: str,
        white: str,
        black: str
    ):
        """
        Set game metadata for PGN files.
        
        Args:
            event: Event name
            site: Site name
            round: Round number
            white: White player name
            black: Black player name
        """
        self._game_event = event
        self._game_site = site
        self._game_round = round
        self._game_white = white
        self._game_black = black
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self._chess_board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self._chess_board.fen()
    
    def reset_board(self):
        """Reset the chess board to starting position."""
        self._chess_board.reset()
    
    def reset_move_state(self):
        """Reset all move-related state variables."""
        self._force_move = False
        self._computer_move = ""
        self._source_square = INVALID_SQUARE
        self._legal_squares = []
        self._other_source_square = INVALID_SQUARE
        board.ledsOff()
    
    def computer_move(self, move_uci: str, forced: bool = True):
        """
        Set the computer move that the player is expected to make.
        
        Args:
            move_uci: Move in UCI format (e.g., "e2e4", "g7g8q")
            forced: Whether this is a forced move (default: True)
        """
        if len(move_uci) < MIN_UCI_MOVE_LENGTH:
            return
        
        self._computer_move = move_uci
        self._force_move = forced
        
        from_square, to_square = self._uci_to_squares(move_uci)
        if from_square is not None and to_square is not None:
            board.ledFromTo(from_square, to_square)
    
    def resign_game(self, side_resigning: int):
        """
        Handle game resignation.
        
        Args:
            side_resigning: 1 for white, 2 for black
        """
        result = "0-1" if side_resigning == 1 else "1-0"
        self._update_game_result(result, "Termination.RESIGN", "resignGame")
    
    def draw_game(self):
        """Handle game draw."""
        self._update_game_result("1/2-1/2", "Termination.DRAW", "drawGame")
    
    def get_result(self) -> str:
        """Get the result of the last game."""
        if self._database_session is None:
            return "Unknown"
        
        gamedata = self._database_session.execute(
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
    
    def set_clock(self, white_seconds: int, black_seconds: int):
        """
        Set the clock times.
        
        Args:
            white_seconds: White player's remaining seconds
            black_seconds: Black player's remaining seconds
        """
        self._white_time = white_seconds
        self._black_time = black_seconds
    
    def start_clock(self):
        """Start the clock thread."""
        time_str = self._format_time(self._white_time, self._black_time)
        epaper.writeText(CLOCK_DISPLAY_LINE, time_str)
        
        self._clock_thread = threading.Thread(
            target=self._clock_thread_main,
            daemon=True
        )
        self._clock_thread.start()
    
    def _game_thread_main(self):
        """Main game thread that handles board events."""
        board.ledsOff()
        log.info("[GameManager._game_thread_main] Subscribing to events")
        
        try:
            board.subscribeEvents(
                self._key_callback_wrapper,
                self._correction_field_callback_wrapper
            )
        except Exception as e:
            log.error(f"[GameManager._game_thread_main] error: {e}")
            log.error(f"[GameManager._game_thread_main] error: {sys.exc_info()[1]}")
            return
        
        while not self._kill_flag:
            time.sleep(0.1)
    
    def _clock_thread_main(self):
        """Clock thread that decrements time and updates display."""
        while not self._kill_flag:
            time.sleep(CLOCK_DECREMENT_SECONDS)
            
            if self._white_time > 0 and self._chess_board.turn == chess.WHITE and self._chess_board.fen() != STARTING_FEN:
                self._white_time -= CLOCK_DECREMENT_SECONDS
            
            if self._black_time > 0 and self._chess_board.turn == chess.BLACK:
                self._black_time -= CLOCK_DECREMENT_SECONDS
            
            if not self._showing_promotion:
                time_str = self._format_time(self._white_time, self._black_time)
                epaper.writeText(CLOCK_DISPLAY_LINE, time_str)
    
    def _key_callback_wrapper(self, key_pressed):
        """
        Wrapper for key callback that handles menu functionality.
        
        Args:
            key_pressed: Key that was pressed
        """
        if self._key_callback is not None:
            if not self._in_menu and key_pressed != board.Key.HELP:
                self._key_callback(key_pressed)
            
            if not self._in_menu and key_pressed == board.Key.HELP:
                self._in_menu = True
                epaper.resignDrawMenu(14)
            
            if self._in_menu and key_pressed == board.Key.BACK:
                epaper.writeText(14, "                   ")
                self._in_menu = False
            
            if self._in_menu and key_pressed == board.Key.UP:
                epaper.writeText(14, "                   ")
                if self._event_callback is not None:
                    self._event_callback(EVENT_REQUEST_DRAW)
                self._in_menu = False
            
            if self._in_menu and key_pressed == board.Key.DOWN:
                epaper.writeText(14, "                   ")
                if self._event_callback is not None:
                    self._event_callback(EVENT_RESIGN_GAME)
                self._in_menu = False
    
    def _correction_field_callback_wrapper(self, piece_event, field, time_in_seconds):
        """
        Wrapper that intercepts field events during correction mode.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63)
            time_in_seconds: Time of the event
        """
        if not self._correction_mode:
            return self._field_callback(piece_event, field, time_in_seconds)
        
        current_state = board.getChessState()
        
        # Check if board is in starting position (new game detection)
        if current_state is not None and len(current_state) == BOARD_SIZE:
            if bytearray(current_state) == STARTING_BOARD_STATE:
                log.info("[GameManager._correction_field_callback_wrapper] Starting position detected - exiting correction and triggering new game")
                board.ledsOff()
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                self._reset_game()
                return
        
        log.info(f"[GameManager._correction_field_callback_wrapper] Current state:")
        board.printChessState(current_state, logging.ERROR)
        log.info(f"[GameManager._correction_field_callback_wrapper] Correction expected state:")
        board.printChessState(self._correction_expected_state)
        
        if self._validate_board_state(current_state, self._correction_expected_state):
            log.info("[GameManager._correction_field_callback_wrapper] Board corrected, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            return
        
        # Still incorrect, update guidance
        self._provide_correction_guidance(current_state, self._correction_expected_state)
    
    def _field_callback(self, piece_event, field, time_in_seconds):
        """
        Handle field events (piece lift/place).
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63)
            time_in_seconds: Time of the event
        """
        field_name = chess.square_name(field)
        piece_color = self._chess_board.color_at(field)
        
        log.info(f"[GameManager._field_callback] piece_event={piece_event} field={field} fieldname={field_name} color_at={'White' if piece_color else 'Black'} time_in_seconds={time_in_seconds}")
        
        is_lift = (piece_event == 0)
        is_place = (piece_event == 1)
        
        # Check if piece color matches current turn
        is_current_player_piece = (self._chess_board.turn == chess.WHITE) == (piece_color == True)
        
        if is_lift and field not in self._legal_squares and self._source_square < 0 and is_current_player_piece:
            self._legal_squares = self._calculate_legal_squares(field)
            self._source_square = field
        
        # Track opposing side lifts
        if is_lift and not is_current_player_piece:
            self._other_source_square = field
        
        # If opponent piece is placed back on original square, reset
        if is_place and not is_current_player_piece and self._other_source_square >= 0 and field == self._other_source_square:
            board.ledsOff()
            self._other_source_square = INVALID_SQUARE
        
        # Handle forced moves
        if self._force_move and is_lift and is_current_player_piece:
            if field_name != self._computer_move[0:2]:
                # Wrong piece lifted for forced move
                self._legal_squares = [field]
                self._source_square = field
            else:
                # Correct piece, limit legal squares to target
                target = self._computer_move[2:4]
                target_square = chess.parse_square(target)
                self._legal_squares = [target_square]
                self._source_square = field
        
        # Ignore stale PLACE events without corresponding LIFT
        if is_place and self._source_square < 0 and self._other_source_square < 0:
            if self._correction_just_exited:
                if self._force_move and self._computer_move and len(self._computer_move) >= MIN_UCI_MOVE_LENGTH:
                    forced_source = chess.parse_square(self._computer_move[0:2])
                    if field != forced_source:
                        log.info(f"[GameManager._field_callback] Ignoring stale PLACE event after correction exit for field {field}")
                        self._correction_just_exited = False
                        return
                else:
                    log.info(f"[GameManager._field_callback] Ignoring stale PLACE event after correction exit for field {field}")
                    self._correction_just_exited = False
                    return
            
            if self._force_move and self._computer_move and len(self._computer_move) >= MIN_UCI_MOVE_LENGTH:
                forced_source = chess.parse_square(self._computer_move[0:2])
                if field == forced_source:
                    log.info(f"[GameManager._field_callback] Ignoring stale PLACE event for forced move source field {field}")
                    self._correction_just_exited = False
                    return
            
            if not self._force_move:
                log.info(f"[GameManager._field_callback] Ignoring stale PLACE event for field {field} (no corresponding LIFT)")
                self._correction_just_exited = False
                return
        
        # Clear flag once we process a valid event (LIFT)
        if is_lift:
            self._correction_just_exited = False
        
        # Handle illegal placements
        if is_place and field not in self._legal_squares:
            board.beep(board.SOUND_WRONG_MOVE)
            log.warning(f"[GameManager._field_callback] Piece placed on illegal square {field}")
            is_takeback = self._check_last_board_state()
            if not is_takeback:
                self._guide_misplaced_piece(field, self._source_square, self._other_source_square, is_current_player_piece)
        
        # Handle legal placements
        if is_place and field in self._legal_squares:
            log.info(f"[GameManager._field_callback] Making move")
            
            if field == self._source_square:
                # Piece placed back on source square
                board.ledsOff()
                self._source_square = INVALID_SQUARE
                self._legal_squares = []
            else:
                # Valid move
                self._process_move(field)
    
    def _process_move(self, target_square: int):
        """
        Process a completed move.
        
        Args:
            target_square: Target square index (0-63)
        """
        from_name = chess.square_name(self._source_square)
        to_name = chess.square_name(target_square)
        piece_name = str(self._chess_board.piece_at(self._source_square))
        
        promotion_suffix = self._handle_promotion(target_square, piece_name, self._force_move)
        
        if self._force_move:
            move_uci = self._computer_move
        else:
            move_uci = from_name + to_name + promotion_suffix
        
        # Make the move and update fen.log
        self._chess_board.push(chess.Move.from_uci(move_uci))
        paths.write_fen_log(self._chess_board.fen())
        
        # Log move to database
        game_move = models.GameMove(
            gameid=self._game_db_id,
            move=move_uci,
            fen=str(self._chess_board.fen())
        )
        self._database_session.add(game_move)
        self._database_session.commit()
        
        self._collect_board_state()
        self._reset_move_state()
        
        if self._move_callback is not None:
            self._move_callback(move_uci)
        
        board.beep(board.SOUND_GENERAL)
        board.led(target_square)
        
        # Check game outcome
        outcome = self._chess_board.outcome(claim_draw=True)
        if outcome is None:
            self._switch_turn_with_event()
        else:
            board.beep(board.SOUND_GENERAL)
            result_str = str(self._chess_board.result())
            termination = str(outcome.termination)
            self._update_game_result(result_str, termination, "field_callback")
    
    def _check_last_board_state(self) -> bool:
        """
        Check if current board state matches previous state (takeback detection).
        
        Returns:
            True if takeback detected, False otherwise
        """
        if self._takeback_callback is None or len(self._board_states) <= 1:
            return False
        
        log.info(f"[GameManager._check_last_board_state] Checking last board state")
        current_state = board.getChessState()
        log.info(f"[GameManager._check_last_board_state] Current board state:")
        board.printChessState(current_state)
        log.info(f"[GameManager._check_last_board_state] Last board state:")
        board.printChessState(self._board_states[len(self._board_states) - 2])
        
        if current_state == self._board_states[len(self._board_states) - 2]:
            board.ledsOff()
            self._board_states = self._board_states[:-1]
            
            # Remove last move from database
            last_move = self._database_session.query(models.GameMove).order_by(models.GameMove.id.desc()).first()
            self._database_session.delete(last_move)
            self._database_session.commit()
            
            self._chess_board.pop()
            paths.write_fen_log(self._chess_board.fen())
            board.beep(board.SOUND_GENERAL)
            
            if self._takeback_callback is not None:
                self._takeback_callback()
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            current = board.getChessState()
            if not self._validate_board_state(current, self._board_states[-1] if self._board_states else None):
                log.info("[GameManager._check_last_board_state] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            return True
        
        return False
    
    def _handle_promotion(self, target_square: int, piece_name: str, is_forced_move: bool) -> str:
        """
        Handle pawn promotion by prompting user for piece choice.
        
        Args:
            target_square: Target square index
            piece_name: Piece symbol ("P" for white, "p" for black)
            is_forced_move: Whether this is a forced move (no user prompt)
        
        Returns:
            Promotion piece suffix ("q", "r", "b", "n") or empty string
        """
        is_white_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
        is_black_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        
        if not is_forced_move:
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
    
    def _calculate_legal_squares(self, source_square: int) -> List[int]:
        """
        Calculate legal destination squares for a piece at the given square.
        
        Args:
            source_square: Source square index (0-63)
        
        Returns:
            List of legal destination square indices, including the source square
        """
        legal_moves = self._chess_board.legal_moves
        legal_squares = [source_square]  # Include source square
        
        for move in legal_moves:
            if move.from_square == source_square:
                legal_squares.append(move.to_square)
        
        return legal_squares
    
    def _switch_turn_with_event(self):
        """Trigger appropriate event callback based on current turn."""
        if self._event_callback is not None:
            if self._chess_board.turn == chess.WHITE:
                self._event_callback(EVENT_WHITE_TURN)
            else:
                self._event_callback(EVENT_BLACK_TURN)
    
    def _update_game_result(self, result_str: str, termination: str, context: str):
        """
        Update game result in database and trigger event callback.
        
        Args:
            result_str: Result string (e.g., "1-0", "0-1", "1/2-1/2")
            termination: Termination string for event callback
            context: Context string for logging
        """
        game = self._database_session.query(models.Game).filter(models.Game.id == self._game_db_id).first()
        if game is not None:
            game.result = result_str
            self._database_session.flush()
            self._database_session.commit()
        else:
            log.warning(f"[GameManager.{context}] Game with id {self._game_db_id} not found in database, cannot update result")
        
        if self._event_callback is not None:
            self._event_callback(termination)
    
    def _collect_board_state(self):
        """Append the current board state to board_states."""
        log.info(f"[GameManager._collect_board_state] Collecting board state")
        self._board_states.append(board.getChessState())
        print(self._chess_board)
    
    def _reset_game(self):
        """Reset game to starting position and trigger NEW_GAME event."""
        try:
            log.info("DEBUG: Detected starting position - triggering NEW_GAME")
            self.reset_move_state()
            self._chess_board.reset()
            paths.write_fen_log(self._chess_board.fen())
            self._double_beep()
            board.ledsOff()
            
            if self._event_callback is not None:
                self._event_callback(EVENT_NEW_GAME)
                self._event_callback(EVENT_WHITE_TURN)
            
            # Log new game in database
            game = models.Game(
                source=self._game_source,
                event=self._game_event,
                site=self._game_site,
                round=self._game_round,
                white=self._game_white,
                black=self._game_black
            )
            log.info(game)
            self._database_session.add(game)
            self._database_session.commit()
            
            # Get the max game id as that is this game id
            self._game_db_id = self._database_session.query(func.max(models.Game.id)).scalar()
            
            # Make an entry in GameMove for this start state
            game_move = models.GameMove(
                gameid=self._game_db_id,
                move='',
                fen=str(self._chess_board.fen())
            )
            self._database_session.add(game_move)
            self._database_session.commit()
            
            self._board_states = []
            self._collect_board_state()
        except Exception as e:
            log.error(f"Error resetting game: {e}")
            import traceback
            traceback.print_exc()
    
    def _double_beep(self):
        """Play two beeps with a short delay between them."""
        board.beep(board.SOUND_GENERAL)
        time.sleep(0.3)
        board.beep(board.SOUND_GENERAL)
    
    def _format_time(self, white_seconds: int, black_seconds: int) -> str:
        """
        Format time display string for clock.
        
        Args:
            white_seconds: White player's remaining seconds
            black_seconds: Black player's remaining seconds
        
        Returns:
            Formatted time string "MM:SS       MM:SS"
        """
        white_minutes = white_seconds // SECONDS_PER_MINUTE
        white_secs = white_seconds % SECONDS_PER_MINUTE
        black_minutes = black_seconds // SECONDS_PER_MINUTE
        black_secs = black_seconds % SECONDS_PER_MINUTE
        
        return f"{white_minutes:02d}:{white_secs:02d}       {black_minutes:02d}:{black_secs:02d}"
    
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
    
    def _validate_board_state(self, current_state, expected_state) -> bool:
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
    
    def _enter_correction_mode(self):
        """Enter correction mode to guide user in fixing board state."""
        self._correction_mode = True
        self._correction_expected_state = self._board_states[-1] if self._board_states else None
        self._correction_just_exited = False
        log.warning(f"[GameManager._enter_correction_mode] Entered correction mode (forcemove={self._force_move}, computermove={self._computer_move})")
    
    def _exit_correction_mode(self):
        """Exit correction mode and resume normal game flow."""
        self._correction_mode = False
        self._correction_expected_state = None
        self._correction_just_exited = True
        log.warning("[GameManager._exit_correction_mode] Exited correction mode")
        
        # Reset move state variables
        self._source_square = INVALID_SQUARE
        self._legal_squares = []
        self._other_source_square = INVALID_SQUARE
        
        # If there was a forced move pending, restore the LEDs
        if self._force_move and self._computer_move and len(self._computer_move) >= MIN_UCI_MOVE_LENGTH:
            from_square, to_square = self._uci_to_squares(self._computer_move)
            if from_square is not None and to_square is not None:
                board.ledFromTo(from_square, to_square)
                log.info(f"[GameManager._exit_correction_mode] Restored forced move LEDs: {self._computer_move}")
    
    def _guide_misplaced_piece(self, field: int, source_square: int, other_source_square: int, is_current_player_piece: bool):
        """
        Guide the user to correct misplaced pieces using LED indicators.
        
        Args:
            field: The square where the illegal piece was placed
            source_square: The source square of the current player's piece being moved
            other_source_square: The source square of an opponent's piece that was lifted
            is_current_player_piece: Whether the piece belongs to the current player
        """
        log.warning(f"[GameManager._guide_misplaced_piece] Entering correction mode for field {field}")
        self._enter_correction_mode()
        current_state = board.getChessState()
        if self._board_states and len(self._board_states) > 0:
            self._provide_correction_guidance(current_state, self._board_states[-1])
    
    def _provide_correction_guidance(self, current_state, expected_state):
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
        
        def square_to_row_col(square_idx):
            """Convert square index to (row, col)."""
            return (square_idx // BOARD_WIDTH), (square_idx % BOARD_WIDTH)
        
        def manhattan_distance(square_a, square_b):
            """Calculate Manhattan distance between two squares."""
            ar, ac = square_to_row_col(square_a)
            br, bc = square_to_row_col(square_b)
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
        
        log.warning(f"[GameManager._provide_correction_guidance] Found {len(wrong_locations)} wrong pieces, {len(missing_origins)} missing pieces")
        
        # Guide one piece at a time
        if len(wrong_locations) > 0 and len(missing_origins) > 0:
            num_wrong = len(wrong_locations)
            num_missing = len(missing_origins)
            
            if num_wrong == 1 and num_missing == 1:
                # Simple case - just pair the only two
                from_idx = wrong_locations[0]
                to_idx = missing_origins[0]
            else:
                # Create cost matrix based on Manhattan distances
                costs = np.zeros((num_wrong, num_missing))
                for i, wl in enumerate(wrong_locations):
                    for j, mo in enumerate(missing_origins):
                        costs[i, j] = manhattan_distance(wl, mo)
                
                # Find optimal assignment
                row_ind, col_ind = linear_sum_assignment(costs)
                
                # Guide the first pair
                from_idx = wrong_locations[row_ind[0]]
                to_idx = missing_origins[col_ind[0]]
            
            board.ledsOff()
            board.ledFromTo(from_idx, to_idx, intensity=5)
            log.warning(f"[GameManager._provide_correction_guidance] Guiding piece from {chess.square_name(from_idx)} to {chess.square_name(to_idx)}")
        else:
            # Only pieces missing or only extra pieces
            if len(missing_origins) > 0:
                board.ledsOff()
                for idx in missing_origins:
                    board.led(idx, intensity=5)
                log.warning(f"[GameManager._provide_correction_guidance] Pieces missing at: {[chess.square_name(sq) for sq in missing_origins]}")
            elif len(wrong_locations) > 0:
                board.ledsOff()
                for idx in wrong_locations:
                    board.led(idx, intensity=5)
                log.warning(f"[GameManager._provide_correction_guidance] Extra pieces at: {[chess.square_name(sq) for sq in wrong_locations]}")


# Backward compatibility: create a singleton instance
_game_manager_instance = None

def subscribeGame(eventCallback, moveCallback, keyCallback, takebackCallback=None):
    """Backward compatibility wrapper for GameManager.subscribe_game."""
    global _game_manager_instance
    _game_manager_instance = GameManager()
    _game_manager_instance.subscribe_game(eventCallback, moveCallback, keyCallback, takebackCallback)
    return _game_manager_instance

def unsubscribeGame():
    """Backward compatibility wrapper for GameManager.unsubscribe_game."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.unsubscribe_game()
        _game_manager_instance = None

def getBoard():
    """Backward compatibility wrapper for GameManager.get_board."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        return _game_manager_instance.get_board()
    return chess.Board()

def getFEN():
    """Backward compatibility wrapper for GameManager.get_fen."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        return _game_manager_instance.get_fen()
    return STARTING_FEN

def resetMoveState():
    """Backward compatibility wrapper for GameManager.reset_move_state."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.reset_move_state()

def resetBoard():
    """Backward compatibility wrapper for GameManager.reset_board."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.reset_board()

def computerMove(mv, forced=True):
    """Backward compatibility wrapper for GameManager.computer_move."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.computer_move(mv, forced)

def setGameInfo(gi_event, gi_site, gi_round, gi_white, gi_black):
    """Backward compatibility wrapper for GameManager.set_game_info."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.set_game_info(gi_event, gi_site, gi_round, gi_white, gi_black)

def resignGame(sideresigning):
    """Backward compatibility wrapper for GameManager.resign_game."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.resign_game(sideresigning)

def getResult():
    """Backward compatibility wrapper for GameManager.get_result."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        return _game_manager_instance.get_result()
    return "Unknown"

def drawGame():
    """Backward compatibility wrapper for GameManager.draw_game."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.draw_game()

def setClock(white, black):
    """Backward compatibility wrapper for GameManager.set_clock."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.set_clock(white, black)

def startClock():
    """Backward compatibility wrapper for GameManager.start_clock."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.start_clock()


# Note: For backward compatibility with code that imports gamemanager,
# the game module should re-export these functions. The games module
# provides a cleaner class-based interface.

