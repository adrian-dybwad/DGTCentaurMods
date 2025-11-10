#!/bin/bash
# VM Setup Script for Debian Bullseye
# Run this inside the VM after initial Debian installation

set -e

echo "=========================================="
echo "DGTCentaurMods VM Setup for Bullseye"
echo "=========================================="
echo

# Update system
echo "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install required packages
echo "Installing required packages..."
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-pil \
    pyserial \
    socat \
    git

# Install Python packages
echo "Installing Python packages..."
pip3 install pyserial Pillow

# Create directories
echo "Creating directories..."
mkdir -p ~/DGTCentaurMods/build/vm-setup
mkdir -p ~/centaur

# Copy scripts (assuming they're in the repo or copied manually)
echo "Setup complete!"
echo
echo "Next steps:"
echo "1. Copy serial_relay_client.py and epaper_proxy_client.py to ~/DGTCentaurMods/build/vm-setup/"
echo "2. Copy centaur software to ~/centaur/"
echo "3. Run serial relay client: python3 ~/DGTCentaurMods/build/vm-setup/serial_relay_client.py --server-ip <PI_IP>"
echo "4. Run epaper proxy client: python3 ~/DGTCentaurMods/build/vm-setup/epaper_proxy_client.py --server-ip <PI_IP>"
echo "5. Run centaur: cd ~/centaur && sudo ./centaur"

