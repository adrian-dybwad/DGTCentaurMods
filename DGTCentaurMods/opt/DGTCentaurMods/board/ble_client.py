"""
Generic BLE Client

A reusable async BLE client class using the bleak library.
Provides device scanning, connection management, notification handling,
and characteristic read/write operations.

This module is device-agnostic and can be used with any BLE device.
Device-specific logic (UUIDs, commands, data parsing) should be implemented
in subclasses or by the calling code.

Requirements:
    pip install bleak
"""

import asyncio
import logging
from typing import Callable, Any

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError
    from bleak.backends.device import BLEDevice
    from bleak.backends.service import BleakGATTServiceCollection
except ImportError:
    raise ImportError(
        "bleak library not installed. Install with: pip install bleak"
    )

from DGTCentaurMods.board.logging import log

# Suppress verbose D-Bus logging from bleak/dbus libraries
logging.getLogger("org.freedesktop").setLevel(logging.INFO)
logging.getLogger("bleak").setLevel(logging.INFO)
logging.getLogger("bleak.backends").setLevel(logging.INFO)
logging.getLogger("bleak.backends.bluezdbus").setLevel(logging.INFO)


# Type alias for notification callback
NotificationCallback = Callable[[Any, bytearray], None]


class BLEClient:
    """Generic async BLE client for connecting to and communicating with BLE devices.
    
    This class provides:
    - Device scanning by name or address
    - Connection management with automatic reconnection
    - Notification subscription and handling
    - Characteristic read/write operations
    - MTU size reporting
    
    Example usage:
        async def my_notification_handler(sender, data):
            print(f"Received: {data.hex()}")
        
        client = BLEClient()
        if await client.scan_and_connect("My Device"):
            await client.start_notify("uuid-here", my_notification_handler)
            await client.write_characteristic("uuid-here", bytes([0x01, 0x02]))
            # ... do work ...
            await client.disconnect()
    """
    
    def __init__(self):
        """Initialize the BLE client."""
        self._client: BleakClient | None = None
        self._device_address: str | None = None
        self._device_name: str | None = None
        self._running = True
        self._notification_handlers: dict[str, NotificationCallback] = {}
    
    @property
    def is_connected(self) -> bool:
        """Check if the client is connected to a device."""
        return self._client is not None and self._client.is_connected
    
    @property
    def device_address(self) -> str | None:
        """Get the address of the connected device."""
        return self._device_address
    
    @property
    def device_name(self) -> str | None:
        """Get the name of the connected device."""
        return self._device_name
    
    @property
    def mtu_size(self) -> int | None:
        """Get the current MTU size, or None if not available."""
        if self._client:
            try:
                return self._client.mtu_size
            except AttributeError:
                return None
        return None
    
    @property
    def services(self) -> BleakGATTServiceCollection | None:
        """Get the discovered GATT services, or None if not connected."""
        if self._client:
            return self._client.services
        return None
    
    async def scan_for_device(
        self,
        device_name: str,
        timeout: float = 30.0,
        partial_match: bool = True
    ) -> str | None:
        """Scan for a BLE device by name.
        
        Uses a callback-based scanner that stops as soon as the device is found,
        rather than waiting for the full timeout.
        
        Args:
            device_name: Name of the device to find (case-insensitive)
            timeout: Maximum time to scan in seconds
            partial_match: If True, match devices containing the name
            
        Returns:
            Device address if found, None otherwise
        """
        log.info(f"Scanning for device with name: {device_name}")
        
        target_name_upper = device_name.upper()
        found_device: BLEDevice | None = None
        stop_event = asyncio.Event()
        
        def detection_callback(device: BLEDevice, advertisement_data):
            nonlocal found_device
            name = device.name or ""
            name_upper = name.upper()
            
            if name_upper == target_name_upper:
                log.info(f"Found device: {device.name} at {device.address}")
                found_device = device
                stop_event.set()
            elif partial_match and target_name_upper in name_upper:
                log.info(f"Found device (partial match): {device.name} at {device.address}")
                found_device = device
                stop_event.set()
        
        scanner = BleakScanner(detection_callback=detection_callback)
        
        try:
            await scanner.start()
            
            # Wait for device to be found or timeout
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            
            await scanner.stop()
        except Exception as e:
            log.error(f"Error during scan: {e}")
            try:
                await scanner.stop()
            except:
                pass
            return None
        
        if found_device:
            self._device_name = found_device.name
            return found_device.address
        
        log.warning(f"Device '{device_name}' not found after {timeout} seconds")
        return None
    
    async def scan_all_devices(self, timeout: float = 10.0) -> list[BLEDevice]:
        """Scan for all available BLE devices.
        
        Args:
            timeout: Maximum time to scan in seconds
            
        Returns:
            List of discovered BLE devices
        """
        log.info(f"Scanning for all BLE devices (timeout: {timeout}s)...")
        devices = await BleakScanner.discover(timeout=timeout)
        log.info(f"Found {len(devices)} device(s)")
        return devices
    
    async def connect(self, device_address: str, retries: int = 3) -> bool:
        """Connect to a BLE device by address.
        
        Args:
            device_address: MAC address of the device
            retries: Number of connection attempts
            
        Returns:
            True if connection successful, False otherwise
        """
        log.info(f"Connecting to {device_address}...")
        
        last_error = None
        for attempt in range(retries):
            try:
                if attempt > 0:
                    log.info(f"Connection attempt {attempt + 1}/{retries}...")
                    await asyncio.sleep(1)  # Brief delay between retries
                
                self._client = BleakClient(device_address)
                await asyncio.wait_for(self._client.connect(), timeout=30.0)
                
                if not self._client.is_connected:
                    log.error("Failed to connect to device")
                    continue
                
                self._device_address = device_address
                log.info("Connected to device")
                
                # Log MTU size
                try:
                    mtu = self._client.mtu_size
                    log.info(f"MTU size: {mtu}")
                except AttributeError:
                    log.info("MTU size not available (platform limitation)")
                
                return True
                
            except asyncio.TimeoutError:
                last_error = "Connection timeout"
                log.warning(f"Connection timeout (attempt {attempt + 1}/{retries})")
            except BleakError as e:
                last_error = str(e)
                error_str = str(e)
                # Check for BR/EDR vs BLE confusion
                if "br-connection" in error_str.lower() or "profile-unavailable" in error_str.lower():
                    log.warning(f"BR/EDR connection error - device may need to be unpaired from classic Bluetooth")
                    log.warning("Try: bluetoothctl remove {device_address}")
                log.warning(f"BLE connection error (attempt {attempt + 1}/{retries}): {e}")
            except Exception as e:
                last_error = str(e)
                log.warning(f"Unexpected error (attempt {attempt + 1}/{retries}): {e}")
        
        log.error(f"Failed to connect after {retries} attempts. Last error: {last_error}")
        return False
    
    async def scan_and_connect(
        self,
        device_name: str,
        scan_timeout: float = 30.0,
        partial_match: bool = True
    ) -> bool:
        """Scan for a device by name and connect to it immediately.
        
        This method scans for the device and connects as soon as it's found,
        avoiding the issue where the device "expires" from BlueZ cache between
        scan and connect operations.
        
        Args:
            device_name: Name of the device to find
            scan_timeout: Maximum time to scan in seconds
            partial_match: If True, match devices containing the name
            
        Returns:
            True if connection successful, False otherwise
        """
        log.info(f"Scanning for device with name: {device_name}")
        
        target_name_upper = device_name.upper()
        found_device: BLEDevice | None = None
        stop_event = asyncio.Event()
        
        def detection_callback(device: BLEDevice, advertisement_data):
            nonlocal found_device
            name = device.name or ""
            name_upper = name.upper()
            
            if name_upper == target_name_upper:
                log.info(f"Found device: {device.name} at {device.address}")
                found_device = device
                stop_event.set()
            elif partial_match and target_name_upper in name_upper:
                log.info(f"Found device (partial match): {device.name} at {device.address}")
                found_device = device
                stop_event.set()
        
        scanner = BleakScanner(detection_callback=detection_callback)
        
        try:
            await scanner.start()
            
            # Wait for device to be found or timeout
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=scan_timeout)
            except asyncio.TimeoutError:
                pass
            
            await scanner.stop()
        except Exception as e:
            log.error(f"Error during scan: {e}")
            try:
                await scanner.stop()
            except:
                pass
            return False
        
        if not found_device:
            log.warning(f"Device '{device_name}' not found after {scan_timeout} seconds")
            return False
        
        # Connect immediately using the BLEDevice object (more reliable than address)
        log.info(f"Connecting to {found_device.address}...")
        
        try:
            # Use the BLEDevice object directly for more reliable connection
            # On Linux, we need to specify the adapter to avoid BR/EDR vs BLE confusion
            # when the device supports both classic Bluetooth and BLE
            self._client = BleakClient(found_device)
            
            # Connect with timeout to avoid hanging
            await asyncio.wait_for(self._client.connect(), timeout=30.0)
            
            if not self._client.is_connected:
                log.error("Failed to connect to device")
                return False
            
            self._device_address = found_device.address
            self._device_name = found_device.name
            log.info("Connected to device")
            
            # Log MTU size
            try:
                mtu = self._client.mtu_size
                log.info(f"MTU size: {mtu}")
            except AttributeError:
                log.info("MTU size not available (platform limitation)")
            
            return True
            
        except BleakError as e:
            log.error(f"BLE connection error: {e}")
            return False
        except Exception as e:
            log.error(f"Unexpected error during connection: {e}")
            import traceback
            log.error(traceback.format_exc())
            return False
    
    async def disconnect(self):
        """Disconnect from the device."""
        if self._client and self._client.is_connected:
            log.info("Disconnecting...")
            try:
                await self._client.disconnect()
                log.info("Disconnected")
            except Exception as e:
                log.error(f"Error during disconnect: {e}")
        
        self._client = None
        self._device_address = None
        self._notification_handlers.clear()
    
    def log_services(self):
        """Log all discovered services and characteristics."""
        if not self._client or not self._client.services:
            log.warning("No services available (not connected?)")
            return
        
        log.info("Discovered services:")
        for service in self._client.services:
            log.info(f"  Service: {service.uuid}")
            for char in service.characteristics:
                props = ", ".join(char.properties)
                log.info(f"    Characteristic: {char.uuid} [{props}]")
    
    async def start_notify(
        self,
        characteristic_uuid: str,
        callback: NotificationCallback
    ) -> bool:
        """Enable notifications on a characteristic.
        
        Args:
            characteristic_uuid: UUID of the characteristic
            callback: Function to call when notification received.
                      Signature: callback(sender, data: bytearray)
            
        Returns:
            True if notifications enabled, False otherwise
        """
        if not self._client or not self._client.is_connected:
            log.error("Cannot enable notifications: not connected")
            return False
        
        try:
            await self._client.start_notify(characteristic_uuid, callback)
            self._notification_handlers[characteristic_uuid] = callback
            log.info(f"Notifications enabled on {characteristic_uuid}")
            return True
        except BleakError as e:
            log.error(f"Failed to enable notifications on {characteristic_uuid}: {e}")
            # Try with uppercase UUID as fallback
            try:
                await self._client.start_notify(
                    characteristic_uuid.upper(),
                    callback
                )
                self._notification_handlers[characteristic_uuid.upper()] = callback
                log.info(f"Notifications enabled on {characteristic_uuid.upper()}")
                return True
            except BleakError as e2:
                log.error(f"Failed to enable notifications (retry): {e2}")
                return False
    
    async def stop_notify(self, characteristic_uuid: str) -> bool:
        """Disable notifications on a characteristic.
        
        Args:
            characteristic_uuid: UUID of the characteristic
            
        Returns:
            True if notifications disabled, False otherwise
        """
        if not self._client or not self._client.is_connected:
            log.error("Cannot disable notifications: not connected")
            return False
        
        try:
            await self._client.stop_notify(characteristic_uuid)
            self._notification_handlers.pop(characteristic_uuid, None)
            log.info(f"Notifications disabled on {characteristic_uuid}")
            return True
        except BleakError as e:
            log.error(f"Failed to disable notifications on {characteristic_uuid}: {e}")
            return False
    
    async def write_characteristic(
        self,
        characteristic_uuid: str,
        data: bytes,
        response: bool = False
    ) -> bool:
        """Write data to a characteristic.
        
        Args:
            characteristic_uuid: UUID of the characteristic
            data: Bytes to write
            response: If True, wait for write response (slower but confirmed)
            
        Returns:
            True if write successful, False otherwise
        """
        if not self._client or not self._client.is_connected:
            log.error("Cannot write: not connected")
            return False
        
        try:
            await self._client.write_gatt_char(
                characteristic_uuid,
                data,
                response=response
            )
            return True
        except BleakError as e:
            log.error(f"Failed to write to {characteristic_uuid}: {e}")
            return False
    
    async def read_characteristic(self, characteristic_uuid: str) -> bytes | None:
        """Read data from a characteristic.
        
        Args:
            characteristic_uuid: UUID of the characteristic
            
        Returns:
            Bytes read, or None on error
        """
        if not self._client or not self._client.is_connected:
            log.error("Cannot read: not connected")
            return None
        
        try:
            data = await self._client.read_gatt_char(characteristic_uuid)
            return bytes(data)
        except BleakError as e:
            log.error(f"Failed to read from {characteristic_uuid}: {e}")
            return None
    
    async def run_until_disconnected(self, check_interval: float = 1.0):
        """Run until the connection is lost or stop() is called.
        
        Args:
            check_interval: How often to check connection status in seconds
        """
        while self._running and self.is_connected:
            await asyncio.sleep(check_interval)
    
    async def run_with_reconnect(
        self,
        device_name: str,
        reconnect_delay: float = 5.0,
        scan_timeout: float = 30.0
    ):
        """Run with automatic reconnection on disconnect.
        
        Args:
            device_name: Name of the device to reconnect to
            reconnect_delay: Seconds to wait before reconnection attempt
            scan_timeout: Timeout for device scanning
        """
        while self._running:
            if self.is_connected:
                await asyncio.sleep(1)
            else:
                log.warning("Connection lost, attempting to reconnect...")
                if not await self.scan_and_connect(device_name, scan_timeout):
                    log.error(f"Reconnection failed, waiting {reconnect_delay}s...")
                    await asyncio.sleep(reconnect_delay)
    
    def stop(self):
        """Signal the client to stop running."""
        self._running = False

