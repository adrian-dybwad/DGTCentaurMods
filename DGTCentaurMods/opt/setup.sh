#!/bin/bash
# Quick resource setup for Pi environment
# Run this from: /home/pi/DGTCentaurMods/DGTCentaurMods/opt

echo "Setting up resource paths for AssetManager..."

# Create the directories AssetManager expects
sudo mkdir -p /home/pi/resources
sudo mkdir -p /opt/DGTCentaurMods/resources

# Copy the config file from your development environment
sudo mkdir -p /opt/DGTCentaurMods/config
sudo cp /home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/config/centaur.ini /opt/DGTCentaurMods/config/

# Copy the default config
sudo mkdir -p /opt/DGTCentaurMods/defaults/config
sudo cp /home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/config/centaur.ini /opt/DGTCentaurMods/defaults/config/

echo "Setting up resource paths for AssetManager..."

sudo mkdir -p /opt/DGTCentaurMods/resources
sudo cp -r /home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/resources/* /opt/DGTCentaurMods/resources/

sudo chown -R pi:pi /opt/DGTCentaurMods
sudo chmod -R u+w /opt/DGTCentaurMods
sudo chown -R pi:pi /opt/DGTCentaurMods
sudo chown -R pi:pi /opt/DGTCentaurMods/resources
sudo chown -R pi:pi /opt/DGTCentaurMods/config
sudo chown -R pi:pi /opt/DGTCentaurMods/defaults/config

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
