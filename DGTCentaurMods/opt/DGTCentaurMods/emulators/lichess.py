# Lichess Protocol Emulator
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Bridges the DGT Centaur board to Lichess for online play.
# Unlike byte-stream emulators (Millennium, Pegasus, Chessnut),
# this emulator uses HTTP/WebSocket API communication.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

import threading
import time
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Callable

from DGTCentaurMods.board import board, centaur
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.managers.events import (
    EVENT_NEW_GAME,
    EVENT_WHITE_TURN,
    EVENT_BLACK_TURN,
    EVENT_RESIGN_GAME,
    EVENT_REQUEST_DRAW,
)


class LichessGameMode(Enum):
    """Lichess game modes supported by the emulator."""
    NEW = auto()        # Seek a new game with specified parameters
    ONGOING = auto()    # Resume an ongoing game by ID
    CHALLENGE = auto()  # Accept or wait for a challenge


@dataclass
class LichessConfig:
    """Configuration for Lichess game session.
    
    Attributes:
        mode: Game mode (NEW, ONGOING, or CHALLENGE)
        time_minutes: Time control in minutes (for NEW mode)
        increment_seconds: Increment in seconds (for NEW mode)
        rated: Whether game is rated (for NEW mode)
        color: Preferred color 'white', 'black', or 'random' (for NEW mode)
        rating_range: Rating range for matchmaking (for NEW mode)
        game_id: Game ID to resume (for ONGOING mode)
        challenge_id: Challenge ID to accept (for CHALLENGE mode)
        challenge_direction: 'in' for incoming, 'out' for outgoing (for CHALLENGE mode)
    """
    mode: LichessGameMode
    time_minutes: int = 10
    increment_seconds: int = 5
    rated: bool = False
    color: str = 'random'
    rating_range: str = ''
    game_id: str = ''
    challenge_id: str = ''
    challenge_direction: str = 'in'


class LichessGameState(Enum):
    """State machine states for Lichess game lifecycle."""
    DISCONNECTED = auto()      # No connection to Lichess
    AUTHENTICATING = auto()    # Validating API token
    SEEKING = auto()           # Looking for opponent (NEW mode)
    WAITING_CHALLENGE = auto() # Waiting for challenge acceptance
    PLAYING = auto()           # Game in progress
    GAME_OVER = auto()         # Game ended
    ERROR = auto()             # Error state


class Lichess:
    """Lichess API integration as a protocol emulator.
    
    Bridges the physical DGT Centaur board to Lichess for online play.
    Unlike byte-stream emulators, this manages its own API connection
    and game state streaming.
    
    The emulator follows the same callback pattern as other emulators:
    - handle_manager_event: Receives game events from GameManager
    - handle_manager_move: Receives moves made on the physical board
    - handle_manager_key: Receives button presses
    
    Opponent moves from Lichess are pushed to GameManager via computer_move().
    
    Thread Model:
    - Main thread: GameManager callbacks
    - Stream thread: Lichess game state streaming
    - Seek thread: Game seeking (for NEW mode)
    
    All state modifications are protected by locks for thread safety.
    """
    
    # Class property indicating this is not a byte-stream protocol
    supports_rfcomm = False
    supports_ble = False
    is_remote_game = True  # Distinguishes from local protocol emulators
    
    def __init__(
        self,
        sendMessage_callback: Optional[Callable] = None,
        manager=None,
        config: Optional[LichessConfig] = None,
        display_callback: Optional[Callable] = None,
    ):
        """Initialize the Lichess emulator.
        
        Args:
            sendMessage_callback: Not used for Lichess (no byte responses).
                                 Kept for interface compatibility.
            manager: GameManager instance for move handling.
            config: LichessConfig with game parameters.
            display_callback: Optional callback(text_lines: dict) for UI updates.
                             Keys are line numbers, values are text strings.
        """
        self.manager = manager
        self.config = config or LichessConfig(mode=LichessGameMode.NEW)
        self._display_callback = display_callback
        
        # Lichess API client (berserk)
        self._client = None
        self._token = None
        
        # Game state
        self._state = LichessGameState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._game_id: Optional[str] = None
        self._player_is_white: Optional[bool] = None
        self._current_turn_is_white: bool = True
        
        # Player info (populated from Lichess)
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
        
        # Threading
        self._should_stop = threading.Event()
        self._stream_thread: Optional[threading.Thread] = None
        self._seek_thread: Optional[threading.Thread] = None
        
        # Board orientation
        self._board_flip: bool = False
    
    # =========================================================================
    # Public API - Lifecycle Management
    # =========================================================================
    
    def start(self) -> bool:
        """Start the Lichess connection and game.
        
        Authenticates with Lichess API, then starts the appropriate
        game flow based on config.mode (NEW, ONGOING, or CHALLENGE).
        
        Returns:
            True if connection started successfully, False on error.
        """
        log.info("[Lichess] Starting Lichess emulator")
        
        # Get API token
        self._token = centaur.get_lichess_api()
        if not self._token or self._token == "tokenhere":
            log.error("[Lichess] No valid API token configured")
            self._set_state(LichessGameState.ERROR)
            self._display_error("No API token", "Configure in web UI")
            return False
        
        # Initialize berserk client
        try:
            import berserk
            session = berserk.TokenSession(self._token)
            self._client = berserk.Client(session=session)
        except ImportError:
            log.error("[Lichess] berserk library not installed")
            self._set_state(LichessGameState.ERROR)
            self._display_error("berserk not installed")
            return False
        except Exception as e:
            log.error(f"[Lichess] Failed to create berserk client: {e}")
            self._set_state(LichessGameState.ERROR)
            self._display_error("API client error")
            return False
        
        # Authenticate and get user info
        self._set_state(LichessGameState.AUTHENTICATING)
        try:
            user_info = self._client.account.get()
            self._username = user_info.get('username', '')
            log.info(f"[Lichess] Authenticated as: {self._username}")
        except Exception as e:
            log.error(f"[Lichess] Authentication failed: {e}")
            self._set_state(LichessGameState.ERROR)
            self._display_error("API token invalid")
            return False
        
        # Start appropriate game flow
        if self.config.mode == LichessGameMode.NEW:
            return self._start_new_game()
        elif self.config.mode == LichessGameMode.ONGOING:
            return self._start_ongoing_game()
        elif self.config.mode == LichessGameMode.CHALLENGE:
            return self._start_challenge()
        
        return False
    
    def stop(self):
        """Stop the Lichess connection and cleanup.
        
        Signals all threads to stop and waits for them to finish.
        """
        log.info("[Lichess] Stopping Lichess emulator")
        self._should_stop.set()
        
        # Wait for threads to finish
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=2.0)
        if self._seek_thread and self._seek_thread.is_alive():
            self._seek_thread.join(timeout=2.0)
        
        self._set_state(LichessGameState.DISCONNECTED)
        log.info("[Lichess] Lichess emulator stopped")
    
    def is_connected(self) -> bool:
        """Check if connected to a Lichess game.
        
        Returns:
            True if in PLAYING state, False otherwise.
        """
        with self._state_lock:
            return self._state == LichessGameState.PLAYING
    
    # =========================================================================
    # GameManager Callbacks - Same interface as other emulators
    # =========================================================================
    
    def handle_manager_event(self, event, piece_event, field, time_in_seconds):
        """Handle game events from the GameManager.
        
        Args:
            event: Event constant (EVENT_NEW_GAME, EVENT_WHITE_TURN, etc.)
            piece_event: Raw board piece event (0=LIFT, 1=PLACE)
            field: Chess field index (0-63)
            time_in_seconds: Time since game start
        """
        log.debug(f"[Lichess] handle_manager_event: event={event}")
        
        if event == EVENT_NEW_GAME:
            # Game reset detected - update display
            self._update_display()
        
        elif event == EVENT_WHITE_TURN:
            self._current_turn_is_white = True
            self._update_turn_display()
            # If it's opponent's turn, remote move will come via stream
            if not self._is_player_turn():
                log.debug("[Lichess] Opponent's turn - waiting for remote move")
        
        elif event == EVENT_BLACK_TURN:
            self._current_turn_is_white = False
            self._update_turn_display()
            if not self._is_player_turn():
                log.debug("[Lichess] Opponent's turn - waiting for remote move")
        
        elif event == EVENT_RESIGN_GAME:
            self._resign_game()
        
        elif event == EVENT_REQUEST_DRAW:
            self._offer_draw()
        
        # Handle game termination events (passed as strings)
        if isinstance(event, str) and event.startswith("Termination."):
            self._handle_termination(event)
    
    def handle_manager_move(self, move):
        """Handle a move made on the physical board.
        
        Called by GameManager when the player completes a valid move.
        Sends the move to Lichess if it's the player's turn.
        
        Args:
            move: Chess move object (e.g., chess.Move)
        """
        if not self.is_connected():
            log.warning("[Lichess] handle_manager_move called but not connected")
            return
        
        if not self._is_player_turn():
            log.debug(f"[Lichess] Ignoring move {move} - not player's turn")
            return
        
        move_uci = str(move).lower()
        log.info(f"[Lichess] Sending player move to Lichess: {move_uci}")
        
        try:
            success = False
            retries = 3
            for attempt in range(retries):
                try:
                    result = self._client.board.make_move(self._game_id, move_uci)
                    if result:
                        success = True
                        break
                except Exception as e:
                    log.warning(f"[Lichess] Move attempt {attempt + 1} failed: {e}")
                    if attempt < retries - 1:
                        time.sleep(0.5)
            
            if not success:
                log.error(f"[Lichess] Failed to send move {move_uci} after {retries} attempts")
        except Exception as e:
            log.error(f"[Lichess] Error sending move: {e}")
    
    def handle_manager_key(self, key):
        """Handle button presses from the board.
        
        Args:
            key: Key enum value (board.Key.BACK, etc.)
        """
        log.debug(f"[Lichess] handle_manager_key: {key}")
        
        # BACK button typically means exit/resign
        if hasattr(key, 'name') and key.name == 'BACK':
            log.info("[Lichess] BACK key pressed - triggering stop")
            # This will be handled by the calling code to exit
    
    def handle_manager_takeback(self):
        """Handle takeback request.
        
        Lichess doesn't support takeback from external boards,
        so this sends a polite decline message.
        """
        log.info("[Lichess] Takeback requested - not supported on Lichess")
        if self._game_id and self._client:
            try:
                self._client.board.post_message(
                    self._game_id,
                    "Sorry, this external board doesn't support takeback",
                    spectator=False
                )
            except Exception as e:
                log.warning(f"[Lichess] Failed to send takeback message: {e}")
    
    # =========================================================================
    # Game Flow Methods - Private
    # =========================================================================
    
    def _start_new_game(self) -> bool:
        """Start seeking a new game.
        
        Returns:
            True if seek started successfully.
        """
        log.info(f"[Lichess] Seeking new game: {self.config.time_minutes}+{self.config.increment_seconds}")
        self._set_state(LichessGameState.SEEKING)
        self._display_status("Finding Game...")
        
        # Start seek in background thread
        self._seek_thread = threading.Thread(
            target=self._seek_game_thread,
            name="lichess-seek",
            daemon=True
        )
        self._seek_thread.start()
        
        return True
    
    def _seek_game_thread(self):
        """Background thread for game seeking.
        
        Calls Lichess seek API and monitors for game start.
        """
        try:
            rated = self.config.rated
            color = self.config.color.lower() if self.config.color else None
            rating_range = self.config.rating_range or centaur.lichess_range
            
            # Start the seek (blocking call until matched or cancelled)
            self._client.board.seek(
                int(self.config.time_minutes),
                int(self.config.increment_seconds),
                rated,
                color=color,
                rating_range=rating_range
            )
            
            # After seek returns, find the game that was created
            if not self._should_stop.is_set():
                self._find_and_start_game()
                
        except Exception as e:
            if not self._should_stop.is_set():
                log.error(f"[Lichess] Seek failed: {e}")
                self._set_state(LichessGameState.ERROR)
                self._display_error("Seek failed")
    
    def _find_and_start_game(self):
        """Find the most recent matching game and start streaming."""
        import datetime
        
        log.info("[Lichess] Looking for started game...")
        
        # Poll for ongoing games
        max_attempts = 30
        for attempt in range(max_attempts):
            if self._should_stop.is_set():
                return
            
            try:
                ongoing = self._client.games.get_ongoing(30)
                for game in ongoing:
                    game_id = game.get('gameId')
                    if game_id:
                        # Found a game - start it
                        self._game_id = game_id
                        log.info(f"[Lichess] Found game: {game_id}")
                        self._start_game_stream()
                        return
            except Exception as e:
                log.warning(f"[Lichess] Error checking ongoing games: {e}")
            
            time.sleep(0.5)
        
        log.error("[Lichess] Could not find started game")
        self._set_state(LichessGameState.ERROR)
    
    def _start_ongoing_game(self) -> bool:
        """Resume an ongoing game.
        
        Returns:
            True if game stream started successfully.
        """
        self._game_id = self.config.game_id
        if not self._game_id:
            log.error("[Lichess] No game_id provided for ONGOING mode")
            return False
        
        log.info(f"[Lichess] Resuming ongoing game: {self._game_id}")
        self._start_game_stream()
        return True
    
    def _start_challenge(self) -> bool:
        """Accept or wait for a challenge.
        
        Returns:
            True if challenge accepted/waiting started.
        """
        challenge_id = self.config.challenge_id
        if not challenge_id:
            log.error("[Lichess] No challenge_id provided")
            return False
        
        log.info(f"[Lichess] Handling challenge: {challenge_id}")
        self._set_state(LichessGameState.WAITING_CHALLENGE)
        self._display_status("Accepting challenge...")
        
        try:
            if self.config.challenge_direction == 'in':
                self._client.challenges.accept(challenge_id)
            # For outgoing challenges, just wait for acceptance
            
            self._game_id = challenge_id
            self._start_game_stream()
            return True
            
        except Exception as e:
            log.error(f"[Lichess] Challenge handling failed: {e}")
            self._set_state(LichessGameState.ERROR)
            return False
    
    def _start_game_stream(self):
        """Start the game state streaming thread."""
        log.info(f"[Lichess] Starting game stream for: {self._game_id}")
        
        self._stream_thread = threading.Thread(
            target=self._game_stream_thread,
            name="lichess-stream",
            daemon=True
        )
        self._stream_thread.start()
    
    def _game_stream_thread(self):
        """Background thread for streaming game state from Lichess.
        
        Receives game state updates and processes:
        - Player info (names, ratings, colors)
        - Move updates (remote moves to execute)
        - Clock updates
        - Game status (resign, draw, timeout, etc.)
        """
        log.info(f"[Lichess] Game stream thread started for {self._game_id}")
        
        try:
            game_stream = self._client.board.stream_game_state(self._game_id)
            
            for state in game_stream:
                if self._should_stop.is_set():
                    break
                
                self._process_game_state(state)
                
        except Exception as e:
            if not self._should_stop.is_set():
                log.error(f"[Lichess] Game stream error: {e}")
                self._set_state(LichessGameState.ERROR)
        
        log.info("[Lichess] Game stream thread ended")
    
    def _process_game_state(self, state: dict):
        """Process a game state update from Lichess stream.
        
        Args:
            state: Game state dictionary from Lichess API
        """
        log.debug(f"[Lichess] Game state update: {state}")
        
        # Skip non-game messages
        if 'chatLine' in str(state) or 'opponentGone' in str(state):
            return
        
        # Extract player info from initial game state
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
        
        # Convert moves to string
        moves = str(moves) if moves else ''
        
        # Check for new remote moves
        if moves != self._remote_moves:
            self._remote_moves = moves
            self._check_for_remote_move()
        
        # Check game status
        self._check_game_status(status, state)
    
    def _extract_player_info(self, state: dict):
        """Extract player information from game state.
        
        Args:
            state: Game state with 'white' and 'black' keys
        """
        white_info = state.get('white', {})
        black_info = state.get('black', {})
        
        self._white_player = str(white_info.get('name', 'Unknown'))
        self._white_rating = str(white_info.get('rating', ''))
        self._black_player = str(black_info.get('name', 'Unknown'))
        self._black_rating = str(black_info.get('rating', ''))
        
        # Determine which color we are
        if self._white_player == self._username:
            self._player_is_white = True
            self._board_flip = False
        else:
            self._player_is_white = False
            self._board_flip = True
        
        log.info(f"[Lichess] Players: {self._white_player} ({self._white_rating}) vs "
                 f"{self._black_player} ({self._black_rating})")
        log.info(f"[Lichess] We are: {'White' if self._player_is_white else 'Black'}")
        
        # Now in playing state
        self._set_state(LichessGameState.PLAYING)
        
        # Update GameManager with game info
        if self.manager:
            white_str = f"{self._white_player}({self._white_rating})"
            black_str = f"{self._black_player}({self._black_rating})"
            self.manager.set_game_info("", "", "", white_str, black_str)
        
        self._update_display()
    
    def _process_time_update(self, state: dict):
        """Process clock time update from game state.
        
        Args:
            state: State dict with wtime/btime fields
        """
        try:
            # Time can be in milliseconds or datetime format
            wtime = state.get('wtime')
            btime = state.get('btime')
            
            if wtime is not None:
                if isinstance(wtime, int):
                    self._white_time = wtime // 1000
                # Handle datetime format if needed
            
            if btime is not None:
                if isinstance(btime, int):
                    self._black_time = btime // 1000
            
            # Update GameManager clock
            if self.manager:
                self.manager.set_clock(self._white_time, self._black_time)
                
        except Exception as e:
            log.warning(f"[Lichess] Error processing time update: {e}")
    
    def _check_for_remote_move(self):
        """Check if there's a new remote move to process.
        
        Compares current move list with last processed to detect
        opponent's moves that need to be executed on the physical board.
        """
        if not self._remote_moves:
            return
        
        # Get the last move from the move string
        moves_list = self._remote_moves.split()
        if not moves_list:
            return
        
        last_move = moves_list[-1].lower()
        
        # Skip if we already processed this move
        if self._remote_moves == self._last_processed_moves:
            return
        
        self._last_processed_moves = self._remote_moves
        
        # Only process if it's opponent's move (not our move echoed back)
        if self._is_player_turn():
            log.debug(f"[Lichess] Move {last_move} is our move, ignoring")
            return
        
        log.info(f"[Lichess] Remote move received: {last_move}")
        
        # Push to GameManager for execution on physical board
        if self.manager:
            self.manager.computer_move(last_move, forced=True)
    
    def _check_game_status(self, status: str, state: dict):
        """Check game status and handle game end conditions.
        
        Args:
            status: Status string from Lichess
            state: Full game state dict
        """
        status = str(status).lower()
        
        terminal_states = ['mate', 'resign', 'draw', 'aborted', 'outoftime', 'timeout', 'stalemate']
        
        if status in terminal_states:
            log.info(f"[Lichess] Game ended with status: {status}")
            self._set_state(LichessGameState.GAME_OVER)
            
            winner = state.get('winner', '')
            self._display_game_over(status, winner)
            
            # Notify GameManager
            if self.manager:
                self.manager.event_callback(f"Termination.{status.upper()}")
    
    # =========================================================================
    # Game Actions
    # =========================================================================
    
    def _resign_game(self):
        """Resign the current game."""
        if not self._game_id or not self._client:
            return
        
        log.info("[Lichess] Resigning game")
        try:
            self._client.board.resign_game(self._game_id)
        except Exception as e:
            log.error(f"[Lichess] Failed to resign: {e}")
    
    def _offer_draw(self):
        """Offer a draw to the opponent."""
        if not self._game_id or not self._client:
            return
        
        log.info("[Lichess] Offering draw")
        try:
            self._client.board.offer_draw(self._game_id)
        except Exception as e:
            log.error(f"[Lichess] Failed to offer draw: {e}")
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def _is_player_turn(self) -> bool:
        """Check if it's currently the player's turn.
        
        Returns:
            True if it's the local player's turn to move.
        """
        if self._player_is_white is None:
            return False
        
        if self._player_is_white:
            return self._current_turn_is_white
        else:
            return not self._current_turn_is_white
    
    def _set_state(self, new_state: LichessGameState):
        """Thread-safe state transition.
        
        Args:
            new_state: New state to transition to
        """
        with self._state_lock:
            old_state = self._state
            self._state = new_state
            log.info(f"[Lichess] State: {old_state.name} -> {new_state.name}")
    
    def _handle_termination(self, event: str):
        """Handle game termination event.
        
        Args:
            event: Termination event string (e.g., "Termination.CHECKMATE")
        """
        termination_type = event.replace("Termination.", "")
        log.info(f"[Lichess] Game terminated: {termination_type}")
        self._set_state(LichessGameState.GAME_OVER)
    
    # =========================================================================
    # Display Methods
    # =========================================================================
    
    def _display_status(self, text: str):
        """Display a status message.
        
        Args:
            text: Status text to display
        """
        if self._display_callback:
            self._display_callback({0: text})
        log.info(f"[Lichess] Status: {text}")
    
    def _display_error(self, line1: str, line2: str = ""):
        """Display an error message.
        
        Args:
            line1: First line of error
            line2: Optional second line
        """
        if self._display_callback:
            self._display_callback({0: line1, 1: line2})
        log.error(f"[Lichess] Error: {line1} {line2}")
    
    def _update_display(self):
        """Update the display with current game state."""
        if not self._display_callback:
            return
        
        lines = {
            1: self._black_player,
            2: f"({self._black_rating})" if self._black_rating else "",
            10: self._white_player,
            11: f"({self._white_rating})" if self._white_rating else "",
        }
        
        self._display_callback(lines)
    
    def _update_turn_display(self):
        """Update the turn indicator on display."""
        if not self._display_callback:
            return
        
        if self._is_player_turn():
            turn_text = "Your turn"
        else:
            turn_text = "Opponent turn"
        
        if self._current_turn_is_white:
            turn_text = f"White - {turn_text}"
        else:
            turn_text = f"Black - {turn_text}"
        
        self._display_callback({12: turn_text})
    
    def _display_game_over(self, status: str, winner: str):
        """Display game over information.
        
        Args:
            status: Game end status
            winner: Winner color or empty for draw
        """
        if self._display_callback:
            lines = {
                0: status.upper(),
                12: f"{winner} wins" if winner else "Draw",
            }
            self._display_callback(lines)
    
    # =========================================================================
    # Properties
    # =========================================================================
    
    @property
    def board_flip(self) -> bool:
        """Whether the board display should be flipped.
        
        Returns:
            True if playing as black (board should be flipped).
        """
        return self._board_flip
    
    @property
    def game_id(self) -> Optional[str]:
        """Current game ID.
        
        Returns:
            Lichess game ID or None if no game active.
        """
        return self._game_id
    
    @property
    def state(self) -> LichessGameState:
        """Current emulator state.
        
        Returns:
            Current LichessGameState.
        """
        with self._state_lock:
            return self._state
