"""
Bluetooth status module.

Provides functions to query Bluetooth adapter status and format
Bluetooth information for display in menus.
"""

import subprocess
from typing import Optional, List

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# Advertised service names for different protocols
ADVERTISED_NAMES = {
    'pegasus': 'DGT PEGASUS',
    'millennium': 'MILLENNIUM CHESS',
    'chessnut': 'Chessnut Air',
}


def get_bluetooth_status(device_name: str = "DGT PEGASUS",
                         ble_manager=None,
                         rfcomm_connected: bool = False) -> dict:
    """Get current Bluetooth adapter status and information.
    
    Args:
        device_name: The primary advertised device name
        ble_manager: Optional BleManager instance to check BLE connection status
        rfcomm_connected: Whether an RFCOMM client is connected
    
    Returns:
        Dictionary with keys:
        - enabled: bool, whether Bluetooth is enabled (not blocked by rfkill)
        - powered: bool, whether adapter is powered on
        - device_name: str, the primary advertised device name
        - address: str, the Bluetooth MAC address
        - ble_connected: bool, whether a BLE client is connected
        - ble_client_type: str or None, type of connected BLE client
        - rfcomm_connected: bool, whether an RFCOMM client is connected
        - advertised_names: list of str, all names being advertised
    """
    status = {
        'enabled': False,
        'powered': False,
        'device_name': device_name,
        'address': '',
        'ble_connected': False,
        'ble_client_type': None,
        'rfcomm_connected': rfcomm_connected,
        'advertised_names': list(ADVERTISED_NAMES.values()),
    }
    
    # Check rfkill status
    try:
        result = subprocess.run(['rfkill', 'list', 'bluetooth'],
                               capture_output=True, text=True, timeout=5)
        # If "Soft blocked: no" is in output, Bluetooth is enabled
        status['enabled'] = 'Soft blocked: no' in result.stdout
    except Exception as e:
        log.warning(f"[Bluetooth] Failed to check rfkill status: {e}")
    
    # Get adapter address via hciconfig
    try:
        result = subprocess.run(['hciconfig', 'hci0'],
                               capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Parse output for BD Address
            for line in result.stdout.split('\n'):
                if 'BD Address:' in line:
                    parts = line.split('BD Address:')
                    if len(parts) > 1:
                        addr = parts[1].strip().split()[0]
                        status['address'] = addr
                if 'UP RUNNING' in line:
                    status['powered'] = True
    except Exception as e:
        log.warning(f"[Bluetooth] Failed to get adapter info: {e}")
    
    # Check BLE connection status
    if ble_manager is not None:
        status['ble_connected'] = ble_manager.connected
        status['ble_client_type'] = ble_manager.client_type
    
    return status


def format_status_label(status: dict) -> str:
    """Format Bluetooth status into a multi-line label for display.
    
    Shows device name, MAC address, connection status, and connected client type.
    
    Args:
        status: Dictionary from get_bluetooth_status()
        
    Returns:
        Multi-line string for display
    """
    lines = []
    
    # Device name
    lines.append(status['device_name'])
    
    # MAC address
    if status['address']:
        lines.append(status['address'])
    
    # Connection status
    if status['ble_connected']:
        client_type = status.get('ble_client_type', 'BLE')
        if client_type:
            lines.append(f"BLE: {client_type}")
        else:
            lines.append("BLE: Connected")
    elif status['rfcomm_connected']:
        lines.append("RFCOMM: Connected")
    elif status['enabled'] and status['powered']:
        lines.append("Ready")
    elif status['enabled']:
        lines.append("Enabled")
    else:
        lines.append("Disabled")
    
    return '\n'.join(lines)


def get_advertised_names_label() -> str:
    """Get a formatted label showing all advertised names.
    
    Returns:
        Multi-line string with all advertised names
    """
    return '\n'.join(ADVERTISED_NAMES.values())


def enable_bluetooth() -> bool:
    """Enable Bluetooth via rfkill.
    
    Returns:
        True if command succeeded, False otherwise
    """
    try:
        subprocess.run(['sudo', 'rfkill', 'unblock', 'bluetooth'], timeout=5)
        log.info("[Bluetooth] Enabled via rfkill")
        return True
    except Exception as e:
        log.error(f"[Bluetooth] Failed to enable: {e}")
        return False


def disable_bluetooth() -> bool:
    """Disable Bluetooth via rfkill.
    
    Returns:
        True if command succeeded, False otherwise
    """
    try:
        subprocess.run(['sudo', 'rfkill', 'block', 'bluetooth'], timeout=5)
        log.info("[Bluetooth] Disabled via rfkill")
        return True
    except Exception as e:
        log.error(f"[Bluetooth] Failed to disable: {e}")
        return False
