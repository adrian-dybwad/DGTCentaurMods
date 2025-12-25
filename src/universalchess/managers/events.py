# Event Constants
#
# This file is part of the Universal-Chess project
# ( https://github.com/adrian-dybwad/Universal-Chess )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

"""
Event constants for board and game events.

This lightweight module contains only event constants, avoiding heavy imports.
Use this module when you only need event constants (e.g., in emulators).
"""

# Game state events (values must match game.py)
EVENT_NEW_GAME = 1
EVENT_BLACK_TURN = 2
EVENT_WHITE_TURN = 3
EVENT_REQUEST_DRAW = 4
EVENT_RESIGN_GAME = 5

# Board events
EVENT_LIFT_PIECE = 6
EVENT_PLACE_PIECE = 7

# Player events
EVENT_PLAYER_READY = 8

__all__ = [
    'EVENT_NEW_GAME',
    'EVENT_BLACK_TURN',
    'EVENT_WHITE_TURN',
    'EVENT_REQUEST_DRAW',
    'EVENT_RESIGN_GAME',
    'EVENT_LIFT_PIECE',
    'EVENT_PLACE_PIECE',
    'EVENT_PLAYER_READY',
]
