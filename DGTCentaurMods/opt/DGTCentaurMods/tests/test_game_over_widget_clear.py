#!/usr/bin/env python3
"""Tests for game over widget clearing on new game.

When a game ends and the game over widget is displayed, resetting the board
to starting position should clear the game over widget.

Test case:
1. Game ends (game over widget is shown)
2. User resets pieces to starting position
3. EVENT_NEW_GAME is fired
4. Game over widget should be removed

Expected failure before fix: game_over_widget is not tracked as instance variable,
clear_game_over() method does not exist.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch
import importlib.util

# =============================================================================
# Mock all hardware-specific and Linux-specific modules BEFORE any imports
# =============================================================================

# Mock hardware and Linux-specific modules
for mod in ['spidev', 'RPi', 'RPi.GPIO', 'gpiozero', 'smbus', 'smbus2', 'bluetooth', 'psutil']:
    sys.modules[mod] = MagicMock()

# Mock dbus with submodules (dbus is a package, not just a module)
dbus_mock = types.ModuleType('dbus')
dbus_mock.mainloop = MagicMock()
dbus_mock.service = MagicMock()
dbus_mock.Interface = MagicMock()
dbus_mock.SystemBus = MagicMock()
dbus_mock.SessionBus = MagicMock()
dbus_mock.String = str
dbus_mock.Byte = int
dbus_mock.Array = list
dbus_mock.Dictionary = dict
sys.modules['dbus'] = dbus_mock
sys.modules['dbus.mainloop'] = MagicMock()
sys.modules['dbus.mainloop.glib'] = MagicMock()
sys.modules['dbus.service'] = MagicMock()

# Mock gi (GObject Introspection)
sys.modules['gi'] = MagicMock()
sys.modules['gi.repository'] = MagicMock()

# Mock serial
sys.modules['serial'] = MagicMock()
sys.modules['serial.tools'] = MagicMock()
sys.modules['serial.tools.list_ports'] = MagicMock()

# Mock numpy and PIL
sys.modules['numpy'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['PIL.Image'] = MagicMock()
sys.modules['PIL.ImageDraw'] = MagicMock()
sys.modules['PIL.ImageFont'] = MagicMock()

# Create proper package mocks for DGTCentaurMods.board
board_package = types.ModuleType('DGTCentaurMods.board')
mock_board = MagicMock()
mock_board.display_manager = MagicMock()
mock_board.display_manager.add_widget = MagicMock(return_value=MagicMock())
mock_board.display_manager.remove_widget = MagicMock()
mock_centaur = MagicMock()
board_package.board = mock_board
board_package.centaur = mock_centaur
sys.modules['DGTCentaurMods.board'] = board_package
sys.modules['DGTCentaurMods.board.board'] = mock_board
sys.modules['DGTCentaurMods.board.centaur'] = mock_centaur
sys.modules['DGTCentaurMods.board.logging'] = MagicMock()
sys.modules['DGTCentaurMods.board.settings'] = MagicMock()


class TestGameOverWidgetClear(unittest.TestCase):
    """Test that game over widget is properly cleared on new game."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset the mock board's display_manager for each test
        mock_board.display_manager.reset_mock()
    
    def _create_display_manager(self):
        """Create a DisplayManager with mocked dependencies.
        
        Returns tuple of (DisplayManager instance, test_mock_board).
        
        Note: This method sets the mock board at module level and does NOT
        restore it. Tests must ensure isolation through setUp().
        """
        # Import the display module (hardware mocks already in place)
        from DGTCentaurMods.managers.display import DisplayManager
        import DGTCentaurMods.managers.display as display_module
        
        # Create a fresh mock board for this test to ensure isolation
        test_mock_board = MagicMock()
        test_mock_board.display_manager = MagicMock()
        test_mock_board.display_manager.add_widget = MagicMock(return_value=MagicMock())
        test_mock_board.display_manager.remove_widget = MagicMock()
        
        # Create mock game state
        mock_game_state = MagicMock()
        
        # Set mocks at module level
        display_module.get_chess_game = MagicMock(return_value=mock_game_state)
        display_module._load_widgets = MagicMock()
        display_module.get_chess_clock_service = MagicMock(return_value=MagicMock())
        display_module.get_clock_state = MagicMock(return_value=MagicMock())
        
        # Set the board mock at module level so clear_game_over() uses it
        display_module.board = test_mock_board
        
        # Patch _init_widgets to avoid the whole initialization chain
        with patch.object(DisplayManager, '_init_widgets'):
            dm = DisplayManager()
        dm._clock = MagicMock()
        dm.clock_widget = MagicMock()
        return dm, test_mock_board

    def test_display_manager_has_game_over_widget_attribute(self):
        """DisplayManager should track game_over_widget as instance variable.
        
        Expected error before fix: AttributeError - 'DisplayManager' has no attribute 'game_over_widget'
        Why: game_over_widget needs to be tracked like pause_widget to enable removal.
        """
        dm, _ = self._create_display_manager()
        
        self.assertTrue(
            hasattr(dm, 'game_over_widget'),
            "DisplayManager must have game_over_widget attribute to track the widget"
        )
        self.assertIsNone(
            dm.game_over_widget,
            "game_over_widget should initially be None"
        )

    def test_display_manager_has_clear_game_over_method(self):
        """DisplayManager should have clear_game_over() method.
        
        Expected error before fix: AttributeError - 'DisplayManager' has no attribute 'clear_game_over'
        Why: Need a method to remove the game over widget when new game starts.
        """
        dm, _ = self._create_display_manager()
        
        self.assertTrue(
            callable(getattr(dm, 'clear_game_over', None)),
            "DisplayManager must have clear_game_over() method"
        )

    def test_clear_game_over_removes_widget(self):
        """clear_game_over() should remove widget from display and clear reference.
        
        Expected error before fix: clear_game_over() does not exist
        Why: Widget must be removed from display manager when new game starts.
        """
        dm, board_mock = self._create_display_manager()
        
        # Simulate game over widget being shown
        mock_widget = MagicMock()
        dm.game_over_widget = mock_widget
        
        # Clear should remove from display
        dm.clear_game_over()
        
        board_mock.display_manager.remove_widget.assert_called_once_with(mock_widget)
        self.assertIsNone(
            dm.game_over_widget,
            "clear_game_over() must set game_over_widget to None"
        )

    def test_clear_game_over_shows_clock_widget(self):
        """clear_game_over() should restore clock widget visibility.
        
        Expected error before fix: clock widget remains hidden after game over is cleared
        Why: show_game_over() hides the clock; clear_game_over() should restore it.
        """
        dm, _ = self._create_display_manager()
        dm._show_clock = True  # Clock should be visible
        
        # Simulate game over widget being shown
        mock_widget = MagicMock()
        dm.game_over_widget = mock_widget
        
        dm.clear_game_over()
        
        dm.clock_widget.show.assert_called_once()

    def test_clear_game_over_with_no_widget_is_safe(self):
        """clear_game_over() should be safe to call when no widget exists.
        
        Expected: No error, no side effects
        Why: EVENT_NEW_GAME may fire when no game over widget is displayed.
        """
        dm, board_mock = self._create_display_manager()
        dm.game_over_widget = None  # No game over widget
        
        # Should not raise
        dm.clear_game_over()
        
        # Should not call remove_widget when widget is None
        board_mock.display_manager.remove_widget.assert_not_called()


if __name__ == "__main__":
    unittest.main()
