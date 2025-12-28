"""Move-state tracking for physical-board interaction.

Tracks in-progress move information, including special handling for:
- rook-first castling sequences
- king lift resign gestures (timer-based)
"""

import threading
from typing import Optional

import chess

# Board constants
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
INVALID_SQUARE = -1

# Move constants
MIN_UCI_MOVE_LENGTH = 4

# Kings-in-center resign/draw detection center squares: d4, d5, e4, e5
CENTER_SQUARES = {chess.D4, chess.D5, chess.E4, chess.E5}


class MoveState:
    """Tracks the state of a move in progress.

    For castling, supports both king-first and rook-first move ordering.
    When rook is moved first during castling:
    1. Rook is lifted from h1/a1/h8/a8 -> tracked in castling_rook_source
    2. Rook is placed on f1/d1/f8/d8 -> tracked in castling_rook_placed
    3. King is lifted from e1/e8 -> tracked in source_square
    4. King is placed on g1/c1/g8/c8 -> castling move is executed using king move
    """

    # Castling square definitions (chess square indices 0=a1, 63=h8)
    WHITE_KING_SQUARE = chess.E1  # 4
    BLACK_KING_SQUARE = chess.E8  # 60

    WHITE_KINGSIDE_ROOK = chess.H1  # 7
    WHITE_QUEENSIDE_ROOK = chess.A1  # 0
    BLACK_KINGSIDE_ROOK = chess.H8  # 63
    BLACK_QUEENSIDE_ROOK = chess.A8  # 56

    WHITE_KINGSIDE_ROOK_DEST = chess.F1  # 5
    WHITE_QUEENSIDE_ROOK_DEST = chess.D1  # 3
    BLACK_KINGSIDE_ROOK_DEST = chess.F8  # 61
    BLACK_QUEENSIDE_ROOK_DEST = chess.D8  # 59

    WHITE_KINGSIDE_KING_DEST = chess.G1  # 6
    WHITE_QUEENSIDE_KING_DEST = chess.C1  # 2
    BLACK_KINGSIDE_KING_DEST = chess.G8  # 62
    BLACK_QUEENSIDE_KING_DEST = chess.C8  # 58

    def __init__(self):
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_destination_squares = []
        self.computer_move_uci = ""
        self.is_forced_move = False
        self.source_piece_color = None  # piece color when lifted (for captures)

        # Castling state for rook-first ordering
        self.castling_rook_source = INVALID_SQUARE
        self.castling_rook_placed = False
        self.late_castling_in_progress = False

        # King lift resign tracking
        self.king_lifted_square = INVALID_SQUARE
        self.king_lifted_color = None
        self.king_lift_timer: Optional[threading.Timer] = None

    def reset(self):
        """Reset all move state variables.
        
        Also clears any pending move broadcast to the web interface.
        """
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_destination_squares = []
        self.computer_move_uci = ""
        self.is_forced_move = False
        self.source_piece_color = None
        self.castling_rook_source = INVALID_SQUARE
        self.castling_rook_placed = False
        self.late_castling_in_progress = False
        self._cancel_king_lift_timer()
        self.king_lifted_square = INVALID_SQUARE
        self.king_lifted_color = None
        
        # Clear pending move from web broadcast
        from universalchess.services.game_broadcast import set_pending_move
        set_pending_move(None)

    def is_rook_castling_square(self, square: int) -> bool:
        """Check if a square is a rook's starting position for castling."""
        return square in (
            self.WHITE_KINGSIDE_ROOK,
            self.WHITE_QUEENSIDE_ROOK,
            self.BLACK_KINGSIDE_ROOK,
            self.BLACK_QUEENSIDE_ROOK,
        )

    def is_valid_rook_castling_destination(self, rook_source: int, rook_dest: int) -> bool:
        """Check if rook placement is valid for castling."""
        valid_pairs = {
            self.WHITE_KINGSIDE_ROOK: self.WHITE_KINGSIDE_ROOK_DEST,
            self.WHITE_QUEENSIDE_ROOK: self.WHITE_QUEENSIDE_ROOK_DEST,
            self.BLACK_KINGSIDE_ROOK: self.BLACK_KINGSIDE_ROOK_DEST,
            self.BLACK_QUEENSIDE_ROOK: self.BLACK_QUEENSIDE_ROOK_DEST,
        }
        return valid_pairs.get(rook_source) == rook_dest

    def get_castling_king_move(self, rook_source: int) -> str:
        """Get the king's UCI move for castling based on rook source."""
        castling_moves = {
            self.WHITE_KINGSIDE_ROOK: "e1g1",
            self.WHITE_QUEENSIDE_ROOK: "e1c1",
            self.BLACK_KINGSIDE_ROOK: "e8g8",
            self.BLACK_QUEENSIDE_ROOK: "e8c8",
        }
        return castling_moves.get(rook_source, "")

    def set_computer_move(self, uci_move: str, forced: bool = True):
        """Set the computer move that the player is expected to make."""
        if len(uci_move) < MIN_UCI_MOVE_LENGTH:
            return False
        self.computer_move_uci = uci_move
        self.is_forced_move = forced
        return True

    def _cancel_king_lift_timer(self):
        """Cancel any active king lift resign timer."""
        if self.king_lift_timer is not None:
            self.king_lift_timer.cancel()
            self.king_lift_timer = None


__all__ = [
    "MoveState",
    "BOARD_WIDTH",
    "PROMOTION_ROW_WHITE",
    "PROMOTION_ROW_BLACK",
    "INVALID_SQUARE",
    "MIN_UCI_MOVE_LENGTH",
    "CENTER_SQUARES",
]


