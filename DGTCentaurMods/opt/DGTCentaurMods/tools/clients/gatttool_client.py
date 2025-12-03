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
import time
from typing import Callable

from DGTCentaurMods.board.logging import log


# Type alias for notification callback
NotificationCallback = Callable[[int, bytearray], None]


class GatttoolClient:
    """BLE client using gatttool for communication.
    
    This client uses gatttool in interactive mode to communicate with BLE devices.
    It is useful for devices where bleak fails due to BlueZ dual-mode handling.
    
    All operations (connect, discover, read, write, notify) are done within a
    single interactive gatttool session to avoid connection issues.
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
        self._response_queue: queue.Queue = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._output_buffer = ""
    
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
    
    def _read_output(self, timeout: float = 2.0) -> str:
        """Read output from gatttool with timeout.
        
        Args:
            timeout: Maximum time to wait for output
            
        Returns:
            Output string
        """
        output_lines = []
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                line = self._response_queue.get(timeout=0.1)
                output_lines.append(line)
                # Reset timeout on each line received
                start_time = time.time()
            except queue.Empty:
                # If we have some output and queue is empty, we're done
                if output_lines:
                    break
        
        return '\n'.join(output_lines)
    
    def _reader_loop(self):
        """Background thread to read gatttool output."""
        while self._running and self._process:
            try:
                if self._process.stdout:
                    line = self._process.stdout.readline()
                    if line:
                        line = line.strip()
                        if line:
                            log.debug(f"gatttool: {line}")
                            self._response_queue.put(line)
                            
                            # Check for notifications
                            if 'Notification' in line or 'Indication' in line:
                                self._handle_notification_line(line)
                    else:
                        # EOF - process ended
                        break
            except Exception as e:
                if self._running:
                    log.debug(f"Reader error: {e}")
                break
    
    def _handle_notification_line(self, line: str):
        """Parse and handle a notification line."""
        # Format: "Notification handle = 0x0037 value: 73 52 4e 42..."
        match = re.search(
            r'handle\s*=\s*0x([0-9a-f]+).*?value:\s*([0-9a-f ]+)',
            line, re.IGNORECASE
        )
        if match:
            handle = int(match.group(1), 16)
            hex_str = match.group(2).strip()
            try:
                data = bytearray.fromhex(hex_str.replace(' ', ''))
                
                # Call registered callback
                if handle in self._notification_callbacks:
                    try:
                        self._notification_callbacks[handle](handle, data)
                    except Exception as e:
                        log.error(f"Notification callback error: {e}")
                else:
                    log.info(f"RX [handle {handle:04x}]: {data.hex()}")
            except ValueError as e:
                log.warning(f"Failed to parse notification data: {e}")
    
    def _send_command(self, cmd: str):
        """Send a command to gatttool."""
        if self._process and self._process.stdin:
            self._process.stdin.write(f"{cmd}\n")
            self._process.stdin.flush()
    
    async def connect_and_discover(self, device_address: str, timeout: int = 15) -> bool:
        """Connect to device and discover services in one session.
        
        This method connects and discovers services within a single gatttool
        interactive session, avoiding the connection issues that occur when
        using separate gatttool invocations.
        
        Args:
            device_address: MAC address of the device
            timeout: Connection timeout in seconds
            
        Returns:
            True if connected and services discovered, False otherwise
        """
        self._device_address = device_address
        self._services = []
        self._characteristics = []
        
        # Stop any existing connection
        await self.disconnect()
        
        log.info(f"Connecting to {device_address} via gatttool...")
        
        try:
            self._process = subprocess.Popen(
                ['gatttool', '-b', device_address, '-I'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1  # Line buffered
            )
            
            self._running = True
            
            # Start reader thread
            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()
            
            await asyncio.sleep(0.5)
            
            # Clear any initial output
            while not self._response_queue.empty():
                try:
                    self._response_queue.get_nowait()
                except queue.Empty:
                    break
            
            # Send connect command
            log.info("Sending connect command...")
            self._send_command("connect")
            
            # Wait for connection
            connected = False
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    line = self._response_queue.get(timeout=0.5)
                    if 'Connection successful' in line:
                        connected = True
                        log.info("Connected!")
                        break
                    elif 'Error' in line or 'error' in line:
                        log.error(f"Connection error: {line}")
                        await self.disconnect()
                        return False
                except queue.Empty:
                    pass
            
            if not connected:
                log.error(f"Connection timed out after {timeout} seconds")
                await self.disconnect()
                return False
            
            self._connected = True
            
            # Discover primary services
            log.info("Discovering primary services...")
            self._send_command("primary")
            await asyncio.sleep(1)
            
            output = self._read_output(timeout=3.0)
            self._services = self._parse_primary_output(output)
            log.info(f"Found {len(self._services)} services")
            
            for service in self._services:
                log.info(f"  Service: {service['uuid']} (handles {service['start_handle']:04x}-{service['end_handle']:04x})")
            
            # Discover characteristics
            log.info("Discovering characteristics...")
            self._send_command("char-desc")
            await asyncio.sleep(2)
            
            output = self._read_output(timeout=3.0)
            self._characteristics = self._parse_char_desc_output(output)
            log.info(f"Found {len(self._characteristics)} characteristics")
            
            # Log key characteristics
            for char in self._characteristics:
                if char['uuid'] in ['0000fff1-0000-1000-8000-00805f9b34fb',
                                    '0000fff2-0000-1000-8000-00805f9b34fb']:
                    cccd_info = f", CCCD: {char['cccd_handle']:04x}" if char.get('cccd_handle') else ""
                    log.info(f"  Key char: {char['uuid']} (handle {char['value_handle']:04x}{cccd_info})")
            
            return True
            
        except FileNotFoundError:
            log.error("gatttool not found - ensure bluez is installed")
            return False
        except Exception as e:
            log.error(f"Connection error: {e}")
            await self.disconnect()
            return False
    
    def _parse_primary_output(self, output: str) -> list[dict]:
        """Parse gatttool primary output to find service handles and UUIDs."""
        services = []
        pattern = r'attr handle[=:]\s*0x([0-9a-f]+),?\s*end grp handle[=:]\s*0x([0-9a-f]+)\s*uuid[=:]\s*([0-9a-f-]+)'
        
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
        
        # Pattern: "handle = 0xXXXX, uuid = UUID"
        pattern = r'handle[=:]\s*0x([0-9a-f]+),?\s*uuid[=:]\s*([0-9a-f-]+)'
        
        prev_decl_handle = None
        
        for i, line in enumerate(lines):
            match = re.search(pattern, line, re.IGNORECASE)
            if not match:
                continue
            
            handle = int(match.group(1), 16)
            uuid = match.group(2).lower()
            
            # Skip standard Bluetooth attribute UUIDs
            skip_uuids = [
                '00002800-0000-1000-8000-00805f9b34fb',  # Primary Service
                '00002801-0000-1000-8000-00805f9b34fb',  # Secondary Service
                '00002803-0000-1000-8000-00805f9b34fb',  # Characteristic Declaration
            ]
            
            if uuid in skip_uuids:
                if uuid == '00002803-0000-1000-8000-00805f9b34fb':
                    prev_decl_handle = handle
                continue
            
            # CCCD (Client Characteristic Configuration Descriptor)
            if uuid == '00002902-0000-1000-8000-00805f9b34fb':
                # Attach to previous characteristic
                if characteristics:
                    characteristics[-1]['cccd_handle'] = handle
                continue
            
            # This is a characteristic value
            char_entry = {
                'decl_handle': prev_decl_handle,
                'value_handle': handle,
                'uuid': uuid,
                'cccd_handle': None
            }
            characteristics.append(char_entry)
        
        return characteristics
    
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
            # Try handle + 1 as a common pattern
            cccd_handle = handle + 1
            log.warning(f"No CCCD found for handle {handle:04x}, trying {cccd_handle:04x}")
        
        # Write 0x0100 to CCCD to enable notifications
        log.info(f"Enabling notifications on handle {handle:04x} (CCCD {cccd_handle:04x})")
        self._send_command(f"char-write-req {cccd_handle:04x} 0100")
        self._notification_callbacks[handle] = callback
        await asyncio.sleep(0.3)
        
        # Check for success
        output = self._read_output(timeout=1.0)
        if 'successfully' in output.lower():
            log.info("Notifications enabled")
            return True
        elif 'error' in output.lower():
            log.error(f"Failed to enable notifications: {output}")
            return False
        
        # Assume success if no error
        return True
    
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
        self._send_command(f"{cmd} {handle:04x} {hex_data}")
        await asyncio.sleep(0.1)
        
        if response:
            output = self._read_output(timeout=1.0)
            if 'successfully' in output.lower():
                return True
            elif 'error' in output.lower():
                log.error(f"Write failed: {output}")
                return False
        
        return True
    
    async def disconnect(self):
        """Disconnect from the device."""
        self._running = False
        self._connected = False
        
        if self._process:
            try:
                self._send_command("disconnect")
                await asyncio.sleep(0.3)
                self._send_command("exit")
                await asyncio.sleep(0.2)
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
