# Chess Game Manager
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
Chess game manager providing complete game state management, automatic turn tracking,
event-driven notifications, and hardware abstraction.

This module manages the chess game state independently of UI and engine logic.
It uses board.py for hardware abstraction and provides callbacks for game events.
"""

import chess
import threading
import time
from typing import Optional, Callable, List, Tuple
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log

# Event constants
EVENT_NEW_GAME = 1
EVENT_WHITE_TURN = 2
EVENT_BLACK_TURN = 3
EVENT_GAME_OVER = 4
EVENT_MOVE_MADE = 5
EVENT_ILLEGAL_MOVE = 6
EVENT_PROMOTION_NEEDED = 7

# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class GameManager:
    """
    Manages chess game state, turn tracking, and hardware interaction.
    
    Provides event-driven notifications for game events and abstracts
    hardware operations through board.py.
    """
    
    def __init__(self):
        """Initialize the game manager with a fresh chess board."""
        self._board = chess.Board()
        self._kill = False
        self._event_callback: Optional[Callable[[int], None]] = None
        self._move_callback: Optional[Callable[[str], None]] = None
        self._key_callback: Optional[Callable[[int], None]] = None
        
        # Move tracking state
        self._source_square: Optional[int] = None
        self._legal_squares: List[int] = []
        self._forced_move: Optional[str] = None
        self._forced_move_active = False
        
        # Thread management
        self._game_thread: Optional[threading.Thread] = None
        
    def subscribe(
        self,
        event_callback: Optional[Callable[[int], None]] = None,
        move_callback: Optional[Callable[[str], None]] = None,
        key_callback: Optional[Callable[[int], None]] = None
    ):
        """
        Subscribe to game events.
        
        Args:
            event_callback: Called with event constants (EVENT_NEW_GAME, etc.)
            move_callback: Called with UCI move string when a move is made
            key_callback: Called with key press events from board
        """
        self._event_callback = event_callback
        self._move_callback = move_callback
        self._key_callback = key_callback
        
        self._kill = False
        self._game_thread = threading.Thread(target=self._game_thread_func, daemon=True)
        self._game_thread.start()
        
    def unsubscribe(self):
        """Stop the game manager and unsubscribe from events."""
        self._kill = True
        board.ledsOff()
        if self._game_thread is not None:
            self._game_thread.join(timeout=2.0)
            
    def get_board(self) -> chess.Board:
        """
        Get the current chess board state.
        
        Returns:
            The current chess.Board instance
        """
        return self._board
        
    def get_fen(self) -> str:
        """
        Get current board position as FEN string.
        
        Returns:
            FEN string representation of current position
        """
        return self._board.fen()
        
    def reset(self):
        """Reset the board to starting position and trigger NEW_GAME event."""
        self._board.reset()
        self._reset_move_state()
        board.ledsOff()
        self._trigger_event(EVENT_NEW_GAME)
        self._trigger_turn_event()
        
    def set_forced_move(self, uci_move: str):
        """
        Set a forced move that the player must make.
        
        Args:
            uci_move: UCI move string (e.g., "e2e4")
        """
        if len(uci_move) < 4:
            return
            
        self._forced_move = uci_move
        self._forced_move_active = True
        
        # Convert UCI to square indices and light LEDs
        from_sq, to_sq = self._uci_to_squares(uci_move)
        if from_sq is not None and to_sq is not None:
            board.ledFromTo(from_sq, to_sq)
            
    def clear_forced_move(self):
        """Clear any active forced move."""
        self._forced_move = None
        self._forced_move_active = False
        
    def _uci_to_squares(self, uci_move: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Convert UCI move string to square indices.
        
        Args:
            uci_move: UCI move string (e.g., "e2e4")
            
        Returns:
            Tuple of (from_square, to_square) as integers (0-63)
        """
        if len(uci_move) < 4:
            return None, None
            
        try:
            from_sq = chess.parse_square(uci_move[0:2])
            to_sq = chess.parse_square(uci_move[2:4])
            return from_sq, to_sq
        except ValueError:
            return None, None
            
    def _reset_move_state(self):
        """Reset move-related state variables."""
        self._source_square = None
        self._legal_squares = []
        self._forced_move = None
        self._forced_move_active = False
        
    def _trigger_event(self, event: int):
        """Trigger an event callback if registered."""
        if self._event_callback is not None:
            try:
                self._event_callback(event)
            except Exception as e:
                log.error(f"Error in event callback: {e}")
                
    def _trigger_move(self, move: str):
        """Trigger a move callback if registered."""
        if self._move_callback is not None:
            try:
                self._move_callback(move)
            except Exception as e:
                log.error(f"Error in move callback: {e}")
                
    def _trigger_turn_event(self):
        """Trigger appropriate turn event based on current turn."""
        if self._board.turn == chess.WHITE:
            self._trigger_event(EVENT_WHITE_TURN)
        else:
            self._trigger_event(EVENT_BLACK_TURN)
            
    def _calculate_legal_squares(self, square: int) -> List[int]:
        """
        Calculate legal destination squares for a piece at the given square.
        
        Args:
            square: Source square index (0-63)
            
        Returns:
            List of legal destination square indices, including the source square
        """
        legal_squares = [square]  # Include source square
        
        for move in self._board.legal_moves:
            if move.from_square == square:
                legal_squares.append(move.to_square)
                
        return legal_squares
        
    def _handle_promotion(self, to_square: int, piece_symbol: str) -> str:
        """
        Check if promotion is needed and return promotion suffix.
        
        Args:
            to_square: Target square index
            piece_symbol: Piece symbol ("P" for white, "p" for black)
            
        Returns:
            Promotion piece suffix ("q", "r", "b", "n") or empty string
        """
        is_white_promotion = (to_square // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_symbol == "P"
        is_black_promotion = (to_square // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_symbol == "p"
        
        if is_white_promotion or is_black_promotion:
            self._trigger_event(EVENT_PROMOTION_NEEDED)
            # Default to queen if no explicit choice provided
            return "q"
        return ""
        
    def _key_callback_wrapper(self, key_pressed):
        """Wrapper for key callback that handles board key events."""
        if self._key_callback is not None:
            try:
                self._key_callback(key_pressed)
            except Exception as e:
                log.error(f"Error in key callback: {e}")
                
    def _field_callback_wrapper(self, piece_event: int, field: int, time_in_seconds: float):
        """
        Handle piece lift/place events from the board.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0=a1, 63=h8)
            time_in_seconds: Time of the event
        """
        lift = (piece_event == 0)
        place = (piece_event == 1)
        
        field_name = chess.square_name(field)
        piece_color = self._board.color_at(field)
        
        log.info(f"[GameManager] piece_event={'LIFT' if lift else 'PLACE'} field={field} ({field_name})")
        
        # Check if piece belongs to current player
        is_current_player_piece = (self._board.turn == chess.WHITE) == (piece_color == True)
        
        # Handle piece lift
        if lift:
            if is_current_player_piece:
                if self._source_square is None:
                    # Start of a new move
                    self._legal_squares = self._calculate_legal_squares(field)
                    self._source_square = field
                    
                    # Handle forced move restrictions
                    if self._forced_move_active and self._forced_move:
                        forced_from, forced_to = self._uci_to_squares(self._forced_move)
                        if forced_from is not None and field == forced_from:
                            # Correct piece lifted for forced move, limit legal squares
                            self._legal_squares = [forced_to] if forced_to is not None else []
                        else:
                            # Wrong piece lifted for forced move
                            self._legal_squares = [field]  # Can only put it back
                            
                    # Light up legal destination squares
                    board.ledsOff()
                    for sq in self._legal_squares:
                        if sq != field:  # Don't light source square
                            board.led(sq)
            else:
                # Opponent piece lifted - ignore or handle as needed
                pass
                
        # Handle piece place
        if place:
            if self._source_square is None:
                # Place without lift - ignore stale events
                log.debug(f"[GameManager] Ignoring place event without lift at {field}")
                return
                
            if field not in self._legal_squares:
                # Illegal move
                board.beep(board.SOUND_WRONG_MOVE)
                self._trigger_event(EVENT_ILLEGAL_MOVE)
                log.warning(f"[GameManager] Illegal move attempted: {chess.square_name(self._source_square)} to {field_name}")
                return
                
            if field == self._source_square:
                # Piece placed back on source square - cancel move
                board.ledsOff()
                self._reset_move_state()
                return
                
            # Valid move - construct UCI move string
            from_name = chess.square_name(self._source_square)
            to_name = chess.square_name(field)
            piece_symbol = str(self._board.piece_at(self._source_square))
            
            # Handle promotion
            promotion_suffix = self._handle_promotion(field, piece_symbol)
            
            # Use forced move if active, otherwise construct from piece movement
            if self._forced_move_active and self._forced_move:
                uci_move = self._forced_move
            else:
                uci_move = from_name + to_name + promotion_suffix
                
            # Make the move
            try:
                move = chess.Move.from_uci(uci_move)
                if move not in self._board.legal_moves:
                    board.beep(board.SOUND_WRONG_MOVE)
                    self._trigger_event(EVENT_ILLEGAL_MOVE)
                    log.warning(f"[GameManager] Move {uci_move} is not legal")
                    return
                    
                self._board.push(move)
                board.beep(board.SOUND_GENERAL)
                board.led(field)  # Light destination square
                
                # Clear forced move if it was used
                if self._forced_move_active:
                    self._forced_move_active = False
                    self._forced_move = None
                    
                # Reset move state
                self._reset_move_state()
                
                # Trigger move callback
                self._trigger_move(uci_move)
                
                # Check game outcome
                outcome = self._board.outcome(claim_draw=True)
                if outcome is not None:
                    self._trigger_event(EVENT_GAME_OVER)
                else:
                    # Switch turn
                    self._trigger_turn_event()
                    
            except ValueError as e:
                log.error(f"[GameManager] Invalid move format: {uci_move}, error: {e}")
                board.beep(board.SOUND_WRONG_MOVE)
                self._trigger_event(EVENT_ILLEGAL_MOVE)
                
    def _game_thread_func(self):
        """Main game thread that subscribes to board events."""
        log.info("[GameManager] Starting game thread")
        board.ledsOff()
        
        try:
            board.subscribeEvents(
                keycallback=self._key_callback_wrapper,
                fieldcallback=self._field_callback_wrapper
            )
        except Exception as e:
            log.error(f"[GameManager] Error subscribing to board events: {e}")
            return
            
        # Keep thread alive
        while not self._kill:
            time.sleep(0.1)
            
        log.info("[GameManager] Game thread exiting")

