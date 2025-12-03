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
        
        Args:
            device_name: Name of the device to find (case-insensitive)
            timeout: Maximum time to scan in seconds
            partial_match: If True, match devices containing the name
            
        Returns:
            Device address if found, None otherwise
        """
        log.info(f"Scanning for device with name: {device_name}")
        
        target_name_upper = device_name.upper()
        
        devices = await BleakScanner.discover(timeout=timeout)
        
        for device in devices:
            name = device.name or ""
            name_upper = name.upper()
            
            if name_upper == target_name_upper:
                log.info(f"Found device: {device.name} at {device.address}")
                self._device_name = device.name
                return device.address
            
            if partial_match and target_name_upper in name_upper:
                log.info(f"Found device (partial match): {device.name} at {device.address}")
                self._device_name = device.name
                return device.address
        
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
    
    async def connect(self, device_address: str) -> bool:
        """Connect to a BLE device by address.
        
        Args:
            device_address: MAC address of the device
            
        Returns:
            True if connection successful, False otherwise
        """
        log.info(f"Connecting to {device_address}...")
        
        try:
            self._client = BleakClient(device_address)
            await self._client.connect()
            
            if not self._client.is_connected:
                log.error("Failed to connect to device")
                return False
            
            self._device_address = device_address
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
    
    async def scan_and_connect(
        self,
        device_name: str,
        scan_timeout: float = 30.0,
        partial_match: bool = True
    ) -> bool:
        """Scan for a device by name and connect to it.
        
        Args:
            device_name: Name of the device to find
            scan_timeout: Maximum time to scan in seconds
            partial_match: If True, match devices containing the name
            
        Returns:
            True if connection successful, False otherwise
        """
        address = await self.scan_for_device(
            device_name,
            timeout=scan_timeout,
            partial_match=partial_match
        )
        
        if not address:
            return False
        
        return await self.connect(address)
    
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

