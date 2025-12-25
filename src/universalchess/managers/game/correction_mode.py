"""Correction mode state.

Correction mode is used when the physical board does not match the authoritative
logical `chess.Board` state. The manager guides the user to fix misplaced pieces.
"""


class CorrectionMode:
    """Manages correction mode for fixing misplaced pieces."""

    def __init__(self):
        self.is_active = False
        self.expected_state = None
        self.just_exited = False

    def enter(self, expected_state):
        """Enter correction mode."""
        self.is_active = True
        self.expected_state = expected_state
        self.just_exited = False

    def exit(self):
        """Exit correction mode."""
        self.is_active = False
        self.expected_state = None
        self.just_exited = True

    def clear_exit_flag(self):
        """Clear the just-exited flag."""
        self.just_exited = False


__all__ = ["CorrectionMode"]


