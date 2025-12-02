#!/usr/bin/env python3
"""
BLE System Diagnostics Tool

This tool checks all BLE-related system configuration and status on the Pi
to help diagnose why BLE clients aren't receiving data.

Usage:
    python3 tools/ble_diagnostics.py [--device-address AA:BB:CC:DD:EE:FF]
"""

import argparse
import subprocess
import sys
import os
import dbus
import dbus.mainloop.glib

# Ensure we import the repo package first
try:
    REPO_OPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if REPO_OPT not in sys.path:
        sys.path.insert(0, REPO_OPT)
except Exception as e:
    print(f"Warning: Could not add repo path: {e}")

from DGTCentaurMods.thirdparty.bletools import BleTools
from DGTCentaurMods.board.logging import log

BLUEZ_SERVICE_NAME = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
DEVICE_IFACE = "org.bluez.Device1"
ADAPTER_IFACE = "org.bluez.Adapter1"


def run_command(cmd, description):
    """Run a shell command and return output"""
    log.info(f"\n{'='*60}")
    log.info(f"{description}")
    log.info(f"{'='*60}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        log.info(f"Command: {cmd}")
        log.info(f"Exit code: {result.returncode}")
        if result.stdout:
            log.info(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            log.info(f"STDERR:\n{result.stderr}")
        return result
    except subprocess.TimeoutExpired:
        log.error(f"Command timed out: {cmd}")
        return None
    except Exception as e:
        log.error(f"Error running command: {e}")
        return None


def check_bluez_version():
    """Check BlueZ version"""
    run_command("bluetoothctl --version", "BlueZ Version")
    run_command("dpkg -l | grep bluez", "BlueZ Package Info")


def check_bluetooth_service():
    """Check Bluetooth service status"""
    run_command("systemctl status bluetooth", "Bluetooth Service Status")
    run_command("systemctl is-active bluetooth", "Bluetooth Service Active Status")
    run_command("systemctl is-enabled bluetooth", "Bluetooth Service Enabled Status")


def check_adapter_status():
    """Check BLE adapter status"""
    run_command("hciconfig", "HCI Adapter Configuration")
    run_command("hciconfig hci0", "HCI0 Detailed Info")
    run_command("hciconfig hci0 up", "Bringing HCI0 Up (if needed)")
    run_command("hciconfig hci0", "HCI0 Status After Up")


def check_bluetoothctl_info():
    """Check bluetoothctl info"""
    run_command("bluetoothctl show", "Bluetooth Adapter Info")
    run_command("bluetoothctl list", "Bluetooth Adapter List")


def check_gatttool():
    """Check gatttool availability"""
    run_command("which gatttool", "Gatttool Location")
    run_command("gatttool --help | head -20", "Gatttool Help (first 20 lines)")


def check_ble_connections():
    """Check active BLE connections"""
    run_command("hcitool con", "Active HCI Connections")
    run_command("bluetoothctl devices", "Paired/Trusted Devices")


def check_dbus_ble_state(bus):
    """Check BLE state via D-Bus and return discovered devices"""
    log.info(f"\n{'='*60}")
    log.info("D-Bus BLE State")
    log.info(f"{'='*60}")
    
    discovered_devices = []
    
    try:
        remote_om = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        
        # Find adapters
        adapters = []
        for path, interfaces in objects.items():
            if ADAPTER_IFACE in interfaces:
                adapters.append((path, interfaces[ADAPTER_IFACE]))
        
        log.info(f"Found {len(adapters)} Bluetooth adapter(s):")
        for path, props in adapters:
            log.info(f"  Adapter: {path}")
            log.info(f"    Address: {props.get('Address', 'N/A')}")
            log.info(f"    Name: {props.get('Name', 'N/A')}")
            log.info(f"    Alias: {props.get('Alias', 'N/A')}")
            log.info(f"    Powered: {props.get('Powered', 'N/A')}")
            log.info(f"    Discoverable: {props.get('Discoverable', 'N/A')}")
            log.info(f"    Pairable: {props.get('Pairable', 'N/A')}")
            log.info(f"    Discovering: {props.get('Discovering', 'N/A')}")
            log.info(f"    UUIDs: {props.get('UUIDs', [])}")
        
        # Find devices
        devices = []
        for path, interfaces in objects.items():
            if DEVICE_IFACE in interfaces:
                dev_props = interfaces[DEVICE_IFACE]
                devices.append((path, dev_props))
        
        log.info(f"\nFound {len(devices)} BLE device(s):")
        for path, props in devices:
            address = props.get('Address', 'N/A')
            name = props.get('Name', 'N/A')
            alias = props.get('Alias', 'N/A')
            connected = props.get('Connected', False)
            
            log.info(f"  Device: {path}")
            log.info(f"    Address: {address}")
            log.info(f"    Name: {name}")
            log.info(f"    Alias: {alias}")
            log.info(f"    Connected: {connected}")
            log.info(f"    Paired: {props.get('Paired', 'N/A')}")
            log.info(f"    Trusted: {props.get('Trusted', 'N/A')}")
            log.info(f"    RSSI: {props.get('RSSI', 'N/A')}")
            log.info(f"    ServicesResolved: {props.get('ServicesResolved', 'N/A')}")
            log.info(f"    UUIDs: {props.get('UUIDs', [])}")
            
            # Store device info for later testing
            if address != 'N/A':
                discovered_devices.append({
                    'address': address,
                    'name': name,
                    'alias': alias,
                    'connected': connected,
                    'path': path
                })
            
            # Check GATT services if connected
            if connected:
                log.info(f"    Device is connected - checking GATT services...")
                try:
                    device_obj = bus.get_object(BLUEZ_SERVICE_NAME, path)
                    device_props = dbus.Interface(device_obj, DBUS_PROP_IFACE)
                    gatt_services = device_props.Get(DEVICE_IFACE, "GattServices")
                    log.info(f"    GATT Services: {gatt_services}")
                except Exception as e:
                    log.warning(f"    Could not get GATT services: {e}")
        
    except Exception as e:
        log.error(f"Error checking D-Bus BLE state: {e}")
        import traceback
        log.error(traceback.format_exc())
    
    return discovered_devices


def check_system_logs():
    """Check recent BLE-related system logs"""
    run_command("journalctl -u bluetooth --since '5 minutes ago' --no-pager | tail -50", 
                "Recent Bluetooth Service Logs")
    run_command("dmesg | grep -i bluetooth | tail -20", "Recent Bluetooth Kernel Messages")


def check_ble_config_files():
    """Check BLE configuration files and suggest MTU fix"""
    config_files = [
        "/etc/bluetooth/main.conf",
        "/etc/bluetooth/network.conf",
    ]
    
    log.info(f"\n{'='*60}")
    log.info("BLE Configuration Files")
    log.info(f"{'='*60}")
    
    mtu_found = False
    mtu_enabled = False
    
    for config_file in config_files:
        if os.path.exists(config_file):
            log.info(f"\n{config_file}:")
            try:
                with open(config_file, 'r') as f:
                    content = f.read()
                    log.info(content)
                    
                    # Check for MTU setting
                    if 'ExchangeMTU' in content:
                        mtu_found = True
                        # Check if it's enabled (not commented)
                        for line in content.split('\n'):
                            if 'ExchangeMTU' in line and not line.strip().startswith('#'):
                                mtu_enabled = True
                                log.info(f"\n*** FOUND: ExchangeMTU is enabled in {config_file} ***")
                                # Extract the value
                                import re
                                match = re.search(r'ExchangeMTU\s*=\s*(\d+)', line)
                                if match:
                                    mtu_value = int(match.group(1))
                                    log.info(f"*** MTU is set to {mtu_value} bytes ***")
                                    if mtu_value >= 500:
                                        log.info("*** MTU is sufficient for Chessnut (needs 500) ***")
                                    else:
                                        log.warning(f"*** MTU {mtu_value} is too small for Chessnut (needs 500) ***")
            except Exception as e:
                log.error(f"Error reading {config_file}: {e}")
        else:
            log.info(f"{config_file}: File not found")
    
    if mtu_found and not mtu_enabled:
        log.info(f"\n{'='*60}")
        log.info("MTU CONFIGURATION ISSUE DETECTED")
        log.info(f"{'='*60}")
        log.warning("ExchangeMTU is commented out in /etc/bluetooth/main.conf")
        log.warning("This means BLE connections will use default MTU of 23 bytes")
        log.warning("Chessnut Air needs MTU of 500 bytes for 36-byte FEN packets")
        log.info("\nTo fix this, edit /etc/bluetooth/main.conf and uncomment/modify:")
        log.info("  Change: #ExchangeMTU = 517")
        log.info("  To:     ExchangeMTU = 500")
        log.info("\nThen restart Bluetooth service:")
        log.info("  sudo systemctl restart bluetooth")
    elif not mtu_found:
        log.warning("\nExchangeMTU setting not found in config files")
        log.warning("You may need to add it manually to /etc/bluetooth/main.conf under [GATT] section")


def check_mtu_settings():
    """Check MTU-related settings"""
    run_command("cat /sys/kernel/debug/bluetooth/hci0/conn_info 2>/dev/null || echo 'conn_info not available'", 
                "HCI Connection Info (MTU)")
    run_command("ls -la /sys/kernel/debug/bluetooth/ 2>/dev/null || echo 'debugfs not available'", 
                "Bluetooth Debug FS")


def test_gatt_connection(device_address, device_name=None):
    """Test GATT connection with gatttool"""
    if not device_address:
        return
    
    name_str = f" ({device_name})" if device_name else ""
    log.info(f"\n{'='*60}")
    log.info(f"Testing GATT Connection to {device_address}{name_str}")
    log.info(f"{'='*60}")
    
    # Try to discover services
    run_command(f"gatttool -b {device_address} --primary 2>&1", 
                f"GATT Primary Services Discovery")
    
    # Try to discover characteristics for Chessnut services
    if 'chessnut' in (device_name or '').lower():
        log.info(f"\n{'='*60}")
        log.info("Testing Chessnut-specific GATT characteristics")
        log.info(f"{'='*60}")
        
        # FEN Notification Service
        run_command(f"gatttool -b {device_address} --char-desc 0x0100 0x0103 2>&1", 
                    "FEN Notification Service Characteristics")
        
        # Operation Commands Service
        run_command(f"gatttool -b {device_address} --char-desc 0x0200 0x0205 2>&1", 
                    "Operation Commands Service Characteristics")
    
    # Try to get characteristics with properties
    run_command(f"gatttool -b {device_address} --characteristics 0x0001 0xffff 2>&1 | head -50", 
                f"All Characteristics (first 50)")
    
    # Check MTU (if available)
    run_command(f"timeout 3 gatttool -b {device_address} -I <<< $'connect\nmtu\n' 2>&1 | head -20 || echo 'MTU check not available'", 
                f"MTU Check")


def check_permissions():
    """Check user permissions for Bluetooth"""
    log.info(f"\n{'='*60}")
    log.info("User Permissions")
    log.info(f"{'='*60}")
    run_command("whoami", "Current User")
    run_command("groups", "User Groups")
    run_command("id", "User ID and Groups")
    run_command("ls -la /var/lib/bluetooth/ 2>/dev/null | head -10 || echo 'Cannot access bluetooth directory'", 
                "Bluetooth Directory Permissions")


def check_kernel_modules():
    """Check loaded Bluetooth kernel modules"""
    run_command("lsmod | grep -i bluetooth", "Loaded Bluetooth Kernel Modules")
    run_command("modinfo bluetooth 2>/dev/null | head -10 || echo 'bluetooth module info not available'", 
                "Bluetooth Module Info")


def main():
    """Main diagnostic function - runs all diagnostics automatically"""
    parser = argparse.ArgumentParser(description='BLE System Diagnostics (Auto-run)')
    parser.add_argument('--device-address', 
                       help='Specific BLE device address to test (optional, auto-discovers if not provided)')
    args = parser.parse_args()
    
    log.info("="*80)
    log.info("BLE SYSTEM DIAGNOSTICS - AUTO-RUN")
    log.info("="*80)
    log.info("This script will automatically check all BLE system components")
    log.info("="*80)
    
    # Basic system info
    run_command("uname -a", "System Information")
    run_command("cat /proc/version", "Kernel Version")
    run_command("cat /etc/os-release 2>/dev/null | head -10 || echo 'OS release not available'", 
                "OS Release Info")
    
    # Permissions
    check_permissions()
    
    # Kernel modules
    check_kernel_modules()
    
    # BlueZ and Bluetooth service
    check_bluez_version()
    check_bluetooth_service()
    
    # Adapter status
    check_adapter_status()
    check_bluetoothctl_info()
    
    # GATT tools
    check_gatttool()
    
    # Connections
    check_ble_connections()
    
    # D-Bus state and device discovery
    discovered_devices = []
    try:
        bus = BleTools.get_bus()
        discovered_devices = check_dbus_ble_state(bus)
    except Exception as e:
        log.error(f"Error accessing D-Bus: {e}")
        import traceback
        log.error(traceback.format_exc())
    
    # System logs
    check_system_logs()
    
    # Configuration files
    check_ble_config_files()
    
    # MTU settings
    check_mtu_settings()
    
    # Test GATT connections
    devices_to_test = []
    if args.device_address:
        # Test specific device
        devices_to_test.append({
            'address': args.device_address,
            'name': 'User specified'
        })
    else:
        # Auto-discover and test all devices, prioritizing Chessnut Air
        chessnut_devices = [d for d in discovered_devices if 'chessnut' in (d.get('name', '') + d.get('alias', '')).lower()]
        other_devices = [d for d in discovered_devices if 'chessnut' not in (d.get('name', '') + d.get('alias', '')).lower()]
        
        # Test Chessnut devices first
        devices_to_test.extend(chessnut_devices)
        devices_to_test.extend(other_devices)
    
    if devices_to_test:
        log.info(f"\n{'='*80}")
        log.info(f"Testing GATT connections for {len(devices_to_test)} device(s)")
        log.info(f"{'='*80}")
        for device in devices_to_test:
            test_gatt_connection(device['address'], device.get('name') or device.get('alias'))
    else:
        log.info("\nNo devices found to test. Try connecting to a device first.")
    
    # Summary
    log.info(f"\n{'='*80}")
    log.info("DIAGNOSTICS COMPLETE")
    log.info(f"{'='*80}")
    log.info("\nSUMMARY - Key things to check:")
    log.info("1. Is Bluetooth service running and enabled?")
    log.info("2. Is the adapter powered and discoverable?")
    log.info("3. Are there any errors in system logs?")
    log.info("4. Is BlueZ version compatible? (5.50+ recommended)")
    log.info("5. Are GATT connections being established?")
    log.info("6. Is MTU negotiation working? (default 23 bytes, Chessnut needs 500)")
    log.info("7. Are notifications being enabled successfully?")
    log.info("8. Check if user has bluetooth group membership")
    log.info("\nKNOWN ISSUES:")
    log.info("- gatttool does not support explicit MTU exchange")
    log.info("- Default MTU (23 bytes) may be too small for 36-byte FEN packets")
    log.info("- May need Python BLE library (bleak/bluepy) for proper MTU handling")
    log.info(f"{'='*80}")


if __name__ == "__main__":
    main()

