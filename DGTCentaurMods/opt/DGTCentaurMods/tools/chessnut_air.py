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
# Battery level command
CHESSNUT_BATTERY_LEVEL_CMD = [0x29, 0x01, 0x00]

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
    """Handle SIGINT and SIGTERM signals - must be async-safe"""
    global kill, running
    # Don't use logging in signal handler - it can cause reentrant calls
    # Just set flags and let cleanup handle logging
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
                
                # Convert dbus types to strings
                alias = str(alias) if alias else ""
                name = str(name) if name else ""
                address = str(address) if address else ""
                
                alias_normalized = alias.strip().upper()
                name_normalized = name.strip().upper()
                
                if alias_normalized == target_name_normalized or name_normalized == target_name_normalized:
                    log.info(f"Found device '{device_name}' at path: {path} (Address: {address})")
                    return address  # Return as plain string
        
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
                
                # Check connection status
                proc.stdin.write("char-read-hnd 0x0001\n")
                proc.stdin.flush()
                time.sleep(1)
                
                if proc.poll() is None:
                    log.info("gatttool interactive session started")
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
        
        # Start threads to drain stdout and stderr FIRST (before any operations)
        stdout_queue = queue.Queue()
        stderr_queue = queue.Queue()
        
        def drain_stdout():
            chunks_received = 0
            while running and not kill:
                try:
                    if select.select([proc.stdout], [], [], 0.1)[0]:
                        chunk = proc.stdout.read(1024)
                        if chunk:
                            chunks_received += 1
                            stdout_queue.put(chunk)
                            # Log first few chunks to verify it's working
                            if chunks_received <= 5:
                                log.info(f"drain_stdout received chunk #{chunks_received}: {repr(chunk[:100])}")
                        else:
                            if running:
                                log.warning("drain_stdout: read() returned empty, stream may be closed")
                            break
                except Exception as e:
                    if running:
                        log.error(f"drain_stdout error: {e}")
                        import traceback
                        log.error(traceback.format_exc())
                    break
            if running:
                log.info(f"drain_stdout thread exiting (received {chunks_received} chunks total)")
        
        def drain_stderr():
            while running and not kill:
                try:
                    if select.select([proc.stderr], [], [], 0.1)[0]:
                        chunk = proc.stderr.read(1024)
                        if chunk:
                            stderr_queue.put(chunk)
                            # Log stderr output for debugging
                            log.info(f"gatttool stderr: {chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else chunk}")
                        else:
                            break
                except Exception as e:
                    if running:
                        log.debug(f"drain_stderr error: {e}")
                    break
        
        threading.Thread(target=drain_stdout, daemon=True).start()
        threading.Thread(target=drain_stderr, daemon=True).start()
        
        # Wait for drain threads to start and verify connection
        time.sleep(1)
        log.info("Verifying connection by reading a characteristic...")
        try:
            proc.stdin.write("char-read-hnd 0x0001\n")
            proc.stdin.flush()
            time.sleep(1)
            # Check if we got any response
            try:
                if not stdout_queue.empty():
                    chunk = stdout_queue.get_nowait()
                    chunk_str = chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else chunk
                    log.info(f"Connection verification response: {repr(chunk_str[:200])}")
                    if 'Connection successful' in chunk_str or 'Characteristic' in chunk_str:
                        log.info("Connection verified - gatttool is responding")
                    else:
                        log.warning(f"Unexpected response format: {chunk_str[:200]}")
                else:
                    log.warning("No response to connection verification - connection may not be working")
            except queue.Empty:
                log.warning("No response received for connection verification")
        except Exception as e:
            log.warning(f"Error verifying connection: {e}")
        
        # Set BLE MTU to 500 (required for receiving full FEN data)
        # According to Chessnut documentation: "If you cannot receive the full FEN data, 
        # please set the BLE MTU to 500 after the BLE connection is established."
        log.info("Setting BLE MTU to 500...")
        try:
            # Use D-Bus to access BlueZ GATT interface and request MTU exchange
            bus = BleTools.get_bus()
            device_path = None
            
            # Find the device path
            remote_om = dbus.Interface(
                bus.get_object(BLUEZ_SERVICE_NAME, "/"),
                DBUS_OM_IFACE)
            objects = remote_om.GetManagedObjects()
            
            for path, interfaces in objects.items():
                if DEVICE_IFACE in interfaces:
                    device_props = interfaces[DEVICE_IFACE]
                    if device_props.get("Address", "").upper() == device_address.upper():
                        device_path = path
                        break
            
            if device_path:
                # Try to get GATT interface (if available)
                try:
                    device_obj = bus.get_object(BLUEZ_SERVICE_NAME, device_path)
                    # Check if device has GATT interface
                    if 'org.bluez.Device1' in objects.get(device_path, {}):
                        # MTU exchange is typically handled automatically, but we can try to request it
                        # Note: BlueZ doesn't expose MTU exchange directly via D-Bus in older versions
                        # The MTU is negotiated automatically during connection
                        log.info("MTU exchange is typically handled automatically by BlueZ during connection")
                        log.info("If MTU is still too small, you may need to use a BLE library that supports explicit MTU exchange")
                except Exception as e:
                    log.debug(f"Could not access device GATT interface: {e}")
            else:
                log.warning("Could not find device path for MTU exchange")
        except Exception as e:
            log.warning(f"Could not set MTU via D-Bus: {e}")
            log.warning("MTU exchange may need to be handled by the BLE stack automatically")
            log.warning("If you're not receiving data, the MTU might be too small (default is 23 bytes)")
            log.warning("Consider using a BLE library like 'bleak' or 'bluepy' that supports explicit MTU exchange")
        
        # Drain threads already started above
        
        # Enable notifications/indications on FEN RX characteristic
        # Note: 0x0100 enables notifications, 0x0200 enables indications
        # Since these are INDICATE (0x10), we should use 0x0200, but 0x0100 might work too
        if fen_rx_char.get('cccd_handle'):
            log.info(f"Enabling indications on FEN RX characteristic (CCCD handle {fen_rx_char['cccd_handle']:04x})")
            log.info("NOTE: This characteristic uses INDICATE (0x10) which requires acknowledgment")
            try:
                # Try 0x0200 for indications first, fallback to 0x0100
                proc.stdin.write(f"char-write-req {fen_rx_char['cccd_handle']:04x} 0200\n")
                proc.stdin.flush()
                log.info("Sent char-write-req 0200 (indications), waiting for response...")
                time.sleep(2)  # Wait longer for confirmation
                # Check for confirmation in output
                response_found = False
                response_text = ""
                try:
                    # Drain any immediate response
                    timeout = time.time() + 3
                    while time.time() < timeout:
                        try:
                            chunk = stdout_queue.get(timeout=0.2)
                            chunk_str = chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else chunk
                            response_text += chunk_str
                            log.info(f"gatttool stdout after FEN indication enable: {repr(chunk_str)}")
                            if any(word in chunk_str.lower() for word in ['success', 'written', 'characteristic', 'error', 'fail']):
                                response_found = True
                        except queue.Empty:
                            if response_found:
                                break
                except Exception as e:
                    log.warning(f"Error checking for FEN indication response: {e}")
                
                if not response_found:
                    log.warning("No confirmation received for FEN indication enable - trying 0x0100 (notifications)")
                    # Fallback to 0x0100
                    proc.stdin.write(f"char-write-req {fen_rx_char['cccd_handle']:04x} 0100\n")
                    proc.stdin.flush()
                    time.sleep(1)
                else:
                    log.info(f"FEN indication enable confirmed: {response_text[:200]}")
            except Exception as e:
                log.error(f"Error enabling indications on FEN RX: {e}")
                import traceback
                log.error(traceback.format_exc())
        
        # Enable notifications/indications on Operation RX characteristic
        if op_rx_char.get('cccd_handle'):
            log.info(f"Enabling indications on Operation RX characteristic (CCCD handle {op_rx_char['cccd_handle']:04x})")
            log.info("NOTE: This characteristic uses INDICATE (0x10) which requires acknowledgment")
            try:
                # Try 0x0200 for indications first, fallback to 0x0100
                proc.stdin.write(f"char-write-req {op_rx_char['cccd_handle']:04x} 0200\n")
                proc.stdin.flush()
                log.info("Sent char-write-req 0200 (indications), waiting for response...")
                time.sleep(2)  # Wait longer for confirmation
                # Check for confirmation in output
                response_found = False
                response_text = ""
                try:
                    # Drain any immediate response
                    timeout = time.time() + 3
                    while time.time() < timeout:
                        try:
                            chunk = stdout_queue.get(timeout=0.2)
                            chunk_str = chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else chunk
                            response_text += chunk_str
                            log.info(f"gatttool stdout after Operation indication enable: {repr(chunk_str)}")
                            if any(word in chunk_str.lower() for word in ['success', 'written', 'characteristic', 'error', 'fail']):
                                response_found = True
                        except queue.Empty:
                            if response_found:
                                break
                except Exception as e:
                    log.warning(f"Error checking for Operation indication response: {e}")
                
                if not response_found:
                    log.warning("No confirmation received for Operation indication enable - trying 0x0100 (notifications)")
                    # Fallback to 0x0100
                    proc.stdin.write(f"char-write-req {op_rx_char['cccd_handle']:04x} 0100\n")
                    proc.stdin.flush()
                    time.sleep(1)
                else:
                    log.info(f"Operation indication enable confirmed: {response_text[:200]}")
            except Exception as e:
                log.error(f"Error enabling indications on Operation RX: {e}")
                import traceback
                log.error(traceback.format_exc())
        
        # Remove duplicate thread creation
        
        # Start notification reader
        def read_notifications():
            global running, kill
            buffer = ""
            last_activity_log = time.time()
            lines_processed = 0
            
            log.info("Notification reader thread started")
            
            while running and not kill:
                try:
                    # Log periodic status to confirm thread is running
                    if time.time() - last_activity_log > 5:
                        log.info(f"Notification reader active (processed {lines_processed} lines so far)")
                        last_activity_log = time.time()
                    
                    # Also check stderr queue
                    try:
                        stderr_chunk = stderr_queue.get_nowait()
                        log.info(f"gatttool stderr: {stderr_chunk.decode('utf-8', errors='replace') if isinstance(stderr_chunk, bytes) else stderr_chunk}")
                    except queue.Empty:
                        pass
                    
                    try:
                        chunk = stdout_queue.get(timeout=0.1)
                        buffer += chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else chunk
                        # Log all gatttool output for debugging
                        if chunk:
                            log.info(f"gatttool stdout chunk: {repr(chunk)}")
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line_stripped = line.strip()
                            lines_processed += 1
                            # Log all lines for debugging
                            if line_stripped:
                                log.info(f"gatttool line: {line_stripped}")
                            # Check for command write responses
                            if 'Characteristic value was written successfully' in line:
                                log.info(f"Command write confirmed: {line_stripped}")
                            
                            if 'Notification' in line or 'Indication' in line:
                                log.info(f"*** RECEIVED NOTIFICATION/INDICATION: {line_stripped} ***")
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
                                        
                                        log.info(f"*** RX [{char_name}] (handle {handle:04x}): {' '.join(f'{b:02x}' for b in data)} ***")
                                        
                                        # Parse battery level response if this is Operation RX
                                        if handle == op_rx_char['value_handle'] and len(data) >= 4:
                                            if data[0] == 0x2a and data[1] == 0x02:
                                                battery_level_byte = data[2]
                                                charging = (battery_level_byte & 0x80) != 0
                                                battery_percent = battery_level_byte & 0x7F
                                                log.info(f"*** RX [Operation RX] Battery Level: {battery_percent}% ({'Charging' if charging else 'Not charging'}) ***")
                                        
                                        # Try to decode as text if possible
                                        try:
                                            text = data.decode('utf-8', errors='replace')
                                            if text.isprintable() or '\n' in text or '\r' in text:
                                                log.info(f"RX [{char_name}] (handle {handle:04x}) text: {repr(text)}")
                                        except:
                                            pass
                                    except ValueError as e:
                                        log.warning(f"Error parsing notification data: {e}, hex_str: {hex_str}")
                                else:
                                    log.warning(f"Could not parse notification line: {line_stripped}")
                    except queue.Empty:
                        pass
                except Exception as e:
                    if running:
                        log.error(f"Notification read error: {e}")
                        import traceback
                        log.error(traceback.format_exc())
                    break
        
        threading.Thread(target=read_notifications, daemon=True).start()
        
        # Wait a bit for notifications to be fully enabled
        time.sleep(1)
        log.info("Waiting for notifications to be fully enabled...")
        
        # Wait a bit more for any pending output to be processed
        time.sleep(1)
        
        # Send initial enable reporting command
        log.info("Sending initial enable reporting command [0x21, 0x01, 0x00]...")
        chessnut_hex = ' '.join(f'{b:02x}' for b in CHESSNUT_ENABLE_REPORTING_CMD)
        try:
            # Use char-write-req to get confirmation
            proc.stdin.write(f"char-write-req {op_tx_char['value_handle']:04x} {chessnut_hex}\n")
            proc.stdin.flush()
            log.info(f"Sent enable reporting command (with response) to Operation TX characteristic (handle {op_tx_char['value_handle']:04x})")
            log.info("Waiting for write confirmation...")
            time.sleep(2)  # Wait longer for response
            # Check for response - drain all available output
            responses_found = 0
            try:
                timeout = time.time() + 3
                while time.time() < timeout:
                    try:
                        chunk = stdout_queue.get(timeout=0.3)
                        chunk_str = chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else chunk
                        log.info(f"Enable reporting command response chunk: {repr(chunk_str)}")
                        if 'written successfully' in chunk_str.lower() or 'error' in chunk_str.lower():
                            responses_found += 1
                            log.info(f"*** Enable reporting command write {'SUCCEEDED' if 'success' in chunk_str.lower() else 'FAILED'} ***")
                    except queue.Empty:
                        if responses_found > 0:
                            break
            except Exception as e:
                log.debug(f"Error checking enable reporting response: {e}")
            if responses_found == 0:
                log.warning("No write confirmation received for enable reporting command")
        except Exception as e:
            log.error(f"Error sending enable reporting command: {e}")
        
        # Send battery level command
        log.info("Sending battery level command [0x29, 0x01, 0x00]...")
        battery_hex = ' '.join(f'{b:02x}' for b in CHESSNUT_BATTERY_LEVEL_CMD)
        try:
            # Use char-write-req to get confirmation
            proc.stdin.write(f"char-write-req {op_tx_char['value_handle']:04x} {battery_hex}\n")
            proc.stdin.flush()
            log.info(f"Sent battery level command (with response) to Operation TX characteristic (handle {op_tx_char['value_handle']:04x})")
            log.info("Waiting for write confirmation and battery response...")
            time.sleep(3)  # Wait longer for both write confirmation and battery response
            # Check for response - drain all available output
            responses_found = 0
            try:
                timeout = time.time() + 4
                while time.time() < timeout:
                    try:
                        chunk = stdout_queue.get(timeout=0.3)
                        chunk_str = chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else chunk
                        log.info(f"Battery level command response chunk: {repr(chunk_str)}")
                        if 'written successfully' in chunk_str.lower() or 'error' in chunk_str.lower() or 'indication' in chunk_str.lower() or 'notification' in chunk_str.lower():
                            responses_found += 1
                            if 'written successfully' in chunk_str.lower():
                                log.info("*** Battery level command write SUCCEEDED ***")
                            if 'indication' in chunk_str.lower() or 'notification' in chunk_str.lower():
                                log.info("*** Battery level response received via indication/notification ***")
                    except queue.Empty:
                        if responses_found > 0:
                            break
            except Exception as e:
                log.debug(f"Error checking battery level response: {e}")
            if responses_found == 0:
                log.warning("No write confirmation or response received for battery level command")
        except Exception as e:
            log.error(f"Error sending battery level command: {e}")
        
        # Log that we're now waiting for data
        log.info("Commands sent. Waiting for notifications...")
        log.info("Note: FEN data will only be sent when pieces are moved on the board")
        log.info("Battery level response should arrive shortly if the device supports it")
        
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
        
        # Ensure device_address is a plain string (not dbus.String)
        device_address = str(device_address)
        log.info(f"Using device address: {device_address}")
        
        # Find device path and check pairing status
        device_path = None
        try:
            remote_om = dbus.Interface(
                bus.get_object(BLUEZ_SERVICE_NAME, "/"),
                DBUS_OM_IFACE)
            objects = remote_om.GetManagedObjects()
            
            for path, interfaces in objects.items():
                if DEVICE_IFACE in interfaces:
                    dev_props = interfaces[DEVICE_IFACE]
                    dev_address = str(dev_props.get('Address', ''))
                    if dev_address.upper() == device_address.upper():
                        device_path = path
                        break
            
            if device_path:
                log.info(f"Checking if device {device_address} needs pairing...")
                try:
                    device_obj = bus.get_object(BLUEZ_SERVICE_NAME, device_path)
                    device_props = dbus.Interface(device_obj, DBUS_PROP_IFACE)
                    paired = device_props.Get(DEVICE_IFACE, "Paired")
                    trusted = device_props.Get(DEVICE_IFACE, "Trusted")
                    log.info(f"Device pairing status: Paired={paired}, Trusted={trusted}")
                    
                    if not paired or not trusted:
                        log.info("Device is not paired/trusted")
                        log.info("Note: Many BLE devices work without pairing for GATT access")
                        log.info("Attempting to trust device (pairing may require user interaction)...")
                        try:
                            # Try to trust the device (doesn't require authentication)
                            if not trusted:
                                try:
                                    device_props.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
                                    log.info("Device set as trusted")
                                except Exception as e:
                                    log.debug(f"Could not set device as trusted: {e}")
                            
                            # Try pairing (may fail if device requires PIN/user interaction)
                            if not paired:
                                try:
                                    device_iface = dbus.Interface(device_obj, DEVICE_IFACE)
                                    device_iface.Pair()
                                    log.info("Pairing initiated, waiting...")
                                    time.sleep(3)
                                    # Check if pairing succeeded
                                    try:
                                        paired_after = device_props.Get(DEVICE_IFACE, "Paired")
                                        if paired_after:
                                            log.info("Pairing succeeded")
                                        else:
                                            log.info("Pairing may require PIN or user interaction - continuing without pairing")
                                    except:
                                        pass
                                except dbus.exceptions.DBusException as e:
                                    if "AuthenticationFailed" in str(e) or "Authentication" in str(e):
                                        log.info("Pairing requires authentication (PIN/user interaction) - continuing without pairing")
                                        log.info("Many BLE devices work without pairing for GATT operations")
                                    else:
                                        log.warning(f"Pairing attempt failed: {e}")
                                        log.info("Continuing without pairing - GATT may still work")
                        except Exception as e:
                            log.info(f"Could not pair/trust device automatically: {e}")
                            log.info("Continuing without pairing - many BLE devices work without pairing")
                except Exception as e:
                    log.debug(f"Could not check pairing status: {e}")
        except Exception as e:
            log.debug(f"Could not find device path for pairing check: {e}")
        
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

