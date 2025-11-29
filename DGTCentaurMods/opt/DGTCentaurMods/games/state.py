# State Game
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

import chess


class State:
    """Manages chess board state using FEN notation."""
    
    def __init__(self):
        """Initialize the State handler."""
        self.board = chess.Board()
    
    def setFEN(self, fen):
        """Set the chess board state from a FEN string.
        
        Args:
            fen: FEN string representing the chess position
        """
        self.board = chess.Board(fen)
    
    def getFEN(self, format=False):
        """Get the current FEN string.
        
        Args:
            format: If True, replace numbers with periods and remove slashes in the FEN string
            
        Returns:
            str: FEN string representation of the current board state
        """
        fen = self.board.fen()
        
        if format:
            # Replace numbers with periods
            import re
            fen = re.sub(r'\d', lambda m: '.' * int(m.group()), fen)
            # Replace / with nothing
            fen = fen.replace('/', '')
        
        return fen

