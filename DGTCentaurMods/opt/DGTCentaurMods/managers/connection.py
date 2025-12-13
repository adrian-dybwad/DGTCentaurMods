# Connection Manager
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Centralizes BLE and RFCOMM data routing to ProtocolManager.
# Buffers incoming protocol data when ProtocolManager is not yet ready
# (e.g., during menu -> game transition).
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from DGTCentaurMods.board.logging import log
from typing import Callable, Optional, List, Tuple


class ConnectionManager:
    """Manages protocol data routing between BLE/RFCOMM connections and ProtocolManager.
    
    Buffers incoming data when ProtocolManager is not ready (e.g., during menu -> game
    transition) and processes queued data once a handler is registered.
    
    Also handles relay mode forwarding to shadow targets.
    
    This singleton pattern ensures consistent data routing across the application.
    """
    
    _instance: Optional['ConnectionManager'] = None
    
    def __new__(cls) -> 'ConnectionManager':
        """Singleton pattern - returns existing instance or creates new one."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the ConnectionManager.
        
        Only initializes once due to singleton pattern.
        """
        if self._initialized:
            return
        
        self._initialized = True
        self._protocol_manager = None
        self._relay_manager = None
        self._relay_mode = False
        
        # Queue of (data_bytes, source) tuples for data received before handler is ready
        # source is 'millennium', 'pegasus', 'chessnut', or 'rfcomm'
        self._pending_data: List[Tuple[bytes, str]] = []
        
        log.info("[ConnectionManager] Initialized")
    
    def set_protocol_manager(self, handler) -> None:
        """Register the ProtocolManager for data routing.
        
        When a handler is registered, any queued data is immediately processed.
        
        Args:
            handler: ProtocolManager instance, or None to clear
        """
        self._protocol_manager = handler
        
        if handler is not None:
            self._process_pending_data()
    
    def set_relay_manager(self, relay_manager, relay_mode: bool) -> None:
        """Configure relay mode forwarding.
        
        Args:
            relay_manager: RelayManager instance for forwarding data
            relay_mode: True to enable relay forwarding
        """
        self._relay_manager = relay_manager
        self._relay_mode = relay_mode
    
    def receive_data(self, data: bytes, source: str) -> None:
        """Receive protocol data from BLE or RFCOMM connection.
        
        Routes data to ProtocolManager if available, otherwise queues for later.
        Also forwards to relay target if relay mode is enabled.
        
        Args:
            data: Raw bytes received from connection
            source: Data source identifier ('millennium', 'pegasus', 'chessnut', 'rfcomm')
        """
        hex_str = ' '.join(f'{b:02x}' for b in data)
        log.info(f"[{source.upper()} RX] {len(data)} bytes - {hex_str}")
        
        if self._protocol_manager is not None:
            for byte_val in data:
                self._protocol_manager.receive_data(byte_val)
        else:
            log.info(f"[ConnectionManager] Queuing {len(data)} bytes from {source} - handler not ready")
            self._pending_data.append((bytes(data), source))
        
        # Forward to shadow target if in relay mode
        if self._relay_mode and self._relay_manager is not None and self._relay_manager.connected:
            self._relay_manager.send_to_target(data)
    
    def _process_pending_data(self) -> None:
        """Process any data queued before ProtocolManager was ready.
        
        Called automatically when a ProtocolManager is registered via set_protocol_manager().
        """
        if not self._pending_data:
            return
        
        if self._protocol_manager is None:
            log.warning("[ConnectionManager] Cannot process pending data - no handler")
            return
        
        log.info(f"[ConnectionManager] Processing {len(self._pending_data)} queued data packets")
        
        for data, source in self._pending_data:
            hex_str = ' '.join(f'{b:02x}' for b in data)
            log.info(f"[ConnectionManager] Processing queued {source} data: {len(data)} bytes - {hex_str}")
            for byte_val in data:
                self._protocol_manager.receive_data(byte_val)
        
        self._pending_data.clear()
    
    def clear_pending_data(self) -> None:
        """Clear any pending queued data.
        
        Called during game cleanup to prevent stale data from being processed.
        """
        if self._pending_data:
            log.debug(f"[ConnectionManager] Clearing {len(self._pending_data)} pending data packets")
        self._pending_data.clear()
    
    def clear_handler(self) -> None:
        """Clear the registered ProtocolManager and pending data.
        
        Called during game cleanup.
        """
        self._protocol_manager = None
        self.clear_pending_data()
    
    @property
    def has_handler(self) -> bool:
        """Check if a ProtocolManager is currently registered."""
        return self._protocol_manager is not None
    
    @property
    def pending_count(self) -> int:
        """Number of queued data packets awaiting processing."""
        return len(self._pending_data)
