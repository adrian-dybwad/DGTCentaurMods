#!/usr/bin/env python3
"""
Serial port proxy using socat.

Proxies /dev/ttyS0 through a PTY to /dev/ttyS0.real, allowing monitoring
and interception of serial traffic.

Usage:
    sudo python3 proxy.py
"""

import os
import sys
import subprocess
import signal
import time
import re


DEV = "/dev/ttyS0"
REAL = f"{DEV}.real"
keep_running = True
socat_process = None


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


def cleanup():
    """Cleanup function to restore device on exit."""
    global keep_running, socat_process
    keep_running = False
    
    # Terminate socat process if running
    if socat_process is not None:
        try:
            socat_process.terminate()
            socat_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            socat_process.kill()
        except Exception:
            pass
    
    # Remove symlink if it exists
    if os.path.islink(DEV):
        try:
            os.unlink(DEV)
        except Exception:
            pass
    
    # Restore real device if it exists
    if os.path.exists(REAL):
        try:
            os.rename(REAL, DEV)
        except Exception:
            pass


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print("\nShutting down...", file=sys.stderr)
    cleanup()
    sys.exit(0)


def process_socat_line(line, pending_direction=None):
    """
    Process a single line of socat output, matching the sed/awk pipeline behavior.
    
    The shell script does:
    sed -E 's/^([><]).*/\1/' | grep -v '^--$' | awk '/^[><]$/ {dir=$0; getline; print dir " " $0; next} {print}'
    
    Returns:
        tuple: (output_line or None, pending_direction or None)
    """
    line = line.strip()
    
    # Remove separator lines
    if line == '--':
        return None, pending_direction
    
    # Extract direction character if line starts with > or <
    match = re.match(r'^([><]).*', line)
    if match:
        direction = match.group(1)
        # If we have a pending direction, combine with current line
        if pending_direction:
            return f"{pending_direction} {line}", None
        # Otherwise, this becomes the pending direction
        return None, direction
    else:
        # Regular line: if we have pending direction, combine; otherwise just output
        if pending_direction:
            return f"{pending_direction} {line}", None
        return line, None


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
        try:
            os.rename(DEV, REAL)
        except Exception as e:
            print(f"Error moving {DEV} to {REAL}: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Ensure the real device is ready and not locked
    run_command(["sudo", "chmod", "666", REAL], ignore_errors=True)
    
    # Set baud rate explicitly to 1000000 (device requirement)
    # Other settings (raw mode, etc.) are handled by socat's raw option
    run_command(["sudo", "stty", "-F", REAL, "1000000"], ignore_errors=True)
    
    # Start the proxy using socat
    # waitslave ensures connection is established before data transfer
    # ignoreeof on PTY side prevents exit when slave closes
    # Use raw on PTY side for binary data
    # Use raw on real device side too
    # -v shows direction indicators (> and <), -x shows hex bytes
    socat_cmd = [
        "sudo", "socat", "-v", "-x",
        f"pty,raw,echo=0,link={DEV},waitslave,mode=666,ignoreeof",
        f"{REAL},raw,echo=0,clocal=1,hupcl=0"
    ]
    
    global socat_process
    
    try:
        # Start socat process
        socat_process = subprocess.Popen(
            socat_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        # Process output line by line in real-time
        pending_direction = None
        for line in socat_process.stdout:
            if not keep_running:
                break
            
            output, pending_direction = process_socat_line(line, pending_direction)
            if output is not None:
                print(output)
        
        # Output any remaining pending direction
        if pending_direction is not None:
            print(pending_direction)
        
        # Wait for process to complete
        socat_process.wait()
        
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error running socat: {e}", file=sys.stderr)
    finally:
        cleanup()


if __name__ == "__main__":
    main()

