# Lichess Opponent
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Implements a chess opponent using Lichess online play.
# Connects to Lichess API for real-time games against human opponents.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable

import chess

from DGTCentaurMods.board import board, centaur
from DGTCentaurMods.board.logging import log
from .base import Opponent, OpponentConfig, OpponentState


class LichessGameMode(Enum):
    """Lichess game modes."""
    NEW = auto()        # Seek a new game with specified parameters
    ONGOING = auto()    # Resume an ongoing game by ID
    CHALLENGE = auto()  # Accept or wait for a challenge


@dataclass
class LichessConfig(OpponentConfig):
    """Configuration for Lichess opponent.
    
    Attributes:
        name: Display name.
        time_limit_seconds: Not used for Lichess (server manages clock).
        mode: Game mode (NEW, ONGOING, or CHALLENGE).
        time_minutes: Time control in minutes (for NEW mode).
        increment_seconds: Increment in seconds (for NEW mode).
        rated: Whether game is rated (for NEW mode).
        color_preference: Preferred color when seeking ('white', 'black', 'random').
                         This is a game-seeking preference, not stored state.
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


class LichessOpponent(Opponent):
    """Lichess online opponent.
    
    Plays against the user via Lichess API. Unlike engine opponents,
    moves come from a remote human player via HTTP/WebSocket streaming.
    
    This is fundamentally different from local opponents:
    - Moves arrive asynchronously via stream (not computed locally)
    - Player's moves are sent to server (not just tracked locally)
    - Game lifecycle managed by Lichess (resign, draw, abort)
    
    Thread Model:
    - start() authenticates and begins seek/stream
    - Stream thread receives opponent moves and pushes via callback
    - Player moves sent immediately to Lichess API
    """
    
    def __init__(self, config: Optional[LichessConfig] = None):
        """Initialize the Lichess opponent.
        
        Args:
            config: Lichess configuration. If None, uses defaults.
        """
        super().__init__(config or LichessConfig())
        self._lichess_config: LichessConfig = self._config
        
        # Lichess API client (berserk)
        self._client = None
        self._token = None
        
        # Game state
        self._game_id: Optional[str] = None
        self._player_is_white: Optional[bool] = None
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
        
        # Track opponent moves being executed on board (to avoid sending back)
        # When we receive an opponent move, we add it here. When the user
        # physically executes it and on_player_move is called, we skip sending.
        self._pending_opponent_moves: set = set()
        
        # Threading
        self._should_stop = threading.Event()
        self._stream_thread: Optional[threading.Thread] = None
        self._seek_thread: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()
        
        # Board orientation
        self._board_flip: bool = False
        
        # Callback for game events
        self._on_game_connected: Optional[Callable] = None
        self._clock_callback: Optional[Callable[[int, int], None]] = None
        self._game_info_callback: Optional[Callable[[str, str, str, str], None]] = None
    
    @property
    def board_flip(self) -> bool:
        """Whether board display should be flipped (True if playing black)."""
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
        """Set callback for when game is connected and ready.
        
        Args:
            callback: Function to call when game transitions to playing.
        """
        self._on_game_connected = callback
    
    def set_clock_callback(self, callback: Callable[[int, int], None]) -> None:
        """Set callback for clock updates.
        
        Args:
            callback: Function(white_time, black_time) in seconds.
        """
        self._clock_callback = callback
    
    def set_game_info_callback(self, callback: Callable[[str, str, str, str], None]) -> None:
        """Set callback for game info updates.
        
        Args:
            callback: Function(white_player, white_rating, black_player, black_rating).
        """
        self._game_info_callback = callback
    
    def start(self) -> bool:
        """Start the Lichess connection and game.
        
        Authenticates with Lichess API, then starts the appropriate
        game flow based on config.mode (NEW, ONGOING, or CHALLENGE).
        
        Returns:
            True if connection started successfully, False on error.
        """
        log.info("[LichessOpponent] Starting Lichess opponent")
        self._set_state(OpponentState.INITIALIZING)
        self._report_status("Connecting to Lichess...")
        
        # Get API token
        self._token = centaur.get_lichess_api()
        if not self._token or self._token == "tokenhere":
            log.error("[LichessOpponent] No valid API token configured")
            self._set_state(OpponentState.ERROR, "No API token configured")
            return False
        
        # Initialize berserk client
        try:
            import berserk
            session = berserk.TokenSession(self._token)
            self._client = berserk.Client(session=session)
        except ImportError:
            log.error("[LichessOpponent] berserk library not installed")
            self._set_state(OpponentState.ERROR, "berserk not installed")
            return False
        except Exception as e:
            log.error(f"[LichessOpponent] Failed to create berserk client: {e}")
            self._set_state(OpponentState.ERROR, "API client error")
            return False
        
        # Authenticate and get user info
        self._report_status("Authenticating...")
        try:
            user_info = self._client.account.get()
            self._username = user_info.get('username', '')
            log.info(f"[LichessOpponent] Authenticated as: {self._username}")
        except Exception as e:
            log.error(f"[LichessOpponent] Authentication failed: {e}")
            self._set_state(OpponentState.ERROR, "API token invalid")
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
        log.info("[LichessOpponent] Stopping Lichess opponent")
        self._should_stop.set()
        
        # Wait for threads to finish
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=2.0)
        if self._seek_thread and self._seek_thread.is_alive():
            self._seek_thread.join(timeout=2.0)
        
        self._set_state(OpponentState.STOPPED)
        log.info("[LichessOpponent] Lichess opponent stopped")
    
    def get_move(self, board: chess.Board) -> Optional[chess.Move]:
        """Get opponent's move.
        
        For Lichess, moves arrive asynchronously via the stream thread.
        This method returns None immediately - moves are delivered via
        the move_callback when they arrive from Lichess.
        
        Args:
            board: Current chess position (not used - Lichess tracks state).
        
        Returns:
            None (moves delivered asynchronously).
        """
        log.debug("[LichessOpponent] get_move called - moves arrive via stream")
        return None
    
    def on_player_move(self, move: chess.Move, board: chess.Board) -> None:
        """Send player's move to Lichess.
        
        Called after the player's move is validated and applied locally.
        Sends the move to Lichess server.
        
        Note: Skips sending if this move was received from the opponent
        (i.e., the user physically executed the opponent's move on the board).
        
        Args:
            move: The move the player made.
            board: Board state after the move.
        """
        if self._state != OpponentState.READY:
            log.warning(f"[LichessOpponent] Cannot send move - state is {self._state}")
            return
        
        move_uci = move.uci()
        
        # Check if this is an opponent move being physically executed
        if move_uci in self._pending_opponent_moves:
            log.debug(f"[LichessOpponent] Skipping send - this is opponent move being executed: {move_uci}")
            self._pending_opponent_moves.discard(move_uci)
            return
        
        log.info(f"[LichessOpponent] Sending player move: {move_uci}")
        
        retries = 3
        for attempt in range(retries):
            try:
                # make_move returns None on success, raises exception on failure
                self._client.board.make_move(self._game_id, move_uci)
                log.debug(f"[LichessOpponent] Move sent successfully")
                return
            except Exception as e:
                log.warning(f"[LichessOpponent] Move attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(0.5)
        
        log.error(f"[LichessOpponent] Failed to send move after {retries} attempts")
    
    def on_new_game(self) -> None:
        """Notification that a new game is starting.
        
        For Lichess, this is handled by the game stream.
        """
        log.info("[LichessOpponent] New game notification")
    
    def on_resign(self) -> None:
        """Resign the current game."""
        if not self._game_id or not self._client:
            log.warning("[LichessOpponent] Cannot resign - no active game")
            return
        
        if self._state != OpponentState.READY:
            log.info(f"[LichessOpponent] Cannot resign - state is {self._state}")
            return
        
        log.info("[LichessOpponent] Resigning game")
        try:
            self._client.board.resign_game(self._game_id)
        except Exception as e:
            log.error(f"[LichessOpponent] Failed to resign: {e}")
    
    def on_draw_offer(self) -> None:
        """Offer a draw to the opponent."""
        if not self._game_id or not self._client:
            log.warning("[LichessOpponent] Cannot offer draw - no active game")
            return
        
        log.info("[LichessOpponent] Offering draw")
        try:
            self._client.board.offer_draw(self._game_id)
        except Exception as e:
            log.error(f"[LichessOpponent] Failed to offer draw: {e}")
    
    def abort_game(self) -> None:
        """Abort the current game (only valid in first few moves)."""
        if not self._game_id or not self._client:
            log.warning("[LichessOpponent] Cannot abort - no active game")
            return
        
        if self._state != OpponentState.READY:
            log.info(f"[LichessOpponent] Cannot abort - state is {self._state}")
            return
        
        log.info("[LichessOpponent] Aborting game")
        try:
            self._client.board.abort_game(self._game_id)
        except Exception as e:
            log.error(f"[LichessOpponent] Failed to abort: {e}")
    
    # Aliases for compatibility with emulator API
    def resign_game(self) -> None:
        """Alias for on_resign() for compatibility."""
        self.on_resign()
    
    def offer_draw(self) -> None:
        """Alias for on_draw_offer() for compatibility."""
        self.on_draw_offer()
    
    def supports_takeback(self) -> bool:
        """Lichess doesn't support takeback from external boards."""
        return False
    
    def get_info(self) -> dict:
        """Get information about this opponent."""
        info = super().get_info()
        info.update({
            'type': 'lichess',
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
        log.info(f"[LichessOpponent] Seeking: {self._lichess_config.time_minutes}+{self._lichess_config.increment_seconds}")
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
                log.error(f"[LichessOpponent] Seek failed: {e}")
                self._set_state(OpponentState.ERROR, "Seek failed")
    
    def _find_and_start_game(self):
        """Find the most recent matching game and start streaming."""
        log.info("[LichessOpponent] Looking for started game...")
        
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
                        log.info(f"[LichessOpponent] Found game: {game_id}")
                        self._start_game_stream()
                        return
            except Exception as e:
                log.warning(f"[LichessOpponent] Error checking ongoing games: {e}")
            
            time.sleep(0.5)
        
        log.error("[LichessOpponent] Could not find started game")
        self._set_state(OpponentState.ERROR, "Game not found")
    
    def _start_ongoing_game(self) -> bool:
        """Resume an ongoing game."""
        self._game_id = self._lichess_config.game_id
        if not self._game_id:
            log.error("[LichessOpponent] No game_id provided for ONGOING mode")
            return False
        
        log.info(f"[LichessOpponent] Resuming game: {self._game_id}")
        self._start_game_stream()
        return True
    
    def _start_challenge(self) -> bool:
        """Accept or wait for a challenge."""
        challenge_id = self._lichess_config.challenge_id
        if not challenge_id:
            log.error("[LichessOpponent] No challenge_id provided")
            return False
        
        log.info(f"[LichessOpponent] Handling challenge: {challenge_id}")
        self._report_status("Accepting challenge...")
        
        try:
            if self._lichess_config.challenge_direction == 'in':
                self._client.challenges.accept(challenge_id)
            
            self._game_id = challenge_id
            self._start_game_stream()
            return True
            
        except Exception as e:
            log.error(f"[LichessOpponent] Challenge handling failed: {e}")
            self._set_state(OpponentState.ERROR, "Challenge failed")
            return False
    
    def _start_game_stream(self):
        """Start the game state streaming thread."""
        log.info(f"[LichessOpponent] Starting game stream: {self._game_id}")
        
        self._stream_thread = threading.Thread(
            target=self._game_stream_thread,
            name="lichess-stream",
            daemon=True
        )
        self._stream_thread.start()
    
    def _game_stream_thread(self):
        """Background thread for streaming game state from Lichess."""
        log.info(f"[LichessOpponent] Stream thread started for {self._game_id}")
        
        try:
            game_stream = self._client.board.stream_game_state(self._game_id)
            
            for state in game_stream:
                if self._should_stop.is_set():
                    break
                
                self._process_game_state(state)
                
        except Exception as e:
            if not self._should_stop.is_set():
                log.error(f"[LichessOpponent] Stream error: {e}")
                self._set_state(OpponentState.ERROR, "Stream disconnected")
        
        log.info("[LichessOpponent] Stream thread ended")
    
    def _process_game_state(self, state: dict):
        """Process a game state update from Lichess stream."""
        log.debug(f"[LichessOpponent] State update: {state}")
        
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
        else:
            self._player_is_white = False
            self._board_flip = True
        
        log.info(f"[LichessOpponent] Players: {self._white_player} ({self._white_rating}) vs "
                 f"{self._black_player} ({self._black_rating})")
        log.info(f"[LichessOpponent] Playing as: {'White' if self._player_is_white else 'Black'}")
        
        self._set_state(OpponentState.READY)
        
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
                log.warning(f"[LichessOpponent] Error in on_game_connected: {e}")
    
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
            log.warning(f"[LichessOpponent] Error processing time: {e}")
    
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
        
        # Check if this is our own move echoed back
        if self._player_is_white is not None:
            if self._player_is_white and last_move_was_white:
                log.debug(f"[LichessOpponent] Ignoring echo of our move: {last_move}")
                return
            elif not self._player_is_white and not last_move_was_white:
                log.debug(f"[LichessOpponent] Ignoring echo of our move: {last_move}")
                return
        
        log.info(f"[LichessOpponent] Remote move from opponent: {last_move}")
        
        # Track this as a pending opponent move - will be physically executed on board
        # and we should not re-send it when on_player_move is called
        self._pending_opponent_moves.add(last_move)
        
        # Convert to chess.Move and deliver via callback
        try:
            move = chess.Move.from_uci(last_move)
            if self._move_callback:
                self._move_callback(move)
        except Exception as e:
            log.error(f"[LichessOpponent] Invalid move from Lichess: {last_move}: {e}")
    
    def _check_game_status(self, status: str, state: dict):
        """Check game status and handle game end conditions."""
        status = str(status).lower()
        
        terminal_states = ['mate', 'resign', 'draw', 'aborted', 'outoftime', 'timeout', 'stalemate']
        
        if status in terminal_states:
            log.info(f"[LichessOpponent] Game ended: {status}")
            self._set_state(OpponentState.STOPPED)


def create_lichess_opponent(
    mode: LichessGameMode = LichessGameMode.NEW,
    time_minutes: int = 10,
    increment_seconds: int = 5,
    rated: bool = False,
    color: str = 'random',
    game_id: str = '',
    challenge_id: str = '',
) -> LichessOpponent:
    """Factory function to create a Lichess opponent.
    
    Args:
        mode: Game mode (NEW, ONGOING, CHALLENGE).
        time_minutes: Time control in minutes.
        increment_seconds: Increment in seconds.
        rated: Whether game is rated.
        color: Preferred color ('white', 'black', 'random').
        game_id: Game ID for ONGOING mode.
        challenge_id: Challenge ID for CHALLENGE mode.
    
    Returns:
        Configured LichessOpponent instance.
    """
    config = LichessConfig(
        name="Lichess",
        mode=mode,
        time_minutes=time_minutes,
        increment_seconds=increment_seconds,
        rated=rated,
        color_preference=color,
        game_id=game_id,
        challenge_id=challenge_id,
    )
    
    return LichessOpponent(config)
