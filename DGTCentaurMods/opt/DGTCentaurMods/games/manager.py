"""
Chess Game Manager

Provides complete chess game state management with automatic turn tracking,
event-driven notifications, and hardware abstraction.

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
from typing import Optional, Callable, Dict, Any
from enum import IntEnum
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.db import models
from sqlalchemy.orm import sessionmaker
from DGTCentaurMods.config import paths


class GameEvent(IntEnum):
    """Game event types"""
    NEW_GAME = 1
    WHITE_TURN = 2
    BLACK_TURN = 3
    REQUEST_DRAW = 4
    RESIGN_GAME = 5
    GAME_OVER = 6


class GameManager:
    """
    Manages chess game state with automatic turn tracking and event-driven notifications.
    
    Provides hardware abstraction through board.py and maintains complete game state
    including move history, board state validation, and game outcome detection.
    """
    
    BOARD_SIZE = 64
    BOARD_WIDTH = 8
    PROMOTION_ROW_WHITE = 7
    PROMOTION_ROW_BLACK = 0
    STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    STARTING_STATE = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
                               b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                               b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                               b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                               b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')
    
    def __init__(self):
        """Initialize the game manager with clean state."""
        self._lock = threading.Lock()
        self._chess_board = chess.Board()
        self._board_states = []
        self._game_id: Optional[int] = None
        self._session: Optional[Any] = None
        self._running = False
        self._kill_flag = False
        
        # Move state
        self._source_square: Optional[int] = None
        self._legal_squares: list[int] = []
        self._forced_move: Optional[str] = None
        self._is_forced_move = False
        
        # Callbacks
        self._event_callback: Optional[Callable[[GameEvent], None]] = None
        self._move_callback: Optional[Callable[[str], None]] = None
        self._key_callback: Optional[Callable[[Any], None]] = None
        self._takeback_callback: Optional[Callable[[], None]] = None
        
        # Game metadata
        self._game_info: Dict[str, str] = {
            'event': '',
            'site': '',
            'round': '',
            'white': '',
            'black': ''
        }
    
    def subscribe(self, 
                  event_callback: Callable[[GameEvent], None],
                  move_callback: Callable[[str], None],
                  key_callback: Callable[[Any], None],
                  takeback_callback: Optional[Callable[[], None]] = None) -> None:
        """
        Subscribe to game events.
        
        Args:
            event_callback: Called with GameEvent when game events occur
            move_callback: Called with UCI move string when a move is made
            key_callback: Called with key press events (passed through from board)
            takeback_callback: Called when a takeback is detected
        """
        with self._lock:
            self._event_callback = event_callback
            self._move_callback = move_callback
            self._key_callback = key_callback
            self._takeback_callback = takeback_callback
            
            # Initialize database session
            Session = sessionmaker(bind=models.engine)
            self._session = Session()
            
            # Collect initial board state
            self._collect_board_state()
            
            # Start event thread
            self._running = True
            self._kill_flag = False
            thread = threading.Thread(target=self._event_thread, daemon=True)
            thread.start()
    
    def unsubscribe(self) -> None:
        """Stop the game manager and clean up resources."""
        with self._lock:
            self._kill_flag = True
            self._running = False
            
            if self._session:
                try:
                    self._session.close()
                except Exception:
                    pass
                self._session = None
            
            board.ledsOff()
    
    def set_game_info(self, event: str = '', site: str = '', round: str = '',
                     white: str = '', black: str = '') -> None:
        """Set game metadata for database logging."""
        with self._lock:
            self._game_info = {
                'event': event,
                'site': site,
                'round': round,
                'white': white,
                'black': black
            }
    
    def set_forced_move(self, move: str) -> None:
        """
        Set a forced move that the player must make.
        
        Args:
            move: UCI move string (e.g., "e2e4")
        """
        with self._lock:
            if len(move) < 4:
                return
            
            self._forced_move = move
            self._is_forced_move = True
            
            # Light up LEDs to indicate the move
            from_sq, to_sq = self._uci_to_squares(move)
            if from_sq is not None and to_sq is not None:
                board.ledFromTo(from_sq, to_sq)
    
    def clear_forced_move(self) -> None:
        """Clear any pending forced move."""
        with self._lock:
            self._forced_move = None
            self._is_forced_move = False
            board.ledsOff()
    
    def get_board(self) -> chess.Board:
        """Get the current chess board state."""
        with self._lock:
            return self._chess_board.copy()
    
    def get_fen(self) -> str:
        """Get current board position as FEN string."""
        with self._lock:
            return self._chess_board.fen()
    
    def reset_game(self) -> None:
        """Reset the game to starting position."""
        with self._lock:
            self._chess_board.reset()
            paths.write_fen_log(self._chess_board.fen())
            self._board_states = []
            self._collect_board_state()
            self._reset_move_state()
            
            # Create new game in database
            game = models.Game(
                source=self._get_source(),
                event=self._game_info['event'],
                site=self._game_info['site'],
                round=self._game_info['round'],
                white=self._game_info['white'],
                black=self._game_info['black']
            )
            self._session.add(game)
            self._session.flush()
            self._session.commit()
            self._game_id = game.id
            
            # Log starting position
            gamemove = models.GameMove(
                gameid=self._game_id,
                move='',
                fen=str(self._chess_board.fen())
            )
            self._session.add(gamemove)
            self._session.commit()
            
            board.beep(board.SOUND_GENERAL)
            time.sleep(0.3)
            board.beep(board.SOUND_GENERAL)
            board.ledsOff()
            
            if self._event_callback:
                self._event_callback(GameEvent.NEW_GAME)
                self._event_callback(GameEvent.WHITE_TURN)
    
    def resign(self, side: int) -> None:
        """
        Resign the game.
        
        Args:
            side: 1 for white, 2 for black
        """
        with self._lock:
            result = "0-1" if side == 1 else "1-0"
            self._update_game_result(result, "Termination.RESIGN")
    
    def draw(self) -> None:
        """Offer/accept a draw."""
        with self._lock:
            self._update_game_result("1/2-1/2", "Termination.DRAW")
    
    def get_result(self) -> str:
        """Get the result of the current game."""
        with self._lock:
            if self._game_id is None:
                return "Unknown"
            
            game = self._session.query(models.Game).filter(
                models.Game.id == self._game_id
            ).first()
            
            if game and game.result:
                return game.result
            return "Unknown"
    
    def _event_thread(self) -> None:
        """Main event thread that subscribes to board events."""
        board.ledsOff()
        log.info("[GameManager] Subscribing to board events")
        
        try:
            board.subscribeEvents(self._key_callback_wrapper, self._field_callback_wrapper)
        except Exception as e:
            log.error(f"[GameManager] Error subscribing to events: {e}")
            return
        
        while not self._kill_flag:
            time.sleep(0.1)
    
    def _key_callback_wrapper(self, key_pressed: Any) -> None:
        """Wrapper for key callback that handles game-specific keys."""
        if self._key_callback:
            self._key_callback(key_pressed)
    
    def _field_callback_wrapper(self, piece_event: int, field: int, time_in_seconds: float) -> None:
        """
        Handle piece lift/place events from the board.
        
        Args:
            piece_event: 0 for lift, 1 for place
            field: Square index (0-63, a1=0, h8=63)
            time_in_seconds: Timestamp of the event
        """
        with self._lock:
            if not self._running:
                return
            
            # Check if game is over
            if self._chess_board.outcome(claim_draw=True) is not None:
                return
            
            is_lift = (piece_event == 0)
            is_place = (piece_event == 1)
            
            if is_lift:
                self._handle_piece_lift(field)
            elif is_place:
                self._handle_piece_place(field)
    
    def _handle_piece_lift(self, field: int) -> None:
        """Handle piece lift event."""
        piece_color = self._chess_board.color_at(field)
        current_turn = self._chess_board.turn
        
        # Check if piece belongs to current player
        if piece_color != current_turn:
            return
        
        # Handle forced move
        if self._is_forced_move and self._forced_move:
            expected_source = chess.parse_square(chess.square_name(field))
            forced_source = chess.parse_square(self._forced_move[0:2])
            
            if expected_source != forced_source:
                # Wrong piece lifted for forced move
                self._legal_squares = [field]
                self._source_square = field
                return
        
        # Calculate legal moves for this piece
        self._legal_squares = self._calculate_legal_squares(field)
        self._source_square = field
    
    def _handle_piece_place(self, field: int) -> None:
        """Handle piece place event."""
        if self._source_square is None:
            # No corresponding lift - ignore stale place events
            return
        
        if field not in self._legal_squares:
            # Illegal move
            board.beep(board.SOUND_WRONG_MOVE)
            log.warning(f"[GameManager] Illegal move attempted: {field}")
            
            # Check for takeback
            if self._check_takeback():
                return
            
            return
        
        if field == self._source_square:
            # Piece placed back - cancel move
            self._reset_move_state()
            return
        
        # Valid move
        self._execute_move(field)
    
    def _execute_move(self, to_field: int) -> None:
        """Execute a move from source square to destination."""
        from_name = chess.square_name(self._source_square)
        to_name = chess.square_name(to_field)
        
        # Check for promotion
        piece = self._chess_board.piece_at(self._source_square)
        promotion_suffix = self._handle_promotion(to_field, piece)
        
        # Build move string
        if self._is_forced_move and self._forced_move:
            move_str = self._forced_move
        else:
            move_str = from_name + to_name + promotion_suffix
        
        # Validate and execute move
        try:
            move = chess.Move.from_uci(move_str)
            if move not in self._chess_board.legal_moves:
                board.beep(board.SOUND_WRONG_MOVE)
                log.warning(f"[GameManager] Move not legal: {move_str}")
                return
            
            self._chess_board.push(move)
            paths.write_fen_log(self._chess_board.fen())
            
            # Log to database
            if self._game_id:
                gamemove = models.GameMove(
                    gameid=self._game_id,
                    move=move_str,
                    fen=str(self._chess_board.fen())
                )
                self._session.add(gamemove)
                self._session.commit()
            
            self._collect_board_state()
            self._reset_move_state()
            
            # Notify callback
            if self._move_callback:
                self._move_callback(move_str)
            
            board.beep(board.SOUND_GENERAL)
            board.led(to_field)
            
            # Check game outcome
            outcome = self._chess_board.outcome(claim_draw=True)
            if outcome is not None:
                result_str = str(self._chess_board.result())
                termination = str(outcome.termination)
                self._update_game_result(result_str, termination)
            else:
                # Switch turn
                if self._chess_board.turn == chess.WHITE:
                    if self._event_callback:
                        self._event_callback(GameEvent.WHITE_TURN)
                else:
                    if self._event_callback:
                        self._event_callback(GameEvent.BLACK_TURN)
        
        except ValueError as e:
            log.error(f"[GameManager] Invalid move {move_str}: {e}")
            board.beep(board.SOUND_WRONG_MOVE)
    
    def _handle_promotion(self, field: int, piece: Optional[chess.Piece]) -> str:
        """
        Handle pawn promotion.
        
        Args:
            field: Destination square
            piece: Piece being moved
            
        Returns:
            Promotion suffix ("q", "r", "b", "n") or empty string
        """
        if piece is None:
            return ""
        
        piece_name = piece.symbol()
        row = field // self.BOARD_WIDTH
        
        is_white_promotion = (row == self.PROMOTION_ROW_WHITE and piece_name == "P")
        is_black_promotion = (row == self.PROMOTION_ROW_BLACK and piece_name == "p")
        
        if not (is_white_promotion or is_black_promotion):
            return ""
        
        # For forced moves, use the promotion from the move string
        if self._is_forced_move and self._forced_move and len(self._forced_move) > 4:
            return self._forced_move[4]
        
        # Otherwise, default to queen (could be enhanced with UI prompt)
        board.beep(board.SOUND_GENERAL)
        return "q"
    
    def _calculate_legal_squares(self, field: int) -> list[int]:
        """Calculate legal destination squares for a piece."""
        legal_squares = [field]  # Include source square
        
        for move in self._chess_board.legal_moves:
            if move.from_square == field:
                legal_squares.append(move.to_square)
        
        return legal_squares
    
    def _check_takeback(self) -> bool:
        """Check if a takeback is being performed."""
        if self._takeback_callback is None or len(self._board_states) < 2:
            return False
        
        current_state = board.getChessState()
        previous_state = self._board_states[-2]
        
        if self._validate_board_state(current_state, previous_state):
            # Takeback detected
            board.ledsOff()
            self._board_states.pop()
            
            # Remove last move from database
            if self._game_id:
                last_move = self._session.query(models.GameMove).filter(
                    models.GameMove.gameid == self._game_id
                ).order_by(models.GameMove.id.desc()).first()
                
                if last_move:
                    self._session.delete(last_move)
                    self._session.commit()
            
            # Pop move from board
            self._chess_board.pop()
            paths.write_fen_log(self._chess_board.fen())
            
            board.beep(board.SOUND_GENERAL)
            
            if self._takeback_callback:
                self._takeback_callback()
            
            return True
        
        return False
    
    def _validate_board_state(self, current: bytearray, expected: bytearray) -> bool:
        """Validate that board state matches expected state."""
        if current is None or expected is None:
            return False
        
        if len(current) != self.BOARD_SIZE or len(expected) != self.BOARD_SIZE:
            return False
        
        return bytearray(current) == bytearray(expected)
    
    def _collect_board_state(self) -> None:
        """Collect and store current board state."""
        state = board.getChessState()
        if state:
            self._board_states.append(bytearray(state))
    
    def _reset_move_state(self) -> None:
        """Reset move-related state variables."""
        self._source_square = None
        self._legal_squares = []
        self._forced_move = None
        self._is_forced_move = False
        board.ledsOff()
    
    def _uci_to_squares(self, uci_move: str) -> tuple[Optional[int], Optional[int]]:
        """Convert UCI move string to square indices."""
        if len(uci_move) < 4:
            return None, None
        
        try:
            from_sq = chess.parse_square(uci_move[0:2])
            to_sq = chess.parse_square(uci_move[2:4])
            return from_sq, to_sq
        except ValueError:
            return None, None
    
    def _update_game_result(self, result: str, termination: str) -> None:
        """Update game result in database and trigger event."""
        if self._game_id:
            game = self._session.query(models.Game).filter(
                models.Game.id == self._game_id
            ).first()
            
            if game:
                game.result = result
                self._session.flush()
                self._session.commit()
        
        if self._event_callback:
            self._event_callback(GameEvent.GAME_OVER)
    
    def _get_source(self) -> str:
        """Get source identifier for database logging."""
        import inspect
        import sys
        frame = sys._getframe(2)
        source_file = inspect.getsourcefile(frame)
        if source_file:
            return source_file
        return "unknown"

