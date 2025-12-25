# Protocol Emulators
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
Protocol emulators for chess board apps.

These modules emulate the protocols used by various chess board companion apps,
allowing Universal Chess to appear as different board types to those apps.

Includes:
- Chessnut: Chessnut Air protocol (BLE)
- Millennium: Millennium ChessLink protocol (BLE/RFCOMM)
- Pegasus: DGT Pegasus protocol (BLE)

"""

import time as _t
import logging as _log
_logger = _log.getLogger(__name__)
_s = _t.time()

from .chessnut import Chessnut
_logger.debug(f"[emulators init] chessnut: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from .millennium import Millennium
_logger.debug(f"[emulators init] millennium: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from .pegasus import Pegasus
_logger.debug(f"[emulators init] pegasus: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

__all__ = ['Chessnut', 'Millennium', 'Pegasus']
