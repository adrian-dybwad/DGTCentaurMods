#!/usr/bin/env python3
"""
Serial port proxy using PTY and threading.

Proxies /dev/ttyS0 through a PTY to /dev/ttyS0.real, allowing monitoring
and interception of serial traffic.

Useful to monitor traffic to and from the real centaur software.

Example:
1) In one ssh session, start this script:
    cd ~/DGTCentaurMods/tools/dev-tools/proxies
    python centaur.py
2) In another ssh session, start the real centaur software:
    cd ~/centaur # or wherever the centaur binary is
    ./centaur
3) Monitor the traffic logs in the ssh proxy session as you play the game.

4) To stop the proxy, press Ctrl-C in the ssh proxy session. This will restore the serial ports.

5) To stop the centaur software, you need to kill the process or it will instead shutdown the pi.
To do this, use the kill command in a separate ssh session as follows:
    sudo pkill centaur



NOTE: If the ttyS0 port is not restored correctly on exiting this proxy script, 
running the centaur software on its own will not work and you may also have 
trouble using any Centaur Mods as well.

To restore the ttyS0 port, do the following:
    a) See if a port exists with the name /dev/ttyS0.real:
        ls -l /dev/ttyS0*
    b) If, and only if the /dev/ttyS0.real port exists, remove the ttyS0 symlink with:
        sudo rm -f /dev/ttyS0
    c) Restore the real device with:
        sudo mv /dev/ttyS0.real /dev/ttyS0
"""

import os
import sys
import subprocess
import signal
import time
import threading
import pty
import fcntl
import serial
from datetime import datetime

# Prefer repo's opt path
try:
    REPO_OPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'DGTCentaurMods', 'opt'))
    if REPO_OPT not in sys.path:
        sys.path.insert(0, REPO_OPT)
except Exception:
    pass

DEV = "/dev/ttyS0"
REAL = f"{DEV}.real"
keep_running = True
master_fd = None
slave_fd = None
real_ser = None


def run_command(cmd, ignore_errors=False, capture_output=False):
    """
    Run a shell command.
    
    Args:
        cmd: Command to run (list or string)
        ignore_errors: If True, ignore non-zero exit codes
        capture_output: If True, capture and return stdout/stderr
    
    Returns:
        subprocess.CompletedProcess or None
    """
    try:
        if isinstance(cmd, str):
            cmd = cmd.split()
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            check=not ignore_errors
        )
        return result
    except subprocess.CalledProcessError as e:
        if not ignore_errors:
            raise
        return None
    except Exception as e:
        if not ignore_errors:
            print(f"Error running command {cmd}: {e}", file=sys.stderr)
            raise
        return None


def format_hex(data):
    """Format bytes as hex string."""
    return ' '.join(f'{b:02x}' for b in data)


def log_message(direction, data, timestamp=None):
    """Log a serial message with timestamp."""
    if timestamp is None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    hex_str = format_hex(data)
    log_line = f"[{timestamp}] {direction}: {hex_str}"
    print(log_line)


def relay_pty_to_real(master_fd, real_ser):
    """Relay data from PTY master to real device (client -> hardware)."""
    global keep_running
    while keep_running:
        try:
            # Read from PTY master file descriptor
            data = os.read(master_fd, 4096)
            if data:
                log_message("CLIENT->REAL", data)
                real_ser.write(data)
                real_ser.flush()
            time.sleep(0.001)  # Small delay to prevent CPU spinning
        except BlockingIOError:
            # No data available, continue
            time.sleep(0.001)
            continue
        except OSError as e:
            # EOF or connection closed
            if keep_running and e.errno != 5:  # Ignore "Input/output error" on close
                print(f"Error in CLIENT->REAL relay: {e}", file=sys.stderr)
            break
        except Exception as e:
            if keep_running:
                print(f"Error in CLIENT->REAL relay: {e}", file=sys.stderr)
            break


def relay_real_to_pty(master_fd, real_ser):
    """Relay data from real device to PTY master (hardware -> client)."""
    global keep_running
    while keep_running:
        try:
            data = real_ser.read(1000)
            if data:
                log_message("REAL->CLIENT", data)
                os.write(master_fd, data)
            time.sleep(0.001)
        except Exception as e:
            if keep_running:
                print(f"Error in REAL->CLIENT relay: {e}", file=sys.stderr)
            break


def cleanup():
    """Cleanup function to restore device on exit."""
    global keep_running, real_ser, master_fd, slave_fd
    keep_running = False
    
    # Close serial connection
    if real_ser is not None:
        try:
            real_ser.close()
        except Exception:
            pass
    
    # Close file descriptors
    if master_fd is not None:
        try:
            os.close(master_fd)
        except Exception:
            pass
    
    if slave_fd is not None:
        try:
            os.close(slave_fd)
        except Exception:
            pass
    
    # Remove symlink if it exists
    if os.path.islink(DEV):
        run_command(["sudo", "rm", "-f", DEV], ignore_errors=True)
    
    # Restore real device if it exists
    if os.path.exists(REAL):
        run_command(["sudo", "mv", REAL, DEV], ignore_errors=True)


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print("\nShutting down...", file=sys.stderr)
    cleanup()
    sys.exit(0)


def main():
    """Main function."""
    global keep_running
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Stop getty (ignore errors if already stopped)
    dev_basename = os.path.basename(DEV)
    service_name = f"serial-getty@{dev_basename}.service"
    run_command(["sudo", "systemctl", "stop", service_name], ignore_errors=True)
    
    # Kill any processes using the device
    run_command(["sudo", "fuser", "-k", DEV], ignore_errors=True)
    run_command(["sudo", "fuser", "-k", REAL], ignore_errors=True)
    time.sleep(0.5)
    
    # If the "real" device doesn't exist yet, move the real one aside
    if not os.path.exists(REAL):
        result = run_command(["sudo", "mv", DEV, REAL], ignore_errors=False)
        if result is None or result.returncode != 0:
            print(f"Error moving {DEV} to {REAL}", file=sys.stderr)
            sys.exit(1)
    
    # Ensure the real device is ready and not locked
    run_command(["sudo", "chmod", "666", REAL], ignore_errors=True)
    
    # Set baud rate explicitly to 1000000 (device requirement)
    run_command(["sudo", "stty", "-F", REAL, "1000000"], ignore_errors=True)
    
    global master_fd, slave_fd, real_ser
    
    try:
        # Create PTY pair
        master_fd, slave_fd = pty.openpty()
        slave_name = os.ttyname(slave_fd)
        print(f"Created PTY: master_fd={master_fd}, slave={slave_name}")
        
        # Set master to non-blocking mode
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        # Create symlink from /dev/ttyS0 to slave PTY
        run_command(["sudo", "ln", "-sf", slave_name, DEV], ignore_errors=False)
        print(f"Symlinked {DEV} -> {slave_name}")
        
        # Set permissions on slave PTY
        run_command(["sudo", "chmod", "666", slave_name], ignore_errors=True)
        
        # Open real device
        real_ser = serial.Serial(REAL, baudrate=1000000, timeout=0.2)
        print(f"Opened real device: {REAL}")
        
        # Start relay threads
        print("\nStarting relay threads...")
        thread1 = threading.Thread(
            target=relay_pty_to_real,
            args=(master_fd, real_ser),
            daemon=True
        )
        thread2 = threading.Thread(
            target=relay_real_to_pty,
            args=(master_fd, real_ser),
            daemon=True
        )
        thread1.start()
        thread2.start()
        
        print("Proxy running. Forwarding between PTY slave (clients open {}) and {}".format(DEV, REAL))
        print("Logs will appear here with timestamps. Ctrl-C to stop and restore device node.")
        print("=" * 60)
        
        # Keep main thread alive
        try:
            while keep_running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nInterrupted by user")
        
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        cleanup()


if __name__ == "__main__":
    main()

