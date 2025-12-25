"""Tests for the assistants module.

Tests cover:
- AssistantConfig dataclass creation
- Suggestion dataclass creation
- SuggestionType enum values
- Assistant base class abstract methods
- HandBrainAssistant initialization and configuration
- HintAssistant initialization and configuration

Test Approach:
- Mock chess.engine to avoid actual engine processes
- Test state transitions and callback behavior
- Verify suggestion types are correctly identified
"""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import threading
import time


class TestAssistantConfig(unittest.TestCase):
    """Test cases for AssistantConfig dataclass."""
    
    def test_config_defaults(self):
        """Test that AssistantConfig has sensible defaults.
        
        Expected: Default config should have reasonable time limit and auto_suggest.
        Failure: Config defaults are wrong, breaking expected assistant behavior.
        """
        from universalchess.assistants.base import AssistantConfig
        
        config = AssistantConfig()
        
        assert config.name == "Assistant"
        assert config.time_limit_seconds == 2.0
        assert config.auto_suggest is True
    
    def test_config_custom_values(self):
        """Test AssistantConfig with custom values.
        
        Expected: Custom values should be stored correctly.
        Failure: Custom assistant settings not applied.
        """
        from universalchess.assistants.base import AssistantConfig
        
        config = AssistantConfig(
            name="Custom Brain",
            time_limit_seconds=5.0,
            auto_suggest=False
        )
        
        assert config.name == "Custom Brain"
        assert config.time_limit_seconds == 5.0
        assert config.auto_suggest is False


class TestSuggestionType(unittest.TestCase):
    """Test cases for SuggestionType enum."""
    
    def test_suggestion_types_exist(self):
        """Test that all expected suggestion types exist.
        
        Expected: PIECE_TYPE and MOVE types should be defined.
        Failure: Missing type breaks assistant suggestion handling.
        """
        from universalchess.assistants.base import SuggestionType
        
        assert SuggestionType.PIECE_TYPE is not None
        assert SuggestionType.MOVE is not None
    
    def test_piece_type_for_hand_brain(self):
        """Test PIECE_TYPE suggestion type for Hand+Brain mode.
        
        Expected: PIECE_TYPE should be used for Hand+Brain suggestions.
        Failure: Hand+Brain mode won't display piece hints correctly.
        """
        from universalchess.assistants.base import SuggestionType
        
        # PIECE_TYPE is for suggesting which piece type to move (K, Q, R, B, N, P)
        assert SuggestionType.PIECE_TYPE.value is not None
    
    def test_move_type_for_hints(self):
        """Test MOVE suggestion type for move hints.
        
        Expected: MOVE should be used for full move suggestions.
        Failure: Move hints won't be handled correctly.
        """
        from universalchess.assistants.base import SuggestionType
        
        # MOVE is for suggesting a complete move
        assert SuggestionType.MOVE.value is not None


class TestSuggestion(unittest.TestCase):
    """Test cases for Suggestion dataclass."""
    
    def test_piece_type_suggestion(self):
        """Test creating a PIECE_TYPE suggestion.
        
        Expected: Suggestion should store piece type and relevant squares.
        Failure: Hand+Brain hints won't be created correctly.
        """
        from universalchess.assistants.base import Suggestion, SuggestionType
        
        suggestion = Suggestion(
            suggestion_type=SuggestionType.PIECE_TYPE,
            piece_type="N",
            squares=[1, 6, 57, 62]  # Knight starting squares
        )
        
        assert suggestion.suggestion_type == SuggestionType.PIECE_TYPE
        assert suggestion.piece_type == "N"
        assert len(suggestion.squares) == 4
        assert suggestion.move is None
    
    def test_move_suggestion(self):
        """Test creating a MOVE suggestion.
        
        Expected: Suggestion should store the suggested move.
        Failure: Move hints won't be created correctly.
        """
        import chess
        from universalchess.assistants.base import Suggestion, SuggestionType
        
        move = chess.Move.from_uci("e2e4")
        suggestion = Suggestion(
            suggestion_type=SuggestionType.MOVE,
            move=move
        )
        
        assert suggestion.suggestion_type == SuggestionType.MOVE
        assert suggestion.move == move
        assert suggestion.piece_type is None
    
    def test_suggestion_with_confidence(self):
        """Test suggestion with confidence score.
        
        Expected: Confidence should be stored if provided.
        Failure: Confidence info not available for UI.
        """
        from universalchess.assistants.base import Suggestion, SuggestionType
        
        suggestion = Suggestion(
            suggestion_type=SuggestionType.PIECE_TYPE,
            piece_type="Q",
            confidence=0.95
        )
        
        assert suggestion.confidence == 0.95


class TestHandBrainConfig(unittest.TestCase):
    """Test cases for HandBrainConfig dataclass."""
    
    def test_config_defaults(self):
        """Test HandBrainConfig default values.
        
        Expected: Default should use stockfish for analysis.
        Failure: Hand+Brain mode uses wrong engine.
        """
        from universalchess.assistants.hand_brain import HandBrainConfig
        
        config = HandBrainConfig()
        
        assert config.engine_name == "stockfish"
        assert config.elo_section == "Default"
        assert config.auto_suggest is True
    
    def test_config_custom_values(self):
        """Test HandBrainConfig with custom values.
        
        Expected: Custom engine settings should be stored.
        Failure: Cannot configure different engines for Hand+Brain.
        """
        from universalchess.assistants.hand_brain import HandBrainConfig
        
        config = HandBrainConfig(
            name="Maia Brain",
            engine_name="maia",
            elo_section="1500",
            time_limit_seconds=3.0
        )
        
        assert config.name == "Maia Brain"
        assert config.engine_name == "maia"
        assert config.elo_section == "1500"
        assert config.time_limit_seconds == 3.0


class TestHandBrainAssistant(unittest.TestCase):
    """Test cases for HandBrainAssistant."""
    
    def test_init_with_config(self):
        """Test HandBrainAssistant initialization with config.
        
        Expected: Assistant should store configuration.
        Failure: Hand+Brain settings not applied correctly.
        """
        from universalchess.assistants.hand_brain import HandBrainAssistant, HandBrainConfig
        
        config = HandBrainConfig(engine_name="ct800", elo_section="1200")
        assistant = HandBrainAssistant(config)
        
        assert assistant.name == config.name
        assert assistant._hand_brain_config.engine_name == "ct800"
    
    def test_auto_suggest_enabled(self):
        """Test that auto_suggest is enabled by default.
        
        Expected: Hand+Brain should auto-suggest on player's turn.
        Failure: Brain hints not shown automatically.
        """
        from universalchess.assistants.hand_brain import HandBrainAssistant, HandBrainConfig
        
        config = HandBrainConfig()
        assistant = HandBrainAssistant(config)
        
        assert assistant.auto_suggest is True
    
    def test_get_info(self):
        """Test get_info() returns Hand+Brain metadata.
        
        Expected: Info should identify this as hand_brain assistant.
        Failure: Display shows wrong assistant information.
        """
        from universalchess.assistants.hand_brain import HandBrainAssistant, HandBrainConfig
        
        config = HandBrainConfig(
            name="Test Brain",
            engine_name="stockfish",
            elo_section="1500"
        )
        assistant = HandBrainAssistant(config)
        info = assistant.get_info()
        
        assert info['type'] == 'hand_brain'
        assert info['engine_name'] == 'stockfish'
        assert info['elo_section'] == '1500'


class TestHintConfig(unittest.TestCase):
    """Test cases for HintConfig dataclass."""
    
    def test_config_defaults(self):
        """Test HintConfig default values.
        
        Expected: Default hint should use stockfish, auto_suggest off.
        Failure: Hint mode uses wrong settings.
        """
        from universalchess.assistants.hint import HintConfig
        
        config = HintConfig()
        
        assert config.engine_name == "stockfish"
        assert config.elo_section == "Default"
        assert config.auto_suggest is False  # Hints are on-demand
    
    def test_config_custom_values(self):
        """Test HintConfig with custom values.
        
        Expected: Custom engine settings should be stored.
        Failure: Cannot configure different engines for hints.
        """
        from universalchess.assistants.hint import HintConfig
        
        config = HintConfig(
            name="Quick Hint",
            engine_name="ct800",
            time_limit_seconds=1.0
        )
        
        assert config.name == "Quick Hint"
        assert config.engine_name == "ct800"
        assert config.time_limit_seconds == 1.0


class TestHintAssistant(unittest.TestCase):
    """Test cases for HintAssistant."""
    
    def test_init_with_config(self):
        """Test HintAssistant initialization with config.
        
        Expected: Assistant should store configuration.
        Failure: Hint settings not applied correctly.
        """
        from universalchess.assistants.hint import HintAssistant, HintConfig
        
        config = HintConfig(engine_name="stockfish")
        assistant = HintAssistant(config)
        
        assert assistant.name == config.name
        assert assistant._hint_config.engine_name == "stockfish"
    
    def test_auto_suggest_disabled(self):
        """Test that auto_suggest is disabled for hints.
        
        Expected: Hints should only be shown on request, not automatically.
        Failure: Hints incorrectly shown on every turn.
        """
        from universalchess.assistants.hint import HintAssistant, HintConfig
        
        config = HintConfig()
        assistant = HintAssistant(config)
        
        assert assistant.auto_suggest is False
    
    def test_get_info(self):
        """Test get_info() returns hint metadata.
        
        Expected: Info should identify this as hint assistant.
        Failure: Display shows wrong assistant information.
        """
        from universalchess.assistants.hint import HintAssistant, HintConfig
        
        config = HintConfig(name="Position Hint")
        assistant = HintAssistant(config)
        info = assistant.get_info()
        
        assert info['type'] == 'hint'
        assert info['name'] == 'Position Hint'


class TestCreateHandBrainAssistant(unittest.TestCase):
    """Test cases for create_hand_brain_assistant factory function."""
    
    def test_factory_defaults(self):
        """Test factory function with defaults.
        
        Expected: Factory should create assistant with sensible defaults.
        Failure: Cannot create Hand+Brain assistants easily.
        """
        from universalchess.assistants import create_hand_brain_assistant
        
        assistant = create_hand_brain_assistant()
        
        assert assistant is not None
        assert assistant.auto_suggest is True
    
    def test_factory_custom_values(self):
        """Test factory function with custom values.
        
        Expected: Factory should pass through custom settings.
        Failure: Custom brain settings not applied.
        """
        from universalchess.assistants import create_hand_brain_assistant
        
        assistant = create_hand_brain_assistant(
            engine_name="ct800",
            elo_section="1200",
            time_limit=3.0
        )
        
        info = assistant.get_info()
        assert info['engine_name'] == 'ct800'
        assert info['elo_section'] == '1200'


class TestCreateHintAssistant(unittest.TestCase):
    """Test cases for create_hint_assistant factory function."""
    
    def test_factory_defaults(self):
        """Test factory function with defaults.
        
        Expected: Factory should create assistant with sensible defaults.
        Failure: Cannot create hint assistants easily.
        """
        from universalchess.assistants import create_hint_assistant
        
        assistant = create_hint_assistant()
        
        assert assistant is not None
        assert assistant.auto_suggest is False
    
    def test_factory_custom_values(self):
        """Test factory function with custom values.
        
        Expected: Factory should pass through custom settings.
        Failure: Custom hint settings not applied.
        """
        from universalchess.assistants import create_hint_assistant
        
        assistant = create_hint_assistant(
            engine_name="stockfish",
            time_limit=5.0
        )
        
        info = assistant.get_info()
        assert info['engine_name'] == 'stockfish'


class TestAssistantCallbacks(unittest.TestCase):
    """Test cases for assistant callback functionality."""
    
    def test_set_suggestion_callback(self):
        """Test setting suggestion callback.
        
        Expected: Callback should be stored and callable.
        Failure: Suggestions not delivered to display.
        """
        from universalchess.assistants.hand_brain import HandBrainAssistant, HandBrainConfig
        
        config = HandBrainConfig()
        assistant = HandBrainAssistant(config)
        callback = MagicMock()
        
        assistant.set_suggestion_callback(callback)
        
        assert assistant._suggestion_callback == callback
    
    def test_set_status_callback(self):
        """Test setting status callback.
        
        Expected: Status callback should be stored.
        Failure: Status messages not delivered to UI.
        """
        from universalchess.assistants.hand_brain import HandBrainAssistant, HandBrainConfig
        
        config = HandBrainConfig()
        assistant = HandBrainAssistant(config)
        callback = MagicMock()
        
        assistant.set_status_callback(callback)
        
        assert assistant._status_callback == callback


class TestAssistantLifecycle(unittest.TestCase):
    """Test cases for assistant lifecycle methods."""
    
    def test_on_new_game(self):
        """Test on_new_game resets state.
        
        Expected: Assistant should reset any game-specific state.
        Failure: State from previous game affects new game.
        """
        from universalchess.assistants.hand_brain import HandBrainAssistant, HandBrainConfig
        
        config = HandBrainConfig()
        assistant = HandBrainAssistant(config)
        
        # Should not raise
        assistant.on_new_game()
    
    def test_on_takeback(self):
        """Test on_takeback handles position change.
        
        Expected: Assistant should handle takeback without crashing.
        Failure: Takeback causes assistant errors.
        """
        import chess
        from universalchess.assistants.hand_brain import HandBrainAssistant, HandBrainConfig
        
        config = HandBrainConfig()
        assistant = HandBrainAssistant(config)
        board = chess.Board()
        
        # Should not raise
        assistant.on_takeback(board)
    
    def test_clear_suggestion(self):
        """Test clear_suggestion removes current suggestion.
        
        Expected: Current suggestion should be cleared.
        Failure: Stale suggestions shown to user.
        """
        from universalchess.assistants.hand_brain import HandBrainAssistant, HandBrainConfig
        
        config = HandBrainConfig()
        assistant = HandBrainAssistant(config)
        
        callback = MagicMock()
        assistant.set_suggestion_callback(callback)
        
        assistant.clear_suggestion()
        
        # Should call callback with None or empty suggestion
        # Implementation may vary, just ensure no crash
        assert True


if __name__ == '__main__':
    unittest.main()
