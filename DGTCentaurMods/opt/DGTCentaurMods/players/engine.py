# UCI Engine Player
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# A player that uses a UCI chess engine (Stockfish, Maia, CT800, etc.)
# to compute moves. The engine runs as a subprocess and communicates
# via the UCI protocol.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

import configparser
import os
import pathlib
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict

import chess
import chess.engine

from DGTCentaurMods.board.logging import log
from .base import Player, PlayerConfig, PlayerState, PlayerType


@dataclass
class EnginePlayerConfig(PlayerConfig):
    """Configuration for UCI engine player.
    
    Attributes:
        name: Engine name for display.
        color: The color this player plays.
        time_limit_seconds: Maximum time per move.
        engine_name: Name of the engine executable (e.g., "stockfish_pi").
        engine_path: Full path to engine executable. If None, searches in
                    standard locations (engines/ folder).
        elo_section: Section name from .uci config file for ELO settings.
        uci_options: Additional UCI options to configure.
    """
    time_limit_seconds: float = 5.0
    engine_name: str = "stockfish_pi"
    engine_path: Optional[str] = None
    elo_section: str = "Default"
    uci_options: Dict[str, str] = field(default_factory=dict)


class EnginePlayer(Player):
    """A player that uses a UCI chess engine to compute moves.
    
    The engine runs as a subprocess and communicates via UCI protocol.
    Engine initialization is done in a background thread to avoid
    blocking game startup.
    
    Move Flow:
    1. request_move() - engine starts computing in background
    2. Engine finishes - stores pending_move, notifies for LED display
    3. on_piece_event() - forms move from lift/place
    4. If move matches pending_move - submits via callback
    5. If move doesn't match - board needs correction, no submission
    
    Thread Safety:
    - start() spawns initialization thread
    - request_move() spawns thinking thread
    - stop() waits for threads to complete
    """
    
    def __init__(self, config: Optional[EnginePlayerConfig] = None):
        """Initialize the engine player.
        
        Args:
            config: Engine configuration. If None, uses defaults.
        """
        super().__init__(config or EnginePlayerConfig())
        self._engine_config: EnginePlayerConfig = self._config
        
        # Engine process handle
        self._engine: Optional[chess.engine.SimpleEngine] = None
        
        # Threading
        self._init_thread: Optional[threading.Thread] = None
        self._think_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._thinking = False
        
        # UCI options loaded from config file
        self._uci_options: Dict[str, str] = {}
        
        # Pending move from engine computation (for LED display)
        self._pending_move: Optional[chess.Move] = None
    
    @property
    def player_type(self) -> PlayerType:
        """Engine player type."""
        return PlayerType.ENGINE
    
    @property
    def engine_name(self) -> str:
        """Name of the engine."""
        return self._engine_config.engine_name
    
    @property
    def elo_section(self) -> str:
        """ELO section being used."""
        return self._engine_config.elo_section
    
    @property
    def pending_move(self) -> Optional[chess.Move]:
        """The computed move waiting to be executed on the board."""
        return self._pending_move
    
    def start(self) -> bool:
        """Initialize and start the engine.
        
        Spawns a background thread to load the engine, allowing the
        game to start immediately while the engine initializes.
        
        Returns:
            True if initialization started, False on immediate error.
        """
        if self._state not in (PlayerState.UNINITIALIZED, PlayerState.STOPPED):
            log.warning(f"[EnginePlayer] Cannot start - already in state {self._state}")
            return False
        
        self._set_state(PlayerState.INITIALIZING)
        self._report_status(f"Loading {self.engine_name}...")
        
        # Find engine path
        engine_path = self._resolve_engine_path()
        if not engine_path:
            self._set_state(PlayerState.ERROR, f"Engine not found: {self.engine_name}")
            return False
        
        # Load UCI options from config file (synchronous, fast)
        uci_file_path = str(engine_path) + ".uci"
        self._load_uci_options(uci_file_path)
        
        # Start engine initialization in background
        def _init_engine():
            try:
                log.info(f"[EnginePlayer] Starting engine: {engine_path}")
                engine = chess.engine.SimpleEngine.popen_uci(str(engine_path))
                
                # Apply UCI options
                if self._uci_options:
                    log.info(f"[EnginePlayer] Configuring with options: {self._uci_options}")
                    engine.configure(self._uci_options)
                
                with self._lock:
                    self._engine = engine
                
                color_name = 'White' if self._color == chess.WHITE else 'Black' if self._color == chess.BLACK else ''
                log.info(f"[EnginePlayer] {color_name} engine ready: {self.engine_name} @ {self.elo_section}")
                self._report_status(f"{self.engine_name} ready")
                
                # Set state OUTSIDE lock - _set_state may call _do_request_move
                # which needs to acquire the lock
                self._set_state(PlayerState.READY)
                
            except Exception as e:
                log.error(f"[EnginePlayer] Failed to initialize engine: {e}")
                self._set_state(PlayerState.ERROR, str(e))
        
        self._init_thread = threading.Thread(
            target=_init_engine,
            name=f"engine-init-{self.engine_name}",
            daemon=True
        )
        self._init_thread.start()
        
        return True
    
    def stop(self) -> None:
        """Stop the engine and release resources."""
        log.info(f"[EnginePlayer] Stopping engine: {self.engine_name}")
        
        # Wait for init thread if running
        if self._init_thread and self._init_thread.is_alive():
            self._init_thread.join(timeout=1.0)
        
        # Close engine
        with self._lock:
            if self._engine:
                try:
                    self._engine.quit()
                    log.info(f"[EnginePlayer] Engine closed: {self.engine_name}")
                except Exception as e:
                    log.debug(f"[EnginePlayer] Error closing engine: {e}")
                self._engine = None
        
        self._set_state(PlayerState.STOPPED)
    
    def _do_request_move(self, board: chess.Board) -> None:
        """Request the engine to compute a move.
        
        Spawns a background thread for thinking. When done, stores the
        pending move and notifies via pending_move_callback for LED display.
        The actual move submission happens via on_piece_event.
        
        Args:
            board: Current chess position.
        """
        if self._thinking:
            log.debug("[EnginePlayer] Already thinking, ignoring duplicate call")
            return
        
        # If we already have a pending move waiting for execution, don't restart
        if self._pending_move is not None:
            log.debug(f"[EnginePlayer] Already have pending move {self._pending_move.uci()}, ignoring request")
            return
        
        with self._lock:
            if not self._engine:
                log.warning("[EnginePlayer] Engine not initialized")
                return
        
        # Reset state for new turn
        self._lifted_squares = []
        
        self._thinking = True
        self._set_state(PlayerState.THINKING)
        
        # Copy board immediately to capture current state
        board_copy = board.copy()
        
        def _think():
            try:
                log.info(f"[EnginePlayer] {self.engine_name} thinking...")
                
                # Re-apply UCI options before each move (some engines reset)
                with self._lock:
                    if self._engine and self._uci_options:
                        self._engine.configure(self._uci_options)
                
                # Get engine move
                time_limit = self._engine_config.time_limit_seconds
                with self._lock:
                    if self._engine:
                        result = self._engine.play(
                            board_copy,
                            chess.engine.Limit(time=time_limit)
                        )
                        move = result.move
                    else:
                        move = None
                
                if move:
                    log.info(f"[EnginePlayer] {self.engine_name} computed: {move.uci()}")
                    self._pending_move = move
                    
                    # Notify for LED display
                    if self._pending_move_callback:
                        self._pending_move_callback(move)
                else:
                    log.warning("[EnginePlayer] Engine returned no move")
                    
            except Exception as e:
                log.error(f"[EnginePlayer] Error getting move: {e}")
                import traceback
                traceback.print_exc()
            finally:
                self._thinking = False
                if self._state == PlayerState.THINKING:
                    self._set_state(PlayerState.READY)
        
        self._think_thread = threading.Thread(
            target=_think,
            name=f"engine-think-{self.engine_name}",
            daemon=True
        )
        self._think_thread.start()
    
    def _on_move_formed(self, move: chess.Move) -> None:
        """Validate formed move matches engine's computed move.
        
        Only submits if the move matches the pending move. If it doesn't
        match, the board state is wrong and needs correction.
        
        Handles destination-only moves (from_square == to_square) which indicate
        a missed lift event. If the destination matches the pending move's to_square,
        we trust the move was executed correctly.
        
        Args:
            move: The formed move from piece events.
        """
        log.debug(f"[EnginePlayer] Move formed: {move.uci()}")
        
        if self._pending_move is None:
            # Engine still computing - user moved pieces prematurely
            log.warning(f"[EnginePlayer] Move formed but no pending move - engine still thinking")
            self._report_error("move_mismatch")
            return
        
        # Handle destination-only move (missed lift event)
        # If from_square == to_square and matches pending move's to_square, trust it
        if move.from_square == move.to_square:
            if move.to_square == self._pending_move.to_square:
                log.warning(f"[EnginePlayer] MISSED LIFT RECOVERY: Destination-only move to {chess.square_name(move.to_square)} matches pending move's destination")
                if self._move_callback:
                    self._move_callback(self._pending_move)
                return
            else:
                log.warning(f"[EnginePlayer] Destination-only move {chess.square_name(move.to_square)} does not match pending {self._pending_move.uci()}")
                self._report_error("move_mismatch")
                return
        
        # Check if move matches (ignoring promotion - use pending move's promotion)
        if move.from_square == self._pending_move.from_square and \
           move.to_square == self._pending_move.to_square:
            # Match! Submit the pending move (includes promotion if any)
            log.info(f"[EnginePlayer] Move matches pending: {self._pending_move.uci()}")
            if self._move_callback:
                self._move_callback(self._pending_move)
            else:
                log.warning("[EnginePlayer] No move callback set, cannot submit move")
        else:
            # Doesn't match - board needs correction
            log.warning(f"[EnginePlayer] Move {move.uci()} does not match pending {self._pending_move.uci()}")
            self._report_error("move_mismatch")
    
    def on_move_made(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that a move was made.
        
        Clears pending state after a move is executed.
        """
        log.debug(f"[EnginePlayer] Move made: {move.uci()}")
        self._pending_move = None
        self._lifted_squares = []
    
    def on_new_game(self) -> None:
        """Notification that a new game is starting.
        
        Resets engine state for the new game.
        """
        log.info(f"[EnginePlayer] New game - resetting {self.engine_name}")
        # The chess.engine library handles ucinewgame automatically
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notification that a takeback occurred.
        
        Engine handles this automatically via the board state.
        """
        log.debug("[EnginePlayer] Takeback - engine will use new position")
    
    def get_info(self) -> dict:
        """Get information about this engine for display."""
        info = super().get_info()
        info.update({
            'engine': self.engine_name,
            'elo': self.elo_section,
            'description': f"{self.engine_name} @ {self.elo_section}",
        })
        return info
    
    def _resolve_engine_path(self) -> Optional[pathlib.Path]:
        """Find the engine executable.
        
        Searches in standard locations if not explicitly configured.
        Uses paths.get_engine_path() which checks installed location first,
        then falls back to development location.
        
        Returns:
            Path to engine executable, or None if not found.
        """
        if self._engine_config.engine_path:
            path = pathlib.Path(self._engine_config.engine_path)
            if path.exists():
                return path
            log.warning(f"[EnginePlayer] Configured path not found: {path}")
        
        from DGTCentaurMods.paths import get_engine_path
        engine_path = get_engine_path(self._engine_config.engine_name)
        if engine_path:
            return pathlib.Path(engine_path)
        
        log.error(f"[EnginePlayer] Engine not found: {self._engine_config.engine_name}")
        return None
    
    def _load_uci_options(self, uci_file_path: str) -> None:
        """Load UCI options from configuration file.
        
        Args:
            uci_file_path: Path to the .uci config file.
        """
        if not os.path.exists(uci_file_path):
            log.warning(f"[EnginePlayer] UCI file not found: {uci_file_path}")
            return
        
        config = configparser.ConfigParser()
        config.optionxform = str  # Preserve case for UCI option names
        config.read(uci_file_path)
        
        section = self._engine_config.elo_section
        
        if config.has_section(section):
            log.info(f"[EnginePlayer] Loading UCI options from section: {section}")
            for key, value in config.items(section):
                self._uci_options[key] = value
            
            # Filter out non-UCI metadata fields
            non_uci_fields = ['Description']
            self._uci_options = {
                k: v for k, v in self._uci_options.items()
                if k not in non_uci_fields
            }
            log.info(f"[EnginePlayer] UCI options: {self._uci_options}")
        else:
            log.warning(f"[EnginePlayer] Section '{section}' not found in {uci_file_path}")
            # Fall back to DEFAULT section
            if config.has_section("DEFAULT"):
                for key, value in config.items("DEFAULT"):
                    if key not in ['Description']:
                        self._uci_options[key] = value
        
        # Merge with explicitly configured options (override file settings)
        self._uci_options.update(self._engine_config.uci_options)


def create_engine_player(
    color: chess.Color,
    engine_name: str = "stockfish_pi",
    elo_section: str = "Default",
    time_limit: float = 5.0
) -> EnginePlayer:
    """Factory function to create an engine player.
    
    Args:
        color: The color this engine plays (WHITE or BLACK).
        engine_name: Name of the engine (e.g., "stockfish_pi", "maia").
        elo_section: ELO section from .uci config file.
        time_limit: Maximum thinking time per move in seconds.
    
    Returns:
        Configured EnginePlayer instance.
    """
    config = EnginePlayerConfig(
        name=f"{engine_name} ({elo_section})",
        color=color,
        time_limit_seconds=time_limit,
        engine_name=engine_name,
        elo_section=elo_section,
    )
    
    return EnginePlayer(config)
