#!/bin/bash
# Quick resource setup for Pi environment
# Run this from: /home/pi/DGTCentaurMods/DGTCentaurMods/opt

echo "Setting up resource paths for AssetManager..."

# Create the directories AssetManager expects
sudo mkdir -p /home/pi/resources
sudo mkdir -p /opt/DGTCentaurMods/resources
sudo mkdir -p /opt/DGTCentaurMods/config
sudo mkdir -p /opt/DGTCentaurMods/defaults/config

# Create symlinks to the actual resources
sudo ln -sf /home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/resources/* /home/pi/resources/
sudo ln -sf /home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/resources/* /opt/DGTCentaurMods/resources/
sudo ln -sf /home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/config/* /opt/DGTCentaurMods/config/
sudo ln -sf /home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/defaults/config/* /opt/DGTCentaurMods/defaults/config/

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
