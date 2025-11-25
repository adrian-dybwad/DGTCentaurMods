#!/usr/bin/env python3
"""
BLE Relay Probe

This probe acts as a BLE relay between two BLE devices:
1. Acts as a BLE peripheral (server) - accepts incoming BLE connections (like millennium.py)
2. Acts as a BLE client - connects to a nominated BLE host
3. Relays and logs all messages between the two connections

Usage:
    python3 tools/dev-tools/ble_relay_probe.py --target-address AA:BB:CC:DD:EE:FF
    python3 tools/dev-tools/ble_relay_probe.py --target-address AA:BB:CC:DD:EE:FF --service-uuid 49535343-FE7D-4AE5-8FA9-9FAFD205E455
    python3 tools/dev-tools/ble_relay_probe.py --auto-connect-millennium
"""

import argparse
import sys
import os
import time
import threading
import signal
import re
import subprocess
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

# BLE Client state
client_device_path = None
client_tx_char_path = None
client_rx_char_path = None
client_tx_char_obj = None
client_rx_char_obj = None
client_notify_handler = None

# Default service UUIDs (can be overridden via command line)
# Millennium ChessLink service UUID
DEFAULT_SERVICE_UUID = "49535343-FE7D-4AE5-8FA9-9FAFD205E455"
DEFAULT_TX_CHAR_UUID = "49535343-1E4D-4BD9-BA61-23C647249616"  # Peripheral TX -> App RX
DEFAULT_RX_CHAR_UUID = "49535343-8841-43F4-A8D4-ECBE34729BB3"  # App TX -> Peripheral RX


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
            "MinInterval": dbus.UInt16(0x0014),  # 20ms
            "MaxInterval": dbus.UInt16(0x0098),  # 152.5ms
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
        # Use current value of DEFAULT_SERVICE_UUID at instantiation time
        Service.__init__(self, index, DEFAULT_SERVICE_UUID, True)
        self.add_characteristic(RelayTXCharacteristic(self))
        self.add_characteristic(RelayRXCharacteristic(self))


class RelayRXCharacteristic(Characteristic):
    """BLE RX characteristic - receives data from BLE client and relays to remote host"""
    
    def __init__(self, service):
        # Use current value of DEFAULT_RX_CHAR_UUID at instantiation time
        Characteristic.__init__(
            self, DEFAULT_RX_CHAR_UUID,
            ["write", "write-without-response"], service)
    
    def WriteValue(self, value, options):
        """When the remote device writes data via BLE, relay it to the client connection"""
        global running, kill, client_connected, client_rx_char_obj
        
        if kill or not running:
            return
        
        try:
            bytes_data = bytearray()
            for i in range(0, len(value)):
                bytes_data.append(value[i])
            
            log.info(f"PERIPHERAL RX -> CLIENT: {' '.join(f'{b:02x}' for b in bytes_data)}")
            log.info(f"PERIPHERAL RX -> CLIENT (ASCII): {bytes_data.decode('utf-8', errors='replace')}")
            
            # Relay to client connection if connected
            if client_connected and client_rx_char_obj is not None:
                try:
                    # Write to remote BLE device's RX characteristic
                    client_rx_char_obj.WriteValue(
                        [dbus.Byte(b) for b in bytes_data],
                        {},
                        dbus_interface=GATT_CHRC_IFACE
                    )
                    log.debug("Successfully relayed message to client")
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
        # Use current value of DEFAULT_TX_CHAR_UUID at instantiation time
        Characteristic.__init__(
            self, DEFAULT_TX_CHAR_UUID,
            ["read", "notify"], service)
        self.notifying = False
    
    def sendMessage(self, data):
        """Send a message via BLE notification"""
        if not self.notifying:
            return
        log.debug(f"CLIENT -> PERIPHERAL TX: {' '.join(f'{b:02x}' for b in data)}")
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
# BLE Client Implementation
# ============================================================================

def find_device_by_address(bus, adapter_path, address):
    """Find a BLE device by MAC address"""
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
                    return path
        
        log.warning(f"Device with address {address} not found")
        return None
    except Exception as e:
        log.error(f"Error finding device: {e}")
        import traceback
        log.error(traceback.format_exc())
        return None


def find_device_by_name(bus, adapter_path, device_name):
    """Find a BLE device by name (Alias or Name property)"""
    try:
        remote_om = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        
        # Normalize the target name for comparison (case-insensitive, strip whitespace)
        target_name_normalized = device_name.strip().upper()
        found_devices = []
        
        for path, interfaces in objects.items():
            if DEVICE_IFACE in interfaces:
                device_props = interfaces[DEVICE_IFACE]
                # Check both Alias and Name properties
                alias = device_props.get("Alias", "")
                name = device_props.get("Name", "")
                address = device_props.get("Address", "")
                rssi = device_props.get("RSSI", "N/A")
                
                # Log all devices for debugging
                device_info = f"Address: {address}, Alias: '{alias}', Name: '{name}', RSSI: {rssi}"
                found_devices.append(device_info)
                
                # Case-insensitive comparison
                alias_normalized = str(alias).strip().upper()
                name_normalized = str(name).strip().upper()
                
                if alias_normalized == target_name_normalized or name_normalized == target_name_normalized:
                    log.info(f"Found device '{device_name}' at path: {path} (Address: {address})")
                    return path
        
        # Log all discovered devices if target not found
        if found_devices:
            log.info(f"Discovered {len(found_devices)} BLE device(s):")
            for dev_info in found_devices:
                log.info(f"  - {dev_info}")
        else:
            log.warning("No BLE devices found in object tree")
        
        log.warning(f"Device with name '{device_name}' not found")
        return None
    except Exception as e:
        log.error(f"Error finding device by name: {e}")
        import traceback
        log.error(traceback.format_exc())
        return None


def get_device_properties(bus, device_path):
    """Get device properties"""
    try:
        device_obj = bus.get_object(BLUEZ_SERVICE_NAME, device_path)
        device_props = dbus.Interface(device_obj, DBUS_PROP_IFACE)
        props = device_props.GetAll(DEVICE_IFACE)
        return props
    except Exception as e:
        log.debug(f"Error getting device properties: {e}")
        return None


def connect_to_device(bus, device_path):
    """Connect to a BLE device with retry and pairing support"""
    global client_device_path, client_connected
    
    try:
        device_obj = bus.get_object(BLUEZ_SERVICE_NAME, device_path)
        device_iface = dbus.Interface(device_obj, DEVICE_IFACE)
        device_props = dbus.Interface(device_obj, DBUS_PROP_IFACE)
        
        # Check device state
        props = get_device_properties(bus, device_path)
        if props:
            connected = props.get("Connected", False)
            paired = props.get("Paired", False)
            trusted = props.get("Trusted", False)
            address = props.get("Address", "unknown")
            log.info(f"Device state - Connected: {connected}, Paired: {paired}, Trusted: {trusted}, Address: {address}")
            
            # If already connected, we're good
            if connected:
                log.info("Device is already connected")
                client_device_path = device_path
                client_connected = True
                return True
            
            # Trust the device if not trusted (required for some BLE devices)
            if not trusted:
                log.info("Device is not trusted, setting Trusted=True...")
                try:
                    device_props.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
                    log.info("Device trusted successfully")
                    time.sleep(0.5)
                except Exception as e:
                    log.warning(f"Could not set Trusted property: {e}")
            
            # Try to disconnect first if it shows as connected (sometimes state is stale)
            if connected:
                log.info("Device shows as connected, attempting disconnect first...")
                try:
                    device_iface.Disconnect()
                    time.sleep(1)
                    log.info("Disconnected from device")
                except Exception as e:
                    log.debug(f"Disconnect attempt: {e}")
            
            # Try to pair if not paired
            if not paired:
                log.info("Device is not paired, attempting to pair...")
                try:
                    device_iface.Pair()
                    log.info("Pairing initiated, waiting for completion...")
                    # Wait for pairing to complete (up to 10 seconds)
                    for i in range(20):
                        time.sleep(0.5)
                        props = get_device_properties(bus, device_path)
                        if props and props.get("Paired", False):
                            log.info("Pairing successful")
                            # Trust after pairing
                            try:
                                device_props.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
                            except:
                                pass
                            break
                        if props and props.get("Connected", False):
                            log.info("Device connected during pairing")
                            client_device_path = device_path
                            client_connected = True
                            return True
                except dbus.exceptions.DBusException as e:
                    error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
                    if "AlreadyExists" in error_name or "Already paired" in str(e):
                        log.info("Device is already paired")
                    else:
                        log.warning(f"Pairing failed or not needed: {e}")
        
        # Wait a bit after discovery/trusting before attempting connection
        log.info("Waiting for device to become connectable...")
        time.sleep(2)
        
        # Try to connect with retries
        max_retries = 5
        for attempt in range(max_retries):
            try:
                # Refresh device properties before each attempt
                props = get_device_properties(bus, device_path)
                if props:
                    connected = props.get("Connected", False)
                    if connected:
                        log.info("Device is now connected")
                        client_device_path = device_path
                        client_connected = True
                        return True
                
                log.info(f"Connecting to device at {device_path}... (attempt {attempt + 1}/{max_retries})")
                device_iface.Connect()
                
                # Wait a moment and verify connection
                time.sleep(2)
                props = get_device_properties(bus, device_path)
                if props and props.get("Connected", False):
                    client_device_path = device_path
                    client_connected = True
                    log.info("Successfully connected to device")
                    return True
                else:
                    log.warning(f"Connect() returned but device not showing as connected, retrying...")
            except dbus.exceptions.DBusException as e:
                error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
                error_msg = str(e)
                
                if "NotAvailable" in error_name or "NotAvailable" in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = 3 + attempt  # Increasing wait time
                        log.warning(f"Device not available, waiting {wait_time}s before retry... ({error_msg})")
                        log.info("This may mean the device needs to be in a connectable state")
                        log.info("Make sure the device is advertising and ready to accept connections")
                        time.sleep(wait_time)
                        continue
                    else:
                        log.error(f"Device not available after {max_retries} attempts: {error_msg}")
                        log.error("The device may not be in a connectable state")
                        log.error("Try ensuring the device is actively advertising and ready for connections")
                elif "AlreadyConnected" in error_name or "Already connected" in error_msg:
                    log.info("Device is already connected")
                    client_device_path = device_path
                    client_connected = True
                    return True
                elif "InProgress" in error_name or "In progress" in error_msg:
                    log.info("Connection in progress, waiting...")
                    time.sleep(3)
                    props = get_device_properties(bus, device_path)
                    if props and props.get("Connected", False):
                        client_device_path = device_path
                        client_connected = True
                        return True
                else:
                    log.error(f"Failed to connect: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
        
        return False
    except Exception as e:
        log.error(f"Error connecting to device: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def discover_services(bus, device_path, service_uuid):
    """Discover services and characteristics on the connected device"""
    global client_tx_char_path, client_rx_char_path
    
    try:
        device_obj = bus.get_object(BLUEZ_SERVICE_NAME, device_path)
        device_iface = dbus.Interface(device_obj, DEVICE_IFACE)
        device_props = dbus.Interface(device_obj, DBUS_PROP_IFACE)
        
        # CRITICAL: BlueZ doesn't automatically discover GATT services like Android does
        # We need to trigger discovery by accessing the GATT client interface
        # Try to get the adapter's GATT client manager and trigger discovery
        try:
            adapter = BleTools.find_adapter(bus)
            if adapter:
                # Try to access GATT client interface - this may trigger service discovery
                gatt_client = dbus.Interface(
                    bus.get_object(BLUEZ_SERVICE_NAME, adapter),
                    "org.bluez.GattManager1")
                log.debug("Accessed GATT manager interface")
        except Exception as e:
            log.debug(f"Could not access GATT manager: {e}")
        
        # Check if services are already resolved
        props = device_props.GetAll(DEVICE_IFACE)
        services_resolved = props.get("ServicesResolved", False)
        
        # CRITICAL FINDING: The UUIDs property shows Classic Bluetooth UUIDs (00001101=SPP, 00001200=PnP)
        # This means BlueZ is connecting via Classic Bluetooth, NOT BLE GATT
        # nRF Connect uses BLE GATT, which is why it can see the services
        # We need to force BLE GATT connection using gatttool or bluetoothctl GATT menu
        try:
            uuids = props.get("UUIDs", [])
            log.debug(f"Device UUIDs property: {uuids}")
            if uuids:
                uuid_strs = [str(u) for u in uuids]
                log.info(f"Device UUIDs property shows {len(uuids)} service(s): {uuid_strs}")
                # Check if these are Classic Bluetooth UUIDs (not BLE GATT)
                classic_bt_uuids = ['00001101', '00001200', '0000110a', '0000110c', '0000110e']
                is_classic = any(any(cb_uuid in str(u).lower() for cb_uuid in classic_bt_uuids) for u in uuids)
                if is_classic:
                    log.warning("Device UUIDs indicate Classic Bluetooth connection, not BLE GATT!")
                    log.warning("BlueZ Connect() may be using Classic Bluetooth instead of BLE GATT")
                    log.warning("Need to force BLE GATT connection using gatttool or bluetoothctl GATT menu")
        except:
            pass
        
        # Force BLE GATT service discovery using gatttool
        # gatttool connects via BLE GATT and automatically discovers services
        if not services_resolved:
            log.info("Services not resolved, forcing BLE GATT connection via gatttool...")
            try:
                device_address = props.get("Address", "")
                if device_address:
                    # Use gatttool to connect via BLE GATT and discover services
                    # This forces BLE GATT connection instead of Classic Bluetooth
                    log.info(f"Using gatttool to force BLE GATT connection to {device_address}")
                    try:
                        # gatttool -b ADDRESS --primary will list primary services (triggers discovery)
                        result = subprocess.run(
                            ['gatttool', '-b', device_address, '--primary'],
                            capture_output=True,
                            timeout=5,
                            text=True
                        )
                        if result.returncode == 0:
                            log.info("gatttool successfully connected via BLE GATT")
                            log.debug(f"gatttool output: {result.stdout[:200]}")
                        else:
                            log.warning(f"gatttool returned code {result.returncode}: {result.stderr[:200]}")
                    except FileNotFoundError:
                        log.warning("gatttool not found - cannot force BLE GATT connection")
                        log.warning("Install bluez package: sudo apt-get install bluez")
                    except subprocess.TimeoutExpired:
                        log.warning("gatttool timed out")
                    except Exception as e:
                        log.debug(f"gatttool error: {e}")
                    
                    # Wait for BlueZ to update its D-Bus objects after gatttool connection
                    time.sleep(2)
            except Exception as e:
                log.debug(f"GATT connection attempt: {e}")
        
        if not services_resolved:
            log.info("Services not yet resolved, waiting for service discovery...")
            # Wait for services to be resolved (up to 15 seconds)
            for i in range(30):
                time.sleep(0.5)
                props = device_props.GetAll(DEVICE_IFACE)
                services_resolved = props.get("ServicesResolved", False)
                connected = props.get("Connected", False)
                
                if not connected:
                    log.warning("Device disconnected during service discovery, reconnecting...")
                    try:
                        device_iface.Connect()
                        time.sleep(1)
                    except:
                        pass
                
                if services_resolved:
                    log.info("Services resolved")
                    break
                # Also check if services appeared even if ServicesResolved is False
                remote_om = dbus.Interface(
                    bus.get_object(BLUEZ_SERVICE_NAME, "/"),
                    DBUS_OM_IFACE)
                objects = remote_om.GetManagedObjects()
                service_uuid_upper = service_uuid.upper()
                for path, interfaces in objects.items():
                    if path.startswith(device_path) and "org.bluez.GattService1" in interfaces:
                        service_props = interfaces["org.bluez.GattService1"]
                        device_uuid = service_props.get("UUID", "")
                        # Compare case-insensitively
                        if device_uuid.upper() == service_uuid_upper:
                            log.info(f"Service found even though ServicesResolved is False (UUID: {device_uuid})")
                            services_resolved = True
                            break
                if services_resolved:
                    break
                # Log progress every 5 seconds
                if (i + 1) % 10 == 0:
                    log.info(f"Still waiting for services... ({i * 0.5:.1f}s)")
                    # Try accessing UUIDs again to trigger discovery
                    try:
                        props = device_props.GetAll(DEVICE_IFACE)
                        _ = props.get("UUIDs", [])
                    except:
                        pass
        
        # Give a bit more time for all services to appear
        time.sleep(1)
        
        remote_om = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        
        # Log ALL objects under the device path for debugging
        device_objects = []
        for path, interfaces in objects.items():
            if path.startswith(device_path):
                device_objects.append((path, list(interfaces.keys())))
        
        log.info(f"Found {len(device_objects)} object(s) under device path:")
        for obj_path, ifaces in device_objects:
            log.info(f"  - {obj_path}: {', '.join(ifaces)}")
        
        # Log all services found for debugging
        found_services = []
        for path, interfaces in objects.items():
            if path.startswith(device_path) and "org.bluez.GattService1" in interfaces:
                service_props = interfaces["org.bluez.GattService1"]
                uuid = service_props.get("UUID", "unknown")
                primary = service_props.get("Primary", False)
                found_services.append(f"{uuid} (Primary: {primary}) at {path}")
        
        if found_services:
            log.info(f"Found {len(found_services)} GATT service(s) on device:")
            for svc in found_services:
                log.info(f"  - {svc}")
        else:
            log.warning("No GATT services found on device")
            log.warning("This may mean:")
            log.warning("  1. The device doesn't advertise BLE services")
            log.warning("  2. The device needs to be in a specific mode to advertise services")
            log.warning("  3. The device uses a different connection method (e.g., RFCOMM)")
            log.warning("  4. Services haven't been discovered yet (try waiting longer)")
        
        # Find the service with matching UUID (case-insensitive comparison)
        service_path = None
        service_uuid_upper = service_uuid.upper()
        for path, interfaces in objects.items():
            if path.startswith(device_path) and "org.bluez.GattService1" in interfaces:
                props = interfaces["org.bluez.GattService1"]
                device_uuid = props.get("UUID", "")
                # Compare case-insensitively
                if device_uuid.upper() == service_uuid_upper:
                    service_path = path
                    log.info(f"Found target service at path: {path} (UUID: {device_uuid})")
                    break
        
        if not service_path:
            log.error(f"Service with UUID {service_uuid} not found")
            log.error("Available services listed above")
            return False
        
        # Get service handle range from gatttool output to query characteristics
        # First, try to discover characteristics using gatttool
        service_handle_start = None
        service_handle_end = None
        try:
            # Get device address from device properties
            device_props_refresh = device_props.GetAll(DEVICE_IFACE)
            device_address = device_props_refresh.get("Address", "")
            if device_address:
                log.info(f"Using gatttool to discover characteristics for service {service_uuid}")
                # First get the service handle range
                result = subprocess.run(
                    ['gatttool', '-b', device_address, '--primary'],
                    capture_output=True,
                    timeout=5,
                    text=True
                )
                if result.returncode == 0:
                    # Parse output to find service handle range
                    # Format: attr handle: 0x0030, end grp handle: 0x003d uuid: 49535343-fe7d-4ae5-8fa9-9fafd205e455
                    for line in result.stdout.split('\n'):
                        if service_uuid.replace('-', '').lower() in line.replace('-', '').lower():
                            # Extract handle range
                            match = re.search(r'attr handle:\s*(0x[0-9a-fA-F]+).*end grp handle:\s*(0x[0-9a-fA-F]+)', line)
                            if match:
                                service_handle_start = match.group(1)
                                service_handle_end = match.group(2)
                                log.info(f"Found service handle range: {service_handle_start} to {service_handle_end}")
                                break
                    
                    # Now query characteristics for this service
                    if service_handle_start and service_handle_end:
                        log.info(f"Querying characteristics in range {service_handle_start}-{service_handle_end}")
                        char_result = subprocess.run(
                            ['gatttool', '-b', device_address, '--characteristics', f'{service_handle_start}', f'{service_handle_end}'],
                            capture_output=True,
                            timeout=5,
                            text=True
                        )
                        if char_result.returncode == 0:
                            log.info("Discovered characteristics via gatttool")
                            log.debug(f"gatttool characteristics output: {char_result.stdout[:500]}")
                            
                            # Parse characteristics from output
                            # Format: handle: 0x0031, char properties: 0x12, char value handle: 0x0032, uuid: 49535343-1e4d-4bd9-ba61-23c647249616
                            tx_uuid_upper = DEFAULT_TX_CHAR_UUID.upper().replace('-', '')
                            rx_uuid_upper = DEFAULT_RX_CHAR_UUID.upper().replace('-', '')
                            found_chars = []
                            for line in char_result.stdout.split('\n'):
                                if 'uuid:' in line.lower():
                                    # Extract UUID
                                    uuid_match = re.search(r'uuid:\s*([0-9a-fA-F-]+)', line, re.IGNORECASE)
                                    if uuid_match:
                                        char_uuid = uuid_match.group(1)
                                        char_uuid_normalized = char_uuid.upper().replace('-', '')
                                        found_chars.append((char_uuid, line))
                                        
                                        # Check if this is our TX or RX characteristic
                                        if char_uuid_normalized == tx_uuid_upper:
                                            log.info(f"Found TX characteristic via gatttool: {char_uuid}")
                                        elif char_uuid_normalized == rx_uuid_upper:
                                            log.info(f"Found RX characteristic via gatttool: {char_uuid}")
                            
                            if found_chars:
                                log.info(f"Found {len(found_chars)} characteristic(s) via gatttool:")
                                for char_uuid, line in found_chars:
                                    log.info(f"  - {char_uuid}: {line[:100]}")
                            
                            # Wait a bit for BlueZ to update D-Bus objects
                            time.sleep(2)
                        else:
                            log.warning(f"gatttool characteristics query returned code {char_result.returncode}: {char_result.stderr[:200]}")
        except Exception as e:
            log.debug(f"Error querying characteristics via gatttool: {e}")
        
        # Refresh D-Bus objects after gatttool characteristic discovery
        remote_om = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        
        # Find TX and RX characteristics (case-insensitive comparison)
        tx_uuid_upper = DEFAULT_TX_CHAR_UUID.upper()
        rx_uuid_upper = DEFAULT_RX_CHAR_UUID.upper()
        found_characteristics = []
        for path, interfaces in objects.items():
            if path.startswith(service_path) and "org.bluez.GattCharacteristic1" in interfaces:
                props = interfaces["org.bluez.GattCharacteristic1"]
                char_uuid = props.get("UUID", "")
                char_uuid_upper = char_uuid.upper()
                found_characteristics.append((path, char_uuid))
                
                if char_uuid_upper == tx_uuid_upper:
                    client_tx_char_path = path
                    log.info(f"Found TX characteristic at: {path} (UUID: {char_uuid})")
                elif char_uuid_upper == rx_uuid_upper:
                    client_rx_char_path = path
                    log.info(f"Found RX characteristic at: {path} (UUID: {char_uuid})")
        
        # Log all found characteristics for debugging
        if found_characteristics:
            log.info(f"Available characteristics: {[f'{uuid} at {path}' for path, uuid in found_characteristics]}")
        else:
            log.warning("Available characteristics: []")
            log.warning("Characteristics not found in D-Bus object tree")
            log.warning("This may mean BlueZ hasn't populated the characteristics yet")
            log.warning("Try waiting longer or check if gatttool successfully discovered characteristics")
        
        if not client_tx_char_path or not client_rx_char_path:
            log.error("Could not find both TX and RX characteristics")
            if not client_tx_char_path:
                log.error(f"TX characteristic {DEFAULT_TX_CHAR_UUID} not found")
            if not client_rx_char_path:
                log.error(f"RX characteristic {DEFAULT_RX_CHAR_UUID} not found")
            return False
        
        log.info("Successfully discovered services and characteristics")
        return True
    except Exception as e:
        log.error(f"Error discovering services: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def setup_notifications(bus, char_path):
    """Subscribe to notifications from a characteristic"""
    global client_tx_char_obj, client_notify_handler
    
    try:
        char_obj = bus.get_object(BLUEZ_SERVICE_NAME, char_path)
        char_props = dbus.Interface(char_obj, DBUS_PROP_IFACE)
        char_iface = dbus.Interface(char_obj, GATT_CHRC_IFACE)
        
        # Set up signal handler for property changes (notifications) BEFORE enabling
        # This ensures we catch notifications as soon as they're enabled
        client_tx_char_obj = char_obj
        char_props.connect_to_signal("PropertiesChanged", on_notification_received)
        client_notify_handler = char_props
        
        # Try to enable notifications using StartNotify method
        try:
            char_iface.StartNotify()
            log.info("Enabled notifications using StartNotify")
        except dbus.exceptions.DBusException as e:
            log.warning(f"StartNotify failed: {e}, trying CCCD method")
            
            # Fallback: Try to write to CCCD directly
            remote_om = dbus.Interface(
                bus.get_object(BLUEZ_SERVICE_NAME, "/"),
                DBUS_OM_IFACE)
            objects = remote_om.GetManagedObjects()
            
            cccd_path = None
            for path, interfaces in objects.items():
                if path.startswith(char_path) and "org.bluez.GattDescriptor1" in interfaces:
                    desc_props = interfaces["org.bluez.GattDescriptor1"]
                    if desc_props.get("UUID") == "00002902-0000-1000-8000-00805f9b34fb":  # CCCD UUID
                        cccd_path = path
                        break
            
            if cccd_path:
                cccd_obj = bus.get_object(BLUEZ_SERVICE_NAME, cccd_path)
                cccd_iface = dbus.Interface(cccd_obj, "org.bluez.GattDescriptor1")
                
                # Enable notifications (value 0x01)
                cccd_iface.WriteValue([dbus.Byte(0x01), dbus.Byte(0x00)], {})
                log.info("Enabled notifications via CCCD")
            else:
                log.error("Could not find CCCD and StartNotify failed")
                return False
        
        log.info("Successfully set up notifications")
        return True
    except Exception as e:
        log.error(f"Error setting up notifications: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def on_notification_received(interface, changed_props, invalidated_props):
    """Handle notifications from the remote BLE device"""
    global running, kill, peripheral_connected, RelayService
    
    if kill or not running:
        return
    
    try:
        if "Value" in changed_props:
            value = changed_props["Value"]
            bytes_data = bytearray()
            for byte in value:
                bytes_data.append(int(byte))
            
            log.info(f"CLIENT RX -> PERIPHERAL: {' '.join(f'{b:02x}' for b in bytes_data)}")
            log.info(f"CLIENT RX -> PERIPHERAL (ASCII): {bytes_data.decode('utf-8', errors='replace')}")
            
            # Relay to peripheral if connected
            if peripheral_connected and RelayService.tx_obj is not None:
                RelayService.tx_obj.sendMessage(bytes_data)
                log.debug("Successfully relayed message to peripheral")
            else:
                log.warning("Peripheral not connected, message dropped")
    except Exception as e:
        log.error(f"Error handling notification: {e}")
        import traceback
        log.error(traceback.format_exc())


def scan_and_connect(bus, adapter_path, target_address=None, target_name=None, service_uuid=None):
    """Scan for and connect to the target BLE device by address or name"""
    global client_rx_char_obj
    
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
        
        # Enable discovery
        adapter_props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(1))
        
        # Make sure adapter is discoverable (helps with BLE scanning)
        try:
            adapter_props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(1))
            log.info("Adapter set to discoverable mode")
        except Exception as e:
            log.debug(f"Could not set discoverable: {e}")
        
        # Check if discovery is already in progress
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
                # Try to start discovery anyway
                try:
                    adapter_iface.StartDiscovery()
                    discovery_started_by_us = True
                    log.info("Started BLE scan")
                except dbus.exceptions.DBusException as e2:
                    if "InProgress" in str(e2) or "org.bluez.Error.InProgress" in str(e2):
                        log.info("Discovery already in progress, using existing scan")
                    else:
                        raise
        
        # Give discovery a moment to start finding devices
        time.sleep(2)
        
        # Wait for device to be discovered
        max_wait = 30  # seconds
        wait_time = 0
        device_path = None
        last_log_time = 0
        
        log.info(f"Waiting up to {max_wait} seconds for device to appear...")
        
        while wait_time < max_wait and device_path is None:
            if target_address:
                device_path = find_device_by_address(bus, adapter_path, target_address)
            elif target_name:
                device_path = find_device_by_name(bus, adapter_path, target_name)
            
            if device_path:
                break
            
            # Log progress every 5 seconds
            if wait_time - last_log_time >= 5:
                log.info(f"Still scanning... ({wait_time}/{max_wait} seconds)")
                last_log_time = wait_time
            
            time.sleep(1)
            wait_time += 1
        
        # Only stop discovery if we started it
        if discovery_started_by_us:
            try:
                discovering = adapter_props.Get(ADAPTER_IFACE, "Discovering")
                if discovering:
                    adapter_iface.StopDiscovery()
                    log.info("Stopped BLE scan")
            except dbus.exceptions.DBusException as e:
                log.debug(f"Could not stop discovery (may have been stopped already): {e}")
        
        if not device_path:
            if target_address:
                log.error(f"Device {target_address} not found after {max_wait} seconds")
            elif target_name:
                log.error(f"Device '{target_name}' not found after {max_wait} seconds")
            return False
        
        # Connect to device
        if not connect_to_device(bus, device_path):
            return False
        
        # Wait for connection to stabilize and services to be available
        log.info("Waiting for connection to stabilize...")
        time.sleep(3)
        
        # Discover services
        if not discover_services(bus, device_path, service_uuid):
            log.error("Service discovery failed - device may not be advertising the expected service")
            log.error("Make sure the target device is running and advertising the correct service UUID")
            return False
        
        # Set up notifications on TX characteristic
        if not setup_notifications(bus, client_tx_char_path):
            return False
        
        # Get RX characteristic object for writing
        client_rx_char_obj = bus.get_object(BLUEZ_SERVICE_NAME, client_rx_char_path)
        
        log.info("BLE client connection established successfully")
        return True
    except Exception as e:
        log.error(f"Error in scan_and_connect: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


# ============================================================================
# Main Application
# ============================================================================

def cleanup():
    """Clean up BLE services and connections"""
    global kill, app, adv, bluetooth_controller, pairThread, running
    global client_device_path, client_connected
    
    try:
        log.info("Cleaning up BLE relay probe...")
        kill = 1
        running = False
        
        # Disconnect client
        if client_connected and client_device_path:
            try:
                bus = BleTools.get_bus()
                device_obj = bus.get_object(BLUEZ_SERVICE_NAME, client_device_path)
                device_iface = dbus.Interface(device_obj, DEVICE_IFACE)
                device_iface.Disconnect()
                log.info("Disconnected from client device")
            except Exception as e:
                log.debug(f"Error disconnecting client: {e}")
        
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
    
    # Update UUIDs if provided (now we can modify the global variables)
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
    
    # Small delay to let bt-agent initialize
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
    
    # Connect to target BLE device (client mode)
    bus = BleTools.get_bus()
    adapter = BleTools.find_adapter(bus)
    
    # Start client connection in a separate thread to avoid blocking
    def connect_client():
        time.sleep(3)  # Give peripheral time to start advertising
        log.info("Starting client connection to target device...")
        if scan_and_connect(bus, adapter, target_address=target_address, target_name=target_name, service_uuid=DEFAULT_SERVICE_UUID):
            log.info("Client connection established")
        else:
            log.error("Failed to establish client connection")
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
    
    # Give cleanup time to complete
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

