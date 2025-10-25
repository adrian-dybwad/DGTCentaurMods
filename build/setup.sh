#!/bin/bash
# Quick resource setup for Pi environment
# Run this from: /home/pi/DGTCentaurMods

set -euo pipefail

echo "Setting up dev resources..."

# Create the directories AssetManager expects
sudo mkdir -p /home/pi/resources
sudo mkdir -p /opt/DGTCentaurMods/resources

# Active config
sudo mkdir -p /opt/DGTCentaurMods/config

# Populate runtime config from defaults (if missing)
if [ ! -f /opt/DGTCentaurMods/config/centaur.ini ]; then
    sudo cp /home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/defaults/config/centaur.ini /opt/DGTCentaurMods/config/
fi

# Copy resources for AssetManager (best effort)
if [ -d /home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/resources ]; then
  sudo cp -r /home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/resources/* /opt/DGTCentaurMods/resources/ || true
fi

sudo chown -R pi:pi /opt/DGTCentaurMods
sudo chmod -R u+w /opt/DGTCentaurMods
sudo chown -R pi:pi /opt/DGTCentaurMods/resources
sudo chown -R pi:pi /opt/DGTCentaurMods/config

echo "Resource setup complete!"
echo ""
echo "Verifying Font.ttc..."
if [ -f "/home/pi/resources/Font.ttc" ]; then
    echo "✓ Font.ttc found in /home/pi/resources/"
else
    echo "✗ Font.ttc NOT found in /home/pi/resources/"
fi

if [ -f "/opt/DGTCentaurMods/resources/Font.ttc" ]; then
    echo "✓ Font.ttc found in /opt/DGTCentaurMods/resources/"
else
    echo "✗ Font.ttc NOT found in /opt/DGTCentaurMods/resources/"
fi

echo ""
echo "You can now run your tests!"


