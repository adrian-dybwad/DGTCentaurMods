#!/bin/bash
# Helper script to install Debian Bullseye in the VM
# This launches QEMU with the Debian installer ISO

set -euo pipefail

VM_DIR="${HOME}/.dgtcentaurmods-vm"
VM_IMAGE="${VM_DIR}/bullseye-arm.img"
ISO_FILE="${VM_DIR}/debian-11.9.0-armhf-netinst.iso"

echo "=== Debian Bullseye ARM Installation ==="
echo ""

# Check if ISO exists
if [ ! -f "$ISO_FILE" ]; then
    echo "ISO file not found: $ISO_FILE"
    echo ""
    echo "Downloading Debian Bullseye ARM netinst ISO..."
    echo "This may take several minutes..."
    cd "$VM_DIR"
    curl -L -o debian-11.9.0-armhf-netinst.iso \
        https://cdimage.debian.org/cdimage/archive/11.9.0/armhf/iso-cd/debian-11.9.0-armhf-netinst.iso
    
    if [ ! -f "$ISO_FILE" ]; then
        echo "Error: Failed to download ISO"
        exit 1
    fi
    echo "✓ ISO downloaded"
fi

# Check if VM image exists
if [ ! -f "$VM_IMAGE" ]; then
    echo "VM image not found. Run setup-mac-vm.sh first"
    exit 1
fi

echo "Launching Debian installer..."
echo ""
echo "Instructions:"
echo "1. Follow the Debian installer prompts"
echo "2. When asked about disk, select the virtio disk"
echo "3. Install a minimal system (no desktop needed)"
echo "4. After installation, you can SSH in: ssh -p 2222 root@localhost"
echo ""
echo "Press Enter to start..."
read

qemu-system-arm \
  -M virt \
  -cpu cortex-a15 \
  -m 2G \
  -drive file="$VM_IMAGE",format=qcow2 \
  -cdrom "$ISO_FILE" \
  -boot d \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-device,netdev=net0 \
  -display none \
  -nographic

echo ""
echo "Installation complete (or cancelled)."
echo "To boot the installed system, run: ./run-centaur-vm.sh --pi-ip <PI_IP>"

