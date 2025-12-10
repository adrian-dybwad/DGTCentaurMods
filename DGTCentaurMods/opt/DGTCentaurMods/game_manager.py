# Game Manager
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.
#
# This script manages a chess game, passing events and moves back to the calling script with callbacks.
# The calling script is expected to manage the display using the centralized epaper service.
# Calling script initialises with subscribeGame(eventCallback, moveCallback, keyCallback)
# eventCallback feeds back events such as start of game, gameover
# moveCallback feeds back the chess moves made on the board
# keyCallback feeds back key presses from keys under the display

from DGTCentaurMods.board import board
from DGTCentaurMods.db import models
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func, select, create_engine
from scipy.optimize import linear_sum_assignment
import threading
import time
import chess
import sys
import inspect
import numpy as np
from DGTCentaurMods.config import paths
from DGTCentaurMods.board.logging import log


# Event constants
EVENT_NEW_GAME = 1
EVENT_BLACK_TURN = 2
EVENT_WHITE_TURN = 3
EVENT_REQUEST_DRAW = 4
EVENT_RESIGN_GAME = 5
EVENT_LIFT_PIECE = 6
EVENT_PLACE_PIECE = 7

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

# Starting position: pieces on ranks 1, 2, 7, 8 (squares 0-15 and 48-63)
STARTING_POSITION_STATE = bytearray(
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 1 (squares 0-7)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 2 (squares 8-15)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 3 (squares 16-23)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 4 (squares 24-31)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 5 (squares 32-39)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 6 (squares 40-47)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 7 (squares 48-55)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 8 (squares 56-63)
)


class ClockManager:
    """Manages chess clock timing and display."""
    
    def __init__(self, display_line: int = CLOCK_DISPLAY_LINE):
        self.white_time_seconds = 0
        self.black_time_seconds = 0
        self.display_line = display_line
        self.is_running = False
        self.clock_thread = None
        self.should_stop = False
    
    def set_times(self, white_seconds: int, black_seconds: int):
        """Set the clock times for both players."""
        self.white_time_seconds = white_seconds
        self.black_time_seconds = black_seconds
    
    def format_time(self, white_seconds: int, black_seconds: int) -> str:
        """Format time display string for clock."""
        white_minutes = white_seconds // SECONDS_PER_MINUTE
        white_secs = white_seconds % SECONDS_PER_MINUTE
        black_minutes = black_seconds // SECONDS_PER_MINUTE
        black_secs = black_seconds % SECONDS_PER_MINUTE
        return f"{white_minutes:02d}:{white_secs:02d}       {black_minutes:02d}:{black_secs:02d}"
    
    def _update_clock(self, current_turn: bool, is_starting_position: bool, showing_promotion: bool):
        """Update clock times based on current turn."""
        if current_turn == chess.WHITE and not is_starting_position:
            if self.white_time_seconds > 0:
                self.white_time_seconds = max(0, self.white_time_seconds - CLOCK_DECREMENT_SECONDS)
        elif current_turn == chess.BLACK:
            if self.black_time_seconds > 0:
                self.black_time_seconds = max(0, self.black_time_seconds - CLOCK_DECREMENT_SECONDS)
        
        if not showing_promotion:
            time_string = self.format_time(self.white_time_seconds, self.black_time_seconds)
            # TODO: Replace with proper clock widget display
            # The old widgets.write_text() no longer exists
            log.debug(f"[ClockManager] Time: {time_string}")
    
    def start(self, current_turn_getter, is_starting_position_getter, showing_promotion_getter):
        """Start the clock thread."""
        if self.is_running:
            return
        
        self.should_stop = False
        self.is_running = True
        
        def clock_thread():
            while not self.should_stop:
                time.sleep(CLOCK_DECREMENT_SECONDS)
                current_turn = current_turn_getter()
                is_starting = is_starting_position_getter()
                showing_promo = showing_promotion_getter()
                self._update_clock(current_turn, is_starting, showing_promo)
        
        self.clock_thread = threading.Thread(target=clock_thread, daemon=True)
        self.clock_thread.start()
        
        # Initial display
        time_string = self.format_time(self.white_time_seconds, self.black_time_seconds)
        # TODO: Replace with proper clock widget display
        log.debug(f"[ClockManager] Initial time: {time_string}")
    
    def stop(self):
        """Stop the clock thread."""
        self.should_stop = True
        self.is_running = False


class MoveState:
    """Tracks the state of a move in progress."""
    
    def __init__(self):
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_destination_squares = []
        self.computer_move_uci = ""
        self.is_forced_move = False
        self.source_piece_color = None  # Store piece color when lifted (for captures)
    
    def reset(self):
        """Reset all move state variables."""
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_destination_squares = []
        self.computer_move_uci = ""
        self.is_forced_move = False
        self.source_piece_color = None
    
    def set_computer_move(self, uci_move: str, forced: bool = True):
        """Set the computer move that the player is expected to make."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return False
        self.computer_move_uci = uci_move
        self.is_forced_move = forced
        return True


class CorrectionMode:
    """Manages correction mode for fixing misplaced pieces."""
    
    def __init__(self):
        self.is_active = False
        self.expected_state = None
        self.just_exited = False
    
    def enter(self, expected_state):
        """Enter correction mode."""
        self.is_active = True
        self.expected_state = expected_state
        self.just_exited = False
    
    def exit(self):
        """Exit correction mode."""
        self.is_active = False
        self.expected_state = None
        self.just_exited = True
    
    def clear_exit_flag(self):
        """Clear the just-exited flag."""
        self.just_exited = False


class GameManager:
    """Manages chess game state, moves, and board interactions.
    
    The logical chess board (self.chess_board) is the AUTHORITY for game state.
    The physical board state must conform to the logical board state.
    When there's a mismatch, correction mode guides the user to fix the physical board.
    """
    
    def __init__(self):
        # Logical chess board - this is the AUTHORITY for game state
        # Physical board must conform to this state
        self.chess_board = chess.Board()
        self.clock_manager = ClockManager()
        self.move_state = MoveState()
        self.correction_mode = CorrectionMode()
        
        # Callbacks
        self.event_callback = None
        self.move_callback = None
        self.key_callback = None
        self.takeback_callback = None
        
        # Game metadata
        self.game_info = {
            'event': '',
            'site': '',
            'round': '',
            'white': '',
            'black': ''
        }
        self.source_file = ""
        self.game_db_id = -1
        self.database_session = None
        self.database_engine = None  # Engine created in game thread
        self.cached_result = None  # Cache game result for thread-safe access
        
        # UI state
        self.is_showing_promotion = False
        self.is_in_menu = False
        
        # UI callbacks (set by DisplayManager)
        # on_promotion_needed(is_white: bool) -> str: Called when promotion piece selection needed
        # on_back_pressed() -> None: Called when BACK pressed during game (show resign/draw menu)
        self.on_promotion_needed = None
        self.on_back_pressed = None
        
        # Thread control
        self.should_stop = False
        self.game_thread = None
        self._stop_event = threading.Event()
    
    def _is_starting_position(self, board_state) -> bool:
        """Check if the board is in the starting position."""
        if board_state is None or len(board_state) != BOARD_SIZE:
            return False
        return bytearray(board_state) == STARTING_POSITION_STATE
    
    def _chess_board_to_state(self, chess_board: chess.Board) -> bytearray:
        """Convert chess board object to board state bytearray.
        
        Args:
            chess_board: The chess.Board object representing the logical game state
            
        Returns:
            bytearray: Board state where 1 indicates a piece is present, 0 indicates empty
            
        Raises:
            ValueError: If chess_board is None or invalid
        """
        if chess_board is None:
            raise ValueError("chess_board cannot be None")
        
        state = bytearray(BOARD_SIZE)
        try:
            for square in range(BOARD_SIZE):
                piece = chess_board.piece_at(square)
                state[square] = 1 if piece is not None else 0
        except Exception as e:
            log.error(f"[GameManager._chess_board_to_state] Error converting chess board to state: {e}")
            raise ValueError(f"Failed to convert chess board to state: {e}") from e
        
        return state
    
    def _validate_board_state(self, current_state, expected_state) -> bool:
        """Validate board state by comparing piece presence."""
        if current_state is None or expected_state is None:
            return False
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return False
        return bytearray(current_state) == bytearray(expected_state)
    
    def _uci_to_squares(self, uci_move: str):
        """Convert UCI move string to square indices."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return None, None
        from_square = ((ord(uci_move[1:2]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[0:1]) - ord("a"))
        to_square = ((ord(uci_move[3:4]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[2:3]) - ord("a"))
        return from_square, to_square
    
    def _calculate_legal_squares(self, source_square: int) -> list:
        """Calculate legal destination squares for a piece at the given square."""
        legal_destinations = [source_square]  # Include source square
        for move in self.chess_board.legal_moves:
            if move.from_square == source_square:
                legal_destinations.append(move.to_square)
        return legal_destinations
    
    def _switch_turn_with_event(self):
        """Trigger appropriate event callback based on current turn."""
        if self.event_callback is not None:
            if self.chess_board.turn == chess.WHITE:
                self.event_callback(EVENT_WHITE_TURN)
            else:
                self.event_callback(EVENT_BLACK_TURN)
    
    def _update_game_result(self, result_string: str, termination: str, context: str = ""):
        """Update game result in database and trigger event callback."""
        # Only update database if game has been properly initialized
        # This prevents database operations with invalid game ID (game_db_id = -1) before _reset_game() is called
        if self.database_session is not None and self.game_db_id >= 0:
            game_record = self.database_session.query(models.Game).filter(
                models.Game.id == self.game_db_id
            ).first()
            if game_record is not None:
                game_record.result = result_string
                self.database_session.flush()
                self.database_session.commit()
                self.cached_result = result_string  # Cache the result for thread-safe access
                log.info(f"[GameManager.{context}] Updated game result in database: id={self.game_db_id}, result={result_string}, termination={termination}")
            else:
                log.warning(f"[GameManager.{context}] Game with id {self.game_db_id} not found in database. Result: {result_string}, termination: {termination}")
                # Cache the result even if not found in database
                self.cached_result = result_string
        elif self.database_session is not None and self.game_db_id < 0:
            log.warning(f"[GameManager.{context}] Skipping database update: game not initialized (game_db_id={self.game_db_id}). Result: {result_string}, termination: {termination}")
            # Cache the result even if database update is skipped
            self.cached_result = result_string
        else:
            # No database session, just cache the result
            self.cached_result = result_string
        
        if self.event_callback is not None:
            self.event_callback(termination)
    
    def _handle_promotion(self, target_square: int, piece_name: str, is_forced: bool) -> str:
        """Handle pawn promotion by requesting piece choice via callback.
        
        Uses the on_promotion_needed callback to request piece selection from the
        display controller. The callback should return the selected piece letter.
        
        Args:
            target_square: The target square index (0-63)
            piece_name: The piece name ('P' for white pawn, 'p' for black pawn)
            is_forced: Whether this is a forced/computer move (skip prompt if True)
            
        Returns:
            Promotion piece letter ('q', 'r', 'b', 'n') or empty string if not a promotion
        """
        is_white_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
        is_black_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        board.beep(board.SOUND_GENERAL)
        if not is_forced:
            self.is_showing_promotion = True
            
            # Request promotion choice via callback
            if self.on_promotion_needed:
                promotion_choice = self.on_promotion_needed(is_white_promotion)
            else:
                # Default to queen if no callback
                log.warning("[GameManager] No promotion callback set, defaulting to queen")
                promotion_choice = "q"
            
            self.is_showing_promotion = False
            log.info(f"[GameManager] Promotion selected: {promotion_choice}")
            return promotion_choice
        return ""
    
    def _check_takeback(self) -> bool:
        """Check if a takeback is in progress by comparing board states.
        
        After each piece placement, checks if the current board state matches
        the previous state (before the last move). If it matches, executes the takeback.
        This handles all takeback scenarios regardless of piece placement order.
        """
        if self.takeback_callback is None:
            return False
        
        # Check if there are any moves to take back
        if len(self.chess_board.move_stack) == 0:
            log.debug("[GameManager._check_takeback] No moves to take back")
            return False
        
        # Get current physical board state
        current_state = board.getChessState()
        if current_state is None or len(current_state) != BOARD_SIZE:
            log.warning("[GameManager._check_takeback] Cannot check takeback: current board state is invalid")
            return False
        
        # Get expected previous state from logical chess board (the authority)
        previous_state = None
        try:
            # Temporarily pop the last move to get previous position
            last_move = self.chess_board.pop()
            previous_state = self._chess_board_to_state(self.chess_board)
            # Push the move back to restore state
            self.chess_board.push(last_move)
            log.debug("[GameManager._check_takeback] Reconstructed previous state from logical chess board")
        except Exception as e:
            log.error(f"[GameManager._check_takeback] Failed to reconstruct previous state from chess board: {e}")
            return False
        
        if previous_state is None or len(previous_state) != BOARD_SIZE:
            log.warning("[GameManager._check_takeback] Cannot check takeback: previous board state is invalid")
            return False
        
        # Check if current board state matches previous state
        if self._validate_board_state(current_state, previous_state):
            log.info("[GameManager._check_takeback] Takeback detected - board state matches previous state")
            board.ledsOff()
            
            # Preserve forced move info before callback (which may reset move state)
            forced_move_uci = self.move_state.computer_move_uci if self.move_state.is_forced_move else None
            
            # Remove last move from database
            if self.database_session is not None:
                db_last_move = self.database_session.query(models.GameMove).order_by(
                    models.GameMove.id.desc()
                ).first()
                if db_last_move is not None:
                    self.database_session.delete(db_last_move)
                    self.database_session.commit()
            
            self.chess_board.pop()
            paths.write_fen_log(self.chess_board.fen())
            board.beep(board.SOUND_GENERAL)
            
            self.takeback_callback()
            
            # If there was a forced move, restore it and reapply LEDs after takeback
            if forced_move_uci is not None:
                # Check if the forced move is still valid at the new position
                try:
                    move = chess.Move.from_uci(forced_move_uci)
                    if move in self.chess_board.legal_moves:
                        # Restore the forced move state
                        self.move_state.set_computer_move(forced_move_uci, forced=True)
                        # Reapply LEDs for the forced move
                        from_sq, to_sq = self._uci_to_squares(forced_move_uci)
                        if from_sq is not None and to_sq is not None:
                            board.ledFromTo(from_sq, to_sq, repeat=0)
                            log.info(f"[GameManager._check_takeback] Reapplied LEDs for forced move {forced_move_uci} after takeback")
                        else:
                            log.warning(f"[GameManager._check_takeback] Could not convert forced move {forced_move_uci} to squares")
                    else:
                        log.info(f"[GameManager._check_takeback] Forced move {forced_move_uci} is no longer legal at position after takeback")
                except (ValueError, AttributeError) as e:
                    log.warning(f"[GameManager._check_takeback] Could not reapply forced move LEDs after takeback: {e}")
            else:
                log.debug("[GameManager._check_takeback] No forced move to restore after takeback")
            
            # Verify board is correct after takeback
            current = board.getChessState()
            expected_state = self._chess_board_to_state(self.chess_board)
            
            if expected_state is not None and not self._validate_board_state(current, expected_state):
                log.info("[GameManager._check_takeback] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
                # Provide correction guidance using logical state
                self._provide_correction_guidance(current, expected_state)
            
            return True
        
        return False
    
    def _enter_correction_mode(self):
        """Enter correction mode to guide user in fixing board state.
        
        Uses logical chess board state (self.chess_board) as the authority.
        The physical board must conform to the logical board state.
        """
        expected_state = self._chess_board_to_state(self.chess_board)
        
        if expected_state is None:
            log.error("[GameManager._enter_correction_mode] Cannot enter correction mode: failed to convert chess board to state")
            return
        
        self.correction_mode.enter(expected_state)
        log.warning(f"[GameManager._enter_correction_mode] Entered correction mode - physical board must match logical board (FEN: {self.chess_board.fen()})")
    
    def _exit_correction_mode(self):
        """Exit correction mode and resume normal game flow."""
        self.correction_mode.exit()
        log.warning("[GameManager._exit_correction_mode] Exited correction mode")
        
        # Turn off correction LEDs first
        board.ledsOff()
        
        # Reset move state variables
        self.move_state.source_square = INVALID_SQUARE
        self.move_state.legal_destination_squares = []
        self.move_state.opponent_source_square = INVALID_SQUARE
        
        # Restore forced move LEDs if needed
        if self.move_state.is_forced_move and self.move_state.computer_move_uci:
            if len(self.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH:
                from_sq, to_sq = self._uci_to_squares(self.move_state.computer_move_uci)
                if from_sq is not None and to_sq is not None:
                    board.ledFromTo(from_sq, to_sq, repeat=0)
                    log.info(f"[GameManager._exit_correction_mode] Restored forced move LEDs: {self.move_state.computer_move_uci}")
    
    def _provide_correction_guidance(self, current_state, expected_state):
        """Provide LED guidance to correct misplaced pieces using Hungarian algorithm."""
        if current_state is None or expected_state is None:
            return
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return
        
        def square_to_row_col(square_idx):
            """Convert square index to (row, col)."""
            return (square_idx // BOARD_WIDTH), (square_idx % BOARD_WIDTH)
        
        def manhattan_distance(sq1, sq2):
            """Calculate Manhattan distance between two squares."""
            r1, c1 = square_to_row_col(sq1)
            r2, c2 = square_to_row_col(sq2)
            return abs(r1 - r2) + abs(c1 - c2)
        
        # Find misplaced pieces
        missing_squares = []  # Squares that should have pieces but don't
        extra_squares = []    # Squares that have pieces but shouldn't
        
        for i in range(BOARD_SIZE):
            if expected_state[i] == 1 and current_state[i] == 0:
                missing_squares.append(i)
            elif expected_state[i] == 0 and current_state[i] == 1:
                extra_squares.append(i)
        
        if len(missing_squares) == 0 and len(extra_squares) == 0:
            board.ledsOff()
            return
        
        log.warning(f"[GameManager._provide_correction_guidance] Found {len(extra_squares)} wrong pieces, {len(missing_squares)} missing pieces")
        
        # Guide one piece at a time
        if len(extra_squares) > 0 and len(missing_squares) > 0:
            if len(extra_squares) == 1 and len(missing_squares) == 1:
                from_idx = extra_squares[0]
                to_idx = missing_squares[0]
            else:
                # Use Hungarian algorithm for optimal pairing
                n_extra = len(extra_squares)
                n_missing = len(missing_squares)
                costs = np.zeros((n_extra, n_missing))
                for i, extra_sq in enumerate(extra_squares):
                    for j, missing_sq in enumerate(missing_squares):
                        costs[i, j] = manhattan_distance(extra_sq, missing_sq)
                
                row_ind, col_ind = linear_sum_assignment(costs)
                from_idx = extra_squares[row_ind[0]]
                to_idx = missing_squares[col_ind[0]]
            
            board.ledsOff()
            board.ledFromTo(from_idx, to_idx, repeat=0)
            log.warning(f"[GameManager._provide_correction_guidance] Guiding piece from {chess.square_name(from_idx)} to {chess.square_name(to_idx)}")
        else:
            # Only pieces missing or only extra pieces
            if len(missing_squares) > 0:
                board.ledsOff()
                for idx in missing_squares:
                    board.led(idx, repeat=0)
                log.warning(f"[GameManager._provide_correction_guidance] Pieces missing at: {[chess.square_name(sq) for sq in missing_squares]}")
            elif len(extra_squares) > 0:
                board.ledsOff()
                # Use ledArray for continuous flashing
                board.ledArray(extra_squares, speed=10, intensity=5, repeat=0)
                log.warning(f"[GameManager._provide_correction_guidance] Extra pieces at: {[chess.square_name(sq) for sq in extra_squares]}")
    
    def _handle_field_event_in_correction_mode(self, piece_event: int, field: int, time_in_seconds: float):
        """Handle field events during correction mode.
        
        Validates physical board against logical board (self.chess_board).
        The logical board is the authority - physical board must conform to it.
        """
        current_physical_state = board.getChessState()
        
        # Check if board is in starting position (new game detection)
        # If starting position is detected, abandon current game and start fresh
        if current_physical_state is not None and len(current_physical_state) == BOARD_SIZE:
            if self._is_starting_position(current_physical_state):
                log.warning("[GameManager._handle_field_event_in_correction_mode] Starting position detected during correction mode - abandoning current game and starting new game")
                # Exit correction mode first (this will clean up correction state)
                self._exit_correction_mode()
                # Then reset game (this will clean up all game state and mark previous game as abandoned)
                self._reset_game()
                return
        
        # Always use current logical board state as authority (it may have changed)
        # Don't rely on stored expected_state - recalculate from logical board
        expected_logical_state = self._chess_board_to_state(self.chess_board)
        
        if expected_logical_state is None:
            log.error("[GameManager._handle_field_event_in_correction_mode] Cannot validate: failed to get logical board state")
            return
        
        if current_physical_state is not None and self._validate_board_state(current_physical_state, expected_logical_state):
            log.info("[GameManager._handle_field_event_in_correction_mode] Physical board now matches logical board, exiting correction mode")
            board.beep(board.SOUND_GENERAL)
            self._exit_correction_mode()
            return
        
        # Still incorrect, update guidance using current logical board as authority
        # Recalculate expected state from logical board (authority) in case it changed
        if current_physical_state is not None:
            current_expected_state = self._chess_board_to_state(self.chess_board)
            if current_expected_state is not None:
                self._provide_correction_guidance(current_physical_state, current_expected_state)
    
    def _handle_piece_lift(self, field: int, piece_color):
        """Handle piece lift event."""
        is_current_player_piece = (self.chess_board.turn == chess.WHITE) == (piece_color == True)
        
        if field not in self.move_state.legal_destination_squares and \
           self.move_state.source_square < 0 and \
           is_current_player_piece:
            # Generate legal destination squares for this piece
            self.move_state.legal_destination_squares = self._calculate_legal_squares(field)
            self.move_state.source_square = field
            # Store piece color for use during PLACE event (important for captures)
            self.move_state.source_piece_color = piece_color
        
        # Track opposing side lifts
        if not is_current_player_piece:
            self.move_state.opponent_source_square = field
        
        # Handle forced moves
        if self.move_state.is_forced_move and is_current_player_piece:
            field_name = chess.square_name(field)
            if field_name != self.move_state.computer_move_uci[0:2]:
                # Wrong piece lifted for forced move
                self.move_state.legal_destination_squares = [field]
            else:
                # Correct piece, limit to target square
                target = self.move_state.computer_move_uci[2:4]
                target_square = chess.parse_square(target)
                self.move_state.legal_destination_squares = [target_square]
                # Store piece color for forced moves too
                self.move_state.source_piece_color = piece_color

    def _handle_piece_place(self, field: int, piece_color):
        """Handle piece place event."""
        
        is_current_player_piece = (self.chess_board.turn == chess.WHITE) == (piece_color == True)
        
        # Handle opponent piece placed back
        if not is_current_player_piece and \
           self.move_state.opponent_source_square >= 0 and \
           field == self.move_state.opponent_source_square:
            board.ledsOff()
            self.move_state.opponent_source_square = INVALID_SQUARE
            return
        
        # Ignore stale PLACE events without corresponding LIFT
        if self.move_state.source_square < 0 and self.move_state.opponent_source_square < 0:
            # First, check if this PLACE event created an invalid board state (extra piece)
            # This check should happen for ALL cases, not just non-forced moves
            # 
            # IMPORTANT: Use the logical chess board state (FEN) as the expected state, not the physical board state.
            # This ensures consistency with the chess board widget display.
            # 
            # Timing assumption: This check occurs immediately after a PLACE event, so chess_board should
            # reflect the current logical game state. The chess_board is updated synchronously in _execute_move()
            # before any subsequent events can occur, so there should be no race condition.
            current_state = board.getChessState()
            expected_state = self._chess_board_to_state(self.chess_board)
            
            if current_state is not None and expected_state is not None:
                # Check if there are extra pieces (pieces on squares that shouldn't have them)
                extra_squares = []
                if len(current_state) == BOARD_SIZE and len(expected_state) == BOARD_SIZE:
                    for i in range(BOARD_SIZE):
                        if expected_state[i] == 0 and current_state[i] == 1:
                            extra_squares.append(i)
                    
                    # Debug logging for troubleshooting
                    if len(extra_squares) > 0:
                        log.debug(f"[GameManager._handle_piece_place] Current FEN: {self.chess_board.fen()}")
                        log.debug(f"[GameManager._handle_piece_place] Extra pieces detected: {[chess.square_name(sq) for sq in extra_squares]}")
                
                if len(extra_squares) > 0:
                    log.warning(f"[GameManager._handle_piece_place] PLACE event without LIFT created invalid board state with {len(extra_squares)} extra piece(s) at {[chess.square_name(sq) for sq in extra_squares]}, entering correction mode")
                    board.beep(board.SOUND_WRONG_MOVE)
                    self._enter_correction_mode()
                    self._provide_correction_guidance(current_state, expected_state)
                    return
            else:
                log.debug(f"[GameManager._handle_piece_place] Cannot check board state: current_state={current_state is not None}, expected_state={expected_state is not None}")
            
            if self.correction_mode.just_exited:
                # Check if this is the forced move source square
                if self.move_state.is_forced_move and self.move_state.computer_move_uci:
                    if len(self.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH:
                        forced_source = chess.parse_square(self.move_state.computer_move_uci[0:2])
                        if field != forced_source:
                            log.info(f"[GameManager._handle_piece_place] Ignoring stale PLACE event after correction exit for field {field}")
                            self.correction_mode.clear_exit_flag()
                            return
                else:
                    log.info(f"[GameManager._handle_piece_place] Ignoring stale PLACE event after correction exit for field {field}")
                    self.correction_mode.clear_exit_flag()
                    return
            
            # For forced moves, ignore stale PLACE events on source square
            if self.move_state.is_forced_move and self.move_state.computer_move_uci:
                if len(self.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH:
                    forced_source = chess.parse_square(self.move_state.computer_move_uci[0:2])
                    if field == forced_source:
                        log.info(f"[GameManager._handle_piece_place] Ignoring stale PLACE event for forced move source field {field}")
                        self.correction_mode.clear_exit_flag()
                        return
            
            if not self.move_state.is_forced_move:
                log.info(f"[GameManager._handle_piece_place] Ignoring stale PLACE event for field {field}")
                self.correction_mode.clear_exit_flag()
                return
        
        # Clear exit flag on valid LIFT (handled in lift handler)
        
        # Check for illegal placement
        if field not in self.move_state.legal_destination_squares:
            board.beep(board.SOUND_WRONG_MOVE)
            log.warning(f"[GameManager._handle_piece_place] Piece placed on illegal square {field}")
            is_takeback = self._check_takeback()
            if not is_takeback:
                self._enter_correction_mode()
                current_state = board.getChessState()
                expected_state = self._chess_board_to_state(self.chess_board)
                
                if expected_state is not None:
                    self._provide_correction_guidance(current_state, expected_state)
            return
        
        # Legal placement
        if field == self.move_state.source_square:
            # Piece placed back on source square
            board.ledsOff()
            self.move_state.source_square = INVALID_SQUARE
            self.move_state.legal_destination_squares = []
            self.move_state.source_piece_color = None
        else:
            # Valid move
            self._execute_move(field)
    
    def _execute_move(self, target_square: int):
        """Execute a move from source to target square.
        
        Prevents moves from being executed after the game has ended.
        If the game is already over, logs a warning and returns early.
        """
        # Check if game is already over before executing move
        # This prevents moves from being executed after game termination, which would corrupt game state
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is not None:
            log.warning(f"[GameManager._execute_move] Attempted to execute move after game ended. Result: {self.chess_board.result()}, Termination: {outcome.termination}")
            board.beep(board.SOUND_WRONG_MOVE)
            board.ledsOff()
            self.move_state.reset()
            return
        
        from_name = chess.square_name(self.move_state.source_square)
        to_name = chess.square_name(target_square)
        piece_name = str(self.chess_board.piece_at(self.move_state.source_square))
        
        if self.move_state.is_forced_move:
            # For forced moves, use the computer move UCI directly
            # However, we need to ensure promotion is included if needed
            move_uci = self.move_state.computer_move_uci
            
            # Check if promotion is needed (pawn reaching promotion rank)
            is_white_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
            is_black_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
            
            if (is_white_promotion or is_black_promotion):
                # Promotion is needed - check if UCI already includes it
                if len(move_uci) < 5:
                    # UCI doesn't include promotion piece - this should not happen if move was validated
                    # but handle it gracefully by defaulting to queen
                    log.warning(f"[GameManager._execute_move] Forced move UCI '{move_uci}' missing promotion piece for promotion move, defaulting to queen")
                    move_uci = move_uci + "q"
                # If UCI already has promotion (length >= 5), use it as-is
        else:
            # For non-forced moves, get promotion choice from user if needed
            promotion_suffix = self._handle_promotion(target_square, piece_name, self.move_state.is_forced_move)
            move_uci = from_name + to_name + promotion_suffix
        
        # Atomic operation: Add to database first, then push to chess engine
        # If chess engine push fails, rollback database to maintain consistency
        # This ensures database and chess engine state are always synchronized
        
        # Validate move UCI format first (before any database operations)
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError as e:
            log.error(f"[GameManager._execute_move] Invalid move UCI format: {move_uci}. Error: {e}")
            board.beep(board.SOUND_WRONG_MOVE)
            board.ledsOff()
            self.move_state.reset()
            return
        
        # Atomic operation: Add to database first, then push to chess engine
        # If chess engine push fails, rollback database to maintain consistency
        # This ensures database and chess engine state are always synchronized
        
        # Step 0: Create new game in database if this is the first move (game_db_id == -1)
        # This is part of the atomic transaction - if chess engine push fails, game creation is rolled back
        new_game_created = False
        if self.database_session is not None and self.game_db_id < 0:
            try:
                log.info("[GameManager._execute_move] First move detected - creating new game in database (will commit after chess engine push succeeds)")
                game = models.Game(
                    source=self.source_file,
                    event=self.game_info['event'],
                    site=self.game_info['site'],
                    round=self.game_info['round'],
                    white=self.game_info['white'],
                    black=self.game_info['black']
                )
                self.database_session.add(game)
                # Flush to get the game ID, but don't commit yet
                self.database_session.flush()
                
                # Get the game ID from the flushed object
                # The game object should now have an ID assigned
                if hasattr(game, 'id') and game.id is not None:
                    self.game_db_id = game.id
                    new_game_created = True
                    log.info(f"[GameManager._execute_move] New game created in database (id={self.game_db_id}), will commit after chess engine push succeeds")
                    
                    # Create initial game move entry for starting position (before this move)
                    initial_move = models.GameMove(
                        gameid=self.game_db_id,
                        move='',
                        fen=str(self.chess_board.fen())  # FEN before this move
                    )
                    self.database_session.add(initial_move)
                    # Don't commit yet - wait for chess engine push
                else:
                    log.error(f"[GameManager._execute_move] Failed to get game ID after creating new game")
                    # Rollback the game creation attempt
                    self.database_session.rollback()
            except Exception as db_error:
                log.error(f"[GameManager._execute_move] Error creating new game in database: {db_error}")
                # Rollback any partial game creation
                try:
                    self.database_session.rollback()
                except Exception:
                    pass
                # Continue - game can proceed without database entry
        
        # Step 1: Add move to database (but don't commit yet)
        # Use a flag to track if we need to rollback
        database_move_added = False
        game_move = None
        if self.database_session is not None and self.game_db_id >= 0:
            try:
                # Create move object but don't commit - we'll commit after chess engine push succeeds
                game_move = models.GameMove(
                    gameid=self.game_db_id,
                    move=move_uci,
                    fen=None  # Will be set after chess engine push succeeds
                )
                self.database_session.add(game_move)
                database_move_added = True
                # Flush to ensure the object is in the session, but don't commit yet
                self.database_session.flush()
            except Exception as db_error:
                # Database add failed - log but continue to try chess engine push
                # If chess engine push succeeds, we'll have inconsistent state, but that's better than
                # blocking the move entirely
                log.error(f"[GameManager._execute_move] Failed to add move to database: {db_error}")
                database_move_added = False
                game_move = None
        elif self.database_session is not None and self.game_db_id < 0:
            log.warning(f"[GameManager._execute_move] Skipping database write: game not initialized (game_db_id={self.game_db_id}). Move: {move_uci}")
        
        # Step 2: Push to chess engine (this is the critical operation)
        # If this fails, we'll rollback the database (including new game creation if this was first move)
        try:
            self.chess_board.push(move)
        except (ValueError, AssertionError) as e:
            # Chess engine push failed - rollback database (game creation and/or move)
            if new_game_created or database_move_added:
                try:
                    self.database_session.rollback()
                    # Reset game_db_id if we created a new game
                    if new_game_created:
                        self.game_db_id = -1
                    log.warning(f"[GameManager._execute_move] Chess engine push failed, rolled back database (game creation and/or move). Move: {move_uci}, Error: {e}")
                except Exception as rollback_error:
                    log.error(f"[GameManager._execute_move] Failed to rollback database after chess engine push failure: {rollback_error}")
            
            log.error(f"[GameManager._execute_move] Illegal move or chess engine push failed: {move_uci}. Error: {e}")
            board.beep(board.SOUND_WRONG_MOVE)
            board.ledsOff()
            self.move_state.reset()
            return
        
        # Step 3: Chess engine push succeeded - now commit database with final FEN
        # This commits both the new game (if first move) and the move
        if new_game_created or (database_move_added and game_move is not None):
            try:
                # Update FEN now that we know the move succeeded
                if game_move is not None:
                    game_move.fen = str(self.chess_board.fen())
                
                # Commit everything: new game (if first move) and move
                self.database_session.commit()
                if new_game_created:
                    log.info(f"[GameManager._execute_move] New game (id={self.game_db_id}) and first move {move_uci} committed to database after successful chess engine push")
                else:
                    log.debug(f"[GameManager._execute_move] Move {move_uci} committed to database after successful chess engine push")
            except Exception as commit_error:
                # Database commit failed - this is bad but chess engine already has the move
                # Log error but continue - chess engine state is authoritative
                log.error(f"[GameManager._execute_move] Database commit failed after chess engine push succeeded: {commit_error}")
                log.error(f"[GameManager._execute_move] WARNING: Database and chess engine are now out of sync for move {move_uci}")
                # Reset game_db_id if we created a new game but commit failed
                if new_game_created:
                    self.game_db_id = -1
                # Try to rollback to prevent partial state
                try:
                    self.database_session.rollback()
                except Exception:
                    pass
        
        paths.write_fen_log(self.chess_board.fen())
        
        # Always call move callback FIRST to update display with logical board state
        # The display must always reflect self.chess_board (the authority), not the physical board
        if self.move_callback is not None:
            try:
                self.move_callback(move_uci)
            except Exception as e:
                log.error(f"[GameManager._execute_move] Error in move callback: {e}")
                import traceback
                traceback.print_exc()
        
        # Validate physical board matches logical board after move
        # If there's a mismatch, enter correction mode to guide user
        try:
            current_physical_state = board.getChessState()
            expected_logical_state = self._chess_board_to_state(self.chess_board)
            
            if current_physical_state is not None and expected_logical_state is not None:
                if not self._validate_board_state(current_physical_state, expected_logical_state):
                    log.warning(f"[GameManager._execute_move] Physical board does not match logical board after move {move_uci}, entering correction mode")
                    self._enter_correction_mode()
                    self._provide_correction_guidance(current_physical_state, expected_logical_state)
            else:
                # Can't validate - log warning but continue
                log.warning(f"[GameManager._execute_move] Could not validate physical board state (current={current_physical_state is not None}, expected={expected_logical_state is not None})")
        except Exception as e:
            log.warning(f"[GameManager._execute_move] Error validating physical board state: {e}")
        
        self.move_state.reset()
        board.ledsOff()
        
        board.beep(board.SOUND_GENERAL)
        board.led(target_square)
        
        # Check game outcome
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is None:
            self._switch_turn_with_event()
        else:
            board.beep(board.SOUND_GENERAL)
            result_string = str(self.chess_board.result())
            termination = str(outcome.termination)
            self._update_game_result(result_string, termination, "_execute_move")
    
    def receive_field(self, piece_event: int, field: int, time_in_seconds: float):
        """Handle field events (piece lift/place)."""
        field_name = chess.square_name(field)
        
        # For LIFT events, get piece color from the field
        # For PLACE events, use stored source piece color (important for captures)
        # where the destination square may have the opponent's piece
        if piece_event == 0:  # LIFT event
            if self.event_callback is not None:
                self.event_callback(EVENT_LIFT_PIECE, piece_event, field, time_in_seconds)
            piece_color = self.chess_board.color_at(field)
        else:  # PLACE event
            if self.event_callback is not None:
                self.event_callback(EVENT_PLACE_PIECE, piece_event, field, time_in_seconds)
            if self.move_state.source_piece_color is not None:
                # Use stored piece color from when the piece was lifted
                piece_color = self.move_state.source_piece_color
            else:
                # Fallback to destination square if no stored color (shouldn't normally happen)
                piece_color = self.chess_board.color_at(field)
        
        log.info(f"[GameManager.receive_field] piece_event={piece_event} field={field} fieldname={field_name} "
                 f"color_at={'White' if piece_color else 'Black'} time_in_seconds={time_in_seconds}")
        
        # Check for takeback FIRST, before any other processing including correction mode
        # Takeback detection must work regardless of correction mode state
        is_place = (piece_event == 1)
        if is_place and len(self.chess_board.move_stack) > 0:
            is_takeback = self._check_takeback()
            if is_takeback:
                # Takeback was successful, reset move state and return
                # Exit correction mode if active since takeback resolved the issue
                if self.correction_mode.is_active:
                    log.info("[GameManager.receive_field] Takeback detected during correction mode, exiting correction mode")
                    self._exit_correction_mode()
                self.move_state.reset()
                board.ledsOff()
                return
        
        # Handle correction mode (only if takeback was not detected)
        if self.correction_mode.is_active:
            self._handle_field_event_in_correction_mode(piece_event, field, time_in_seconds)
            return
        
        # Check for starting position when piece is placed
        # Starting position detection is the mechanism to abandon a game in progress
        # This allows players to reset and start fresh at any time
        if is_place:
            current_state = board.getChessState()
            if self._is_starting_position(current_state):
                log.warning("[GameManager.receive_field] Starting position detected - abandoning current game")
                self._reset_game()
                return
        
        is_lift = (piece_event == 0)
        
        if is_lift:
            self._handle_piece_lift(field, piece_color)
            self.correction_mode.clear_exit_flag()
        elif is_place:
            self._handle_piece_place(field, piece_color)
    
    def receive_key(self, key_pressed):
        """Handle key press events.
        
        GameManager handles game-related key logic:
        - BACK during game: Shows resign/draw menu, only passes through if user chooses to exit
        - BACK with no game: Passes through to external callback (caller handles exit)
        - Other keys: Passed through to external callback
        
        Args:
            key_pressed: Key that was pressed (board.Key enum value)
        """
        # Handle BACK key - notify DisplayManager if game in progress
        if key_pressed == board.Key.BACK:
            if self.is_game_in_progress():
                log.info("[GameManager] BACK pressed during game - notifying display controller")
                if self.on_back_pressed:
                    self.on_back_pressed()
                return
            else:
                # No game in progress - pass through to external callback for exit handling
                log.info("[GameManager] BACK pressed - no game in progress, passing to external callback")
        
        # Pass other keys (and BACK when no game) to external callback
        if self.key_callback is not None:
            self.key_callback(key_pressed)
    
    def is_game_in_progress(self) -> bool:
        """Check if a game is in progress (at least one move has been made).
        
        Returns:
            True if at least one move has been made, False otherwise
        """
        return len(self.chess_board.move_stack) > 0
    
    def handle_resign(self, player_color: chess.Color = None) -> None:
        """Handle game resignation by the human player.
        
        The human player (at the physical board) is resigning. The result is recorded
        as a loss for the specified color, or the current turn if not specified.
        
        Args:
            player_color: Color of the player resigning. If None, defaults to current turn.
        """
        log.info("[GameManager] Processing resignation")
        
        # Determine which color is resigning
        if player_color is None:
            player_color = self.chess_board.turn
        
        # Human resigns, so human loses
        if player_color == chess.WHITE:
            result = "0-1"  # Black wins (human was white)
            log.info("[GameManager] White resigned - Black wins")
        else:
            result = "1-0"  # White wins (human was black)
            log.info("[GameManager] Black resigned - White wins")
        
        # Update database with result
        self._update_game_result(result, "Termination.RESIGN", "handle_resign")
        
        # Play sound and turn off LEDs
        board.beep(board.SOUND_GENERAL)
        board.ledsOff()
    
    def handle_draw(self) -> None:
        """Handle draw claim/agreement by the human player.
        
        The human player (at the physical board) is claiming or agreeing to a draw.
        This records the game result as a draw.
        """
        log.info("[GameManager] Processing draw")
        
        result = "1/2-1/2"
        
        # Update database with result
        self._update_game_result(result, "Termination.DRAW", "handle_draw")
        
        # Play sound and turn off LEDs
        board.beep(board.SOUND_GENERAL)
        board.ledsOff()
    
    def _reset_game(self):
        """Abandon current game and reset to starting position.
        
        When a player sets up pieces in the starting position, this indicates
        they want to abandon the current game. All state from the previous game
        must be cleaned up. A new game will be created in the database only when
        the first move is made.
        """
        try:
            log.warning("[GameManager._reset_game] Starting position detected - abandoning current game and cleaning up state")
            
            # Step 1: Exit correction mode if active (clean up any correction state)
            if self.correction_mode.is_active:
                log.info("[GameManager._reset_game] Exiting correction mode before reset")
                self._exit_correction_mode()
            
            # Step 2: Clean up any pending database transactions from previous game
            if self.database_session is not None:
                try:
                    # Rollback any uncommitted transactions from the previous game
                    # Check if there are any pending changes in the session
                    if self.database_session.dirty or self.database_session.new or self.database_session.deleted:
                        self.database_session.rollback()
                        log.debug("[GameManager._reset_game] Rolled back pending database transactions")
                except Exception as rollback_error:
                    log.warning(f"[GameManager._reset_game] Error rolling back database transactions: {rollback_error}")
            
            # Step 3: Mark previous game as abandoned if it was in progress
            if self.database_session is not None and self.game_db_id >= 0:
                try:
                    # Check if the previous game has a result (if not, it was abandoned)
                    previous_game = self.database_session.query(models.Game).filter(
                        models.Game.id == self.game_db_id
                    ).first()
                    if previous_game is not None and previous_game.result is None:
                        # Mark as abandoned (no result means game was in progress)
                        previous_game.result = "*"  # "*" indicates game abandoned/unfinished
                        self.database_session.commit()
                        log.info(f"[GameManager._reset_game] Marked previous game (id={self.game_db_id}) as abandoned")
                except Exception as abandon_error:
                    log.warning(f"[GameManager._reset_game] Error marking previous game as abandoned: {abandon_error}")
            
            # Step 4: Reset all game state
            self.move_state.reset()  # Clear move state (source square, legal moves, forced moves, etc.)
            self.chess_board.reset()  # Reset logical board to starting position
            self.cached_result = None  # Clear cached game result
            
            # Step 5: Reset UI state
            self.is_showing_promotion = False  # Clear promotion state
            self.is_in_menu = False  # Exit menu if open
            
            # Step 6: Reset clock
            self.clock_manager.stop()  # Stop clock if running
            
            # Step 7: Clear all board LEDs and turn off any indicators
            board.ledsOff()
            
            # Step 8: Reset game_db_id to -1 to indicate no active game in database
            # New game will be created when first move is made
            self.game_db_id = -1
            log.info("[GameManager._reset_game] Reset game_db_id to -1 - new game will be created on first move")
            
            # Step 9: Update FEN log
            paths.write_fen_log(self.chess_board.fen())
            
            # Step 10: Notify callbacks of new game (but don't create DB entry yet)
            if self.event_callback is not None:
                self.event_callback(EVENT_NEW_GAME)
                # Determine which turn event to send based on current board state
                if self.chess_board.turn == chess.WHITE:
                    self.event_callback(EVENT_WHITE_TURN)
                else:
                    self.event_callback(EVENT_BLACK_TURN)
            
            # Step 11: Audio/visual feedback for game abandonment
            board.beep(board.SOUND_GENERAL)
            time.sleep(0.3)
            board.beep(board.SOUND_GENERAL)
            
            log.info("[GameManager._reset_game] Game abandoned and reset complete - ready for new game (will be created on first move)")
        except Exception as e:
            log.error(f"[GameManager._reset_game] Error resetting game: {e}")
            import traceback
            traceback.print_exc()
            # Try to ensure at least basic cleanup happens even on error
            try:
                self.move_state.reset()
                self.chess_board.reset()
                self.game_db_id = -1
                board.ledsOff()
                if self.correction_mode.is_active:
                    self._exit_correction_mode()
            except Exception:
                pass
    
    def _game_thread(self, event_callback, move_callback, key_callback, takeback_callback):
        """Main game thread that handles events."""
        self.event_callback = event_callback
        self.move_callback = move_callback
        self.key_callback = key_callback
        self.takeback_callback = takeback_callback
        
        # Create database engine and session in this thread to ensure all SQL operations happen in the same thread
        # We create a new engine here instead of using models.engine because the global engine's
        # connection pool was created in a different thread (module import time)
        thread_id = threading.get_ident()
        database_uri = paths.get_database_uri()
        # Configure SQLite with check_same_thread=False to allow connections created in this thread
        # to be used throughout the thread's lifetime. This is safe because we create and use
        # the engine entirely within this thread.
        if database_uri.startswith('sqlite'):
            self.database_engine = create_engine(
                database_uri,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True  # Verify connections before using
            )
        else:
            self.database_engine = create_engine(database_uri, pool_pre_ping=True)
        Session = sessionmaker(bind=self.database_engine)
        self.database_session = Session()
        log.info(f"[GameManager._game_thread] Database engine and session created in thread {thread_id}")
        
        board.ledsOff()
        log.info("[GameManager._game_thread] Ready to receive events from app coordinator")
        
        # Note: GameManager no longer subscribes to board events directly.
        # Events are routed from the app coordinator (universal.py) through
        # GameHandler.receive_key() and GameHandler.receive_field() methods.
        
        try:
            while not self.should_stop:
                # Use interruptible sleep to allow quick thread termination
                if not self._stop_event.wait(timeout=0.1):
                    # Timeout occurred (normal case), clear the event for next iteration
                    self._stop_event.clear()
        finally:
            # Clean up database session and engine in the same thread they were created
            if self.database_session is not None:
                try:
                    log.info(f"[GameManager._game_thread] Closing database session in thread {thread_id}")
                    self.database_session.close()
                    self.database_session = None
                except Exception as e:
                    log.error(f"[GameManager._game_thread] Error closing database session: {e}")
                    self.database_session = None
            if self.database_engine is not None:
                try:
                    log.info(f"[GameManager._game_thread] Disposing database engine in thread {thread_id}")
                    self.database_engine.dispose()
                    self.database_engine = None
                except Exception as e:
                    log.error(f"[GameManager._game_thread] Error disposing database engine: {e}")
                    self.database_engine = None
    
    def set_game_info(self, event: str, site: str, round_str: str, white: str, black: str):
        """Set game metadata for PGN files."""
        self.game_info = {
            'event': event,
            'site': site,
            'round': round_str,
            'white': white,
            'black': black
        }
    
    def set_clock(self, white_seconds: int, black_seconds: int):
        """Set the clock times for both players."""
        self.clock_manager.set_times(white_seconds, black_seconds)
    
    def start_clock(self):
        """Start the clock thread."""
        def get_current_turn():
            return self.chess_board.turn
        
        def is_starting_position():
            current_state = board.getChessState()
            return self._is_starting_position(current_state)
        
        def is_showing_promotion():
            return self.is_showing_promotion
        
        self.clock_manager.start(get_current_turn, is_starting_position, is_showing_promotion)
    
    def computer_move(self, uci_move: str, forced: bool = True):
        """Set the computer move that the player is expected to make.
        
        Validates that the move is legal at the current position and that the game
        is not already over before setting up the forced move.
        """
        # Check if game is already over
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is not None:
            log.warning(f"[GameManager.computer_move] Attempted to set forced move after game ended. Result: {self.chess_board.result()}, Termination: {outcome.termination}")
            return
        
        # Validate move UCI format
        if not self.move_state.set_computer_move(uci_move, forced):
            return
        
        # Validate that the move is legal at the current position
        # This prevents illegal moves from being set up, which would fail when executed
        try:
            move = chess.Move.from_uci(uci_move)
            if move not in self.chess_board.legal_moves:
                log.error(f"[GameManager.computer_move] Illegal move: {uci_move}. Legal moves: {list(self.chess_board.legal_moves)[:10]}...")
                board.beep(board.SOUND_WRONG_MOVE)
                return
        except ValueError as e:
            log.error(f"[GameManager.computer_move] Invalid move UCI format: {uci_move}. Error: {e}")
            board.beep(board.SOUND_WRONG_MOVE)
            return
        
        # Light up LEDs to indicate the move
        from_sq, to_sq = self._uci_to_squares(uci_move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq, repeat=0)
    
    def resign_game(self, side_resigning: int):
        """Handle game resignation."""
        result_string = "0-1" if side_resigning == 1 else "1-0"
        self._update_game_result(result_string, "Termination.RESIGN", "resign_game")
    
    def draw_game(self):
        """Handle game draw."""
        self._update_game_result("1/2-1/2", "Termination.DRAW", "draw_game")
    
    def get_result(self) -> str:
        """Get the result of the last game."""
        current_thread_id = threading.get_ident()
        game_thread_id = self.game_thread.ident if self.game_thread is not None else None
        
        # Check if we're in the game thread
        if current_thread_id != game_thread_id:
            # Not in game thread - use cached result
            if self.cached_result is not None:
                log.debug(f"[GameManager.get_result] Called from different thread (current={current_thread_id}, game_thread={game_thread_id}), returning cached result: {self.cached_result}")
                return self.cached_result
            else:
                log.warning(f"[GameManager.get_result] Called from different thread (current={current_thread_id}, game_thread={game_thread_id}) and no cached result available")
                return "Unknown"
        
        # We're in the game thread - can safely access database
        if self.database_session is None:
            # Fall back to cached result if available
            if self.cached_result is not None:
                return self.cached_result
            return "Unknown"
        
        game_data = self.database_session.execute(
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
        
        if game_data is not None:
            result = str(game_data.result)
            self.cached_result = result  # Update cache
            return result
        return "Unknown"
    
    def get_board(self):
        """Get the current chess board state."""
        return self.chess_board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self.chess_board.fen()
    
    def subscribe_game(self, event_callback, move_callback, key_callback, takeback_callback=None):
        """Subscribe to the game manager.
        
        Args:
            event_callback: Called for game events (new game, turn changes, etc.)
            move_callback: Called when a move is made
            key_callback: Called for key presses (BACK passed only when no game in progress)
            takeback_callback: Called when takeback is requested
        """
        self.source_file = inspect.getsourcefile(sys._getframe(1))
        thread_id = threading.get_ident()
        log.info(f"[GameManager.subscribe_game] GameManager initialized, source_file={self.source_file}, thread_id={thread_id}")
        
        self.should_stop = False
        self.game_thread = threading.Thread(
            target=self._game_thread,
            args=(event_callback, move_callback, key_callback, takeback_callback)
        )
        self.game_thread.daemon = True
        self.game_thread.start()
    
    def unsubscribe_game(self):
        """Stop the game manager."""
        self.should_stop = True
        self._stop_event.set()  # Signal the event to wake up any sleeping thread
        board.ledsOff()
        self.clock_manager.stop()
        
        # Wait for game thread to finish (it will clean up the database session)
        if self.game_thread is not None:
            self.game_thread.join(timeout=1.0)
            if self.game_thread.is_alive():
                log.warning("[GameManager.unsubscribe_game] Game thread did not finish within timeout")


# Global instance for backward compatibility
_game_manager_instance = None


def subscribeGame(event_callback, move_callback, key_callback, takeback_callback=None):
    """Subscribe to the game manager (backward compatibility function)."""
    global _game_manager_instance
    _game_manager_instance = GameManager()
    _game_manager_instance.subscribe_game(event_callback, move_callback, key_callback, takeback_callback)


def unsubscribeGame():
    """Unsubscribe from the game manager (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.unsubscribe_game()
        _game_manager_instance = None


def setGameInfo(event, site, round_str, white, black):
    """Set game metadata (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.set_game_info(event, site, round_str, white, black)


def setClock(white, black):
    """Set clock times (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.set_clock(white, black)


def startClock():
    """Start the clock (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.start_clock()


def computerMove(mv, forced=True):
    """Set computer move (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.computer_move(mv, forced)


def resignGame(side_resigning):
    """Resign game (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.resign_game(side_resigning)


def drawGame():
    """Draw game (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.draw_game()


def getResult():
    """Get game result (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        return _game_manager_instance.get_result()
    return "Unknown"


def getBoard():
    """Get chess board (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        return _game_manager_instance.get_board()
    return None


def getFEN():
    """Get FEN string (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        return _game_manager_instance.get_fen()
    return STARTING_FEN


def resetMoveState():
    """Reset move state (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.move_state.reset()


def resetBoard():
    """Reset board (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.chess_board.reset()


def setBoard(board_obj):
    """Set board (backward compatibility function)."""
    global _game_manager_instance
    if _game_manager_instance is not None:
        _game_manager_instance.chess_board = board_obj

