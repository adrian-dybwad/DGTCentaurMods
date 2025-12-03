"""
BLE Client modules for connecting to chess boards.

This package contains:
- BLEClient: Generic bleak-based BLE client with PreferredBearer support
- GatttoolClient: Fallback gatttool-based client for devices with BlueZ GATT issues
"""

from DGTCentaurMods.tools.clients.ble_client import BLEClient
from DGTCentaurMods.tools.clients.gatttool_client import GatttoolClient

__all__ = ['BLEClient', 'GatttoolClient']

