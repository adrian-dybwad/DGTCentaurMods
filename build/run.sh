#!/usr/bin/env bash
# ------------------------------------------
# DGTCentaur launcher
# Works on Bullseye, Bookworm, or desktop
# ------------------------------------------

# Always run from the project root
cd "$(dirname "$0")" || exit 1

cd ~/DGTCentaurMods/DGTCentaurMods/opt

git pull

# Ensure virtualenv exists
if [ ! -d "DGTCentaurMods/.venv" ]; then
  echo "No .venv found! Create one with:"
  echo "   python3 -m venv --system-site-packages DGTCentaurMods/.venv && source DGTCentaurMods/.venv/bin/activate && pip install -r DGTCentaurMods/setup/requirements.txt"
  exit 1
fi



# Activate the virtual environment
source DGTCentaurMods/.venv/bin/activate

# Add project root to Python path (for flat layout)
export PYTHONPATH="$PWD:$PYTHONPATH"

# Stop web service if it exists
if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "DGTCentaurMods.service"; then
	sudo systemctl stop DGTCentaurMods 2>/dev/null || true
fi

# Launch the game
python -m DGTCentaurMods.menu "$@"
# or if you restructured into a package, replace the above with:
# python -m DGTCentaurMods.menu "$@"

# Deactivate when done
deactivate

# Start web service if it exists
if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "DGTCentaurMods.service"; then
	sudo systemctl start DGTCentaurMods 2>/dev/null || true
fi
