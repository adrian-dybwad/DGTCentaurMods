"""
WiFi status information module.

Provides functions to query WiFi adapter status and format
WiFi information for display in menus.
"""

import subprocess
from typing import Optional, Tuple

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


def get_wifi_status() -> dict:
    """Get current WiFi adapter status and connection information.
    
    Returns:
        Dictionary with keys:
        - enabled: bool, whether WiFi is enabled (not blocked by rfkill)
        - connected: bool, whether connected to a network
        - ssid: str, current network SSID (empty if not connected)
        - ip_address: str, IP address (empty if not connected)
        - netmask: str, subnet mask (empty if not available)
        - gateway: str, default gateway (empty if not available)
        - signal: int, signal strength percentage (0-100, 0 if not connected)
        - frequency: str, connection frequency (e.g., "2.4 GHz", empty if not connected)
        - mac_address: str, WiFi adapter MAC address
    """
    status = {
        'enabled': False,
        'connected': False,
        'ssid': '',
        'ip_address': '',
        'netmask': '',
        'gateway': '',
        'signal': 0,
        'frequency': '',
        'mac_address': '',
    }
    
    # Check rfkill status
    try:
        result = subprocess.run(['rfkill', 'list', 'wifi'],
                               capture_output=True, text=True, timeout=5)
        # If "Soft blocked: no" is in output, WiFi is enabled
        status['enabled'] = 'Soft blocked: no' in result.stdout
    except Exception as e:
        log.warning(f"[WiFi] Failed to check rfkill status: {e}")
    
    # Get SSID
    try:
        result = subprocess.run(['iwgetid', '-r'],
                               capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            status['ssid'] = result.stdout.strip()
            status['connected'] = True
    except Exception as e:
        log.warning(f"[WiFi] Failed to get SSID: {e}")
    
    # Get IP address and netmask via ip command
    if status['connected']:
        try:
            result = subprocess.run(['ip', '-o', '-4', 'addr', 'show', 'wlan0'],
                                   capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                # Parse output like: "3: wlan0    inet 192.168.1.100/24 brd 192.168.1.255 scope global wlan0"
                parts = result.stdout.split()
                for i, part in enumerate(parts):
                    if part == 'inet' and i + 1 < len(parts):
                        ip_cidr = parts[i + 1]
                        if '/' in ip_cidr:
                            ip, cidr = ip_cidr.split('/')
                            status['ip_address'] = ip
                            # Convert CIDR to netmask
                            cidr_int = int(cidr)
                            mask = (0xffffffff >> (32 - cidr_int)) << (32 - cidr_int)
                            status['netmask'] = f"{(mask >> 24) & 0xff}.{(mask >> 16) & 0xff}.{(mask >> 8) & 0xff}.{mask & 0xff}"
                        else:
                            status['ip_address'] = ip_cidr
                        break
        except Exception as e:
            log.warning(f"[WiFi] Failed to get IP address: {e}")
        
        # Fallback to hostname -I if ip command didn't work
        if not status['ip_address']:
            try:
                result = subprocess.run(['hostname', '-I'],
                                       capture_output=True, text=True, timeout=5)
                ips = result.stdout.strip().split()
                if ips:
                    status['ip_address'] = ips[0]
            except Exception:
                pass
    
    # Get gateway
    try:
        result = subprocess.run(['ip', 'route', 'show', 'default'],
                               capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Parse output like: "default via 192.168.1.1 dev wlan0"
            parts = result.stdout.split()
            for i, part in enumerate(parts):
                if part == 'via' and i + 1 < len(parts):
                    status['gateway'] = parts[i + 1]
                    break
    except Exception as e:
        log.warning(f"[WiFi] Failed to get gateway: {e}")
    
    # Get signal strength and frequency via iwconfig
    if status['connected']:
        try:
            result = subprocess.run(['iwconfig', 'wlan0'],
                                   capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                output = result.stdout
                
                # Parse signal level (e.g., "Signal level=-45 dBm")
                import re
                signal_match = re.search(r'Signal level[=:](-?\d+)', output)
                if signal_match:
                    dbm = int(signal_match.group(1))
                    # Convert dBm to percentage (rough approximation)
                    # -30 dBm = 100%, -90 dBm = 0%
                    percentage = max(0, min(100, (dbm + 90) * 100 // 60))
                    status['signal'] = percentage
                
                # Parse frequency (e.g., "Frequency:2.437 GHz")
                freq_match = re.search(r'Frequency[=:](\d+\.?\d*)\s*GHz', output)
                if freq_match:
                    freq = float(freq_match.group(1))
                    if freq < 3:
                        status['frequency'] = "2.4 GHz"
                    else:
                        status['frequency'] = "5 GHz"
        except Exception as e:
            log.warning(f"[WiFi] Failed to get signal info: {e}")
    
    # Get MAC address
    try:
        result = subprocess.run(['cat', '/sys/class/net/wlan0/address'],
                               capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            status['mac_address'] = result.stdout.strip().upper()
    except Exception as e:
        log.warning(f"[WiFi] Failed to get MAC address: {e}")
    
    return status


def format_status_label(status: dict) -> str:
    """Format WiFi status into a multi-line label for display.
    
    Shows SSID, IP address, signal strength, and other connection details.
    
    Args:
        status: Dictionary from get_wifi_status()
        
    Returns:
        Multi-line string for display
    """
    lines = []
    
    if status['connected']:
        # Connected - show network details
        lines.append(status['ssid'])
        
        if status['ip_address']:
            lines.append(status['ip_address'])
        
        if status['signal'] > 0:
            lines.append(f"Signal: {status['signal']}%")
        
        if status['frequency']:
            lines.append(status['frequency'])
    elif status['enabled']:
        lines.append("Not connected")
        lines.append("WiFi enabled")
    else:
        lines.append("WiFi disabled")
    
    return '\n'.join(lines)


def enable_wifi() -> bool:
    """Enable WiFi via rfkill.
    
    Returns:
        True if command succeeded, False otherwise
    """
    try:
        subprocess.run(['sudo', 'rfkill', 'unblock', 'wifi'], timeout=5)
        log.info("[WiFi] Enabled via rfkill")
        return True
    except Exception as e:
        log.error(f"[WiFi] Failed to enable: {e}")
        return False


def disable_wifi() -> bool:
    """Disable WiFi via rfkill.
    
    Returns:
        True if command succeeded, False otherwise
    """
    try:
        subprocess.run(['sudo', 'rfkill', 'block', 'wifi'], timeout=5)
        log.info("[WiFi] Disabled via rfkill")
        return True
    except Exception as e:
        log.error(f"[WiFi] Failed to disable: {e}")
        return False
