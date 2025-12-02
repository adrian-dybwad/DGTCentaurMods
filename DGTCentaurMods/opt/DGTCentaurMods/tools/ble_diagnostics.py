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


def check_dbus_ble_state(bus, device_address=None):
    """Check BLE state via D-Bus"""
    log.info(f"\n{'='*60}")
    log.info("D-Bus BLE State")
    log.info(f"{'='*60}")
    
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
                if device_address:
                    if dev_props.get('Address', '').upper() == device_address.upper():
                        devices.append((path, dev_props))
                else:
                    devices.append((path, dev_props))
        
        log.info(f"\nFound {len(devices)} BLE device(s):")
        for path, props in devices:
            log.info(f"  Device: {path}")
            log.info(f"    Address: {props.get('Address', 'N/A')}")
            log.info(f"    Name: {props.get('Name', 'N/A')}")
            log.info(f"    Alias: {props.get('Alias', 'N/A')}")
            log.info(f"    Connected: {props.get('Connected', 'N/A')}")
            log.info(f"    Paired: {props.get('Paired', 'N/A')}")
            log.info(f"    Trusted: {props.get('Trusted', 'N/A')}")
            log.info(f"    RSSI: {props.get('RSSI', 'N/A')}")
            log.info(f"    ServicesResolved: {props.get('ServicesResolved', 'N/A')}")
            log.info(f"    UUIDs: {props.get('UUIDs', [])}")
            
            # Check GATT services if connected
            if props.get('Connected', False):
                log.info(f"    Device is connected - checking GATT services...")
                try:
                    # Try to get GATT services
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


def check_system_logs():
    """Check recent BLE-related system logs"""
    run_command("journalctl -u bluetooth --since '5 minutes ago' --no-pager | tail -50", 
                "Recent Bluetooth Service Logs")
    run_command("dmesg | grep -i bluetooth | tail -20", "Recent Bluetooth Kernel Messages")


def check_ble_config_files():
    """Check BLE configuration files"""
    config_files = [
        "/etc/bluetooth/main.conf",
        "/etc/bluetooth/network.conf",
    ]
    
    log.info(f"\n{'='*60}")
    log.info("BLE Configuration Files")
    log.info(f"{'='*60}")
    
    for config_file in config_files:
        if os.path.exists(config_file):
            log.info(f"\n{config_file}:")
            try:
                with open(config_file, 'r') as f:
                    content = f.read()
                    log.info(content)
            except Exception as e:
                log.error(f"Error reading {config_file}: {e}")
        else:
            log.info(f"{config_file}: File not found")


def check_mtu_settings():
    """Check MTU-related settings"""
    run_command("cat /sys/kernel/debug/bluetooth/hci0/conn_info 2>/dev/null || echo 'conn_info not available'", 
                "HCI Connection Info (MTU)")
    run_command("ls -la /sys/kernel/debug/bluetooth/ 2>/dev/null || echo 'debugfs not available'", 
                "Bluetooth Debug FS")


def test_gatt_connection(device_address):
    """Test GATT connection with gatttool"""
    if not device_address:
        log.info("No device address provided, skipping GATT test")
        return
    
    log.info(f"\n{'='*60}")
    log.info(f"Testing GATT Connection to {device_address}")
    log.info(f"{'='*60}")
    
    # Try to discover services
    run_command(f"gatttool -b {device_address} --primary 2>&1 | head -20", 
                f"GATT Primary Services Discovery")
    
    # Try to connect
    run_command(f"timeout 5 gatttool -b {device_address} -I <<< 'connect' 2>&1 || echo 'Connection test completed'", 
                f"GATT Connection Test")


def main():
    """Main diagnostic function"""
    parser = argparse.ArgumentParser(description='BLE System Diagnostics')
    parser.add_argument('--device-address', 
                       help='BLE device address to check (optional)')
    args = parser.parse_args()
    
    log.info("="*60)
    log.info("BLE System Diagnostics")
    log.info("="*60)
    
    # Basic system info
    run_command("uname -a", "System Information")
    run_command("cat /proc/version", "Kernel Version")
    
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
    
    # D-Bus state
    try:
        bus = BleTools.get_bus()
        check_dbus_ble_state(bus, args.device_address)
    except Exception as e:
        log.error(f"Error accessing D-Bus: {e}")
    
    # System logs
    check_system_logs()
    
    # Configuration files
    check_ble_config_files()
    
    # MTU settings
    check_mtu_settings()
    
    # Test GATT connection if device address provided
    if args.device_address:
        test_gatt_connection(args.device_address)
    
    log.info(f"\n{'='*60}")
    log.info("Diagnostics Complete")
    log.info(f"{'='*60}")
    log.info("\nKey things to check:")
    log.info("1. Is Bluetooth service running and enabled?")
    log.info("2. Is the adapter powered and discoverable?")
    log.info("3. Are there any errors in system logs?")
    log.info("4. Is BlueZ version compatible?")
    log.info("5. Are GATT connections being established?")
    log.info("6. Is MTU negotiation working? (may need debugfs)")


if __name__ == "__main__":
    main()

