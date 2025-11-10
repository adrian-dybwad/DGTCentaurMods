#!/bin/bash
# Launch Bullseye ARM VM on Mac with serial connection to Pi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_DIR="${HOME}/.dgtcentaurmods-vm"
VM_IMAGE="${VM_DIR}/bullseye-arm.img"
CENTAUR_DIR="/home/pi/centaur"  # Path in VM
PI_IP=""
PI_SERIAL_PORT=8888

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --pi-ip)
            PI_IP="$2"
            shift 2
            ;;
        --pi-port)
            PI_SERIAL_PORT="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--pi-ip IP] [--pi-port PORT]"
            echo ""
            echo "Options:"
            echo "  --pi-ip IP      Raspberry Pi IP address (required)"
            echo "  --pi-port PORT  Serial relay port on Pi (default: 8888)"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage"
            exit 1
            ;;
    esac
done

if [ -z "$PI_IP" ]; then
    echo "Error: --pi-ip is required"
    echo "Usage: $0 --pi-ip <PI_IP_ADDRESS>"
    exit 1
fi

# Check if VM image exists
if [ ! -f "$VM_IMAGE" ]; then
    echo "Error: VM image not found at $VM_IMAGE"
    echo "Run setup-mac-vm.sh first"
    exit 1
fi

echo "=== Launching Centaur VM ==="
echo "VM Image: $VM_IMAGE"
echo "Pi IP: $PI_IP"
echo "Serial Relay Port: $PI_SERIAL_PORT"
echo ""
echo "Make sure serial relay is running on Pi:"
echo "  python3 build/vm-mac/pi-serial-relay.py"
echo ""

# QEMU command to launch VM with serial connection to Pi
qemu-system-arm \
  -M virt \
  -cpu cortex-a15 \
  -m 2G \
  -drive file="$VM_IMAGE",format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-device,netdev=net0 \
  -chardev socket,id=serial0,host="$PI_IP",port="$PI_SERIAL_PORT",reconnect=2 \
  -serial chardev:serial0 \
  -display none \
  -nographic

echo ""
echo "VM exited."

