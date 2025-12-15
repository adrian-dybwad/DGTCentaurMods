# Lichess Player
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# A player that connects to Lichess for online games. Moves come from
# the Lichess server (either from a remote human opponent or Lichess AI).
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Callable

import chess

from DGTCentaurMods.board import board, centaur
from DGTCentaurMods.board.logging import log
from .base import Player, PlayerConfig, PlayerState, PlayerType


class LichessGameMode(Enum):
    """Lichess game modes."""
    NEW = auto()        # Seek a new game with specified parameters
    ONGOING = auto()    # Resume an ongoing game by ID
    CHALLENGE = auto()  # Accept or wait for a challenge


@dataclass
class LichessPlayerConfig(PlayerConfig):
    """Configuration for Lichess player.
    
    Attributes:
        name: Display name.
        color: The color this player plays (set after game starts).
        mode: Game mode (NEW, ONGOING, or CHALLENGE).
        time_minutes: Time control in minutes (for NEW mode).
        increment_seconds: Increment in seconds (for NEW mode).
        rated: Whether game is rated (for NEW mode).
        color_preference: Preferred color when seeking ('white', 'black', 'random').
        rating_range: Rating range for matchmaking (for NEW mode).
        game_id: Game ID to resume (for ONGOING mode).
        challenge_id: Challenge ID to accept (for CHALLENGE mode).
        challenge_direction: 'in' for incoming, 'out' for outgoing.
    """
    mode: LichessGameMode = LichessGameMode.NEW
    time_minutes: int = 10
    increment_seconds: int = 5
    rated: bool = False
    color_preference: str = 'random'
    rating_range: str = ''
    game_id: str = ''
    challenge_id: str = ''
    challenge_direction: str = 'in'


class LichessPlayer(Player):
    """A player that connects to Lichess for online games.
    
    This player represents the remote opponent. Moves come from the
    Lichess server via HTTP streaming.
    
    Move Flow (when it's this player's turn):
    1. Stream receives move from server, stores as pending_move
    2. Notifies via lichess_move_callback for LED display
    3. on_piece_event() forms move from lift/place
    4. If move matches pending_move - submits via move_callback
    5. If move doesn't match - board needs correction, no submission
    
    Thread Model:
    - start() authenticates and begins seek/stream
    - Stream thread receives remote moves and stores them
    - Piece events validate execution and submit
    """
    
    def __init__(self, config: Optional[LichessPlayerConfig] = None):
        """Initialize the Lichess player.
        
        Args:
            config: Lichess configuration. If None, uses defaults.
        """
        super().__init__(config or LichessPlayerConfig())
        self._lichess_config: LichessPlayerConfig = self._config
        
        # Lichess API client (berserk)
        self._client = None
        self._token = None
        
        # Game state
        self._game_id: Optional[str] = None
        self._player_is_white: Optional[bool] = None  # Is the LOCAL player white?
        self._current_turn_is_white: bool = True
        
        # Player info
        self._username: str = ''
        self._white_player: str = ''
        self._black_player: str = ''
        self._white_rating: str = ''
        self._black_rating: str = ''
        
        # Clock state (in seconds)
        self._white_time: int = 0
        self._black_time: int = 0
        
        # Move tracking for remote move detection
        self._remote_moves: str = ''
        self._last_processed_moves: str = ''
        
        # Pending move from server (for validation)
        self._pending_move: Optional[chess.Move] = None
        
        # Threading
        self._should_stop = threading.Event()
        self._stream_thread: Optional[threading.Thread] = None
        self._seek_thread: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()
        
        # Board orientation
        self._board_flip: bool = False
        
        # Callbacks for game events
        self._on_game_connected: Optional[Callable] = None
        self._clock_callback: Optional[Callable[[int, int], None]] = None
        self._game_info_callback: Optional[Callable[[str, str, str, str], None]] = None
    
    @property
    def player_type(self) -> PlayerType:
        """Lichess player type."""
        return PlayerType.LICHESS
    
    def supports_late_castling(self) -> bool:
        """Lichess does not support late castling.
        
        Once a move is sent to the Lichess server, it cannot be undone.
        Players must castle properly (king first).
        """
        return False
    
    @property
    def board_flip(self) -> bool:
        """Whether board display should be flipped (True if local player is black)."""
        return self._board_flip
    
    @property
    def game_id(self) -> Optional[str]:
        """Current Lichess game ID."""
        return self._game_id
    
    @property
    def white_player(self) -> str:
        """White player's username."""
        return self._white_player
    
    @property
    def black_player(self) -> str:
        """Black player's username."""
        return self._black_player
    
    @property
    def white_rating(self) -> str:
        """White player's rating."""
        return self._white_rating
    
    @property
    def black_rating(self) -> str:
        """Black player's rating."""
        return self._black_rating
    
    def set_on_game_connected(self, callback: Callable) -> None:
        """Set callback for when game is connected and ready."""
        self._on_game_connected = callback
    
    def set_clock_callback(self, callback: Callable[[int, int], None]) -> None:
        """Set callback for clock updates (white_time, black_time in seconds)."""
        self._clock_callback = callback
    
    def set_game_info_callback(self, callback: Callable[[str, str, str, str], None]) -> None:
        """Set callback for game info (white_player, white_rating, black_player, black_rating)."""
        self._game_info_callback = callback
    
    def start(self) -> bool:
        """Start the Lichess connection and game.
        
        Authenticates with Lichess API, then starts the appropriate
        game flow based on config.mode (NEW, ONGOING, or CHALLENGE).
        
        Returns:
            True if connection started successfully, False on error.
        """
        log.info("[LichessPlayer] Starting Lichess player")
        self._set_state(PlayerState.INITIALIZING)
        self._report_status("Connecting to Lichess...")
        
        # Get API token
        self._token = centaur.get_lichess_api()
        if not self._token or self._token == "tokenhere":
            log.error("[LichessPlayer] No valid API token configured")
            self._set_state(PlayerState.ERROR, "No API token configured")
            return False
        
        # Initialize berserk client
        try:
            import berserk
            session = berserk.TokenSession(self._token)
            self._client = berserk.Client(session=session)
        except ImportError:
            log.error("[LichessPlayer] berserk library not installed")
            self._set_state(PlayerState.ERROR, "berserk not installed")
            return False
        except Exception as e:
            log.error(f"[LichessPlayer] Failed to create berserk client: {e}")
            self._set_state(PlayerState.ERROR, "API client error")
            return False
        
        # Authenticate and get user info
        self._report_status("Authenticating...")
        try:
            user_info = self._client.account.get()
            self._username = user_info.get('username', '')
            log.info(f"[LichessPlayer] Authenticated as: {self._username}")
        except Exception as e:
            log.error(f"[LichessPlayer] Authentication failed: {e}")
            self._set_state(PlayerState.ERROR, "API token invalid")
            return False
        
        # Start appropriate game flow
        if self._lichess_config.mode == LichessGameMode.NEW:
            return self._start_new_game()
        elif self._lichess_config.mode == LichessGameMode.ONGOING:
            return self._start_ongoing_game()
        elif self._lichess_config.mode == LichessGameMode.CHALLENGE:
            return self._start_challenge()
        
        return False
    
    def stop(self) -> None:
        """Stop the Lichess connection and cleanup."""
        log.info("[LichessPlayer] Stopping Lichess player")
        self._should_stop.set()
        
        # Wait for threads to finish
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=2.0)
        if self._seek_thread and self._seek_thread.is_alive():
            self._seek_thread.join(timeout=2.0)
        
        self._set_state(PlayerState.STOPPED)
        log.info("[LichessPlayer] Lichess player stopped")
    
    def _do_request_move(self, board: chess.Board) -> None:
        """Request a move from this player.
        
        If a pending move exists (received from server), displays LEDs.
        Resets piece event tracking for the new turn.
        
        Args:
            board: Current chess position.
        """
        self._lifted_squares = []
        
        if self._pending_move:
            log.info(f"[LichessPlayer] Displaying pending move: {self._pending_move.uci()}")
            if self._pending_move_callback:
                self._pending_move_callback(self._pending_move)
        else:
            log.debug("[LichessPlayer] request_move called - waiting for server move")
    
    def _on_move_formed(self, move: chess.Move) -> None:
        """Validate formed move matches server's move.
        
        Only submits if the move matches the pending move from server.
        If it doesn't match, the board state is wrong and needs correction.
        
        Args:
            move: The formed move from piece events.
        """
        log.debug(f"[LichessPlayer] Move formed: {move.uci()}")
        
        if self._pending_move is None:
            log.warning(f"[LichessPlayer] Move formed but no pending move from server")
            return
        
        # Check if move matches (ignoring promotion - use pending move's promotion)
        if move.from_square == self._pending_move.from_square and \
           move.to_square == self._pending_move.to_square:
            # Match! Submit the pending move (includes promotion if any)
            log.info(f"[LichessPlayer] Move matches server: {self._pending_move.uci()}")
            if self._move_callback:
                self._move_callback(self._pending_move)
            else:
                log.warning("[LichessPlayer] No move callback set, cannot submit move")
        else:
            # Doesn't match - board needs correction
            log.warning(f"[LichessPlayer] Move {move.uci()} does not match server {self._pending_move.uci()} - correction needed")
    
    def on_move_made(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that a move was made on the board.
        
        Clears pending state. For the local player's moves, sends to Lichess.
        
        Args:
            move: The move that was made.
            board: Board state after the move.
        """
        # Clear pending state
        self._pending_move = None
        self._lifted_square = None
        
        # If this was the remote player's move (this player's move), don't send to server
        # The move came FROM the server, so we don't echo it back
        # on_move_made is called for ALL moves, so we need to check whose move it was
        # The board.turn is now the NEXT player's turn, so if it's our color, the last move was opponent's
        if board.turn == self._color:
            # Last move was opponent's (local player's) - they made a move, send it to server
            log.info(f"[LichessPlayer] Sending local player's move to server: {move.uci()}")
            self._send_move_to_server(move)
        else:
            # Last move was ours (remote player's) - came from server, don't echo
            log.debug(f"[LichessPlayer] Our move executed: {move.uci()}")
    
    def _send_move_to_server(self, move: chess.Move) -> None:
        """Send a move to the Lichess server.
        
        Args:
            move: The move to send.
        """
        if self._state != PlayerState.READY:
            log.warning(f"[LichessPlayer] Cannot send move - state is {self._state}")
            return
        
        move_uci = move.uci()
        
        retries = 3
        for attempt in range(retries):
            try:
                self._client.board.make_move(self._game_id, move_uci)
                log.debug("[LichessPlayer] Move sent successfully")
                return
            except Exception as e:
                log.warning(f"[LichessPlayer] Move attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(0.5)
        
        log.error(f"[LichessPlayer] Failed to send move after {retries} attempts")
    
    def on_new_game(self) -> None:
        """Notification that a new game is starting."""
        log.info("[LichessPlayer] New game notification")
    
    def on_resign(self, color: chess.Color) -> None:
        """Resign the current game."""
        if not self._game_id or not self._client:
            log.warning("[LichessPlayer] Cannot resign - no active game")
            return
        
        if self._state != PlayerState.READY:
            log.info(f"[LichessPlayer] Cannot resign - state is {self._state}")
            return
        
        log.info("[LichessPlayer] Resigning game")
        try:
            self._client.board.resign_game(self._game_id)
        except Exception as e:
            log.error(f"[LichessPlayer] Failed to resign: {e}")
    
    def on_draw_offer(self) -> None:
        """Offer a draw to the opponent."""
        if not self._game_id or not self._client:
            log.warning("[LichessPlayer] Cannot offer draw - no active game")
            return
        
        log.info("[LichessPlayer] Offering draw")
        try:
            self._client.board.offer_draw(self._game_id)
        except Exception as e:
            log.error(f"[LichessPlayer] Failed to offer draw: {e}")
    
    def abort_game(self) -> None:
        """Abort the current game (only valid in first few moves)."""
        if not self._game_id or not self._client:
            log.warning("[LichessPlayer] Cannot abort - no active game")
            return
        
        if self._state != PlayerState.READY:
            log.info(f"[LichessPlayer] Cannot abort - state is {self._state}")
            return
        
        log.info("[LichessPlayer] Aborting game")
        try:
            self._client.board.abort_game(self._game_id)
        except Exception as e:
            log.error(f"[LichessPlayer] Failed to abort: {e}")
    
    def supports_takeback(self) -> bool:
        """Lichess doesn't support takeback from external boards."""
        return False
    
    def get_info(self) -> dict:
        """Get information about this player."""
        info = super().get_info()
        info.update({
            'game_id': self._game_id,
            'username': self._username,
            'white_player': self._white_player,
            'black_player': self._black_player,
            'white_rating': self._white_rating,
            'black_rating': self._black_rating,
            'description': 'Lichess online game',
        })
        return info
    
    # =========================================================================
    # Game Flow Methods - Private
    # =========================================================================
    
    def _start_new_game(self) -> bool:
        """Start seeking a new game."""
        log.info(f"[LichessPlayer] Seeking: {self._lichess_config.time_minutes}+{self._lichess_config.increment_seconds}")
        self._report_status("Finding opponent...")
        
        self._seek_thread = threading.Thread(
            target=self._seek_game_thread,
            name="lichess-seek",
            daemon=True
        )
        self._seek_thread.start()
        
        return True
    
    def _seek_game_thread(self):
        """Background thread for game seeking."""
        try:
            rated = self._lichess_config.rated
            color = self._lichess_config.color_preference.lower()
            if color == 'random':
                color = None
            rating_range = self._lichess_config.rating_range or centaur.lichess_range
            
            self._client.board.seek(
                int(self._lichess_config.time_minutes),
                int(self._lichess_config.increment_seconds),
                rated,
                color=color,
                rating_range=rating_range
            )
            
            if not self._should_stop.is_set():
                self._find_and_start_game()
                
        except Exception as e:
            if not self._should_stop.is_set():
                log.error(f"[LichessPlayer] Seek failed: {e}")
                self._set_state(PlayerState.ERROR, "Seek failed")
    
    def _find_and_start_game(self):
        """Find the most recent matching game and start streaming."""
        log.info("[LichessPlayer] Looking for started game...")
        
        max_attempts = 30
        for attempt in range(max_attempts):
            if self._should_stop.is_set():
                return
            
            try:
                ongoing = self._client.games.get_ongoing(30)
                for game in ongoing:
                    game_id = game.get('gameId')
                    if game_id:
                        self._game_id = game_id
                        log.info(f"[LichessPlayer] Found game: {game_id}")
                        self._start_game_stream()
                        return
            except Exception as e:
                log.warning(f"[LichessPlayer] Error checking ongoing games: {e}")
            
            time.sleep(0.5)
        
        log.error("[LichessPlayer] Could not find started game")
        self._set_state(PlayerState.ERROR, "Game not found")
    
    def _start_ongoing_game(self) -> bool:
        """Resume an ongoing game."""
        self._game_id = self._lichess_config.game_id
        if not self._game_id:
            log.error("[LichessPlayer] No game_id provided for ONGOING mode")
            return False
        
        log.info(f"[LichessPlayer] Resuming game: {self._game_id}")
        self._start_game_stream()
        return True
    
    def _start_challenge(self) -> bool:
        """Accept or wait for a challenge."""
        challenge_id = self._lichess_config.challenge_id
        if not challenge_id:
            log.error("[LichessPlayer] No challenge_id provided")
            return False
        
        log.info(f"[LichessPlayer] Handling challenge: {challenge_id}")
        self._report_status("Accepting challenge...")
        
        try:
            if self._lichess_config.challenge_direction == 'in':
                self._client.challenges.accept(challenge_id)
            
            self._game_id = challenge_id
            self._start_game_stream()
            return True
            
        except Exception as e:
            log.error(f"[LichessPlayer] Challenge handling failed: {e}")
            self._set_state(PlayerState.ERROR, "Challenge failed")
            return False
    
    def _start_game_stream(self):
        """Start the game state streaming thread."""
        log.info(f"[LichessPlayer] Starting game stream: {self._game_id}")
        
        self._stream_thread = threading.Thread(
            target=self._game_stream_thread,
            name="lichess-stream",
            daemon=True
        )
        self._stream_thread.start()
    
    def _game_stream_thread(self):
        """Background thread for streaming game state from Lichess."""
        log.info(f"[LichessPlayer] Stream thread started for {self._game_id}")
        
        try:
            game_stream = self._client.board.stream_game_state(self._game_id)
            
            for state in game_stream:
                if self._should_stop.is_set():
                    break
                
                self._process_game_state(state)
                
        except Exception as e:
            if not self._should_stop.is_set():
                log.error(f"[LichessPlayer] Stream error: {e}")
                self._set_state(PlayerState.ERROR, "Stream disconnected")
        
        log.info("[LichessPlayer] Stream thread ended")
    
    def _process_game_state(self, state: dict):
        """Process a game state update from Lichess stream."""
        log.debug(f"[LichessPlayer] State update: {state}")
        
        # Skip non-game messages
        if 'chatLine' in str(state) or 'opponentGone' in str(state):
            return
        
        # Extract player info from initial state
        if 'white' in state and 'black' in state:
            self._extract_player_info(state)
        
        # Extract moves and status
        if 'state' in state:
            inner_state = state['state']
            moves = inner_state.get('moves', '')
            status = inner_state.get('status', '')
            self._process_time_update(inner_state)
        else:
            moves = state.get('moves', '')
            status = state.get('status', '')
            self._process_time_update(state)
        
        moves = str(moves) if moves else ''
        
        # Check for new remote moves
        if moves != self._remote_moves:
            self._remote_moves = moves
            self._check_for_remote_move()
        
        # Check game status
        self._check_game_status(status, state)
    
    def _extract_player_info(self, state: dict):
        """Extract player information from game state."""
        white_info = state.get('white', {})
        black_info = state.get('black', {})
        
        self._white_player = str(white_info.get('name', 'Unknown'))
        self._white_rating = str(white_info.get('rating', ''))
        self._black_player = str(black_info.get('name', 'Unknown'))
        self._black_rating = str(black_info.get('rating', ''))
        
        if self._white_player == self._username:
            self._player_is_white = True
            self._board_flip = False
            # This player represents the remote opponent (Black)
            self._color = chess.BLACK
        else:
            self._player_is_white = False
            self._board_flip = True
            # This player represents the remote opponent (White)
            self._color = chess.WHITE
        
        log.info(f"[LichessPlayer] Players: {self._white_player} ({self._white_rating}) vs "
                 f"{self._black_player} ({self._black_rating})")
        log.info(f"[LichessPlayer] Local user is: {'White' if self._player_is_white else 'Black'}")
        log.info(f"[LichessPlayer] This player instance represents: {'White' if self._color == chess.WHITE else 'Black'}")
        
        self._set_state(PlayerState.READY)
        
        # Notify game info callback
        if self._game_info_callback:
            self._game_info_callback(
                self._white_player, self._white_rating,
                self._black_player, self._black_rating
            )
        
        # Notify game connected callback
        if self._on_game_connected:
            try:
                self._on_game_connected()
            except Exception as e:
                log.warning(f"[LichessPlayer] Error in on_game_connected: {e}")
    
    def _process_time_update(self, state: dict):
        """Process clock time update."""
        try:
            wtime = state.get('wtime')
            btime = state.get('btime')
            
            if wtime is not None and isinstance(wtime, int):
                self._white_time = wtime // 1000
            
            if btime is not None and isinstance(btime, int):
                self._black_time = btime // 1000
            
            if self._clock_callback:
                self._clock_callback(self._white_time, self._black_time)
                
        except Exception as e:
            log.warning(f"[LichessPlayer] Error processing time: {e}")
    
    def _check_for_remote_move(self):
        """Check if there's a new remote move to process."""
        if not self._remote_moves:
            return
        
        moves_list = self._remote_moves.split()
        if not moves_list:
            return
        
        last_move = moves_list[-1].lower()
        
        if self._remote_moves == self._last_processed_moves:
            return
        
        self._last_processed_moves = self._remote_moves
        
        # Determine who made the last move
        move_count = len(moves_list)
        last_move_was_white = (move_count % 2 == 1)
        
        # Check if this is the local user's own move echoed back
        if self._player_is_white is not None:
            if self._player_is_white and last_move_was_white:
                log.debug(f"[LichessPlayer] Ignoring echo of local move: {last_move}")
                return
            elif not self._player_is_white and not last_move_was_white:
                log.debug(f"[LichessPlayer] Ignoring echo of local move: {last_move}")
                return
        
        log.info(f"[LichessPlayer] Remote move from server: {last_move}")
        
        # Store as pending move - will be submitted after piece events confirm
        try:
            self._pending_move = chess.Move.from_uci(last_move)
            
            # Notify for LED display
            if self._pending_move_callback:
                self._pending_move_callback(self._pending_move)
        except Exception as e:
            log.error(f"[LichessPlayer] Invalid move from Lichess: {last_move}: {e}")
    
    def _check_game_status(self, status: str, state: dict):
        """Check game status and handle game end conditions."""
        status = str(status).lower()
        
        terminal_states = ['mate', 'resign', 'draw', 'aborted', 'outoftime', 'timeout', 'stalemate']
        
        if status in terminal_states:
            log.info(f"[LichessPlayer] Game ended: {status}")
            self._set_state(PlayerState.STOPPED)


def create_lichess_player(
    mode: LichessGameMode = LichessGameMode.NEW,
    time_minutes: int = 10,
    increment_seconds: int = 5,
    rated: bool = False,
    color: str = 'random',
    game_id: str = '',
    challenge_id: str = '',
) -> LichessPlayer:
    """Factory function to create a Lichess player.
    
    Args:
        mode: Game mode (NEW, ONGOING, CHALLENGE).
        time_minutes: Time control in minutes.
        increment_seconds: Increment in seconds.
        rated: Whether game is rated.
        color: Preferred color ('white', 'black', 'random').
        game_id: Game ID for ONGOING mode.
        challenge_id: Challenge ID for CHALLENGE mode.
    
    Returns:
        Configured LichessPlayer instance.
    """
    config = LichessPlayerConfig(
        name="Lichess",
        mode=mode,
        time_minutes=time_minutes,
        increment_seconds=increment_seconds,
        rated=rated,
        color_preference=color,
        game_id=game_id,
        challenge_id=challenge_id,
    )
    
    return LichessPlayer(config)
