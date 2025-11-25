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
    """Prepare device for BLE GATT connection: pair, trust, and disconnect any existing connections"""
    global client_device_path
    
    try:
        device_obj = bus.get_object(BLUEZ_SERVICE_NAME, device_path)
        device_iface = dbus.Interface(device_obj, DEVICE_IFACE)
        device_props = dbus.Interface(device_obj, DBUS_PROP_IFACE)
        
        props = get_device_properties(bus, device_path)
        if props:
            connected = props.get("Connected", False)
            paired = props.get("Paired", False)
            trusted = props.get("Trusted", False)
            address = props.get("Address", "unknown")
            log.info(f"Device state - Connected: {connected}, Paired: {paired}, Trusted: {trusted}, Address: {address}")
            
            if connected:
                log.info("Device is connected, disconnecting to prepare for BLE GATT connection...")
                try:
                    device_iface.Disconnect()
                    time.sleep(1)
                    log.info("Disconnected from device")
                except Exception as e:
                    log.debug(f"Disconnect attempt: {e}")
            
            if not trusted:
                log.info("Device is not trusted, setting Trusted=True...")
                try:
                    device_props.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
                    log.info("Device trusted successfully")
                    time.sleep(0.5)
                except Exception as e:
                    log.warning(f"Could not set Trusted property: {e}")
            
            if not paired:
                log.info("Device is not paired, attempting to pair...")
                try:
                    device_iface.Pair()
                    log.info("Pairing initiated, waiting for completion...")
                    for i in range(20):
                        time.sleep(0.5)
                        props = get_device_properties(bus, device_path)
                        if props and props.get("Paired", False):
                            log.info("Pairing successful")
                            try:
                                device_props.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
                            except:
                                pass
                            break
                        if props and props.get("Connected", False):
                            log.info("Device connected during pairing, disconnecting...")
                            try:
                                device_iface.Disconnect()
                                time.sleep(1)
                            except:
                                pass
                except dbus.exceptions.DBusException as e:
                    error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
                    if "AlreadyExists" in error_name or "Already paired" in str(e):
                        log.info("Device is already paired")
                    else:
                        log.warning(f"Pairing failed or not needed: {e}")
        
        props = get_device_properties(bus, device_path)
        if props and props.get("Connected", False):
            log.info("Ensuring device is disconnected before BLE GATT connection...")
            try:
                device_iface.Disconnect()
                time.sleep(1)
            except:
                pass
        
        client_device_path = device_path
        log.info("Device prepared for BLE GATT connection via gatttool")
        return True
    except Exception as e:
        log.error(f"Error preparing device: {e}")
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
        
        try:
            adapter = BleTools.find_adapter(bus)
            if adapter:
                gatt_client = dbus.Interface(
                    bus.get_object(BLUEZ_SERVICE_NAME, adapter),
                    "org.bluez.GattManager1")
                log.debug("Accessed GATT manager interface")
        except Exception as e:
            log.debug(f"Could not access GATT manager: {e}")
        
        props = device_props.GetAll(DEVICE_IFACE)
        services_resolved = props.get("ServicesResolved", False)
        
        if not services_resolved:
            log.info("Services not resolved, forcing BLE GATT connection via gatttool...")
            try:
                import subprocess
                device_address = props.get("Address", "")
                if device_address:
                    log.info(f"Connecting to {device_address} via BLE GATT using gatttool...")
                    try:
                        result = subprocess.run(
                            ['gatttool', '-b', device_address, '--primary'],
                            capture_output=True,
                            timeout=5,
                            text=True
                        )
                        if result.returncode == 0:
                            log.info("Discovered primary services via gatttool")
                            log.debug(f"gatttool output: {result.stdout[:200]}")
                            
                            import re
                            service_handle = None
                            for line in result.stdout.split('\n'):
                                if service_uuid.lower().replace('-', '') in line.lower().replace('-', '').replace(' ', ''):
                                    # Extract handle (e.g., "handle = 0x0030" -> "0030")
                                    match = re.search(r'handle\s*=\s*0x([0-9a-f]+)', line, re.IGNORECASE)
                                    if match:
                                        service_handle = match.group(1)
                                        break
                            
                            if service_handle:
                                log.info(f"Found target service handle: 0x{service_handle}")
                                end_handle = None
                                for line in result.stdout.split('\n'):
                                    if f'0x{service_handle}' in line.lower() or service_handle in line:
                                        range_match = re.search(r'handles\s+([0-9a-f]+)-([0-9a-f]+)', line, re.IGNORECASE)
                                        if range_match:
                                            end_handle = range_match.group(2)
                                            break
                                
                                if end_handle:
                                    handle_range = f'0x{service_handle}-0x{end_handle}'
                                else:
                                    handle_int = int(service_handle, 16)
                                    end_handle = f'{handle_int + 13:04x}'  # Assume ~14 handles
                                    handle_range = f'0x{service_handle}-0x{end_handle}'
                                
                                char_result = subprocess.run(
                                    ['gatttool', '-b', device_address, '--characteristics', handle_range],
                                    capture_output=True,
                                    timeout=5,
                                    text=True
                                )
                                if char_result.returncode == 0:
                                    log.info("Discovered characteristics via gatttool")
                                    log.debug(f"gatttool characteristics output: {char_result.stdout[:300]}")
                                else:
                                    log.warning(f"gatttool characteristics returned code {char_result.returncode}: {char_result.stderr[:200]}")
                            else:
                                log.warning("Could not find service handle in gatttool output")
                        else:
                            log.warning(f"gatttool returned code {result.returncode}: {result.stderr[:200]}")
                    except FileNotFoundError:
                        log.warning("gatttool not found - cannot force BLE GATT connection")
                        log.warning("Install bluez package: sudo apt-get install bluez")
                    except subprocess.TimeoutExpired:
                        log.warning("gatttool timed out")
                    except Exception as e:
                        log.debug(f"gatttool error: {e}")
                    
                    time.sleep(3)
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
                
                if services_resolved:
                    log.info("Services resolved")
                    break
                remote_om = dbus.Interface(
                    bus.get_object(BLUEZ_SERVICE_NAME, "/"),
                    DBUS_OM_IFACE)
                objects = remote_om.GetManagedObjects()
                service_uuid_upper = service_uuid.upper()
                for path, interfaces in objects.items():
                    if path.startswith(device_path) and "org.bluez.GattService1" in interfaces:
                        service_props = interfaces["org.bluez.GattService1"]
                        device_uuid = service_props.get("UUID", "")
                        if device_uuid.upper() == service_uuid_upper:
                            log.info(f"Service found even though ServicesResolved is False (UUID: {device_uuid})")
                            services_resolved = True
                            break
                if services_resolved:
                    break
                if (i + 1) % 10 == 0:
                    log.info(f"Still waiting for services... ({i * 0.5:.1f}s)")
                    try:
                        props = device_props.GetAll(DEVICE_IFACE)
                        _ = props.get("UUIDs", [])
                    except:
                        pass
        
        time.sleep(1)
        
        remote_om = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        
        device_objects = []
        for path, interfaces in objects.items():
            if path.startswith(device_path):
                device_objects.append((path, list(interfaces.keys())))
        
        log.info(f"Found {len(device_objects)} object(s) under device path:")
        for obj_path, ifaces in device_objects:
            log.info(f"  - {obj_path}: {', '.join(ifaces)}")
        
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
        
        service_path = None
        service_uuid_upper = service_uuid.upper()
        for path, interfaces in objects.items():
            if path.startswith(device_path) and "org.bluez.GattService1" in interfaces:
                props = interfaces["org.bluez.GattService1"]
                device_uuid = props.get("UUID", "")
                if device_uuid.upper() == service_uuid_upper:
                    service_path = path
                    log.info(f"Found target service at path: {path} (UUID: {device_uuid})")
                    break
        
        if not service_path:
            log.error(f"Service with UUID {service_uuid} not found")
            log.error("Available services listed above")
            return False
        
        available_chars = []
        for path, interfaces in objects.items():
            if path.startswith(service_path) and "org.bluez.GattCharacteristic1" in interfaces:
                props = interfaces["org.bluez.GattCharacteristic1"]
                char_uuid = props.get("UUID", "")
                available_chars.append((path, char_uuid))
        
        if available_chars:
            log.info(f"Available characteristics: {[f'{uuid} at {path}' for path, uuid in available_chars]}")
        else:
            log.warning("No characteristics found - may need to wait longer for D-Bus to update")
            time.sleep(2)
            remote_om = dbus.Interface(
                bus.get_object(BLUEZ_SERVICE_NAME, "/"),
                DBUS_OM_IFACE)
            objects = remote_om.GetManagedObjects()
            for path, interfaces in objects.items():
                if path.startswith(service_path) and "org.bluez.GattCharacteristic1" in interfaces:
                    props = interfaces["org.bluez.GattCharacteristic1"]
                    char_uuid = props.get("UUID", "")
                    available_chars.append((path, char_uuid))
            if available_chars:
                log.info(f"Found characteristics after additional wait: {[f'{uuid} at {path}' for path, uuid in available_chars]}")
        
        tx_uuid_upper = DEFAULT_TX_CHAR_UUID.upper()
        rx_uuid_upper = DEFAULT_RX_CHAR_UUID.upper()
        for path, char_uuid in available_chars:
            char_uuid_upper = char_uuid.upper()
            
            if char_uuid_upper == tx_uuid_upper:
                client_tx_char_path = path
                log.info(f"Found TX characteristic at: {path} (UUID: {char_uuid})")
            elif char_uuid_upper == rx_uuid_upper:
                client_rx_char_path = path
                log.info(f"Found RX characteristic at: {path} (UUID: {char_uuid})")
        
        if not client_tx_char_path or not client_rx_char_path:
            log.error("Could not find both TX and RX characteristics")
            if not client_tx_char_path:
                log.error(f"TX characteristic {DEFAULT_TX_CHAR_UUID} not found")
            if not client_rx_char_path:
                log.error(f"RX characteristic {DEFAULT_RX_CHAR_UUID} not found")
            if available_chars:
                log.error(f"Available characteristics: {[uuid for _, uuid in available_chars]}")
            else:
                log.error("Available characteristics: []")
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
        
        client_tx_char_obj = char_obj
        char_props.connect_to_signal("PropertiesChanged", on_notification_received)
        client_notify_handler = char_props
        
        try:
            char_iface.StartNotify()
            log.info("Enabled notifications using StartNotify")
        except dbus.exceptions.DBusException as e:
            log.warning(f"StartNotify failed: {e}, trying CCCD method")
            
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
        
        if not connect_to_device(bus, device_path):
            return False
        
        log.info("Device prepared, gatttool will establish BLE GATT connection...")
        time.sleep(1)
        
        if not discover_services(bus, device_path, service_uuid):
            log.error("Service discovery failed - device may not be advertising the expected service")
            log.error("Make sure the target device is running and advertising the correct service UUID")
            return False
        
        if not setup_notifications(bus, client_tx_char_path):
            return False
        
        client_rx_char_obj = bus.get_object(BLUEZ_SERVICE_NAME, client_rx_char_path)
        
        global client_connected
        client_connected = True
        
        log.info("BLE client connection established successfully via gatttool")
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
    global kill, app, adv, running
    global client_device_path, client_connected
    
    try:
        log.info("Cleaning up BLE relay probe...")
        kill = 1
        running = False
        
        if client_connected and client_device_path:
            try:
                bus = BleTools.get_bus()
                device_obj = bus.get_object(BLUEZ_SERVICE_NAME, client_device_path)
                device_iface = dbus.Interface(device_obj, DEVICE_IFACE)
                device_iface.Disconnect()
                log.info("Disconnected from client device")
            except Exception as e:
                log.debug(f"Error disconnecting client: {e}")
        
        if RelayService.tx_obj is not None:
            try:
                RelayService.tx_obj.StopNotify()
                log.info("BLE notifications stopped")
            except Exception as e:
                log.debug(f"Error stopping notify: {e}")
        
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
    global app, adv, running, kill
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
    
    # Enable Bluetooth adapter for BLE GATT
    try:
        bus = BleTools.get_bus()
        adapter = BleTools.find_adapter(bus)
        if adapter:
            adapter_obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter)
            adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)
            adapter_props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(1))
            adapter_props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(1))
            log.info("Bluetooth enabled and made discoverable")
    except Exception as e:
        log.warning(f"Could not enable Bluetooth: {e}")
    
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

