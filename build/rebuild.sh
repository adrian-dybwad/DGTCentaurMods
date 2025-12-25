#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

BRANCH_OR_TAG="${1:-AsyncController}"

# Always work repo-relative (portable across checkout folder names)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${REPO_DIR}/build"
RELEASES_DIR="${BUILD_DIR}/releases"

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "Repository not found at $REPO_DIR (expecting a git repo)." >&2
  exit 1
fi

log "1/8 Purging existing packages (if installed)"
sudo apt-get -y purge universal-chess || true
sudo apt-get -y purge dgtcentaurmods || true
#sudo apt-get -y autoremove --purge || true

log "2/8 Updating repository and switching to '$BRANCH_OR_TAG'"
cd "$REPO_DIR"
git fetch --all --prune
# Try to switch to branch; if it fails, try checkout (for tags). If detached, skip pull.
if git rev-parse --verify --quiet "refs/heads/$BRANCH_OR_TAG" >/dev/null; then
  git switch "$BRANCH_OR_TAG"
  git pull --ff-only
else
  git checkout "$BRANCH_OR_TAG"
  git rev-parse --verify --quiet HEAD >/dev/null || { echo "Invalid ref: $BRANCH_OR_TAG" >&2; exit 1; }
fi

log "3/8 Building package from '$BRANCH_OR_TAG'"
cd "$BUILD_DIR"
./build.sh "$BRANCH_OR_TAG"

log "4/8 Locating latest .deb artifact"
# Multi-arch package uses _all.deb
artifact=$(ls -1t "$RELEASES_DIR"/universal-chess_*_all.deb 2>/dev/null | head -n1 || true)
if [ -z "${artifact:-}" ] || [ ! -f "$artifact" ]; then
  echo "No .deb artifact found in $RELEASES_DIR" >&2
  exit 1
fi
log "Found artifact: $(basename "$artifact")"

log "5/8 Copying artifact to /tmp and installing"
ART_BASENAME="$(basename "$artifact")"
TMP_ART="/tmp/$ART_BASENAME"
sudo cp -f "$artifact" "$TMP_ART"
sudo apt-get -y install "$TMP_ART"

log "6/8 Reloading systemd units"
sudo systemctl daemon-reload || true

restart_if_present() {
  local unit="$1"
  if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "${unit}"; then
    log "Restarting ${unit}"
    sudo systemctl restart "${unit}" || true
  fi
}

log "7/8 Restarting services"
restart_if_present "universal-chess.service"
restart_if_present "universal-chess-web.service"
restart_if_present "universal-chess-stop-controller.service"

log "8/8 Ensuring Font.ttc is present (optional step)"
FONT_TARGET="/opt/universalchess/resources/Font.ttc"
FONT_SOURCE="${REPO_DIR}/src/universalchess/resources/Font.ttc"
if [ ! -f "$FONT_TARGET" ] && [ -f "$FONT_SOURCE" ]; then
  sudo mkdir -p "/opt/universalchess/resources"
  sudo cp -f "$FONT_SOURCE" "$FONT_TARGET"
  sudo chmod 0644 "$FONT_TARGET"
  log "Copied Font.ttc to $FONT_TARGET"
fi

log "Rebuild and redeploy complete. Installed: $ART_BASENAME"

