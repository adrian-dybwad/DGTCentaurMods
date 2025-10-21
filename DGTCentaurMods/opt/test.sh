#!/usr/bin/env bash
# ------------------------------------------
# DGTCentaur launcher
# Works on Bullseye, Bookworm, or desktop
# ------------------------------------------

# Always run from the project root
cd "$(dirname "$0")" || exit 1

# Ensure virtualenv exists
if [ ! -d "DGTCentaurMods/.venv" ]; then
  echo "No .venv found! Create one with:"
  echo "   python3 -m venv DGTCentaurMods/.venv && source DGTCentaurMods/.venv/bin/activate && pip install -r DGTCentaurMods/setup/requirements.txt"
  exit 1
fi

git pull

# Activate the virtual environment
source DGTCentaurMods/.venv/bin/activate

# Add project root to Python path (for flat layout)
export PYTHONPATH="$PWD:$PYTHONPATH"

python test_serial_helper.py

# Deactivate when done
deactivate