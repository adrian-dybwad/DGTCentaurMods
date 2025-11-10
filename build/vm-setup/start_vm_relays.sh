#!/bin/bash
# Start both serial relay and epaper proxy clients in VM
# Usage: ./start_vm_relays.sh <PI_IP_ADDRESS>

if [ -z "$1" ]; then
    echo "Usage: $0 <PI_IP_ADDRESS>"
    echo "Example: $0 192.168.1.100"
    exit 1
fi

PI_IP=$1
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Starting VM relay services..."
echo "Connecting to Pi at: $PI_IP"
echo

# Start serial relay client in background
echo "Starting serial relay client..."
python3 "$SCRIPT_DIR/serial_relay_client.py" --server-ip "$PI_IP" &
SERIAL_PID=$!

# Wait a moment for serial relay to establish
sleep 2

# Start epaper proxy client in background
echo "Starting epaper proxy client..."
python3 "$SCRIPT_DIR/epaper_proxy_client.py" --server-ip "$PI_IP" &
EPAPER_PID=$!

echo
echo "Relay services started:"
echo "  Serial relay PID: $SERIAL_PID"
echo "  Epaper proxy PID: $EPAPER_PID"
echo
echo "Press Ctrl+C to stop all services"

# Wait for interrupt
trap "kill $SERIAL_PID $EPAPER_PID 2>/dev/null; exit" INT TERM

# Wait for processes
wait $SERIAL_PID $EPAPER_PID

