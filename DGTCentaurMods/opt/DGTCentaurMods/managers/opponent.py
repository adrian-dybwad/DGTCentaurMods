# Opponent Manager
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Provides a unified interface for opponent management. The game coordinator
# (universal.py) works with this manager without needing to know the specific
# opponent type (engine, Lichess, human).
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Callable

import chess

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.opponents import (
    Opponent,
    OpponentState,
    EngineOpponent,
    EngineConfig,
    HumanOpponent,
    HumanConfig,
    create_engine_opponent,
)


class OpponentType(Enum):
    """Types of opponents supported by the manager."""
    HUMAN = auto()      # Two-player mode (null opponent)
    ENGINE = auto()     # Local UCI chess engine
    LICHESS = auto()    # Lichess online play


@dataclass
class OpponentManagerConfig:
    """Configuration for creating an opponent.
    
    This is the unified configuration that the game coordinator passes
    to the OpponentManager. The manager determines the opponent type
    and creates the appropriate implementation.
    
    Attributes:
        opponent_type: Type of opponent to create.
        engine_name: Name of UCI engine (for ENGINE type).
        elo_section: ELO section from .uci config file (for ENGINE type).
        time_limit: Time limit for opponent moves in seconds.
        lichess_mode: Game mode for Lichess (for LICHESS type).
        lichess_time_minutes: Time control in minutes (for LICHESS type).
        lichess_increment_seconds: Increment in seconds (for LICHESS type).
        lichess_rated: Whether game is rated (for LICHESS type).
        lichess_color_preference: Preferred color 'white', 'black', or 'random'.
        lichess_game_id: Game ID to resume (for ONGOING mode).
        lichess_challenge_id: Challenge ID to accept (for CHALLENGE mode).
        lichess_challenge_direction: 'in' for incoming, 'out' for outgoing.
    """
    opponent_type: OpponentType = OpponentType.HUMAN
    
    # Engine configuration
    engine_name: str = "stockfish_pi"
    elo_section: str = "Default"
    time_limit: float = 5.0
    
    # Lichess configuration
    lichess_mode: str = "NEW"  # NEW, ONGOING, CHALLENGE
    lichess_time_minutes: int = 10
    lichess_increment_seconds: int = 5
    lichess_rated: bool = False
    lichess_color_preference: str = "random"
    lichess_game_id: str = ""
    lichess_challenge_id: str = ""
    lichess_challenge_direction: str = "in"


class OpponentManager:
    """Manages opponent lifecycle and provides unified interface.
    
    The game coordinator creates an OpponentManager with configuration,
    then interacts with it through a standard interface without needing
    to know the specific opponent type.
    
    This follows the Facade pattern - hiding opponent implementation
    details behind a simple interface.
    
    Example:
        # In universal.py
        config = OpponentManagerConfig(
            opponent_type=OpponentType.ENGINE,
            engine_name="stockfish_pi",
            elo_section="1500"
        )
        opponent_mgr = OpponentManager(
            config,
            move_callback=on_opponent_move,
            status_callback=lambda msg: log.info(msg)
        )
        opponent_mgr.start()
        
        # Later, when it's opponent's turn:
        opponent_mgr.request_move(board)
        
        # On cleanup:
        opponent_mgr.stop()
    """
    
    def __init__(
        self,
        config: OpponentManagerConfig,
        move_callback: Optional[Callable[[chess.Move], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        clock_callback: Optional[Callable[[int, int], None]] = None,
        game_info_callback: Optional[Callable[[str, str, str, str], None]] = None,
        game_connected_callback: Optional[Callable[[], None]] = None,
    ):
        """Initialize the opponent manager.
        
        Args:
            config: Configuration specifying opponent type and parameters.
            move_callback: Called when opponent has a move ready.
            status_callback: Called with status messages (e.g., "Thinking...").
            clock_callback: Called with clock updates (Lichess only).
            game_info_callback: Called with player info (Lichess only).
            game_connected_callback: Called when game connects (Lichess only).
        """
        self._config = config
        self._opponent: Optional[Opponent] = None
        self._move_callback = move_callback
        self._status_callback = status_callback
        self._clock_callback = clock_callback
        self._game_info_callback = game_info_callback
        self._game_connected_callback = game_connected_callback
        
        self._create_opponent()
        self._wire_callbacks()
    
    def _create_opponent(self) -> None:
        """Create the appropriate opponent based on configuration."""
        if self._config.opponent_type == OpponentType.HUMAN:
            self._opponent = HumanOpponent()
            log.info("[OpponentManager] Created human opponent (two-player mode)")
            
        elif self._config.opponent_type == OpponentType.ENGINE:
            self._opponent = create_engine_opponent(
                engine_name=self._config.engine_name,
                elo_section=self._config.elo_section,
                time_limit=self._config.time_limit
            )
            log.info(f"[OpponentManager] Created engine opponent: "
                    f"{self._config.engine_name} @ {self._config.elo_section}")
            
        elif self._config.opponent_type == OpponentType.LICHESS:
            self._create_lichess_opponent()
        
        else:
            raise ValueError(f"Unknown opponent type: {self._config.opponent_type}")
    
    def _create_lichess_opponent(self) -> None:
        """Create Lichess opponent from configuration.
        
        Imports Lichess classes lazily to avoid loading berserk when not needed.
        """
        from DGTCentaurMods.opponents.lichess import (
            LichessOpponent,
            LichessConfig,
            LichessGameMode
        )
        
        # Map string mode to enum
        mode_map = {
            "NEW": LichessGameMode.NEW,
            "ONGOING": LichessGameMode.ONGOING,
            "CHALLENGE": LichessGameMode.CHALLENGE,
        }
        mode = mode_map.get(self._config.lichess_mode, LichessGameMode.NEW)
        
        lichess_config = LichessConfig(
            name="Lichess",
            mode=mode,
            time_minutes=self._config.lichess_time_minutes,
            increment_seconds=self._config.lichess_increment_seconds,
            rated=self._config.lichess_rated,
            color_preference=self._config.lichess_color_preference,
            game_id=self._config.lichess_game_id,
            challenge_id=self._config.lichess_challenge_id,
            challenge_direction=self._config.lichess_challenge_direction,
        )
        
        self._opponent = LichessOpponent(lichess_config)
        log.info(f"[OpponentManager] Created Lichess opponent (mode: {mode.name})")
    
    def _wire_callbacks(self) -> None:
        """Wire all callbacks to the opponent.
        
        Called after opponent creation and when callbacks are set.
        """
        if not self._opponent:
            return
        
        if self._move_callback:
            self._opponent.set_move_callback(self._move_callback)
        if self._status_callback:
            self._opponent.set_status_callback(self._status_callback)
        
        # Lichess-specific callbacks
        if self._config.opponent_type == OpponentType.LICHESS:
            from DGTCentaurMods.opponents.lichess import LichessOpponent
            if isinstance(self._opponent, LichessOpponent):
                if self._clock_callback:
                    self._opponent.set_clock_callback(self._clock_callback)
                if self._game_info_callback:
                    self._opponent.set_game_info_callback(self._game_info_callback)
                if self._game_connected_callback:
                    self._opponent.set_on_game_connected(self._game_connected_callback)
    
    # =========================================================================
    # Callback Setters - Can also be called after construction
    # =========================================================================
    
    def set_move_callback(self, callback: Callable[[chess.Move], None]) -> None:
        """Set callback for when opponent makes a move.
        
        Args:
            callback: Function(move) called when opponent has a move ready.
        """
        self._move_callback = callback
        if self._opponent:
            self._opponent.set_move_callback(callback)
    
    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for opponent status messages.
        
        Args:
            callback: Function(message) for status updates (e.g., "Thinking...").
        """
        self._status_callback = callback
        if self._opponent:
            self._opponent.set_status_callback(callback)
    
    def set_clock_callback(self, callback: Callable[[int, int], None]) -> None:
        """Set callback for clock updates (Lichess only).
        
        Args:
            callback: Function(white_time, black_time) in seconds.
        """
        self._clock_callback = callback
        if self._opponent and self._config.opponent_type == OpponentType.LICHESS:
            from DGTCentaurMods.opponents.lichess import LichessOpponent
            if isinstance(self._opponent, LichessOpponent):
                self._opponent.set_clock_callback(callback)
    
    def set_game_info_callback(self, callback: Callable[[str, str, str, str], None]) -> None:
        """Set callback for game info (Lichess only).
        
        Args:
            callback: Function(white_player, white_rating, black_player, black_rating).
        """
        self._game_info_callback = callback
        if self._opponent and self._config.opponent_type == OpponentType.LICHESS:
            from DGTCentaurMods.opponents.lichess import LichessOpponent
            if isinstance(self._opponent, LichessOpponent):
                self._opponent.set_game_info_callback(callback)
    
    def set_game_connected_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for when game is connected (Lichess only).
        
        Args:
            callback: Function() called when game transitions to playing state.
        """
        self._game_connected_callback = callback
        if self._opponent and self._config.opponent_type == OpponentType.LICHESS:
            from DGTCentaurMods.opponents.lichess import LichessOpponent
            if isinstance(self._opponent, LichessOpponent):
                self._opponent.set_on_game_connected(callback)
    
    # =========================================================================
    # Lifecycle Methods
    # =========================================================================
    
    def start(self) -> bool:
        """Start the opponent.
        
        Returns:
            True if opponent started successfully.
        """
        if not self._opponent:
            log.error("[OpponentManager] No opponent to start")
            return False
        
        return self._opponent.start()
    
    def stop(self) -> None:
        """Stop the opponent and release resources."""
        if self._opponent:
            self._opponent.stop()
    
    def on_new_game(self) -> None:
        """Notify opponent of new game."""
        if self._opponent:
            self._opponent.on_new_game()
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notify opponent of takeback.
        
        Args:
            board: Current board position after takeback.
        """
        if self._opponent:
            self._opponent.on_takeback(board)
    
    # =========================================================================
    # Game Flow Methods
    # =========================================================================
    
    def request_move(self, board: chess.Board) -> None:
        """Request a move from the opponent.
        
        The move will be delivered asynchronously via the move callback.
        
        Args:
            board: Current board position.
        """
        if self._opponent:
            self._opponent.get_move(board)
    
    def notify_player_move(self, move: chess.Move, board: chess.Board) -> None:
        """Notify opponent of player's move.
        
        For stateful opponents (like Lichess) that need to track moves.
        
        Args:
            move: The player's move.
            board: Board position after the move.
        """
        if self._opponent:
            self._opponent.on_player_move(move, board)
    
    # =========================================================================
    # Lichess-Specific Methods (encapsulated)
    # =========================================================================
    
    def resign(self) -> None:
        """Resign the current game (Lichess only)."""
        if self._opponent and self._config.opponent_type == OpponentType.LICHESS:
            from DGTCentaurMods.opponents.lichess import LichessOpponent
            if isinstance(self._opponent, LichessOpponent):
                self._opponent.resign_game()
    
    def abort(self) -> None:
        """Abort the current game (Lichess only)."""
        if self._opponent and self._config.opponent_type == OpponentType.LICHESS:
            from DGTCentaurMods.opponents.lichess import LichessOpponent
            if isinstance(self._opponent, LichessOpponent):
                self._opponent.abort_game()
    
    def offer_draw(self) -> None:
        """Offer a draw (Lichess only)."""
        if self._opponent and self._config.opponent_type == OpponentType.LICHESS:
            from DGTCentaurMods.opponents.lichess import LichessOpponent
            if isinstance(self._opponent, LichessOpponent):
                self._opponent.offer_draw()
    
    # =========================================================================
    # Properties
    # =========================================================================
    
    @property
    def is_ready(self) -> bool:
        """Check if opponent is ready to play."""
        return self._opponent.is_ready if self._opponent else False
    
    @property
    def is_lichess(self) -> bool:
        """Check if opponent is Lichess (for UI-specific handling)."""
        return self._config.opponent_type == OpponentType.LICHESS
    
    @property
    def is_human(self) -> bool:
        """Check if opponent is human (two-player mode)."""
        return self._config.opponent_type == OpponentType.HUMAN
    
    @property
    def is_engine(self) -> bool:
        """Check if opponent is a local engine."""
        return self._config.opponent_type == OpponentType.ENGINE
    
    @property
    def board_flip(self) -> bool:
        """Get whether board should be flipped (True if player is black).
        
        For Lichess, this is determined by the server.
        For local games, this is based on player color setting.
        """
        if self._opponent and self._config.opponent_type == OpponentType.LICHESS:
            from DGTCentaurMods.opponents.lichess import LichessOpponent
            if isinstance(self._opponent, LichessOpponent):
                return self._opponent.board_flip
        return False
    
    @property
    def supports_takeback(self) -> bool:
        """Check if opponent supports takeback."""
        return self._opponent.supports_takeback() if self._opponent else False
    
    def get_info(self) -> dict:
        """Get information about the current opponent."""
        if self._opponent:
            return self._opponent.get_info()
        return {'type': 'unknown', 'name': 'Unknown'}
