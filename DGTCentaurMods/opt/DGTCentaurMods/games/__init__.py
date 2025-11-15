# Games module
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

"""
Games module providing chess game management and UCI engine integration.

This module contains:
- manager: Complete chess game state management with event-driven notifications
- uci: UCI engine handler that reacts to game events and manages engine lifecycle
"""

from DGTCentaurMods.games.manager import GameManager, EVENT_NEW_GAME, EVENT_WHITE_TURN, EVENT_BLACK_TURN, EVENT_GAME_OVER, EVENT_MOVE_MADE, EVENT_ILLEGAL_MOVE, EVENT_PROMOTION_NEEDED
from DGTCentaurMods.games.uci import UCIHandler

__all__ = [
    'GameManager',
    'UCIHandler',
    'EVENT_NEW_GAME',
    'EVENT_WHITE_TURN',
    'EVENT_BLACK_TURN',
    'EVENT_GAME_OVER',
    'EVENT_MOVE_MADE',
    'EVENT_ILLEGAL_MOVE',
    'EVENT_PROMOTION_NEEDED',
]

