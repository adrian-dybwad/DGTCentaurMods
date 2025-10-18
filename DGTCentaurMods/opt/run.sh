#!/usr/bin/env bash
# ------------------------------------------
# DGTCentaur launcher
# Works on Bullseye, Bookworm, or desktop
# ------------------------------------------

# Always run from the project root
cd "$(dirname "$0")" || exit 1

# Ensure virtualenv exists
if [ ! -d ".venv" ]; then
  echo "❌ No .venv found! Create one with:"
  echo "   python3 -m venv DGTCentaurMods/.venv && source DGTCentaurMods/.venv/bin/activate && pip install -r DGTCentaurMods/setup/requirements.txt"
  exit 1
fi

# Activate the virtual environment
source .venv/bin/activate

# Add project root to Python path (for flat layout)
export PYTHONPATH="$PWD:$PYTHONPATH"

# Launch the game
python -m DGTCentaurMods.game.menu "$@"
# or if you restructured into a package, replace the above with:
# python -m DGTCentaurMods.game.menu "$@"

# Deactivate when done
deactivate