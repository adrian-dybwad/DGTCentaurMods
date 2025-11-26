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

# BLE Client state (using gatttool handles)
client_device_address = None
client_tx_char_handle = None
client_rx_char_handle = None
client_gatt_process = None

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
        global running, kill, client_connected, client_rx_char_handle, client_gatt_process
        
        if kill or not running:
            return
        
        try:
            bytes_data = bytearray()
            for i in range(0, len(value)):
                bytes_data.append(value[i])
            
            log.info(f"PERIPHERAL RX -> CLIENT: {' '.join(f'{b:02x}' for b in bytes_data)}")
            log.info(f"PERIPHERAL RX -> CLIENT (ASCII): {bytes_data.decode('utf-8', errors='replace')}")
            
            # Relay to client connection if connected
            if client_connected and client_rx_char_handle is not None and client_gatt_process is not None:
                try:
                    # Write to remote BLE device's RX characteristic using gatttool
                    hex_data = ''.join(f'{b:02x}' for b in bytes_data)
                    cmd = f"char-write-req {client_rx_char_handle:04x} {hex_data}\n"
                    client_gatt_process.stdin.write(cmd)
                    client_gatt_process.stdin.flush()
                    log.debug("Successfully relayed message to client via gatttool")
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


def connect_ble_gatt(device_address, service_uuid, tx_char_uuid, rx_char_uuid):
    """Connect to BLE device using gatttool and discover services/characteristics"""
    global client_device_address, client_tx_char_handle, client_rx_char_handle, client_gatt_process, client_connected
    
    try:
        log.info(f"Connecting to {device_address} via BLE GATT using gatttool...")
        
        # Step 1: Discover primary services
        result = subprocess.run(
            ['gatttool', '-b', device_address, '--primary'],
            capture_output=True,
            timeout=10,
            text=True
        )
        
        if result.returncode != 0:
            log.error(f"gatttool --primary failed: {result.stderr}")
            return False
        
        log.info("Discovered primary services via gatttool")
        services = parse_gatttool_primary_output(result.stdout)
        
        # Find target service
        service_uuid_lower = service_uuid.lower()
        target_service = None
        for svc in services:
            if svc['uuid'] == service_uuid_lower:
                target_service = svc
                break
        
        if not target_service:
            log.error(f"Service {service_uuid} not found")
            log.info(f"Available services: {[s['uuid'] for s in services]}")
            return False
        
        log.info(f"Found target service: {service_uuid} (handles {target_service['start_handle']:04x}-{target_service['end_handle']:04x})")
        
        # Step 2: Discover characteristics in the service
        result = subprocess.run(
            ['gatttool', '-b', device_address, '--characteristics', f'0x{target_service["start_handle"]:04x}', f'0x{target_service["end_handle"]:04x}'],
            capture_output=True,
            timeout=10,
            text=True
        )
        
        if result.returncode != 0:
            log.error(f"gatttool --characteristics failed: {result.stderr}")
            return False
        
        log.info("Discovered characteristics via gatttool")
        characteristics = parse_gatttool_characteristics_output(result.stdout)
        
        # Find TX and RX characteristics
        tx_char_uuid_lower = tx_char_uuid.lower()
        rx_char_uuid_lower = rx_char_uuid.lower()
        
        for char in characteristics:
            if char['uuid'] == tx_char_uuid_lower:
                client_tx_char_handle = char['value_handle']
                log.info(f"Found TX characteristic: {tx_char_uuid} (handle: {client_tx_char_handle:04x})")
            elif char['uuid'] == rx_char_uuid_lower:
                client_rx_char_handle = char['value_handle']
                log.info(f"Found RX characteristic: {rx_char_uuid} (handle: {client_rx_char_handle:04x})")
        
        if not client_tx_char_handle or not client_rx_char_handle:
            log.error("Could not find both TX and RX characteristics")
            if not client_tx_char_handle:
                log.error(f"TX characteristic {tx_char_uuid} not found")
            if not client_rx_char_handle:
                log.error(f"RX characteristic {rx_char_uuid} not found")
            log.info(f"Available characteristics: {[c['uuid'] for c in characteristics]}")
            return False
        
        # Step 3: Start interactive gatttool session for notifications and writes
        log.info("Starting interactive gatttool session...")
        client_gatt_process = subprocess.Popen(
            ['gatttool', '-b', device_address, '-I'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0  # Unbuffered for real-time communication
        )
        
        # Connect in interactive mode
        log.info("Sending connect command to gatttool...")
        client_gatt_process.stdin.write("connect\n")
        client_gatt_process.stdin.flush()
        
        # Wait for connection confirmation
        time.sleep(2)
        
        # Check if connection was successful
        if client_gatt_process.poll() is not None:
            stderr_output = client_gatt_process.stderr.read()
            log.error(f"gatttool process exited immediately: {stderr_output}")
            return False
        
        # Enable notifications on TX characteristic (find CCCD handle)
        # CCCD is typically at value_handle + 1
        cccd_handle = client_tx_char_handle + 1
        log.info(f"Enabling notifications on TX characteristic (CCCD handle: {cccd_handle:04x})")
        client_gatt_process.stdin.write(f"char-write-req {cccd_handle:04x} 0100\n")
        client_gatt_process.stdin.flush()
        time.sleep(0.5)
        
        # Start thread to read notifications
        def read_notifications():
            global running, kill, peripheral_connected, RelayService
            log.info("Starting notification reader thread")
            buffer = ""
            while running and not kill and client_gatt_process:
                try:
                    if client_gatt_process.poll() is not None:
                        log.warning("gatttool process ended")
                        break
                    
                    # Read available output (non-blocking)
                    if select.select([client_gatt_process.stdout], [], [], 0.1)[0]:
                        chunk = client_gatt_process.stdout.read(1024)
                        if chunk:
                            buffer += chunk
                            # Process complete lines
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                line = line.strip()
                                if not line:
                                    continue
                                
                                # Parse notification: Notification handle = 0xXXXX value: XX XX XX ...
                                if 'Notification handle =' in line or 'Indication handle =' in line:
                                    match = re.search(r'value: ([0-9a-f ]+)', line, re.IGNORECASE)
                                    if match:
                                        hex_str = match.group(1).replace(' ', '')
                                        try:
                                            bytes_data = bytearray.fromhex(hex_str)
                                            log.info(f"CLIENT RX -> PERIPHERAL: {' '.join(f'{b:02x}' for b in bytes_data)}")
                                            log.info(f"CLIENT RX -> PERIPHERAL (ASCII): {bytes_data.decode('utf-8', errors='replace')}")
                                            
                                            # Relay to peripheral if connected
                                            if peripheral_connected and RelayService.tx_obj is not None:
                                                RelayService.tx_obj.sendMessage(bytes_data)
                                                log.debug("Successfully relayed message to peripheral")
                                            else:
                                                log.warning("Peripheral not connected, message dropped")
                                        except ValueError:
                                            log.debug(f"Could not parse notification value: {hex_str}")
                                else:
                                    # Log other gatttool output for debugging
                                    log.debug(f"gatttool: {line}")
                except Exception as e:
                    if running:
                        log.error(f"Error reading notifications: {e}")
                    break
            
            log.info("Notification reader thread stopped")
        
        notification_thread = threading.Thread(target=read_notifications, daemon=True)
        notification_thread.start()
        
        client_device_address = device_address
        client_connected = True
        log.info("BLE GATT connection established successfully")
        return True
        
    except FileNotFoundError:
        log.error("gatttool not found - cannot connect via BLE GATT")
        log.error("Install bluez package: sudo apt-get install bluez")
        return False
    except subprocess.TimeoutExpired:
        log.error("gatttool command timed out")
        return False
    except Exception as e:
        log.error(f"Error connecting via BLE GATT: {e}")
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
        
        adapter_props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(1))
        
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
        
        # Connect using BLE GATT only (via gatttool)
        return connect_ble_gatt(device_address, service_uuid, tx_char_uuid, rx_char_uuid)
        
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
        
        # Stop gatttool process
        if client_gatt_process:
            try:
                client_gatt_process.stdin.write("exit\n")
                client_gatt_process.stdin.flush()
                time.sleep(0.5)
                client_gatt_process.terminate()
                client_gatt_process.wait(timeout=2)
                log.info("Stopped gatttool process")
            except Exception as e:
                log.debug(f"Error stopping gatttool: {e}")
                try:
                    client_gatt_process.kill()
                except:
                    pass
        
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
