#!/usr/bin/env python3
"""
Bluetooth Classic SPP Relay with BLE Support

This relay connects to "MILLENNIUM CHESS" via Bluetooth Classic SPP (RFCOMM)
and relays data between that device and a client connected to this relay.
Also provides BLE service matching millennium.py for host connections.

Usage:
    python3 tools/universal_relay.py
"""

import argparse
import sys
import os
import time
import threading
import signal
import psutil
import bluetooth
import dbus
import dbus.mainloop.glib
try:
    from gi.repository import GObject
except ImportError:
    import gobject as GObject

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board.bluetooth_controller import BluetoothController
from DGTCentaurMods.games.millennium import receive_data
from DGTCentaurMods.thirdparty.advertisement import Advertisement
from DGTCentaurMods.thirdparty.service import Application, Service, Characteristic
from DGTCentaurMods.thirdparty.bletools import BleTools

# Global state
running = True
kill = 0
millennium_connected = False
client_connected = False
ble_connected = False

# Socket references
millennium_sock = None
server_sock = None
client_sock = None

# BLE references
ble_app = None
ble_adv = None

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"


# ============================================================================
# BLE Service Implementation (matching millennium.py)
# ============================================================================

class UARTAdvertisement(Advertisement):
    """BLE advertisement for Millennium ChessLink service"""
    def __init__(self, index):
        Advertisement.__init__(self, index, "peripheral")
        self.add_local_name("MILLENNIUM CHESS")
        self.include_tx_power = True
        # Millennium ChessLink Transparent UART service UUID
        self.add_service_uuid("49535343-FE7D-4AE5-8FA9-9FAFD205E455")
        log.info("BLE Advertisement initialized with name: MILLENNIUM CHESS")
        log.info("BLE Advertisement service UUID: 49535343-FE7D-4AE5-8FA9-9FAFD205E455")
    
    def register_ad_callback(self):
        """Callback when advertisement is successfully registered"""
        log.info("BLE advertisement registered successfully")
        log.info("Device should now be discoverable as 'MILLENNIUM CHESS'")
    
    def register_ad_error_callback(self, error):
        """Callback when advertisement registration fails"""
        log.error(f"Failed to register BLE advertisement: {error}")
        log.error("Check that BlueZ is running and BLE is enabled")
    
    def register(self):
        """Register advertisement with iOS/macOS compatible options"""
        try:
            bus = BleTools.get_bus()
            adapter = BleTools.find_adapter(bus)
            log.info(f"Found Bluetooth adapter: {adapter}")
            
            ad_manager = dbus.Interface(
                bus.get_object("org.bluez", adapter),
                "org.bluez.LEAdvertisingManager1")
            
            # iOS/macOS compatibility options
            options = {
                "MinInterval": dbus.UInt16(0x0014),  # 20ms
                "MaxInterval": dbus.UInt16(0x0098),  # 152.5ms
            }
            
            log.info("Registering BLE advertisement with iOS/macOS compatible intervals")
            ad_manager.RegisterAdvertisement(
                self.get_path(),
                options,
                reply_handler=self.register_ad_callback,
                error_handler=self.register_ad_error_callback)
        except Exception as e:
            log.error(f"Exception during BLE advertisement registration: {e}")
            import traceback
            log.error(traceback.format_exc())


class UARTService(Service):
    """BLE UART service for Millennium ChessLink protocol - Transparent UART service"""
    tx_obj = None
    
    # Millennium ChessLink Transparent UART service UUID
    UART_SVC_UUID = "49535343-FE7D-4AE5-8FA9-9FAFD205E455"
    
    def __init__(self, index):
        Service.__init__(self, index, self.UART_SVC_UUID, True)
        self.add_characteristic(UARTTXCharacteristic(self))
        self.add_characteristic(UARTRXCharacteristic(self))


class UARTRXCharacteristic(Characteristic):
    """BLE RX characteristic - receives Millennium protocol commands from app and logs them"""
    # Millennium ChessLink App TX → Peripheral RX characteristic UUID
    UARTRX_CHARACTERISTIC_UUID = "49535343-8841-43F4-A8D4-ECBE34729BB3"
    
    def __init__(self, service):
        Characteristic.__init__(
            self, self.UARTRX_CHARACTERISTIC_UUID,
            ["write", "write-without-response"], service)
    
    def WriteValue(self, value, options):
        """When the remote device writes data via BLE, log the incoming bytes"""
        global kill, ble_connected
        if kill:
            return
        
        try:
            bytes_data = bytearray()
            for i in range(0, len(value)):
                bytes_data.append(value[i])
            
            # Log incoming bytes
            log.info(f"BLE RX (incoming bytes): {' '.join(f'{b:02x}' for b in bytes_data)}")
            log.info(f"BLE RX (hex string): {bytes_data.hex()}")
            log.info(f"BLE RX (length): {len(bytes_data)} bytes")
            
            # Try to decode as ASCII for readability (non-printable chars will be shown as hex)
            try:
                ascii_str = bytes_data.decode('utf-8', errors='replace')
                if all(c.isprintable() or c in '\n\r\t' for c in ascii_str):
                    log.info(f"BLE RX (ASCII): {repr(ascii_str)}")
            except:
                pass

            # Process each byte through receive_data
            for byte_val in bytes_data:
                receive_data(byte_val)
            
            if millennium_sock is not None:
                # Write to MILLENNIUM CHESS
                millennium_sock.send(bytes_data)

            ble_connected = True
        except Exception as e:
            log.error(f"Error in WriteValue: {e}")
            import traceback
            log.error(traceback.format_exc())
            raise


class UARTTXCharacteristic(Characteristic):
    """BLE TX characteristic - sends Millennium protocol responses via notifications"""
    # Millennium ChessLink Peripheral TX → App RX characteristic UUID
    UARTTX_CHARACTERISTIC_UUID = "49535343-1E4D-4BD9-BA61-23C647249616"
    
    def __init__(self, service):
        Characteristic.__init__(
            self, self.UARTTX_CHARACTERISTIC_UUID,
            ["read", "notify"], service)
        self.notifying = False
    
    def sendMessage(self, data):
        """Send a message via BLE notification"""
        if not self.notifying:
            return
        log.debug(f"BLE TX -> Client: {' '.join(f'{b:02x}' for b in data)}")
        tosend = bytearray()
        for x in range(0, len(data)):
            tosend.append(data[x])
        UARTService.tx_obj.updateValue(tosend)
    
    def StartNotify(self):
        """Called when BLE client subscribes to notifications"""
        try:
            log.info("TX Characteristic StartNotify called - BLE client subscribing to notifications")
            UARTService.tx_obj = self
            self.notifying = True
            global ble_connected
            ble_connected = True
            log.info("BLE notifications enabled successfully")
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
        global ble_connected
        ble_connected = False
        return self.notifying
    
    def updateValue(self, value):
        """Update the characteristic value and notify subscribers"""
        if not self.notifying:
            return
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
# Bluetooth Classic SPP Functions
# ============================================================================

def find_millennium_device():
    """Find the MILLENNIUM CHESS device by name"""
    log.info("Looking for MILLENNIUM CHESS device...")
    
    # First, try to find in paired devices using bluetoothctl
    try:
        import subprocess
        result = subprocess.run(['bluetoothctl', 'devices'], 
                              capture_output=True, timeout=5, text=True)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Device' in line:
                    parts = line.strip().split(' ', 2)
                    if len(parts) >= 3:
                        addr = parts[1]
                        name = parts[2]
                        log.info(f"Paired device: {name} ({addr})")
                        if name and "MILLENNIUM CHESS" in name.upper():
                            log.info(f"Found MILLENNIUM CHESS in paired devices: {addr}")
                            return addr
    except Exception as e:
        log.debug(f"Could not check paired devices: {e}")
    
    # If not found in paired devices, do a discovery scan
    log.info("Scanning for MILLENNIUM CHESS device...")
    devices = bluetooth.discover_devices(duration=8, lookup_names=True, flush_cache=True)
    
    for addr, name in devices:
        log.info(f"Found device: {name} ({addr})")
        if name and "MILLENNIUM CHESS" in name.upper():
            log.info(f"Found MILLENNIUM CHESS at address: {addr}")
            return addr
    
    log.warning("MILLENNIUM CHESS device not found in scan")
    return None


def find_millennium_service(device_addr):
    """Find the RFCOMM service on the MILLENNIUM CHESS device"""
    log.info(f"Discovering services on {device_addr}...")
    
    services = bluetooth.find_service(address=device_addr)
    
    for service in services:
        log.info(f"Service: {service.get('name', 'Unknown')} - "
                 f"Protocol: {service.get('protocol', 'Unknown')} - "
                 f"Port: {service.get('port', 'Unknown')}")
        
        # Look for Serial Port Profile
        if service.get('protocol') == 'RFCOMM':
            port = service.get('port')
            if port is not None:
                log.info(f"Found RFCOMM service on port {port}")
                return port
    
    log.warning("No RFCOMM service found on MILLENNIUM CHESS device")
    return None


def connect_to_millennium():
    """Connect to the MILLENNIUM CHESS device"""
    global millennium_sock, millennium_connected
    
    try:
        # Find device
        device_addr = find_millennium_device()
        if not device_addr:
            log.error("Could not find MILLENNIUM CHESS device")
            return False
        
        # Find service
        port = find_millennium_service(device_addr)
        if port is None:
            # Try common RFCOMM ports
            log.info("Trying common RFCOMM ports...")
            for common_port in [1, 2, 3, 4, 5]:
                try:
                    log.info(f"Attempting connection to {device_addr} on port {common_port}...")
                    sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
                    sock.connect((device_addr, common_port))
                    millennium_sock = sock
                    millennium_connected = True
                    log.info(f"Connected to MILLENNIUM CHESS on port {common_port}")
                    return True
                except Exception as e:
                    log.debug(f"Failed to connect on port {common_port}: {e}")
                    try:
                        sock.close()
                    except:
                        pass
            log.error("Could not connect to MILLENNIUM CHESS on any common port")
            return False
        
        # Connect to the service
        log.info(f"Connecting to MILLENNIUM CHESS at {device_addr}:{port}...")
        millennium_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        millennium_sock.connect((device_addr, port))
        millennium_connected = True
        log.info("Connected to MILLENNIUM CHESS successfully")
        return True
        
    except Exception as e:
        log.error(f"Error connecting to MILLENNIUM CHESS: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def millennium_to_client():
    """Relay data from MILLENNIUM CHESS to client"""
    global running, millennium_sock, client_sock, millennium_connected, client_connected
    
    log.info("Starting MILLENNIUM -> Client relay thread")
    try:
        while running and not kill:
            try:
                if not millennium_connected or millennium_sock is None:
                    time.sleep(0.1)
                    continue
                
                if not client_connected or client_sock is None:
                    time.sleep(0.1)
                    continue
                
                # Read from MILLENNIUM CHESS
                data = millennium_sock.recv(1024)
                if len(data) > 0:
                    data_bytes = bytearray(data)
                    log.info(f"MILLENNIUM -> Client: {' '.join(f'{b:02x}' for b in data_bytes)}")
                    log.debug(f"MILLENNIUM -> Client (ASCII): {data_bytes.decode('utf-8', errors='replace')}")
                    
                    # Write to client
                    client_sock.send(data)
            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error in MILLENNIUM -> Client relay: {e}")
                millennium_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error in MILLENNIUM -> Client relay: {e}")
                break
    except Exception as e:
        log.error(f"MILLENNIUM -> Client thread error: {e}")
    finally:
        log.info("MILLENNIUM -> Client relay thread stopped")
        millennium_connected = False


def client_to_millennium():
    """Relay data from client to MILLENNIUM CHESS"""
    global running, millennium_sock, client_sock, millennium_connected, client_connected
    
    log.info("Starting Client -> MILLENNIUM relay thread")
    try:
        while running and not kill:
            try:
                if not client_connected or client_sock is None:
                    time.sleep(0.1)
                    continue
                
                if not millennium_connected or millennium_sock is None:
                    time.sleep(0.1)
                    continue
                
                # Read from client
                data = client_sock.recv(1024)
                if len(data) > 0:
                    data_bytes = bytearray(data)
                    log.info(f"Client -> MILLENNIUM: {' '.join(f'{b:02x}' for b in data_bytes)}")
                    log.debug(f"Client -> MILLENNIUM (ASCII): {data_bytes.decode('utf-8', errors='replace')}")
                    
                    # Process each byte through receive_data
                    for byte_val in data_bytes:
                        receive_data(byte_val)
                    
                    # Write to MILLENNIUM CHESS
                    millennium_sock.send(data)
            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error in Client -> MILLENNIUM relay: {e}")
                client_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error in Client -> MILLENNIUM relay: {e}")
                break
    except Exception as e:
        log.error(f"Client -> MILLENNIUM thread error: {e}")
    finally:
        log.info("Client -> MILLENNIUM relay thread stopped")
        client_connected = False


def cleanup():
    """Clean up connections and resources"""
    global kill, running, millennium_sock, client_sock, server_sock
    global millennium_connected, client_connected, ble_app, ble_adv
    
    try:
        log.info("Cleaning up relay...")
        kill = 1
        running = False
        
        # Clean up BLE services
        try:
            log.info("Cleaning up BLE services...")
            
            # Stop BLE notifications
            if UARTService.tx_obj is not None:
                try:
                    UARTService.tx_obj.StopNotify()
                    log.info("BLE notifications stopped")
                except Exception as e:
                    log.debug(f"Error stopping BLE notify: {e}")
            
            # Unregister BLE advertisement
            if ble_adv is not None:
                try:
                    bus = BleTools.get_bus()
                    adapter = BleTools.find_adapter(bus)
                    if adapter:
                        ad_manager = dbus.Interface(
                            bus.get_object("org.bluez", adapter),
                            "org.bluez.LEAdvertisingManager1")
                        ad_manager.UnregisterAdvertisement(ble_adv.get_path())
                        log.info("BLE advertisement unregistered")
                except Exception as e:
                    log.debug(f"Error unregistering BLE advertisement: {e}")
            
            # Unregister BLE application
            if ble_app is not None:
                try:
                    bus = BleTools.get_bus()
                    adapter = BleTools.find_adapter(bus)
                    if adapter:
                        service_manager = dbus.Interface(
                            bus.get_object("org.bluez", adapter),
                            "org.bluez.GattManager1")
                        service_manager.UnregisterApplication(ble_app.get_path())
                        log.info("BLE application unregistered")
                except Exception as e:
                    log.debug(f"Error unregistering BLE application: {e}")
            
            # Quit BLE application mainloop
            if ble_app is not None:
                try:
                    ble_app.quit()
                    log.info("BLE application mainloop stopped")
                except Exception as e:
                    log.debug(f"Error quitting BLE app: {e}")
        except Exception as e:
            log.debug(f"Error in BLE cleanup: {e}")
        
        # Close client connection
        if client_sock:
            try:
                client_sock.close()
                log.info("Client socket closed")
            except Exception as e:
                log.debug(f"Error closing client socket: {e}")
        
        # Close MILLENNIUM connection
        if millennium_sock:
            try:
                millennium_sock.close()
                log.info("MILLENNIUM CHESS socket closed")
            except Exception as e:
                log.debug(f"Error closing MILLENNIUM socket: {e}")
        
        # Close server socket
        if server_sock:
            try:
                server_sock.close()
                log.info("Server socket closed")
            except Exception as e:
                log.debug(f"Error closing server socket: {e}")
        
        millennium_connected = False
        client_connected = False
        
        log.info("Cleanup completed")
    except Exception as e:
        log.error(f"Error in cleanup: {e}")
        import traceback
        log.error(traceback.format_exc())


def signal_handler(signum, frame):
    """Handle termination signals"""
    log.info(f"Received signal {signum}, cleaning up...")
    cleanup()
    sys.exit(0)


def main():
    """Main entry point"""
    global server_sock, client_sock, millennium_sock
    global millennium_connected, client_connected, running, kill
    global ble_app, ble_adv
    
    parser = argparse.ArgumentParser(description="Bluetooth Classic SPP Relay with BLE - Connect to MILLENNIUM CHESS and relay data")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="RFCOMM port for server (default: auto-assign)"
    )
    
    args = parser.parse_args()
    
    log.info("=" * 60)
    log.info("Bluetooth Classic SPP Relay with BLE Starting")
    log.info("=" * 60)
    
    # Initialize BLE application
    log.info("Initializing BLE service...")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    ble_app = Application()
    ble_app.add_service(UARTService(0))
    
    # Register the BLE application
    try:
        ble_app.register()
        log.info("BLE application registered successfully")
    except Exception as e:
        log.error(f"Failed to register BLE application: {e}")
        import traceback
        log.error(traceback.format_exc())
        log.warning("Continuing without BLE support...")
        ble_app = None
    
    # Register BLE advertisement
    if ble_app is not None:
        ble_adv = UARTAdvertisement(0)
        try:
            ble_adv.register()
            log.info("BLE advertisement registered successfully")
            log.info("BLE service registered and advertising as 'MILLENNIUM CHESS'")
            log.info("Waiting for BLE connection...")
        except Exception as e:
            log.error(f"Failed to register BLE advertisement: {e}")
            import traceback
            log.error(traceback.format_exc())
            log.warning("Continuing without BLE advertisement...")
            ble_adv = None
    
    # Start BLE mainloop in a separate thread
    def ble_mainloop():
        """Run BLE application mainloop in background thread"""
        if ble_app is not None:
            try:
                ble_app.run()
            except Exception as e:
                log.error(f"Error in BLE mainloop: {e}")
    
    if ble_app is not None:
        ble_thread = threading.Thread(target=ble_mainloop, daemon=True)
        ble_thread.start()
        log.info("BLE mainloop thread started")
    
    # Create Bluetooth controller instance and start pairing thread
    bluetooth_controller = BluetoothController(device_name="SPP Relay")
    bluetooth_controller.enable_bluetooth()
    bluetooth_controller.set_device_name("SPP Relay")
    pair_thread = bluetooth_controller.start_pairing_thread()
    
    time.sleep(2)
    
    # Kill rfcomm if it is started
    os.system('sudo service rfcomm stop')
    time.sleep(2)
    for p in psutil.process_iter(attrs=['pid', 'name']):
        if str(p.info["name"]) == "rfcomm":
            p.kill()
    
    iskilled = 0
    log.info("Checking for rfcomm processes...")
    while iskilled == 0:
        iskilled = 1
        for p in psutil.process_iter(attrs=['pid', 'name']):
            if str(p.info["name"]) == "rfcomm":
                iskilled = 0
        time.sleep(0.1)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize server socket
    log.info("Setting up server socket...")
    server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
    server_sock.bind(("", args.port if args.port else bluetooth.PORT_ANY))
    server_sock.settimeout(0.5)
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    uuid = "94f39d29-7d6d-437d-973b-fba39e49d4ee"
    bluetooth.advertise_service(server_sock, "SPPRelayServer", service_id=uuid,
                              service_classes=[uuid, bluetooth.SERIAL_PORT_CLASS],
                              profiles=[bluetooth.SERIAL_PORT_PROFILE])
    
    log.info(f"Server listening on RFCOMM channel: {port}")
    
    # Connect to MILLENNIUM CHESS in a separate thread
    def connect_millennium():
        time.sleep(1)  # Give server time to start
        if connect_to_millennium():
            log.info("MILLENNIUM CHESS connection established")
        else:
            log.error("Failed to connect to MILLENNIUM CHESS")
            global kill
            kill = 1
    
    millennium_thread = threading.Thread(target=connect_millennium, daemon=True)
    millennium_thread.start()
    
    # Wait for client connection
    log.info("Waiting for client connection...")
    connected = False
    while not connected and not kill:
        try:
            client_sock, client_info = server_sock.accept()
            connected = True
            client_connected = True
            log.info(f"Client connected from {client_info}")
        except bluetooth.BluetoothError:
            # Timeout, check kill flag
            time.sleep(0.1)
        except Exception as e:
            if running:
                log.error(f"Error accepting client connection: {e}")
            time.sleep(0.1)
    
    if kill:
        log.info("Exiting...")
        cleanup()
        sys.exit(0)
    
    # Wait for MILLENNIUM connection if not already connected
    max_wait = 30
    wait_time = 0
    while not millennium_connected and wait_time < max_wait and not kill:
        time.sleep(0.5)
        wait_time += 0.5
        if wait_time % 5 == 0:
            log.info(f"Waiting for MILLENNIUM CHESS connection... ({wait_time}/{max_wait} seconds)")
    
    if not millennium_connected:
        log.error("MILLENNIUM CHESS connection timeout")
        cleanup()
        sys.exit(1)
    
    if kill:
        cleanup()
        sys.exit(0)
    
    log.info("Both connections established - starting relay")
    
    # Start relay threads
    millennium_to_client_thread = threading.Thread(target=millennium_to_client, daemon=True)
    client_to_millennium_thread = threading.Thread(target=client_to_millennium, daemon=True)
    
    millennium_to_client_thread.start()
    client_to_millennium_thread.start()
    
    log.info("Relay threads started")
    
    # Main loop - monitor for exit conditions
    try:
        while running and not kill:
            time.sleep(1)
            # Check if threads are still alive
            if not millennium_to_client_thread.is_alive() or not client_to_millennium_thread.is_alive():
                log.warning("One of the relay threads has stopped")
                running = False
                break
            # Check connection status
            if not millennium_connected or not client_connected:
                log.warning("One of the connections has been lost")
                running = False
                break
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")
        running = False
    except Exception as e:
        log.error(f"Error in main loop: {e}")
        running = False
    
    # Cleanup
    log.info("Shutting down...")
    cleanup()
    time.sleep(0.5)
    log.info("Disconnected")
    time.sleep(0.5)
    log.info("Exiting relay2.py")


if __name__ == "__main__":
    main()

