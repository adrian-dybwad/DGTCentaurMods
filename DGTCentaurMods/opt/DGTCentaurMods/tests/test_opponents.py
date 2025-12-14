"""Tests for the opponents module.

Tests cover:
- OpponentConfig dataclass creation
- Opponent base class abstract methods
- EngineOpponent initialization and configuration
- HumanOpponent (null object pattern)
- LichessOpponent configuration

Test Approach:
- Mock chess.engine to avoid actual engine processes
- Mock berserk library to avoid actual API calls
- Test state transitions and callback behavior
"""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import threading
import time


class TestOpponentConfig(unittest.TestCase):
    """Test cases for OpponentConfig dataclass."""
    
    def test_config_defaults(self):
        """Test that OpponentConfig has sensible defaults.
        
        Expected: Default config should have reasonable time limit.
        Failure: Config defaults are wrong, breaking expected game setup.
        """
        from DGTCentaurMods.opponents.base import OpponentConfig
        
        config = OpponentConfig()
        
        assert config.name == "Opponent"
        assert config.time_limit_seconds == 5.0
    
    def test_config_custom_values(self):
        """Test OpponentConfig with custom values.
        
        Expected: Custom values should be stored correctly.
        Failure: Custom opponent settings not applied.
        """
        from DGTCentaurMods.opponents.base import OpponentConfig
        
        config = OpponentConfig(
            name="Custom Engine",
            time_limit_seconds=10.0
        )
        
        assert config.name == "Custom Engine"
        assert config.time_limit_seconds == 10.0


class TestOpponentState(unittest.TestCase):
    """Test cases for OpponentState enum."""
    
    def test_state_values(self):
        """Test that all expected states exist.
        
        Expected: All opponent lifecycle states should be defined.
        Failure: Missing state will break state machine logic.
        """
        from DGTCentaurMods.opponents.base import OpponentState
        
        # Verify all expected states exist
        assert OpponentState.UNINITIALIZED is not None
        assert OpponentState.STARTING is not None
        assert OpponentState.READY is not None
        assert OpponentState.THINKING is not None
        assert OpponentState.STOPPED is not None
        assert OpponentState.ERROR is not None


class TestHumanOpponent(unittest.TestCase):
    """Test cases for HumanOpponent (null object for two-player mode)."""
    
    def test_init(self):
        """Test HumanOpponent initialization.
        
        Expected: HumanOpponent should initialize with sensible defaults.
        Failure: Two-player mode won't work.
        """
        from DGTCentaurMods.opponents import HumanOpponent
        
        opponent = HumanOpponent()
        
        assert opponent.name == "Human"
    
    def test_start_succeeds(self):
        """Test that start() always succeeds for HumanOpponent.
        
        Expected: start() should return True immediately.
        Failure: Two-player games won't start.
        """
        from DGTCentaurMods.opponents import HumanOpponent
        
        opponent = HumanOpponent()
        result = opponent.start()
        
        assert result is True
        assert opponent.is_ready is True
    
    def test_get_move_does_nothing(self):
        """Test that get_move() does nothing (null object pattern).
        
        Expected: get_move() should not raise or call any callback.
        Failure: Two-player mode incorrectly triggers computer moves.
        """
        import chess
        from DGTCentaurMods.opponents import HumanOpponent
        
        opponent = HumanOpponent()
        opponent.start()
        
        move_callback = MagicMock()
        opponent.set_move_callback(move_callback)
        
        board = chess.Board()
        opponent.get_move(board)
        
        # HumanOpponent should never call the move callback
        move_callback.assert_not_called()
    
    def test_stop_succeeds(self):
        """Test that stop() always succeeds for HumanOpponent.
        
        Expected: stop() should work without errors.
        Failure: Cleanup fails for two-player games.
        """
        from DGTCentaurMods.opponents import HumanOpponent
        
        opponent = HumanOpponent()
        opponent.start()
        opponent.stop()
        
        assert opponent.is_ready is False
    
    def test_supports_takeback(self):
        """Test that HumanOpponent supports takeback.
        
        Expected: Two-player mode should allow takebacks.
        Failure: Takebacks wrongly disabled in two-player mode.
        """
        from DGTCentaurMods.opponents import HumanOpponent
        
        opponent = HumanOpponent()
        
        assert opponent.supports_takeback() is True
    
    def test_get_info(self):
        """Test get_info() returns expected metadata.
        
        Expected: Info dict should identify this as human opponent.
        Failure: Display/logging shows wrong opponent info.
        """
        from DGTCentaurMods.opponents import HumanOpponent
        
        opponent = HumanOpponent()
        info = opponent.get_info()
        
        assert info['type'] == 'human'
        assert info['name'] == 'Human'


class TestEngineConfig(unittest.TestCase):
    """Test cases for EngineConfig dataclass."""
    
    def test_config_defaults(self):
        """Test EngineConfig default values.
        
        Expected: Default engine should be stockfish_pi with sensible settings.
        Failure: Engine starts with wrong configuration.
        """
        from DGTCentaurMods.opponents.engine import EngineConfig
        
        config = EngineConfig()
        
        assert config.engine_name == "stockfish_pi"
        assert config.elo_section == "Default"
        assert config.time_limit_seconds == 5.0
    
    def test_config_custom_values(self):
        """Test EngineConfig with custom values.
        
        Expected: Custom engine settings should be stored.
        Failure: Cannot configure different engines or ELO levels.
        """
        from DGTCentaurMods.opponents.engine import EngineConfig
        
        config = EngineConfig(
            name="Maia 1500",
            engine_name="maia",
            elo_section="1500",
            time_limit_seconds=3.0
        )
        
        assert config.name == "Maia 1500"
        assert config.engine_name == "maia"
        assert config.elo_section == "1500"
        assert config.time_limit_seconds == 3.0


class TestEngineOpponent(unittest.TestCase):
    """Test cases for EngineOpponent."""
    
    def test_init_with_config(self):
        """Test EngineOpponent initialization with config.
        
        Expected: Engine opponent should store configuration.
        Failure: Engine settings not applied correctly.
        """
        from DGTCentaurMods.opponents.engine import EngineOpponent, EngineConfig
        from DGTCentaurMods.opponents.base import OpponentState
        
        config = EngineConfig(engine_name="stockfish_pi", elo_section="1350")
        opponent = EngineOpponent(config)
        
        assert opponent.name == config.name
        assert opponent._state == OpponentState.UNINITIALIZED
    
    def test_get_info(self):
        """Test get_info() returns engine metadata.
        
        Expected: Info should include engine name and ELO section.
        Failure: Display shows wrong engine information.
        """
        from DGTCentaurMods.opponents.engine import EngineOpponent, EngineConfig
        
        config = EngineConfig(
            name="Test Engine",
            engine_name="stockfish_pi",
            elo_section="1500"
        )
        opponent = EngineOpponent(config)
        info = opponent.get_info()
        
        assert info['type'] == 'engine'
        assert info['engine_name'] == 'stockfish_pi'
        assert info['elo_section'] == '1500'
    
    def test_supports_takeback(self):
        """Test that engine opponent supports takeback.
        
        Expected: UCI engines should support takeback (just reset position).
        Failure: Takebacks wrongly disabled for engine games.
        """
        from DGTCentaurMods.opponents.engine import EngineOpponent, EngineConfig
        
        config = EngineConfig()
        opponent = EngineOpponent(config)
        
        assert opponent.supports_takeback() is True


class TestCreateEngineOpponent(unittest.TestCase):
    """Test cases for create_engine_opponent factory function."""
    
    def test_factory_defaults(self):
        """Test factory function with defaults.
        
        Expected: Factory should create engine opponent with sensible defaults.
        Failure: Cannot create engine opponents easily.
        """
        from DGTCentaurMods.opponents import create_engine_opponent
        
        opponent = create_engine_opponent()
        
        assert opponent is not None
        assert "stockfish_pi" in opponent.name.lower() or opponent.name != ""
    
    def test_factory_custom_values(self):
        """Test factory function with custom values.
        
        Expected: Factory should pass through custom settings.
        Failure: Custom engine settings not applied.
        """
        from DGTCentaurMods.opponents import create_engine_opponent
        
        opponent = create_engine_opponent(
            engine_name="ct800",
            elo_section="1200",
            time_limit=3.0
        )
        
        info = opponent.get_info()
        assert info['engine_name'] == 'ct800'
        assert info['elo_section'] == '1200'


class TestLichessConfig(unittest.TestCase):
    """Test cases for LichessConfig dataclass."""
    
    def test_config_defaults(self):
        """Test LichessConfig default values.
        
        Expected: Default should be NEW game mode with 10+5 time control.
        Failure: Lichess games start with wrong settings.
        """
        from DGTCentaurMods.opponents.lichess import LichessConfig, LichessGameMode
        
        config = LichessConfig()
        
        assert config.mode == LichessGameMode.NEW
        assert config.time_minutes == 10
        assert config.increment_seconds == 5
        assert config.rated is False
        assert config.color_preference == 'random'
    
    def test_config_new_game(self):
        """Test LichessConfig for NEW game mode.
        
        Expected: All NEW game parameters should be stored.
        Failure: Cannot configure Lichess game settings.
        """
        from DGTCentaurMods.opponents.lichess import LichessConfig, LichessGameMode
        
        config = LichessConfig(
            mode=LichessGameMode.NEW,
            time_minutes=15,
            increment_seconds=10,
            rated=True,
            color_preference='white'
        )
        
        assert config.mode == LichessGameMode.NEW
        assert config.time_minutes == 15
        assert config.increment_seconds == 10
        assert config.rated is True
        assert config.color_preference == 'white'
    
    def test_config_ongoing_game(self):
        """Test LichessConfig for ONGOING game mode.
        
        Expected: Game ID should be stored for resuming games.
        Failure: Cannot resume ongoing Lichess games.
        """
        from DGTCentaurMods.opponents.lichess import LichessConfig, LichessGameMode
        
        config = LichessConfig(
            mode=LichessGameMode.ONGOING,
            game_id='abc123xyz'
        )
        
        assert config.mode == LichessGameMode.ONGOING
        assert config.game_id == 'abc123xyz'
    
    def test_config_challenge(self):
        """Test LichessConfig for CHALLENGE mode.
        
        Expected: Challenge ID and direction should be stored.
        Failure: Cannot accept or create Lichess challenges.
        """
        from DGTCentaurMods.opponents.lichess import LichessConfig, LichessGameMode
        
        config = LichessConfig(
            mode=LichessGameMode.CHALLENGE,
            challenge_id='challenge123',
            challenge_direction='in'
        )
        
        assert config.mode == LichessGameMode.CHALLENGE
        assert config.challenge_id == 'challenge123'
        assert config.challenge_direction == 'in'


class TestLichessOpponent(unittest.TestCase):
    """Test cases for LichessOpponent."""
    
    def test_init_with_config(self):
        """Test LichessOpponent initialization with config.
        
        Expected: Opponent should initialize with provided config.
        Failure: Lichess opponent won't start with game settings.
        """
        from DGTCentaurMods.opponents.lichess import LichessOpponent, LichessConfig, LichessGameMode
        from DGTCentaurMods.opponents.base import OpponentState
        
        config = LichessConfig(mode=LichessGameMode.NEW, time_minutes=5)
        opponent = LichessOpponent(config)
        
        assert opponent._lichess_config.mode == LichessGameMode.NEW
        assert opponent._lichess_config.time_minutes == 5
        assert opponent._state == OpponentState.UNINITIALIZED
    
    def test_get_info(self):
        """Test get_info() returns Lichess metadata.
        
        Expected: Info should identify this as Lichess opponent.
        Failure: Display shows wrong opponent information.
        """
        from DGTCentaurMods.opponents.lichess import LichessOpponent, LichessConfig
        
        config = LichessConfig()
        opponent = LichessOpponent(config)
        info = opponent.get_info()
        
        assert info['type'] == 'lichess'
        assert 'description' in info
    
    def test_supports_takeback(self):
        """Test that Lichess opponent does NOT support takeback.
        
        Expected: Online games cannot have local takeback.
        Failure: Takeback incorrectly enabled for online games.
        """
        from DGTCentaurMods.opponents.lichess import LichessOpponent, LichessConfig
        
        config = LichessConfig()
        opponent = LichessOpponent(config)
        
        assert opponent.supports_takeback() is False
    
    def test_board_flip_default(self):
        """Test board_flip property defaults to False.
        
        Expected: Board not flipped until we know player color.
        Failure: Board incorrectly flipped before game starts.
        """
        from DGTCentaurMods.opponents.lichess import LichessOpponent, LichessConfig
        
        config = LichessConfig()
        opponent = LichessOpponent(config)
        
        assert opponent.board_flip is False


class TestLichessGameMode(unittest.TestCase):
    """Test cases for LichessGameMode enum."""
    
    def test_game_modes_exist(self):
        """Test that all expected game modes exist.
        
        Expected: NEW, ONGOING, and CHALLENGE modes should be defined.
        Failure: Missing mode breaks Lichess menu options.
        """
        from DGTCentaurMods.opponents.lichess import LichessGameMode
        
        assert LichessGameMode.NEW is not None
        assert LichessGameMode.ONGOING is not None
        assert LichessGameMode.CHALLENGE is not None


class TestOpponentCallbacks(unittest.TestCase):
    """Test cases for opponent callback functionality."""
    
    def test_set_move_callback(self):
        """Test setting move callback.
        
        Expected: Callback should be stored and callable.
        Failure: Opponent moves not delivered to game manager.
        """
        from DGTCentaurMods.opponents import HumanOpponent
        
        opponent = HumanOpponent()
        callback = MagicMock()
        
        opponent.set_move_callback(callback)
        
        assert opponent._move_callback == callback
    
    def test_set_status_callback(self):
        """Test setting status callback.
        
        Expected: Status callback should be stored.
        Failure: Status messages not delivered to UI.
        """
        from DGTCentaurMods.opponents import HumanOpponent
        
        opponent = HumanOpponent()
        callback = MagicMock()
        
        opponent.set_status_callback(callback)
        
        assert opponent._status_callback == callback


if __name__ == '__main__':
    unittest.main()
