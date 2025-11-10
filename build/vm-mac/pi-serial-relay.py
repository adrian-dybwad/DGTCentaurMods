#!/usr/bin/env python3
"""
Serial Relay Daemon for Raspberry Pi
Forwards serial data between /dev/serial0 and network socket
Allows Mac VM to communicate with real Pi hardware
"""

import socket
import serial
import threading
import sys
import signal
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "DGTCentaurMods" / "opt" / "DGTCentaurMods"))

from board.logging import setup_logging

log = setup_logging(__name__)

SERIAL_PORT = "/dev/serial0"
SERIAL_BAUD = 9600  # Adjust if needed
NETWORK_PORT = 8888
NETWORK_HOST = "0.0.0.0"  # Listen on all interfaces

class SerialRelay:
    def __init__(self, serial_port, network_port, network_host="0.0.0.0"):
        self.serial_port = serial_port
        self.network_port = network_port
        self.network_host = network_host
        self.serial_conn = None
        self.network_conn = None
        self.network_socket = None
        self.running = False
        
    def start(self):
        """Start the serial relay"""
        log.info(f"Starting serial relay: {self.serial_port} <-> {self.network_host}:{self.network_port}")
        
        # Open serial port
        try:
            self.serial_conn = serial.Serial(
                self.serial_port,
                SERIAL_BAUD,
                timeout=1
            )
            log.info(f"Serial port opened: {self.serial_port}")
        except Exception as e:
            log.error(f"Failed to open serial port: {e}")
            return False
        
        # Create network socket
        try:
            self.network_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.network_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.network_socket.bind((self.network_host, self.network_port))
            self.network_socket.listen(1)
            log.info(f"Listening on {self.network_host}:{self.network_port}")
        except Exception as e:
            log.error(f"Failed to create network socket: {e}")
            return False
        
        self.running = True
        
        # Accept connections
        while self.running:
            try:
                log.info("Waiting for VM connection...")
                self.network_conn, addr = self.network_socket.accept()
                log.info(f"VM connected from {addr}")
                
                # Start bidirectional forwarding
                self._forward_data()
                
            except Exception as e:
                if self.running:
                    log.error(f"Connection error: {e}")
                break
        
        return True
    
    def _forward_data(self):
        """Forward data bidirectionally between serial and network"""
        def serial_to_network():
            """Forward serial -> network"""
            while self.running and self.network_conn:
                try:
                    data = self.serial_conn.read(1024)
                    if data:
                        log.debug(f"Serial->Network: {len(data)} bytes")
                        self.network_conn.sendall(data)
                except Exception as e:
                    if self.running:
                        log.error(f"Serial->Network error: {e}")
                    break
        
        def network_to_serial():
            """Forward network -> serial"""
            while self.running and self.network_conn:
                try:
                    data = self.network_conn.recv(1024)
                    if not data:
                        break
                    log.debug(f"Network->Serial: {len(data)} bytes")
                    self.serial_conn.write(data)
                    self.serial_conn.flush()
                except Exception as e:
                    if self.running:
                        log.error(f"Network->Serial error: {e}")
                    break
        
        # Start forwarding threads
        t1 = threading.Thread(target=serial_to_network, daemon=True)
        t2 = threading.Thread(target=network_to_serial, daemon=True)
        t1.start()
        t2.start()
        
        # Wait for threads to complete
        t1.join()
        t2.join()
        
        # Close connection
        if self.network_conn:
            self.network_conn.close()
            self.network_conn = None
        log.info("VM disconnected")
    
    def stop(self):
        """Stop the relay"""
        log.info("Stopping serial relay...")
        self.running = False
        
        if self.network_conn:
            self.network_conn.close()
        if self.network_socket:
            self.network_socket.close()
        if self.serial_conn:
            self.serial_conn.close()
        
        log.info("Serial relay stopped")

def main():
    relay = SerialRelay(SERIAL_PORT, NETWORK_PORT, NETWORK_HOST)
    
    # Handle signals
    def signal_handler(sig, frame):
        relay.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start relay
    try:
        relay.start()
    except KeyboardInterrupt:
        pass
    finally:
        relay.stop()

if __name__ == "__main__":
    main()

