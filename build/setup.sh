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

# Create symlink for stockfish_pi in dev engines directory
DEV_ENGINES_DIR="/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/engines"
STOCKFISH_NAME="stockfish_pi"
STOCKFISH_DEV_PATH="${DEV_ENGINES_DIR}/${STOCKFISH_NAME}"

# Check if stockfish_pi exists in old location or installed location
if [ -f "/home/pi/centaur/engines/${STOCKFISH_NAME}" ]; then
    STOCKFISH_SOURCE="/home/pi/centaur/engines/${STOCKFISH_NAME}"
elif [ -f "/opt/DGTCentaurMods/engines/${STOCKFISH_NAME}" ]; then
    STOCKFISH_SOURCE="/opt/DGTCentaurMods/engines/${STOCKFISH_NAME}"
else
    STOCKFISH_SOURCE=""
fi

if [ -n "$STOCKFISH_SOURCE" ]; then
    mkdir -p "$DEV_ENGINES_DIR"
    # Remove existing symlink or file if it exists
    if [ -e "$STOCKFISH_DEV_PATH" ]; then
        rm -f "$STOCKFISH_DEV_PATH"
    fi
    # Create symlink
    ln -s "$STOCKFISH_SOURCE" "$STOCKFISH_DEV_PATH"
    echo "✓ Created symlink: $STOCKFISH_DEV_PATH -> $STOCKFISH_SOURCE"
else
    echo "⚠ stockfish_pi not found in /home/pi/centaur/engines/ or /opt/DGTCentaurMods/engines/"
    echo "   Skipping symlink creation"
fi

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
echo "Verifying stockfish_pi..."
if [ -f "$STOCKFISH_DEV_PATH" ] || [ -L "$STOCKFISH_DEV_PATH" ]; then
    echo "✓ stockfish_pi found in dev engines: $STOCKFISH_DEV_PATH"
    if [ -L "$STOCKFISH_DEV_PATH" ]; then
        echo "  (symlink to: $(readlink "$STOCKFISH_DEV_PATH"))"
    fi
else
    echo "✗ stockfish_pi NOT found in dev engines: $STOCKFISH_DEV_PATH"
fi

echo ""
echo "You can now run your tests!"


