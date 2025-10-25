#!/bin/bash
# Download and install maia chess engine weight files
# This script should be run on the Raspberry Pi as the pi user

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DGTCM_PATH="/opt/DGTCentaurMods"
TMP_DIR="${DGTCM_PATH}/tmp"

# Ensure /opt/DGTCentaurMods directory structure exists
if [ ! -d "$DGTCM_PATH" ]; then
    echo "Creating $DGTCM_PATH directory structure..."
    sudo mkdir -p "$DGTCM_PATH"
    sudo chown pi:pi "$DGTCM_PATH"
fi
MAIA_REPO="https://github.com/CSSLab/maia-chess.git"
ENGINES_PATH="${DGTCM_PATH}/engines"
WEIGHTS_PATH="${ENGINES_PATH}/maia_weights"

echo "=== Maia Weight Files Installer ==="
echo ""

# Check if running as root (should not be)
if [ "$EUID" -eq 0 ]; then 
    echo "ERROR: Do not run this script as root"
    echo "Please run as the pi user: ./maia_weights.sh"
    exit 1
fi

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "ERROR: git is not installed"
    echo "Please install git: sudo apt-get install git"
    exit 1
fi

# Check available disk space (need at least 50MB)
available_space=$(df /opt | tail -1 | awk '{print $4}')
if [ "$available_space" -lt 51200 ]; then
    echo "ERROR: Not enough disk space available"
    echo "Need at least 50MB free space in /opt"
    exit 1
fi

# Create tmp directory if it doesn't exist
echo "Creating temporary directory..."
sudo mkdir -p "$TMP_DIR"
sudo chown pi:pi "$TMP_DIR"

# Check if weights already exist
if [ -d "$WEIGHTS_PATH" ] && [ "$(ls -A $WEIGHTS_PATH)" ]; then
    echo "WARNING: Maia weight files already exist at $WEIGHTS_PATH"
    read -p "Do you want to re-download them? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
    echo "Removing existing weight files..."
    rm -rf "$WEIGHTS_PATH"
fi

# Clone maia-chess repository
echo ""
echo "Downloading maia-chess repository..."
echo "This may take a few minutes depending on your connection..."
if [ -d "$TMP_DIR/maia-chess" ]; then
    echo "Removing old temporary files..."
    rm -rf "$TMP_DIR/maia-chess"
fi

if ! git clone --depth 1 "$MAIA_REPO" "$TMP_DIR/maia-chess"; then
    echo "ERROR: Failed to clone maia-chess repository"
    echo "Please check your internet connection and try again"
    exit 1
fi

# Verify the weight files exist in the cloned repo
if [ ! -d "$TMP_DIR/maia-chess/maia_weights" ]; then
    echo "ERROR: maia_weights directory not found in cloned repository"
    rm -rf "$TMP_DIR/maia-chess"
    exit 1
fi

# Count weight files
weight_count=$(ls -1 "$TMP_DIR/maia-chess/maia_weights/"*.pb.gz 2>/dev/null | wc -l)
if [ "$weight_count" -eq 0 ]; then
    echo "ERROR: No weight files found in repository"
    rm -rf "$TMP_DIR/maia-chess"
    exit 1
fi

echo "Found $weight_count weight files"

# Copy weight files to engines directory
echo ""
echo "Installing weight files to $WEIGHTS_PATH..."
sudo mkdir -p "$WEIGHTS_PATH"
sudo cp -r "$TMP_DIR/maia-chess/maia_weights/"* "$WEIGHTS_PATH/"
sudo chown -R pi:pi "$WEIGHTS_PATH"

# Also copy the highest-rated weight file to engines root (as per postinst)
echo "Copying maia-1900.pb.gz to engines directory..."
sudo cp "$WEIGHTS_PATH/maia-1900.pb.gz" "$ENGINES_PATH/"
sudo chown pi:pi "$ENGINES_PATH/maia-1900.pb.gz"

# Set proper permissions
echo "Setting permissions..."
sudo chmod 755 "$ENGINES_PATH/maia" 2>/dev/null || true
sudo chmod 644 "$WEIGHTS_PATH"/*.pb.gz
sudo chmod 644 "$ENGINES_PATH/maia-1900.pb.gz"

# Clean up temporary files
echo ""
echo "Cleaning up temporary files..."
rm -rf "$TMP_DIR/maia-chess"

# Verify installation
echo ""
echo "=== Installation Complete ==="
echo ""
echo "Installed weight files:"
ls -lh "$WEIGHTS_PATH"/*.pb.gz | awk '{print "  " $9 " (" $5 ")"}'
echo ""
echo "Total size: $(du -sh $WEIGHTS_PATH | awk '{print $1}')"
echo ""
echo "The maia chess engine is now ready to use!"
echo "You can select it from the Engines menu on your DGT Centaur."
