#!/usr/bin/env bash
set -euo pipefail

# Run relative to repo, not ~ or /home/pi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

if [ ! -d "${REPO_ROOT}/.venv" ]; then
  echo "No .venv found at ${REPO_ROOT}/.venv"
  echo "Create one with (from repo root):"
  echo "   cd \"${REPO_ROOT}\" && python3 -m venv --system-site-packages .venv && source .venv/bin/activate && pip install -r src/universalchess/setup/requirements.txt"
  echo "If you're currently in build/:"
  echo "   cd .. && python3 -m venv --system-site-packages .venv && source .venv/bin/activate && pip install -r src/universalchess/setup/requirements.txt"
  exit 1
fi

# Stop web service if it exists (best-effort)
if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "universal-chess-web.service"; then
	sudo systemctl stop universal-chess-web.service 2>/dev/null || true
fi

# shellcheck disable=SC1091
source "${REPO_ROOT}/.venv/bin/activate"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

cd "${REPO_ROOT}/src/universalchess/web"
export FLASK_APP=app.py
python -m flask run --host=0.0.0.0 --port=5000

# Deactivate when done
deactivate

# Start web service if it exists
if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "universal-chess-web.service"; then
	sudo systemctl start universal-chess-web.service 2>/dev/null || true
fi