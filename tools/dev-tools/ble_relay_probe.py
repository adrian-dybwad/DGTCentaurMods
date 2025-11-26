#!/usr/bin/env python3
"""
BLE Relay Probe

This probe acts as a BLE relay between two BLE devices:
1. Acts as a BLE peripheral (server) - accepts incoming BLE connections (like millennium.py)
2. Acts as a BLE client - connects to a nominated BLE host using BLE GATT only
3. Relays and logs all messages between the two connections

Usage:
    python3 tools/dev-tools/ble_relay_probe.py --target-address AA:BB:CC:DD:EE:FF
    python3 tools/dev-tools/ble_relay_probe.py --auto-connect-millennium
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
    REPO_OPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'DGTCentaurMods', 'opt'))
    if REPO_OPT not in sys.path:
        sys.path.insert(0, REPO_OPT)
except Exception as e:
    print(f"Warning: Could not add repo path: {e}")

from DGTCentaurMods.thirdparty.advertisement import Advertisement
from DGTCentaurMods.thirdparty.service import Application, Service, Characteristic
from DGTCentaurMods.thirdparty.bletools import BleTools
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board.bluetooth_controller import BluetoothController

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
BLUEZ_SERVICE_NAME = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
DEVICE_IFACE = "org.bluez.Device1"
ADAPTER_IFACE = "org.bluez.Adapter1"

# Global state
running = True
kill = 0
peripheral_connected = False
client_connected = False

# BLE Client state (using DBus objects or gatttool)
client_device_address = None
client_gatt_process = None  # Dict with 'tx_char_iface', 'rx_char_iface', 'device_obj' or gatttool process
client_tx_char_handle = None  # For gatttool fallback
client_rx_char_handle = None  # For gatttool fallback

# Default service UUIDs (can be overridden via command line)
DEFAULT_SERVICE_UUID = "49535343-FE7D-4AE5-8FA9-9FAFD205E455"
DEFAULT_TX_CHAR_UUID = "49535343-1E4D-4BD9-BA61-23C647249616"
DEFAULT_RX_CHAR_UUID = "49535343-8841-43F4-A8D4-ECBE34729BB3"


# ============================================================================
# BLE Peripheral (Server) Implementation
# ============================================================================

class RelayAdvertisement(Advertisement):
    """BLE advertisement for relay service"""
    def __init__(self, index):
        Advertisement.__init__(self, index, "peripheral")
        self.add_local_name("BLE Relay Probe")
        self.include_tx_power = True
        self.add_service_uuid(DEFAULT_SERVICE_UUID)
        log.info("BLE Relay advertisement initialized")
    
    def register_ad_callback(self):
        log.info("BLE Relay advertisement registered successfully")
    
    def register_ad_error_callback(self, error):
        log.error(f"Failed to register BLE Relay advertisement: {error}")
    
    def register(self):
        bus = BleTools.get_bus()
        adapter = BleTools.find_adapter(bus)
        
        ad_manager = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, adapter),
            "org.bluez.LEAdvertisingManager1")
        
        options = {
            "MinInterval": dbus.UInt16(0x0014),
            "MaxInterval": dbus.UInt16(0x0098),
        }
        
        log.info("Registering BLE Relay advertisement")
        ad_manager.RegisterAdvertisement(
            self.get_path(),
            options,
            reply_handler=self.register_ad_callback,
            error_handler=self.register_ad_error_callback)


class RelayService(Service):
    """BLE UART service for relay"""
    tx_obj = None
    
    def __init__(self, index):
        Service.__init__(self, index, DEFAULT_SERVICE_UUID, True)
        self.add_characteristic(RelayTXCharacteristic(self))
        self.add_characteristic(RelayRXCharacteristic(self))


class RelayRXCharacteristic(Characteristic):
    """BLE RX characteristic - receives data from BLE client and relays to remote host"""
    
    def __init__(self, service):
        Characteristic.__init__(
            self, DEFAULT_RX_CHAR_UUID,
            ["write", "write-without-response"], service)
    
    def WriteValue(self, value, options):
        """When the remote device writes data via BLE, relay it to the client connection"""
        global running, kill, client_connected, client_gatt_process
        
        if kill or not running:
            return
        
        try:
            bytes_data = bytearray()
            for i in range(0, len(value)):
                bytes_data.append(value[i])
            
            log.info(f"PERIPHERAL RX -> CLIENT: {' '.join(f'{b:02x}' for b in bytes_data)}")
            log.info(f"PERIPHERAL RX -> CLIENT (ASCII): {bytes_data.decode('utf-8', errors='replace')}")
            
            # Relay to client connection if connected
            if client_connected and client_gatt_process is not None:
                try:
                    # Check if using gatttool or DBus
                    if client_gatt_process.get('use_gatttool'):
                        # Write using gatttool
                        proc = client_gatt_process.get('process')
                        rx_handle = client_gatt_process.get('rx_char_handle')
                        if proc and rx_handle:
                            hex_data = ''.join(f'{b:02x}' for b in bytes_data)
                            cmd = f"char-write-req {rx_handle:04x} {hex_data}\n"
                            proc.stdin.write(cmd)
                            proc.stdin.flush()
                            log.debug("Successfully relayed message to client via gatttool")
                        else:
                            log.warning("Gatttool process or RX handle not available")
                    else:
                        # Write using DBus
                        rx_char_iface = client_gatt_process.get('rx_char_iface')
                        if rx_char_iface:
                            # Convert to DBus array
                            dbus_value = dbus.Array([dbus.Byte(b) for b in bytes_data], signature=dbus.Signature('y'))
                            rx_char_iface.WriteValue(dbus_value, {})
                            log.debug("Successfully relayed message to client via DBus")
                        else:
                            log.warning("RX characteristic interface not available")
                except Exception as e:
                    log.error(f"Error relaying to client: {e}")
            else:
                log.warning("Client not connected, message dropped")
        except Exception as e:
            log.error(f"Error in WriteValue: {e}")
            import traceback
            log.error(traceback.format_exc())


class RelayTXCharacteristic(Characteristic):
    """BLE TX characteristic - sends data from client connection to BLE peripheral"""
    
    def __init__(self, service):
        Characteristic.__init__(
            self, DEFAULT_TX_CHAR_UUID,
            ["read", "notify"], service)
        self.notifying = False
    
    def sendMessage(self, data):
        """Send a message via BLE notification"""
        if not self.notifying:
            return
        log.info(f"CLIENT -> PERIPHERAL TX: {' '.join(f'{b:02x}' for b in data)}")
        log.info(f"CLIENT -> PERIPHERAL TX (ASCII): {data.decode('utf-8', errors='replace')}")
        tosend = bytearray()
        for x in range(0, len(data)):
            tosend.append(data[x])
        RelayService.tx_obj.updateValue(tosend)
    
    def StartNotify(self):
        """Called when BLE client subscribes to notifications"""
        try:
            log.info("TX Characteristic StartNotify called - BLE client subscribing to notifications")
            RelayService.tx_obj = self
            self.notifying = True
            global peripheral_connected
            peripheral_connected = True
            log.info("Peripheral notifications enabled successfully")
            return self.notifying
        except Exception as e:
            log.error(f"Error in StartNotify: {e}")
            import traceback
            log.error(traceback.format_exc())
            raise
    
    def StopNotify(self):
        """Called when BLE client unsubscribes from notifications"""
        if not self.notifying:
            return
        log.info("BLE client stopped notifications")
        self.notifying = False
        global peripheral_connected
        peripheral_connected = False
        return self.notifying
    
    def updateValue(self, value):
        """Update the characteristic value and notify subscribers"""
        if not self.notifying:
            return
        log.info(f"CLIENT -> PERIPHERAL TX: {' '.join(f'{b:02x}' for b in value)}")
        log.info(f"CLIENT -> PERIPHERAL TX (ASCII): {value.decode('utf-8', errors='replace')}")
        send = dbus.Array(signature=dbus.Signature('y'))
        for i in range(0, len(value)):
            send.append(dbus.Byte(value[i]))
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': send}, [])
    
    def ReadValue(self, options):
        """Read the current characteristic value"""
        try:
            log.info("TX Characteristic ReadValue called by BLE client")
            value = bytearray()
            value.append(0)
            return value
        except Exception as e:
            log.error(f"Error in ReadValue: {e}")
            import traceback
            log.error(traceback.format_exc())
            raise


# ============================================================================
# BLE Client Implementation (BLE GATT only via gatttool)
# ============================================================================

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


def find_device_by_address(bus, adapter_path, address):
    """Find a BLE device by MAC address and return the address"""
    try:
        remote_om = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        
        for path, interfaces in objects.items():
            if DEVICE_IFACE in interfaces:
                device_props = interfaces[DEVICE_IFACE]
                if device_props.get("Address") == address:
                    log.info(f"Found device at path: {path}")
                    return address
        
        log.warning(f"Device with address {address} not found")
        return None
    except Exception as e:
        log.error(f"Error finding device: {e}")
        import traceback
        log.error(traceback.format_exc())
        return None


def parse_gatttool_primary_output(output):
    """Parse gatttool --primary output to find service handles and UUIDs"""
    services = []
    # Pattern: attr handle = 0xXXXX, end grp handle = 0xYYYY uuid: UUID
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


def parse_gatttool_characteristics_output(output):
    """Parse gatttool --characteristics output to find characteristic handles and UUIDs"""
    characteristics = []
    # Pattern: handle = 0xXXXX, char properties = 0xXX, char value handle = 0xYYYY uuid: UUID
    pattern = r'handle = 0x([0-9a-f]+), char properties = 0x([0-9a-f]+), char value handle = 0x([0-9a-f]+) uuid: ([0-9a-f-]+)'
    
    for line in output.split('\n'):
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            decl_handle = int(match.group(1), 16)
            properties = int(match.group(2), 16)
            value_handle = int(match.group(3), 16)
            uuid = match.group(4).lower()
            characteristics.append({
                'decl_handle': decl_handle,
                'value_handle': value_handle,
                'properties': properties,
                'uuid': uuid
            })
    
    return characteristics


def read_gatttool_output(process, timeout=3, max_bytes=8192):
    """Read output from gatttool process until prompt appears or timeout"""
    output = ""
    stderr_output = ""
    start_time = time.time()
    # Prompt patterns: [CON]>, [LE]>, [   ]>, or just >
    # Also match prompts that might be on their own line or at end of line
    prompt_pattern = re.compile(r'\[?([A-Z]+)\]?>|^>\s*$')
    
    last_chunk_time = start_time
    no_data_count = 0  # Count consecutive iterations with no data
    
    while time.time() - start_time < timeout:
        # Check both stdout and stderr with short timeout
        try:
            ready, _, _ = select.select([process.stdout, process.stderr], [], [], 0.2)
        except (OSError, ValueError):
            # Process might have closed file descriptors
            break
        
        if process.stdout in ready:
            try:
                chunk = process.stdout.read(max_bytes - len(output))
                if chunk:
                    output += chunk
                    last_chunk_time = time.time()
                    no_data_count = 0
                    # Check if we got the prompt (command completed)
                    # Look for prompt at end of output or on its own line
                    if prompt_pattern.search(output):
                        # Remove the prompt from output (keep everything before the last prompt)
                        lines = output.split('\n')
                        cleaned_lines = []
                        for line in lines:
                            line_stripped = line.strip()
                            if prompt_pattern.match(line_stripped) or line_stripped.endswith('>'):
                                # Found prompt, stop here
                                break
                            cleaned_lines.append(line)
                        output = '\n'.join(cleaned_lines)
                        break
            except (OSError, ValueError):
                # File descriptor closed
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
            # If we have output and no data for several iterations, assume done
            if output and no_data_count > 3:
                break
            # Small delay to avoid busy waiting
            time.sleep(0.05)
        else:
            no_data_count = 0
        
        # If we haven't received data for a while and have some output, assume command completed
        if output and (time.time() - last_chunk_time) > 0.5:
            # No more data coming, assume we're done
            break
    
    # Include stderr in output if there are errors
    if stderr_output:
        output += "\n[stderr]\n" + stderr_output
    
    return output.strip()


def parse_gatttool_char_desc_output(output):
    """Parse gatttool char-desc output to find characteristic handles and UUIDs"""
    characteristics = []
    # Pattern: handle = 0xXXXX, uuid = UUID (note: char-desc uses "uuid =", not "uuid:")
    # Characteristic declaration: handle = 0xXXXX, uuid = 00002803-0000-1000-8000-00805f9b34fb
    # Characteristic value: handle = 0xYYYY, uuid = <actual-uuid> (may be 16-bit or 128-bit)
    # CCCD: handle = 0xZZZZ, uuid = 00002902-0000-1000-8000-00805f9b34fb
    
    lines = output.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        
        # Look for characteristic declaration (uuid 2803)
        # Pattern: handle = 0xXXXX, uuid = 00002803-0000-1000-8000-00805f9b34fb
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
                        
                        # Handle 16-bit UUIDs (nRF format)
                        # nRF devices use 16-bit UUIDs that are part of the 4953... service base
                        # If UUID is 16-bit (8 hex digits with leading zeros, or 4 hex digits), extract the 16-bit part
                        uuid_16bit = None
                        if len(uuid_raw) == 8 and uuid_raw.startswith('0000'):
                            # Format: 0000XXXX (8 hex digits, first 4 are zeros)
                            uuid_16bit = uuid_raw[4:8].lower()
                            uuid = None  # We'll match by 16-bit only
                        elif len(uuid_raw) == 4 and '-' not in uuid_raw:
                            # Format: XXXX (4 hex digits)
                            uuid_16bit = uuid_raw.lower()
                            uuid = None  # We'll match by 16-bit only
                        elif len(uuid_raw) > 8 and '-' in uuid_raw:
                            # Full 128-bit UUID
                            uuid = uuid_raw.lower()
                            # Extract 16-bit part if it's a 4953... UUID
                            if uuid.startswith('49535343-'):
                                parts = uuid.split('-')
                                if len(parts) >= 2:
                                    uuid_16bit = parts[1].lower()
                        else:
                            uuid = uuid_raw.lower()
                        
                        properties = 0  # We'll determine this from the declaration if needed
                        characteristics.append({
                            'decl_handle': decl_handle,
                            'value_handle': value_handle,
                            'properties': properties,
                            'uuid': uuid,
                            'uuid_16bit': uuid_raw if len(uuid_raw) == 4 and '-' not in uuid_raw else None
                        })
        i += 1
    
    return characteristics


def connect_ble_gatt(bus, device_path, service_uuid, tx_char_uuid, rx_char_uuid):
    """Connect to BLE device - use non-interactive gatttool for discovery, interactive for notifications"""
    global client_device_address, client_gatt_process, client_connected, client_tx_char_handle, client_rx_char_handle
    
    try:
        # Get device address
        device_obj = bus.get_object(BLUEZ_SERVICE_NAME, device_path)
        device_props = dbus.Interface(device_obj, DBUS_PROP_IFACE)
        device_address = device_props.Get(DEVICE_IFACE, "Address")
        log.info(f"Connecting to device {device_address}")
        
        # Connect via bluetoothctl
        log.info("Connecting via bluetoothctl...")
        result = subprocess.run(['bluetoothctl', 'connect', device_address], 
                               capture_output=True, timeout=10, text=True)
        log.debug(f"bluetoothctl output: {result.stdout}")
        time.sleep(2)
        
        # Use non-interactive gatttool to discover services
        log.info("Discovering services with gatttool...")
        result = subprocess.run(['gatttool', '-b', device_address, '--primary'],
                               capture_output=True, timeout=10, text=True)
        
        if result.returncode != 0:
            log.error(f"gatttool --primary failed: {result.stderr}")
            return False
        
        log.info(f"All services found:\n{result.stdout}")
        
        # Find the CORRECT service (49535343-fe7d-4ae5-8fa9-9fafd205e455), NOT the standard BT one
        service_uuid_lower = service_uuid.lower()
        service_start = None
        service_end = None
        
        for line in result.stdout.split('\n'):
            # Make sure we match the FULL service UUID, not just part of it
            # The service UUID should be: 49535343-fe7d-4ae5-8fa9-9fafd205e455
            if service_uuid_lower in line.lower():
                match = re.search(r'attr handle = 0x([0-9a-f]+), end grp handle = 0x([0-9a-f]+).*uuid: ([0-9a-f-]+)', line, re.IGNORECASE)
                if match:
                    found_uuid = match.group(3).lower()
                    if found_uuid == service_uuid_lower:
                        service_start = int(match.group(1), 16)
                        service_end = int(match.group(2), 16)
                        log.info(f"Found CORRECT service {service_uuid_lower} at handles {service_start:04x}-{service_end:04x}")
                        break
                    else:
                        log.warning(f"Found service with partial match but wrong UUID: {found_uuid}")
        
        if not service_start:
            log.error(f"Service {service_uuid} not found in output!")
            log.error(f"Looking for: {service_uuid_lower}")
            log.error(f"Full output: {result.stdout}")
            return False
        
        # Discover characteristics using char-desc - use the CORRECT service range
        log.info(f"Discovering characteristics in service range {service_start:04x}-{service_end:04x}...")
        char_result = subprocess.run(['gatttool', '-b', device_address, '--char-desc',
                                     f'0x{service_start:04x}', f'0x{service_end:04x}'],
                                    capture_output=True, timeout=15, text=True)
        
        if char_result.returncode != 0:
            log.error(f"gatttool --char-desc failed: {char_result.stderr}")
            return False
        
        log.info(f"Full char-desc output:\n{char_result.stdout}")
        
        # Extract 16-bit UUIDs from full UUIDs (nRF format)
        tx_16bit = tx_char_uuid.lower().split('-')[1] if '-' in tx_char_uuid else None
        rx_16bit = rx_char_uuid.lower().split('-')[1] if '-' in rx_char_uuid else None
        
        log.info(f"Looking for TX 16-bit: {tx_16bit}, RX 16-bit: {rx_16bit}")
        log.info(f"Looking for TX full: {tx_char_uuid.lower()}, RX full: {rx_char_uuid.lower()}")
        
        # Parse ALL lines looking for UUIDs starting with 4953 (nRF service prefix)
        # Expected UUIDs from nRF config:
        # TX: 49535343-1e4d-4bd9-ba61-23c647249616
        # RX: 49535343-8841-43f4-a8d4-ecbe34729bb3
        lines = char_result.stdout.split('\n')
        all_4953_uuids = []
        all_characteristics = []
        
        for line in lines:
            # Look for ANY UUID starting with 4953
            if '4953' in line.lower():
                all_4953_uuids.append(line.strip())
                log.info(f"Found 4953 UUID line: {line.strip()}")
                # Parse: handle = 0xXXXX, uuid = UUID
                uuid_match = re.search(r'uuid = ([0-9a-f-]+)', line, re.IGNORECASE)
                handle_match = re.search(r'handle = 0x([0-9a-f]+)', line, re.IGNORECASE)
                if uuid_match and handle_match:
                    uuid_found = uuid_match.group(1).lower()
                    handle = int(handle_match.group(1), 16)
                    all_characteristics.append((handle, uuid_found))
                    log.info(f"  Handle {handle:04x}: UUID {uuid_found}")
                    
                    # Match by full UUID (exact match)
                    if uuid_found == tx_char_uuid.lower():
                        client_tx_char_handle = handle
                        log.info(f"  *** MATCHED TX at handle {handle:04x} ***")
                    elif uuid_found == rx_char_uuid.lower():
                        client_rx_char_handle = handle
                        log.info(f"  *** MATCHED RX at handle {handle:04x} ***")
        
        # If not found by exact match, try matching by 16-bit part
        if not client_tx_char_handle or not client_rx_char_handle:
            log.info("Trying 16-bit UUID matching...")
            for handle, uuid_found in all_characteristics:
                if uuid_found.startswith('4953'):
                    parts = uuid_found.split('-')
                    if len(parts) >= 2:
                        uuid_16bit = parts[1].lower()
                        if not client_tx_char_handle and tx_16bit and uuid_16bit == tx_16bit.lower():
                            client_tx_char_handle = handle
                            log.info(f"  *** MATCHED TX at handle {handle:04x} (16-bit: {uuid_16bit}) ***")
                        if not client_rx_char_handle and rx_16bit and uuid_16bit == rx_16bit.lower():
                            client_rx_char_handle = handle
                            log.info(f"  *** MATCHED RX at handle {handle:04x} (16-bit: {uuid_16bit}) ***")
        
        if all_4953_uuids:
            log.info(f"Found {len(all_4953_uuids)} lines with 4953 UUIDs:")
            for uuid_line in all_4953_uuids:
                log.info(f"  {uuid_line}")
        else:
            log.warning("NO 4953 UUIDs found in char-desc output!")
        
        log.info(f"All characteristics with 4953 prefix: {all_characteristics}")
        
        if not client_tx_char_handle or not client_rx_char_handle:
            log.error("Could not find both characteristics")
            log.info(f"TX handle: {client_tx_char_handle}, RX handle: {client_rx_char_handle}")
            log.info(f"Full char-desc output:\n{char_result.stdout}")
            return False
        
        # Now start interactive gatttool for notifications
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
        
        # Enable notifications
        cccd_handle = client_tx_char_handle + 1
        log.info(f"Enabling notifications on handle {cccd_handle:04x}")
        proc.stdin.write(f"char-write-req {cccd_handle:04x} 0100\n")
        proc.stdin.flush()
        time.sleep(0.5)
        
        # Store process
        client_gatt_process = {
            'process': proc,
            'rx_char_handle': client_rx_char_handle,
            'use_gatttool': True
        }
        client_device_address = device_address
        
        # Start threads to drain stdout and stderr to prevent blocking
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
            global running, kill, peripheral_connected, RelayService
            buffer = ""
            while running and not kill:
                try:
                    # Get data from queue
                    try:
                        chunk = stdout_queue.get(timeout=0.1)
                        buffer += chunk
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            if 'Notification' in line or 'Indication' in line:
                                match = re.search(r'value: ([0-9a-f ]+)', line, re.IGNORECASE)
                                if match:
                                    hex_str = match.group(1).replace(' ', '')
                                    try:
                                        data = bytearray.fromhex(hex_str)
                                        log.info(f"CLIENT RX -> PERIPHERAL: {' '.join(f'{b:02x}' for b in data)}")
                                        if peripheral_connected and RelayService.tx_obj:
                                            RelayService.tx_obj.sendMessage(data)
                                    except ValueError:
                                        pass
                    except queue.Empty:
                        pass
                except Exception as e:
                    if running:
                        log.error(f"Notification read error: {e}")
                    break
        
        threading.Thread(target=read_notifications, daemon=True).start()
        
        client_connected = True
        log.info("BLE connection established")
        return True
        
    except Exception as e:
        log.error(f"Connection error: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def scan_and_connect_ble_gatt(bus, adapter_path, target_address=None, target_name=None, service_uuid=None, tx_char_uuid=None, rx_char_uuid=None):
    """Scan for and connect to target BLE device using BLE GATT only"""
    if target_address:
        log.info(f"Scanning for device with address: {target_address}")
    elif target_name:
        log.info(f"Scanning for device with name: {target_name}")
    else:
        log.error("Either target_address or target_name must be provided")
        return False
    
    # Start scanning
    try:
        adapter_obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
        adapter_iface = dbus.Interface(adapter_obj, ADAPTER_IFACE)
        adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)
        
        # Bluetooth should already be enabled by BluetoothController.enable_bluetooth() in main()
        # Verify it's powered, but don't try to set it (DBus signature issues with Properties.Set)
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
        last_log_time = 0
        
        log.info(f"Waiting up to {max_wait} seconds for device to appear...")
        
        while wait_time < max_wait and device_address is None:
            if target_address:
                device_address = find_device_by_address(bus, adapter_path, target_address)
            elif target_name:
                device_address = find_device_by_name(bus, adapter_path, target_name)
            
            if device_address:
                break
            
            if wait_time - last_log_time >= 5:
                log.info(f"Still scanning... ({wait_time}/{max_wait} seconds)")
                last_log_time = wait_time
            
            time.sleep(1)
            wait_time += 1
        
        if discovery_started_by_us:
            try:
                discovering = adapter_props.Get(ADAPTER_IFACE, "Discovering")
                if discovering:
                    adapter_iface.StopDiscovery()
                    log.info("Stopped BLE scan")
            except dbus.exceptions.DBusException as e:
                log.debug(f"Could not stop discovery: {e}")
        
        if not device_address:
            if target_address:
                log.error(f"Device {target_address} not found after {max_wait} seconds")
            elif target_name:
                log.error(f"Device '{target_name}' not found after {max_wait} seconds")
            return False
        
        # Find device path
        device_path = None
        remote_om = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        
        for path, interfaces in objects.items():
            if DEVICE_IFACE in interfaces:
                device_props = interfaces[DEVICE_IFACE]
                if device_props.get("Address") == device_address:
                    device_path = path
                    break
        
        if not device_path:
            log.error(f"Could not find device path for {device_address}")
            return False
        
        # Connect using BLE GATT via DBus (like millennium.py but as client)
        return connect_ble_gatt(bus, device_path, service_uuid, tx_char_uuid, rx_char_uuid)
        
    except Exception as e:
        log.error(f"Error in scan_and_connect_ble_gatt: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


# ============================================================================
# Cleanup and Signal Handling
# ============================================================================

def cleanup():
    """Clean up BLE services and connections"""
    global kill, app, adv, bluetooth_controller, pairThread, running
    global client_gatt_process, client_connected
    
    try:
        log.info("Cleaning up BLE relay probe...")
        kill = 1
        running = False
        
        # Disconnect from client device
        if client_gatt_process:
            try:
                if isinstance(client_gatt_process, dict):
                    if client_gatt_process.get('use_gatttool'):
                        # Stop gatttool process
                        proc = client_gatt_process.get('process')
                        if proc:
                            try:
                                proc.stdin.write("exit\n")
                                proc.stdin.flush()
                                time.sleep(0.5)
                                proc.terminate()
                                proc.wait(timeout=2)
                                log.info("Stopped gatttool process")
                            except:
                                try:
                                    proc.kill()
                                except:
                                    pass
                    else:
                        # Disconnect via DBus
                        device_obj = client_gatt_process.get('device_obj')
                        if device_obj:
                            device_iface = dbus.Interface(device_obj, DEVICE_IFACE)
                            device_iface.Disconnect()
                            log.info("Disconnected from client device")
            except Exception as e:
                log.debug(f"Error disconnecting from device: {e}")
        
        # Stop BLE notifications
        if RelayService.tx_obj is not None:
            try:
                RelayService.tx_obj.StopNotify()
                log.info("BLE notifications stopped")
            except Exception as e:
                log.debug(f"Error stopping notify: {e}")
        
        # Unregister BLE advertisement
        try:
            if 'adv' in globals() and adv is not None:
                bus = BleTools.get_bus()
                adapter = BleTools.find_adapter(bus)
                if adapter:
                    ad_manager = dbus.Interface(
                        bus.get_object(BLUEZ_SERVICE_NAME, adapter),
                        "org.bluez.LEAdvertisingManager1")
                    ad_manager.UnregisterAdvertisement(adv.get_path())
                    log.info("BLE advertisement unregistered")
        except Exception as e:
            log.debug(f"Error unregistering advertisement: {e}")
        
        # Unregister BLE application
        try:
            if 'app' in globals() and app is not None:
                bus = BleTools.get_bus()
                adapter = BleTools.find_adapter(bus)
                if adapter:
                    service_manager = dbus.Interface(
                        bus.get_object(BLUEZ_SERVICE_NAME, adapter),
                        "org.bluez.GattManager1")
                    service_manager.UnregisterApplication(app.get_path())
                    log.info("BLE application unregistered")
        except Exception as e:
            log.debug(f"Error unregistering application: {e}")
        
        # Stop Bluetooth controller pairing thread
        try:
            if 'bluetooth_controller' in globals() and bluetooth_controller is not None:
                bluetooth_controller.stop_pairing_thread()
                log.info("Bluetooth pairing thread stopped")
        except Exception as e:
            log.debug(f"Error stopping pairing thread: {e}")
        
        log.info("Cleanup completed")
    except Exception as e:
        log.error(f"Error in cleanup: {e}")
        import traceback
        log.error(traceback.format_exc())


def signal_handler(signum, frame):
    """Handle termination signals"""
    log.info(f"Received signal {signum}, cleaning up...")
    cleanup()
    try:
        if 'app' in globals() and app is not None:
            app.quit()
    except Exception:
        pass
    sys.exit(0)


def check_kill_flag():
    """Periodically check kill flag and quit app if set"""
    global kill, app
    if kill:
        log.info("Kill flag set, cleaning up and quitting application")
        cleanup()
        try:
            app.quit()
        except Exception:
            pass
        return False
    return True


# ============================================================================
# Main Application
# ============================================================================

def main():
    """Main entry point"""
    global app, adv, bluetooth_controller, pairThread, running, kill
    global DEFAULT_SERVICE_UUID, DEFAULT_TX_CHAR_UUID, DEFAULT_RX_CHAR_UUID
    
    # Store original values for argument parser defaults
    original_service_uuid = DEFAULT_SERVICE_UUID
    original_tx_char_uuid = DEFAULT_TX_CHAR_UUID
    original_rx_char_uuid = DEFAULT_RX_CHAR_UUID
    
    parser = argparse.ArgumentParser(description="BLE Relay Probe - Relay messages between BLE devices")
    parser.add_argument(
        "--target-address",
        help="MAC address of the target BLE device to connect to (e.g., AA:BB:CC:DD:EE:FF)"
    )
    parser.add_argument(
        "--auto-connect-millennium",
        action="store_true",
        help="Automatically scan and connect to a device named 'MILLENNIUM CHESS'"
    )
    parser.add_argument(
        "--service-uuid",
        default=original_service_uuid,
        help=f"Service UUID to use (default: {original_service_uuid})"
    )
    parser.add_argument(
        "--tx-char-uuid",
        default=original_tx_char_uuid,
        help=f"TX characteristic UUID (default: {original_tx_char_uuid})"
    )
    parser.add_argument(
        "--rx-char-uuid",
        default=original_rx_char_uuid,
        help=f"RX characteristic UUID (default: {original_rx_char_uuid})"
    )
    
    args = parser.parse_args()
    
    # Validate that either target-address or auto-connect-millennium is provided
    if not args.target_address and not args.auto_connect_millennium:
        parser.error("Either --target-address or --auto-connect-millennium must be provided")
    
    if args.target_address and args.auto_connect_millennium:
        parser.error("Cannot specify both --target-address and --auto-connect-millennium")
    
    # Update UUIDs if provided (need global to modify module-level variables)
    DEFAULT_SERVICE_UUID = args.service_uuid
    DEFAULT_TX_CHAR_UUID = args.tx_char_uuid
    DEFAULT_RX_CHAR_UUID = args.rx_char_uuid
    
    # Determine target address or name
    target_address = None
    target_name = None
    
    if args.auto_connect_millennium:
        target_name = "MILLENNIUM CHESS"
        log.info("Auto-connect mode: will scan for device named 'MILLENNIUM CHESS'")
    else:
        target_address = args.target_address.upper()
        
        # Validate MAC address format
        import re
        mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
        if not mac_pattern.match(target_address):
            log.error(f"Invalid MAC address format: {target_address}")
            log.error("Expected format: AA:BB:CC:DD:EE:FF")
            sys.exit(1)
    
    log.info("=" * 60)
    log.info("BLE Relay Probe Starting")
    log.info("=" * 60)
    if target_address:
        log.info(f"Target BLE device (address): {target_address}")
    elif target_name:
        log.info(f"Target BLE device (name): {target_name}")
    log.info(f"Service UUID: {DEFAULT_SERVICE_UUID}")
    log.info(f"TX Characteristic UUID: {DEFAULT_TX_CHAR_UUID}")
    log.info(f"RX Characteristic UUID: {DEFAULT_RX_CHAR_UUID}")
    log.info("=" * 60)
    
    # Create Bluetooth controller instance and start pairing thread
    bluetooth_controller = BluetoothController(device_name="BLE Relay Probe")
    bluetooth_controller.enable_bluetooth()
    bluetooth_controller.set_device_name("BLE Relay Probe")
    pairThread = bluetooth_controller.start_pairing_thread()
    
    time.sleep(2.5)
    
    # Initialize BLE application (peripheral/server)
    running = True
    app = Application()
    app.add_service(RelayService(0))
    
    # Register the application
    try:
        app.register()
        log.info("BLE application registered successfully")
    except Exception as e:
        log.error(f"Failed to register BLE application: {e}")
        import traceback
        log.error(traceback.format_exc())
        sys.exit(1)
    
    # Register advertisement
    adv = RelayAdvertisement(0)
    try:
        adv.register()
        log.info("BLE advertisement registered successfully")
    except Exception as e:
        log.error(f"Failed to register BLE advertisement: {e}")
        import traceback
        log.error(traceback.format_exc())
        sys.exit(1)
    
    log.info("BLE peripheral service registered and advertising")
    log.info("Waiting for BLE connection to peripheral...")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start periodic check for kill flag
    try:
        from gi.repository import GLib
        GLib.timeout_add(100, check_kill_flag)
    except ImportError:
        GObject.timeout_add(100, check_kill_flag)
    
    # Connect to target BLE device using BLE GATT only
    bus = BleTools.get_bus()
    adapter = BleTools.find_adapter(bus)
    
    # Start client connection in a separate thread to avoid blocking
    def connect_client():
        time.sleep(3)  # Give peripheral time to start advertising
        log.info("Starting BLE GATT client connection to target device...")
        if scan_and_connect_ble_gatt(
            bus, adapter,
            target_address=target_address,
            target_name=target_name,
            service_uuid=DEFAULT_SERVICE_UUID,
            tx_char_uuid=DEFAULT_TX_CHAR_UUID,
            rx_char_uuid=DEFAULT_RX_CHAR_UUID
        ):
            log.info("BLE GATT client connection established")
        else:
            log.error("Failed to establish BLE GATT client connection")
            global kill
            kill = 1
    
    client_thread = threading.Thread(target=connect_client, daemon=True)
    client_thread.start()
    
    # Main loop - run BLE application mainloop
    try:
        log.info("Entering main loop...")
        app.run()
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")
        running = False
    except Exception as e:
        log.error(f"Error in main loop: {e}")
        import traceback
        log.error(traceback.format_exc())
        running = False
    
    # Cleanup
    log.info("Shutting down...")
    running = False
    cleanup()
    
    time.sleep(0.5)
    
    try:
        if 'app' in globals() and app is not None:
            app.quit()
    except Exception:
        pass
    
    log.info("Disconnected")
    time.sleep(0.5)
    log.info("Exiting ble_relay_probe.py")


if __name__ == "__main__":
    main()
