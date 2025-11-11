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
real_ser = None
monitor_ser = None
socat_process = None

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

def relay_hw_to_virtual(real_ser, monitor_ser):
    """Relay data from hardware to virtual port (RX from board)"""
    global running
    while running:
        try:
            data = real_ser.read(1000)
            if data:
                log_message("HW->CENTAUR", data)
                monitor_ser.write(data)
                monitor_ser.flush()
            time.sleep(0.001)
        except serial.SerialTimeoutException:
            time.sleep(0.001)
        except Exception as e:
            if running:
                print(f"Error in HW->CENTAUR relay: {e}")
            break

def relay_virtual_to_hw(real_ser, monitor_ser):
    """Relay data from virtual port to hardware (TX from centaur)"""
    global running
    while running:
        try:
            data = monitor_ser.read(1000)
            if data:
                log_message("CENTAUR->HW", data)
                real_ser.write(data)
                real_ser.flush()
            time.sleep(0.001)
        except serial.SerialTimeoutException:
            time.sleep(0.001)
        except Exception as e:
            if running:
                print(f"Error in CENTAUR->HW relay: {e}")
            break

def setup_virtual_serial():
    """Create virtual serial port pair using socat"""
    global socat_process
    # Kill any existing socat processes for our virtual port
    os.system("pkill -f 'socat.*centaur_serial' 2>/dev/null")
    time.sleep(0.5)
    
    # Create a virtual serial port pair using socat
    # One end (centaur_port) is for centaur, the other end (monitor_port) is for us to read
    monitor_port_link = "/tmp/monitor_port"
    cmd = f"socat -d -d pty,raw,echo=0,link={VIRTUAL_PORT_FOR_CENTAUR} pty,raw,echo=0,link={monitor_port_link}"
    socat_process = subprocess.Popen(
        cmd.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)  # Wait for socat to create the ports
    
    # Verify ports exist
    if not os.path.exists(VIRTUAL_PORT_FOR_CENTAUR):
        print(f"ERROR: Failed to create virtual port {VIRTUAL_PORT_FOR_CENTAUR}")
        return None, None
    
    if not os.path.exists(monitor_port_link):
        print(f"ERROR: Failed to create monitor port {monitor_port_link}")
        return None, None
    
    return VIRTUAL_PORT_FOR_CENTAUR, monitor_port_link

def replace_serial0():
    """Replace /dev/serial0 with symlink to virtual port"""
    try:
        # Remove existing /dev/serial0
        os.system("sudo rm -f /dev/serial0")
        
        # Create symlink from /dev/serial0 to virtual port
        result = os.system(f"sudo ln -sf {VIRTUAL_PORT_FOR_CENTAUR} /dev/serial0")
        if result != 0:
            print(f"Warning: Failed to create symlink (result={result})")
        
        # Verify it was created
        if os.path.exists("/dev/serial0") and os.path.islink("/dev/serial0"):
            actual_target = os.readlink("/dev/serial0")
            if actual_target == VIRTUAL_PORT_FOR_CENTAUR:
                return True
            else:
                print(f"WARNING: symlink points to {actual_target}, expected {VIRTUAL_PORT_FOR_CENTAUR}")
                return False
        else:
            print("ERROR: symlink was not created or is not a symlink")
            return False
    except Exception as e:
        print(f"Error setting up serial0 symlink: {e}")
        return False

def restore_serial0():
    """Restore /dev/serial0 to point to /dev/ttyAMA0 (the correct default)"""
    try:
        # Remove existing /dev/serial0
        os.system("sudo rm -f /dev/serial0")
        
        # Create symlink to ttyAMA0 (the correct default)
        result = os.system("sudo ln -sf /dev/ttyAMA0 /dev/serial0")
        if result == 0:
            print("Restored /dev/serial0 -> /dev/ttyAMA0")
            return True
        else:
            print("Warning: Failed to restore /dev/serial0")
            return False
    except Exception as e:
        print(f"Error restoring serial0: {e}")
        # Last resort: try again
        try:
            os.system("sudo ln -sf /dev/ttyAMA0 /dev/serial0")
        except:
            pass
        return False

def cleanup():
    """Clean up all resources"""
    global running, centaur_process, real_ser, monitor_ser, socat_process
    
    # Kill centaur FIRST, before setting running=False or doing anything else
    # This must happen immediately to prevent reboot
    # Use synchronous kill first for immediate effect
    os.system("sudo pkill -9 -f './centaur' >/dev/null 2>&1")
    os.system("sudo pkill -9 centaur >/dev/null 2>&1")
    
    # Also kill asynchronously as backup
    devnull = open(os.devnull, 'w')
    subprocess.Popen(["sudo", "pkill", "-9", "-f", "./centaur"], 
                     stdout=devnull, 
                     stderr=devnull)
    subprocess.Popen(["sudo", "pkill", "-9", "centaur"], 
                     stdout=devnull, 
                     stderr=devnull)
    
    running = False
    
    # Also kill the subprocess we started (sudo process)
    if centaur_process:
        try:
            # Try to kill the process group first
            try:
                pgid = os.getpgid(centaur_process.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError, AttributeError):
                # Process group might not exist, try killing the process directly
                try:
                    centaur_process.kill()
                except:
                    pass
        except Exception as e:
            # Fallback: try to kill the process directly
            try:
                centaur_process.kill()
            except:
                pass
    
    # Close serial ports
    if real_ser and real_ser.is_open:
        try:
            real_ser.close()
        except:
            pass
    
    if monitor_ser and monitor_ser.is_open:
        try:
            monitor_ser.close()
        except:
            pass
    
    # Kill socat process
    if socat_process:
        try:
            socat_process.terminate()
            try:
                socat_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                socat_process.kill()
        except:
            pass
    
    # Also kill any remaining socat processes
    os.system("pkill -f 'socat.*centaur_serial' 2>/dev/null")
    
    # Restore serial0
    restore_serial0()

def signal_handler(sig, frame):
    """Handle shutdown signals - kill centaur immediately to prevent reboot"""
    # Kill centaur IMMEDIATELY before anything else
    # Don't even print - just kill it
    os.system("sudo pkill -9 -f './centaur' >/dev/null 2>&1")
    os.system("sudo pkill -9 centaur >/dev/null 2>&1")
    
    print("\nShutting down...")
    cleanup()
    sys.exit(0)

def main():
    global running, centaur_process, real_ser, monitor_ser
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("=" * 60)
    print("Centaur Serial Port Monitor")
    print("=" * 60)
    print(f"Log file: {MONITOR_LOG_FILE}")
    print()
    
    # Setup virtual serial port pair
    print("Setting up virtual serial ports...")
    centaur_port, monitor_port = setup_virtual_serial()
    if not centaur_port or not monitor_port:
        print("Failed to create virtual serial ports")
        return 1
    
    print(f"Virtual port for centaur: {centaur_port}")
    print(f"Monitor port: {monitor_port}")
    
    # Replace /dev/serial0 with symlink to virtual port
    print("\nSetting up /dev/serial0 redirection...")
    if not replace_serial0():
        print("Failed to set up /dev/serial0 redirection")
        cleanup()
        return 1
    
    # Open serial ports
    print("\nOpening serial ports...")
    try:
        # Hardware port - read/write
        real_ser = serial.Serial(REAL_SERIAL_PORT, baudrate=1000000, timeout=0.1)
        print(f"Opened {REAL_SERIAL_PORT} (hardware)")
        
        # Monitor port - open via symlink (FIXED: use symlink, not resolved path)
        # When we write to monitor_port, socat forwards it to centaur_port (where centaur reads)
        # When centaur writes to centaur_port, socat forwards it to monitor_port (where we read)
        monitor_ser = serial.Serial(monitor_port, baudrate=1000000, timeout=0.1, write_timeout=0.1)
        print(f"Opened {monitor_port} (monitor - we read/write here)")
        print(f"{centaur_port} is used by centaur via /dev/serial0 (we don't open it)")
        
    except Exception as e:
        print(f"Failed to open serial ports: {e}")
        import traceback
        traceback.print_exc()
        cleanup()
        return 1
    
    # Start relay threads
    print("\nStarting relay threads...")
    thread1 = threading.Thread(target=relay_hw_to_virtual, args=(real_ser, monitor_ser), daemon=True)
    thread2 = threading.Thread(target=relay_virtual_to_hw, args=(real_ser, monitor_ser), daemon=True)
    thread1.start()
    thread2.start()
    
    print("Relay active. Monitoring serial traffic...")
    print("=" * 60)
    print()
    
    # Start centaur executable
    print("Starting centaur executable...")
    os.chdir("/home/pi/centaur")
    # Start in a new session so it doesn't receive terminal signals (like Ctrl+C)
    # This prevents centaur from getting SIGINT when we press Ctrl+C
    try:
        # Python 3.8+ supports start_new_session parameter
        centaur_process = subprocess.Popen(["sudo", "./centaur"], 
                                           stdout=subprocess.PIPE, 
                                           stderr=subprocess.PIPE,
                                           start_new_session=True)
    except TypeError:
        # Fallback for older Python versions
        centaur_process = subprocess.Popen(["sudo", "./centaur"], 
                                           stdout=subprocess.PIPE, 
                                           stderr=subprocess.PIPE,
                                           preexec_fn=os.setsid)
    
    # Monitor until centaur exits or we get a signal
    try:
        while running:
            if centaur_process.poll() is not None:
                print(f"\nCentaur process exited with code {centaur_process.poll()}")
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
    
    # Cleanup
    cleanup()
    
    print("\nMonitor stopped.")
    return 0

if __name__ == "__main__":
    sys.exit(main())


