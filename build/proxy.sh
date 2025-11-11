#!/bin/bash
set -euo pipefail

DEV=/dev/ttyS0
REAL="$DEV.real"

# Stop getty (ignore errors if already stopped)
sudo systemctl stop "serial-getty@$(basename "$DEV").service" 2>/dev/null || true

# If the "real" device doesn’t exist yet, move the real one aside
if [ ! -e "$REAL" ]; then
  sudo mv "$DEV" "$REAL"
fi

# --- Capture the current serial settings ---
MODE=$(stty -F "$REAL" -g)

# Optionally print them for visibility
echo "Captured serial mode: $MODE"

# --- Apply the same settings again to ensure consistency ---
sudo stty -F "$REAL" "$MODE"

# --- Start the proxy ---
sudo socat -d -d -v -x \
  pty,raw,echo=0,link="$DEV",waitslave,mode=666 \
  "$REAL",raw,echo=0,nonblock,ignoreeof,clocal=1,hupcl=0
