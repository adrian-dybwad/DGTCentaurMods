#!/bin/bash
# Setup script for Bullseye VM on Raspberry Pi
# This is a complex solution - see README.md for details

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_DIR="/opt/bullseye-vm"
VM_IMAGE="${VM_DIR}/bullseye.img"
VM_SIZE="4G"

echo "=== Bullseye VM Setup for Centaur Binary ==="
echo ""
echo "WARNING: This is a complex solution with significant overhead."
echo "Consider using Bullseye directly on the host instead."
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Check if running on supported hardware
echo "1. Checking hardware support..."
if [ ! -f /dev/kvm ]; then
    echo "WARNING: /dev/kvm not found. KVM acceleration is NOT available."
    echo "VM will run in emulation mode (VERY SLOW)."
    echo ""
    echo "This is likely a Pi Zero 2 W or Pi Zero W."
    echo "VM performance will be extremely poor - NOT RECOMMENDED."
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted. Consider using Bullseye directly on the host instead."
        exit 1
    fi
fi

# Check available memory
TOTAL_MEM=$(free -m | awk '/^Mem:/{print $2}')
AVAILABLE_MEM=$(free -m | awk '/^Mem:/{print $7}')
echo "Total RAM: ${TOTAL_MEM}MB"
echo "Available RAM: ${AVAILABLE_MEM}MB"

if [ "$TOTAL_MEM" -lt 1024 ]; then
    echo ""
    echo "ERROR: System has only ${TOTAL_MEM}MB total RAM."
    echo "VM requires at least 512MB-1GB RAM minimum."
    echo "VM is NOT POSSIBLE on this hardware."
    echo ""
    echo "This appears to be a Pi Zero 2 W or Pi Zero W."
    echo "VM solution is not viable - use Bullseye directly on the host instead."
    exit 1
fi

if [ "$AVAILABLE_MEM" -lt 512 ]; then
    echo "WARNING: Less than 512MB free memory. VM may not run well."
    echo "VM requires at least 512MB free memory."
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted. Free up memory or use Bullseye directly on the host."
        exit 1
    fi
fi

# Install QEMU
echo "2. Installing QEMU..."
if ! command -v qemu-system-arm &> /dev/null; then
    sudo apt-get update
    sudo apt-get install -y qemu-system-arm qemu-utils debootstrap
else
    echo "QEMU already installed."
fi

# Create VM directory
echo "3. Creating VM directory..."
sudo mkdir -p "$VM_DIR"

# Create VM disk image
if [ ! -f "$VM_IMAGE" ]; then
    echo "4. Creating VM disk image (${VM_SIZE})..."
    sudo qemu-img create -f raw "$VM_IMAGE" "$VM_SIZE"
else
    echo "VM image already exists at $VM_IMAGE"
fi

# Create Bullseye root filesystem
BULLSEYE_ROOT="${VM_DIR}/rootfs"
if [ ! -d "$BULLSEYE_ROOT" ]; then
    echo "5. Creating Bullseye root filesystem..."
    echo "This will take several minutes..."
    sudo debootstrap --arch=armhf --variant=minbase \
        bullseye "$BULLSEYE_ROOT" \
        http://deb.debian.org/debian
    
    echo "6. Setting up chroot environment..."
    sudo chroot "$BULLSEYE_ROOT" /bin/bash <<EOF
apt-get update
apt-get install -y --no-install-recommends \
    linux-image-armmp \
    systemd \
    openssh-server \
    sudo
EOF
else
    echo "Bullseye rootfs already exists at $BULLSEYE_ROOT"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Configure VM networking and hardware passthrough"
echo "2. Set up hardware proxy daemon for GPIO/SPI access"
echo "3. Create VM launch script"
echo ""
echo "See README.md for detailed instructions."

