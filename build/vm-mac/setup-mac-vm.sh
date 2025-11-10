#!/bin/bash
# Setup script for Bullseye ARM VM on Mac
# This creates a VM that can connect to real Pi hardware via network

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_DIR="${HOME}/.dgtcentaurmods-vm"
VM_IMAGE="${VM_DIR}/bullseye-arm.img"
VM_SIZE="8G"
# Debian ARM images - try multiple sources
DEBIAN_URLS=(
    "https://cdimage.debian.org/cdimage/archive/11.9.0/armhf/iso-cd/debian-11.9.0-armhf-netinst.iso"
    "https://raspi.debian.net/tested-images/raspi_3.img.xz"
)

echo "=== Mac VM Setup for Centaur Binary Development ==="
echo ""
echo "This will create a Debian Bullseye ARM VM on your Mac"
echo "that can connect to real Raspberry Pi hardware via network."
echo ""

# Check if QEMU is installed
if ! command -v qemu-system-arm &> /dev/null; then
    echo "QEMU not found. Installing via Homebrew..."
    if ! command -v brew &> /dev/null; then
        echo "Error: Homebrew not found. Please install Homebrew first:"
        echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        exit 1
    fi
    brew install qemu
fi

echo "✓ QEMU found: $(qemu-system-arm --version | head -1)"
echo ""

# Create VM directory
mkdir -p "$VM_DIR"
cd "$VM_DIR"

# Check if VM image already exists
if [ -f "$VM_IMAGE" ]; then
    echo "VM image already exists at $VM_IMAGE"
    read -p "Recreate? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -f "$VM_IMAGE"
    else
        echo "Using existing VM image."
        exit 0
    fi
fi

# Create VM disk image
echo "Creating VM disk image (${VM_SIZE})..."
qemu-img create -f qcow2 "$VM_IMAGE" "$VM_SIZE"

echo ""
echo "VM disk image created. You have two options:"
echo ""
echo "Option 1: Install Debian Bullseye from ISO (Recommended)"
echo "  Download Debian Bullseye ARM netinst ISO:"
echo "    https://cdimage.debian.org/cdimage/archive/11.9.0/armhf/iso-cd/debian-11.9.0-armhf-netinst.iso"
echo ""
echo "  Then run:"
echo "    qemu-system-arm -M virt -cpu cortex-a15 -m 2G \\"
echo "      -drive file=$VM_IMAGE,format=qcow2 \\"
echo "      -cdrom debian-11.9.0-armhf-netinst.iso \\"
echo "      -boot d -netdev user,id=net0 -device virtio-net-device,netdev=net0"
echo ""
echo "Option 2: Use pre-built Debian image"
echo "  Download a pre-built Debian ARM image and convert it"
echo ""
echo "For now, the VM disk is ready. You can install Debian manually or"
echo "use a pre-built image. See README.md for detailed instructions."

echo ""
echo "=== Setup Complete ==="
echo ""
echo "VM image created at: $VM_IMAGE"
echo ""
echo "Next steps:"
echo "1. Set up serial relay on Pi: python3 build/vm-mac/pi-serial-relay.py"
echo "2. Set up display proxy on Pi: python3 build/vm-mac/pi-display-proxy.py"
echo "3. Launch VM: ./build/vm-mac/run-centaur-vm.sh --pi-ip <PI_IP>"
echo ""

