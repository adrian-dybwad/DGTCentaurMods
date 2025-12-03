"""
BLE Client modules for connecting to chess boards.

This package contains:
- BLEClient: Generic bleak-based BLE client with PreferredBearer support
- GatttoolClient: Fallback gatttool-based client for devices with BlueZ GATT issues
- MillenniumClient: Protocol handler for Millennium ChessLink boards
- ChessnutClient: Protocol handler for Chessnut Air boards
- PegasusClient: Protocol handler for DGT Pegasus boards
"""

from DGTCentaurMods.tools.clients.ble_client import BLEClient
from DGTCentaurMods.tools.clients.gatttool_client import GatttoolClient
from DGTCentaurMods.tools.clients.millennium_client import MillenniumClient
from DGTCentaurMods.tools.clients.chessnut_client import ChessnutClient
from DGTCentaurMods.tools.clients.pegasus_client import PegasusClient

__all__ = [
    'BLEClient',
    'GatttoolClient',
    'MillenniumClient',
    'ChessnutClient',
    'PegasusClient',
]

