"""Tests for the Lichess emulator.

Tests cover:
- LichessConfig creation and validation
- Lichess emulator initialization
- State machine transitions
- GameManager callback interface
- Move handling (player and remote moves)
- Error handling

Test Approach:
- Mock berserk library to avoid actual API calls
- Mock GameManager to verify callback behavior
- Test state transitions independently
"""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import threading
import time


class TestLichessConfig(unittest.TestCase):
    """Test cases for LichessConfig dataclass."""
    
    def test_config_defaults(self):
        """Test that LichessConfig has sensible defaults.
        
        Expected: Default config should use NEW mode with 10+5 time control.
        Failure: Config defaults are wrong, breaking expected game setup.
        """
        from DGTCentaurMods.emulators.lichess import LichessConfig, LichessGameMode
        
        config = LichessConfig(mode=LichessGameMode.NEW)
        
        assert config.mode == LichessGameMode.NEW
        assert config.time_minutes == 10
        assert config.increment_seconds == 5
        assert config.rated is False
        assert config.color == 'random'
    
    def test_config_new_game(self):
        """Test LichessConfig for NEW game mode.
        
        Expected: All NEW game parameters should be stored correctly.
        Failure: Game will start with wrong time control or rating.
        """
        from DGTCentaurMods.emulators.lichess import LichessConfig, LichessGameMode
        
        config = LichessConfig(
            mode=LichessGameMode.NEW,
            time_minutes=15,
            increment_seconds=10,
            rated=True,
            color='white'
        )
        
        assert config.mode == LichessGameMode.NEW
        assert config.time_minutes == 15
        assert config.increment_seconds == 10
        assert config.rated is True
        assert config.color == 'white'
    
    def test_config_ongoing_game(self):
        """Test LichessConfig for ONGOING game mode.
        
        Expected: Game ID should be stored for resuming a game.
        Failure: Cannot resume ongoing games.
        """
        from DGTCentaurMods.emulators.lichess import LichessConfig, LichessGameMode
        
        config = LichessConfig(
            mode=LichessGameMode.ONGOING,
            game_id='abc123xyz'
        )
        
        assert config.mode == LichessGameMode.ONGOING
        assert config.game_id == 'abc123xyz'
    
    def test_config_challenge(self):
        """Test LichessConfig for CHALLENGE mode.
        
        Expected: Challenge ID and direction should be stored.
        Failure: Cannot accept or create challenges.
        """
        from DGTCentaurMods.emulators.lichess import LichessConfig, LichessGameMode
        
        config = LichessConfig(
            mode=LichessGameMode.CHALLENGE,
            challenge_id='challenge123',
            challenge_direction='in'
        )
        
        assert config.mode == LichessGameMode.CHALLENGE
        assert config.challenge_id == 'challenge123'
        assert config.challenge_direction == 'in'


class TestLichessEmulatorInit(unittest.TestCase):
    """Test cases for Lichess emulator initialization."""
    
    def test_init_with_config(self):
        """Test emulator initialization with config.
        
        Expected: Emulator should initialize with provided config.
        Failure: Emulator won't start with custom game settings.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessConfig, LichessGameMode, LichessGameState
        
        config = LichessConfig(mode=LichessGameMode.NEW, time_minutes=5)
        mock_manager = MagicMock()
        
        emulator = Lichess(
            sendMessage_callback=None,
            manager=mock_manager,
            config=config
        )
        
        assert emulator.config.mode == LichessGameMode.NEW
        assert emulator.config.time_minutes == 5
        assert emulator.manager == mock_manager
        assert emulator.state == LichessGameState.DISCONNECTED
    
    def test_init_default_config(self):
        """Test emulator initialization without config uses defaults.
        
        Expected: Default config should be created automatically.
        Failure: Emulator crashes when no config provided.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameMode, LichessGameState
        
        emulator = Lichess(manager=MagicMock())
        
        assert emulator.config.mode == LichessGameMode.NEW
        assert emulator.state == LichessGameState.DISCONNECTED
    
    def test_class_properties(self):
        """Test emulator class properties for protocol detection.
        
        Expected: Lichess should be marked as remote game, not byte-stream.
        Failure: ProtocolManager may incorrectly try to use byte parsing.
        """
        from DGTCentaurMods.emulators.lichess import Lichess
        
        assert Lichess.supports_rfcomm is False
        assert Lichess.supports_ble is False
        assert Lichess.is_remote_game is True


class TestLichessStateTransitions(unittest.TestCase):
    """Test cases for Lichess state machine transitions."""
    
    def test_initial_state(self):
        """Test that emulator starts in DISCONNECTED state.
        
        Expected: Initial state should be DISCONNECTED.
        Failure: State machine starts in wrong state.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        
        emulator = Lichess(manager=MagicMock())
        
        assert emulator.state == LichessGameState.DISCONNECTED
    
    def test_state_thread_safety(self):
        """Test that state changes are thread-safe.
        
        Expected: Concurrent state changes should not cause race conditions.
        Failure: State corruption under concurrent access.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        
        emulator = Lichess(manager=MagicMock())
        
        results = []
        
        def change_state(new_state):
            emulator._set_state(new_state)
            results.append(emulator.state)
        
        threads = []
        states = [
            LichessGameState.AUTHENTICATING,
            LichessGameState.SEEKING,
            LichessGameState.PLAYING,
        ]
        
        for state in states:
            t = threading.Thread(target=change_state, args=(state,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # All state changes should complete without error
        assert len(results) == 3
        # Final state should be one of the states (order not guaranteed)
        assert emulator.state in states


class TestLichessManagerCallbacks(unittest.TestCase):
    """Test cases for GameManager callback interface."""
    
    def test_handle_manager_event_white_turn(self):
        """Test handling white turn event.
        
        Expected: Turn flag should be set to white.
        Failure: Turn tracking broken, wrong moves sent to Lichess.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        from DGTCentaurMods.managers.events import EVENT_WHITE_TURN
        
        emulator = Lichess(manager=MagicMock())
        emulator._set_state(LichessGameState.PLAYING)
        
        emulator.handle_manager_event(EVENT_WHITE_TURN, None, None, None)
        
        assert emulator._current_turn_is_white is True
    
    def test_handle_manager_event_black_turn(self):
        """Test handling black turn event.
        
        Expected: Turn flag should be set to black.
        Failure: Turn tracking broken, wrong moves sent to Lichess.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        from DGTCentaurMods.managers.events import EVENT_BLACK_TURN
        
        emulator = Lichess(manager=MagicMock())
        emulator._set_state(LichessGameState.PLAYING)
        
        emulator.handle_manager_event(EVENT_BLACK_TURN, None, None, None)
        
        assert emulator._current_turn_is_white is False
    
    def test_handle_manager_move_not_connected(self):
        """Test that moves are ignored when not connected.
        
        Expected: Move should be silently ignored when disconnected.
        Failure: Crashes or sends moves when not connected.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        
        emulator = Lichess(manager=MagicMock())
        # State is DISCONNECTED by default
        
        # Should not raise
        emulator.handle_manager_move(MagicMock())
        
        # No client to send to, should be fine
        assert emulator.state == LichessGameState.DISCONNECTED
    
    def test_handle_manager_key_back(self):
        """Test handling BACK key press.
        
        Expected: BACK key should be logged (triggering exit handled externally).
        Failure: Key handling crashes or behaves unexpectedly.
        """
        from DGTCentaurMods.emulators.lichess import Lichess
        
        emulator = Lichess(manager=MagicMock())
        
        mock_key = MagicMock()
        mock_key.name = 'BACK'
        
        # Should not raise
        emulator.handle_manager_key(mock_key)
    
    def test_handle_manager_takeback(self):
        """Test handling takeback request.
        
        Expected: Takeback should be declined (Lichess doesn't support from external).
        Failure: Crashes on takeback request.
        """
        from DGTCentaurMods.emulators.lichess import Lichess
        
        emulator = Lichess(manager=MagicMock())
        
        # Should not raise
        emulator.handle_manager_takeback()


class TestLichessPlayerTurn(unittest.TestCase):
    """Test cases for player turn detection."""
    
    def test_is_player_turn_as_white(self):
        """Test turn detection when playing as white.
        
        Expected: Player turn when white to move and playing white.
        Failure: Moves sent at wrong time.
        """
        from DGTCentaurMods.emulators.lichess import Lichess
        
        emulator = Lichess(manager=MagicMock())
        emulator._player_is_white = True
        emulator._current_turn_is_white = True
        
        assert emulator._is_player_turn() is True
        
        emulator._current_turn_is_white = False
        assert emulator._is_player_turn() is False
    
    def test_is_player_turn_as_black(self):
        """Test turn detection when playing as black.
        
        Expected: Player turn when black to move and playing black.
        Failure: Moves sent at wrong time.
        """
        from DGTCentaurMods.emulators.lichess import Lichess
        
        emulator = Lichess(manager=MagicMock())
        emulator._player_is_white = False
        emulator._current_turn_is_white = False
        
        assert emulator._is_player_turn() is True
        
        emulator._current_turn_is_white = True
        assert emulator._is_player_turn() is False
    
    def test_is_player_turn_unknown_color(self):
        """Test turn detection before player color is known.
        
        Expected: Should return False when player color unknown.
        Failure: Premature moves sent before game setup complete.
        """
        from DGTCentaurMods.emulators.lichess import Lichess
        
        emulator = Lichess(manager=MagicMock())
        emulator._player_is_white = None
        
        assert emulator._is_player_turn() is False


class TestLichessStartStop(unittest.TestCase):
    """Test cases for start/stop lifecycle."""
    
    @patch('DGTCentaurMods.board.centaur.get_lichess_api')
    def test_start_no_token(self, mock_get_api):
        """Test start fails gracefully with no API token.
        
        Expected: Should return False and set ERROR state.
        Failure: Crashes or hangs without token.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        
        mock_get_api.return_value = ""
        
        emulator = Lichess(manager=MagicMock())
        result = emulator.start()
        
        assert result is False
        assert emulator.state == LichessGameState.ERROR
    
    @patch('DGTCentaurMods.board.centaur.get_lichess_api')
    def test_start_invalid_token(self, mock_get_api):
        """Test start fails gracefully with placeholder token.
        
        Expected: Should return False and set ERROR state.
        Failure: Tries to connect with invalid token.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        
        mock_get_api.return_value = "tokenhere"
        
        emulator = Lichess(manager=MagicMock())
        result = emulator.start()
        
        assert result is False
        assert emulator.state == LichessGameState.ERROR
    
    def test_stop_cleans_up(self):
        """Test stop signals threads to stop.
        
        Expected: Should signal threads and transition to DISCONNECTED.
        Failure: Threads left running, resources leaked.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        
        emulator = Lichess(manager=MagicMock())
        emulator._set_state(LichessGameState.PLAYING)
        
        emulator.stop()
        
        assert emulator._should_stop.is_set()
        assert emulator.state == LichessGameState.DISCONNECTED
    
    def test_is_connected_when_playing(self):
        """Test is_connected returns True when in PLAYING state.
        
        Expected: True only in PLAYING state.
        Failure: Incorrect connection status reported.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        
        emulator = Lichess(manager=MagicMock())
        
        assert emulator.is_connected() is False
        
        emulator._set_state(LichessGameState.PLAYING)
        assert emulator.is_connected() is True
        
        emulator._set_state(LichessGameState.GAME_OVER)
        assert emulator.is_connected() is False


class TestLichessRemoteMove(unittest.TestCase):
    """Test cases for remote move processing."""
    
    def test_check_for_remote_move_opponent_move(self):
        """Test processing opponent's remote move.
        
        Expected: Should call manager.computer_move for opponent moves.
        Failure: Opponent moves not executed on physical board.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        
        mock_manager = MagicMock()
        emulator = Lichess(manager=mock_manager)
        emulator._set_state(LichessGameState.PLAYING)
        emulator._player_is_white = True
        emulator._current_turn_is_white = False  # Black's turn (opponent)
        
        emulator._remote_moves = "e2e4 e7e5"
        emulator._last_processed_moves = "e2e4"
        
        emulator._check_for_remote_move()
        
        mock_manager.computer_move.assert_called_once_with("e5", forced=True)
    
    def test_check_for_remote_move_player_move_ignored(self):
        """Test that player's own move echo is ignored.
        
        Expected: Should not call computer_move for player's own moves.
        Failure: Player's moves duplicated on board.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        
        mock_manager = MagicMock()
        emulator = Lichess(manager=mock_manager)
        emulator._set_state(LichessGameState.PLAYING)
        emulator._player_is_white = True
        emulator._current_turn_is_white = True  # White's turn (player)
        
        emulator._remote_moves = "e2e4"
        emulator._last_processed_moves = ""
        
        emulator._check_for_remote_move()
        
        mock_manager.computer_move.assert_not_called()
    
    def test_check_for_remote_move_no_new_moves(self):
        """Test that duplicate move lists are ignored.
        
        Expected: Should not process if moves haven't changed.
        Failure: Same move processed multiple times.
        """
        from DGTCentaurMods.emulators.lichess import Lichess, LichessGameState
        
        mock_manager = MagicMock()
        emulator = Lichess(manager=mock_manager)
        emulator._set_state(LichessGameState.PLAYING)
        
        emulator._remote_moves = "e2e4"
        emulator._last_processed_moves = "e2e4"
        
        emulator._check_for_remote_move()
        
        mock_manager.computer_move.assert_not_called()


class TestLichessProperties(unittest.TestCase):
    """Test cases for emulator properties."""
    
    def test_board_flip_as_white(self):
        """Test board_flip is False when playing as white.
        
        Expected: No flip needed when playing white.
        Failure: Board displayed upside down for white.
        """
        from DGTCentaurMods.emulators.lichess import Lichess
        
        emulator = Lichess(manager=MagicMock())
        emulator._board_flip = False
        
        assert emulator.board_flip is False
    
    def test_board_flip_as_black(self):
        """Test board_flip is True when playing as black.
        
        Expected: Flip needed when playing black.
        Failure: Board displayed wrong way for black.
        """
        from DGTCentaurMods.emulators.lichess import Lichess
        
        emulator = Lichess(manager=MagicMock())
        emulator._board_flip = True
        
        assert emulator.board_flip is True
    
    def test_game_id_property(self):
        """Test game_id property returns current game ID.
        
        Expected: Should return game ID when set.
        Failure: Cannot track current game.
        """
        from DGTCentaurMods.emulators.lichess import Lichess
        
        emulator = Lichess(manager=MagicMock())
        
        assert emulator.game_id is None
        
        emulator._game_id = "test_game_123"
        assert emulator.game_id == "test_game_123"


class TestProtocolManagerLichessIntegration(unittest.TestCase):
    """Test cases for ProtocolManager Lichess integration."""
    
    @patch('DGTCentaurMods.managers.protocol.Millennium')
    @patch('DGTCentaurMods.managers.protocol.Pegasus')
    @patch('DGTCentaurMods.managers.protocol.Chessnut')
    @patch('DGTCentaurMods.managers.game.GameManager')
    def test_protocol_manager_lichess_mode(self, mock_game_manager, mock_chessnut, mock_pegasus, mock_millennium):
        """Test ProtocolManager creates Lichess emulator when configured.
        
        Expected: Lichess mode should set is_lichess flag and skip byte emulators.
        Failure: Lichess mode not activated properly.
        """
        from DGTCentaurMods.managers.protocol import ProtocolManager
        from DGTCentaurMods.emulators.lichess import LichessConfig, LichessGameMode
        
        # Mock GameManager to avoid hardware access
        mock_game_manager.return_value = MagicMock()
        
        config = LichessConfig(mode=LichessGameMode.NEW)
        
        with patch('DGTCentaurMods.emulators.lichess.Lichess') as mock_lichess:
            mock_lichess.return_value = MagicMock()
            
            manager = ProtocolManager(lichess_config=config)
            
            assert manager.is_lichess is True
            assert manager.client_type == ProtocolManager.CLIENT_LICHESS
            mock_lichess.assert_called_once()
    
    @patch('DGTCentaurMods.managers.protocol.Millennium')
    @patch('DGTCentaurMods.managers.protocol.Pegasus')
    @patch('DGTCentaurMods.managers.protocol.Chessnut')
    @patch('DGTCentaurMods.managers.game.GameManager')
    def test_protocol_manager_normal_mode(self, mock_game_manager, mock_chessnut, mock_pegasus, mock_millennium):
        """Test ProtocolManager creates byte emulators when no Lichess config.
        
        Expected: Normal mode should create Millennium/Pegasus/Chessnut emulators.
        Failure: Byte-stream emulators not created.
        """
        from DGTCentaurMods.managers.protocol import ProtocolManager
        
        # Mock GameManager to avoid hardware access
        mock_game_manager.return_value = MagicMock()
        
        manager = ProtocolManager()
        
        assert manager.is_lichess is False
        mock_millennium.assert_called()
        mock_pegasus.assert_called()
        mock_chessnut.assert_called()
    
    @patch('DGTCentaurMods.managers.protocol.Millennium')
    @patch('DGTCentaurMods.managers.protocol.Pegasus')
    @patch('DGTCentaurMods.managers.protocol.Chessnut')
    @patch('DGTCentaurMods.managers.game.GameManager')
    def test_is_app_connected_includes_lichess(self, mock_game_manager, mock_chessnut, mock_pegasus, mock_millennium):
        """Test is_app_connected includes Lichess.
        
        Expected: Should return True when Lichess is active.
        Failure: Lichess not recognized as connected app.
        """
        from DGTCentaurMods.managers.protocol import ProtocolManager
        from DGTCentaurMods.emulators.lichess import LichessConfig, LichessGameMode
        
        mock_game_manager.return_value = MagicMock()
        
        config = LichessConfig(mode=LichessGameMode.NEW)
        
        with patch('DGTCentaurMods.emulators.lichess.Lichess') as mock_lichess:
            mock_lichess.return_value = MagicMock()
            
            manager = ProtocolManager(lichess_config=config)
            
            assert manager.is_app_connected() is True


if __name__ == '__main__':
    unittest.main()
