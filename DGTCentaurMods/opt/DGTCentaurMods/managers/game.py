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

import threading
import queue
import time
import chess
import sys
import inspect
import numpy as np

from DGTCentaurMods.board import board
from DGTCentaurMods.managers.asset import AssetManager
from DGTCentaurMods.board.logging import log

# Deferred imports - these are slow (~3s total on Raspberry Pi) and loaded in background
# to avoid blocking startup. They're only needed when a game actually starts.
_deferred_imports_ready = threading.Event()
_deferred_models = None
_deferred_linear_sum_assignment = None
_deferred_sessionmaker = None
_deferred_func = None
_deferred_select = None
_deferred_create_engine = None

def _load_deferred_imports():
    """Load slow imports in background thread.
    
    Imports scipy and database models which take ~3 seconds combined on Pi.
    Sets _deferred_imports_ready event when complete.
    
    Import order matters: scipy first (no dependencies on our code), then
    database/SQLAlchemy (which may have already been imported by db.models).
    """
    global _deferred_models, _deferred_linear_sum_assignment
    global _deferred_sessionmaker, _deferred_func, _deferred_select, _deferred_create_engine
    
    try:
        # Import scipy first (~1.5s) - no conflicts with our codebase
        from scipy.optimize import linear_sum_assignment as _lsa
        _deferred_linear_sum_assignment = _lsa
        log.debug("[GameManager] scipy loaded successfully")
    except Exception as e:
        log.warning(f"[GameManager] scipy import failed (correction guidance will use fallback): {e}")
    
    try:
        # Import database models (~1.5s)
        # Note: db.models imports SQLAlchemy at module level, so we import
        # models first to ensure SQLAlchemy is fully initialized
        from DGTCentaurMods.db import models as _models
        _deferred_models = _models
        
        # Import SQLAlchemy components (should already be loaded by models)
        from sqlalchemy.orm import sessionmaker as _sessionmaker
        from sqlalchemy import func as _func, select as _select, create_engine as _create_engine
        _deferred_sessionmaker = _sessionmaker
        _deferred_func = _func
        _deferred_select = _select
        _deferred_create_engine = _create_engine
        
        log.debug("[GameManager] Deferred imports loaded successfully")
    except Exception as e:
        log.error(f"[GameManager] Error loading database imports: {e}")
    finally:
        _deferred_imports_ready.set()

# Start background import thread
_import_thread = threading.Thread(target=_load_deferred_imports, daemon=True)
_import_thread.start()

def _wait_for_imports(timeout=30.0):
    """Wait for deferred imports to complete.
    
    Called by functions that need the deferred modules.
    Returns True if imports are ready, False on timeout.
    
    Args:
        timeout: Maximum seconds to wait (default 30s, plenty of time)
    
    Returns:
        True if imports ready, False if timed out
    """
    if _deferred_imports_ready.is_set():
        return True
    log.debug("[GameManager] Waiting for deferred imports...")
    return _deferred_imports_ready.wait(timeout=timeout)

def _get_models():
    """Get the models module, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_models

def _get_linear_sum_assignment():
    """Get the linear_sum_assignment function, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_linear_sum_assignment

def _get_sessionmaker():
    """Get SQLAlchemy sessionmaker, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_sessionmaker

def _get_sqlalchemy_func():
    """Get SQLAlchemy func, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_func

def _get_sqlalchemy_select():
    """Get SQLAlchemy select, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_select

def _get_create_engine():
    """Get SQLAlchemy create_engine, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_create_engine


# Event constants - import from lightweight events module for backward compatibility
from DGTCentaurMods.managers.events import (
    EVENT_NEW_GAME,
    EVENT_BLACK_TURN,
    EVENT_WHITE_TURN,
    EVENT_REQUEST_DRAW,
    EVENT_RESIGN_GAME,
    EVENT_LIFT_PIECE,
    EVENT_PLACE_PIECE,
)

# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
INVALID_SQUARE = -1

# Display constants
PROMOTION_DISPLAY_LINE = 13

# Move constants
MIN_UCI_MOVE_LENGTH = 4

# Kings-in-center resign/draw detection
# Center squares: d4, d5, e4, e5
CENTER_SQUARES = {chess.D4, chess.D5, chess.E4, chess.E5}

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


class MoveState:
    """Tracks the state of a move in progress.
    
    For castling, supports both king-first and rook-first move ordering.
    When rook is moved first during castling:
    1. Rook is lifted from h1/a1/h8/a8 -> tracked in castling_rook_source
    2. Rook is placed on f1/d1/f8/d8 -> tracked in castling_rook_placed
    3. King is lifted from e1/e8 -> tracked in source_square
    4. King is placed on g1/c1/g8/c8 -> castling move is executed using king move
    """
    
    # Castling square definitions (chess square indices 0=a1, 63=h8)
    # King starting squares
    WHITE_KING_SQUARE = chess.E1  # 4
    BLACK_KING_SQUARE = chess.E8  # 60
    
    # Rook starting squares
    WHITE_KINGSIDE_ROOK = chess.H1   # 7
    WHITE_QUEENSIDE_ROOK = chess.A1  # 0
    BLACK_KINGSIDE_ROOK = chess.H8   # 63
    BLACK_QUEENSIDE_ROOK = chess.A8  # 56
    
    # Rook destination squares for castling
    WHITE_KINGSIDE_ROOK_DEST = chess.F1   # 5
    WHITE_QUEENSIDE_ROOK_DEST = chess.D1  # 3
    BLACK_KINGSIDE_ROOK_DEST = chess.F8   # 61
    BLACK_QUEENSIDE_ROOK_DEST = chess.D8  # 59
    
    # King destination squares for castling
    WHITE_KINGSIDE_KING_DEST = chess.G1   # 6
    WHITE_QUEENSIDE_KING_DEST = chess.C1  # 2
    BLACK_KINGSIDE_KING_DEST = chess.G8   # 62
    BLACK_QUEENSIDE_KING_DEST = chess.C8  # 58
    
    def __init__(self):
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_destination_squares = []
        self.computer_move_uci = ""
        self.is_forced_move = False
        self.source_piece_color = None  # Store piece color when lifted (for captures)
        
        # Castling state for rook-first ordering
        self.castling_rook_source = INVALID_SQUARE  # Where rook was lifted from
        self.castling_rook_placed = False  # True if rook has been placed in castling position
        self.late_castling_in_progress = False  # True when king is lifted for late castling
        
        # King lift resign tracking
        self.king_lifted_square = INVALID_SQUARE  # Square the king was lifted from
        self.king_lifted_color = None  # Color of the lifted king (chess.WHITE or chess.BLACK)
        self.king_lift_timer = None  # Timer for 3-second resign detection
    
    def reset(self):
        """Reset all move state variables."""
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_destination_squares = []
        self.computer_move_uci = ""
        self.is_forced_move = False
        self.source_piece_color = None
        self.castling_rook_source = INVALID_SQUARE
        self.castling_rook_placed = False
        self.late_castling_in_progress = False
        self._cancel_king_lift_timer()
        self.king_lifted_square = INVALID_SQUARE
        self.king_lifted_color = None
    
    def is_rook_castling_square(self, square: int) -> bool:
        """Check if a square is a rook's starting position for castling."""
        return square in (
            self.WHITE_KINGSIDE_ROOK, self.WHITE_QUEENSIDE_ROOK,
            self.BLACK_KINGSIDE_ROOK, self.BLACK_QUEENSIDE_ROOK
        )
    
    def is_valid_rook_castling_destination(self, rook_source: int, rook_dest: int) -> bool:
        """Check if rook placement is valid for castling.
        
        Args:
            rook_source: Square where rook was lifted from
            rook_dest: Square where rook was placed
            
        Returns:
            True if this is a valid rook castling destination
        """
        valid_pairs = {
            self.WHITE_KINGSIDE_ROOK: self.WHITE_KINGSIDE_ROOK_DEST,
            self.WHITE_QUEENSIDE_ROOK: self.WHITE_QUEENSIDE_ROOK_DEST,
            self.BLACK_KINGSIDE_ROOK: self.BLACK_KINGSIDE_ROOK_DEST,
            self.BLACK_QUEENSIDE_ROOK: self.BLACK_QUEENSIDE_ROOK_DEST,
        }
        return valid_pairs.get(rook_source) == rook_dest
    
    def get_castling_king_move(self, rook_source: int) -> str:
        """Get the king's UCI move for castling based on rook source.
        
        Args:
            rook_source: The square the rook was lifted from
            
        Returns:
            UCI string for the king's castling move (e.g., "e1g1")
        """
        castling_moves = {
            self.WHITE_KINGSIDE_ROOK: "e1g1",
            self.WHITE_QUEENSIDE_ROOK: "e1c1",
            self.BLACK_KINGSIDE_ROOK: "e8g8",
            self.BLACK_QUEENSIDE_ROOK: "e8c8",
        }
        return castling_moves.get(rook_source, "")
    
    def set_computer_move(self, uci_move: str, forced: bool = True):
        """Set the computer move that the player is expected to make."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return False
        self.computer_move_uci = uci_move
        self.is_forced_move = forced
        return True
    
    def _cancel_king_lift_timer(self):
        """Cancel any active king lift resign timer."""
        if self.king_lift_timer is not None:
            self.king_lift_timer.cancel()
            self.king_lift_timer = None


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
    
    def __init__(self, save_to_database: bool = True):
        """Initialize GameManager.
        
        Args:
            save_to_database: If True, game moves are saved to the database.
                             If False, database operations are disabled (for position games).
        """
        # Logical chess board - this is the AUTHORITY for game state
        # Physical board must conform to this state
        self.chess_board = chess.Board()
        self.move_state = MoveState()
        self.correction_mode = CorrectionMode()
        
        # Database control
        self.save_to_database = save_to_database
        
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
        # on_kings_in_center() -> None: Called when both kings detected in center squares
        # on_kings_in_center_cancel() -> None: Called when kings-in-center gesture is cancelled (pieces returned)
        # on_king_lift_resign(color: chess.Color) -> None: Called when king held off board for 3+ seconds
        # on_king_lift_resign_cancel() -> None: Called when king-lift resign menu should be dismissed
        # on_terminal_position(result: str, termination: str) -> None: Called when position is terminal
        #   (e.g., after correction mode exits for a checkmate/stalemate position)
        self.on_promotion_needed = None
        self.on_back_pressed = None
        self.on_kings_in_center = None
        self.on_kings_in_center_cancel = None
        self._kings_in_center_menu_active = False  # Track if the menu is showing
        self.on_king_lift_resign = None
        self.on_king_lift_resign_cancel = None
        self._king_lift_resign_menu_active = False  # Track if the king-lift resign menu is showing
        self.on_terminal_position = None
        
        # Display bridge - consolidated interface for display-related operations
        # Set by ProtocolManager to connect GameManager with DisplayManager
        # Provides: get_clock_times, set_clock_times, get_eval_score, update_position,
        #           show_check_alert, show_queen_threat, clear_alerts, analyze_position
        self.display_bridge = None
        
        # Player configuration - which color(s) are human players
        # In 2-player mode, both colors are human. In engine mode, only player_color is human.
        # Set by ProtocolManager after initialization.
        self.player_color = None  # chess.WHITE, chess.BLACK, or None (meaning both are human)
        
        # Thread control
        self.should_stop = False
        self.game_thread = None
        self._stop_event = threading.Event()
        
        # Ready state and event queue for synchronization
        # Events received before ready are queued and replayed when ready
        self._is_ready = False
        
        # Pending hint move for position games
        # Stored as (from_square, to_square) tuple, applied after correction mode exits
        self._pending_hint_squares = None
        self._pending_field_events = []
        self._ready_lock = threading.Lock()
        
        # Async task queue for post-move operations
        # Ensures all I/O operations (board serial, database, callbacks) execute in order
        self._task_queue = queue.Queue()
        self._task_worker_thread = None
        self._start_task_worker()
    
    def _start_task_worker(self):
        """Start the background worker thread for async task processing.
        
        The worker processes tasks from the queue sequentially, ensuring
        proper ordering of I/O operations across multiple rapid moves.
        """
        def worker():
            while not self._stop_event.is_set():
                try:
                    # Wait for task with timeout to allow checking stop event
                    try:
                        task = self._task_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    
                    # Execute the task
                    try:
                        task()
                    except Exception as e:
                        log.error(f"[GameManager._task_worker] Error executing task: {e}")
                    finally:
                        self._task_queue.task_done()
                        
                except Exception as e:
                    log.error(f"[GameManager._task_worker] Unexpected error in worker loop: {e}")
        
        self._task_worker_thread = threading.Thread(target=worker, daemon=True, name="GameManager-TaskWorker")
        self._task_worker_thread.start()
        log.debug("[GameManager] Task worker thread started")
    
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
    
    def _get_clock_times_for_db(self) -> tuple:
        """Get clock times for database storage.

        Returns:
            Tuple of (white_seconds, black_seconds), or (None, None) if unavailable
        """
        if self.display_bridge:
            try:
                return self.display_bridge.get_clock_times()
            except Exception as e:
                log.debug(f"[GameManager._get_clock_times_for_db] Error getting clock times: {e}")
        return (None, None)
    
    def _get_eval_score_for_db(self) -> int:
        """Get evaluation score for database storage.

        Returns:
            Evaluation score in centipawns (from white's perspective), or None if unavailable
        """
        if self.display_bridge:
            try:
                return self.display_bridge.get_eval_score()
            except Exception as e:
                log.debug(f"[GameManager._get_eval_score_for_db] Error getting eval score: {e}")
        return None
    
    def _update_game_result(self, result_string: str, termination: str, context: str = ""):
        """Update game result in database and trigger event callback."""
        # Only update database if game has been properly initialized
        # This prevents database operations with invalid game ID (game_db_id = -1) before _reset_game() is called
        if self.database_session is not None and self.game_db_id >= 0:
            models = _get_models()
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
        
        board.beep(board.SOUND_GENERAL, event_type='game_event')
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
                models = _get_models()
                db_last_move = self.database_session.query(models.GameMove).order_by(
                    models.GameMove.id.desc()
                ).first()
                if db_last_move is not None:
                    self.database_session.delete(db_last_move)
                    self.database_session.commit()
            
            self.chess_board.pop()
            AssetManager.write_fen_log(self.chess_board.fen())
            board.beep(board.SOUND_GENERAL, event_type='game_event')
            
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
            
            # Post-takeback validation uses low-priority queue to avoid blocking polling.
            # If the queue is busy, validation is skipped - the takeback was already
            # validated by comparing current state to previous state before executing it.
            current = board.getChessStateLowPriority()
            if current is not None:
                expected_state = self._chess_board_to_state(self.chess_board)
                if expected_state is not None and not self._validate_board_state(current, expected_state):
                    log.info("[GameManager._check_takeback] Board state incorrect after takeback, entering correction mode")
                    self._enter_correction_mode()
                    self._provide_correction_guidance(current, expected_state)
            
            return True

        return False

    def set_pending_hint(self, from_square: int, to_square: int):
        """Set a pending hint move to be shown after correction mode exits.
        
        Used by position loading to defer hint display until the board
        is correctly set up.
        
        Args:
            from_square: Source square index (0-63)
            to_square: Destination square index (0-63)
        """
        self._pending_hint_squares = (from_square, to_square)
        log.debug(f"[GameManager.set_pending_hint] Stored hint: {chess.square_name(from_square)} -> {chess.square_name(to_square)}")

    def clear_pending_hint(self):
        """Clear any pending hint move."""
        if self._pending_hint_squares is not None:
            log.debug("[GameManager.clear_pending_hint] Cleared pending hint")
            self._pending_hint_squares = None

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
        """Exit correction mode and resume normal game flow.
        
        If a pending hint move was set (from position loading), it is shown
        on the LEDs after correction mode exits.
        """
        self.correction_mode.exit()
        log.warning("[GameManager._exit_correction_mode] Exited correction mode")
        
        # Turn off correction LEDs first
        board.ledsOff()
        
        # Reset move state variables
        self.move_state.source_square = INVALID_SQUARE
        self.move_state.legal_destination_squares = []
        self.move_state.opponent_source_square = INVALID_SQUARE
        
        # Check if position is already terminal (checkmate, stalemate, insufficient material)
        # This can happen when loading a position that's already game-over
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is not None:
            result_string = str(self.chess_board.result())
            termination = str(outcome.termination).replace("Termination.", "")
            log.info(f"[GameManager._exit_correction_mode] Position is terminal: {termination} ({result_string})")
            # Clear any pending hints since game is over
            self._pending_hint_squares = None
            # Notify via callback
            if self.on_terminal_position:
                self.on_terminal_position(result_string, termination)
            return
        
        # Restore forced move LEDs if needed
        if self.move_state.is_forced_move and self.move_state.computer_move_uci:
            if len(self.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH:
                from_sq, to_sq = self._uci_to_squares(self.move_state.computer_move_uci)
                if from_sq is not None and to_sq is not None:
                    board.ledFromTo(from_sq, to_sq, repeat=0)
                    log.info(f"[GameManager._exit_correction_mode] Restored forced move LEDs: {self.move_state.computer_move_uci}")
        # Apply pending hint move if set (from position loading)
        elif self._pending_hint_squares is not None:
            from_sq, to_sq = self._pending_hint_squares
            board.ledFromTo(from_sq, to_sq, repeat=0)
            log.info(f"[GameManager._exit_correction_mode] Showing hint LEDs: {chess.square_name(from_sq)} -> {chess.square_name(to_sq)}")
            # Clear the hint after showing it once
            self._pending_hint_squares = None
        else:
            # No forced move or pending hint - trigger turn event so engine can move
            # if it's the engine's turn. This handles resuming games where the engine
            # needs to make a move after the board is corrected.
            self._switch_turn_with_event()
    
    def _check_kings_in_center_from_state(self, missing_squares: list, extra_squares: list) -> bool:
        """Check if the misplaced piece state indicates a kings-in-center gesture.
        
        The gesture is detected when:
        1. Both king squares (where kings should be) are in missing_squares
        2. At least 2 center squares (d4, d5, e4, e5) are in extra_squares
        
        Args:
            missing_squares: List of squares that should have pieces but don't
            extra_squares: List of squares that have pieces but shouldn't
            
        Returns:
            True if kings-in-center gesture detected, False otherwise
        """
        # Don't trigger resign/draw gesture if the game is already over
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is not None:
            log.debug(f"[GameManager._check_kings_in_center_from_state] Skipping - game already over: {outcome.termination}")
            return False
        
        # Find where kings should be according to logical board
        white_king_square = self.chess_board.king(chess.WHITE)
        black_king_square = self.chess_board.king(chess.BLACK)
        
        if white_king_square is None or black_king_square is None:
            return False
        
        # Check if both king squares are missing pieces
        white_king_missing = white_king_square in missing_squares
        black_king_missing = black_king_square in missing_squares
        
        if not (white_king_missing and black_king_missing):
            return False
        
        # Check if at least 2 center squares have extra pieces
        center_extras = [sq for sq in extra_squares if sq in CENTER_SQUARES]
        
        if len(center_extras) >= 2:
            log.debug(f"[GameManager] Kings-in-center detected: "
                     f"white_king={chess.square_name(white_king_square)} missing, "
                     f"black_king={chess.square_name(black_king_square)} missing, "
                     f"center_extras={[chess.square_name(sq) for sq in center_extras]}")
            return True
        
        return False
    
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
        
        # Check for kings-in-center gesture (resign/draw)
        # Detect when both kings are missing from expected squares and pieces are on center squares
        if self._check_kings_in_center_from_state(missing_squares, extra_squares):
            log.info("[GameManager._provide_correction_guidance] Kings-in-center gesture detected")
            self._exit_correction_mode()
            board.ledsOff()
            self.move_state.reset()
            self._kings_in_center_menu_active = True
            if self.on_kings_in_center:
                self.on_kings_in_center()
            return
        
        log.warning(f"[GameManager._provide_correction_guidance] Found {len(extra_squares)} wrong pieces, {len(missing_squares)} missing pieces")
        
        # Guide one piece at a time
        if len(extra_squares) > 0 and len(missing_squares) > 0:
            if len(extra_squares) == 1 and len(missing_squares) == 1:
                from_idx = extra_squares[0]
                to_idx = missing_squares[0]
            else:
                # Use Hungarian algorithm for optimal pairing if scipy is available
                linear_sum_assignment = _get_linear_sum_assignment()
                if linear_sum_assignment is not None:
                    n_extra = len(extra_squares)
                    n_missing = len(missing_squares)
                    costs = np.zeros((n_extra, n_missing))
                    for i, extra_sq in enumerate(extra_squares):
                        for j, missing_sq in enumerate(missing_squares):
                            costs[i, j] = manhattan_distance(extra_sq, missing_sq)
                    row_ind, col_ind = linear_sum_assignment(costs)
                    from_idx = extra_squares[row_ind[0]]
                    to_idx = missing_squares[col_ind[0]]
                else:
                    # Fallback: guide first extra piece to nearest missing square
                    log.warning("[GameManager._provide_correction_guidance] scipy unavailable, using simple fallback")
                    from_idx = extra_squares[0]
                    # Find nearest missing square by Manhattan distance
                    min_dist = float('inf')
                    to_idx = missing_squares[0]
                    for missing_sq in missing_squares:
                        dist = manhattan_distance(from_idx, missing_sq)
                        if dist < min_dist:
                            min_dist = dist
                            to_idx = missing_sq
            
            board.ledsOff()
            # Use faster flashing (speed=10) for correction guidance to distinguish from normal moves (default speed=3)
            board.ledFromTo(from_idx, to_idx, speed=10, repeat=0)
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
        
        Note: When sliding pieces, sensors may briefly show incorrect states.
        A small delay allows sensors to settle before polling board state.
        """
        # Small delay to allow sensors to settle after piece placement
        # This helps with sliding pieces where sensors may briefly show both squares
        is_place = (piece_event == 1)
        if is_place:
            time.sleep(0.05)  # 50ms delay for sensor settling
        
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
            board.beep(board.SOUND_GENERAL, event_type='game_event')
            self._exit_correction_mode()
            return
        
        # Still incorrect, update guidance using current logical board as authority
        # Recalculate expected state from logical board (authority) in case it changed
        if current_physical_state is not None:
            current_expected_state = self._chess_board_to_state(self.chess_board)
            if current_expected_state is not None:
                self._provide_correction_guidance(current_physical_state, current_expected_state)
    
    def _handle_piece_lift(self, field: int, piece_color):
        """Handle piece lift event.
        
        For castling support, tracks when a rook is lifted from a castling position.
        This allows rook-first castling where the player moves the rook before the king.
        
        If a rook move was executed and the king is subsequently lifted from its
        starting square, this may be a late castling attempt.
        """
        is_current_player_piece = (self.chess_board.turn == chess.WHITE) == (piece_color == True)
        
        # Check if this is a late castling attempt
        # This happens when:
        # 1. A rook move was already executed (castling_rook_placed is True)
        # 2. The king is now being lifted from its starting square
        # Note: We check based on which rook moved, not whose turn it is, because
        # the engine may have already responded (changing the turn back to the player).
        if self.move_state.castling_rook_placed:
            # Determine the expected king square based on which rook moved
            expected_king_square = None
            expected_king_color = None
            if self.move_state.castling_rook_source in (MoveState.WHITE_KINGSIDE_ROOK, MoveState.WHITE_QUEENSIDE_ROOK):
                expected_king_square = MoveState.WHITE_KING_SQUARE
                expected_king_color = chess.WHITE
            elif self.move_state.castling_rook_source in (MoveState.BLACK_KINGSIDE_ROOK, MoveState.BLACK_QUEENSIDE_ROOK):
                expected_king_square = MoveState.BLACK_KING_SQUARE
                expected_king_color = chess.BLACK
            
            # Check if this is the king being lifted from the expected square
            if field == expected_king_square:
                piece_at_field = self.chess_board.piece_at(field)
                is_correct_king = (piece_at_field is not None and 
                                   piece_at_field.piece_type == chess.KING and
                                   piece_at_field.color == expected_king_color)
                
                if is_correct_king:
                    # This is a late castling attempt - king lifted after rook was moved
                    log.info(f"[GameManager._handle_piece_lift] Late castling detected - king lifted from {chess.square_name(field)} after rook move")
                    # Track this as a potential late castling
                    self.move_state.source_square = field
                    self.move_state.source_piece_color = piece_color
                    self.move_state.late_castling_in_progress = True  # Suppress board validation
                    # Set legal destinations to include only the castling destination
                    king_dest = None
                    if self.move_state.castling_rook_source == MoveState.WHITE_KINGSIDE_ROOK:
                        king_dest = MoveState.WHITE_KINGSIDE_KING_DEST
                    elif self.move_state.castling_rook_source == MoveState.WHITE_QUEENSIDE_ROOK:
                        king_dest = MoveState.WHITE_QUEENSIDE_KING_DEST
                    elif self.move_state.castling_rook_source == MoveState.BLACK_KINGSIDE_ROOK:
                        king_dest = MoveState.BLACK_KINGSIDE_KING_DEST
                    elif self.move_state.castling_rook_source == MoveState.BLACK_QUEENSIDE_ROOK:
                        king_dest = MoveState.BLACK_QUEENSIDE_KING_DEST
                    
                    self.move_state.legal_destination_squares = [field, king_dest] if king_dest else [field]
                    return
            
            # If we reach here and it's not the king from the expected square,
            # but some other piece is being lifted, clear castling tracking
            # (the player is making a different move)
            if not is_current_player_piece:
                # Non-player piece lifted - might be executing the forced move
                # Don't clear castling tracking yet
                pass
            elif self.move_state.source_square < 0:
                # Player is starting a new move (not the king for castling)
                # Clear castling tracking as the player is abandoning the late castling
                log.info(f"[GameManager._handle_piece_lift] Late castling abandoned - different piece lifted from {chess.square_name(field)}")
                self.move_state.castling_rook_source = INVALID_SQUARE
                self.move_state.castling_rook_placed = False
                self.move_state.late_castling_in_progress = False
        
        # Check if this is a rook lift from a castling position (for rook-first castling)
        # Only track if:
        # 1. It's the current player's piece
        # 2. The piece is a rook at a castling starting square
        # 3. We're not already tracking a move in progress
        if is_current_player_piece and self.move_state.source_square < 0:
            piece_at_field = self.chess_board.piece_at(field)
            if piece_at_field is not None and piece_at_field.piece_type == chess.ROOK:
                if self.move_state.is_rook_castling_square(field):
                    # Check if castling is actually legal (not just has rights)
                    # Castling rights only track if king/rook have moved, but castling
                    # can be illegal due to: pieces blocking path, king in check,
                    # king passing through attacked square, or king landing on attacked square.
                    # Use legal_moves to verify castling is actually possible.
                    castling_move = None
                    if field == MoveState.WHITE_KINGSIDE_ROOK:
                        castling_move = chess.Move.from_uci("e1g1")
                    elif field == MoveState.WHITE_QUEENSIDE_ROOK:
                        castling_move = chess.Move.from_uci("e1c1")
                    elif field == MoveState.BLACK_KINGSIDE_ROOK:
                        castling_move = chess.Move.from_uci("e8g8")
                    elif field == MoveState.BLACK_QUEENSIDE_ROOK:
                        castling_move = chess.Move.from_uci("e8c8")
                    
                    can_castle = castling_move is not None and castling_move in self.chess_board.legal_moves
                    
                    if can_castle:
                        log.info(f"[GameManager._handle_piece_lift] Potential castling rook lifted from {chess.square_name(field)}")
                        self.move_state.castling_rook_source = field
                        # Store piece color for use during PLACE event (important for captures
                        # where destination square has opponent's piece). Even though we don't
                        # set source_square yet, we need the color for proper piece identification.
                        self.move_state.source_piece_color = piece_color
        
        # If we're tracking a potential castling rook, don't set source_square here.
        # The source_square will be set in _handle_piece_place when the rook is placed,
        # allowing the castling tracking logic to check castling_rook_source first.
        if self.move_state.castling_rook_source == INVALID_SQUARE:
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
        
        # King-lift resign detection: if a human player's king is lifted, start 3-second timer
        # This works in any game mode but only for human players (not engine's king)
        piece_at_field = self.chess_board.piece_at(field)
        if piece_at_field is not None and piece_at_field.piece_type == chess.KING:
            king_color = piece_at_field.color
            # Check if this is a human player's king
            # In 2-player mode (player_color is None), both colors are human
            # In engine mode, only player_color is human
            is_human_king = (self.player_color is None or king_color == self.player_color)
            
            if is_human_king:
                # Cancel any existing timer and start a new one
                self.move_state._cancel_king_lift_timer()
                self.move_state.king_lifted_square = field
                self.move_state.king_lifted_color = king_color
                
                # Start 3-second timer for resign menu
                def _king_lift_timeout():
                    log.info(f"[GameManager] King held off board for 3 seconds - showing resign menu for {'White' if king_color == chess.WHITE else 'Black'}")
                    self._king_lift_resign_menu_active = True
                    if self.on_king_lift_resign:
                        self.on_king_lift_resign(king_color)
                
                self.move_state.king_lift_timer = threading.Timer(3.0, _king_lift_timeout)
                self.move_state.king_lift_timer.daemon = True
                self.move_state.king_lift_timer.start()
                log.debug(f"[GameManager._handle_piece_lift] King lifted from {chess.square_name(field)}, started 3-second resign timer")
        
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
        """Handle piece place event.
        
        For castling support, handles both king-first and rook-first ordering.
        When rook is moved first:
        1. Rook placement on castling destination is tracked (not treated as illegal)
        2. When king is subsequently placed on its castling destination, the move is executed
        """
        # Cancel king-lift resign timer on any piece placement
        # If the king-lift resign menu is active, cancel it when the king is placed
        if self.move_state.king_lift_timer is not None:
            self.move_state._cancel_king_lift_timer()
            log.debug(f"[GameManager._handle_piece_place] Cancelled king-lift resign timer")
            
            # If the resign menu is active and the king was placed back, cancel the menu
            if self._king_lift_resign_menu_active:
                log.info("[GameManager._handle_piece_place] King placed - cancelling resign menu")
                self._king_lift_resign_menu_active = False
                if self.on_king_lift_resign_cancel:
                    self.on_king_lift_resign_cancel()
            
            # Clear king lift tracking
            self.move_state.king_lifted_square = INVALID_SQUARE
            self.move_state.king_lifted_color = None
        
        # PRIORITY: Check for late castling completion FIRST, before any other validation
        # This prevents brief flashes of "misplaced piece" mode during the castling sequence
        if self.move_state.late_castling_in_progress:
            # Determine the expected king destination based on which rook moved
            expected_king_dest = None
            if self.move_state.castling_rook_source == MoveState.WHITE_KINGSIDE_ROOK:
                expected_king_dest = MoveState.WHITE_KINGSIDE_KING_DEST
            elif self.move_state.castling_rook_source == MoveState.WHITE_QUEENSIDE_ROOK:
                expected_king_dest = MoveState.WHITE_QUEENSIDE_KING_DEST
            elif self.move_state.castling_rook_source == MoveState.BLACK_KINGSIDE_ROOK:
                expected_king_dest = MoveState.BLACK_KINGSIDE_KING_DEST
            elif self.move_state.castling_rook_source == MoveState.BLACK_QUEENSIDE_ROOK:
                expected_king_dest = MoveState.BLACK_QUEENSIDE_KING_DEST
            
            if expected_king_dest is not None and field == expected_king_dest:
                # King placed on correct castling destination - execute late castling
                log.info(f"[GameManager._handle_piece_place] Late castling completion: King placed on {chess.square_name(field)}")
                self._execute_late_castling(self.move_state.castling_rook_source)
                return
            elif field == self.move_state.source_square:
                # King placed back on starting square - cancel late castling
                log.info(f"[GameManager._handle_piece_place] Late castling cancelled: King returned to {chess.square_name(field)}")
                self.move_state.reset()
                board.ledsOff()
                return
            else:
                # King placed on unexpected square - this is an error
                log.warning(f"[GameManager._handle_piece_place] Late castling failed: King placed on unexpected square {chess.square_name(field)}")
                board.beep(board.SOUND_WRONG_MOVE, event_type='error')
                self._enter_correction_mode()
                current_state = board.getChessState()
                expected_state = self._chess_board_to_state(self.chess_board)
                if expected_state is not None:
                    self._provide_correction_guidance(current_state, expected_state)
                self.move_state.reset()
                return
        
        is_current_player_piece = (self.chess_board.turn == chess.WHITE) == (piece_color == True)
        
        # Handle opponent piece placed back
        if not is_current_player_piece and \
           self.move_state.opponent_source_square >= 0 and \
           field == self.move_state.opponent_source_square:
            board.ledsOff()
            self.move_state.opponent_source_square = INVALID_SQUARE
            return
        
        # Check for rook move from castling position
        # If a rook is moved from h1/a1/h8/a8 to its castling destination (f1/d1/f8/d8),
        # treat it as a regular rook move (e.g., h1f1). This is a legal move in chess.
        # 
        # If the player subsequently moves the king to the castling destination,
        # we detect this was intended as castling, undo both moves, and execute castling.
        if self.move_state.castling_rook_source != INVALID_SQUARE and \
           self.move_state.source_square < 0:
            if field == self.move_state.castling_rook_source:
                # Rook placed back on its original square - cancel castling tracking
                log.info(f"[GameManager._handle_piece_place] Rook returned to {chess.square_name(field)} - cancelling potential castling")
                self.move_state.castling_rook_source = INVALID_SQUARE
                self.move_state.castling_rook_placed = False
                return
            
            # Rook is being moved somewhere - treat as a regular rook move
            # Set source_square so _execute_move can process it
            self.move_state.source_square = self.move_state.castling_rook_source
            self.move_state.legal_destination_squares = self._calculate_legal_squares(self.move_state.castling_rook_source)
            
            # Track that this was a potential castling rook move (for late castling detection)
            if self.move_state.is_valid_rook_castling_destination(
                self.move_state.castling_rook_source, field
            ):
                log.info(f"[GameManager._handle_piece_place] Rook moved to castling position {chess.square_name(field)} - treating as regular move, tracking for late castling")
                self.move_state.castling_rook_placed = True
            else:
                # Rook moved elsewhere - clear castling tracking
                self.move_state.castling_rook_source = INVALID_SQUARE
                self.move_state.castling_rook_placed = False
            
            # Fall through to normal move processing below
        
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
                    board.beep(board.SOUND_WRONG_MOVE, event_type='error')
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
        
        # Note: Late castling completion is handled at the very beginning of _handle_piece_place
        # when late_castling_in_progress is True. This ensures no other validation can trigger
        # "misplaced piece" mode during the castling sequence.
        
        # Check for illegal placement
        if field not in self.move_state.legal_destination_squares:
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
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
            # Also reset castling state if we're putting the king back
            self.move_state.castling_rook_source = INVALID_SQUARE
            self.move_state.castling_rook_placed = False
        else:
            # Valid move
            self._execute_move(field)
    
    def _execute_castling_move(self, rook_source: int):
        """Execute a castling move when the rook was moved first.
        
        The chess library represents castling as a king move (e.g., e1g1 for white kingside).
        This method converts the rook-first physical move sequence into the proper UCI format.
        
        Args:
            rook_source: The square the rook was lifted from (determines which castling type)
        """
        # Check if game is already over before executing move
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is not None:
            log.warning(f"[GameManager._execute_castling_move] Attempted to execute castling after game ended. Result: {self.chess_board.result()}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            board.ledsOff()
            self.move_state.reset()
            return
        
        # Get the king's UCI move for this castling
        castling_uci = self.move_state.get_castling_king_move(rook_source)
        if not castling_uci:
            log.error(f"[GameManager._execute_castling_move] Invalid rook source for castling: {rook_source}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            self.move_state.reset()
            return
        
        log.info(f"[GameManager._execute_castling_move] Executing rook-first castling: {castling_uci}")
        
        # Validate the castling move is legal
        try:
            move = chess.Move.from_uci(castling_uci)
            if move not in self.chess_board.legal_moves:
                log.error(f"[GameManager._execute_castling_move] Castling move {castling_uci} is not legal at current position")
                board.beep(board.SOUND_WRONG_MOVE, event_type='error')
                self._enter_correction_mode()
                current_state = board.getChessState()
                expected_state = self._chess_board_to_state(self.chess_board)
                if expected_state is not None:
                    self._provide_correction_guidance(current_state, expected_state)
                self.move_state.reset()
                return
        except ValueError as e:
            log.error(f"[GameManager._execute_castling_move] Invalid castling UCI: {castling_uci}. Error: {e}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            self.move_state.reset()
            return
        
        # Extract king's destination for LED feedback
        king_dest = chess.parse_square(castling_uci[2:4])
        
        # Push the castling move to the chess board
        try:
            self.chess_board.push(move)
        except (ValueError, AssertionError) as e:
            log.error(f"[GameManager._execute_castling_move] Failed to push castling move: {e}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            self.move_state.reset()
            return
        
        # Save to database (similar to _execute_move but simplified for castling)
        if self.database_session is not None and self.game_db_id >= 0:
            try:
                models = _get_models()
                white_clock, black_clock = self._get_clock_times_for_db()
                eval_score = self._get_eval_score_for_db()
                game_move = models.GameMove(
                    gameid=self.game_db_id,
                    move=castling_uci,
                    fen=str(self.chess_board.fen()),
                    white_clock=white_clock,
                    black_clock=black_clock,
                    eval_score=eval_score
                )
                self.database_session.add(game_move)
                self.database_session.commit()
            except Exception as db_error:
                log.error(f"[GameManager._execute_castling_move] Database error: {db_error}")
        elif self.database_session is not None and self.game_db_id < 0:
            # First move - need to create game first (handle this case)
            log.info("[GameManager._execute_castling_move] First move is castling - creating game")
            try:
                models = _get_models()
                game = models.Game(
                    source=self.source_file,
                    event=self.game_info['event'],
                    site=self.game_info['site'],
                    round=self.game_info['round'],
                    white=self.game_info['white'],
                    black=self.game_info['black']
                )
                self.database_session.add(game)
                self.database_session.flush()
                if hasattr(game, 'id') and game.id is not None:
                    self.game_db_id = game.id
                    white_clock, black_clock = self._get_clock_times_for_db()
                    # Create initial position move (no clock times for initial position)
                    initial_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
                    initial_move = models.GameMove(
                        gameid=self.game_db_id,
                        move='',
                        fen=initial_fen
                    )
                    self.database_session.add(initial_move)
                    # Create castling move
                    eval_score = self._get_eval_score_for_db()
                    game_move = models.GameMove(
                        gameid=self.game_db_id,
                        move=castling_uci,
                        fen=str(self.chess_board.fen()),
                        white_clock=white_clock,
                        black_clock=black_clock,
                        eval_score=eval_score
                    )
                    self.database_session.add(game_move)
                    self.database_session.commit()
            except Exception as db_error:
                log.error(f"[GameManager._execute_castling_move] Database error creating game: {db_error}")
                try:
                    self.database_session.rollback()
                except Exception:
                    pass
        
        AssetManager.write_fen_log(self.chess_board.fen())
        
        # Call move callback to update display
        if self.move_callback is not None:
            try:
                self.move_callback(castling_uci)
            except Exception as e:
                log.error(f"[GameManager._execute_castling_move] Error in move callback: {e}")
        
        # Reset move state (including castling tracking)
        self.move_state.reset()
        
        # LED and sound feedback
        board.ledsOff()
        board.beep(board.SOUND_GENERAL, event_type='game_event')
        board.led(king_dest)
        
        # Check game outcome
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is None:
            self._switch_turn_with_event()
        else:
            board.beep(board.SOUND_GENERAL, event_type='game_event')
            result_string = str(self.chess_board.result())
            termination = str(outcome.termination)
            self._update_game_result(result_string, termination, "_execute_castling_move")
    
    def _execute_late_castling(self, rook_source: int):
        """Execute castling when rook move was already made as a regular move.
        
        This handles the case where:
        1. Player moved rook from h1 to f1 (executed as regular move h1f1)
        2. Engine made a response move
        3. Player now moves king e1 to g1 (indicating they intended castling)
        
        We need to:
        1. Undo the engine's response move (if any)
        2. Undo the rook move from the logical board
        3. Execute the proper castling move (e1g1)
        4. Notify the takeback callback to re-trigger the engine
        
        Args:
            rook_source: The original square the rook was moved from (h1, a1, h8, a8)
        """
        log.info(f"[GameManager._execute_late_castling] Processing late castling for rook from {chess.square_name(rook_source)}")
        
        # Get the castling move UCI
        castling_uci = self.move_state.get_castling_king_move(rook_source)
        if not castling_uci:
            log.error(f"[GameManager._execute_late_castling] Invalid rook source: {rook_source}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            self.move_state.reset()
            return
        
        # Determine how many moves to undo:
        # - If it's the opponent's turn, undo 1 move (just the rook move)
        # - If it's the castling player's turn again, undo 2 moves (rook move + opponent response)
        # Actually, since the rook was the player's move, it's now the opponent's turn.
        # If the player is moving the king, they're moving out of turn, which means
        # either no opponent move was made yet, or we need to undo the opponent's move.
        
        # Check if the rook move is in the move stack
        if len(self.chess_board.move_stack) < 1:
            log.error("[GameManager._execute_late_castling] No moves in stack to undo")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            self.move_state.reset()
            return
        
        # Get the rook move UCI for database cleanup
        rook_move_uci = None
        if rook_source == MoveState.WHITE_KINGSIDE_ROOK:
            rook_move_uci = "h1f1"
        elif rook_source == MoveState.WHITE_QUEENSIDE_ROOK:
            rook_move_uci = "a1d1"
        elif rook_source == MoveState.BLACK_KINGSIDE_ROOK:
            rook_move_uci = "h8f8"
        elif rook_source == MoveState.BLACK_QUEENSIDE_ROOK:
            rook_move_uci = "a8d8"
        
        # Count moves to undo
        moves_to_undo = 0
        undone_moves = []
        
        # Check the move stack - we need to find and undo the rook move
        # The rook move should be either the last move (opponent hasn't moved yet)
        # or second-to-last (opponent has moved)
        for i in range(min(2, len(self.chess_board.move_stack))):
            check_move = self.chess_board.move_stack[-(i + 1)]
            if check_move.uci() == rook_move_uci:
                moves_to_undo = i + 1
                break
        
        if moves_to_undo == 0:
            log.error(f"[GameManager._execute_late_castling] Rook move {rook_move_uci} not found in recent moves")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            self.move_state.reset()
            return
        
        log.info(f"[GameManager._execute_late_castling] Undoing {moves_to_undo} move(s) to correct castling")
        
        # Undo the moves
        for i in range(moves_to_undo):
            undone_move = self.chess_board.pop()
            undone_moves.append(undone_move)
            log.info(f"[GameManager._execute_late_castling] Undone move: {undone_move.uci()}")
            
            # Remove from database
            if self.database_session is not None:
                try:
                    models = _get_models()
                    db_last_move = self.database_session.query(models.GameMove).filter(
                        models.GameMove.gameid == self.game_db_id
                    ).order_by(models.GameMove.id.desc()).first()
                    if db_last_move is not None:
                        self.database_session.delete(db_last_move)
                        self.database_session.commit()
                except Exception as e:
                    log.error(f"[GameManager._execute_late_castling] Error removing move from database: {e}")
        
        # Now verify castling is legal at this position
        try:
            castling_move = chess.Move.from_uci(castling_uci)
            if castling_move not in self.chess_board.legal_moves:
                log.error(f"[GameManager._execute_late_castling] Castling {castling_uci} not legal after undo")
                # Restore the moves we undid
                for move in reversed(undone_moves):
                    self.chess_board.push(move)
                board.beep(board.SOUND_WRONG_MOVE, event_type='error')
                self._enter_correction_mode()
                current_state = board.getChessState()
                expected_state = self._chess_board_to_state(self.chess_board)
                if expected_state is not None:
                    self._provide_correction_guidance(current_state, expected_state)
                self.move_state.reset()
                return
        except ValueError as e:
            log.error(f"[GameManager._execute_late_castling] Invalid castling UCI: {e}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            self.move_state.reset()
            return
        
        # Execute the castling move
        try:
            self.chess_board.push(castling_move)
        except (ValueError, AssertionError) as e:
            log.error(f"[GameManager._execute_late_castling] Failed to push castling: {e}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            self.move_state.reset()
            return
        
        log.info(f"[GameManager._execute_late_castling] Castling {castling_uci} executed successfully")
        
        # Save to database
        if self.database_session is not None and self.game_db_id >= 0:
            try:
                models = _get_models()
                white_clock, black_clock = self._get_clock_times_for_db()
                eval_score = self._get_eval_score_for_db()
                game_move = models.GameMove(
                    gameid=self.game_db_id,
                    move=castling_uci,
                    fen=str(self.chess_board.fen()),
                    white_clock=white_clock,
                    black_clock=black_clock,
                    eval_score=eval_score
                )
                self.database_session.add(game_move)
                self.database_session.commit()
            except Exception as db_error:
                log.error(f"[GameManager._execute_late_castling] Database error: {db_error}")
        
        AssetManager.write_fen_log(self.chess_board.fen())
        
        # Call move callback to update display
        if self.move_callback is not None:
            try:
                self.move_callback(castling_uci)
            except Exception as e:
                log.error(f"[GameManager._execute_late_castling] Error in move callback: {e}")
        
        # Reset move state
        self.move_state.reset()
        
        # LED and sound feedback
        king_dest = chess.parse_square(castling_uci[2:4])
        board.ledsOff()
        board.beep(board.SOUND_GENERAL, event_type='game_event')
        board.led(king_dest)
        
        # Notify takeback callback to re-trigger engine
        # This is used when moves_to_undo > 1 (opponent had already moved)
        if moves_to_undo > 1 and self.takeback_callback is not None:
            log.info("[GameManager._execute_late_castling] Calling takeback callback to re-trigger engine")
            try:
                self.takeback_callback()
            except Exception as e:
                log.error(f"[GameManager._execute_late_castling] Error in takeback callback: {e}")
        
        # Check game outcome
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is None:
            self._switch_turn_with_event()
        else:
            board.beep(board.SOUND_GENERAL, event_type='game_event')
            result_string = str(self.chess_board.result())
            termination = str(outcome.termination)
            self._update_game_result(result_string, termination, "_execute_late_castling")
    
    def _execute_move(self, target_square: int):
        """Execute a move from source to target square.
        
        Critical path is optimized for speed:
        1. Move validation and chess engine push are synchronous
        2. Board feedback (beep + LED) is sent immediately after push for minimum latency
        3. All other I/O operations (database, FEN log, callbacks) are performed
           asynchronously via a queue to ensure correct ordering
        
        Prevents moves from being executed after the game has ended.
        If the game is already over, logs a warning and returns early.
        """
        # Check if game is already over before executing move
        # This prevents moves from being executed after game termination, which would corrupt game state
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is not None:
            log.warning(f"[GameManager._execute_move] Attempted to execute move after game ended. Result: {self.chess_board.result()}, Termination: {outcome.termination}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
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
        
        # Validate move UCI format (fast, no I/O)
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError as e:
            log.error(f"[GameManager._execute_move] Invalid move UCI format: {move_uci}. Error: {e}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            board.ledsOff()
            self.move_state.reset()
            return
        
        # Capture FEN before move for database (needed for initial position record)
        fen_before_move = str(self.chess_board.fen())
        is_first_move = self.game_db_id < 0
        
        # CRITICAL PATH: Push move to chess engine
        # This is the only truly critical operation - must succeed before any feedback
        try:
            self.chess_board.push(move)
        except (ValueError, AssertionError) as e:
            log.error(f"[GameManager._execute_move] Illegal move or chess engine push failed: {move_uci}. Error: {e}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            board.ledsOff()
            self.move_state.reset()
            return
        
        # IMMEDIATE FEEDBACK: Beep and LED are sent synchronously here for minimum latency
        # These bypass the serial queue via _send_immediate() in sync_centaur
        board.ledsOff()
        board.beep(board.SOUND_GENERAL, event_type='game_event')
        board.led(target_square)
        
        # Capture state needed for async operations
        fen_after_move = str(self.chess_board.fen())
        late_castling_in_progress = self.move_state.late_castling_in_progress
        
        # Check game outcome (fast, no I/O)
        game_ended = False
        result_string = None
        termination = None
        outcome = self.chess_board.outcome(claim_draw=True)
        if outcome is not None:
            game_ended = True
            result_string = str(self.chess_board.result())
            termination = str(outcome.termination)
        
        # Preserve castling tracking state if a potential rook-first castling is in progress
        preserve_castling_rook_source = self.move_state.castling_rook_source
        preserve_castling_rook_placed = self.move_state.castling_rook_placed
        
        self.move_state.reset()
        
        # Restore castling tracking state if it was set (for late castling detection)
        if preserve_castling_rook_placed:
            self.move_state.castling_rook_source = preserve_castling_rook_source
            self.move_state.castling_rook_placed = preserve_castling_rook_placed
        
        # Switch turn event (fast, no I/O - just sets internal state)
        if not game_ended:
            self._switch_turn_with_event()
        
        # ASYNC: Remaining I/O operations run in background thread with queue for ordering
        # Board feedback (beep + LED) was already sent immediately above
        # Queue ensures: database → FEN log → callbacks → validation
        self._enqueue_post_move_tasks(
            target_square=target_square,
            move_uci=move_uci,
            fen_before_move=fen_before_move,
            fen_after_move=fen_after_move,
            is_first_move=is_first_move,
            late_castling_in_progress=late_castling_in_progress,
            game_ended=game_ended,
            result_string=result_string,
            termination=termination
        )
    
    def _enqueue_post_move_tasks(self, target_square: int, move_uci: str,
                                  fen_before_move: str, fen_after_move: str,
                                  is_first_move: bool, late_castling_in_progress: bool,
                                  game_ended: bool, result_string: str, termination: str):
        """Queue post-move tasks for async execution in order.
        
        All tasks are executed sequentially in a background thread to ensure
        proper ordering while not blocking the main game loop.
        
        Note: Board feedback (beep + LED) is sent IMMEDIATELY in _execute_move
        before this method is called, ensuring minimum latency for user feedback.
        
        Task order:
        1. Database operations - persist the move
        2. FEN log write
        3. Move callback (display update, emulator forwarding)
        4. Physical board validation (low priority - yields to polling commands)
        5. Game end handling (if applicable)
        
        Physical board validation uses getChessStateLowPriority() which yields
        to polling commands. If the board is busy with piece detection, validation
        is skipped - which is acceptable since moves are validated logically.
        """
        def execute_tasks():
            try:
                # 1. Database operations
                if self.database_session is not None:
                    try:
                        models = _get_models()
                        # Create new game if first move
                        if is_first_move:
                            game = models.Game(
                                source=self.source_file,
                                event=self.game_info['event'],
                                site=self.game_info['site'],
                                round=self.game_info['round'],
                                white=self.game_info['white'],
                                black=self.game_info['black']
                            )
                            self.database_session.add(game)
                            self.database_session.flush()
                            
                            if hasattr(game, 'id') and game.id is not None:
                                self.game_db_id = game.id
                                log.info(f"[GameManager.async] New game created (id={self.game_db_id})")
                                
                                # Initial position record (no clock times for initial position)
                                initial_move = models.GameMove(
                                    gameid=self.game_db_id,
                                    move='',
                                    fen=fen_before_move
                                )
                                self.database_session.add(initial_move)
                        
                        # Add this move
                        if self.game_db_id >= 0:
                            white_clock, black_clock = self._get_clock_times_for_db()
                            eval_score = self._get_eval_score_for_db()
                            game_move = models.GameMove(
                                gameid=self.game_db_id,
                                move=move_uci,
                                fen=fen_after_move,
                                white_clock=white_clock,
                                black_clock=black_clock,
                                eval_score=eval_score
                            )
                            self.database_session.add(game_move)
                            self.database_session.commit()
                            log.debug(f"[GameManager.async] Move {move_uci} committed to database")
                    except Exception as db_error:
                        log.error(f"[GameManager.async] Database error: {db_error}")
                        try:
                            self.database_session.rollback()
                        except Exception:
                            pass
                
                # 2. FEN log
                AssetManager.write_fen_log(fen_after_move)
                
                # 3. Move callback (updates display, forwards to emulators)
                if self.move_callback is not None:
                    try:
                        self.move_callback(move_uci)
                    except Exception as e:
                        log.error(f"[GameManager.async] Error in move callback: {e}")
                
                # 3.5. Check and queen threat detection (only if game not ended)
                # This triggers LED flashing and alert widget display
                if not game_ended:
                    try:
                        self._detect_check_and_threats()
                    except Exception as e:
                        log.error(f"[GameManager.async] Error detecting check/threats: {e}")
                
                # 4. Physical board validation (low priority - yields to polling)
                # Uses low-priority queue so validation doesn't delay piece event detection.
                # If the queue is busy with polling, validation is skipped - which is fine
                # since the chess engine already validates moves logically.
                if not late_castling_in_progress:
                    try:
                        current_physical_state = board.getChessStateLowPriority()
                        if current_physical_state is not None:
                            expected_logical_state = self._chess_board_to_state(self.chess_board)
                            if expected_logical_state is not None:
                                if not self._validate_board_state(current_physical_state, expected_logical_state):
                                    log.warning(f"[GameManager.async] Physical board mismatch after {move_uci}, entering correction mode")
                                    self._enter_correction_mode()
                                    self._provide_correction_guidance(current_physical_state, expected_logical_state)
                    except Exception as e:
                        log.debug(f"[GameManager.async] Error validating physical board: {e}")
                
                # 5. Game end handling
                if game_ended:
                    board.beep(board.SOUND_GENERAL, event_type='game_event')
                    self._update_game_result(result_string, termination, "_execute_move")
                        
            except Exception as e:
                log.error(f"[GameManager.async] Unexpected error in post-move tasks: {e}")
        
        # Add task to queue - worker thread will execute in order
        self._task_queue.put(execute_tasks)
    
    def receive_field(self, piece_event: int, field: int, time_in_seconds: float):
        """Handle field events (piece lift/place).
        
        If the game thread is not yet ready, events are queued and will be
        replayed when the thread becomes ready.
        """
        # Queue events if not ready
        with self._ready_lock:
            if not self._is_ready:
                log.info(f"[GameManager.receive_field] Not ready, queuing event: piece_event={piece_event}, field={field}")
                self._pending_field_events.append((piece_event, field, time_in_seconds))
                return
        
        self._process_field_event(piece_event, field, time_in_seconds)
    
    def _process_field_event(self, piece_event: int, field: int, time_in_seconds: float):
        """Process a field event (internal implementation)."""
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
        
        is_place = (piece_event == 1)
        
        # When a resign menu is active (kings-in-center or king-lift), check for:
        # 1. Board corrected (pieces returned to position) → cancel menu
        # 2. LIFT event → cancel menu and enter correction mode to guide pieces back
        if self._kings_in_center_menu_active or self._king_lift_resign_menu_active:
            expected_state = self._chess_board_to_state(self.chess_board)
            current_state = board.getChessState()
            
            # Check if board is now correct (pieces returned to position)
            if current_state is not None and expected_state is not None:
                if self._validate_board_state(current_state, expected_state):
                    log.info("[GameManager.receive_field] Board corrected while resign menu active - cancelling menu")
                    if self._kings_in_center_menu_active:
                        self._kings_in_center_menu_active = False
                        if self.on_kings_in_center_cancel:
                            self.on_kings_in_center_cancel()
                    if self._king_lift_resign_menu_active:
                        self._king_lift_resign_menu_active = False
                        self.move_state._cancel_king_lift_timer()
                        self.move_state.king_lifted_square = INVALID_SQUARE
                        self.move_state.king_lifted_color = None
                        if self.on_king_lift_resign_cancel:
                            self.on_king_lift_resign_cancel()
                    return
            
            # If a piece is lifted while menu is active, cancel menu and enter correction mode
            is_lift = (piece_event == 0)
            if is_lift:
                log.info("[GameManager.receive_field] Piece lifted while resign menu active - cancelling menu and entering correction mode")
                if self._kings_in_center_menu_active:
                    self._kings_in_center_menu_active = False
                    if self.on_kings_in_center_cancel:
                        self.on_kings_in_center_cancel()
                if self._king_lift_resign_menu_active:
                    self._king_lift_resign_menu_active = False
                    self.move_state._cancel_king_lift_timer()
                    self.move_state.king_lifted_square = INVALID_SQUARE
                    self.move_state.king_lifted_color = None
                    if self.on_king_lift_resign_cancel:
                        self.on_king_lift_resign_cancel()
                # Enter correction mode and provide guidance
                self._enter_correction_mode()
                if current_state is not None and expected_state is not None:
                    self._provide_correction_guidance(current_state, expected_state)
                return
            
            return  # Skip all other processing while menu is active (PLACE events)
        
        # Skip takeback and correction mode checks if late castling is in progress
        # During late castling, the board is intentionally in a transitional state
        if not self.move_state.late_castling_in_progress:
            # Check for takeback FIRST, before any other processing including correction mode
            # Takeback detection must work regardless of correction mode state
            # 
            # Optimization: Only check for takeback when no move is in progress (orphan PLACE).
            # If player has lifted a piece (source_square >= 0), they're making a move, not taking back.
            # This avoids a blocking getChessState() call on every normal move.
            if is_place and len(self.chess_board.move_stack) > 0 and self.move_state.source_square < 0:
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
        
        # Starting position detection: Only check when there's no active move in progress
        # (i.e., orphan PLACE event). During normal play (LIFT followed by PLACE), skip
        # this check to avoid blocking the serial queue with getChessState().
        # This allows players to reset by setting up the starting position, but only
        # detects it when pieces are being moved without a prior LIFT.
        if is_place and self.move_state.source_square < 0 and self.move_state.opponent_source_square < 0:
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
        - BACK after game over: Passes through to external callback (return to menu)
        - Other keys: Passed through to external callback

        Args:
            key_pressed: Key that was pressed (board.Key enum value)
        """
        # Handle BACK key - notify DisplayManager if game in progress
        if key_pressed == board.Key.BACK:
            # Check if game is over (checkmate, stalemate, etc.)
            outcome = self.chess_board.outcome(claim_draw=True)
            if outcome is not None:
                # Game is over - pass through to external callback for exit handling
                log.info(f"[GameManager] BACK pressed after game over ({outcome.termination}) - passing to external callback")
            elif self.is_game_in_progress():
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
        board.beep(board.SOUND_GENERAL, event_type='game_event')
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
        board.beep(board.SOUND_GENERAL, event_type='game_event')
        board.ledsOff()
    
    def handle_flag(self, flagged_color: chess.Color) -> None:
        """Handle time expiration (flag) for a player.

        When a player's clock runs out, they lose on time.

        Args:
            flagged_color: The color of the player whose time expired (they lose)
        """
        if flagged_color == chess.WHITE:
            result = "0-1"  # Black wins on time
            log.info("[GameManager] White flagged - Black wins on time")
        else:
            result = "1-0"  # White wins on time
            log.info("[GameManager] Black flagged - White wins on time")

        # Update database with result
        self._update_game_result(result, "Termination.TIME_FORFEIT", "handle_flag")

        # Play sound and turn off LEDs
        board.beep(board.SOUND_GENERAL, event_type='game_event')
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
                    models = _get_models()
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
            
            # Step 6: Clear all board LEDs and turn off any indicators
            # Note: Clock is managed by DisplayManager, reset via EVENT_NEW_GAME callback
            board.ledsOff()
            
            # Step 8: Reset game_db_id to -1 to indicate no active game in database
            # New game will be created when first move is made
            self.game_db_id = -1
            log.info("[GameManager._reset_game] Reset game_db_id to -1 - new game will be created on first move")
            
            # Step 9: Update FEN log
            AssetManager.write_fen_log(self.chess_board.fen())
            
            # Step 10: Notify callbacks of new game (but don't create DB entry yet)
            if self.event_callback is not None:
                self.event_callback(EVENT_NEW_GAME)
                # Determine which turn event to send based on current board state
                if self.chess_board.turn == chess.WHITE:
                    self.event_callback(EVENT_WHITE_TURN)
                else:
                    self.event_callback(EVENT_BLACK_TURN)
            
            # Step 11: Audio/visual feedback for game abandonment
            board.beep(board.SOUND_GENERAL, event_type='game_event')
            time.sleep(0.3)
            board.beep(board.SOUND_GENERAL, event_type='game_event')
            
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
        
        # Only create database session if save_to_database is enabled
        if self.save_to_database:
            database_uri = AssetManager.get_database_uri()
            # Configure SQLite with check_same_thread=False to allow connections created in this thread
            # to be used throughout the thread's lifetime. This is safe because we create and use
            # the engine entirely within this thread.
            create_engine = _get_create_engine()
            sessionmaker = _get_sessionmaker()
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
        else:
            log.info(f"[GameManager._game_thread] Database disabled for this game (position mode) in thread {thread_id}")
        
        board.ledsOff()
        log.info("[GameManager._game_thread] Ready to receive events from app coordinator")
        
        # Note: GameManager no longer subscribes to board events directly.
        # Events are routed from the app coordinator (universal.py) through
        # ProtocolManager.receive_key() and ProtocolManager.receive_field() methods.
        
        # Mark as ready and replay any queued events
        with self._ready_lock:
            self._is_ready = True
            pending_events = list(self._pending_field_events)
            self._pending_field_events.clear()
        
        if pending_events:
            log.info(f"[GameManager._game_thread] Replaying {len(pending_events)} queued field events")
            for piece_event, field, time_in_seconds in pending_events:
                self._process_field_event(piece_event, field, time_in_seconds)
        
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
        """Set the clock times for both players.
        
        Calls the set_clock_times callback if set (connected to DisplayManager).
        Used by Lichess emulator to update clock times from the server.
        """
        if self.set_clock_times:
            try:
                self.set_clock_times(white_seconds, black_seconds)
            except Exception as e:
                log.debug(f"[GameManager.set_clock] Error setting clock times: {e}")
    
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
                board.beep(board.SOUND_WRONG_MOVE, event_type='error')
                return
        except ValueError as e:
            log.error(f"[GameManager.computer_move] Invalid move UCI format: {uci_move}. Error: {e}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
            return
        
        # Light up LEDs to indicate the move
        from_sq, to_sq = self._uci_to_squares(uci_move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq, repeat=0)
    
    def _detect_check_and_threats(self) -> None:
        """Detect check and queen threats after a move, triggering appropriate callbacks.
        
        Called after each move to check:
        1. If the opponent's king is in check - triggers on_check callback
        2. If the opponent's queen is under attack - triggers on_queen_threat callback
        3. If neither applies - triggers on_alert_clear callback
        
        Priority: Check > Queen threat (only one alert at a time)
        """
        try:
            # Check if opponent is in check
            if self.chess_board.is_check():
                # Current side to move is in check
                side_in_check = self.chess_board.turn  # chess.WHITE or chess.BLACK
                is_black_in_check = (side_in_check == chess.BLACK)
                
                # Find the king that's in check
                king_square = self.chess_board.king(side_in_check)
                
                # Find one of the pieces giving check (checkers returns SquareSet)
                checkers = self.chess_board.checkers()
                if checkers and king_square is not None:
                    # Get the first (or only) checker
                    attacker_square = list(checkers)[0]
                    
                    log.info(f"[GameManager._detect_check_and_threats] CHECK: {'Black' if is_black_in_check else 'White'} king in check at {chess.square_name(king_square)} by piece at {chess.square_name(attacker_square)}")
                    
                    if self.display_bridge:
                        self.display_bridge.show_check_alert(is_black_in_check, attacker_square, king_square)
                    return
            
            # No check - check if opponent's queen is under attack
            side_to_move = self.chess_board.turn
            opponent_color = not side_to_move  # Opponent's pieces
            
            # Find opponent's queen
            queens = self.chess_board.pieces(chess.QUEEN, opponent_color)
            if queens:
                queen_square = list(queens)[0]  # Get first queen
                
                # Check if queen is attacked by current side to move
                attackers = self.chess_board.attackers(side_to_move, queen_square)
                if attackers:
                    attacker_square = list(attackers)[0]
                    is_black_queen_threatened = (opponent_color == chess.BLACK)
                    
                    log.info(f"[GameManager._detect_check_and_threats] QUEEN THREAT: {'Black' if is_black_queen_threatened else 'White'} queen at {chess.square_name(queen_square)} attacked by piece at {chess.square_name(attacker_square)}")
                    
                    if self.display_bridge:
                        self.display_bridge.show_queen_threat(is_black_queen_threatened, attacker_square, queen_square)
                    return
            
            # No check or queen threat - clear any existing alert
            if self.display_bridge:
                self.display_bridge.clear_alerts()
                
        except Exception as e:
            log.error(f"[GameManager._detect_check_and_threats] Error detecting threats: {e}")
    
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
        
        models = _get_models()
        select = _get_sqlalchemy_select()
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
        # Note: Clock is managed by DisplayManager, cleaned up when display manager is destroyed
        
        # Reset ready state
        with self._ready_lock:
            self._is_ready = False
            self._pending_field_events.clear()

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
    """Start the clock (backward compatibility function).
    
    Note: Clock is now managed by DisplayManager via event callbacks.
    This function is kept for backward compatibility but is a no-op.
    """
    pass


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

