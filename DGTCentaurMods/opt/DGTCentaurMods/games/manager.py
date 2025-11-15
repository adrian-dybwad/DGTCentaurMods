"""
Chess game manager providing complete game state management.

This module provides a clean, event-driven interface for managing chess games
with automatic turn tracking, move validation, and hardware abstraction.

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

from enum import IntEnum
from typing import Optional, Callable, List
import threading
import time
import chess
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log


class GameEvent(IntEnum):
    """Game events that can be emitted by the game manager."""
    NEW_GAME = 1
    WHITE_TURN = 2
    BLACK_TURN = 3
    MOVE_MADE = 4
    GAME_OVER = 5
    DRAW_OFFERED = 6
    RESIGNATION = 7
    TAKEBACK = 8


class GameManager:
    """
    Manages chess game state with automatic turn tracking and event-driven notifications.
    
    Provides hardware abstraction and handles move validation, promotion, and game outcomes.
    """
    
    STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    STARTING_STATE = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
                               b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                               b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                               b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                               b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')
    
    BOARD_SIZE = 64
    BOARD_WIDTH = 8
    PROMOTION_ROW_WHITE = 7
    PROMOTION_ROW_BLACK = 0
    
    def __init__(self):
        """Initialize the game manager with a fresh chess board."""
        self._board = chess.Board()
        self._event_callbacks: List[Callable[[GameEvent, dict], None]] = []
        self._move_callbacks: List[Callable[[str], None]] = []
        self._key_callbacks: List[Callable[[board.Key], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Move tracking state
        self._source_square: Optional[int] = None
        self._legal_squares: List[int] = []
        self._board_states: List[bytearray] = []
        
        # Forced move (computer move) state
        self._forced_move: Optional[str] = None
        
        # Game metadata
        self._game_id: Optional[int] = None
        
    def subscribe(self, 
                  event_callback: Optional[Callable[[GameEvent, dict], None]] = None,
                  move_callback: Optional[Callable[[str], None]] = None,
                  key_callback: Optional[Callable[[board.Key], None]] = None):
        """
        Subscribe to game events, moves, and key presses.
        
        Args:
            event_callback: Called with (GameEvent, event_data) when game events occur
            move_callback: Called with move string (UCI format) when moves are made
            key_callback: Called with Key enum when keys are pressed
        """
        if event_callback:
            self._event_callbacks.append(event_callback)
        if move_callback:
            self._move_callbacks.append(move_callback)
        if key_callback:
            self._key_callbacks.append(key_callback)
        
        if not self._running:
            self._start()
    
    def unsubscribe(self):
        """Stop the game manager and unsubscribe from hardware events."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        board.ledsOff()
        self._event_callbacks.clear()
        self._move_callbacks.clear()
        self._key_callbacks.clear()
    
    def _start(self):
        """Start the game manager thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._game_thread, daemon=True)
        self._thread.start()
        
        # Check for starting position
        self._check_starting_position()
    
    def _game_thread(self):
        """Main game thread that subscribes to hardware events."""
        log.info("[GameManager] Starting game thread")
        try:
            board.subscribeEvents(self._key_callback, self._field_callback)
        except Exception as e:
            log.error(f"[GameManager] Error subscribing to events: {e}")
            self._running = False
            return
        
        while self._running:
            time.sleep(0.1)
    
    def _key_callback(self, key_pressed: board.Key):
        """Handle key press events from the board."""
        log.info(f"[GameManager] Key pressed: {key_pressed}")
        for callback in self._key_callbacks:
            try:
                callback(key_pressed)
            except Exception as e:
                log.error(f"[GameManager] Error in key callback: {e}")
    
    def _field_callback(self, piece_event: int, field: int, time_in_seconds: float):
        """
        Handle piece lift/place events from the board.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0=a1 to 63=h8)
            time_in_seconds: Timestamp of the event
        """
        # Check for starting position on any piece event
        self._check_starting_position()
        
        is_lift = (piece_event == 0)
        is_place = (piece_event == 1)
        
        field_name = chess.square_name(field)
        piece_color = self._board.color_at(field)
        is_current_player_piece = (self._board.turn == chess.WHITE) == (piece_color == True)
        
        log.info(f"[GameManager] Piece event: {'LIFT' if is_lift else 'PLACE'} "
                f"field={field} ({field_name}) "
                f"piece={'White' if piece_color else 'Black' if piece_color is not None else 'None'} "
                f"current_turn={'White' if self._board.turn else 'Black'}")
        
        if is_lift:
            self._handle_piece_lift(field, is_current_player_piece)
        elif is_place:
            self._handle_piece_place(field, is_current_player_piece)
    
    def _handle_piece_lift(self, field: int, is_current_player_piece: bool):
        """Handle piece lift event."""
        if not is_current_player_piece:
            # Opponent piece lifted - ignore for now
            return
        
        if self._source_square is None:
            # Starting a new move
            self._source_square = field
            self._legal_squares = self._calculate_legal_squares(field)
            log.info(f"[GameManager] Piece lifted from {chess.square_name(field)}, "
                    f"legal squares: {[chess.square_name(sq) for sq in self._legal_squares]}")
        elif self._forced_move:
            # Check if this is the forced move source
            forced_source = chess.parse_square(self._forced_move[0:2])
            if field == forced_source:
                # Correct piece for forced move
                forced_target = chess.parse_square(self._forced_move[2:4])
                self._legal_squares = [forced_target]
                self._source_square = field
            else:
                # Wrong piece - can only put it back
                self._legal_squares = [field]
                self._source_square = field
    
    def _handle_piece_place(self, field: int, is_current_player_piece: bool):
        """Handle piece place event."""
        if self._source_square is None:
            # No corresponding lift - ignore stale events
            return
        
        if field not in self._legal_squares:
            # Illegal move
            board.beep(board.SOUND_WRONG_MOVE)
            log.warning(f"[GameManager] Illegal move attempted: "
                       f"{chess.square_name(self._source_square)} -> {chess.square_name(field)}")
            
            # Check for takeback
            if self._check_takeback():
                return
            
            # Reset move state
            self._reset_move_state()
            return
        
        if field == self._source_square:
            # Piece placed back - cancel move
            self._reset_move_state()
            board.ledsOff()
            return
        
        # Valid move - execute it
        self._execute_move(field)
    
    def _execute_move(self, target_square: int):
        """Execute a valid move."""
        from_name = chess.square_name(self._source_square)
        to_name = chess.square_name(target_square)
        
        # Check for promotion
        piece = self._board.piece_at(self._source_square)
        promotion_suffix = ""
        if piece:
            piece_symbol = piece.symbol()
            is_white_promotion = (target_square // self.BOARD_WIDTH == self.PROMOTION_ROW_WHITE 
                                 and piece_symbol == "P")
            is_black_promotion = (target_square // self.BOARD_WIDTH == self.PROMOTION_ROW_BLACK 
                                 and piece_symbol == "p")
            
            if is_white_promotion or is_black_promotion:
                promotion_suffix = self._get_promotion_choice()
        
        # Build move string
        if self._forced_move:
            move_str = self._forced_move
        else:
            move_str = from_name + to_name + promotion_suffix
        
        # Validate and execute move
        try:
            move = chess.Move.from_uci(move_str)
            if move not in self._board.legal_moves:
                log.error(f"[GameManager] Move {move_str} is not legal!")
                board.beep(board.SOUND_WRONG_MOVE)
                self._reset_move_state()
                return
            
            self._board.push(move)
            log.info(f"[GameManager] Move executed: {move_str}")
            
            # Store board state for takeback detection
            current_state = bytearray(board.getChessState())
            self._board_states.append(current_state)
            
            # Notify callbacks
            for callback in self._move_callbacks:
                try:
                    callback(move_str)
                except Exception as e:
                    log.error(f"[GameManager] Error in move callback: {e}")
            
            board.beep(board.SOUND_GENERAL)
            board.led(target_square)
            
            # Check game outcome
            outcome = self._board.outcome(claim_draw=True)
            if outcome:
                self._handle_game_over(outcome)
            else:
                # Switch turn
                self._notify_turn_change()
            
            self._reset_move_state()
            
        except Exception as e:
            log.error(f"[GameManager] Error executing move: {e}")
            board.beep(board.SOUND_WRONG_MOVE)
            self._reset_move_state()
    
    def _get_promotion_choice(self) -> str:
        """
        Get promotion piece choice from user via button press.
        
        Returns:
            Promotion suffix: "q", "r", "b", or "n"
        """
        board.beep(board.SOUND_GENERAL)
        
        # Wait for user to select promotion piece via button press
        # BACK = Knight, TICK = Bishop, UP = Queen, DOWN = Rook
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
        Calculate legal destination squares for a piece.
        
        Args:
            source_square: Source square index
            
        Returns:
            List of legal destination square indices, including source square
        """
        legal_squares = [source_square]
        for move in self._board.legal_moves:
            if move.from_square == source_square:
                legal_squares.append(move.to_square)
        return legal_squares
    
    def _check_takeback(self) -> bool:
        """
        Check if the current board state matches a previous state (takeback).
        
        Returns:
            True if takeback detected, False otherwise
        """
        if len(self._board_states) < 2:
            return False
        
        current_state = bytearray(board.getChessState())
        previous_state = self._board_states[-2]
        
        if current_state == previous_state:
            log.info("[GameManager] Takeback detected")
            self._board_states.pop()
            self._board.pop()
            board.beep(board.SOUND_GENERAL)
            board.ledsOff()
            
            # Notify takeback
            self._emit_event(GameEvent.TAKEBACK, {})
            
            # Switch turn back
            self._notify_turn_change()
            
            self._reset_move_state()
            return True
        
        return False
    
    def _check_starting_position(self):
        """Check if board is in starting position and start new game if so."""
        current_state = board.getChessState()
        if not current_state:
            return
        
        is_starting_position = bytearray(current_state) == self.STARTING_STATE
        
        # Start new game if:
        # 1. No game has started yet (no board states recorded)
        # 2. Game is in progress and pieces are moved back to starting position
        if is_starting_position:
            if len(self._board_states) == 0:
                # Initial starting position - start first game
                log.info("[GameManager] Starting position detected - starting first game")
                self._start_new_game()
            elif len(self._board.move_stack) > 0:
                # Pieces moved back to starting position during game - start new game
                log.info("[GameManager] Starting position detected - starting new game")
                self._start_new_game()
    
    def _start_new_game(self):
        """Start a new game."""
        log.info("[GameManager] Starting new game")
        self._board.reset()
        self._board_states.clear()
        self._reset_move_state()
        board.ledsOff()
        board.beep(board.SOUND_GENERAL)
        time.sleep(0.3)
        board.beep(board.SOUND_GENERAL)
        
        # Store initial board state
        current_state = bytearray(board.getChessState())
        self._board_states.append(current_state)
        
        # Emit events
        self._emit_event(GameEvent.NEW_GAME, {"fen": self._board.fen()})
        self._notify_turn_change()
    
    def _notify_turn_change(self):
        """Notify that the turn has changed."""
        if self._board.turn == chess.WHITE:
            self._emit_event(GameEvent.WHITE_TURN, {"fen": self._board.fen()})
        else:
            self._emit_event(GameEvent.BLACK_TURN, {"fen": self._board.fen()})
    
    def _handle_game_over(self, outcome: chess.Outcome):
        """Handle game over condition."""
        result = str(self._board.result())
        termination = str(outcome.termination)
        
        log.info(f"[GameManager] Game over: {result} ({termination})")
        
        self._emit_event(GameEvent.GAME_OVER, {
            "result": result,
            "termination": termination,
            "fen": self._board.fen()
        })
    
    def _emit_event(self, event: GameEvent, data: dict):
        """Emit an event to all registered callbacks."""
        for callback in self._event_callbacks:
            try:
                callback(event, data)
            except Exception as e:
                log.error(f"[GameManager] Error in event callback: {e}")
    
    def _reset_move_state(self):
        """Reset move tracking state."""
        self._source_square = None
        self._legal_squares = []
        self._forced_move = None
    
    def set_forced_move(self, move: str):
        """
        Set a forced move (computer move) that the player must make.
        
        Args:
            move: UCI move string (e.g., "e2e4")
        """
        if len(move) < 4:
            log.warning(f"[GameManager] Invalid forced move: {move}")
            return
        
        self._forced_move = move
        from_square = chess.parse_square(move[0:2])
        to_square = chess.parse_square(move[2:4])
        board.ledFromTo(from_square, to_square)
        log.info(f"[GameManager] Forced move set: {move}")
    
    def clear_forced_move(self):
        """Clear any forced move."""
        self._forced_move = None
        board.ledsOff()
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        return self._board
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        return self._board.fen()
    
    def resign(self, side: chess.Color):
        """
        Resign the game.
        
        Args:
            side: chess.WHITE or chess.BLACK
        """
        result = "0-1" if side == chess.WHITE else "1-0"
        self._emit_event(GameEvent.RESIGNATION, {"result": result, "side": side})
    
    def offer_draw(self):
        """Offer a draw."""
        self._emit_event(GameEvent.DRAW_OFFERED, {})

