# Chess Game Manager
#
# This script manages a chess game, passing events and moves back to the calling script with callbacks.
# The calling script is expected to manage the display itself using epaper.py.
# Calling script initialises with subscribeGame(eventCallback, moveCallback, keyCallback)
# eventCallback feeds back events such as start of game, gameover
# moveCallback feeds back the chess moves made on the board
# keyCallback feeds back key presses from keys under the display
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
from DGTCentaurMods.display import epaper
from DGTCentaurMods.db import models
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, MetaData, func, select
from scipy.optimize import linear_sum_assignment
import threading
import time
import chess
import sys
import inspect
import numpy as np
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
STARTING_POSITION_STATE = bytearray(
    b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
)


class ClockManager:
    """Manages chess clock timing and display updates."""
    
    def __init__(self):
        self.white_time_seconds = 0
        self.black_time_seconds = 0
        self.is_running = False
        self.clock_thread = None
        self.is_showing_promotion = False
    
    def set_times(self, white_seconds: int, black_seconds: int):
        """Set the initial clock times for both players."""
        self.white_time_seconds = white_seconds
        self.black_time_seconds = black_seconds
    
    def format_time_display(self) -> str:
        """Format time display string for clock."""
        white_minutes = self.white_time_seconds // SECONDS_PER_MINUTE
        white_seconds = self.white_time_seconds % SECONDS_PER_MINUTE
        black_minutes = self.black_time_seconds // SECONDS_PER_MINUTE
        black_seconds = self.black_time_seconds % SECONDS_PER_MINUTE
        return (f"{white_minutes:02d}:{white_seconds:02d}       "
                f"{black_minutes:02d}:{black_seconds:02d}")
    
    def _update_clock_thread(self, chess_board, kill_flag):
        """Thread function that decrements clock and updates display."""
        while not kill_flag[0]:
            time.sleep(CLOCK_DECREMENT_SECONDS)
            
            # Only decrement active player's clock if game has started
            if chess_board.fen() != STARTING_FEN:
                if (self.white_time_seconds > 0 and 
                    chess_board.turn == chess.WHITE):
                    self.white_time_seconds -= CLOCK_DECREMENT_SECONDS
                
                if (self.black_time_seconds > 0 and 
                    chess_board.turn == chess.BLACK):
                    self.black_time_seconds -= CLOCK_DECREMENT_SECONDS
            
            # Update display unless showing promotion menu
            if not self.is_showing_promotion:
                time_str = self.format_time_display()
                epaper.writeText(CLOCK_DISPLAY_LINE, time_str)
    
    def start(self, chess_board, kill_flag):
        """Start the clock thread."""
        if self.clock_thread is None or not self.clock_thread.is_alive():
            self.is_running = True
            time_str = self.format_time_display()
            epaper.writeText(CLOCK_DISPLAY_LINE, time_str)
            self.clock_thread = threading.Thread(
                target=self._update_clock_thread,
                args=(chess_board, kill_flag)
            )
            self.clock_thread.daemon = True
            self.clock_thread.start()


class MoveState:
    """Manages move-related state during game play."""
    
    def __init__(self):
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_squares = []
        self.computer_move = ""
        self.is_forced_move = False
    
    def reset(self):
        """Reset all move state variables."""
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_squares = []
        self.computer_move = ""
        self.is_forced_move = False
        board.ledsOff()


class GameState:
    """Manages overall game state and board history."""
    
    def __init__(self):
        self.chess_board = chess.Board()
        self.board_states = []
        self.game_database_id = -1
        self.is_in_menu = False
        self.is_showing_promotion = False
    
    def collect_board_state(self):
        """Append current board state to history."""
        current_state = board.getChessState()
        self.board_states.append(current_state)
        log.info(f"[GameState.collectBoardState] Collected board state, total states: {len(self.board_states)}")
    
    def is_starting_position(self, board_state) -> bool:
        """Check if board state matches starting position."""
        if board_state is None or len(board_state) != BOARD_SIZE:
            return False
        return bytearray(board_state) == STARTING_POSITION_STATE
    
    def reset_to_starting_position(self):
        """Reset chess board to starting position."""
        self.chess_board.reset()
        paths.write_fen_log(self.chess_board.fen())


class CorrectionMode:
    """Manages correction mode for fixing misplaced pieces."""
    
    def __init__(self):
        self.is_active = False
        self.expected_state = None
        self.just_exited = False
    
    def enter(self, expected_state):
        """Enter correction mode with expected board state."""
        self.is_active = True
        self.expected_state = expected_state
        self.just_exited = False
        log.warning("[CorrectionMode] Entered correction mode")
    
    def exit(self):
        """Exit correction mode."""
        self.is_active = False
        self.expected_state = None
        self.just_exited = True
        log.warning("[CorrectionMode] Exited correction mode")
    
    def validate_board_state(self, current_state) -> bool:
        """Validate if current board state matches expected state."""
        if current_state is None or self.expected_state is None:
            return False
        
        if len(current_state) != BOARD_SIZE or len(self.expected_state) != BOARD_SIZE:
            return False
        
        return bytearray(current_state) == bytearray(self.expected_state)


class GameManager:
    """Main game manager coordinating all game components."""
    
    def __init__(self):
        self.clock_manager = ClockManager()
        self.move_state = MoveState()
        self.game_state = GameState()
        self.correction_mode = CorrectionMode()
        
        self.key_callback = None
        self.move_callback = None
        self.event_callback = None
        self.takeback_callback = None
        
        self.game_info_event = ""
        self.game_info_site = ""
        self.game_info_round = ""
        self.game_info_white = ""
        self.game_info_black = ""
        
        self.database_session = None
        self.source_file = ""
        self.kill_flag = [False]
    
    def _convert_uci_to_squares(self, uci_move: str) -> tuple:
        """Convert UCI move string to square indices."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return None, None
        
        from_square = ((ord(uci_move[1:2]) - ord("1")) * BOARD_WIDTH) + (
            ord(uci_move[0:1]) - ord("a")
        )
        to_square = ((ord(uci_move[3:4]) - ord("1")) * BOARD_WIDTH) + (
            ord(uci_move[2:3]) - ord("a")
        )
        return from_square, to_square
    
    def _calculate_legal_squares(self, source_square: int) -> list:
        """Calculate legal destination squares for a piece at given square."""
        legal_moves = self.game_state.chess_board.legal_moves
        legal_squares = [source_square]  # Include source square
        
        for move in legal_moves:
            if move.from_square == source_square:
                legal_squares.append(move.to_square)
        
        return legal_squares
    
    def _handle_promotion(self, target_square: int, piece_symbol: str, is_forced: bool) -> str:
        """Handle pawn promotion by prompting user for piece choice."""
        is_white_promotion = (
            (target_square // BOARD_WIDTH) == PROMOTION_ROW_WHITE and 
            piece_symbol == "P"
        )
        is_black_promotion = (
            (target_square // BOARD_WIDTH) == PROMOTION_ROW_BLACK and 
            piece_symbol == "p"
        )
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        if not is_forced:
            screen_backup = epaper.epaperbuffer.copy()
            self.game_state.is_showing_promotion = True
            self.clock_manager.is_showing_promotion = True
            epaper.promotionOptions(PROMOTION_DISPLAY_LINE)
            promotion_choice = self._wait_for_promotion_choice()
            self.game_state.is_showing_promotion = False
            self.clock_manager.is_showing_promotion = False
            epaper.epaperbuffer = screen_backup.copy()
            return promotion_choice
        
        return ""
    
    def _wait_for_promotion_choice(self) -> str:
        """Wait for user to select promotion piece via button press."""
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
    
    def _switch_turn_with_event(self):
        """Trigger appropriate event callback based on current turn."""
        if self.event_callback is not None:
            if self.game_state.chess_board.turn == chess.WHITE:
                self.event_callback(EVENT_WHITE_TURN)
            else:
                self.event_callback(EVENT_BLACK_TURN)
    
    def _update_game_result(self, result_string: str, termination: str, context: str = ""):
        """Update game result in database and trigger event callback."""
        if self.game_state.game_database_id >= 0:
            game_record = self.database_session.query(models.Game).filter(
                models.Game.id == self.game_state.game_database_id
            ).first()
            
            if game_record is not None:
                game_record.result = result_string
                self.database_session.flush()
                self.database_session.commit()
            else:
                log.warning(
                    f"[GameManager.{context}] Game with id {self.game_state.game_database_id} "
                    f"not found in database, cannot update result"
                )
        
        if self.event_callback is not None:
            self.event_callback(termination)
    
    def _check_takeback(self) -> bool:
        """Check if current board state matches previous state (takeback detected)."""
        if self.takeback_callback is None or len(self.game_state.board_states) <= 1:
            return False
        
        current_state = board.getChessState()
        previous_state = self.game_state.board_states[-2]
        
        if bytearray(current_state) == bytearray(previous_state):
            board.ledsOff()
            self.game_state.board_states.pop()
            
            # Remove last move from database
            last_move = self.database_session.query(models.GameMove).order_by(
                models.GameMove.id.desc()
            ).first()
            if last_move:
                self.database_session.delete(last_move)
                self.database_session.commit()
            
            # Pop move from chess board
            self.game_state.chess_board.pop()
            paths.write_fen_log(self.game_state.chess_board.fen())
            board.beep(board.SOUND_GENERAL)
            self.takeback_callback()
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            current = board.getChessState()
            if not self._validate_board_state(current, self.game_state.board_states[-1] if self.game_state.board_states else None):
                log.info("[GameManager._check_takeback] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            return True
        
        return False
    
    def _validate_board_state(self, current_state, expected_state) -> bool:
        """Validate board state by comparing piece presence."""
        if current_state is None or expected_state is None:
            return False
        
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return False
        
        return bytearray(current_state) == bytearray(expected_state)
    
    def _provide_correction_guidance(self, current_state, expected_state):
        """Provide LED guidance to correct misplaced pieces using Hungarian algorithm."""
        if current_state is None or expected_state is None:
            return
        
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return
        
        def _row_col(idx):
            """Convert square index to (row, col)."""
            return (idx // BOARD_WIDTH), (idx % BOARD_WIDTH)
        
        def _manhattan_distance(a, b):
            """Manhattan distance between two squares."""
            ar, ac = _row_col(a)
            br, bc = _row_col(b)
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
        
        log.warning(
            f"[GameManager._provide_correction_guidance] Found {len(wrong_locations)} "
            f"wrong pieces, {len(missing_origins)} missing pieces"
        )
        
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
                        costs[i, j] = _manhattan_distance(wl, mo)
                
                row_ind, col_ind = linear_sum_assignment(costs)
                from_idx = wrong_locations[row_ind[0]]
                to_idx = missing_origins[col_ind[0]]
            
            board.ledsOff()
            board.ledFromTo(from_idx, to_idx, intensity=5)
            log.warning(
                f"[GameManager._provide_correction_guidance] Guiding piece from "
                f"{chess.square_name(from_idx)} to {chess.square_name(to_idx)}"
            )
        else:
            if len(missing_origins) > 0:
                board.ledsOff()
                for idx in missing_origins:
                    board.led(idx, intensity=5)
                log.warning(
                    f"[GameManager._provide_correction_guidance] Pieces missing at: "
                    f"{[chess.square_name(sq) for sq in missing_origins]}"
                )
            elif len(wrong_locations) > 0:
                board.ledsOff()
                for idx in wrong_locations:
                    board.led(idx, intensity=5)
                log.warning(
                    f"[GameManager._provide_correction_guidance] Extra pieces at: "
                    f"{[chess.square_name(sq) for sq in wrong_locations]}"
                )
    
    def _enter_correction_mode(self):
        """Enter correction mode to guide user in fixing board state."""
        expected_state = (
            self.game_state.board_states[-1] 
            if self.game_state.board_states 
            else None
        )
        self.correction_mode.enter(expected_state)
    
    def _exit_correction_mode(self):
        """Exit correction mode and restore forced move LEDs if needed."""
        self.correction_mode.exit()
        
        # Reset move state variables
        self.move_state.source_square = INVALID_SQUARE
        self.move_state.legal_squares = []
        self.move_state.opponent_source_square = INVALID_SQUARE
        
        # Restore forced move LEDs if pending
        if (self.move_state.is_forced_move and 
            self.move_state.computer_move and 
            len(self.move_state.computer_move) >= MIN_UCI_MOVE_LENGTH):
            from_sq, to_sq = self._convert_uci_to_squares(self.move_state.computer_move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
                log.info(
                    f"[GameManager._exit_correction_mode] Restored forced move LEDs: "
                    f"{self.move_state.computer_move}"
                )
    
    def _handle_field_event_in_correction_mode(self, piece_event: int, field: int) -> bool:
        """Handle field events during correction mode. Returns True if handled."""
        if not self.correction_mode.is_active:
            return False
        
        current_state = board.getChessState()
        
        # Check if board is in starting position (new game detection)
        if self.game_state.is_starting_position(current_state):
            log.info(
                "[GameManager._handle_field_event_in_correction_mode] Starting position detected "
                "while in correction mode - exiting correction and triggering new game"
            )
            board.ledsOff()
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            self._reset_game()
            return True
        
        # Check if board is now correct
        if self.correction_mode.validate_board_state(current_state):
            log.info("[GameManager._handle_field_event_in_correction_mode] Board corrected, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            return True
        
        # Still incorrect, update guidance
        self._provide_correction_guidance(current_state, self.correction_mode.expected_state)
        return True
    
    def _handle_field_lift(self, field: int, piece_color):
        """Handle piece lift event."""
        is_valid_piece = (
            (self.game_state.chess_board.turn == chess.WHITE) == (piece_color == True)
        )
        
        # Generate legal squares if valid piece lifted
        if (field not in self.move_state.legal_squares and 
            self.move_state.source_square < 0 and 
            is_valid_piece):
            self.move_state.legal_squares = self._calculate_legal_squares(field)
            self.move_state.source_square = field
        
        # Track opponent piece lifts
        if not is_valid_piece:
            self.move_state.opponent_source_square = field
        
        # Handle forced move
        if self.move_state.is_forced_move and is_valid_piece:
            field_name = chess.square_name(field)
            if field_name != self.move_state.computer_move[0:2]:
                # Wrong piece lifted for forced move
                self.move_state.legal_squares = [field]
            else:
                # Correct piece, limit to target square
                target = self.move_state.computer_move[2:4]
                target_square = chess.parse_square(target)
                self.move_state.legal_squares = [target_square]
    
    def _handle_field_place(self, field: int, piece_color) -> bool:
        """Handle piece place event. Returns True if move was made."""
        is_valid_piece = (
            (self.game_state.chess_board.turn == chess.WHITE) == (piece_color == True)
        )
        
        # Handle opponent piece placed back
        if (not is_valid_piece and 
            self.move_state.opponent_source_square >= 0 and 
            field == self.move_state.opponent_source_square):
            board.ledsOff()
            self.move_state.opponent_source_square = INVALID_SQUARE
            return False
        
        # Ignore stale PLACE events without corresponding LIFT
        if (self.move_state.source_square < 0 and 
            self.move_state.opponent_source_square < 0):
            if self.correction_mode.just_exited:
                # Check if this is forced move source square
                if (self.move_state.is_forced_move and 
                    self.move_state.computer_move and 
                    len(self.move_state.computer_move) >= MIN_UCI_MOVE_LENGTH):
                    forced_source = chess.parse_square(self.move_state.computer_move[0:2])
                    if field != forced_source:
                        log.info(
                            f"[GameManager._handle_field_place] Ignoring stale PLACE event "
                            f"after correction exit for field {field}"
                        )
                        self.correction_mode.just_exited = False
                        return False
                else:
                    log.info(
                        f"[GameManager._handle_field_place] Ignoring stale PLACE event "
                        f"after correction exit for field {field}"
                    )
                    self.correction_mode.just_exited = False
                    return False
            
            # For forced moves, ignore stale PLACE on source square
            if (self.move_state.is_forced_move == 1 and 
                self.move_state.computer_move and 
                len(self.move_state.computer_move) >= MIN_UCI_MOVE_LENGTH):
                forced_source = chess.parse_square(self.move_state.computer_move[0:2])
                if field == forced_source:
                    log.info(
                        f"[GameManager._handle_field_place] Ignoring stale PLACE event "
                        f"for forced move source field {field}"
                    )
                    self.correction_mode.just_exited = False
                    return False
            
            if not self.move_state.is_forced_move:
                log.info(
                    f"[GameManager._handle_field_place] Ignoring stale PLACE event "
                    f"for field {field} (no corresponding LIFT)"
                )
                self.correction_mode.just_exited = False
                return False
        
        # Clear correction flag on valid LIFT
        if self.move_state.source_square >= 0:
            self.correction_mode.just_exited = False
        
        # Handle illegal placement
        if field not in self.move_state.legal_squares:
            board.beep(board.SOUND_WRONG_MOVE)
            log.warning(f"[GameManager._handle_field_place] Piece placed on illegal square {field}")
            is_takeback = self._check_takeback()
            if not is_takeback:
                self._enter_correction_mode()
            return False
        
        # Handle piece placed back on source
        if field == self.move_state.source_square:
            board.ledsOff()
            self.move_state.source_square = INVALID_SQUARE
            self.move_state.legal_squares = []
            return False
        
        # Make the move
        from_name = chess.square_name(self.move_state.source_square)
        to_name = chess.square_name(field)
        piece_symbol = str(self.game_state.chess_board.piece_at(self.move_state.source_square))
        promotion_suffix = self._handle_promotion(
            field, piece_symbol, self.move_state.is_forced_move
        )
        
        if self.move_state.is_forced_move:
            move_uci = self.move_state.computer_move
        else:
            move_uci = from_name + to_name + promotion_suffix
        
        # Execute move
        self.game_state.chess_board.push(chess.Move.from_uci(move_uci))
        paths.write_fen_log(self.game_state.chess_board.fen())
        
        # Log move to database
        game_move = models.GameMove(
            gameid=self.game_state.game_database_id,
            move=move_uci,
            fen=str(self.game_state.chess_board.fen())
        )
        self.database_session.add(game_move)
        self.database_session.commit()
        
        self.game_state.collect_board_state()
        self.move_state.reset()
        
        if self.move_callback is not None:
            self.move_callback(move_uci)
        
        board.beep(board.SOUND_GENERAL)
        board.led(field)
        
        # Check game outcome
        outcome = self.game_state.chess_board.outcome(claim_draw=True)
        if outcome is None:
            self._switch_turn_with_event()
        else:
            board.beep(board.SOUND_GENERAL)
            result_string = str(self.game_state.chess_board.result())
            termination = str(outcome.termination)
            self._update_game_result(result_string, termination, "_handle_field_place")
        
        return True
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """Handle field events (piece lift/place)."""
        field_name = chess.square_name(field)
        piece_color = self.game_state.chess_board.color_at(field)
        
        log.info(
            f"[GameManager._field_callback] piece_event={piece_event} field={field} "
            f"fieldname={field_name} color_at={'White' if piece_color else 'Black'} "
            f"time_in_seconds={time_in_seconds}"
        )
        
        # Check for starting position detection (all pieces in start position triggers new game)
        current_state = board.getChessState()
        if (current_state is not None and 
            self.game_state.is_starting_position(current_state) and
            len(self.game_state.board_states) > 0 and
            self.game_state.chess_board.fen() != STARTING_FEN):
            log.info(
                "[GameManager._field_callback] Starting position detected - "
                "all pieces in start position, triggering new game"
            )
            board.ledsOff()
            board.beep(board.SOUND_GENERAL)
            self._reset_game()
            return
        
        # Handle correction mode
        if self._handle_field_event_in_correction_mode(piece_event, field):
            return
        
        is_lift = (piece_event == 0)
        is_place = (piece_event == 1)
        piece_color_bool = piece_color == True
        
        if is_lift:
            self._handle_field_lift(field, piece_color_bool)
        elif is_place:
            self._handle_field_place(field, piece_color_bool)
    
    def _correction_field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """Wrapper that intercepts field events during correction mode."""
        if not self.correction_mode.is_active:
            return self._field_callback(piece_event, field, time_in_seconds)
        
        return self._handle_field_event_in_correction_mode(piece_event, field)
    
    def _key_callback(self, key_pressed):
        """Handle key press events."""
        if self.key_callback is not None:
            if self.game_state.is_in_menu == 0 and key_pressed != board.Key.HELP:
                self.key_callback(key_pressed)
            
            if self.game_state.is_in_menu == 0 and key_pressed == board.Key.HELP:
                self.game_state.is_in_menu = 1
                epaper.resignDrawMenu(14)
            
            if self.game_state.is_in_menu == 1 and key_pressed == board.Key.BACK:
                epaper.writeText(14, "                   ")
                self.game_state.is_in_menu = 0
            
            if self.game_state.is_in_menu == 1 and key_pressed == board.Key.UP:
                epaper.writeText(14, "                   ")
                if self.event_callback is not None:
                    self.event_callback(EVENT_REQUEST_DRAW)
                self.game_state.is_in_menu = 0
            
            if self.game_state.is_in_menu == 1 and key_pressed == board.Key.DOWN:
                epaper.writeText(14, "                   ")
                if self.event_callback is not None:
                    self.event_callback(EVENT_RESIGN_GAME)
                self.game_state.is_in_menu = 0
    
    def _reset_game(self):
        """Reset game to starting position and trigger new game event."""
        try:
            log.info("[GameManager._reset_game] Detected starting position - triggering NEW_GAME")
            
            # Reset move state
            self.move_state.reset()
            
            # Reset board
            self.game_state.reset_to_starting_position()
            
            # Double beep notification
            board.beep(board.SOUND_GENERAL)
            time.sleep(0.3)
            board.beep(board.SOUND_GENERAL)
            
            board.ledsOff()
            
            # Trigger events
            if self.event_callback is not None:
                self.event_callback(EVENT_NEW_GAME)
                self.event_callback(EVENT_WHITE_TURN)
            
            # Log new game to database
            game_record = models.Game(
                source=self.source_file,
                event=self.game_info_event,
                site=self.game_info_site,
                round=self.game_info_round,
                white=self.game_info_white,
                black=self.game_info_black
            )
            log.info(game_record)
            self.database_session.add(game_record)
            self.database_session.commit()
            
            # Get game ID
            self.game_state.game_database_id = (
                self.database_session.query(func.max(models.Game.id)).scalar()
            )
            
            # Log starting position
            starting_move = models.GameMove(
                gameid=self.game_state.game_database_id,
                move='',
                fen=str(self.game_state.chess_board.fen())
            )
            self.database_session.add(starting_move)
            self.database_session.commit()
            
            # Reset board states
            self.game_state.board_states = []
            self.game_state.collect_board_state()
            
        except Exception as e:
            log.error(f"[GameManager._reset_game] Error resetting game: {e}")
            import traceback
            traceback.print_exc()
    
    def _game_thread(self, event_callback, move_callback, key_callback, takeback_callback):
        """Main game thread handling chess game functionality."""
        self.key_callback = key_callback
        self.move_callback = move_callback
        self.event_callback = event_callback
        self.takeback_callback = takeback_callback
        
        board.ledsOff()
        log.info("[GameManager._game_thread] Subscribing to events")
        
        try:
            board.subscribeEvents(self._key_callback, self._correction_field_callback)
        except Exception as e:
            log.error(f"[GameManager._game_thread] error: {e}")
            log.error(f"[GameManager._game_thread] error: {sys.exc_info()[1]}")
            return
        
        # Monitor for starting position to trigger new game
        last_state_check = time.time()
        while not self.kill_flag[0]:
            time.sleep(0.1)
            
            # Check for starting position periodically
            if time.time() - last_state_check > 0.5:
                current_state = board.getChessState()
                if (current_state is not None and 
                    self.game_state.is_starting_position(current_state) and
                    len(self.game_state.board_states) > 0):
                    # Only trigger if we're not already at starting position
                    if (self.game_state.chess_board.fen() != STARTING_FEN):
                        log.info("[GameManager._game_thread] Starting position detected, resetting game")
                        self._reset_game()
                last_state_check = time.time()
    
    def set_game_info(self, event: str, site: str, round_str: str, white: str, black: str):
        """Set game information for PGN files."""
        self.game_info_event = event
        self.game_info_site = site
        self.game_info_round = round_str
        self.game_info_white = white
        self.game_info_black = black
    
    def set_clock(self, white_seconds: int, black_seconds: int):
        """Set the clock times for both players."""
        self.clock_manager.set_times(white_seconds, black_seconds)
    
    def start_clock(self):
        """Start the clock thread."""
        self.clock_manager.start(self.game_state.chess_board, self.kill_flag)
    
    def computer_move(self, move_uci: str, forced: bool = True):
        """Set the computer move that the player is expected to make."""
        if len(move_uci) < MIN_UCI_MOVE_LENGTH:
            return
        
        self.move_state.computer_move = move_uci
        self.move_state.is_forced_move = forced
        
        from_sq, to_sq = self._convert_uci_to_squares(move_uci)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
    
    def reset_move_state(self):
        """Reset all move-related state variables."""
        self.move_state.reset()
    
    def reset_board(self):
        """Reset the chess board to starting position."""
        self.game_state.reset_to_starting_position()
    
    def get_board(self):
        """Get the current chess board state."""
        return self.game_state.chess_board
    
    def get_fen(self):
        """Get current board position as FEN string."""
        return self.game_state.chess_board.fen()
    
    def resign_game(self, side_resigning: int):
        """Handle game resignation. side_resigning: 1 for white, 2 for black."""
        result_string = "0-1" if side_resigning == 1 else "1-0"
        self._update_game_result(result_string, "Termination.RESIGN", "resign_game")
    
    def draw_game(self):
        """Handle game draw."""
        self._update_game_result("1/2-1/2", "Termination.DRAW", "draw_game")
    
    def get_result(self):
        """Get the result of the last game."""
        game_data = self.database_session.execute(
            select(
                models.Game.created_at, models.Game.source, models.Game.event,
                models.Game.site, models.Game.round, models.Game.white,
                models.Game.black, models.Game.result, models.Game.id
            ).order_by(models.Game.id.desc())
        ).first()
        
        if game_data is not None:
            return str(game_data.result)
        else:
            return "Unknown"
    
    def subscribe_game(self, event_callback, move_callback, key_callback, takeback_callback=None):
        """Subscribe to the game manager."""
        self.source_file = inspect.getsourcefile(sys._getframe(1))
        Session = sessionmaker(bind=models.engine)
        self.database_session = Session()
        
        self.game_state.board_states = []
        self.game_state.collect_board_state()
        
        game_thread = threading.Thread(
            target=self._game_thread,
            args=(event_callback, move_callback, key_callback, takeback_callback)
        )
        game_thread.daemon = True
        game_thread.start()
    
    def unsubscribe_game(self):
        """Stop the game manager."""
        self.kill_flag[0] = True
        board.ledsOff()
        
        if self.database_session is not None:
            try:
                self.database_session.close()
                self.database_session = None
            except Exception:
                self.database_session = None


# Global instance for backward compatibility
_game_manager_instance = GameManager()


def subscribeGame(eventCallback, moveCallback, keyCallback, takebackCallback=None):
    """Subscribe to the game manager (backward compatibility)."""
    _game_manager_instance.subscribe_game(
        eventCallback, moveCallback, keyCallback, takebackCallback
    )


def unsubscribeGame():
    """Unsubscribe from the game manager (backward compatibility)."""
    _game_manager_instance.unsubscribe_game()


def setGameInfo(event, site, round_str, white, black):
    """Set game information (backward compatibility)."""
    _game_manager_instance.set_game_info(event, site, round_str, white, black)


def setClock(white, black):
    """Set clock times (backward compatibility)."""
    _game_manager_instance.set_clock(white, black)


def startClock():
    """Start the clock (backward compatibility)."""
    _game_manager_instance.start_clock()


def computerMove(mv, forced=True):
    """Set computer move (backward compatibility)."""
    _game_manager_instance.computer_move(mv, forced)


def resetMoveState():
    """Reset move state (backward compatibility)."""
    _game_manager_instance.reset_move_state()


def resetBoard():
    """Reset board (backward compatibility)."""
    _game_manager_instance.reset_board()


def getBoard():
    """Get chess board (backward compatibility)."""
    return _game_manager_instance.get_board()


def getFEN():
    """Get FEN string (backward compatibility)."""
    return _game_manager_instance.get_fen()


def resignGame(side_resigning):
    """Resign game (backward compatibility)."""
    _game_manager_instance.resign_game(side_resigning)


def drawGame():
    """Draw game (backward compatibility)."""
    _game_manager_instance.draw_game()


def getResult():
    """Get game result (backward compatibility)."""
    return _game_manager_instance.get_result()

