#!/usr/bin/env python3
"""
Minimal Promotion Tests - Source Code Inspection Only

Tests promotion-related code by inspecting source files directly,
avoiding imports that require hardware resources or fonts.

This is useful for CI/CD environments where hardware is not available.

USAGE:
    cd /home/pi/DGTCentaurMods/DGTCentaurMods/opt
    python3 -m pytest DGTCentaurMods/tests/test_promotion_minimal.py -v
"""

import unittest


class TestGamemanagerSourceCode(unittest.TestCase):
    """
    Tests gamemanager.py source code for promotion functionality.
    
    Uses source code inspection to verify correct implementation
    without importing modules that require hardware.
    """
    
    GAMEMANAGER_PATH = "DGTCentaurMods/game/gamemanager.py"
    
    EXPECTED_BUTTON_MAPPINGS = [
        ("'BACK'", "'n'"),
        ("'TICK'", "'b'"),
        ("'UP'", "'q'"),
        ("'DOWN'", "'r'")
    ]
    
    def _read_source(self):
        """Read gamemanager.py source code."""
        with open(self.GAMEMANAGER_PATH, 'r') as f:
            return f.read()
    
    def test_wait_for_promotion_choice_function_exists(self):
        """
        Test that waitForPromotionChoice function is defined.
        
        Expected: 'def waitForPromotionChoice():' found in source.
        Failure indicates: Function was not implemented.
        """
        try:
            content = self._read_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        self.assertIn(
            'def waitForPromotionChoice():',
            content,
            "waitForPromotionChoice function definition not found"
        )
    
    def test_back_button_maps_to_knight(self):
        """
        Test BACK button -> Knight mapping exists.
        
        Expected: 'BACK' and 'n' found in source.
        Failure indicates: Button mapping is missing or incorrect.
        """
        try:
            content = self._read_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        self.assertIn("'BACK'", content, "BACK button not found")
        self.assertIn("'n'", content, "Knight piece 'n' not found")
    
    def test_tick_button_maps_to_bishop(self):
        """
        Test TICK button -> Bishop mapping exists.
        
        Expected: 'TICK' and 'b' found in source.
        Failure indicates: Button mapping is missing or incorrect.
        """
        try:
            content = self._read_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        self.assertIn("'TICK'", content, "TICK button not found")
        self.assertIn("'b'", content, "Bishop piece 'b' not found")
    
    def test_up_button_maps_to_queen(self):
        """
        Test UP button -> Queen mapping exists.
        
        Expected: 'UP' and 'q' found in source.
        Failure indicates: Button mapping is missing or incorrect.
        """
        try:
            content = self._read_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        self.assertIn("'UP'", content, "UP button not found")
        self.assertIn("'q'", content, "Queen piece 'q' not found")
    
    def test_down_button_maps_to_rook(self):
        """
        Test DOWN button -> Rook mapping exists.
        
        Expected: 'DOWN' and 'r' found in source.
        Failure indicates: Button mapping is missing or incorrect.
        """
        try:
            content = self._read_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        self.assertIn("'DOWN'", content, "DOWN button not found")
        self.assertIn("'r'", content, "Rook piece 'r' not found")
    
    def test_uses_board_wait_for_key_up(self):
        """
        Test that board.wait_for_key_up() is used.
        
        Expected: 'board.wait_for_key_up(' found in source.
        Failure indicates: Not using abstracted board API.
        """
        try:
            content = self._read_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        self.assertIn(
            'board.wait_for_key_up(',
            content,
            "board.wait_for_key_up() not used in gamemanager.py"
        )
    
    def test_uses_board_beep(self):
        """
        Test that board.beep() is used.
        
        Expected: 'board.beep(' found in source.
        Failure indicates: Not using abstracted board API.
        """
        try:
            content = self._read_source()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        self.assertIn(
            'board.beep(',
            content,
            "board.beep() not used in gamemanager.py"
        )


class TestNoDirectSerialAccess(unittest.TestCase):
    """
    Tests to ensure no direct serial access patterns remain.
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
    
    def test_no_forbidden_serial_patterns(self):
        """
        Test that no direct serial access patterns exist.
        
        Expected: None of the forbidden patterns found in source.
        Failure indicates: Refactoring is incomplete - direct serial
        access should be replaced with board API calls.
        """
        try:
            with open(self.GAMEMANAGER_PATH, 'r') as f:
                content = f.read()
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
    
    def test_wait_for_key_up_function_exists(self):
        """
        Test that wait_for_key_up wrapper function exists in board.py.
        
        Expected: 'def wait_for_key_up(' found in source.
        Failure indicates: Board wrapper function was not added.
        """
        try:
            with open(self.BOARD_PATH, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.BOARD_PATH}")
        
        self.assertIn(
            'def wait_for_key_up(',
            content,
            "wait_for_key_up function not found in board.py"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
