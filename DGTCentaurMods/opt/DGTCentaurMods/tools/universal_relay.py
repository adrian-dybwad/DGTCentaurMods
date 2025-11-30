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
from DGTCentaurMods.games.universal import Universal
from DGTCentaurMods.thirdparty.advertisement import Advertisement
from DGTCentaurMods.thirdparty.service import Application, Service, Characteristic
from DGTCentaurMods.thirdparty.bletools import BleTools

# Global state
running = True
kill = 0
shadow_traget_connected = False
client_connected = False
ble_connected = False
universal = None  # Universal instance
_last_message = None  # Last message sent via sendMessage

# Socket references
shadow_target_sock = None
server_sock = None
client_sock = None

# BLE references
ble_app = None
ble_adv = None

# Thread references
shadow_traget_to_client_thread = None
shadow_target_to_client_thread_started = False

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

# ============================================================================
# BLE UUID Definitions
# ============================================================================

# Millennium ChessLink BLE UUIDs
MILLENNIUM_UUIDS = {
    "service": "49535343-FE7D-4AE5-8FA9-9FAFD205E455",
    "rx_characteristic": "49535343-8841-43F4-A8D4-ECBE34729BB3",
    "tx_characteristic": "49535343-1E4D-4BD9-BA61-23C647249616"
}

# Nordic UART Service BLE UUIDs (used by Pegasus)
NORDIC_UUIDS = {
    "service": "6E400001-B5A3-F393-E0A9-E50E24DCCA9E",
    "rx_characteristic": "6E400002-B5A3-F393-E0A9-E50E24DCCA9E",
    "tx_characteristic": "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
}

# ============================================================================
# BLE Service Implementation (matching millennium.py)
# ============================================================================

class UARTAdvertisement(Advertisement):
    """BLE advertisement supporting both Millennium ChessLink and Nordic UART services"""
    def __init__(self, index, local_name="MILLENNIUM CHESS", advertise_millennium=True, advertise_nordic=True):
        """Initialize BLE advertisement.
        
        Args:
            index: Advertisement index
            local_name: Local name for BLE advertisement (default: "MILLENNIUM CHESS")
                       Example: "MILLENNIUM CHESS"
            advertise_millennium: If True, advertise Millennium ChessLink service UUID (default: True)
            advertise_nordic: If True, advertise Nordic UART service UUID (default: True)
        """
        # Store flags for use in register() method to determine primary/secondary
        self._advertise_millennium = advertise_millennium
        self._advertise_nordic = advertise_nordic
        Advertisement.__init__(self, index, "peripheral")
        self.local_name = local_name
        self.add_local_name(local_name)
        self.include_tx_power = True
        self._registration_successful = False  # Track registration status
        
        # Advertise Millennium ChessLink service UUID
        if advertise_millennium:
            self.add_service_uuid(MILLENNIUM_UUIDS["service"])
            log.info(f"BLE Advertisement: Millennium ChessLink service UUID: {MILLENNIUM_UUIDS['service']}")
        
        # Advertise Nordic UART service UUID
        if advertise_nordic:
            self.add_service_uuid(NORDIC_UUIDS["service"])
            log.info(f"BLE Advertisement: Nordic UART service UUID: {NORDIC_UUIDS['service']}")
        
        log.info(f"BLE Advertisement initialized with name: {local_name}")
    
    def register_ad_callback(self):
        """Callback when advertisement is successfully registered"""
        self._registration_successful = True
        log.info("BLE advertisement registered successfully")
        log.info(f"Device should now be discoverable as '{self.local_name}'")
        if self._advertise_millennium and not self._advertise_nordic:
            log.info("Millennium ChessLink advertisement active - iPhone ChessLink app should be able to discover this device")
            log.info("If ChessLink cannot find the device, try:")
            log.info("  1. Ensure Bluetooth is enabled on iPhone")
            log.info("  2. Ensure location services are enabled (required for BLE on iOS)")
            log.info("  3. Do NOT pair via iPhone Settings - let ChessLink app handle connection")
            log.info("  4. Try closing and reopening the ChessLink app")
    
    def register_ad_error_callback(self, error):
        """Callback when advertisement registration fails"""
        # Only log as error if registration wasn't already successful
        # (Sometimes BlueZ calls both callbacks, but if success was called first, we're good)
        if not self._registration_successful:
            log.error(f"Failed to register BLE advertisement: {error}")
            log.error("Check that BlueZ is running and BLE is enabled")
        else:
            # Success was already called, this might be a spurious error callback
            log.debug(f"Advertisement registration error callback received after success: {error}")
    
    def register(self):
        """Register advertisement with iOS/macOS compatible options"""
        try:
            bus = BleTools.get_bus()
            adapter = BleTools.find_adapter(bus)
            log.info(f"Found Bluetooth adapter: {adapter}")
            
            # Get adapter properties interface
            adapter_props = dbus.Interface(
                bus.get_object("org.bluez", adapter),
                "org.freedesktop.DBus.Properties")
            
            # Get adapter MAC address and store it
            mac_address = None
            try:
                mac_address = adapter_props.Get("org.bluez.Adapter1", "Address")
                log.info(f"Bluetooth adapter MAC address: {mac_address}")
                # Store MAC address in advertisement object
                self.mac_address = mac_address
                
                # Note: BLE advertisement has 31-byte limit
                # Adding MAC to manufacturer/service data may exceed this limit
                # The MAC address should be visible in the BLE scan results automatically
                # when AddressType is 'public'
                log.info(f"MAC address will be included in BLE advertisement automatically (AddressType: public)")
            except Exception as e:
                log.warning(f"Could not get MAC address: {e}")
            
            # Configure adapter to use public MAC address instead of random
            # This is required for iOS devices to connect (iOS requires public MAC address)
            # BlueZ privacy mode must be disabled in /etc/bluetooth/main.conf
            try:
                # Check if /etc/bluetooth/main.conf has privacy disabled
                import pathlib
                main_conf = pathlib.Path("/etc/bluetooth/main.conf")
                privacy_disabled = False
                if main_conf.exists():
                    with open(main_conf, 'r') as f:
                        content = f.read()
                        if "Privacy = off" in content or "Privacy=off" in content:
                            privacy_disabled = True
                            log.info("Privacy mode is disabled in /etc/bluetooth/main.conf")
                        else:
                            log.warning("Privacy mode may be enabled in /etc/bluetooth/main.conf")
                            log.warning("Add 'Privacy = off' under [General] section to use public MAC address")
                            log.warning("This is required for iOS devices to connect")
                else:
                    log.warning("/etc/bluetooth/main.conf not found - privacy mode status unknown")
                
                # Try to disable privacy mode via D-Bus (may not work on all systems)
                try:
                    adapter_props.Set("org.bluez.Adapter1", "Privacy", dbus.Boolean(False))
                    log.info("Disabled adapter Privacy mode via D-Bus (using public MAC address)")
                    privacy_disabled = True
                except dbus.exceptions.DBusException as e:
                    log.info(f"Privacy property not available via D-Bus: {e}")
                    if not privacy_disabled:
                        log.warning("Cannot disable privacy mode - iOS devices may not be able to connect")
                        log.warning("To fix: Add 'Privacy = off' to /etc/bluetooth/main.conf under [General] section")
                        log.warning("Then restart bluetooth service: sudo systemctl restart bluetooth")
            except Exception as e:
                log.warning(f"Could not configure adapter for public MAC address: {e}")
                log.warning("iOS devices may not be able to connect without public MAC address")
            
            ad_manager = dbus.Interface(
                bus.get_object("org.bluez", adapter),
                "org.bluez.LEAdvertisingManager1")
            
            # Try to unregister any existing advertisement with the same path first
            # This prevents conflicts if the advertisement was already registered
            try:
                ad_manager.UnregisterAdvertisement(self.get_path())
                log.info(f"Unregistered existing advertisement at {self.get_path()}")
                # Give BlueZ a moment to process the unregistration
                time.sleep(0.1)
            except dbus.exceptions.DBusException as e:
                # It's okay if the advertisement doesn't exist yet
                if "org.bluez.Error.DoesNotExist" not in str(e):
                    log.debug(f"Could not unregister existing advertisement (may not exist): {e}")
            except Exception as e:
                log.debug(f"Error checking for existing advertisement: {e}")
            
            # iOS/macOS compatibility options
            # Try to ensure we're using public address type
            # Note: The address type is typically controlled by the adapter's privacy settings
            # Use iOS-compatible intervals for primary (Millennium) advertisement
            # iOS requires minimum 20ms interval, and shorter intervals may cause issues
            is_primary = self._advertise_millennium and not self._advertise_nordic
            if is_primary:
                # Primary advertisement: iOS-compatible intervals (matching millennium.py)
                # Using standard iOS intervals ensures better compatibility with ChessLink app
                options = {
                    "MinInterval": dbus.UInt16(0x0014),  # 20ms (iOS minimum)
                    "MaxInterval": dbus.UInt16(0x0098),  # 152.5ms (iOS compatible)
                }
                log.info("Using primary advertisement intervals (20-152.5ms) - iOS compatible")
            else:
                # Secondary advertisement: less frequent
                options = {
                    "MinInterval": dbus.UInt16(0x0014),  # 20ms
                    "MaxInterval": dbus.UInt16(0x0098),  # 152.5ms
                }
                log.info("Using secondary advertisement intervals (20-152.5ms)")
            
            # Check the actual AddressType value and try to set LE address to public MAC
            try:
                adapter_info = adapter_props.GetAll("org.bluez.Adapter1")
                address_type = adapter_info.get("AddressType", "unknown")
                mac_address = adapter_info.get("Address", mac_address)
                log.info(f"Adapter AddressType: {address_type}")
                log.info(f"Adapter MAC address: {mac_address}")
                
                if address_type != "public":
                    log.warning(f"Adapter AddressType is '{address_type}', not 'public'")
                    log.warning("Attempting to set LE address to public MAC address...")
                    log.warning("This is required for iOS devices to connect")
                    
                    # Try to set the LE address to the public MAC using hciconfig
                    import subprocess
                    try:
                        # First, check current LE address
                        result_check = subprocess.run(
                            ['hciconfig', 'hci0'],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result_check.returncode == 0:
                            log.info(f"Current hci0 config: {result_check.stdout[:200]}")
                        
                        # Set LE address to public MAC address
                        # Note: This may require the adapter to be down first
                        # Format: hciconfig hci0 leaddr B8:27:EB:21:D2:51
                        if mac_address:
                            log.info(f"Setting LE address to: {mac_address}")
                            result = subprocess.run(
                                ['sudo', 'hciconfig', 'hci0', 'leaddr', mac_address],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            if result.returncode == 0:
                                log.info(f"Successfully set LE address to public MAC: {mac_address}")
                                # Small delay to let it take effect
                                time.sleep(0.5)
                                # Verify it was set
                                result2 = subprocess.run(
                                    ['hciconfig', 'hci0'],
                                    capture_output=True,
                                    text=True,
                                    timeout=5
                                )
                                if result2.returncode == 0:
                                    log.info(f"LE address verification output: {result2.stdout[:300]}")
                            else:
                                log.warning(f"Failed to set LE address (return code {result.returncode})")
                                log.warning(f"Error output: {result.stderr}")
                                log.warning("iOS devices may not be able to connect")
                                log.warning("You may need to manually run: sudo hciconfig hci0 leaddr " + mac_address)
                    except FileNotFoundError:
                        log.warning("hciconfig not found - cannot set LE address")
                        log.warning("Install bluez-hcidump or ensure hciconfig is available")
                        log.warning("iOS devices may not be able to connect without public LE address")
                    except subprocess.TimeoutExpired:
                        log.warning("hciconfig command timed out")
                    except Exception as e:
                        log.warning(f"Error setting LE address: {e}")
                        import traceback
                        log.warning(traceback.format_exc())
                else:
                    log.info("Adapter AddressType is 'public' - MAC address should be visible")
                    log.info("iOS devices should be able to connect")
            except Exception as e:
                log.debug(f"Could not check/set adapter AddressType: {e}")
            
            # Verify LE address is set correctly before advertising
            # This ensures the MAC address is used in BLE advertisements
            try:
                import subprocess
                result = subprocess.run(
                    ['hciconfig', 'hci0'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    output = result.stdout
                    if 'LE Address' in output or 'BD Address' in output:
                        log.info(f"LE/BD Address from hciconfig: {output[output.find('Address'):output.find('Address')+50]}")
                    # Check if we need to set the LE address
                    if mac_address and mac_address.replace(':', '') not in output.replace(' ', '').replace(':', ''):
                        log.warning("MAC address not found in hciconfig output - LE address may not be set correctly")
                        log.warning("iOS devices may not be able to connect")
            except Exception as e:
                log.debug(f"Could not verify LE address via hciconfig: {e}")
            
            log.info(f"Registering BLE advertisement at path: {self.get_path()}")
            log.info("Registering BLE advertisement with iOS/macOS compatible intervals")
            log.info(f"Expected MAC address in advertisement: {mac_address if mac_address else 'unknown'}")
            ad_manager.RegisterAdvertisement(
                self.get_path(),
                options,
                reply_handler=self.register_ad_callback,
                error_handler=self.register_ad_error_callback)
        except Exception as e:
            log.error(f"Exception during BLE advertisement registration: {e}")
            import traceback
            log.error(traceback.format_exc())


def sendMessage(data):
    """Send a message via BLE or BT classic.
    
    Args:
        data: Message data bytes (already formatted with messageType, length, payload)
    """
    global _last_message

    # Data is already formatted, use it directly
    tosend = bytearray(data)

    _last_message = tosend
    log.warning(f"[sendMessage CALLBACK] tosend={' '.join(f'{b:02x}' for b in tosend)}")
    
    return
    
    # Send via BLE if connected (both services share the same tx_obj)
    if UARTService.tx_obj is not None and UARTService.tx_obj.notifying:
        try:
            UARTService.tx_obj.updateValue(tosend)
        except Exception as e:
            log.error(f"[sendMessage] Error sending via BLE: {e}")
    
    # Send via BT classic if connected
    global client_connected, client_sock
    if client_connected and client_sock is not None:
        try:
            client_sock.send(bytes(tosend))
        except Exception as e:
            log.error(f"[sendMessage] Error sending via BT classic: {e}")


class UARTService(Service):
    """BLE UART service supporting both Millennium ChessLink and Nordic UART protocols"""
    tx_obj = None
    
    def __init__(self, index, service_uuid, rx_characteristic_uuid, tx_characteristic_uuid):
        """Initialize BLE UART service.
        
        Args:
            index: Service index
            service_uuid: Service UUID (from MILLENNIUM_UUIDS or NORDIC_UUIDS)
            rx_characteristic_uuid: RX characteristic UUID
            tx_characteristic_uuid: TX characteristic UUID
        """
        Service.__init__(self, index, service_uuid, True)
        self.service_uuid = service_uuid
        self.add_characteristic(UARTTXCharacteristic(self, tx_characteristic_uuid))
        self.add_characteristic(UARTRXCharacteristic(self, rx_characteristic_uuid))


class UARTRXCharacteristic(Characteristic):
    """BLE RX characteristic - receives protocol commands from app and logs them"""
    
    def __init__(self, service, rx_characteristic_uuid):
        """Initialize BLE RX characteristic.
        
        Args:
            service: UARTService instance
            rx_characteristic_uuid: RX characteristic UUID (from MILLENNIUM_UUIDS or NORDIC_UUIDS)
        """
        Characteristic.__init__(
            self, rx_characteristic_uuid,
            ["write", "write-without-response"], service)
    
    def WriteValue(self, value, options):
        """When the remote device writes data via BLE, log the incoming bytes"""
        global kill, ble_connected
        global shadow_traget_connected
        if kill:
            return
        
        try:
            # Convert dbus.Array of dbus.Byte to bytearray (must convert dbus.Byte to int)
            bytes_data = bytearray(int(b) for b in value)
            
            # Log incoming bytes
            log.info(f"BLE RX (incoming bytes): {' '.join(f'{b:02x}' for b in bytes_data)}")
            log.info(f"BLE RX (integers): {' '.join(f'{b}' for b in bytes_data)}")
            # Try to decode as ASCII for readability (non-printable chars will be shown as hex)
            try:
                ascii_str = bytes_data.decode('utf-8', errors='replace')
                if all(c.isprintable() or c in '\n\r\t' for c in ascii_str):
                    log.info(f"BLE RX (ASCII 2): {repr(ascii_str)}")
            except:
                pass
            log.info(f"BLE RX (length): {len(bytes_data)} bytes")

            # Process each byte through universal parser
            global universal
            handled = False
            if universal is not None:
                for byte_val in bytes_data:
                    # byte_val is already an int from the bytearray conversion above
                    handled = universal.receive_data(byte_val)
            
            log.warning(f"handled by universal: {handled}")
            
            # Write to MILLENNIUM CHESS (if connected)
            # Note: Don't raise exceptions for send failures - Android BLE interprets this as write failure
            if shadow_traget_connected and shadow_target_sock is not None:
                try:
                    data_to_send = bytes(bytes_data)
                    log.info(f"BLE -> MILLENNIUM: Sending {len(data_to_send)} bytes: {' '.join(f'{b:02x}' for b in data_to_send)}")
                    bytes_sent = shadow_target_sock.send(data_to_send)
                    if bytes_sent != len(data_to_send):
                        log.warning(f"Partial send to MILLENNIUM: {bytes_sent}/{len(data_to_send)} bytes sent")
                    else:
                        log.info(f"Successfully sent {bytes_sent} bytes to MILLENNIUM CHESS via BT Classic")
                except (bluetooth.BluetoothError, OSError) as e:
                    log.error(f"Error sending to MILLENNIUM CHESS: {e}")
                    shadow_traget_connected = False
                    # Don't raise - Android BLE will think write failed if we raise here
                    # The data was successfully received via BLE, which is what matters
            else:
                log.warning(f"MILLENNIUM CHESS not connected (shadow_traget_connected={shadow_traget_connected}, shadow_target_sock={shadow_target_sock is not None}), data processed through universal parser only")

            ble_connected = True
        except Exception as e:
            log.error(f"Error in WriteValue: {e}")
            import traceback
            log.error(traceback.format_exc())
            # Only raise for critical errors that prevent data processing
            # Android BLE is sensitive to exceptions - they indicate write failure
            # If we can process the data through universal, don't raise
            if universal is None:
                raise


class UARTTXCharacteristic(Characteristic):
    """BLE TX characteristic - sends protocol responses via notifications"""
    
    def __init__(self, service, tx_characteristic_uuid):
        """Initialize BLE TX characteristic.
        
        Args:
            service: UARTService instance
            tx_characteristic_uuid: TX characteristic UUID (from MILLENNIUM_UUIDS or NORDIC_UUIDS)
        """
        Characteristic.__init__(
            self, tx_characteristic_uuid,
            ["read", "notify"], service)
        self.notifying = False
    
    def sendMessage(self, data):
        """Send a message via BLE notification"""
        if not self.notifying:
            return
        log.debug(f"BLE TX -> Client: {' '.join(f'{b:02x}' for b in data)}")


        try:
            ascii_str = data.decode('utf-8', errors='replace')
            if all(c.isprintable() or c in '\n\r\t' for c in ascii_str):
                log.info(f"BLE TX (ASCII): {repr(ascii_str)}")
        except:
            pass


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

            # Instantiate Universal and reset parser on BLE connection
            global universal, ble_connected
            try:
                universal = Universal(sendMessage_callback=sendMessage)
                log.info("[Universal] Instantiated and parser reset on BLE connection")
            except Exception as e:
                log.error(f"[Universal] Error instantiating or resetting parser: {e}")
                import traceback
                traceback.print_exc()

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

def find_millennium_device(shadow_target="MILLENNIUM CHESS"):
    """Find the device by name.
    
    Args:
        shadow_target: Name of the device to find (default: "MILLENNIUM CHESS")
                      Example: "MILLENNIUM CHESS"
    """
    log.info(f"Looking for {shadow_target} device...")
    
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
                        if name and shadow_target.upper() in name.upper():
                            log.info(f"Found {shadow_target} in paired devices: {addr}")
                            return addr
    except Exception as e:
        log.debug(f"Could not check paired devices: {e}")
    
    # If not found in paired devices, do a discovery scan
    log.info(f"Scanning for {shadow_target} device...")
    devices = bluetooth.discover_devices(duration=8, lookup_names=True, flush_cache=True)
    
    for addr, name in devices:
        log.info(f"Found device: {name} ({addr})")
        if name and shadow_target.upper() in name.upper():
            log.info(f"Found {shadow_target} at address: {addr}")
            return addr
    
    log.warning(f"{shadow_target} device not found in scan")
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


def connect_to_millennium(shadow_target="MILLENNIUM CHESS"):
    """Connect to the target device.
    
    Args:
        shadow_target: Name of the target device to connect to (default: "MILLENNIUM CHESS")
                      Example: "MILLENNIUM CHESS"
    """
    global shadow_target_sock, shadow_traget_connected
    global shadow_traget_to_client_thread, shadow_target_to_client_thread_started
    
    try:
        # Find device
        device_addr = find_millennium_device(shadow_target=shadow_target)
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
                    shadow_target_sock = sock
                    shadow_traget_connected = True
                    log.info(f"Connected to MILLENNIUM CHESS on port {common_port}")
                    # Start the relay thread when connection is established
                    if not shadow_target_to_client_thread_started:
                        shadow_traget_to_client_thread = threading.Thread(target=millennium_to_client, daemon=True)
                        shadow_traget_to_client_thread.start()
                        shadow_target_to_client_thread_started = True
                        log.info("Started millennium_to_client thread")
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
        shadow_target_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        shadow_target_sock.connect((device_addr, port))
        shadow_traget_connected = True
        log.info("Connected to MILLENNIUM CHESS successfully")
        # Start the relay thread when connection is established
        if not shadow_target_to_client_thread_started:
            shadow_traget_to_client_thread = threading.Thread(target=millennium_to_client, daemon=True)
            shadow_traget_to_client_thread.start()
            shadow_target_to_client_thread_started = True
            log.info("Started millennium_to_client thread")
        return True
        
    except Exception as e:
        log.error(f"Error connecting to MILLENNIUM CHESS: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def millennium_to_client():
    """Relay data from MILLENNIUM CHESS to client"""
    global running, shadow_target_sock, client_sock, shadow_traget_connected, client_connected, _last_message
    
    log.info("Starting MILLENNIUM -> Client relay thread")
    try:
        while running and not kill:
            try:
                if not shadow_traget_connected or shadow_target_sock is None:
                    time.sleep(0.1)
                    continue
                
                # if not client_connected or client_sock is None:
                #     time.sleep(0.1)
                #     continue
                
                # Read from MILLENNIUM CHESS
                data = shadow_target_sock.recv(1024)
                if len(data) > 0:
                    data_bytes = bytearray(data)
                    log.warning(f"MILLENNIUM -> Client: {' '.join(f'{b:02x}' for b in data_bytes)} <------------------------------------")
                    log.debug(f"MILLENNIUM -> Client (ASCII): {data_bytes.decode('utf-8', errors='replace')}")
                    
                    if _last_message is not None:
                        if _last_message == data_bytes:
                            log.warning(f"[millennium_to_client] _last_message is the same as data_bytes <------------------------------------")
                        else:
                            log.error(f"[millennium_to_client] _last_message is different from data_bytes <------------------------------------")
                        log.warning(f"[millennium_to_client] _last_message={' '.join(f'{b:02x}' for b in _last_message)} <------------------------------------")
                        _last_message = None
                    else:
                        log.error(f"[millennium_to_client] _last_message is None <------------------------------------")

                    # Write to RFCOMM client
                    if client_connected and client_sock is not None:
                        client_sock.send(data)
                    
                    # Write to BLE client via TX characteristic
                    if UARTService.tx_obj is not None:
                        UARTService.tx_obj.sendMessage(data_bytes)

            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error in MILLENNIUM -> Client relay: {e}")
                shadow_traget_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error in MILLENNIUM -> Client relay: {e}")
                    import traceback
                    log.error(traceback.format_exc())
                break
    except Exception as e:
        log.error(f"MILLENNIUM -> Client thread error: {e}")
        import traceback
        log.error(traceback.format_exc())
    finally:
        log.info("MILLENNIUM -> Client relay thread stopped")
        shadow_traget_connected = False


def client_to_millennium():
    """Relay data from client to MILLENNIUM CHESS"""
    global running, shadow_target_sock, client_sock, shadow_traget_connected, client_connected
    
    log.info("Starting Client -> MILLENNIUM relay thread")
    try:
        while running and not kill:
            try:
                if not client_connected or client_sock is None:
                    time.sleep(0.1)
                    continue
                
                if not shadow_traget_connected or shadow_target_sock is None:
                    time.sleep(0.1)
                    continue
                
                # Read from client
                data = client_sock.recv(1024)
                if len(data) == 0:
                    # Empty data indicates client disconnected
                    log.info("Client disconnected (received empty data)")
                    client_connected = False
                    break
                
                data_bytes = bytearray(data)
                log.info(f"Client -> MILLENNIUM: {' '.join(f'{b:02x}' for b in data_bytes)}")
                log.debug(f"Client -> MILLENNIUM (ASCII): {data_bytes.decode('utf-8', errors='replace')}")
                
                # Process each byte through universal parser
                global universal
                if universal is not None:
                    for byte_val in data_bytes:
                        universal.receive_data(byte_val)
                
                if shadow_target_sock is not None: 
                    try:
                        sent = shadow_target_sock.send(data)
                        log.info(f"Sent {sent} bytes to MILLENNIUM CHESS")
                    except Exception as e:
                        log.error(f"Error sending to MILLENNIUM CHESS: {e}")
                        shadow_traget_connected = False
                        break
                    
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
    global kill, running, shadow_target_sock, client_sock, server_sock
    global shadow_traget_connected, client_connected, ble_app, ble_adv_millennium, ble_adv_nordic
    
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
            
            # Unregister BLE advertisements
            bus = BleTools.get_bus()
            adapter = BleTools.find_adapter(bus)
            if adapter:
                ad_manager = dbus.Interface(
                    bus.get_object("org.bluez", adapter),
                    "org.bluez.LEAdvertisingManager1")
                
                # Unregister Millennium advertisement
                if 'ble_adv_millennium' in globals() and ble_adv_millennium is not None:
                    try:
                        ad_manager.UnregisterAdvertisement(ble_adv_millennium.get_path())
                        log.info("Millennium BLE advertisement unregistered")
                    except Exception as e:
                        log.debug(f"Error unregistering Millennium BLE advertisement: {e}")
                
                # Unregister Nordic advertisement
                if 'ble_adv_nordic' in globals() and ble_adv_nordic is not None:
                    try:
                        ad_manager.UnregisterAdvertisement(ble_adv_nordic.get_path())
                        log.info("Nordic BLE advertisement unregistered")
                    except Exception as e:
                        log.debug(f"Error unregistering Nordic BLE advertisement: {e}")
            
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
        if shadow_target_sock:
            try:
                shadow_target_sock.close()
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
        
        shadow_traget_connected = False
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
    global server_sock, client_sock, shadow_target_sock
    global shadow_traget_connected, client_connected, running, kill
    global ble_app, ble_adv_millennium, ble_adv_nordic, shadow_traget_to_client_thread, shadow_target_to_client_thread_started
    
    parser = argparse.ArgumentParser(description="Bluetooth Classic SPP Relay with BLE - Connect to MILLENNIUM CHESS and relay data")
    parser.add_argument("--local-name", type=str, default="MILLENNIUM CHESS",
                       help="Local name for BLE advertisement (default: 'MILLENNIUM CHESS'). Example: 'MILLENNIUM CHESS'")
    parser.add_argument("--shadow-target", type=str, default="MILLENNIUM CHESS",
                       help="Name of the target device to connect to (default: 'MILLENNIUM CHESS'). Example: 'MILLENNIUM CHESS'")
    parser.add_argument("--disable-nordic", action="store_true",
                       help="Disable Nordic UART BLE advertisement (only advertise Millennium ChessLink). Useful for ChessLink app compatibility.")
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
    log.info("Initializing BLE services...")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    ble_app = Application()
    
    # Add Millennium ChessLink service
    log.info(f"Adding Millennium ChessLink service: {MILLENNIUM_UUIDS['service']}")
    ble_app.add_service(UARTService(
        0,
        MILLENNIUM_UUIDS["service"],
        MILLENNIUM_UUIDS["rx_characteristic"],
        MILLENNIUM_UUIDS["tx_characteristic"]
    ))
    
    # Add Nordic UART service (only if not disabled)
    if not args.disable_nordic:
        log.info(f"Adding Nordic UART service: {NORDIC_UUIDS['service']}")
        ble_app.add_service(UARTService(
            1,
            NORDIC_UUIDS["service"],
            NORDIC_UUIDS["rx_characteristic"],
            NORDIC_UUIDS["tx_characteristic"]
        ))
    else:
        log.info("Nordic UART service disabled (--disable-nordic flag set)")
    
    # Register the BLE application
    try:
        ble_app.register()
        if args.disable_nordic:
            log.info("BLE application registered successfully with Millennium ChessLink service only")
        else:
            log.info("BLE application registered successfully with both services")
    except Exception as e:
        log.error(f"Failed to register BLE application: {e}")
        import traceback
        log.error(traceback.format_exc())
        log.warning("Continuing without BLE support...")
        ble_app = None
    
    # Register BLE advertisements (separate advertisements for each service due to 31-byte limit)
    # BLE advertisements have a 31-byte limit, so we need separate advertisements for each service UUID
    ble_adv_millennium = None
    ble_adv_nordic = None
    
    if ble_app is not None:
        # Register Millennium ChessLink advertisement (PRIMARY)
        # This is registered first with more frequent intervals for better discoverability
        try:
            log.info("Registering PRIMARY Millennium ChessLink BLE advertisement...")
            ble_adv_millennium = UARTAdvertisement(0, local_name=args.local_name, advertise_millennium=True, advertise_nordic=False)
            ble_adv_millennium.register()
            log.info("Millennium ChessLink BLE advertisement registered successfully (PRIMARY)")
            # Give Millennium advertisement time to establish before registering secondary
            time.sleep(0.5)
        except Exception as e:
            log.error(f"Failed to register Millennium BLE advertisement: {e}")
            import traceback
            log.error(traceback.format_exc())
            log.warning("Continuing without Millennium BLE advertisement...")
            ble_adv_millennium = None
        
        # Register Nordic UART advertisement (SECONDARY)
        # This is registered after Millennium with less frequent intervals
        # Can be disabled with --disable-nordic flag
        if not args.disable_nordic:
            try:
                log.info("Registering SECONDARY Nordic UART BLE advertisement...")
                ble_adv_nordic = UARTAdvertisement(1, local_name=args.local_name, advertise_millennium=False, advertise_nordic=True)
                ble_adv_nordic.register()
                log.info("Nordic UART BLE advertisement registered successfully (SECONDARY)")
            except Exception as e:
                log.error(f"Failed to register Nordic BLE advertisement: {e}")
                import traceback
                log.error(traceback.format_exc())
                log.warning("Continuing without Nordic BLE advertisement...")
                ble_adv_nordic = None
        else:
            log.info("Nordic UART BLE advertisement disabled (--disable-nordic flag set)")
            log.info("Only Millennium ChessLink service will be advertised")
            ble_adv_nordic = None
        
        if ble_adv_millennium is not None or ble_adv_nordic is not None:
            log.info(f"BLE services registered and advertising as '{args.local_name}'")
            log.info("Waiting for BLE connection...")
        else:
            log.warning("No BLE advertisements were successfully registered")
    
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
    
    # Connect to target device in a separate thread
    def connect_millennium():
        time.sleep(1)  # Give server time to start
        if connect_to_millennium(shadow_target=args.shadow_target):
            log.info(f"{args.shadow_target} connection established")
        else:
            log.error(f"Failed to connect to {args.shadow_target}")
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
            
            # Instantiate Universal on BT classic connection
            global universal
            try:
                universal = Universal(sendMessage_callback=sendMessage)
                log.info("[Universal] Instantiated and parser reset on BT classic connection")
            except Exception as e:
                log.error(f"[Universal] Error instantiating or resetting parser: {e}")
                import traceback
                traceback.print_exc()
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
    while not shadow_traget_connected and wait_time < max_wait and not kill:
        time.sleep(0.5)
        wait_time += 0.5
        if wait_time % 5 == 0:
            log.info(f"Waiting for MILLENNIUM CHESS connection... ({wait_time}/{max_wait} seconds)")
    
    if not shadow_traget_connected:
        log.error("MILLENNIUM CHESS connection timeout")
        cleanup()
        sys.exit(1)
    
    if kill:
        cleanup()
        sys.exit(0)
    
    log.info("Both connections established - starting relay")
    
    # Start relay threads
    # Note: millennium_to_client_thread is started automatically when millennium_connected becomes True
    global shadow_traget_to_client_thread, shadow_target_to_client_thread_started
    if not shadow_target_to_client_thread_started:
        shadow_traget_to_client_thread = threading.Thread(target=millennium_to_client, daemon=True)
        shadow_traget_to_client_thread.start()
        shadow_target_to_client_thread_started = True
        log.info("Started millennium_to_client thread")
    
    client_to_millennium_thread = threading.Thread(target=client_to_millennium, daemon=True)
    client_to_millennium_thread.start()
    
    log.info("Relay threads started")
    
    # Main loop - monitor for exit conditions and handle client reconnections
    try:
        while running and not kill:
            time.sleep(1)
            
            # Check if millennium thread is still alive
            if shadow_traget_to_client_thread is not None and not shadow_traget_to_client_thread.is_alive():
                log.warning("millennium_to_client thread has stopped")
                # Restart the thread if millennium is still connected
                if shadow_traget_connected and shadow_target_sock is not None:
                    shadow_traget_to_client_thread = threading.Thread(target=millennium_to_client, daemon=True)
                    shadow_traget_to_client_thread.start()
                    log.info("Restarted millennium_to_client thread")
                else:
                    log.error("MILLENNIUM connection lost and cannot restart thread")
                    running = False
                    break
            
            # Check if client_to_millennium thread is still alive
            if not client_to_millennium_thread.is_alive():
                log.warning("client_to_millennium thread has stopped")
                # If client disconnected, wait for a new client
                if not client_connected:
                    log.info("Client disconnected, waiting for new client connection...")
                    # Close old socket if it exists
                    if client_sock is not None:
                        try:
                            client_sock.close()
                        except:
                            pass
                        client_sock = None
                    
                    # Wait for new client connection
                    while not client_connected and not kill and running:
                        try:
                            client_sock, client_info = server_sock.accept()
                            client_connected = True
                            log.info(f"New client connected from {client_info}")
                            # Restart the client_to_millennium thread
                            client_to_millennium_thread = threading.Thread(target=client_to_millennium, daemon=True)
                            client_to_millennium_thread.start()
                            log.info("Restarted client_to_millennium thread")
                            break
                        except bluetooth.BluetoothError:
                            # Timeout, check kill flag
                            time.sleep(0.1)
                        except Exception as e:
                            if running:
                                log.error(f"Error accepting client connection: {e}")
                            time.sleep(0.1)
                else:
                    # Thread died but client still connected - error condition
                    log.error("client_to_millennium thread died but client still connected")
                    running = False
                    break
            
            # Check millennium connection status (but don't exit, just log)
            if not shadow_traget_connected:
                log.warning("MILLENNIUM CHESS connection lost")
                # Don't exit, just wait - the connection might be re-established
            
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

