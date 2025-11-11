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
REAL_SERIAL_PORT = "/dev/ttyAMA0"  # The actual hardware port (NOT serial0 - that's for centaur!)
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
    print("[DEBUG] relay_hw_to_virtual thread STARTED")
    print(f"[DEBUG] relay_hw_to_virtual: Writing to monitor_ser (monitor port) so it appears on centaur_port")
    loop_count = 0
    while running:
        try:
            loop_count += 1
            if loop_count % 1000 == 0:
                print(f"[DEBUG] relay_hw_to_virtual: loop {loop_count}, in_waiting={real_ser.in_waiting}, running={running}")
            
            # Try reading directly - don't rely on in_waiting
            data = real_ser.read(1000)  # Read up to 1000 bytes
            if data:
                print(f"[DEBUG] relay_hw_to_virtual: *** GOT DATA! Read {len(data)} bytes from hardware")
                log_message("HW->CENTAUR", data)
                # Write to monitor port - socat will forward it to centaur_port where centaur can read it
                bytes_written = monitor_ser.write(data)
                monitor_ser.flush()
                print(f"[DEBUG] relay_hw_to_virtual: Wrote {bytes_written} bytes to monitor port (will appear on centaur_port)")
            else:
                # No data available, small delay to prevent CPU spinning
                time.sleep(0.001)
        except serial.SerialTimeoutException:
            # Timeout is normal when no data is available
            time.sleep(0.001)
        except Exception as e:
            if running:
                print(f"[DEBUG] ERROR in HW->CENTAUR relay: {e}")
                import traceback
                traceback.print_exc()
            break
    print("[DEBUG] relay_hw_to_virtual thread EXITED")

def relay_virtual_to_hw(real_ser, monitor_ser):
    """Relay data from virtual port to hardware (TX from centaur)"""
    global running
    print("[DEBUG] relay_virtual_to_hw thread STARTED")
    print(f"[DEBUG] relay_virtual_to_hw: Reading from monitor_ser to see what centaur writes to centaur_port")
    loop_count = 0
    # Read from monitor_ser to see what centaur writes
    # When centaur writes to centaur_port (/dev/serial0 -> /tmp/centaur_serial -> /dev/pts/1),
    # it appears on monitor_port (/tmp/monitor_port -> /dev/pts/2) via socat
    while running:
        try:
            loop_count += 1
            if loop_count % 1000 == 0:
                in_waiting = monitor_ser.in_waiting if monitor_ser else 0
                print(f"[DEBUG] relay_virtual_to_hw: loop {loop_count}, in_waiting={in_waiting}, running={running}")
            
            # Try reading directly - don't rely on in_waiting for PTYs
            # Read with timeout - will return empty bytes if nothing available
            data = monitor_ser.read(1000)  # Read up to 1000 bytes
            if data:
                print(f"[DEBUG] relay_virtual_to_hw: *** GOT DATA! Read {len(data)} bytes from monitor port: {data.hex()}")
                print(f"[DEBUG] CENTAUR->HW RAW: {data}")
                log_message("CENTAUR->HW", data)
                # Write to hardware
                bytes_written = real_ser.write(data)
                real_ser.flush()
                print(f"[DEBUG] relay_virtual_to_hw: Wrote {bytes_written} bytes to hardware")
            else:
                # No data available, small delay to prevent CPU spinning
                time.sleep(0.001)
        except serial.SerialTimeoutException:
            # Timeout is normal when no data is available
            time.sleep(0.001)
        except Exception as e:
            if running:
                print(f"[DEBUG] ERROR in CENTAUR->HW relay: {e}")
                import traceback
                traceback.print_exc()
            break
    print("[DEBUG] relay_virtual_to_hw thread EXITED")

def setup_virtual_serial():
    """Create virtual serial port pair using socat"""
    global socat_process
    print("[DEBUG] setup_virtual_serial: STARTING")
    # Kill any existing socat processes for our virtual port
    print("[DEBUG] setup_virtual_serial: Killing existing socat processes")
    os.system("pkill -f 'socat.*centaur_serial' 2>/dev/null")
    time.sleep(0.5)
    
    # Create a virtual serial port pair using socat
    # One end (centaur_port) is for centaur, the other end (monitor_port) is for us to read
    monitor_port_link = "/tmp/monitor_port"
    cmd = f"socat -d -d pty,raw,echo=0,link={VIRTUAL_PORT_FOR_CENTAUR} pty,raw,echo=0,link={monitor_port_link}"
    print(f"[DEBUG] setup_virtual_serial: Running command: {cmd}")
    socat_process = subprocess.Popen(
        cmd.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    print(f"[DEBUG] setup_virtual_serial: socat process started, PID={socat_process.pid}")
    time.sleep(2)  # Wait for socat to create the ports
    print(f"[DEBUG] setup_virtual_serial: Waited 2 seconds, checking ports...")
    
    # Verify ports exist
    if not os.path.exists(VIRTUAL_PORT_FOR_CENTAUR):
        print(f"[DEBUG] ERROR: Failed to create virtual port {VIRTUAL_PORT_FOR_CENTAUR}")
        print(f"[DEBUG] Checking if it exists: {os.path.exists(VIRTUAL_PORT_FOR_CENTAUR)}")
        return None, None
    else:
        print(f"[DEBUG] setup_virtual_serial: Virtual port exists: {VIRTUAL_PORT_FOR_CENTAUR}")
        # Check what it points to
        if os.path.islink(VIRTUAL_PORT_FOR_CENTAUR):
            print(f"[DEBUG] setup_virtual_serial: {VIRTUAL_PORT_FOR_CENTAUR} -> {os.readlink(VIRTUAL_PORT_FOR_CENTAUR)}")
    
    if not os.path.exists(monitor_port_link):
        print(f"[DEBUG] ERROR: Failed to create monitor port {monitor_port_link}")
        print(f"[DEBUG] Checking if it exists: {os.path.exists(monitor_port_link)}")
        return None, None
    else:
        print(f"[DEBUG] setup_virtual_serial: Monitor port exists: {monitor_port_link}")
        # Check what it points to
        if os.path.islink(monitor_port_link):
            print(f"[DEBUG] setup_virtual_serial: {monitor_port_link} -> {os.readlink(monitor_port_link)}")
    
    print(f"[DEBUG] setup_virtual_serial: SUCCESS, returning ({VIRTUAL_PORT_FOR_CENTAUR}, {monitor_port_link})")
    return VIRTUAL_PORT_FOR_CENTAUR, monitor_port_link

def replace_serial0():
    """Replace /dev/serial0 with symlink to virtual port"""
    print("[DEBUG] replace_serial0: CALLED")
    try:
        # Check current state
        if os.path.exists("/dev/serial0"):
            if os.path.islink("/dev/serial0"):
                current_target = os.readlink("/dev/serial0")
                print(f"[DEBUG] replace_serial0: Current /dev/serial0 -> {current_target}")
            else:
                print(f"[DEBUG] replace_serial0: Current /dev/serial0 is not a symlink")
        else:
            print(f"[DEBUG] replace_serial0: /dev/serial0 does not exist")
        
        # Remove existing /dev/serial0 (whether it's a symlink, file, or doesn't exist)
        print(f"[DEBUG] replace_serial0: Removing /dev/serial0")
        result = os.system("sudo rm -f /dev/serial0")
        print(f"[DEBUG] replace_serial0: rm result={result}")
        
        # Create symlink from /dev/serial0 to virtual port
        print(f"[DEBUG] replace_serial0: Creating symlink /dev/serial0 -> {VIRTUAL_PORT_FOR_CENTAUR}")
        result = os.system(f"sudo ln -sf {VIRTUAL_PORT_FOR_CENTAUR} /dev/serial0")
        print(f"[DEBUG] replace_serial0: ln result={result}")
        
        # Verify it was created
        if os.path.exists("/dev/serial0") and os.path.islink("/dev/serial0"):
            actual_target = os.readlink("/dev/serial0")
            print(f"[DEBUG] replace_serial0: Verified /dev/serial0 -> {actual_target}")
            if actual_target == VIRTUAL_PORT_FOR_CENTAUR:
                print(f"[DEBUG] replace_serial0: SUCCESS - symlink points to correct target")
                return True
            else:
                print(f"[DEBUG] replace_serial0: WARNING - symlink points to {actual_target}, expected {VIRTUAL_PORT_FOR_CENTAUR}")
                return False
        else:
            print(f"[DEBUG] replace_serial0: ERROR - symlink was not created or is not a symlink")
            return False
    except Exception as e:
        print(f"[DEBUG] replace_serial0: EXCEPTION - {e}")
        import traceback
        traceback.print_exc()
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
    print("Centaur Serial Port Monitor 2")
    print("=" * 60)
    print(f"Log file: {MONITOR_LOG_FILE}")
    print()
    
    # Setup virtual serial port pair
    print("[DEBUG] main: Setting up virtual serial ports...")
    centaur_port, monitor_port = setup_virtual_serial()
    if not centaur_port or not monitor_port:
        print("[DEBUG] main: FAILED to create virtual serial ports")
        return 1
    
    print(f"[DEBUG] main: Virtual port for centaur: {centaur_port}")
    print(f"[DEBUG] main: Monitor port: {monitor_port}")
    
    # Replace /dev/serial0 with symlink to virtual port
    print("\n[DEBUG] main: Setting up /dev/serial0 redirection...")
    if not replace_serial0():
        print("[DEBUG] main: FAILED to set up /dev/serial0 redirection")
        cleanup()
        return 1
    print("[DEBUG] main: /dev/serial0 redirection SUCCESS")
    
    # Open serial ports
    print("\n[DEBUG] main: Opening serial ports...")
    print(f"[DEBUG] main: NOTE - We do NOT open {centaur_port} - centaur uses it directly via /dev/serial0")
    try:
        print(f"[DEBUG] main: Opening {REAL_SERIAL_PORT} (hardware)")
        # Hardware port - read/write
        real_ser = serial.Serial(REAL_SERIAL_PORT, baudrate=1000000, timeout=0.1)
        print(f"[DEBUG] main: Opened {REAL_SERIAL_PORT}, is_open={real_ser.is_open}")
        
        print(f"[DEBUG] main: Opening {monitor_port} (monitor - we read AND write here)")
        print(f"[DEBUG] main:   - Read from here to see what centaur writes (CENTAUR->HW)")
        print(f"[DEBUG] main:   - Write to here to send data to centaur (HW->CENTAUR)")
        # Monitor port - we read from and write to this
        # When we write to monitor_port, socat forwards it to centaur_port (where centaur reads)
        # When centaur writes to centaur_port, socat forwards it to monitor_port (where we read)
        # Get the actual PTY device path (not the symlink) to open directly
        actual_monitor_pty = os.readlink(monitor_port) if os.path.islink(monitor_port) else monitor_port
        print(f"[DEBUG] main: Opening actual PTY device: {actual_monitor_pty} (via symlink {monitor_port})")
        monitor_ser = serial.Serial(actual_monitor_pty, baudrate=1000000, timeout=0.1, write_timeout=0.1)
        print(f"[DEBUG] main: Opened {actual_monitor_pty}, is_open={monitor_ser.is_open}, port={monitor_ser.port}")
        
        print(f"[DEBUG] main: All ports opened successfully")
        print(f"Opened {REAL_SERIAL_PORT} (hardware)")
        print(f"{centaur_port} is used by centaur via /dev/serial0 (we don't open it)")
        print(f"Opened {monitor_port} (monitor - we read/write here)")
        
        # Get actual device paths
        actual_centaur_pty = os.readlink(centaur_port) if os.path.islink(centaur_port) else centaur_port
        actual_monitor_pty = os.readlink(monitor_port) if os.path.islink(monitor_port) else monitor_port
        print(f"[DEBUG] main: Actual PTY devices:")
        print(f"[DEBUG] main:   centaur uses: {actual_centaur_pty}")
        print(f"[DEBUG] main:   we read from: {actual_monitor_pty}")
        print(f"[DEBUG] main:   socat connects: {actual_centaur_pty} <-> {actual_monitor_pty}")
        
        # Test socat connection - write a test byte and see if we can verify the connection
        print(f"[DEBUG] main: Testing socat connection...")
        test_data = b'\xAA'
        monitor_ser.write(test_data)
        monitor_ser.flush()
        print(f"[DEBUG] main: Wrote test byte 0xAA to monitor_port ({actual_monitor_pty}), should appear on centaur_port ({actual_centaur_pty})")
        time.sleep(0.1)
        # Check if socat process is still running
        if socat_process and socat_process.poll() is None:
            print(f"[DEBUG] main: socat process is running (PID={socat_process.pid})")
        else:
            print(f"[DEBUG] main: WARNING - socat process is not running!")
        
        # Verify /dev/serial0 points to the right place
        if os.path.islink("/dev/serial0"):
            serial0_target = os.readlink("/dev/serial0")
            print(f"[DEBUG] main: /dev/serial0 -> {serial0_target}")
            if serial0_target != centaur_port:
                print(f"[DEBUG] main: WARNING - /dev/serial0 points to {serial0_target}, expected {centaur_port}")
    except Exception as e:
        print(f"[DEBUG] main: EXCEPTION opening serial ports: {e}")
        import traceback
        traceback.print_exc()
        cleanup()
        return 1
    
    # Start relay threads
    print("\n[DEBUG] main: Starting relay threads...")
    thread1 = threading.Thread(target=relay_hw_to_virtual, args=(real_ser, monitor_ser), daemon=True)
    thread2 = threading.Thread(target=relay_virtual_to_hw, args=(real_ser, monitor_ser), daemon=True)
    print(f"[DEBUG] main: Created thread1={thread1}, thread2={thread2}")
    thread1.start()
    print(f"[DEBUG] main: Started thread1, is_alive={thread1.is_alive()}")
    thread2.start()
    print(f"[DEBUG] main: Started thread2, is_alive={thread2.is_alive()}")
    
    print("[DEBUG] main: Both threads started, waiting a moment...")
    time.sleep(0.5)
    print(f"[DEBUG] main: After 0.5s - thread1.is_alive={thread1.is_alive()}, thread2.is_alive={thread2.is_alive()}")
    
    print("Relay active. Monitoring serial traffic...")
    print("=" * 60)
    print()
    
    # Start centaur executable
    print("[DEBUG] main: Starting centaur executable...")
    os.chdir("/home/pi/centaur")
    print(f"[DEBUG] main: Changed to directory: {os.getcwd()}")
    # Start in a new session so it doesn't receive terminal signals (like Ctrl+C)
    # This prevents centaur from getting SIGINT when we press Ctrl+C
    try:
        # Python 3.8+ supports start_new_session parameter
        print("[DEBUG] main: Starting centaur with start_new_session=True")
        centaur_process = subprocess.Popen(["sudo", "./centaur"], 
                                           stdout=subprocess.PIPE, 
                                           stderr=subprocess.PIPE,
                                           start_new_session=True)
        print(f"[DEBUG] main: Centaur process started, PID={centaur_process.pid}")
    except TypeError:
        # Fallback for older Python versions
        print("[DEBUG] main: Using preexec_fn=os.setsid (older Python)")
        centaur_process = subprocess.Popen(["sudo", "./centaur"], 
                                           stdout=subprocess.PIPE, 
                                           stderr=subprocess.PIPE,
                                           preexec_fn=os.setsid)
        print(f"[DEBUG] main: Centaur process started, PID={centaur_process.pid}")
    
    print("[DEBUG] main: Entering main monitoring loop")
    # Monitor until centaur exits or we get a signal
    try:
        loop_count = 0
        while running:
            loop_count += 1
            if loop_count % 100 == 0:
                print(f"[DEBUG] main: Monitoring loop {loop_count}, centaur.poll()={centaur_process.poll()}, running={running}")
                print(f"[DEBUG] main: Thread status - thread1.is_alive={thread1.is_alive()}, thread2.is_alive={thread2.is_alive()}")
                # Don't check in_waiting on ttyAMA0 - it may not support that ioctl
                try:
                    if monitor_ser:
                        print(f"[DEBUG] main: monitor_ser.in_waiting={monitor_ser.in_waiting}")
                except:
                    pass
            if centaur_process.poll() is not None:
                print(f"\n[DEBUG] main: Centaur process exited with code {centaur_process.poll()}")
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        # This should trigger the signal handler, but ensure cleanup
        signal_handler(signal.SIGINT, None)
    
    # Cleanup
    cleanup()
    
    print("\nMonitor stopped.")
    return 0

if __name__ == "__main__":
    sys.exit(main())


