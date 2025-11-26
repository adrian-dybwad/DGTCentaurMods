#!/usr/bin/env python3
"""
Bluetooth Classic SPP Relay

This relay connects to "MILLENNIUM CHESS" via Bluetooth Classic SPP (RFCOMM)
and relays data between that device and a client connected to this relay.

Usage:
    python3 tools/dev-tools/relay2.py
"""

import argparse
import sys
import os
import time
import threading
import signal
import psutil
import bluetooth

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board.bluetooth_controller import BluetoothController
from DGTCentaurMods.games.millennium import receive_data

# Global state
running = True
kill = 0
millennium_connected = False
client_connected = False

# Socket references
millennium_sock = None
server_sock = None
client_sock = None


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
                        packet_type, payload, is_complete = receive_data(byte_val)
                        if is_complete:
                            # Log complete packet results
                            packet_type_str = chr(packet_type) if packet_type and 32 <= packet_type < 127 else f"0x{packet_type:02X}"
                            payload_str = ''.join(chr(b) if 32 <= b < 127 else f'\\x{b:02x}' for b in payload) if payload else "None"
                            log.info(f"[Millennium.receive_data] Complete packet: type={packet_type_str} (0x{packet_type:02X}), payload_len={len(payload) if payload else 0}, payload={payload_str}")
                    
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
    global millennium_connected, client_connected
    
    try:
        log.info("Cleaning up relay...")
        kill = 1
        running = False
        
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
    
    parser = argparse.ArgumentParser(description="Bluetooth Classic SPP Relay - Connect to MILLENNIUM CHESS and relay data")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="RFCOMM port for server (default: auto-assign)"
    )
    
    args = parser.parse_args()
    
    log.info("=" * 60)
    log.info("Bluetooth Classic SPP Relay Starting")
    log.info("=" * 60)
    
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

