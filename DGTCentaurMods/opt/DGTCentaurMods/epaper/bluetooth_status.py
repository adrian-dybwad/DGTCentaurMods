"""
Bluetooth status module.

Provides functions to query Bluetooth adapter status and a widget for
displaying Bluetooth information in menus.
"""

import subprocess
from typing import Optional

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


def get_bluetooth_status(device_name: str = "DGT PEGASUS",
                         ble_manager=None,
                         rfcomm_connected: bool = False) -> dict:
    """Get current Bluetooth adapter status and information.
    
    Args:
        device_name: The advertised device name
        ble_manager: Optional BleManager instance to check BLE connection status
        rfcomm_connected: Whether an RFCOMM client is connected
    
    Returns:
        Dictionary with keys:
        - enabled: bool, whether Bluetooth is enabled (not blocked by rfkill)
        - powered: bool, whether adapter is powered on
        - device_name: str, the advertised device name
        - address: str, the Bluetooth MAC address
        - ble_connected: bool, whether a BLE client is connected
        - rfcomm_connected: bool, whether an RFCOMM client is connected
    """
    status = {
        'enabled': False,
        'powered': False,
        'device_name': device_name,
        'address': '',
        'ble_connected': False,
        'rfcomm_connected': rfcomm_connected,
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
    
    return status


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
