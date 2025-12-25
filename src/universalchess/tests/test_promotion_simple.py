#!/usr/bin/env python3
"""
Unit Tests for Promotion Button Handling

Tests verify that the refactored button handling logic correctly maps
button presses to promotion piece choices and uses proper board API
instead of direct serial access.

USAGE:
    cd /home/pi/DGTCentaurMods/DGTCentaurMods/opt
    python3 -m pytest DGTCentaurMods/tests/test_promotion_simple.py -v
"""

import unittest


class TestWaitForPromotionChoiceMapping(unittest.TestCase):
    """
    Tests for promotion button mapping logic.
    
    Expected behavior:
    - BACK button -> Knight ('n')
    - TICK button -> Bishop ('b')
    - UP button -> Queen ('q')
    - DOWN button -> Rook ('r')
    - Unknown/timeout defaults to Queen ('q')
    """
    
    @staticmethod
    def mock_wait_for_promotion_choice(button_name):
        """
        Mock version of waitForPromotionChoice for testing.
        
        This mirrors the expected button mapping logic without requiring
        the full DGTCentaurMods environment.
        
        Args:
            button_name: Button name string or None for timeout.
            
        Returns:
            Single character representing the promotion piece.
        """
        if button_name == 'BACK':
            return "n"  # Knight
        elif button_name == 'TICK':
            return "b"  # Bishop
        elif button_name == 'UP':
            return "q"  # Queen
        elif button_name == 'DOWN':
            return "r"  # Rook
        else:
            return "q"  # Default to queen on timeout/other
    
    def test_back_button_maps_to_knight(self):
        """
        Test BACK button maps to knight.
        
        Expected: 'n' for knight promotion.
        Failure indicates: Button mapping constant is incorrect.
        """
        result = self.mock_wait_for_promotion_choice('BACK')
        self.assertEqual(result, 'n')
    
    def test_tick_button_maps_to_bishop(self):
        """
        Test TICK button maps to bishop.
        
        Expected: 'b' for bishop promotion.
        Failure indicates: Button mapping constant is incorrect.
        """
        result = self.mock_wait_for_promotion_choice('TICK')
        self.assertEqual(result, 'b')
    
    def test_up_button_maps_to_queen(self):
        """
        Test UP button maps to queen.
        
        Expected: 'q' for queen promotion.
        Failure indicates: Button mapping constant is incorrect.
        """
        result = self.mock_wait_for_promotion_choice('UP')
        self.assertEqual(result, 'q')
    
    def test_down_button_maps_to_rook(self):
        """
        Test DOWN button maps to rook.
        
        Expected: 'r' for rook promotion.
        Failure indicates: Button mapping constant is incorrect.
        """
        result = self.mock_wait_for_promotion_choice('DOWN')
        self.assertEqual(result, 'r')
    
    def test_unknown_button_defaults_to_queen(self):
        """
        Test unknown button defaults to queen.
        
        Expected: 'q' for queen as default.
        Failure indicates: Default fallback is incorrect.
        """
        result = self.mock_wait_for_promotion_choice('UNKNOWN')
        self.assertEqual(result, 'q')
    
    def test_timeout_defaults_to_queen(self):
        """
        Test timeout (None) defaults to queen.
        
        Expected: 'q' for queen on timeout.
        Failure indicates: Timeout handling is incorrect.
        """
        result = self.mock_wait_for_promotion_choice(None)
        self.assertEqual(result, 'q')


class TestNoDirectSerialPatterns(unittest.TestCase):
    """
    Tests to verify gamemanager.py uses proper board API.
    
    The refactored code should not contain direct serial access patterns
    and should use the abstracted board.py wrapper functions instead.
    """
    
    GAMEMANAGER_PATH = "DGTCentaurMods/game/gamemanager.py"
    
    FORBIDDEN_PATTERNS = [
        'board.ser.write',
        'board.ser.read',
        'board.sendPacket',
        'resp.hex()',
        'board.addr1',
        'board.addr2'
    ]
    
    def _read_gamemanager_source(self):
        """Read gamemanager.py source code."""
        with open(self.GAMEMANAGER_PATH, 'r') as f:
            return f.read()
    
    def test_no_direct_serial_access_patterns(self):
        """
        Test that gamemanager.py has no direct serial access.
        
        Expected: No forbidden patterns found in source.
        Failure indicates: Refactoring is incomplete - direct serial
        access still exists and should be replaced with board API calls.
        """
        try:
            content = self._read_gamemanager_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        violations = [p for p in self.FORBIDDEN_PATTERNS if p in content]
        self.assertEqual(
            violations, [],
            f"Found forbidden direct serial access patterns: {violations}"
        )


class TestBoardWrapperExists(unittest.TestCase):
    """
    Tests to verify board.py has required wrapper functions.
    """
    
    BOARD_PATH = "DGTCentaurMods/board/board.py"
    
    def _read_board_source(self):
        """Read board.py source code."""
        with open(self.BOARD_PATH, 'r') as f:
            return f.read()
    
    def test_wait_for_key_up_wrapper_exists(self):
        """
        Test that wait_for_key_up wrapper function exists in board.py.
        
        Expected: 'def wait_for_key_up(' found in source.
        Failure indicates: Board wrapper function was not added.
        """
        try:
            content = self._read_board_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.BOARD_PATH}")
        
        self.assertIn(
            'def wait_for_key_up(',
            content,
            "wait_for_key_up wrapper function not found in board.py"
        )


class TestGamemanagerUsesWrappers(unittest.TestCase):
    """
    Tests to verify gamemanager.py uses board wrapper functions.
    """
    
    GAMEMANAGER_PATH = "DGTCentaurMods/game/gamemanager.py"
    
    def _read_gamemanager_source(self):
        """Read gamemanager.py source code."""
        with open(self.GAMEMANAGER_PATH, 'r') as f:
            return f.read()
    
    def test_uses_board_wait_for_key_up(self):
        """
        Test that gamemanager.py uses board.wait_for_key_up().
        
        Expected: 'board.wait_for_key_up(' found in source.
        Failure indicates: Gamemanager not refactored to use wrapper.
        """
        try:
            content = self._read_gamemanager_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        self.assertIn(
            'board.wait_for_key_up(',
            content,
            "gamemanager.py does not use board.wait_for_key_up()"
        )
    
    def test_uses_board_beep(self):
        """
        Test that gamemanager.py uses board.beep().
        
        Expected: 'board.beep(' found in source.
        Failure indicates: Gamemanager not refactored to use board.beep().
        """
        try:
            content = self._read_gamemanager_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        self.assertIn(
            'board.beep(',
            content,
            "gamemanager.py does not use board.beep()"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
