"""
Relay Manager for Shadow Target connections.

This module manages relay mode functionality, which connects to a "shadow target"
(typically a real Millennium board) and relays data between it and clients.
This is primarily used for development/debugging to compare emulator responses
against a real device.

The relay manager handles:
- Discovery and connection to shadow target devices
- Bidirectional data relay between shadow target and clients
- Response comparison for debugging emulator behavior

Usage:
    relay_manager = RelayManager(
        target_name="MILLENNIUM CHESS",
        on_data_from_target=handle_target_data,
        on_disconnected=handle_disconnect
    )
    relay_manager.connect()
    relay_manager.send_to_target(data)
"""

import threading
import time
import bluetooth

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.rfcomm_manager import RfcommManager


class RelayManager:
    """Manages relay connections to shadow target devices.
    
    The relay manager connects to a real chess board (shadow target) and relays
    data between it and connected clients. This enables comparing emulator
    responses against a real device for debugging purposes.
    
    Attributes:
        target_name: Name of the shadow target device to connect to
        connected: Whether currently connected to shadow target
        on_data_from_target: Callback for data received from shadow target
        on_disconnected: Callback when shadow target disconnects
    """
    
    def __init__(self, target_name: str = "MILLENNIUM CHESS",
                 on_data_from_target=None,
                 on_disconnected=None):
        """Initialize the RelayManager.
        
        Args:
            target_name: Name of the shadow target device to connect to
            on_data_from_target: Callback(data: bytes) for data from shadow target
            on_disconnected: Callback() when shadow target disconnects
        """
        self.target_name = target_name
        self.on_data_from_target = on_data_from_target
        self.on_disconnected = on_disconnected
        
        # Connection state
        self._socket = None
        self._connected = False
        self._running = False
        
        # Receiver thread
        self._receiver_thread = None
        self._receiver_started = False
    
    @property
    def connected(self) -> bool:
        """Check if connected to shadow target."""
        return self._connected
    
    def find_device(self) -> str:
        """Find the shadow target device by name.
        
        First checks known devices, then performs a discovery scan if not found.
        
        Returns:
            Device address if found, None otherwise
        """
        log.info(f"[RelayManager] Looking for {self.target_name} device...")
        
        # First, try to find in known devices using RfcommManager
        controller = RfcommManager()
        addr = controller.find_device_by_name(self.target_name)
        if addr:
            log.info(f"[RelayManager] Found {self.target_name} in known devices: {addr}")
            return addr
        
        # If not found in known devices, do a discovery scan
        log.info(f"[RelayManager] Scanning for {self.target_name} device...")
        devices = bluetooth.discover_devices(duration=8, lookup_names=True, flush_cache=True)
        
        for addr, name in devices:
            log.info(f"[RelayManager] Found device: {name} ({addr})")
            if name and self.target_name.upper() in name.upper():
                log.info(f"[RelayManager] Found {self.target_name} at address: {addr}")
                return addr
        
        log.warning(f"[RelayManager] {self.target_name} device not found in scan")
        return None
    
    def find_service(self, device_addr: str) -> int:
        """Find the RFCOMM service on the shadow target device.
        
        Args:
            device_addr: Bluetooth address of the device
            
        Returns:
            RFCOMM port number if found, None otherwise
        """
        log.info(f"[RelayManager] Discovering services on {device_addr}...")
        
        services = bluetooth.find_service(address=device_addr)
        
        for service in services:
            log.info(f"[RelayManager] Service: {service.get('name', 'Unknown')} - "
                     f"Protocol: {service.get('protocol', 'Unknown')} - "
                     f"Port: {service.get('port', 'Unknown')}")
            
            if service.get('protocol') == 'RFCOMM':
                port = service.get('port')
                if port is not None:
                    log.info(f"[RelayManager] Found RFCOMM service on port {port}")
                    return port
        
        log.warning(f"[RelayManager] No RFCOMM service found on {device_addr}")
        return None
    
    def connect(self) -> bool:
        """Connect to the shadow target device.
        
        Attempts to find the device and connect to its RFCOMM service.
        If no service is found, tries common RFCOMM ports.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            device_addr = self.find_device()
            if not device_addr:
                log.error(f"[RelayManager] Could not find shadow target '{self.target_name}'")
                return False
            
            port = self.find_service(device_addr)
            if port is None:
                log.info("[RelayManager] Trying common RFCOMM ports...")
                for common_port in [1, 2, 3, 4, 5]:
                    try:
                        log.info(f"[RelayManager] Attempting connection on port {common_port}...")
                        sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
                        sock.connect((device_addr, common_port))
                        self._socket = sock
                        self._connected = True
                        self._running = True
                        log.info(f"[RelayManager] Connected to {device_addr} on port {common_port}")
                        self._start_receiver()
                        return True
                    except Exception as e:
                        log.debug(f"[RelayManager] Failed on port {common_port}: {e}")
                        try:
                            sock.close()
                        except:
                            pass
                log.error(f"[RelayManager] Could not connect to {device_addr} on any common port")
                return False
            
            log.info(f"[RelayManager] Connecting to {device_addr}:{port}...")
            self._socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            self._socket.connect((device_addr, port))
            self._connected = True
            self._running = True
            log.info(f"[RelayManager] Connected to shadow target successfully")
            self._start_receiver()
            return True
            
        except Exception as e:
            log.error(f"[RelayManager] Error connecting to shadow target: {e}")
            import traceback
            log.error(traceback.format_exc())
            return False
    
    def _start_receiver(self):
        """Start the receiver thread to handle data from shadow target."""
        if not self._receiver_started:
            self._receiver_thread = threading.Thread(
                target=self._receiver_loop,
                daemon=True,
                name="RelayManager-Receiver"
            )
            self._receiver_thread.start()
            self._receiver_started = True
    
    def _receiver_loop(self):
        """Receive data from shadow target and invoke callback."""
        log.info("[RelayManager] Starting receiver thread")
        try:
            while self._running and self._connected:
                try:
                    if self._socket is None:
                        time.sleep(0.1)
                        continue
                    
                    data = self._socket.recv(1024)
                    if len(data) > 0:
                        data_bytes = bytes(data)
                        hex_str = ' '.join(f'{b:02x}' for b in data_bytes)
                        log.info(f"[RelayManager] Shadow target -> : {hex_str}")
                        
                        # Invoke callback
                        if self.on_data_from_target:
                            self.on_data_from_target(data_bytes)
                    else:
                        # Empty read indicates disconnection
                        log.info("[RelayManager] Shadow target disconnected (empty read)")
                        self._connected = False
                        break
                        
                except bluetooth.BluetoothError as e:
                    if self._running:
                        log.error(f"[RelayManager] Bluetooth error in receiver: {e}")
                    self._connected = False
                    break
                except Exception as e:
                    if self._running:
                        log.error(f"[RelayManager] Error in receiver: {e}")
                    break
        except Exception as e:
            log.error(f"[RelayManager] Receiver thread error: {e}")
        finally:
            log.info("[RelayManager] Receiver thread stopped")
            self._connected = False
            if self.on_disconnected:
                self.on_disconnected()
    
    def send_to_target(self, data: bytes) -> bool:
        """Send data to the shadow target.
        
        Args:
            data: Data bytes to send
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self._connected or self._socket is None:
            log.warning("[RelayManager] Cannot send - not connected to shadow target")
            return False
        
        try:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            log.info(f"[RelayManager] -> Shadow target: {hex_str}")
            self._socket.send(data)
            return True
        except Exception as e:
            log.error(f"[RelayManager] Error sending to shadow target: {e}")
            self._connected = False
            return False
    
    def stop(self):
        """Stop the relay manager and close connection."""
        log.info("[RelayManager] Stopping...")
        self._running = False
        self._connected = False
        
        if self._socket:
            try:
                self._socket.close()
            except Exception as e:
                log.debug(f"[RelayManager] Error closing socket: {e}")
            self._socket = None
        
        log.info("[RelayManager] Stopped")
