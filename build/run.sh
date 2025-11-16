#!/usr/bin/env bash
# ============================================================================
# DGTCentaur Launcher
# ============================================================================
#
# Description:
#   Launch script for DGTCentaurMods project. Supports running on Bullseye,
#   Bookworm, or desktop environments. Automatically manages the Python
#   virtual environment and systemd service lifecycle.
#
# Usage:
#   ./run.sh [MODULE] [MODULE_ARGS...]
#   ./run.sh sf [SIDE] [ELO]
#   ./run.sh ENGINE [SIDE] [PRESET]
#
# Arguments:
#   MODULE        Optional Python module to run (e.g., DGTCentaurMods.menu)
#                 If not specified, defaults to DGTCentaurMods.menu
#   MODULE_ARGS   Optional arguments to pass to the Python module
#
#   Special Modes:
#   sf            Runs Stockfish mode (DGTCentaurMods.game.stockfish)
#     SIDE        Side to play (white|black|random), default: white
#     ELO         Stockfish ELO (1350-2850 recommended), default: 2000
#
#   ENGINE        Runs UCI engine mode (ct800|maia|rodentiv|zahak)
#     SIDE        Side to play (white|black|random), default: random
#     PRESET      Engine preset from .uci file (e.g., "DEFAULT", "1200 ELO")
#                 If not specified, uses the DEFAULT preset from the engine's .uci file
#
# Examples:
#   ./run.sh
#     - Runs the default menu module
#
#   ./run.sh DGTCentaurMods.menu
#     - Explicitly runs the menu module
#
#   ./run.sh DGTCentaurMods.game.gamemanager --debug
#     - Runs the gamemanager module with --debug flag
#
#   ./run.sh DGTCentaurMods.tests.test_uci_cli
#     - Runs a specific test module
#
#   ./run.sh sf
#     - Runs Stockfish mode with defaults (white side, ELO 2000)
#
#   ./run.sh sf black 2500
#     - Runs Stockfish mode playing as black at ELO 2500
#
#   ./run.sh sf random 1800
#     - Runs Stockfish mode with random side at ELO 1800
#
#   ./run.sh rodentiv
#     - Runs RodentIV engine with random side and DEFAULT preset
#
#   ./run.sh rodentiv white
#     - Runs RodentIV engine as white with DEFAULT preset
#
#   ./run.sh rodentiv black "1200 ELO"
#     - Runs RodentIV engine as black with "1200 ELO" preset from rodentIV.uci
#
#   ./run.sh maia random
#     - Runs Maia engine with random side and DEFAULT preset
#
#   ./run.sh zahak white
#     - Runs Zahak engine as white with DEFAULT preset
#
# Environment:
#   - Requires Python virtual environment at DGTCentaurMods/.venv
#   - Automatically stops/starts DGTCentaurMods.service if present
#   - Sets PYTHONPATH to include the project root
#
# Exit Codes:
#   0   - Success
#   1   - Error (missing virtual environment, directory change failed, etc.)
#
# ============================================================================

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

# Parse command line arguments
# Supports special modes (e.g., "sf" for Stockfish, engine names for UCI mode)
# and general Python module execution
DEFAULT_MODULE="DGTCentaurMods.menu"

# List of available engines (lowercase for case-insensitive matching)
AVAILABLE_ENGINES=("ct800" "maia" "rodentiv" "zahak")

# Function to check if a string is in the engines list (case-insensitive)
is_engine() {
  local search="$1"
  local engine
  for engine in "${AVAILABLE_ENGINES[@]}"; do
    if [[ "${search,,}" == "${engine}" ]]; then
      return 0
    fi
  done
  return 1
}

if [ $# -eq 0 ]; then
  # No arguments provided - use default module with no args
  MODULE="$DEFAULT_MODULE"
  MODULE_ARGS=()
elif [ "$1" == "sf" ]; then
  # Special mode: Stockfish launcher
  # Arg1: side (white|black|random), default: white
  # Arg2: ELO (1350-2850 recommended), default: 2000
  shift
  SIDE=${1:-white}
  ELO=${2:-2000}
  MODULE="DGTCentaurMods.game.stockfish"
  MODULE_ARGS=("$SIDE" "$ELO")
  echo "Launching Stockfish mode: side=$SIDE, ELO=$ELO"
elif is_engine "$1"; then
  # Engine mode: Launch a UCI engine
  # Arg1: engine name (ct800|maia|rodentiv|zahak)
  # Arg2: side (white|black|random), default: random
  # Arg3: preset name from .uci file, default: DEFAULT
  ENGINE_NAME="$1"
  shift
  SIDE=${1:-random}
  PRESET=${2:-DEFAULT}
  
  # Normalize engine name to match actual file names (case handling)
  case "${ENGINE_NAME,,}" in
    "ct800")     ENGINE_FILE="ct800" ;;
    "maia")      ENGINE_FILE="maia" ;;
    "rodentiv")  ENGINE_FILE="rodentIV" ;;
    "zahak")     ENGINE_FILE="zahak" ;;
    *)           ENGINE_FILE="${ENGINE_NAME}" ;;
  esac
  
  MODULE="DGTCentaurMods.game.uci"
  MODULE_ARGS=("$SIDE" "$ENGINE_FILE" "$PRESET")
  echo "Launching UCI engine mode: engine=$ENGINE_FILE, side=$SIDE, preset=$PRESET"
elif [[ "$1" == DGTCentaurMods.* ]] || [[ "$1" == *"."* ]]; then
  # First argument looks like a module path - use it as the module
  MODULE="$1"
  shift
  MODULE_ARGS=("$@")
else
  # First argument doesn't look like a module - treat all args as arguments to default module
  MODULE="$DEFAULT_MODULE"
  MODULE_ARGS=("$@")
fi

# Launch the specified Python module
echo "Launching: python -m $MODULE ${MODULE_ARGS[*]}"
python -m "$MODULE" "${MODULE_ARGS[@]}"

# Deactivate when done
deactivate

# Start web service if it exists
if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "DGTCentaurMods.service"; then
	#sudo systemctl start DGTCentaurMods 2>/dev/null || true
fi
