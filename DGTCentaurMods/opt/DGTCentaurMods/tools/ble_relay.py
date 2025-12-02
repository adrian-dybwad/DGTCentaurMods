#!/usr/bin/env python3
"""
BLE Scanner Tool for Chessnut Air

This tool connects to a BLE device called "Chessnut Air" and logs all data received.

Usage:
    python3 tools/ble_relay.py
"""

import argparse
import sys
import os
import time
import threading
import signal
import subprocess
import re
import select
import queue
import dbus
import dbus.mainloop.glib
try:
    from gi.repository import GObject
except ImportError:
    import gobject as GObject

# Ensure we import the repo package first (not a system-installed copy)
try:
    REPO_OPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if REPO_OPT not in sys.path:
        sys.path.insert(0, REPO_OPT)
except Exception as e:
    print(f"Warning: Could not add repo path: {e}")

from DGTCentaurMods.thirdparty.bletools import BleTools
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board.bluetooth_controller import BluetoothController

BLUEZ_SERVICE_NAME = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
DEVICE_IFACE = "org.bluez.Device1"
ADAPTER_IFACE = "org.bluez.Adapter1"

# Global state
running = True
kill = 0
device_connected = False
device_address = None
gatttool_process = None
notification_threads = []


def signal_handler(signum, frame):
    """Handle SIGINT and SIGTERM signals"""
    global kill, running
    log.info("Signal received, shutting down...")
    kill = 1
    running = False


def find_device_by_name(bus, adapter_path, device_name):
    """Find a BLE device by name (Alias or Name property)"""
    try:
        remote_om = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        
        target_name_normalized = device_name.strip().upper()
        
        for path, interfaces in objects.items():
            if DEVICE_IFACE in interfaces:
                device_props = interfaces[DEVICE_IFACE]
                alias = device_props.get("Alias", "")
                name = device_props.get("Name", "")
                address = device_props.get("Address", "")
                
                alias_normalized = str(alias).strip().upper()
                name_normalized = str(name).strip().upper()
                
                if alias_normalized == target_name_normalized or name_normalized == target_name_normalized:
                    log.info(f"Found device '{device_name}' at path: {path} (Address: {address})")
                    return address
        
        log.warning(f"Device with name '{device_name}' not found")
        return None
    except Exception as e:
        log.error(f"Error finding device by name: {e}")
        import traceback
        log.error(traceback.format_exc())
        return None


def parse_gatttool_primary_output(output):
    """Parse gatttool --primary output to find service handles and UUIDs"""
    services = []
    pattern = r'attr handle = 0x([0-9a-f]+), end grp handle = 0x([0-9a-f]+) uuid: ([0-9a-f-]+)'
    
    for line in output.split('\n'):
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            start_handle = int(match.group(1), 16)
            end_handle = int(match.group(2), 16)
            uuid = match.group(3).lower()
            services.append({
                'start_handle': start_handle,
                'end_handle': end_handle,
                'uuid': uuid
            })
    
    return services


def parse_gatttool_char_desc_output(output):
    """Parse gatttool char-desc output to find characteristic handles and UUIDs"""
    characteristics = []
    lines = output.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        
        # Look for characteristic declaration (uuid 2803)
        char_decl_match = re.search(r'handle = 0x([0-9a-f]+), uuid = 00002803-0000-1000-8000-00805f9b34fb', line, re.IGNORECASE)
        if char_decl_match:
            decl_handle = int(char_decl_match.group(1), 16)
            # Next line should be the characteristic value with the actual UUID
            if i + 1 < len(lines):
                value_line = lines[i + 1].strip()
                # Skip if it's another declaration or CCCD
                if '00002803' not in value_line and '00002902' not in value_line:
                    # Pattern: handle = 0xXXXX, uuid = UUID
                    value_match = re.search(r'handle = 0x([0-9a-f]+), uuid = ([0-9a-f-]+)', value_line, re.IGNORECASE)
                    if value_match:
                        value_handle = int(value_match.group(1), 16)
                        uuid_raw = value_match.group(2).lower()
                        
                        # Skip standard Bluetooth UUIDs that aren't characteristics
                        if uuid_raw in ['00002800-0000-1000-8000-00805f9b34fb',  # Primary Service
                                       '00002801-0000-1000-8000-00805f9b34fb',  # Secondary Service
                                       '00002803-0000-1000-8000-00805f9b34fb',  # Characteristic
                                       '00002902-0000-1000-8000-00805f9b34fb']:  # CCCD
                            i += 1
                            continue
                        
                        # Look for CCCD (Client Characteristic Configuration Descriptor) on next line
                        properties = 0
                        cccd_handle = None
                        if i + 2 < len(lines):
                            cccd_line = lines[i + 2].strip()
                            cccd_match = re.search(r'handle = 0x([0-9a-f]+), uuid = 00002902-0000-1000-8000-00805f9b34fb', cccd_line, re.IGNORECASE)
                            if cccd_match:
                                cccd_handle = int(cccd_match.group(1), 16)
                        
                        characteristics.append({
                            'decl_handle': decl_handle,
                            'value_handle': value_handle,
                            'uuid': uuid_raw,
                            'cccd_handle': cccd_handle
                        })
        i += 1
    
    return characteristics


def read_gatttool_output(process, timeout=3, max_bytes=8192):
    """Read output from gatttool process until prompt appears or timeout"""
    output = ""
    stderr_output = ""
    start_time = time.time()
    prompt_pattern = re.compile(r'\[?([A-Z]+)\]?>|^>\s*$')
    
    last_chunk_time = start_time
    no_data_count = 0
    
    while time.time() - start_time < timeout:
        try:
            ready, _, _ = select.select([process.stdout, process.stderr], [], [], 0.2)
        except (OSError, ValueError):
            break
        
        if process.stdout in ready:
            try:
                chunk = process.stdout.read(max_bytes - len(output))
                if chunk:
                    output += chunk
                    last_chunk_time = time.time()
                    no_data_count = 0
                    if prompt_pattern.search(output):
                        lines = output.split('\n')
                        cleaned_lines = []
                        for line in lines:
                            line_stripped = line.strip()
                            if prompt_pattern.match(line_stripped) or line_stripped.endswith('>'):
                                break
                            cleaned_lines.append(line)
                        output = '\n'.join(cleaned_lines)
                        break
            except (OSError, ValueError):
                break
        
        if process.stderr in ready:
            try:
                chunk = process.stderr.read(1024)
                if chunk:
                    stderr_output += chunk
                    last_chunk_time = time.time()
                    no_data_count = 0
            except (OSError, ValueError):
                break
        
        if not ready:
            no_data_count += 1
            if output and no_data_count > 3:
                break
            time.sleep(0.05)
        else:
            no_data_count = 0
        
        if output and (time.time() - last_chunk_time) > 0.5:
            break
    
    if stderr_output:
        output += "\n[stderr]\n" + stderr_output
    
    return output.strip()


def connect_and_scan_ble_device(device_address):
    """Connect to BLE device and scan for all services and characteristics"""
    global device_connected, gatttool_process
    
    try:
        log.info(f"Connecting to device {device_address}")
        
        # Connect via bluetoothctl
        log.info("Connecting via bluetoothctl...")
        result = subprocess.run(['bluetoothctl', 'connect', device_address], 
                               capture_output=True, timeout=10, text=True)
        log.debug(f"bluetoothctl output: {result.stdout}")
        time.sleep(2)
        
        # Discover all services
        log.info("Discovering services with gatttool...")
        result = subprocess.run(['gatttool', '-b', device_address, '--primary'],
                               capture_output=True, timeout=10, text=True)
        
        if result.returncode != 0:
            log.error(f"gatttool --primary failed: {result.stderr}")
            return False
        
        log.info(f"Services found:\n{result.stdout}")
        services = parse_gatttool_primary_output(result.stdout)
        
        # For each service, discover characteristics
        all_characteristics = []
        for service in services:
            log.info(f"Discovering characteristics for service {service['uuid']} (handles {service['start_handle']:04x}-{service['end_handle']:04x})")
            result = subprocess.run(['gatttool', '-b', device_address, '--char-desc', 
                                   f"{service['start_handle']:04x}", f"{service['end_handle']:04x}"],
                                   capture_output=True, timeout=10, text=True)
            
            if result.returncode == 0:
                chars = parse_gatttool_char_desc_output(result.stdout)
                for char in chars:
                    char['service_uuid'] = service['uuid']
                all_characteristics.extend(chars)
                log.info(f"Found {len(chars)} characteristics in service {service['uuid']}")
            else:
                log.warning(f"Failed to discover characteristics for service {service['uuid']}: {result.stderr}")
        
        log.info(f"Total characteristics found: {len(all_characteristics)}")
        
        # Start interactive gatttool for notifications
        log.info("Starting gatttool interactive session for notifications...")
        proc = subprocess.Popen(
            ['gatttool', '-b', device_address, '-I'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0
        )
        
        time.sleep(0.5)
        
        gatttool_process = proc
        
        # Enable notifications on all characteristics that have CCCD
        notification_handles = []
        for char in all_characteristics:
            if char.get('cccd_handle'):
                log.info(f"Enabling notifications on characteristic {char['uuid']} (CCCD handle {char['cccd_handle']:04x})")
                proc.stdin.write(f"char-write-req {char['cccd_handle']:04x} 0100\n")
                proc.stdin.flush()
                notification_handles.append({
                    'value_handle': char['value_handle'],
                    'uuid': char['uuid'],
                    'service_uuid': char.get('service_uuid', 'unknown')
                })
                time.sleep(0.2)
        
        if not notification_handles:
            log.warning("No characteristics with notification support found")
        else:
            log.info(f"Enabled notifications on {len(notification_handles)} characteristics")
        
        # Start threads to drain stdout and stderr
        stdout_queue = queue.Queue()
        stderr_queue = queue.Queue()
        
        def drain_stdout():
            while running and not kill:
                try:
                    if select.select([proc.stdout], [], [], 0.1)[0]:
                        chunk = proc.stdout.read(1024)
                        if chunk:
                            stdout_queue.put(chunk)
                        else:
                            break
                except:
                    break
        
        def drain_stderr():
            while running and not kill:
                try:
                    if select.select([proc.stderr], [], [], 0.1)[0]:
                        chunk = proc.stderr.read(1024)
                        if chunk:
                            stderr_queue.put(chunk)
                        else:
                            break
                except:
                    break
        
        threading.Thread(target=drain_stdout, daemon=True).start()
        threading.Thread(target=drain_stderr, daemon=True).start()
        
        # Start notification reader
        def read_notifications():
            global running, kill
            buffer = ""
            while running and not kill:
                try:
                    try:
                        chunk = stdout_queue.get(timeout=0.1)
                        buffer += chunk
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            if 'Notification' in line or 'Indication' in line:
                                match = re.search(r'handle = 0x([0-9a-f]+).*value: ([0-9a-f ]+)', line, re.IGNORECASE)
                                if match:
                                    handle_str = match.group(1)
                                    hex_str = match.group(2).replace(' ', '')
                                    try:
                                        handle = int(handle_str, 16)
                                        data = bytearray.fromhex(hex_str)
                                        
                                        # Find which characteristic this handle belongs to
                                        char_info = None
                                        for nh in notification_handles:
                                            if nh['value_handle'] == handle:
                                                char_info = nh
                                                break
                                        
                                        if char_info:
                                            log.info(f"RX [{char_info['service_uuid']}] [{char_info['uuid']}] (handle {handle:04x}): {' '.join(f'{b:02x}' for b in data)}")
                                            log.info(f"RX [{char_info['service_uuid']}] [{char_info['uuid']}] (handle {handle:04x}) ASCII: {data.decode('utf-8', errors='replace')}")
                                        else:
                                            log.info(f"RX (handle {handle:04x}): {' '.join(f'{b:02x}' for b in data)}")
                                            log.info(f"RX (handle {handle:04x}) ASCII: {data.decode('utf-8', errors='replace')}")
                                    except ValueError:
                                        pass
                    except queue.Empty:
                        pass
                except Exception as e:
                    if running:
                        log.error(f"Notification read error: {e}")
                    break
        
        threading.Thread(target=read_notifications, daemon=True).start()
        
        device_connected = True
        log.info("BLE connection established and notifications enabled")
        return True
        
    except Exception as e:
        log.error(f"Connection error: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def scan_and_connect_ble_device(bus, adapter_path, target_name):
    """Scan for and connect to target BLE device"""
    log.info(f"Scanning for device with name: {target_name}")
    
    # Start scanning
    try:
        adapter_obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
        adapter_iface = dbus.Interface(adapter_obj, ADAPTER_IFACE)
        adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)
        
        try:
            powered = adapter_props.Get(ADAPTER_IFACE, "Powered")
            if not powered:
                log.warning("Bluetooth adapter is not powered - discovery may fail")
        except Exception as e:
            log.debug(f"Could not check adapter power state: {e}")
        
        discovery_started_by_us = False
        try:
            discovering = adapter_props.Get(ADAPTER_IFACE, "Discovering")
            if discovering:
                log.info("Discovery already in progress, using existing scan")
            else:
                adapter_iface.StartDiscovery()
                discovery_started_by_us = True
                log.info("Started BLE scan")
        except dbus.exceptions.DBusException as e:
            if "InProgress" in str(e) or "org.bluez.Error.InProgress" in str(e):
                log.info("Discovery already in progress, using existing scan")
            else:
                try:
                    adapter_iface.StartDiscovery()
                    discovery_started_by_us = True
                    log.info("Started BLE scan")
                except dbus.exceptions.DBusException as e2:
                    if "InProgress" in str(e2) or "org.bluez.Error.InProgress" in str(e2):
                        log.info("Discovery already in progress, using existing scan")
                    else:
                        raise
        
        time.sleep(2)
        
        # Wait for device to be discovered
        max_wait = 30
        wait_time = 0
        device_address = None
        
        while wait_time < max_wait and not kill:
            device_address = find_device_by_name(bus, adapter_path, target_name)
            if device_address:
                break
            time.sleep(1)
            wait_time += 1
        
        # Stop discovery if we started it
        if discovery_started_by_us:
            try:
                adapter_iface.StopDiscovery()
                log.info("Stopped BLE scan")
            except Exception as e:
                log.debug(f"Error stopping discovery: {e}")
        
        if not device_address:
            log.error(f"Device '{target_name}' not found after {max_wait} seconds")
            return False
        
        # Connect to device
        return connect_and_scan_ble_device(device_address)
        
    except Exception as e:
        log.error(f"Error in scan_and_connect_ble_device: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def cleanup():
    """Clean up BLE connections"""
    global kill, gatttool_process, running, device_connected
    
    try:
        log.info("Cleaning up...")
        kill = 1
        running = False
        
        # Stop gatttool process
        if gatttool_process:
            try:
                gatttool_process.stdin.write("exit\n")
                gatttool_process.stdin.flush()
                time.sleep(0.5)
                gatttool_process.terminate()
                gatttool_process.wait(timeout=2)
                log.info("Stopped gatttool process")
            except:
                try:
                    gatttool_process.kill()
                except:
                    pass
        
        device_connected = False
        log.info("Cleanup complete")
        
    except Exception as e:
        log.debug(f"Error during cleanup: {e}")


def main():
    """Main entry point"""
    global kill, running, device_connected
    
    parser = argparse.ArgumentParser(description='BLE Scanner for Chessnut Air')
    parser.add_argument('--device-name', default='Chessnut Air',
                       help='Name of the BLE device to connect to (default: Chessnut Air)')
    args = parser.parse_args()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Enable Bluetooth
    log.info("Enabling Bluetooth...")
    bluetooth_controller = BluetoothController()
    bluetooth_controller.enable_bluetooth()
    time.sleep(2)
    
    # Get DBus bus and adapter
    bus = BleTools.get_bus()
    adapter = BleTools.find_adapter(bus)
    
    if not adapter:
        log.error("No Bluetooth adapter found")
        sys.exit(1)
    
    log.info(f"Using adapter: {adapter}")
    
    # Scan and connect
    if scan_and_connect_ble_device(bus, adapter, args.device_name):
        log.info("Connected to device. Waiting for data...")
        log.info("Press Ctrl+C to exit")
        
        # Keep running until interrupted
        try:
            while running and not kill:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Keyboard interrupt received")
            running = False
    else:
        log.error("Failed to connect to device")
        sys.exit(1)
    
    # Cleanup
    cleanup()
    log.info("Exiting")


if __name__ == "__main__":
    main()

