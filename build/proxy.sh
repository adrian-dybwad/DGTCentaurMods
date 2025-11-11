#!/bin/bash
set -euo pipefail

DEV=/dev/ttyS0
REAL="$DEV.real"

# Stop getty (ignore errors if already stopped)
sudo systemctl stop "serial-getty@$(basename "$DEV").service" 2>/dev/null || true

# Kill any processes using the device
sudo fuser -k "$DEV" 2>/dev/null || true
sudo fuser -k "$REAL" 2>/dev/null || true
sleep 0.5

# If the "real" device doesn't exist yet, move the real one aside
if [ ! -e "$REAL" ]; then
  sudo mv "$DEV" "$REAL"
fi

# Ensure the real device is ready and not locked
sudo chmod 666 "$REAL" 2>/dev/null || true

# Set baud rate explicitly to 1000000 (device requirement)
# Other settings (raw mode, etc.) are handled by socat's raw option
sudo stty -F "$REAL" 1000000

# --- Start the proxy ---
# waitslave ensures connection is established before data transfer
# ignoreeof on PTY side prevents exit when slave closes
# Use raw on PTY side for binary data
# Use raw on real device side too, remove stty option
# Use -v for verbose to see both directions
sudo socat -d -d -v -x \
  pty,raw,echo=0,link="$DEV",waitslave,mode=666,ignoreeof \
  "$REAL",raw,echo=0,clocal=1,hupcl=0
