# Protocol Emulators
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

"""
Protocol emulators for chess board apps.

These modules emulate the protocols used by various chess board companion apps,
allowing the DGT Centaur to appear as different board types to those apps.
"""

from .chessnut import Chessnut
from .millennium import Millennium
from .pegasus import Pegasus

__all__ = ['Chessnut', 'Millennium', 'Pegasus']
