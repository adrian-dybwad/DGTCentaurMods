# UCI Engine Opponent
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Implements a chess opponent using a UCI engine (Stockfish, Maia, etc.).
# Extracted from ProtocolManager to follow the Opponent abstraction.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

import configparser
import os
import pathlib
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Callable

import chess
import chess.engine

from DGTCentaurMods.board.logging import log
from .base import Opponent, OpponentConfig, OpponentState


@dataclass
class EngineConfig(OpponentConfig):
    """Configuration for UCI engine opponent.
    
    Attributes:
        name: Engine name for display.
        time_limit_seconds: Maximum time per move.
        engine_name: Name of the engine executable (e.g., "stockfish_pi").
        engine_path: Full path to engine executable. If None, searches in
                    standard locations (engines/ folder).
        elo_section: Section name from .uci config file for ELO settings.
        uci_options: Additional UCI options to configure.
    """
    engine_name: str = "stockfish_pi"
    engine_path: Optional[str] = None
    elo_section: str = "Default"
    uci_options: Dict[str, str] = field(default_factory=dict)


class EngineOpponent(Opponent):
    """UCI chess engine opponent.
    
    Plays against the user using a UCI-compatible chess engine like
    Stockfish, Maia, CT800, etc.
    
    The engine runs as a subprocess and communicates via UCI protocol.
    Engine initialization is done in a background thread to avoid
    blocking game startup.
    
    Thread Safety:
    - start() spawns initialization thread
    - get_move() spawns thinking thread
    - stop() waits for threads to complete
    """
    
    def __init__(self, config: Optional[EngineConfig] = None):
        """Initialize the engine opponent.
        
        Args:
            config: Engine configuration. If None, uses defaults.
        """
        super().__init__(config or EngineConfig())
        self._engine_config: EngineConfig = self._config
        
        # Engine process handle
        self._engine: Optional[chess.engine.SimpleEngine] = None
        
        # Threading
        self._init_thread: Optional[threading.Thread] = None
        self._think_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._thinking = False
        
        # UCI options loaded from config file
        self._uci_options: Dict[str, str] = {}
    
    @property
    def engine_name(self) -> str:
        """Name of the engine."""
        return self._engine_config.engine_name
    
    @property
    def elo_section(self) -> str:
        """ELO section being used."""
        return self._engine_config.elo_section
    
    def start(self) -> bool:
        """Initialize and start the engine.
        
        Spawns a background thread to load the engine, allowing the
        game to start immediately while the engine initializes.
        
        Returns:
            True if initialization started, False on immediate error.
        """
        if self._state not in (OpponentState.UNINITIALIZED, OpponentState.STOPPED):
            log.warning(f"[EngineOpponent] Cannot start - already in state {self._state}")
            return False
        
        self._set_state(OpponentState.INITIALIZING)
        self._report_status(f"Loading {self.engine_name}...")
        
        # Find engine path
        engine_path = self._resolve_engine_path()
        if not engine_path:
            self._set_state(OpponentState.ERROR, f"Engine not found: {self.engine_name}")
            return False
        
        # Load UCI options from config file (synchronous, fast)
        uci_file_path = str(engine_path) + ".uci"
        self._load_uci_options(uci_file_path)
        
        # Start engine initialization in background
        def _init_engine():
            try:
                log.info(f"[EngineOpponent] Starting engine: {engine_path}")
                engine = chess.engine.SimpleEngine.popen_uci(str(engine_path))
                
                # Apply UCI options
                if self._uci_options:
                    log.info(f"[EngineOpponent] Configuring with options: {self._uci_options}")
                    engine.configure(self._uci_options)
                
                with self._lock:
                    self._engine = engine
                    self._set_state(OpponentState.READY)
                
                log.info(f"[EngineOpponent] Engine ready: {self.engine_name} @ {self.elo_section}")
                self._report_status(f"{self.engine_name} ready")
                
            except Exception as e:
                log.error(f"[EngineOpponent] Failed to initialize engine: {e}")
                self._set_state(OpponentState.ERROR, str(e))
        
        self._init_thread = threading.Thread(
            target=_init_engine,
            name=f"engine-init-{self.engine_name}",
            daemon=True
        )
        self._init_thread.start()
        
        return True
    
    def stop(self) -> None:
        """Stop the engine and release resources."""
        log.info(f"[EngineOpponent] Stopping engine: {self.engine_name}")
        
        # Wait for init thread if running
        if self._init_thread and self._init_thread.is_alive():
            self._init_thread.join(timeout=1.0)
        
        # Close engine
        with self._lock:
            if self._engine:
                try:
                    self._engine.quit()
                    log.info(f"[EngineOpponent] Engine closed: {self.engine_name}")
                except Exception as e:
                    log.debug(f"[EngineOpponent] Error closing engine: {e}")
                self._engine = None
        
        self._set_state(OpponentState.STOPPED)
    
    def get_move(self, board: chess.Board) -> Optional[chess.Move]:
        """Compute and return the engine's move.
        
        Spawns a background thread for thinking. The move is delivered
        via the move_callback when ready.
        
        Args:
            board: Current chess position.
        
        Returns:
            None (move delivered asynchronously via callback).
        """
        if self._state != OpponentState.READY:
            log.warning(f"[EngineOpponent] get_move called but state is {self._state}")
            return None
        
        if self._thinking:
            log.debug("[EngineOpponent] Already thinking, ignoring duplicate call")
            return None
        
        with self._lock:
            if not self._engine:
                log.warning("[EngineOpponent] Engine not initialized")
                return None
        
        self._thinking = True
        self._set_state(OpponentState.THINKING)
        
        def _think():
            try:
                log.info(f"[EngineOpponent] {self.engine_name} thinking...")
                
                # Re-apply UCI options before each move (some engines reset)
                with self._lock:
                    if self._engine and self._uci_options:
                        self._engine.configure(self._uci_options)
                
                # Copy board to avoid race conditions
                board_copy = board.copy()
                
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
                    log.info(f"[EngineOpponent] {self.engine_name} move: {move.uci()}")
                    if self._move_callback:
                        self._move_callback(move)
                else:
                    log.warning("[EngineOpponent] Engine returned no move")
                    
            except Exception as e:
                log.error(f"[EngineOpponent] Error getting move: {e}")
                import traceback
                traceback.print_exc()
            finally:
                self._thinking = False
                if self._state == OpponentState.THINKING:
                    self._set_state(OpponentState.READY)
        
        self._think_thread = threading.Thread(
            target=_think,
            name=f"engine-think-{self.engine_name}",
            daemon=True
        )
        self._think_thread.start()
        
        return None  # Move delivered via callback
    
    def on_player_move(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that the player made a move.
        
        Engine doesn't need to track this - it uses the board state
        directly when computing moves.
        """
        log.debug(f"[EngineOpponent] Player moved: {move.uci()}")
    
    def on_new_game(self) -> None:
        """Notification that a new game is starting.
        
        Resets engine state for the new game.
        """
        log.info(f"[EngineOpponent] New game - resetting {self.engine_name}")
        # The chess.engine library handles ucinewgame automatically
        # but we could explicitly send it if needed
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notification that a takeback occurred.
        
        Engine handles this automatically via the board state.
        """
        log.debug("[EngineOpponent] Takeback - engine will use new position")
    
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
        
        Returns:
            Path to engine executable, or None if not found.
        """
        if self._engine_config.engine_path:
            path = pathlib.Path(self._engine_config.engine_path)
            if path.exists():
                return path
            log.warning(f"[EngineOpponent] Configured path not found: {path}")
        
        # Search standard locations
        base_path = pathlib.Path(__file__).parent.parent
        engine_path = base_path / "engines" / self._engine_config.engine_name
        
        if engine_path.exists():
            return engine_path
        
        log.error(f"[EngineOpponent] Engine not found: {engine_path}")
        return None
    
    def _load_uci_options(self, uci_file_path: str) -> None:
        """Load UCI options from configuration file.
        
        Args:
            uci_file_path: Path to the .uci config file.
        """
        if not os.path.exists(uci_file_path):
            log.warning(f"[EngineOpponent] UCI file not found: {uci_file_path}")
            return
        
        config = configparser.ConfigParser()
        config.optionxform = str  # Preserve case for UCI option names
        config.read(uci_file_path)
        
        section = self._engine_config.elo_section
        
        if config.has_section(section):
            log.info(f"[EngineOpponent] Loading UCI options from section: {section}")
            for key, value in config.items(section):
                self._uci_options[key] = value
            
            # Filter out non-UCI metadata fields
            non_uci_fields = ['Description']
            self._uci_options = {
                k: v for k, v in self._uci_options.items()
                if k not in non_uci_fields
            }
            log.info(f"[EngineOpponent] UCI options: {self._uci_options}")
        else:
            log.warning(f"[EngineOpponent] Section '{section}' not found in {uci_file_path}")
            # Fall back to DEFAULT section
            if config.has_section("DEFAULT"):
                for key, value in config.items("DEFAULT"):
                    if key not in ['Description']:
                        self._uci_options[key] = value
        
        # Merge with explicitly configured options (override file settings)
        self._uci_options.update(self._engine_config.uci_options)


def create_engine_opponent(
    engine_name: str = "stockfish_pi",
    elo_section: str = "Default",
    time_limit: float = 5.0
) -> EngineOpponent:
    """Factory function to create an engine opponent.
    
    Convenience function for common use case.
    
    Args:
        engine_name: Name of the engine (e.g., "stockfish_pi", "maia").
        elo_section: ELO section from .uci config file.
        time_limit: Maximum thinking time per move in seconds.
    
    Returns:
        Configured EngineOpponent instance.
    """
    config = EngineConfig(
        name=f"{engine_name} ({elo_section})",
        time_limit_seconds=time_limit,
        engine_name=engine_name,
        elo_section=elo_section,
    )
    
    return EngineOpponent(config)
