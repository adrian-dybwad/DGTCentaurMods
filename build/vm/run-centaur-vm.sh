#!/bin/bash
# Launch Bullseye VM with centaur binary
# This script demonstrates the VM approach but has significant limitations

set -euo pipefail

VM_DIR="/opt/bullseye-vm"
VM_IMAGE="${VM_DIR}/bullseye.img"
VM_RAM="512M"
CENTAUR_DIR="/home/pi/centaur"
BULLSEYE_ROOT="${VM_DIR}/rootfs"

# Check if VM image exists
if [ ! -f "$VM_IMAGE" ]; then
    echo "Error: VM image not found at $VM_IMAGE"
    echo "Run setup-vm.sh first"
    exit 1
fi

# Check if centaur directory exists
if [ ! -d "$CENTAUR_DIR" ]; then
    echo "Error: Centaur directory not found at $CENTAUR_DIR"
    exit 1
fi

echo "=== Launching Bullseye VM for Centaur Binary ==="
echo ""

# Check for KVM
if [ ! -f /dev/kvm ]; then
    echo "CRITICAL WARNING: KVM not available (/dev/kvm not found)"
    echo "VM will run in emulation mode - PERFORMANCE WILL BE EXTREMELY POOR"
    echo "This is likely not practical for real-time chess board communication."
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted. Use Bullseye directly on the host instead."
        exit 1
    fi
fi

echo "WARNING: This VM solution has significant limitations:"
echo "- GPIO and SPI cannot be directly accessed from VM"
echo "- Requires hardware proxy daemon (not implemented)"
echo "- Significant performance overhead"
echo "- May not work on Pi Zero due to resource constraints"
echo ""
echo "This is a proof-of-concept. For production use,"
echo "consider using Bullseye directly on the host."
echo ""

# QEMU command with hardware passthrough
# Note: GPIO/SPI passthrough is not directly supported
# This would require a hardware proxy daemon

qemu-system-arm \
  -M virt \
  -cpu cortex-a7 \
  -m "$VM_RAM" \
  -drive file="$VM_IMAGE",format=raw,if=virtio \
  -chardev serial,path=/dev/serial0,id=serial0 \
  -device virtio-serial-device \
  -device virtconsole,chardev=serial0 \
  -fsdev local,id=centaur,path="$CENTAUR_DIR",security_model=mapped \
  -device virtio-9p-pci,fsdev=centaur,mount_tag=centaur \
  -netdev user,id=net0 \
  -device virtio-net-device,netdev=net0 \
  -nographic \
  -no-reboot

echo ""
echo "VM exited."

