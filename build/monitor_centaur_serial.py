#!/usr/bin/env python3
"""
Serial port relay with live monitoring for centaur executable.
This script creates a virtual serial port, relays traffic between
the real hardware and centaur, and logs all messages in real-time.
"""

import serial
import threading
import time
import os
import sys
import subprocess
import signal
from datetime import datetime

# Configuration
REAL_SERIAL_PORT = "/dev/ttyS0"  # The actual hardware port
VIRTUAL_PORT_FOR_CENTAUR = "/tmp/centaur_serial"
MONITOR_LOG_FILE = "/tmp/centaur_serial_monitor.log"

# Global flag for clean shutdown
running = True
centaur_process = None

def format_hex(data):
    """Format bytes as hex string"""
    return ' '.join(f'{b:02x}' for b in data)

def log_message(direction, data, timestamp=None):
    """Log a serial message with timestamp"""
    if timestamp is None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    hex_str = format_hex(data)
    log_line = f"[{timestamp}] {direction}: {hex_str}\n"
    
    # Print to console
    print(log_line.strip())
    
    # Write to log file
    try:
        with open(MONITOR_LOG_FILE, 'a') as f:
            f.write(log_line)
            f.flush()
    except Exception as e:
        print(f"Log write error: {e}")

def relay_hw_to_virtual(real_ser, virtual_ser):
    """Relay data from hardware to virtual port (RX from board)"""
    global running
    while running:
        try:
            data = real_ser.read(1000)
            if data:
                log_message("HW->CENTAUR", data)
                virtual_ser.write(data)
                virtual_ser.flush()
            time.sleep(0.001)  # Small delay to prevent CPU spinning
        except Exception as e:
            if running:
                print(f"Error in HW->CENTAUR relay: {e}")
            break

def relay_virtual_to_hw(real_ser, virtual_ser):
    """Relay data from virtual port to hardware (TX from centaur)"""
    global running
    while running:
        try:
            data = virtual_ser.read(1000)
            if data:
                log_message("CENTAUR->HW", data)
                real_ser.write(data)
                real_ser.flush()
            time.sleep(0.001)
        except Exception as e:
            if running:
                print(f"Error in CENTAUR->HW relay: {e}")
            break

def setup_virtual_serial():
    """Create virtual serial port pair using socat"""
    # Kill any existing socat processes for our virtual port
    os.system("pkill -f 'socat.*centaur_serial' 2>/dev/null")
    time.sleep(0.5)
    
    # Create virtual serial port pair
    # One end will be for centaur, we'll monitor the other end
    cmd = f"socat -d -d pty,raw,echo=0,link={VIRTUAL_PORT_FOR_CENTAUR} pty,raw,echo=0,link=/tmp/monitor_port &"
    os.system(cmd)
    time.sleep(2)  # Wait for socat to create the ports
    
    # Verify ports exist
    if not os.path.exists(VIRTUAL_PORT_FOR_CENTAUR):
        print(f"ERROR: Failed to create virtual port {VIRTUAL_PORT_FOR_CENTAUR}")
        return None, None
    
    if not os.path.exists("/tmp/monitor_port"):
        print("ERROR: Failed to create monitor port")
        return None, None
    
    return VIRTUAL_PORT_FOR_CENTAUR, "/tmp/monitor_port"

def backup_and_replace_serial0():
    """Backup /dev/serial0 and create symlink to virtual port"""
    try:
        # Check if /dev/serial0 exists and is a symlink
        if os.path.islink("/dev/serial0"):
            # Backup the original target
            original_target = os.readlink("/dev/serial0")
            os.system(f"sudo mv /dev/serial0 /dev/serial0.backup")
            print(f"Backed up /dev/serial0 (was -> {original_target})")
        elif os.path.exists("/dev/serial0"):
            # It's a real device, move it
            os.system("sudo mv /dev/serial0 /dev/serial0.backup")
            print("Backed up /dev/serial0")
        
        # Create symlink from /dev/serial0 to virtual port
        os.system(f"sudo ln -s {VIRTUAL_PORT_FOR_CENTAUR} /dev/serial0")
        print(f"Created symlink /dev/serial0 -> {VIRTUAL_PORT_FOR_CENTAUR}")
        return True
    except Exception as e:
        print(f"Error setting up serial0 symlink: {e}")
        return False

def restore_serial0():
    """Restore original /dev/serial0"""
    try:
        if os.path.exists("/dev/serial0.backup"):
            os.system("sudo rm /dev/serial0")
            os.system("sudo mv /dev/serial0.backup /dev/serial0")
            print("Restored /dev/serial0")
        return True
    except Exception as e:
        print(f"Error restoring serial0: {e}")
        return False

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    global running, centaur_process
    print("\nShutting down...")
    running = False
    if centaur_process:
        try:
            centaur_process.terminate()
            centaur_process.wait(timeout=5)
        except:
            centaur_process.kill()
    restore_serial0()
    os.system("pkill -f 'socat.*centaur_serial' 2>/dev/null")
    sys.exit(0)

def main():
    global running, centaur_process
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("=" * 60)
    print("Centaur Serial Port Monitor")
    print("=" * 60)
    print(f"Log file: {MONITOR_LOG_FILE}")
    print()
    
    # Setup virtual serial ports
    print("Setting up virtual serial ports...")
    centaur_port, monitor_port = setup_virtual_serial()
    if not centaur_port or not monitor_port:
        print("Failed to create virtual serial ports")
        return 1
    
    print(f"Virtual port for centaur: {centaur_port}")
    print(f"Monitor port: {monitor_port}")
    
    # Backup and replace /dev/serial0
    print("\nSetting up /dev/serial0 redirection...")
    if not backup_and_replace_serial0():
        print("Failed to set up /dev/serial0 redirection")
        return 1
    
    # Open serial ports
    print("\nOpening serial ports...")
    try:
        real_ser = serial.Serial(REAL_SERIAL_PORT, baudrate=1000000, timeout=0.2)
        virtual_ser = serial.Serial(centaur_port, baudrate=1000000, timeout=0.2)
        print(f"Opened {REAL_SERIAL_PORT} (hardware)")
        print(f"Opened {centaur_port} (virtual, for centaur)")
    except Exception as e:
        print(f"Failed to open serial ports: {e}")
        restore_serial0()
        return 1
    
    # Start relay threads
    print("\nStarting relay threads...")
    thread1 = threading.Thread(target=relay_hw_to_virtual, args=(real_ser, virtual_ser), daemon=True)
    thread2 = threading.Thread(target=relay_virtual_to_hw, args=(real_ser, virtual_ser), daemon=True)
    thread1.start()
    thread2.start()
    
    print("Relay active. Monitoring serial traffic...")
    print("=" * 60)
    print()
    
    # Start centaur executable
    print("Starting centaur executable...")
    os.chdir("/home/pi/centaur")
    centaur_process = subprocess.Popen(["sudo", "./centaur"], 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE)
    
    # Monitor until centaur exits or we get a signal
    try:
        while running:
            if centaur_process.poll() is not None:
                print("\nCentaur process exited")
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    
    # Cleanup
    running = False
    if centaur_process:
        try:
            centaur_process.terminate()
            centaur_process.wait(timeout=5)
        except:
            centaur_process.kill()
    
    restore_serial0()
    os.system("pkill -f 'socat.*centaur_serial' 2>/dev/null")
    
    print("\nMonitor stopped.")
    return 0

if __name__ == "__main__":
    sys.exit(main())

