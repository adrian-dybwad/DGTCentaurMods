"""
Pytest configuration and fixtures for Universal-Chess tests.

This module provides:
- Mock controller fixture for tests that need board functionality
- Automatic cleanup of board state between tests
"""

import pytest
from unittest.mock import MagicMock, PropertyMock


@pytest.fixture
def mock_controller():
    """
    Provide a mock SyncCentaur controller for tests.
    
    This fixture patches board.controller with a MagicMock that has
    all the methods a real controller would have. Use this for tests
    that call board functions (beep, ledsOff, getBoardState, etc.)
    without requiring actual hardware.
    
    Usage:
        def test_something(mock_controller):
            from universalchess.board import board
            board.beep(board.SOUND_GENERAL)  # Uses mock, doesn't crash
            mock_controller.beep.assert_called_once()
    """
    from universalchess.board import board
    
    # Create mock controller with all expected methods
    mock = MagicMock()
    mock.ready = True
    mock._piece_listener = None
    
    # Mock request_response to return valid-ish data
    mock.request_response.return_value = bytes([0] * 64)
    mock.request_response_low_priority.return_value = bytes([0] * 64)
    mock.get_next_key.return_value = None
    mock.wait_for_key_up.return_value = None
    mock.sleep.return_value = True
    
    # Patch the global controller
    original_controller = board.controller
    board.controller = mock
    
    yield mock
    
    # Restore original (likely None in tests)
    board.controller = original_controller



