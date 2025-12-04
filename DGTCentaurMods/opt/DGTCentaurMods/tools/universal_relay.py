#!/usr/bin/env python3
"""
Bluetooth Classic SPP Relay with BLE Support

This relay connects to a target device via Bluetooth Classic SPP (RFCOMM)
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
shadow_target_connected = False
client_connected = False
ble_connected = False
universal = None  # Universal instance
_last_message = None  # Last message sent via sendMessage
relay_mode = False  # Whether relay mode is enabled (connects to relay target)
shadow_target = "MILLENNIUM CHESS"  # Default target device name (can be overridden via --shadow-target)

# Socket references
shadow_target_sock = None
server_sock = None
client_sock = None

# BLE references
ble_app = None
ble_adv = None

# Thread references
shadow_target_to_client_thread = None
shadow_target_to_client_thread_started = False

GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"

# ============================================================================
# BLE UUID Definitions
# ============================================================================

# Millennium ChessLink BLE UUIDs
# Note: The service UUID is the full 128-bit UUID, but the characteristics use
# short 16-bit UUIDs (fff1, fff2) in the standard Bluetooth base UUID format
MILLENNIUM_UUIDS = {
    "service": "49535343-FE7D-4AE5-8FA9-9FAFD205E455",
    "rx_characteristic": "0000FFF1-0000-1000-8000-00805F9B34FB",  # Write TO device
    "tx_characteristic": "0000FFF2-0000-1000-8000-00805F9B34FB"   # Notify FROM device
}

# Nordic UART Service BLE UUIDs (used by Pegasus)
NORDIC_UUIDS = {
    "service": "6E400001-B5A3-F393-E0A9-E50E24DCCA9E",
    "rx_characteristic": "6E400002-B5A3-F393-E0A9-E50E24DCCA9E",
    "tx_characteristic": "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
}

# Chessnut Air BLE UUIDs
CHESSNUT_UUIDS = {
    "service": "1B7E8261-2877-41C3-B46E-CF057C562023",
    "fen_characteristic": "1B7E8262-2877-41C3-B46E-CF057C562023",   # Notify FEN data
    "op_tx_characteristic": "1B7E8272-2877-41C3-B46E-CF057C562023", # Write commands
    "op_rx_characteristic": "1B7E8273-2877-41C3-B46E-CF057C562023"  # Notify responses
}

# ============================================================================
# BLE Service Implementation (matching millennium.py)
# ============================================================================

class UARTAdvertisement(Advertisement):
    """BLE advertisement supporting Millennium ChessLink, Nordic UART, and Chessnut services"""
    def __init__(self, index, local_name="MILLENNIUM CHESS", advertise_millennium=True, advertise_nordic=True, advertise_chessnut=False):
        """Initialize BLE advertisement.
        
        Args:
            index: Advertisement index
            local_name: Local name for BLE advertisement (default: "MILLENNIUM CHESS")
                       Example: "MILLENNIUM CHESS"
            advertise_millennium: If True, advertise Millennium ChessLink service UUID (default: True)
            advertise_nordic: If True, advertise Nordic UART service UUID (default: True)
            advertise_chessnut: If True, advertise Chessnut Air service UUID (default: False)
        """
        # Store flags for use in register() method to determine primary/secondary
        self._advertise_millennium = advertise_millennium
        self._advertise_nordic = advertise_nordic
        self._advertise_chessnut = advertise_chessnut
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
        
        # Advertise Chessnut Air service UUID
        if advertise_chessnut:
            self.add_service_uuid(CHESSNUT_UUIDS["service"])
            log.info(f"BLE Advertisement: Chessnut Air service UUID: {CHESSNUT_UUIDS['service']}")
        
        log.info(f"BLE Advertisement initialized with name: {local_name}")
    
    def register_ad_callback(self):
        """Callback when advertisement is successfully registered"""
        self._registration_successful = True
        log.info("=" * 60)
        log.info("✓ BLE advertisement registered successfully")
        log.info(f"✓ Device should now be discoverable as '{self.local_name}'")
        log.info(f"✓ Service UUID: {MILLENNIUM_UUIDS['service'] if self._advertise_millennium else NORDIC_UUIDS['service']}")
        if self._advertise_millennium and not self._advertise_nordic:
            log.info("=" * 60)
            log.info("Millennium ChessLink advertisement ACTIVE")
            log.info("Apps should now be able to discover this device")
            log.info("")
            log.info("Troubleshooting if apps cannot find the device:")
            log.info("  1. Ensure Bluetooth is enabled on iPhone/Android")
            log.info("  2. Ensure location services are enabled (required for BLE on iOS)")
            log.info("  3. Do NOT pair via iPhone Settings - let apps handle connection")
            log.info("  4. Try closing and reopening the app")
            log.info("  5. Check that the device name matches: " + self.local_name)
            log.info("  6. Verify the service UUID matches: " + MILLENNIUM_UUIDS['service'])
            log.info("=" * 60)
    
    def register_ad_error_callback(self, error):
        """Callback when advertisement registration fails"""
        # Only log as error if registration wasn't already successful
        # (Sometimes BlueZ calls both callbacks, but if success was called first, we're good)
        if not self._registration_successful:
            log.error("=" * 60)
            log.error(f"✗ FAILED to register BLE advertisement: {error}")
            log.error(f"   Advertisement name: {self.local_name}")
            log.error(f"   Service UUID: {MILLENNIUM_UUIDS['service'] if self._advertise_millennium else NORDIC_UUIDS['service']}")
            log.error("")
            log.error("Troubleshooting steps:")
            log.error("  1. Check BlueZ is running: sudo systemctl status bluetooth")
            log.error("  2. Check BlueZ logs: sudo journalctl -u bluetooth -n 50")
            log.error("  3. Verify BLE is enabled: hciconfig hci0")
            log.error("  4. Check if another advertisement is already registered")
            log.error("  5. Try restarting BlueZ: sudo systemctl restart bluetooth")
            log.error("=" * 60)
        else:
            # Success was already called, this might be a spurious error callback
            log.debug(f"Advertisement registration error callback received after success (likely spurious): {error}")
    
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
            
            # Configure adapter to allow pairing
            # Note: Bondable is a D-Bus property, not a config file option
            try:
                # For BLE connections that allow pairing:
                # 1. Set Pairable=True (allows pairing)
                # 2. Optionally set PairableTimeout (0 = infinite, or seconds)
                pairable_set = False
                
                try:
                    adapter_props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
                    log.info("Adapter Pairable set to True (allows pairing)")
                    pairable_set = True
                except dbus.exceptions.DBusException as e:
                    log.warning(f"Could not set Pairable property: {e}")
                    log.warning("This may prevent pairing - clients may not be able to pair")
                
                # Try to set PairableTimeout to 0 (infinite) to keep adapter pairable
                try:
                    adapter_props.Set("org.bluez.Adapter1", "PairableTimeout", dbus.UInt32(0))
                    log.info("Adapter PairableTimeout set to 0 (infinite - stays pairable)")
                except dbus.exceptions.DBusException as e:
                    log.debug(f"Could not set PairableTimeout property: {e}")
                
                # Verify the settings were applied
                try:
                    current_pairable = adapter_props.Get("org.bluez.Adapter1", "Pairable")
                    log.info(f"Current adapter settings - Pairable: {current_pairable}")
                    
                    if current_pairable:
                        log.info("Adapter configured to allow pairing (clients can pair if needed)")
                    else:
                        log.warning("Adapter Pairable is False - pairing may not be possible")
                except dbus.exceptions.DBusException as e:
                    log.debug(f"Could not read adapter properties: {e}")
                    
            except Exception as e:
                log.warning(f"Error configuring adapter for pairing: {e}")
                import traceback
                log.warning(traceback.format_exc())
            
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
                # Using standard iOS intervals ensures better compatibility with apps
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
            log.info(f"Advertisement name: {self.local_name}")
            log.info(f"Service UUIDs: {[MILLENNIUM_UUIDS['service'] if self._advertise_millennium else None, NORDIC_UUIDS['service'] if self._advertise_nordic else None]}")
            
            # Register the advertisement
            # Note: This is asynchronous - callbacks will indicate success/failure
            ad_manager.RegisterAdvertisement(
                self.get_path(),
                options,
                reply_handler=self.register_ad_callback,
                error_handler=self.register_ad_error_callback)
            
            # Give the registration a moment to complete
            # The callback will be called asynchronously, but we wait a bit to see if it succeeds
            time.sleep(0.2)
        except Exception as e:
            log.error(f"Exception during BLE advertisement registration: {e}")
            import traceback
            log.error(traceback.format_exc())


def sendMessage(data):
    """Send a message via BLE or BT classic.
    
    Args:
        data: Message data bytes (already formatted with messageType, length, payload)
    """
    global _last_message, relay_mode, shadow_target

    # Data is already formatted, use it directly
    tosend = bytearray(data)

    _last_message = tosend
    log.warning(f"[sendMessage CALLBACK] tosend={' '.join(f'{b:02x}' for b in tosend)}")
    
    # In relay mode, messages are forwarded to the relay target, so don't send back to client
    # In non-relay mode (--relay not set), send messages back to client via BLE/BT Classic
    if relay_mode:
        log.debug(f"[sendMessage] Relay mode enabled - not sending to client (data forwarded to {shadow_target})")
        return
    
    # Send via BLE if connected (both services share the same tx_obj)
    log.info(f"[sendMessage] Checking BLE: tx_obj={UARTService.tx_obj is not None}, notifying={UARTService.tx_obj.notifying if UARTService.tx_obj else 'N/A'}")
    if UARTService.tx_obj is not None and UARTService.tx_obj.notifying:
        try:
            log.info(f"[sendMessage] Sending {len(tosend)} bytes via BLE")
            UARTService.tx_obj.updateValue(tosend)
            log.info(f"[sendMessage] BLE send complete")
        except Exception as e:
            log.error(f"[sendMessage] Error sending via BLE: {e}")
            import traceback
            log.error(traceback.format_exc())
    else:
        log.warning(f"[sendMessage] BLE not ready - tx_obj={UARTService.tx_obj is not None}, notifying={UARTService.tx_obj.notifying if UARTService.tx_obj else 'N/A'}")
    
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
        log.info("=" * 60)
        log.info("UARTRXCharacteristic.WriteValue CALLED - BLE client is writing data")
        log.info(f"WriteValue: value type={type(value)}, length={len(value) if hasattr(value, '__len__') else 'unknown'}")
        log.info(f"WriteValue: options={options}")
        
        global kill, ble_connected
        global shadow_target_connected
        log.info(f"WriteValue: kill={kill}, ble_connected={ble_connected}, shadow_target_connected={shadow_target_connected}")
        
        if kill:
            log.warning("WriteValue: kill flag is True, returning early without processing")
            return
        
        try:
            # Convert dbus.Array of dbus.Byte to bytearray (must convert dbus.Byte to int)
            log.debug("WriteValue: Converting dbus.Array to bytearray...")
            bytes_data = bytearray(int(b) for b in value)
            log.info(f"WriteValue: Converted to bytearray, length={len(bytes_data)}")
            
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
            log.info(f"WriteValue: universal={universal is not None}")
            handled = False
            if universal is not None:
                log.debug("WriteValue: Processing bytes through universal parser...")
                for byte_val in bytes_data:
                    # byte_val is already an int from the bytearray conversion above
                    handled = universal.receive_data(byte_val)
                log.info(f"WriteValue: Processed {len(bytes_data)} bytes through universal parser")
            else:
                log.warning("WriteValue: universal is None - data not processed through parser")
            
            log.warning(f"handled by universal: {handled}")
            
            # Write to relay target (if connected and relay mode is enabled)
            # Note: Don't raise exceptions for send failures - Android BLE interprets this as write failure
            global relay_mode, shadow_target
            log.info(f"WriteValue: Checking {shadow_target} connection - relay_mode={relay_mode}, shadow_target_connected={shadow_target_connected}, shadow_target_sock={shadow_target_sock is not None}")
            if relay_mode:
                if shadow_target_connected and shadow_target_sock is not None:
                    try:
                        data_to_send = bytes(bytes_data)
                        log.info(f"BLE -> SHADOW TARGET: Sending {len(data_to_send)} bytes: {' '.join(f'{b:02x}' for b in data_to_send)}")
                        bytes_sent = shadow_target_sock.send(data_to_send)
                        if bytes_sent != len(data_to_send):
                            log.warning(f"Partial send to SHADOW TARGET: {bytes_sent}/{len(data_to_send)} bytes sent")
                        else:
                            log.info(f"Successfully sent {bytes_sent} bytes to SHADOW TARGET via BT Classic")
                    except (bluetooth.BluetoothError, OSError) as e:
                        log.error(f"Error sending to {shadow_target}: {e}")
                        shadow_target_connected = False
                        # Don't raise - Android BLE will think write failed if we raise here
                        # The data was successfully received via BLE, which is what matters
                else:
                    log.warning(f"SHADOW TARGET '{shadow_target}' not connected (shadow_target_connected={shadow_target_connected}, shadow_target_sock={shadow_target_sock is not None}), data processed through universal parser only")

            ble_connected = True
            log.info("WriteValue: Processing complete successfully")
            log.info("=" * 60)
        except Exception as e:
            log.error("=" * 60)
            log.error(f"WriteValue: EXCEPTION occurred: {e}")
            log.error(f"WriteValue: Exception type: {type(e).__name__}")
            import traceback
            log.error("WriteValue: Traceback:")
            log.error(traceback.format_exc())
            log.error("=" * 60)
            # Only raise for critical errors that prevent data processing
            # Android BLE is sensitive to exceptions - they indicate write failure
            # If we can process the data through universal, don't raise
            if universal is None:
                log.error("WriteValue: universal is None, raising exception (critical error)")
                raise
            else:
                log.warning("WriteValue: universal exists, not raising exception (non-critical)")


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
        self._cached_value = bytearray([0])  # Cache for ReadValue polling clients
    
    def sendMessage(self, data):
        """Send a message via BLE notification.
        
        Note: Some clients (like HIARCS Desktop) connect via ReadValue without
        calling StartNotify. We still try to send data in this case, though
        the client may not receive it if it's not listening for notifications.
        """
        global ble_connected
        if not self.notifying and not ble_connected:
            log.debug("sendMessage: Not notifying and not BLE connected, skipping")
            return
        if not self.notifying:
            log.debug("sendMessage: Client connected via ReadValue (not StartNotify), attempting to send anyway")
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
            log.info("=" * 60)
            log.info("TX Characteristic StartNotify called - BLE client subscribing to notifications")
            log.info(f"TX Characteristic UUID: {self.uuid}")
            log.info(f"TX Characteristic path: {self.path}")
            log.info(f"Service path: {self.service.path if hasattr(self.service, 'path') else 'N/A'}")
            
            # Only set tx_obj and create Universal if this is the first StartNotify
            # or if we're replacing a stale connection
            global universal, ble_connected, relay_mode
            
            # Determine client type from service UUID BEFORE setting tx_obj
            client_type = None
            
            # Get service UUID - check both the service object and try to infer from characteristic UUID
            service_uuid = None
            if hasattr(self.service, 'service_uuid'):
                service_uuid = self.service.service_uuid.upper()
                log.info(f"[Universal] Service UUID from service object: {service_uuid}")
            elif hasattr(self.service, 'uuid'):
                service_uuid = self.service.uuid.upper()
                log.info(f"[Universal] Service UUID from service.uuid: {service_uuid}")
            
            # Also try to determine from the characteristic UUID itself
            char_uuid = self.uuid.upper() if self.uuid else None
            log.info(f"[Universal] Characteristic UUID: {char_uuid}")
            
            # Log all expected UUIDs for comparison
            log.info(f"[Universal] Expected Millennium service UUID: {MILLENNIUM_UUIDS['service'].upper()}")
            log.info(f"[Universal] Expected Nordic service UUID: {NORDIC_UUIDS['service'].upper()}")
            log.info(f"[Universal] Expected Chessnut service UUID: {CHESSNUT_UUIDS['service'].upper()}")
            
            if service_uuid:
                if service_uuid == MILLENNIUM_UUIDS["service"].upper():
                    client_type = Universal.CLIENT_MILLENNIUM
                    log.info("[Universal] MATCH: Client connected via Millennium ChessLink service")
                elif service_uuid == NORDIC_UUIDS["service"].upper():
                    client_type = Universal.CLIENT_PEGASUS
                    log.info("[Universal] MATCH: Client connected via Nordic UART service (Pegasus)")
                elif service_uuid == CHESSNUT_UUIDS["service"].upper():
                    client_type = Universal.CLIENT_CHESSNUT
                    log.info("[Universal] MATCH: Client connected via Chessnut service")
                else:
                    log.info(f"[Universal] NO MATCH: Unknown service UUID: {service_uuid}")
            elif char_uuid:
                # Fallback: try to determine from characteristic UUID
                log.info(f"[Universal] Falling back to characteristic UUID detection")
                log.info(f"[Universal] Expected Millennium TX char UUID: {MILLENNIUM_UUIDS['tx_characteristic'].upper()}")
                log.info(f"[Universal] Expected Nordic TX char UUID: {NORDIC_UUIDS['tx_characteristic'].upper()}")
                
                if char_uuid == MILLENNIUM_UUIDS["tx_characteristic"].upper():
                    client_type = Universal.CLIENT_MILLENNIUM
                    log.info("[Universal] MATCH: Client connected via Millennium TX characteristic")
                elif char_uuid == NORDIC_UUIDS["tx_characteristic"].upper():
                    client_type = Universal.CLIENT_PEGASUS
                    log.info("[Universal] MATCH: Client connected via Nordic TX characteristic (Pegasus)")
                elif char_uuid == CHESSNUT_UUIDS["op_rx_characteristic"].upper():
                    client_type = Universal.CLIENT_CHESSNUT
                    log.info("[Universal] MATCH: Client connected via Chessnut TX characteristic")
                else:
                    log.info(f"[Universal] NO MATCH: Unknown characteristic UUID: {char_uuid}")
            else:
                log.info("[Universal] Could not determine service or characteristic UUID")
            
            # Now set tx_obj and create Universal
            UARTService.tx_obj = self
            self.notifying = True

            # Log connection summary
            log.info("=" * 60)
            log.info("BLE CLIENT CONNECTION ESTABLISHED")
            log.info("=" * 60)
            log.info(f"Connection type: Bluetooth Low Energy (BLE)")
            log.info(f"Service UUID: {service_uuid}")
            log.info(f"Characteristic UUID: {char_uuid}")
            
            # Map client type to friendly name
            client_type_name = {
                Universal.CLIENT_MILLENNIUM: "Millennium ChessLink",
                Universal.CLIENT_PEGASUS: "DGT Pegasus (Nordic UART)",
                Universal.CLIENT_CHESSNUT: "Chessnut Air",
                None: "Unknown (will auto-detect)"
            }.get(client_type, f"Unknown ({client_type})")
            
            log.info(f"Detected protocol: {client_type_name}")
            log.info(f"Protocol detection: {'Explicit from service UUID' if client_type else 'Will auto-detect from data'}")
            log.info("=" * 60)

            # Instantiate Universal with client type hint and compare_mode if relay enabled
            try:
                universal = Universal(
                    sendMessage_callback=sendMessage,
                    client_type=client_type,
                    compare_mode=relay_mode
                )
                log.info(f"[Universal] Instantiated for BLE with client_type={client_type}, compare_mode={relay_mode}")
            except Exception as e:
                log.error(f"[Universal] Error instantiating: {e}")
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
        log.info("=" * 60)
        log.info("BLE CLIENT DISCONNECTED")
        log.info("=" * 60)
        log.info(f"Characteristic UUID: {self.uuid}")
        self.notifying = False
        global ble_connected, universal
        ble_connected = False
        universal = None  # Reset universal instance for clean reconnection
        log.info("[Universal] Instance reset - ready for new connection")
        log.info("=" * 60)
        return self.notifying
    
    def updateValue(self, value):
        """Update the characteristic value and notify subscribers.
        
        Always caches the value for ReadValue polling clients.
        Sends PropertiesChanged if client has subscribed to notifications OR
        if a BLE client is connected (some clients listen without StartNotify).
        """
        log.info(f"[updateValue] Called with {len(value)} bytes, notifying={self.notifying}, ble_connected={ble_connected}")
        
        # Always cache the value for ReadValue polling
        self._cached_value = bytearray(value)
        
        # Build dbus array for PropertiesChanged
        send = dbus.Array(signature=dbus.Signature('y'))
        for i in range(0, len(value)):
            send.append(dbus.Byte(value[i]))
        
        # Send PropertiesChanged if notifying OR if BLE client is connected
        # Some clients (like HIARCS Desktop) connect via ReadValue and listen for
        # property changes without explicitly calling StartNotify
        global ble_connected
        if self.notifying or ble_connected:
            log.info(f"[updateValue] Sending PropertiesChanged with {len(send)} bytes: {' '.join(f'{b:02x}' for b in value)}")
            self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': send}, [])
        else:
            log.debug("[updateValue] No BLE client connected, value cached for later ReadValue")
    
    def ReadValue(self, options):
        """Read the current characteristic value.
        
        Some BLE clients (like HIARCS Desktop) call ReadValue instead of or before
        StartNotify. We treat this as a connection event and initialize Universal.
        """
        try:
            log.info("=" * 60)
            log.info("TX Characteristic ReadValue called by BLE client")
            log.info(f"Characteristic UUID: {self.uuid}")
            log.info(f"Options: {options}")
            
            global universal, ble_connected, relay_mode
            
            # If Universal is not initialized, treat ReadValue as a connection event
            # This handles clients that read before subscribing to notifications
            if universal is None:
                log.info("ReadValue triggered before StartNotify - initializing connection")
                
                # Determine client type from service UUID
                client_type = None
                service_uuid = None
                if hasattr(self.service, 'service_uuid'):
                    service_uuid = self.service.service_uuid.upper()
                elif hasattr(self.service, 'uuid'):
                    service_uuid = self.service.uuid.upper()
                
                char_uuid = self.uuid.upper() if self.uuid else None
                
                if service_uuid:
                    if service_uuid == MILLENNIUM_UUIDS["service"].upper():
                        client_type = Universal.CLIENT_MILLENNIUM
                    elif service_uuid == NORDIC_UUIDS["service"].upper():
                        client_type = Universal.CLIENT_PEGASUS
                    elif service_uuid == CHESSNUT_UUIDS["service"].upper():
                        client_type = Universal.CLIENT_CHESSNUT
                elif char_uuid:
                    if char_uuid == MILLENNIUM_UUIDS["tx_characteristic"].upper():
                        client_type = Universal.CLIENT_MILLENNIUM
                    elif char_uuid == NORDIC_UUIDS["tx_characteristic"].upper():
                        client_type = Universal.CLIENT_PEGASUS
                    elif char_uuid == CHESSNUT_UUIDS["op_rx_characteristic"].upper():
                        client_type = Universal.CLIENT_CHESSNUT
                
                # Map client type to friendly name
                client_type_name = {
                    Universal.CLIENT_MILLENNIUM: "Millennium ChessLink",
                    Universal.CLIENT_PEGASUS: "DGT Pegasus (Nordic UART)",
                    Universal.CLIENT_CHESSNUT: "Chessnut Air",
                    None: "Unknown (will auto-detect)"
                }.get(client_type, f"Unknown ({client_type})")
                
                log.info("=" * 60)
                log.info("BLE CLIENT CONNECTION (via ReadValue)")
                log.info("=" * 60)
                log.info(f"Connection type: Bluetooth Low Energy (BLE)")
                log.info(f"Service UUID: {service_uuid}")
                log.info(f"Characteristic UUID: {char_uuid}")
                log.info(f"Detected protocol: {client_type_name}")
                log.info("=" * 60)
                
                # Set tx_obj so sendMessage works
                UARTService.tx_obj = self
                
                try:
                    universal = Universal(
                        sendMessage_callback=sendMessage,
                        client_type=client_type,
                        compare_mode=relay_mode
                    )
                    log.info(f"[Universal] Instantiated for BLE (ReadValue) with client_type={client_type}")
                except Exception as e:
                    log.error(f"[Universal] Error instantiating: {e}")
                    import traceback
                    traceback.print_exc()
                
                ble_connected = True
            
            # Return cached value for polling clients
            # Some clients (like HIARCS Desktop) poll via ReadValue instead of using notifications
            log.info(f"[ReadValue] Returning cached value: {len(self._cached_value)} bytes")
            if len(self._cached_value) > 0 and self._cached_value != bytearray([0]):
                log.info(f"[ReadValue] Cached data: {' '.join(f'{b:02x}' for b in self._cached_value[:50])}{'...' if len(self._cached_value) > 50 else ''}")
            log.info("=" * 60)
            return dbus.Array(self._cached_value, signature=dbus.Signature('y'))
        except Exception as e:
            log.error(f"Error in ReadValue: {e}")
            import traceback
            log.error(traceback.format_exc())
            raise


# ============================================================================
# Bluetooth Classic SPP Functions
# ============================================================================

def find_shadow_target_device(shadow_target="MILLENNIUM CHESS"):
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


def find_shadow_target_service(device_addr):
    """Find the RFCOMM service on the SHADOW TARGET device"""
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
    
    log.warning(f"No RFCOMM service found on {device_addr} device")
    return None


def connect_to_shadow_target(shadow_target="MILLENNIUM CHESS"):
    """Connect to the target device.
    
    Args:
        shadow_target: Name of the target device to connect to (default: "MILLENNIUM CHESS")
                      Example: "MILLENNIUM CHESS"
    """
    global shadow_target_sock, shadow_target_connected
    global shadow_target_to_client_thread, shadow_target_to_client_thread_started
    
    try:
        # Find device
        device_addr = find_shadow_target_device(shadow_target=shadow_target)
        if not device_addr:
            log.error(f"Could not find SHADOW TARGET '{shadow_target}'")
            return False
        
        # Find service
        port = find_shadow_target_service(device_addr)
        if port is None:
            # Try common RFCOMM ports
            log.info("Trying common RFCOMM ports...")
            for common_port in [1, 2, 3, 4, 5]:
                try:
                    log.info(f"Attempting connection to SHADOW TARGET '{shadow_target}' at {device_addr} on port {common_port}...")
                    sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
                    sock.connect((device_addr, common_port))
                    shadow_target_sock = sock
                    shadow_target_connected = True
                    log.info(f"Connected to {device_addr} on port {common_port}")
                    # Start the relay thread when connection is established
                    if not shadow_target_to_client_thread_started:
                        shadow_target_to_client_thread = threading.Thread(target=shadow_target_to_client, daemon=True)
                        shadow_target_to_client_thread.start()
                        shadow_target_to_client_thread_started = True
                        log.info("Started shadow_target_to_client thread")
                    return True
                except Exception as e:
                    log.debug(f"Failed to connect {device_addr} on port {common_port}: {e}")
                    try:
                        sock.close()
                    except:
                        pass
            log.error(f"Could not connect to SHADOW TARGET '{shadow_target}' at {device_addr} on any common port")
            return False
        
        # Connect to the service
        log.info(f"Connecting to SHADOW TARGET '{shadow_target}' at {device_addr}:{port}...")
        shadow_target_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        shadow_target_sock.connect((device_addr, port))
        shadow_target_connected = True
        log.info(f"Connected to SHADOW TARGET '{shadow_target}' at {device_addr} successfully")
        # Start the relay thread when connection is established
        if not shadow_target_to_client_thread_started:
            shadow_target_to_client_thread = threading.Thread(target=shadow_target_to_client, daemon=True)
            shadow_target_to_client_thread.start()
            shadow_target_to_client_thread_started = True
            log.info("Started shadow_target_to_client thread")
        return True
        
    except Exception as e:
        log.error(f"Error connecting to SHADOW TARGET '{shadow_target}' at {device_addr}: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def shadow_target_to_client():
    """Relay data from SHADOW TARGET to client.
    
    In relay mode with compare_mode enabled, this function also compares
    the shadow host response with the emulator's response and logs any differences.
    """
    global running, shadow_target_sock, client_sock, shadow_target_connected, client_connected, _last_message, shadow_target, universal
    
    log.info(f"Starting SHADOW TARGET '{shadow_target}' -> Client relay thread")
    try:
        while running and not kill:
            try:
                if not shadow_target_connected or shadow_target_sock is None:
                    time.sleep(0.1)
                    continue
                
                # Read from SHADOW TARGET
                data = shadow_target_sock.recv(1024)
                if len(data) > 0:
                    data_bytes = bytearray(data)
                    log.info(f"SHADOW TARGET -> Client: {' '.join(f'{b:02x}' for b in data_bytes)}")
                    log.debug(f"SHADOW TARGET -> Client (ASCII): {data_bytes.decode('utf-8', errors='replace')}")
                    
                    # Compare with emulator response if Universal is in compare_mode
                    if universal is not None and universal.compare_mode:
                        match, emulator_response = universal.compare_with_shadow(bytes(data_bytes))
                        if match is False:
                            log.error("[Relay] MISMATCH: Emulator response differs from shadow host")
                        elif match is True:
                            log.info("[Relay] MATCH: Emulator response matches shadow host")
                        # Note: match=None means no emulator response was pending
                    
                    # Legacy comparison with _last_message (for debugging)
                    if _last_message is not None:
                        if _last_message == data_bytes:
                            log.debug(f"[shadow_to_client] _last_message matches data_bytes")
                        else:
                            log.warning(f"[shadow_to_client] _last_message differs from data_bytes")
                        log.debug(f"[shadow_to_client] _last_message={' '.join(f'{b:02x}' for b in _last_message)}")
                        _last_message = None

                    # Write to RFCOMM client
                    if client_connected and client_sock is not None:
                        client_sock.send(data)
                    
                    # Write to BLE client via TX characteristic
                    if UARTService.tx_obj is not None:
                        UARTService.tx_obj.sendMessage(data_bytes)

            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error in SHADOW TARGET -> Client relay: {e}")
                shadow_target_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error in SHADOW TARGET -> Client relay: {e}")
                    import traceback
                    log.error(traceback.format_exc())
                break
    except Exception as e:
        log.error(f"SHADOW TARGET -> Client thread error: {e}")
        import traceback
        log.error(traceback.format_exc())
    finally:
        log.info("SHADOW TARGET -> Client relay thread stopped")
        shadow_target_connected = False


def client_to_shadow_target():
    """Relay data from client to SHADOW TARGET"""
    global running, shadow_target_sock, client_sock, shadow_target_connected, client_connected, universal
    
    log.info("Starting Client -> SHADOW TARGET relay thread")
    try:
        while running and not kill:
            try:
                if not client_connected or client_sock is None:
                    time.sleep(0.1)
                    continue
                
                if not shadow_target_connected or shadow_target_sock is None:
                    time.sleep(0.1)
                    continue
                
                # Read from client
                data = client_sock.recv(1024)
                if len(data) == 0:
                    # Empty data indicates client disconnected
                    log.info("=" * 60)
                    log.info("RFCOMM CLIENT DISCONNECTED")
                    log.info("=" * 60)
                    log.info("Received empty data - client has disconnected")
                    client_connected = False
                    universal = None  # Reset for next connection
                    log.info("[Universal] Instance reset - ready for new connection")
                    log.info("=" * 60)
                    break
                
                data_bytes = bytearray(data)
                log.info(f"Client -> SHADOW TARGET: {' '.join(f'{b:02x}' for b in data_bytes)}")
                log.debug(f"Client -> SHADOW TARGET (ASCII): {data_bytes.decode('utf-8', errors='replace')}")
                
                # Process each byte through universal parser
                if universal is not None:
                    for byte_val in data_bytes:
                        universal.receive_data(byte_val)
                
                if shadow_target_sock is not None: 
                    try:
                        sent = shadow_target_sock.send(data)
                        log.info(f"Sent {sent} bytes to SHADOW TARGET")
                    except Exception as e:
                        log.error(f"Error sending to SHADOW TARGET: {e}")
                        shadow_target_connected = False
                        break
                    
            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error in Client -> SHADOW TARGET relay: {e}")
                client_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error in Client -> SHADOW TARGET relay: {e}")
                break
    except Exception as e:
        log.error(f"Client -> SHADOW TARGET thread error: {e}")
    finally:
        log.info("Client -> SHADOW TARGET relay thread stopped")
        client_connected = False


def client_reader():
    """Read data from RFCOMM client in server-only mode (no relay to shadow target).
    
    This function reads data from the connected RFCOMM client and processes it
    through the universal parser. Unlike client_to_shadow_target(), this does
    not forward data to a shadow target - it only processes incoming commands
    and sends responses back to the client.
    """
    global running, client_sock, client_connected, universal
    
    log.info("Starting Client reader thread (server-only mode)")
    try:
        while running and not kill:
            try:
                if not client_connected or client_sock is None:
                    time.sleep(0.1)
                    continue
                
                # Read from client
                data = client_sock.recv(1024)
                if len(data) == 0:
                    # Empty data indicates client disconnected
                    log.info("=" * 60)
                    log.info("RFCOMM CLIENT DISCONNECTED")
                    log.info("=" * 60)
                    log.info("Received empty data - client has disconnected")
                    client_connected = False
                    universal = None  # Reset for next connection
                    log.info("[Universal] Instance reset - ready for new connection")
                    log.info("=" * 60)
                    break
                
                data_bytes = bytearray(data)
                log.info(f"Client -> Server: {' '.join(f'{b:02x}' for b in data_bytes)}")
                log.debug(f"Client -> Server (ASCII): {data_bytes.decode('utf-8', errors='replace')}")
                
                # Process each byte through universal parser
                if universal is not None:
                    for byte_val in data_bytes:
                        universal.receive_data(byte_val)
                else:
                    log.warning("Client data received but universal is None - data not processed")
                    
            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error in client reader: {e}")
                client_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error in client reader: {e}")
                break
    except Exception as e:
        log.error(f"Client reader thread error: {e}")
    finally:
        log.info("Client reader thread stopped")
        client_connected = False


def cleanup():
    """Clean up connections and resources"""
    global kill, running, shadow_target_sock, client_sock, server_sock
    global shadow_target_connected, client_connected, ble_app, ble_adv_millennium, ble_adv_nordic, ble_adv_chessnut
    global universal
    
    try:
        log.info("Cleaning up relay...")
        kill = 1
        running = False
        universal = None  # Reset universal instance
        log.info("[Universal] Instance reset on cleanup")
        
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
                
                # Unregister Chessnut advertisement
                if 'ble_adv_chessnut' in globals() and ble_adv_chessnut is not None:
                    try:
                        ad_manager.UnregisterAdvertisement(ble_adv_chessnut.get_path())
                        log.info("Chessnut BLE advertisement unregistered")
                    except Exception as e:
                        log.debug(f"Error unregistering Chessnut BLE advertisement: {e}")
            
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
                log.info("SHADOW TARGET socket closed")
            except Exception as e:
                log.debug(f"Error closing SHADOW TARGET socket: {e}")
        
        # Close server socket
        if server_sock:
            try:
                server_sock.close()
                log.info("Server socket closed")
            except Exception as e:
                log.debug(f"Error closing server socket: {e}")
        
        shadow_target_connected = False
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
    global shadow_target_connected, client_connected, running, kill
    global ble_app, ble_adv_millennium, ble_adv_nordic, ble_adv_chessnut, shadow_target_to_client_thread, shadow_target_to_client_thread_started
    
    parser = argparse.ArgumentParser(description="Bluetooth Classic SPP Relay with BLE - Connect to target device and relay data")
    parser.add_argument("--local-name", type=str, default="MILLENNIUM CHESS",
                       help="Local name for BLE advertisement (default: 'MILLENNIUM CHESS'). Example: 'MILLENNIUM CHESS'")
    parser.add_argument("--shadow-target", type=str, default="MILLENNIUM CHESS",
                       help="Name of the target device to connect to (default: 'MILLENNIUM CHESS'). Example: 'MILLENNIUM CHESS'")
    parser.add_argument("--disable-nordic", action="store_true",
                       help="Disable Nordic UART BLE advertisement (only advertise Millennium ChessLink).")
    parser.add_argument("--enable-chessnut", action="store_true",
                       help="Enable Chessnut Air BLE service and advertisement.")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="RFCOMM port for server (default: auto-assign)"
    )
    parser.add_argument("--device-name", type=str, default="SPP Relay",
                       help="Bluetooth device name for RFCOMM service (default: 'SPP Relay'). Example: 'MILLENNIUM CHESS'")
    parser.add_argument("--relay", action="store_true",
                       help="Enable relay mode - connect to shadow_target and relay data. Without this flag, only BLE/RFCOMM server mode is enabled (no relay connection).")
    
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
    
    # Add Chessnut Air service (only if enabled)
    if args.enable_chessnut:
        log.info(f"Adding Chessnut Air service: {CHESSNUT_UUIDS['service']}")
        # Chessnut uses separate characteristics for FEN and operations
        # For simplicity, we use the op_tx (write) and op_rx (notify) for the UART-style interface
        ble_app.add_service(UARTService(
            2,
            CHESSNUT_UUIDS["service"],
            CHESSNUT_UUIDS["op_tx_characteristic"],  # Write commands
            CHESSNUT_UUIDS["op_rx_characteristic"]   # Notify responses
        ))
    else:
        log.info("Chessnut Air service disabled (use --enable-chessnut to enable)")
    
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
    
    # Define the correct BLE device names for each protocol
    # These names are what chess apps expect to see when scanning
    MILLENNIUM_BLE_NAME = "MILLENNIUM CHESS"
    PEGASUS_BLE_NAME = "DGT_PEGASUS"
    # Use consistent name from --device-name for ALL BLE advertisements
    # This prevents name oscillation - all advertisements show the same name
    ble_name = args.device_name
    
    if ble_app is not None:
        # Register Millennium ChessLink advertisement
        # Each advertisement has only ONE service UUID to fit in BLE payload (31 bytes max)
        # But all use the SAME name for consistency
        try:
            log.info(f"Registering Millennium ChessLink BLE advertisement as '{ble_name}'...")
            ble_adv_millennium = UARTAdvertisement(
                0, 
                local_name=ble_name, 
                advertise_millennium=True, 
                advertise_nordic=False,
                advertise_chessnut=False
            )
            ble_adv_millennium.register()
            log.info(f"Millennium ChessLink BLE advertisement registered as '{ble_name}'")
            time.sleep(0.5)
        except Exception as e:
            log.error(f"Failed to register Millennium BLE advertisement: {e}")
            import traceback
            log.error(traceback.format_exc())
            ble_adv_millennium = None
        
        # Register Nordic UART advertisement (same name, different service UUID)
        ble_adv_nordic = None
        if not args.disable_nordic:
            try:
                log.info(f"Registering Nordic UART BLE advertisement as '{ble_name}'...")
                ble_adv_nordic = UARTAdvertisement(
                    1, 
                    local_name=ble_name, 
                    advertise_millennium=False, 
                    advertise_nordic=True,
                    advertise_chessnut=False
                )
                ble_adv_nordic.register()
                log.info(f"Nordic UART BLE advertisement registered as '{ble_name}'")
            except Exception as e:
                log.error(f"Failed to register Nordic BLE advertisement: {e}")
                import traceback
                log.error(traceback.format_exc())
                ble_adv_nordic = None
        else:
            log.info("Nordic UART BLE advertisement disabled (--disable-nordic flag set)")
        
        # Register Chessnut Air advertisement (same name, different service UUID)
        global ble_adv_chessnut
        ble_adv_chessnut = None
        if args.enable_chessnut:
            try:
                log.info(f"Registering Chessnut Air BLE advertisement as '{ble_name}'...")
                ble_adv_chessnut = UARTAdvertisement(
                    2, 
                    local_name=ble_name, 
                    advertise_millennium=False, 
                    advertise_nordic=False,
                    advertise_chessnut=True
                )
                ble_adv_chessnut.register()
                log.info(f"Chessnut Air BLE advertisement registered as '{ble_name}'")
            except Exception as e:
                log.error(f"Failed to register Chessnut BLE advertisement: {e}")
                import traceback
                log.error(traceback.format_exc())
                ble_adv_chessnut = None
        else:
            log.info("Chessnut Air BLE advertisement disabled (use --enable-chessnut to enable)")
        
        if ble_adv_millennium is not None or ble_adv_nordic is not None or ble_adv_chessnut is not None:
            log.info("=" * 60)
            log.info("BLE ADVERTISEMENTS REGISTERED")
            log.info("=" * 60)
            log.info(f"  Device Name: '{ble_name}' (consistent across all services)")
            log.info(f"  Services:")
            if ble_adv_millennium is not None:
                log.info(f"    - Millennium ChessLink: {MILLENNIUM_UUIDS['service']}")
            if ble_adv_nordic is not None:
                log.info(f"    - Nordic UART (Pegasus): {NORDIC_UUIDS['service']}")
            if ble_adv_chessnut is not None:
                log.info(f"    - Chessnut Air: {CHESSNUT_UUIDS['service']}")
            log.info("")
            # Wait for advertisement registration callbacks to complete
            log.info("Waiting for BLE advertisement registration to complete...")
            
            # Poll for registration status with timeout (callbacks are async)
            max_wait_time = 5.0  # Maximum time to wait for registration
            poll_interval = 0.1  # Check every 100ms
            elapsed = 0.0
            
            millennium_registered = False
            nordic_registered = False
            chessnut_registered = False
            
            while elapsed < max_wait_time:
                if ble_adv_millennium is not None and hasattr(ble_adv_millennium, '_registration_successful'):
                    millennium_registered = ble_adv_millennium._registration_successful
                if ble_adv_nordic is not None and hasattr(ble_adv_nordic, '_registration_successful'):
                    nordic_registered = ble_adv_nordic._registration_successful
                if ble_adv_chessnut is not None and hasattr(ble_adv_chessnut, '_registration_successful'):
                    chessnut_registered = ble_adv_chessnut._registration_successful
                
                # Check if all enabled advertisements are registered
                all_registered = True
                if ble_adv_millennium is not None and not millennium_registered:
                    all_registered = False
                if ble_adv_nordic is not None and not nordic_registered:
                    all_registered = False
                if ble_adv_chessnut is not None and not chessnut_registered:
                    all_registered = False
                
                if all_registered:
                    break
                
                time.sleep(poll_interval)
                elapsed += poll_interval
            
            # Log registration status
            if millennium_registered:
                log.info("✓ Millennium ChessLink advertisement is ACTIVE")
            elif ble_adv_millennium is not None:
                log.warning("⚠ Millennium ChessLink advertisement registration status unknown")
            
            if nordic_registered:
                log.info("✓ Nordic UART advertisement is ACTIVE")
            elif ble_adv_nordic is not None:
                log.warning("⚠ Nordic UART advertisement registration status unknown")
            
            if chessnut_registered:
                log.info("✓ Chessnut Air advertisement is ACTIVE")
            elif ble_adv_chessnut is not None:
                log.warning("⚠ Chessnut Air advertisement registration status unknown")
            
            if millennium_registered or nordic_registered or chessnut_registered:
                log.info("")
                log.info("To verify the advertisement is being broadcast, run:")
                log.info("  sudo hcitool lescan")
                log.info("")
                log.info(f"You should see: {ble_name}")
            else:
                log.warning("")
                log.warning("⚠ BLE advertisement registration status unknown")
                log.warning("Advertisement may still be active (callbacks are async)")
                log.warning("Check BlueZ logs: sudo journalctl -u bluetooth -f")
            
            log.info("")
            log.info("Waiting for BLE connection from apps...")
            log.info("=" * 60)
        else:
            log.error("=" * 60)
            log.error("✗ No BLE advertisements were successfully registered")
            log.error("Apps will NOT be able to discover this device")
            log.error("Check the error messages above for details")
            log.error("=" * 60)
    
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
    bluetooth_controller = BluetoothController(device_name=args.device_name)
    bluetooth_controller.enable_bluetooth()
    bluetooth_controller.set_device_name(args.device_name)
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
    
    # Advertise RFCOMM service - this registers the service in SDP so clients can discover it
    try:
        bluetooth.advertise_service(server_sock, args.device_name, service_id=uuid,
                                  service_classes=[uuid, bluetooth.SERIAL_PORT_CLASS],
                                  profiles=[bluetooth.SERIAL_PORT_PROFILE])
        log.info(f"RFCOMM service '{args.device_name}' advertised successfully on channel {port}")
        log.info(f"Service UUID: {uuid}")
        log.info(f"Service is now discoverable by paired devices")
    except Exception as e:
        log.error(f"Failed to advertise RFCOMM service: {e}")
        log.error("Service may not be discoverable - clients may not be able to connect")
        import traceback
        log.error(traceback.format_exc())
        # Continue anyway - the socket is still listening, but service discovery may not work
    
    log.info(f"Server listening on RFCOMM channel: {port}")
    log.info(f"Waiting for client connection on device '{args.device_name}'...")
    
    # Set relay mode flag
    global relay_mode
    relay_mode = args.relay

    global shadow_target
    shadow_target = args.shadow_target

    if relay_mode:
        log.info("=" * 60)
        log.info(f"RELAY MODE ENABLED - Will connect to {shadow_target}")
        log.info("=" * 60)
        # Connect to target device in a separate thread
        def connect_shadow_target():
            time.sleep(1)  # Give server time to start
            if connect_to_shadow_target(shadow_target=shadow_target):
                log.info(f"{shadow_target} connection established")
            else:
                log.error(f"Failed to connect to {shadow_target}")
                global kill
                kill = 1
        
        shadow_target_thread = threading.Thread(target=connect_shadow_target, daemon=True)
        shadow_target_thread.start()
    else:
        log.info("=" * 60)
        log.info("RELAY MODE DISABLED - Running in server-only mode (no connection to target device)")
        log.info("Messages will be sent back to clients via BLE/BT Classic")
        log.info("=" * 60)
        
    # Wait for client connection (either RFCOMM or BLE)
    log.info("Waiting for client connection...")
    log.info(f"Server socket is ready and listening on RFCOMM channel {port}")
    log.info(f"Device '{args.device_name}' is paired and service is advertised")
    log.info("Apps should now be able to connect to this device (via RFCOMM or BLE)")
    connected = False
    connection_attempts = 0
    while not connected and not ble_connected and not kill:
        try:
            client_sock, client_info = server_sock.accept()
            connected = True
            client_connected = True
            log.info("=" * 60)
            log.info("RFCOMM CLIENT CONNECTION ESTABLISHED")
            log.info("=" * 60)
            log.info(f"Client address: {client_info}")
            log.info(f"RFCOMM channel: {port}")
            log.info(f"Connection type: Bluetooth Classic (RFCOMM/SPP)")
            log.info(f"Protocol detection: Auto-detect (client_type=None)")
            log.info("=" * 60)
            
            # Instantiate Universal on BT classic connection
            # client_type=None triggers auto-detection from incoming data
            # compare_mode=relay_mode enables response comparison in relay mode
            global universal
            try:
                universal = Universal(
                    sendMessage_callback=sendMessage,
                    client_type=None,  # Auto-detect protocol from incoming data
                    compare_mode=relay_mode
                )
                log.info(f"[Universal] Instantiated for RFCOMM with auto-detection, compare_mode={relay_mode}")
            except Exception as e:
                log.error(f"[Universal] Error instantiating: {e}")
                import traceback
                traceback.print_exc()
        except bluetooth.BluetoothError as e:
            # Timeout or other Bluetooth error - this is normal while waiting
            connection_attempts += 1
            if connection_attempts % 50 == 0:  # Log every 5 seconds (50 * 0.1s)
                log.debug(f"Still waiting for connection... (checked {connection_attempts} times, BLE connected: {ble_connected})")
            time.sleep(0.1)
        except Exception as e:
            connection_attempts += 1
            if running:
                log.error(f"Error accepting client connection: {e}")
                log.error(f"This may indicate a problem with the RFCOMM service or socket")
            time.sleep(0.1)
    
    # Check which connection type was established
    if ble_connected:
        log.info("✓ BLE client connected - skipping RFCOMM-specific setup")
    elif connected:
        log.info("✓ RFCOMM client connected")
    
    if kill:
        log.info("Exiting...")
        cleanup()
        sys.exit(0)
    
    # Wait for MILLENNIUM connection if relay mode is enabled
    if relay_mode:
        max_wait = 30
        wait_time = 0
        while not shadow_target_connected and wait_time < max_wait and not kill:
            time.sleep(0.5)
            wait_time += 0.5
            if wait_time % 5 == 0:
                log.info(f"Waiting for {shadow_target} connection... ({wait_time}/{max_wait} seconds)")
        
        if not shadow_target_connected:
            log.error(f"{shadow_target} connection timeout")
            cleanup()
            sys.exit(1)
    else:
        log.info("Relay mode disabled - skipping target device connection")
    
    if kill:
        cleanup()
        sys.exit(0)
    
    # Determine connection type and start appropriate relay threads
    if relay_mode:
        if ble_connected:
            log.info("BLE client connected - BLE relay handled via UARTRXCharacteristic.WriteValue")
            log.info("Starting SHADOW TARGET -> Client relay thread for BLE notifications")
        elif connected:
            log.info("RFCOMM client connected - starting bidirectional relay threads")
        
        # Start relay threads (only in relay mode)
        # Note: shadow_target_to_client_thread is started automatically when shadow_target_connected becomes True
        global shadow_target_to_client_thread, shadow_target_to_client_thread_started
        if not shadow_target_to_client_thread_started:
            shadow_target_to_client_thread = threading.Thread(target=shadow_target_to_client, daemon=True)
            shadow_target_to_client_thread.start()
            shadow_target_to_client_thread_started = True
            log.info("Started shadow_target_to_client thread")
        
        # Only start client_to_shadow_target thread for RFCOMM connections
        # BLE connections are handled via UARTRXCharacteristic.WriteValue
        client_to_shadow_target_thread = None
        if connected and client_sock is not None:
            client_to_shadow_target_thread = threading.Thread(target=client_to_shadow_target, daemon=True)
            client_to_shadow_target_thread.start()
            log.info("Started client_to_shadow_target thread (RFCOMM)")
        else:
            log.info("Skipping client_to_shadow_target thread (BLE connection or no RFCOMM client)")
        
        log.info("Relay threads started")
        client_reader_thread = None  # Not used in relay mode
    else:
        log.info("Relay mode disabled - starting client reader thread (server-only mode)")
        # In server-only mode, we still need to read from the client to process commands
        # and send responses back. We just don't forward to a shadow target.
        client_reader_thread = None
        if connected and client_sock is not None:
            client_reader_thread = threading.Thread(target=client_reader, daemon=True)
            client_reader_thread.start()
            log.info("Started client_reader thread (RFCOMM, server-only mode)")
        client_to_shadow_target_thread = None
    
    # Main loop - monitor for exit conditions and handle client reconnections
    try:
        while running and not kill:
            time.sleep(1)
            
            # Check if shadow_target_to_client thread is still alive (only in relay mode)
            if relay_mode and shadow_target_to_client_thread is not None and not shadow_target_to_client_thread.is_alive():
                log.warning("shadow_target_to_client thread has stopped")
                # Restart the thread if shadow_target is still connected
                if shadow_target_connected and shadow_target_sock is not None:
                    shadow_target_to_client_thread = threading.Thread(target=shadow_target_to_client, daemon=True)
                    shadow_target_to_client_thread.start()
                    log.info("Restarted shadow_target_to_client thread")
                else:
                    log.error("SHADOW TARGET connection lost and cannot restart thread")
                    running = False
                    break
            
            # Check if client_to_shadow_target thread is still alive (only for RFCOMM connections in relay mode)
            if client_to_shadow_target_thread is not None and not client_to_shadow_target_thread.is_alive():
                log.warning("client_to_shadow_target thread has stopped")
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
                            # Restart the client_to_shadow_target thread
                            client_to_shadow_target_thread = threading.Thread(target=client_to_shadow_target, daemon=True)
                            client_to_shadow_target_thread.start()
                            log.info("Restarted client_to_shadow_target thread")
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
                    log.error("client_to_shadow_target thread died but client still connected")
                    running = False
                    break
            
            # Check if client_reader thread is still alive (server-only mode)
            if not relay_mode and client_reader_thread is not None and not client_reader_thread.is_alive():
                log.warning("client_reader thread has stopped")
                # If client disconnected, wait for a new client
                if not client_connected:
                    log.info("Client disconnected, waiting for new client connection (server-only mode)...")
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
                            # Create new Universal instance for the new client
                            universal = Universal(
                                sendMessage_callback=sendMessage,
                                client_type=None,  # Auto-detect protocol from incoming data
                                compare_mode=False
                            )
                            log.info(f"[Universal] Instantiated for new RFCOMM client with auto-detection")
                            # Restart the client_reader thread
                            client_reader_thread = threading.Thread(target=client_reader, daemon=True)
                            client_reader_thread.start()
                            log.info("Restarted client_reader thread")
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
                    log.error("client_reader thread died but client still connected")
                    running = False
                    break
            
            # Check shadow_target connection status (but don't exit, just log)
            if not shadow_target_connected and relay_mode:
                log.error(f"{shadow_target} connection lost")
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
    log.info("Exiting universal_relay.py")


if __name__ == "__main__":
    main()

