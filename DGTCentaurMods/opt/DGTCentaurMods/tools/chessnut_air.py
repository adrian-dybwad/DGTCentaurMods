#!/usr/bin/env python3
"""
Chessnut Air BLE Tool

This tool connects to a BLE device called "Chessnut Air" and logs all data received.
It enables notifications on the FEN and Operation characteristics and sends the initial
enable reporting command.

Usage:
    python3 tools/chessnut_air.py [--device-name "Chessnut Air"]
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

# Chessnut Air BLE UUIDs
CHESSNUT_FEN_SERVICE_UUID = "1b7e8261-2877-41c3-b46e-cf057c562023"
CHESSNUT_FEN_RX_CHAR_UUID = "1b7e8262-2877-41c3-b46e-cf057c562023"  # Notify from board
CHESSNUT_OP_SERVICE_UUID = "1b7e8271-2877-41c3-b46e-cf057c562023"
CHESSNUT_OP_TX_CHAR_UUID = "1b7e8272-2877-41c3-b46e-cf057c562023"  # Write to board
CHESSNUT_OP_RX_CHAR_UUID = "1b7e8273-2877-41c3-b46e-cf057c562023"  # Notify from board

# Initial command to enable reporting
CHESSNUT_ENABLE_REPORTING_CMD = [0x21, 0x01, 0x00]

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


def signal_handler(signum, frame):
    """Handle SIGINT and SIGTERM signals"""
    global kill, running
    log.info("Signal received, shutting down...")
    kill = 1
    running = False


def normalize_uuid(uuid_str):
    """Normalize UUID string for comparison (remove dashes, uppercase)"""
    return uuid_str.replace('-', '').upper()


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


def connect_and_scan_ble_device(device_address):
    """Connect to Chessnut Air BLE device and enable notifications"""
    global device_connected, gatttool_process
    
    try:
        log.info(f"Connecting to device {device_address}")
        
        # Disconnect any existing connection
        log.info("Disconnecting any existing connection...")
        subprocess.run(['bluetoothctl', 'disconnect', device_address], 
                      capture_output=True, timeout=5, text=True)
        time.sleep(3)
        
        # Discover services
        max_retries = 5
        retry_delay = 2
        
        log.info("Discovering services with gatttool...")
        result = None
        for attempt in range(max_retries):
            result = subprocess.run(['gatttool', '-b', device_address, '--primary'],
                                   capture_output=True, timeout=15, text=True)
            
            if result.returncode == 0:
                break
            
            if "Device or resource busy" in result.stderr or "busy" in result.stderr.lower():
                if attempt < max_retries - 1:
                    log.warning(f"Device busy, retrying in {retry_delay} seconds (attempt {attempt + 1}/{max_retries})...")
                    subprocess.run(['bluetoothctl', 'disconnect', device_address], 
                                  capture_output=True, timeout=5, text=True)
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    log.error(f"gatttool --primary failed after {max_retries} attempts: {result.stderr}")
                    return False
            else:
                log.error(f"gatttool --primary failed: {result.stderr}")
                return False
        
        if result.returncode != 0:
            log.error(f"gatttool --primary failed: {result.stderr}")
            return False
        
        log.info(f"Services found:\n{result.stdout}")
        services = parse_gatttool_primary_output(result.stdout)
        
        # Find Chessnut Air services
        fen_service = None
        op_service = None
        
        CHESSNUT_FEN_SERVICE_UUID_NORM = normalize_uuid(CHESSNUT_FEN_SERVICE_UUID)
        CHESSNUT_OP_SERVICE_UUID_NORM = normalize_uuid(CHESSNUT_OP_SERVICE_UUID)
        
        for service in services:
            service_uuid_norm = normalize_uuid(service['uuid'])
            if service_uuid_norm == CHESSNUT_FEN_SERVICE_UUID_NORM:
                fen_service = service
                log.info(f"Found FEN Notification Service: {service['uuid']} (handles {service['start_handle']:04x}-{service['end_handle']:04x})")
            elif service_uuid_norm == CHESSNUT_OP_SERVICE_UUID_NORM:
                op_service = service
                log.info(f"Found Operation Commands Service: {service['uuid']} (handles {service['start_handle']:04x}-{service['end_handle']:04x})")
        
        if not fen_service:
            log.warning("FEN Notification Service not found")
        if not op_service:
            log.warning("Operation Commands Service not found")
        
        # Discover characteristics for each service
        all_characteristics = []
        CHESSNUT_FEN_RX_CHAR_UUID_NORM = normalize_uuid(CHESSNUT_FEN_RX_CHAR_UUID)
        CHESSNUT_OP_TX_CHAR_UUID_NORM = normalize_uuid(CHESSNUT_OP_TX_CHAR_UUID)
        CHESSNUT_OP_RX_CHAR_UUID_NORM = normalize_uuid(CHESSNUT_OP_RX_CHAR_UUID)
        
        for service in [fen_service, op_service]:
            if not service:
                continue
            
            log.info(f"Discovering characteristics for service {service['uuid']}...")
            char_result = None
            for attempt in range(max_retries):
                char_result = subprocess.run(['gatttool', '-b', device_address, '--char-desc', 
                                           f"{service['start_handle']:04x}", f"{service['end_handle']:04x}"],
                                           capture_output=True, timeout=10, text=True)
                
                if char_result.returncode == 0:
                    break
                
                if "Device or resource busy" in char_result.stderr or "busy" in char_result.stderr.lower():
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        log.warning(f"Failed to discover characteristics for service {service['uuid']}")
                        break
                else:
                    log.warning(f"Failed to discover characteristics for service {service['uuid']}")
                    break
            
            if char_result and char_result.returncode == 0:
                chars = parse_gatttool_char_desc_output(char_result.stdout)
                for char in chars:
                    char['service_uuid'] = service['uuid']
                all_characteristics.extend(chars)
                log.info(f"Found {len(chars)} characteristics in service {service['uuid']}")
        
        # Find the specific characteristics we need
        fen_rx_char = None
        op_tx_char = None
        op_rx_char = None
        
        for char in all_characteristics:
            char_uuid_norm = normalize_uuid(char.get('uuid', ''))
            service_uuid_norm = normalize_uuid(char.get('service_uuid', ''))
            
            if char_uuid_norm == CHESSNUT_FEN_RX_CHAR_UUID_NORM and service_uuid_norm == CHESSNUT_FEN_SERVICE_UUID_NORM:
                fen_rx_char = char
                log.info(f"Found FEN RX characteristic: handle {char['value_handle']:04x}, CCCD {char.get('cccd_handle', 'N/A')}")
            elif char_uuid_norm == CHESSNUT_OP_TX_CHAR_UUID_NORM and service_uuid_norm == CHESSNUT_OP_SERVICE_UUID_NORM:
                op_tx_char = char
                log.info(f"Found Operation TX characteristic: handle {char['value_handle']:04x}")
            elif char_uuid_norm == CHESSNUT_OP_RX_CHAR_UUID_NORM and service_uuid_norm == CHESSNUT_OP_SERVICE_UUID_NORM:
                op_rx_char = char
                log.info(f"Found Operation RX characteristic: handle {char['value_handle']:04x}, CCCD {char.get('cccd_handle', 'N/A')}")
        
        if not fen_rx_char:
            log.error("FEN RX characteristic not found")
        if not op_tx_char:
            log.error("Operation TX characteristic not found")
        if not op_rx_char:
            log.error("Operation RX characteristic not found")
        
        if not fen_rx_char or not op_tx_char or not op_rx_char:
            log.error("Required characteristics not found, cannot proceed")
            return False
        
        # Start interactive gatttool session
        log.info("Starting gatttool interactive session for notifications...")
        proc = None
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    subprocess.run(['bluetoothctl', 'disconnect', device_address], 
                                  capture_output=True, timeout=5, text=True)
                    time.sleep(2)
                
                proc = subprocess.Popen(
                    ['gatttool', '-b', device_address, '-I'],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=0
                )
                time.sleep(1)
                
                # Connect in interactive mode
                proc.stdin.write("connect\n")
                proc.stdin.flush()
                time.sleep(3)
                
                if proc.poll() is None:
                    log.info("gatttool interactive session started and connected successfully")
                    break
                else:
                    exit_code = proc.returncode
                    proc = None
                    if attempt < max_retries - 1:
                        log.warning(f"gatttool process exited with code {exit_code}, retrying...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
            except Exception as e:
                log.warning(f"Failed to start gatttool (attempt {attempt + 1}/{max_retries}): {e}")
                if proc:
                    try:
                        proc.terminate()
                    except:
                        pass
                proc = None
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
        
        if proc is None:
            log.error(f"Failed to start gatttool interactive session after {max_retries} attempts")
            return False
        
        time.sleep(0.5)
        gatttool_process = proc
        
        # Enable notifications on FEN RX characteristic
        if fen_rx_char.get('cccd_handle'):
            log.info(f"Enabling notifications on FEN RX characteristic (CCCD handle {fen_rx_char['cccd_handle']:04x})")
            try:
                proc.stdin.write(f"char-write-req {fen_rx_char['cccd_handle']:04x} 0100\n")
                proc.stdin.flush()
                time.sleep(0.2)
            except Exception as e:
                log.error(f"Error enabling notifications on FEN RX: {e}")
        
        # Enable notifications on Operation RX characteristic
        if op_rx_char.get('cccd_handle'):
            log.info(f"Enabling notifications on Operation RX characteristic (CCCD handle {op_rx_char['cccd_handle']:04x})")
            try:
                proc.stdin.write(f"char-write-req {op_rx_char['cccd_handle']:04x} 0100\n")
                proc.stdin.flush()
                time.sleep(0.2)
            except Exception as e:
                log.error(f"Error enabling notifications on Operation RX: {e}")
        
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
                except Exception as e:
                    if running:
                        log.error(f"drain_stdout error: {e}")
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
                        buffer += chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else chunk
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
                                        
                                        # Determine which characteristic this is
                                        char_name = "Unknown"
                                        if handle == fen_rx_char['value_handle']:
                                            char_name = "FEN RX"
                                        elif handle == op_rx_char['value_handle']:
                                            char_name = "Operation RX"
                                        
                                        log.info(f"RX [{char_name}] (handle {handle:04x}): {' '.join(f'{b:02x}' for b in data)}")
                                        # Try to decode as text if possible
                                        try:
                                            text = data.decode('utf-8', errors='replace')
                                            if text.isprintable() or '\n' in text or '\r' in text:
                                                log.info(f"RX [{char_name}] (handle {handle:04x}) text: {repr(text)}")
                                        except:
                                            pass
                                    except ValueError:
                                        pass
                    except queue.Empty:
                        pass
                except Exception as e:
                    if running:
                        log.error(f"Notification read error: {e}")
                        import traceback
                        log.error(traceback.format_exc())
                    break
        
        threading.Thread(target=read_notifications, daemon=True).start()
        
        # Send initial enable reporting command
        log.info("Sending initial enable reporting command [0x21, 0x01, 0x00]...")
        chessnut_hex = ' '.join(f'{b:02x}' for b in CHESSNUT_ENABLE_REPORTING_CMD)
        try:
            proc.stdin.write(f"char-write-cmd {op_tx_char['value_handle']:04x} {chessnut_hex}\n")
            proc.stdin.flush()
            log.info(f"Sent enable reporting command to Operation TX characteristic (handle {op_tx_char['value_handle']:04x})")
        except Exception as e:
            log.error(f"Error sending enable reporting command: {e}")
        
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
    
    parser = argparse.ArgumentParser(description='Chessnut Air BLE Tool')
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

