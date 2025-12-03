"""
Gatttool-based BLE Client

A BLE client that uses gatttool instead of bleak for connecting to BLE devices.
This is useful for devices where bleak fails due to BlueZ dual-mode handling issues.

gatttool uses LE transport directly and does not suffer from the same issues
as the BlueZ D-Bus API that bleak uses.

Requirements:
    gatttool (part of bluez package)
"""

import asyncio
import subprocess
import threading
import queue
import re
import select
import time
from typing import Callable, Any

from DGTCentaurMods.board.logging import log


# Type alias for notification callback
NotificationCallback = Callable[[int, bytearray], None]


class GatttoolClient:
    """BLE client using gatttool for communication.
    
    This client uses gatttool in interactive mode to communicate with BLE devices.
    It is useful for devices where bleak fails due to BlueZ dual-mode handling.
    """
    
    def __init__(self):
        """Initialize the gatttool client."""
        self._device_address: str | None = None
        self._process: subprocess.Popen | None = None
        self._running = False
        self._connected = False
        self._services: list[dict] = []
        self._characteristics: list[dict] = []
        self._notification_callbacks: dict[int, NotificationCallback] = {}
        self._stdout_queue: queue.Queue = queue.Queue()
        self._stderr_queue: queue.Queue = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to a device."""
        return self._connected and self._process is not None and self._process.poll() is None
    
    @property
    def device_address(self) -> str | None:
        """Get the connected device address."""
        return self._device_address
    
    @property
    def services(self) -> list[dict]:
        """Get discovered services."""
        return self._services
    
    @property
    def characteristics(self) -> list[dict]:
        """Get discovered characteristics."""
        return self._characteristics
    
    def _parse_primary_output(self, output: str) -> list[dict]:
        """Parse gatttool --primary output to find service handles and UUIDs."""
        services = []
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
    
    def _parse_char_desc_output(self, output: str) -> list[dict]:
        """Parse gatttool char-desc output to find characteristic handles and UUIDs."""
        characteristics = []
        lines = output.split('\n')
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            
            # Look for characteristic declaration (uuid 2803)
            char_decl_match = re.search(
                r'handle = 0x([0-9a-f]+), uuid = 00002803-0000-1000-8000-00805f9b34fb',
                line, re.IGNORECASE
            )
            if char_decl_match:
                decl_handle = int(char_decl_match.group(1), 16)
                # Next line should be the characteristic value with the actual UUID
                if i + 1 < len(lines):
                    value_line = lines[i + 1].strip()
                    # Skip if it's another declaration or CCCD
                    if '00002803' not in value_line and '00002902' not in value_line:
                        value_match = re.search(
                            r'handle = 0x([0-9a-f]+), uuid = ([0-9a-f-]+)',
                            value_line, re.IGNORECASE
                        )
                        if value_match:
                            value_handle = int(value_match.group(1), 16)
                            uuid_raw = value_match.group(2).lower()
                            
                            # Skip standard Bluetooth UUIDs
                            skip_uuids = [
                                '00002800-0000-1000-8000-00805f9b34fb',  # Primary Service
                                '00002801-0000-1000-8000-00805f9b34fb',  # Secondary Service
                                '00002803-0000-1000-8000-00805f9b34fb',  # Characteristic
                                '00002902-0000-1000-8000-00805f9b34fb',  # CCCD
                            ]
                            if uuid_raw in skip_uuids:
                                i += 1
                                continue
                            
                            # Look for CCCD on next line
                            cccd_handle = None
                            if i + 2 < len(lines):
                                cccd_line = lines[i + 2].strip()
                                cccd_match = re.search(
                                    r'handle = 0x([0-9a-f]+), uuid = 00002902-0000-1000-8000-00805f9b34fb',
                                    cccd_line, re.IGNORECASE
                                )
                                if cccd_match:
                                    cccd_handle = int(cccd_match.group(1), 16)
                            
                            characteristics.append({
                                'decl_handle': decl_handle,
                                'value_handle': value_handle,
                                'uuid': uuid_raw,
                                'cccd_handle': cccd_handle
                            })
            i += 1
        
        return characteristics
    
    async def discover_services(self, device_address: str, timeout: int = 15) -> bool:
        """Discover services and characteristics using gatttool.
        
        Args:
            device_address: MAC address of the device
            timeout: Timeout in seconds
            
        Returns:
            True if services were discovered, False otherwise
        """
        self._device_address = device_address
        self._services = []
        self._characteristics = []
        
        # Disconnect any existing connection first
        log.info("Disconnecting any existing connection...")
        try:
            subprocess.run(
                ['bluetoothctl', 'disconnect', device_address],
                capture_output=True, timeout=5, text=True
            )
            await asyncio.sleep(1)
        except Exception:
            pass
        
        # Discover services
        log.info(f"Discovering services on {device_address}...")
        try:
            result = subprocess.run(
                ['gatttool', '-b', device_address, '--primary'],
                capture_output=True, text=True, timeout=timeout
            )
            
            if result.returncode != 0:
                log.error(f"gatttool --primary failed: {result.stderr}")
                return False
            
            self._services = self._parse_primary_output(result.stdout)
            log.info(f"Found {len(self._services)} services")
            
            for service in self._services:
                log.info(f"  Service: {service['uuid']} (handles {service['start_handle']:04x}-{service['end_handle']:04x})")
            
        except subprocess.TimeoutExpired:
            log.error(f"gatttool --primary timed out after {timeout} seconds")
            return False
        except FileNotFoundError:
            log.error("gatttool not found - ensure bluez is installed")
            return False
        except Exception as e:
            log.error(f"Error discovering services: {e}")
            return False
        
        # Discover characteristics for each service
        for service in self._services:
            log.info(f"Discovering characteristics for service {service['uuid']}...")
            try:
                result = subprocess.run(
                    ['gatttool', '-b', device_address, '--char-desc',
                     f"{service['start_handle']:04x}", f"{service['end_handle']:04x}"],
                    capture_output=True, text=True, timeout=10
                )
                
                if result.returncode == 0:
                    chars = self._parse_char_desc_output(result.stdout)
                    for char in chars:
                        char['service_uuid'] = service['uuid']
                    self._characteristics.extend(chars)
                    log.info(f"  Found {len(chars)} characteristics")
                else:
                    log.warning(f"Failed to discover characteristics: {result.stderr}")
                    
            except subprocess.TimeoutExpired:
                log.warning(f"Characteristic discovery timed out for service {service['uuid']}")
            except Exception as e:
                log.warning(f"Error discovering characteristics: {e}")
        
        log.info(f"Total characteristics found: {len(self._characteristics)}")
        for char in self._characteristics:
            cccd_info = f", CCCD: {char['cccd_handle']:04x}" if char.get('cccd_handle') else ""
            log.info(f"  Characteristic: {char['uuid']} (handle {char['value_handle']:04x}{cccd_info})")
        
        return len(self._services) > 0
    
    async def connect(self, device_address: str | None = None, timeout: int = 10) -> bool:
        """Connect to the device using gatttool interactive mode.
        
        Args:
            device_address: MAC address (uses previously discovered address if None)
            timeout: Connection timeout in seconds
            
        Returns:
            True if connected, False otherwise
        """
        if device_address:
            self._device_address = device_address
        
        if not self._device_address:
            log.error("No device address specified")
            return False
        
        # Stop any existing connection
        await self.disconnect()
        
        log.info(f"Connecting to {self._device_address} via gatttool...")
        
        try:
            self._process = subprocess.Popen(
                ['gatttool', '-b', self._device_address, '-I'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0
            )
            
            await asyncio.sleep(0.5)
            
            # Send connect command
            self._process.stdin.write("connect\n")
            self._process.stdin.flush()
            
            # Wait for connection
            start_time = time.time()
            connected = False
            
            while time.time() - start_time < timeout:
                if self._process.poll() is not None:
                    log.error("gatttool process exited unexpectedly")
                    return False
                
                # Check for connection success in stdout
                ready, _, _ = select.select([self._process.stdout], [], [], 0.5)
                if ready:
                    try:
                        line = self._process.stdout.readline()
                        if line:
                            line = line.strip()
                            log.debug(f"gatttool: {line}")
                            if 'Connection successful' in line:
                                connected = True
                                break
                            elif 'Error' in line or 'error' in line:
                                log.error(f"Connection error: {line}")
                                return False
                    except Exception:
                        pass
            
            if not connected:
                log.error(f"Connection timed out after {timeout} seconds")
                await self.disconnect()
                return False
            
            self._connected = True
            self._running = True
            
            # Start stdout/stderr drain threads
            self._stdout_thread = threading.Thread(target=self._drain_stdout, daemon=True)
            self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
            self._stdout_thread.start()
            self._stderr_thread.start()
            
            # Start notification reader thread
            self._reader_thread = threading.Thread(target=self._read_notifications, daemon=True)
            self._reader_thread.start()
            
            log.info("Connected via gatttool")
            return True
            
        except FileNotFoundError:
            log.error("gatttool not found - ensure bluez is installed")
            return False
        except Exception as e:
            log.error(f"Connection error: {e}")
            await self.disconnect()
            return False
    
    def _drain_stdout(self):
        """Drain stdout from gatttool process."""
        while self._running and self._process:
            try:
                ready, _, _ = select.select([self._process.stdout], [], [], 0.1)
                if ready:
                    chunk = self._process.stdout.read(1024)
                    if chunk:
                        self._stdout_queue.put(chunk)
                    else:
                        break
            except Exception:
                break
    
    def _drain_stderr(self):
        """Drain stderr from gatttool process."""
        while self._running and self._process:
            try:
                ready, _, _ = select.select([self._process.stderr], [], [], 0.1)
                if ready:
                    chunk = self._process.stderr.read(1024)
                    if chunk:
                        self._stderr_queue.put(chunk)
                    else:
                        break
            except Exception:
                break
    
    def _read_notifications(self):
        """Read and process notifications from gatttool."""
        buffer = ""
        
        while self._running:
            try:
                chunk = self._stdout_queue.get(timeout=0.1)
                buffer += chunk
                
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    
                    if not line:
                        continue
                    
                    # Parse notification/indication
                    if 'Notification' in line or 'Indication' in line:
                        match = re.search(
                            r'handle\s*=\s*0x([0-9a-f]+).*?value:\s*([0-9a-f ]+)',
                            line, re.IGNORECASE
                        )
                        if match:
                            handle = int(match.group(1), 16)
                            hex_str = match.group(2).replace(' ', '')
                            try:
                                data = bytearray.fromhex(hex_str)
                                self._handle_notification(handle, data)
                            except ValueError as e:
                                log.warning(f"Failed to parse notification data: {e}")
                    elif 'handle' in line.lower() and 'value' in line.lower():
                        # Alternative notification format
                        match = re.search(
                            r'handle.*?0x([0-9a-f]+).*?value.*?([0-9a-f]{2}(?:\s+[0-9a-f]{2})*)',
                            line, re.IGNORECASE
                        )
                        if match:
                            handle = int(match.group(1), 16)
                            hex_str = match.group(2).replace(' ', '')
                            try:
                                data = bytearray.fromhex(hex_str)
                                self._handle_notification(handle, data)
                            except ValueError:
                                pass
                                
            except queue.Empty:
                continue
            except Exception as e:
                if self._running:
                    log.error(f"Notification reader error: {e}")
                break
    
    def _handle_notification(self, handle: int, data: bytearray):
        """Handle a notification from the device."""
        log.debug(f"Notification from handle {handle:04x}: {data.hex()}")
        
        # Call registered callback
        if handle in self._notification_callbacks:
            try:
                self._notification_callbacks[handle](handle, data)
            except Exception as e:
                log.error(f"Notification callback error: {e}")
        else:
            # Try to find by value_handle
            for char in self._characteristics:
                if char['value_handle'] == handle:
                    log.info(f"RX [{char['uuid']}]: {data.hex()}")
                    break
            else:
                log.info(f"RX [handle {handle:04x}]: {data.hex()}")
    
    async def enable_notifications(self, handle: int, callback: NotificationCallback) -> bool:
        """Enable notifications on a characteristic.
        
        Args:
            handle: Value handle of the characteristic
            callback: Function to call when notification received
            
        Returns:
            True if notifications enabled, False otherwise
        """
        if not self.is_connected:
            log.error("Not connected")
            return False
        
        # Find CCCD handle for this characteristic
        cccd_handle = None
        for char in self._characteristics:
            if char['value_handle'] == handle and char.get('cccd_handle'):
                cccd_handle = char['cccd_handle']
                break
        
        if cccd_handle is None:
            log.error(f"No CCCD found for handle {handle:04x}")
            return False
        
        # Write 0x0100 to CCCD to enable notifications
        log.info(f"Enabling notifications on handle {handle:04x} (CCCD {cccd_handle:04x})")
        try:
            self._process.stdin.write(f"char-write-req {cccd_handle:04x} 0100\n")
            self._process.stdin.flush()
            self._notification_callbacks[handle] = callback
            await asyncio.sleep(0.2)
            return True
        except Exception as e:
            log.error(f"Failed to enable notifications: {e}")
            return False
    
    async def write_characteristic(self, handle: int, data: bytes, response: bool = True) -> bool:
        """Write data to a characteristic.
        
        Args:
            handle: Value handle of the characteristic
            data: Data to write
            response: If True, use char-write-req (with response), else char-write-cmd
            
        Returns:
            True if write succeeded, False otherwise
        """
        if not self.is_connected:
            log.error("Not connected")
            return False
        
        hex_data = data.hex()
        cmd = "char-write-req" if response else "char-write-cmd"
        
        log.debug(f"Writing to handle {handle:04x}: {hex_data}")
        try:
            self._process.stdin.write(f"{cmd} {handle:04x} {hex_data}\n")
            self._process.stdin.flush()
            await asyncio.sleep(0.1)
            return True
        except Exception as e:
            log.error(f"Write failed: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the device."""
        self._running = False
        self._connected = False
        
        if self._process:
            try:
                self._process.stdin.write("disconnect\n")
                self._process.stdin.flush()
                await asyncio.sleep(0.5)
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        
        self._notification_callbacks.clear()
        log.info("Disconnected")
    
    def find_characteristic_by_uuid(self, uuid: str) -> dict | None:
        """Find a characteristic by UUID.
        
        Args:
            uuid: UUID to search for (case-insensitive)
            
        Returns:
            Characteristic dict or None if not found
        """
        uuid_lower = uuid.lower()
        for char in self._characteristics:
            if char['uuid'].lower() == uuid_lower:
                return char
        return None
    
    def stop(self):
        """Stop the client."""
        self._running = False

