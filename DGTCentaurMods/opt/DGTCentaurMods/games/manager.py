"""
Chess game manager with complete state management, turn tracking, and event-driven architecture.

This module provides:
- Complete chess game state management
- Automatic turn tracking
- Event-driven notifications
- Hardware abstraction via board.py
- Misplaced piece guidance
- Opponent move guidance even if misplaced pieces occur before opponent move completes
"""

import chess
import threading
import time
from typing import Callable, Optional, List, Tuple, Any
from enum import IntEnum
import numpy as np
from scipy.optimize import linear_sum_assignment

from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.db import models
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import func
from DGTCentaurMods.config import paths


class GameEvent(IntEnum):
    """Game event types."""
    NEW_GAME = 1
    WHITE_TURN = 2
    BLACK_TURN = 3
    MOVE_MADE = 4
    GAME_OVER = 5
    TAKEBACK = 6
    DRAW_REQUESTED = 7
    RESIGN_REQUESTED = 8


# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
MIN_UCI_MOVE_LENGTH = 4
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# Starting position state (pieces present on starting squares)
STARTING_STATE = bytearray(
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 1 (white pieces)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 2 (white pawns)
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 3
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 4
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 5
    b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Rank 6
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 7 (black pawns)
    b'\x01\x01\x01\x01\x01\x01\x01\x01'  # Rank 8 (black pieces)
)


class GameManager:
    """
    Manages chess game state, turn tracking, and hardware interaction.
    
    Provides event-driven notifications for game events and handles
    misplaced piece guidance and opponent move guidance.
    """
    
    def __init__(
        self,
        event_callback: Optional[Callable[[GameEvent, dict], None]] = None,
        move_callback: Optional[Callable[[str], None]] = None,
        key_callback: Optional[Callable[[int], None]] = None
    ):
        """
        Initialize game manager.
        
        Args:
            event_callback: Called with (GameEvent, event_data) for game events
            move_callback: Called with UCI move string when a move is made
            key_callback: Called with key code when a key is pressed
        """
        self.event_callback = event_callback
        self.move_callback = move_callback
        self.key_callback = key_callback
        
        self.board = chess.Board()
        self.board_states: List[bytearray] = []
        self.running = False
        self.kill_flag = threading.Event()
        
        # Move tracking state
        self.source_square: Optional[int] = None
        self.legal_squares: List[int] = []
        self.opponent_source_square: Optional[int] = None
        
        # Forced move state (for computer moves)
        self.forced_move: Optional[str] = None
        self.forced_move_active = False
        
        # Correction mode state
        self.correction_mode = False
        self.correction_expected_state: Optional[bytearray] = None
        
        # Game metadata
        self.game_db_id: Optional[int] = None
        self.session: Optional[Session] = None
        
        # Threading
        self.game_thread: Optional[threading.Thread] = None
        
    def _validate_board_state(self, current: bytearray, expected: Optional[bytearray]) -> bool:
        """Validate that current board state matches expected state."""
        if current is None or expected is None:
            return False
        if len(current) != BOARD_SIZE or len(expected) != BOARD_SIZE:
            return False
        return bytearray(current) == bytearray(expected)
    
    def _is_starting_position(self, state: bytearray) -> bool:
        """Check if board state matches starting position."""
        if state is None or len(state) != BOARD_SIZE:
            return False
        return bytearray(state) == STARTING_STATE
    
    def _uci_to_squares(self, uci_move: str) -> Tuple[Optional[int], Optional[int]]:
        """Convert UCI move string to square indices."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return None, None
        try:
            from_sq = chess.parse_square(uci_move[0:2])
            to_sq = chess.parse_square(uci_move[2:4])
            return from_sq, to_sq
        except (ValueError, IndexError):
            return None, None
    
    def _calculate_legal_squares(self, square: int) -> List[int]:
        """Calculate legal destination squares for a piece at the given square."""
        legal_squares = [square]  # Include source square
        for move in self.board.legal_moves:
            if move.from_square == square:
                legal_squares.append(move.to_square)
        return legal_squares
    
    def _reset_move_state(self):
        """Reset move-related state variables."""
        self.source_square = None
        self.legal_squares = []
        self.opponent_source_square = None
        board.ledsOff()
    
    def _provide_correction_guidance(self, current_state: bytearray, expected_state: bytearray):
        """
        Provide LED guidance to correct misplaced pieces using Hungarian algorithm.
        
        Computes optimal pairing between misplaced pieces for minimal movement distance.
        """
        if current_state is None or expected_state is None:
            return
        
        if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
            return
        
        def _row_col(idx: int) -> Tuple[int, int]:
            """Convert square index to (row, col)."""
            return (idx // BOARD_WIDTH), (idx % BOARD_WIDTH)
        
        def _manhattan_dist(a: int, b: int) -> int:
            """Manhattan distance between two squares."""
            ar, ac = _row_col(a)
            br, bc = _row_col(b)
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
        
        # Guide one piece at a time using Hungarian algorithm
        if len(wrong_locations) > 0 and len(missing_origins) > 0:
            if len(wrong_locations) == 1 and len(missing_origins) == 1:
                from_idx = wrong_locations[0]
                to_idx = missing_origins[0]
            else:
                # Create cost matrix based on Manhattan distances
                costs = np.zeros((len(wrong_locations), len(missing_origins)))
                for i, wl in enumerate(wrong_locations):
                    for j, mo in enumerate(missing_origins):
                        costs[i, j] = _manhattan_dist(wl, mo)
                
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
            board.ledsOff()
            if len(missing_origins) > 0:
                for idx in missing_origins:
                    board.led(idx, intensity=5)
                log.warning(f"[GameManager] Pieces missing at: {[chess.square_name(sq) for sq in missing_origins]}")
            elif len(wrong_locations) > 0:
                for idx in wrong_locations:
                    board.led(idx, intensity=5)
                log.warning(f"[GameManager] Extra pieces at: {[chess.square_name(sq) for sq in wrong_locations]}")
    
    def _enter_correction_mode(self):
        """Enter correction mode to guide user in fixing board state."""
        self.correction_mode = True
        self.correction_expected_state = self.board_states[-1] if self.board_states else None
        log.warning("[GameManager] Entered correction mode")
    
    def _exit_correction_mode(self):
        """Exit correction mode and restore forced move LEDs if needed."""
        self.correction_mode = False
        self.correction_expected_state = None
        log.warning("[GameManager] Exited correction mode")
        
        # Reset move state
        self.source_square = None
        self.legal_squares = []
        self.opponent_source_square = None
        
        # Restore forced move LEDs if pending
        if self.forced_move_active and self.forced_move:
            from_sq, to_sq = self._uci_to_squares(self.forced_move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
                log.info(f"[GameManager] Restored forced move LEDs: {self.forced_move}")
    
    def _handle_promotion(self, target_square: int, piece_name: str, forced: bool) -> str:
        """
        Handle pawn promotion by prompting user for piece choice.
        
        Returns:
            Promotion piece suffix ("q", "r", "b", "n") or empty string
        """
        is_white_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
        is_black_promotion = (target_square // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
        
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
        return "q"  # Default for forced moves
    
    def _check_takeback(self, current_state: bytearray) -> bool:
        """
        Check if a takeback is in progress by comparing current state to previous state.
        
        Returns:
            True if takeback detected, False otherwise
        """
        if len(self.board_states) < 2:
            return False
        
        previous_state = self.board_states[-2]
        if self._validate_board_state(current_state, previous_state):
            log.info("[GameManager] Takeback detected")
            board.ledsOff()
            self.board_states.pop()
            
            # Remove last move from database
            if self.session and self.game_db_id:
                last_move = self.session.query(models.GameMove).filter(
                    models.GameMove.gameid == self.game_db_id
                ).order_by(models.GameMove.id.desc()).first()
                if last_move:
                    self.session.delete(last_move)
                    self.session.commit()
            
            # Pop move from board
            self.board.pop()
            paths.write_fen_log(self.board.fen())
            board.beep(board.SOUND_GENERAL)
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            verify_state = bytearray(board.getChessState())
            if not self._validate_board_state(verify_state, self.board_states[-1] if self.board_states else None):
                log.info("[GameManager] Board state incorrect after takeback, entering correction mode")
                self._enter_correction_mode()
            
            # Trigger takeback event
            if self.event_callback:
                self.event_callback(GameEvent.TAKEBACK, {"fen": self.board.fen()})
            
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
        if not self.running:
            return
        
        lift = (piece_event == 0)
        place = (piece_event == 1)
        
        field_name = chess.square_name(field)
        piece_color = self.board.color_at(field)
        
        log.info(f"[GameManager.field_callback] piece_event={'LIFT' if lift else 'PLACE'} "
                f"field={field} fieldname={field_name} "
                f"color_at={'White' if piece_color else 'Black' if piece_color is not None else 'None'}")
        
        # Check if piece color matches current turn
        is_current_player_piece = (self.board.turn == chess.WHITE) == (piece_color == True)
        
        # Handle correction mode
        if self.correction_mode:
            current_state = bytearray(board.getChessState())
            
            # Check if board is in starting position (new game detection)
            if self._is_starting_position(current_state):
                log.info("[GameManager] Starting position detected while in correction mode - triggering new game")
                board.ledsOff()
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                self._reset_game()
                return
            
            # Check if board is now correct
            if self._validate_board_state(current_state, self.correction_expected_state):
                log.info("[GameManager] Board corrected, exiting correction mode")
                board.beep(board.SOUND_GENERAL)
                self._exit_correction_mode()
                return
            
            # Still incorrect, update guidance
            self._provide_correction_guidance(current_state, self.correction_expected_state)
            return
        
        # Normal game flow
        if lift:
            if field not in self.legal_squares and self.source_square is None and is_current_player_piece:
                # Generate legal squares for this piece
                self.legal_squares = self._calculate_legal_squares(field)
                self.source_square = field
            
            # Track opposing side lifts
            if not is_current_player_piece:
                self.opponent_source_square = field
        
        if place:
            # If opponent piece is placed back on original square, reset
            if not is_current_player_piece and self.opponent_source_square is not None:
                if field == self.opponent_source_square:
                    board.ledsOff()
                    self.opponent_source_square = None
                    return
            
            # Handle forced moves
            if self.forced_move_active and self.forced_move:
                from_sq, to_sq = self._uci_to_squares(self.forced_move)
                if lift and is_current_player_piece:
                    if field_name != self.forced_move[0:2]:
                        # Wrong piece lifted for forced move
                        self.legal_squares = [field]
                    else:
                        # Correct piece, limit to target square
                        self.legal_squares = [to_sq] if to_sq is not None else []
            
            # Ignore PLACE events without corresponding LIFT
            if place and self.source_square is None and self.opponent_source_square is None:
                if not self.forced_move_active:
                    log.info(f"[GameManager] Ignoring PLACE event without LIFT for field {field}")
                    return
            
            # Check for illegal placement
            if place and field not in self.legal_squares:
                board.beep(board.SOUND_WRONG_MOVE)
                log.warning(f"[GameManager] Piece placed on illegal square {field}")
                
                # Check for takeback first
                current_state = bytearray(board.getChessState())
                if not self._check_takeback(current_state):
                    # Not a takeback, guide misplaced piece
                    self._enter_correction_mode()
                    self._provide_correction_guidance(
                        current_state,
                        self.board_states[-1] if self.board_states else None
                    )
                return
            
            # Valid move
            if place and field in self.legal_squares:
                if field == self.source_square:
                    # Piece placed back on source square
                    board.ledsOff()
                    self._reset_move_state()
                else:
                    # Piece moved to new square
                    from_name = chess.square_name(self.source_square)
                    to_name = chess.square_name(field)
                    piece_name = str(self.board.piece_at(self.source_square))
                    
                    # Handle promotion
                    promotion_suffix = self._handle_promotion(field, piece_name, self.forced_move_active)
                    
                    # Build move string
                    if self.forced_move_active and self.forced_move:
                        move_str = self.forced_move
                    else:
                        move_str = from_name + to_name + promotion_suffix
                    
                    # Make the move
                    try:
                        move = chess.Move.from_uci(move_str)
                        self.board.push(move)
                        paths.write_fen_log(self.board.fen())
                        
                        # Log move to database
                        if self.session and self.game_db_id:
                            gamemove = models.GameMove(
                                gameid=self.game_db_id,
                                move=move_str,
                                fen=str(self.board.fen())
                            )
                            self.session.add(gamemove)
                            self.session.commit()
                        
                        # Collect board state
                        self.board_states.append(bytearray(board.getChessState()))
                        
                        # Reset move state
                        self._reset_move_state()
                        self.forced_move_active = False
                        self.forced_move = None
                        
                        # Notify move callback
                        if self.move_callback:
                            self.move_callback(move_str)
                        
                        board.beep(board.SOUND_GENERAL)
                        board.led(field)
                        
                        # Check game outcome
                        outcome = self.board.outcome(claim_draw=True)
                        if outcome is None:
                            # Game continues, switch turn
                            if self.board.turn == chess.WHITE:
                                if self.event_callback:
                                    self.event_callback(GameEvent.WHITE_TURN, {"fen": self.board.fen()})
                            else:
                                if self.event_callback:
                                    self.event_callback(GameEvent.BLACK_TURN, {"fen": self.board.fen()})
                        else:
                            # Game over
                            board.beep(board.SOUND_GENERAL)
                            result_str = str(self.board.result())
                            termination = str(outcome.termination)
                            
                            # Update database
                            if self.session and self.game_db_id:
                                game = self.session.query(models.Game).filter(
                                    models.Game.id == self.game_db_id
                                ).first()
                                if game:
                                    game.result = result_str
                                    self.session.commit()
                            
                            # Trigger game over event
                            if self.event_callback:
                                self.event_callback(
                                    GameEvent.GAME_OVER,
                                    {
                                        "result": result_str,
                                        "termination": termination,
                                        "fen": self.board.fen()
                                    }
                                )
                    except ValueError as e:
                        log.error(f"[GameManager] Invalid move: {move_str}, error: {e}")
                        board.beep(board.SOUND_WRONG_MOVE)
                        self._reset_move_state()
    
    def _key_callback(self, key_pressed: int):
        """Handle key press events."""
        if not self.running:
            return
        
        if self.key_callback:
            self.key_callback(key_pressed)
        
        # Handle draw/resign requests via HELP key
        if key_pressed == board.Key.HELP:
            # Menu handling would go here if needed
            pass
    
    def _game_thread(self):
        """Main game thread that subscribes to board events."""
        board.ledsOff()
        log.info("[GameManager] Subscribing to board events")
        
        try:
            board.subscribeEvents(self._key_callback, self._field_callback)
        except Exception as e:
            log.error(f"[GameManager] Error subscribing to events: {e}")
            return
        
        # Monitor for starting position
        try:
            while self.running and not self.kill_flag.is_set():
                current_state = bytearray(board.getChessState())
                
                # Check for starting position (new game)
                if self._is_starting_position(current_state):
                    if len(self.board_states) == 0 or not self._validate_board_state(
                        current_state,
                        self.board_states[0] if self.board_states else None
                    ):
                        log.info("[GameManager] Starting position detected")
                        self._reset_game()
                
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("[GameManager] Keyboard interrupt received in game thread")
        except Exception as e:
            log.error(f"[GameManager] Error in game thread: {e}")
            import traceback
            traceback.print_exc()
    
    def _reset_game(self):
        """Reset game to starting position."""
        try:
            log.info("[GameManager] Resetting game")
            self._reset_move_state()
            self.board.reset()
            paths.write_fen_log(self.board.fen())
            
            # Double beep for game start
            board.beep(board.SOUND_GENERAL)
            time.sleep(0.3)
            board.beep(board.SOUND_GENERAL)
            board.ledsOff()
            
            # Trigger new game event
            if self.event_callback:
                self.event_callback(GameEvent.NEW_GAME, {"fen": self.board.fen()})
                self.event_callback(GameEvent.WHITE_TURN, {"fen": self.board.fen()})
            
            # Log new game in database
            if self.session:
                game = models.Game(
                    source="games/manager",
                    event="",
                    site="",
                    round="",
                    white="",
                    black=""
                )
                self.session.add(game)
                self.session.commit()
                self.game_db_id = self.session.query(func.max(models.Game.id)).scalar()
                
                # Log starting position
                gamemove = models.GameMove(
                    gameid=self.game_db_id,
                    move="",
                    fen=str(self.board.fen())
                )
                self.session.add(gamemove)
                self.session.commit()
            
            self.board_states = []
            self.board_states.append(bytearray(board.getChessState()))
            
        except Exception as e:
            log.error(f"[GameManager] Error resetting game: {e}")
            import traceback
            traceback.print_exc()
    
    def set_computer_move(self, uci_move: str, forced: bool = True):
        """
        Set a computer move that the player is expected to make.
        
        Args:
            uci_move: UCI move string (e.g., "e2e4")
            forced: Whether this is a forced move (default: True)
        """
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return
        
        self.forced_move = uci_move
        self.forced_move_active = forced
        
        # Light up LEDs to indicate the move
        from_sq, to_sq = self._uci_to_squares(uci_move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
            log.info(f"[GameManager] Computer move set: {uci_move}")
    
    def reset_move_state(self):
        """Reset move state (useful for external cleanup)."""
        self._reset_move_state()
        self.forced_move = None
        self.forced_move_active = False
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self.board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self.board.fen()
    
    def start(self):
        """Start the game manager."""
        if self.running:
            return
        
        # Initialize database session
        self.session = sessionmaker(bind=models.engine)()
        
        # Collect initial board state
        self.board_states = []
        self.board_states.append(bytearray(board.getChessState()))
        
        self.running = True
        self.kill_flag.clear()
        
        # Start game thread
        self.game_thread = threading.Thread(target=self._game_thread, daemon=True)
        self.game_thread.start()
        
        log.info("[GameManager] Game manager started")
    
    def stop(self):
        """Stop the game manager."""
        if not self.running:
            return
        
        log.info("[GameManager] Stopping game manager")
        self.running = False
        self.kill_flag.set()
        
        board.ledsOff()
        
        # Clean up database session
        if self.session:
            try:
                self.session.close()
                self.session = None
            except Exception:
                pass
        
        # Wait for thread to finish
        if self.game_thread and self.game_thread.is_alive():
            self.game_thread.join(timeout=2.0)
        
        log.info("[GameManager] Game manager stopped")

