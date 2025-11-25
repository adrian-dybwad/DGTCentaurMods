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
import time
import threading
import signal
import dbus
import dbus.mainloop.glib
try:
    from gi.repository import GObject
except ImportError:
    import gobject as GObject

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
        
        for path, interfaces in objects.items():
            if DEVICE_IFACE in interfaces:
                device_props = interfaces[DEVICE_IFACE]
                # Check both Alias and Name properties
                alias = device_props.get("Alias", "")
                name = device_props.get("Name", "")
                address = device_props.get("Address", "")
                
                if alias == device_name or name == device_name:
                    log.info(f"Found device '{device_name}' at path: {path} (Address: {address})")
                    return path
        
        log.warning(f"Device with name '{device_name}' not found")
        return None
    except Exception as e:
        log.error(f"Error finding device by name: {e}")
        import traceback
        log.error(traceback.format_exc())
        return None


def connect_to_device(bus, device_path):
    """Connect to a BLE device"""
    global client_device_path, client_connected
    
    try:
        device_obj = bus.get_object(BLUEZ_SERVICE_NAME, device_path)
        device_iface = dbus.Interface(device_obj, DEVICE_IFACE)
        
        log.info(f"Connecting to device at {device_path}...")
        device_iface.Connect()
        client_device_path = device_path
        client_connected = True
        log.info("Successfully connected to device")
        return True
    except dbus.exceptions.DBusException as e:
        log.error(f"Failed to connect to device: {e}")
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
        remote_om = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        
        # Find the service with matching UUID
        service_path = None
        for path, interfaces in objects.items():
            if "org.bluez.GattService1" in interfaces:
                props = interfaces["org.bluez.GattService1"]
                if props.get("UUID") == service_uuid:
                    service_path = path
                    log.info(f"Found service at path: {path}")
                    break
        
        if not service_path:
            log.error(f"Service with UUID {service_uuid} not found")
            return False
        
        # Find TX and RX characteristics
        for path, interfaces in objects.items():
            if path.startswith(service_path) and "org.bluez.GattCharacteristic1" in interfaces:
                props = interfaces["org.bluez.GattCharacteristic1"]
                char_uuid = props.get("UUID")
                
                if char_uuid == DEFAULT_TX_CHAR_UUID:
                    client_tx_char_path = path
                    log.info(f"Found TX characteristic at: {path}")
                elif char_uuid == DEFAULT_RX_CHAR_UUID:
                    client_rx_char_path = path
                    log.info(f"Found RX characteristic at: {path}")
        
        if not client_tx_char_path or not client_rx_char_path:
            log.error("Could not find both TX and RX characteristics")
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
        adapter_iface.StartDiscovery()
        log.info("Started BLE scan")
        
        # Wait for device to be discovered
        max_wait = 30  # seconds
        wait_time = 0
        device_path = None
        
        while wait_time < max_wait and device_path is None:
            if target_address:
                device_path = find_device_by_address(bus, adapter_path, target_address)
            elif target_name:
                device_path = find_device_by_name(bus, adapter_path, target_name)
            
            if device_path:
                break
            time.sleep(1)
            wait_time += 1
        
        adapter_iface.StopDiscovery()
        
        if not device_path:
            if target_address:
                log.error(f"Device {target_address} not found after {max_wait} seconds")
            elif target_name:
                log.error(f"Device '{target_name}' not found after {max_wait} seconds")
            return False
        
        # Connect to device
        if not connect_to_device(bus, device_path):
            return False
        
        # Wait a bit for connection to stabilize
        time.sleep(2)
        
        # Discover services
        if not discover_services(bus, device_path, service_uuid):
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
        default=DEFAULT_SERVICE_UUID,
        help=f"Service UUID to use (default: {DEFAULT_SERVICE_UUID})"
    )
    parser.add_argument(
        "--tx-char-uuid",
        default=DEFAULT_TX_CHAR_UUID,
        help=f"TX characteristic UUID (default: {DEFAULT_TX_CHAR_UUID})"
    )
    parser.add_argument(
        "--rx-char-uuid",
        default=DEFAULT_RX_CHAR_UUID,
        help=f"RX characteristic UUID (default: {DEFAULT_RX_CHAR_UUID})"
    )
    
    args = parser.parse_args()
    
    # Validate that either target-address or auto-connect-millennium is provided
    if not args.target_address and not args.auto_connect_millennium:
        parser.error("Either --target-address or --auto-connect-millennium must be provided")
    
    if args.target_address and args.auto_connect_millennium:
        parser.error("Cannot specify both --target-address and --auto-connect-millennium")
    
    # Update UUIDs if provided (need global to modify module-level variables)
    global DEFAULT_SERVICE_UUID, DEFAULT_TX_CHAR_UUID, DEFAULT_RX_CHAR_UUID
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

