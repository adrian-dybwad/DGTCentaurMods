#!/bin/bash
# Start both serial relay and epaper proxy servers on Pi
# Usage: ./start_pi_servers.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Starting Pi relay services..."
echo

# Start serial relay server in background
echo "Starting serial relay server..."
python3 "$SCRIPT_DIR/serial_relay_server.py" &
SERIAL_PID=$!

# Wait a moment for serial relay to start
sleep 2

# Start epaper proxy server in background
echo "Starting epaper proxy server..."
python3 "$SCRIPT_DIR/epaper_proxy_server.py" &
EPAPER_PID=$!

echo
echo "Relay services started:"
echo "  Serial relay server PID: $SERIAL_PID (port 8888)"
echo "  Epaper proxy server PID: $EPAPER_PID (port 8889)"
echo
echo "Press Ctrl+C to stop all services"

# Wait for interrupt
trap "kill $SERIAL_PID $EPAPER_PID 2>/dev/null; exit" INT TERM

wait

