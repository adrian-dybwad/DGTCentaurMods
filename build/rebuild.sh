#!/usr/bin/env bash

set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

BRANCH_OR_TAG="${1:-AsyncController}"
REPO_DIR="$HOME/DGTCentaurMods"
BUILD_DIR="$REPO_DIR/build"
RELEASES_DIR="$BUILD_DIR/releases"

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "Repository not found at $REPO_DIR (expecting a git repo)." >&2
  exit 1
fi

log "1/8 Purging existing dgtcentaurmods (if installed)"
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
artifact=$(ls -1t "$RELEASES_DIR"/dgtcentaurmods_*_armhf.deb 2>/dev/null | head -n1 || true)
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

restart_ci() {
  # $1: base unit name without .service (e.g., DGTCentaurMods)
  local name="$1"
  local match
  match=$(systemctl list-unit-files --type=service --no-legend | awk '{print $1}' | grep -iE "^${name}\\.service$" || true)
  if [ -n "$match" ]; then
    log "Restarting service (matched case-insensitively): $match"
    sudo systemctl restart "$match" || true
  fi
}

log "7/8 Restarting services (case-insensitive, specific then wildcard)"
restart_ci DGTCentaurMods
restart_ci DGTCentaurModsWeb

# Fallback: restart any service whose name starts with 'dgt' (case-insensitive)
mapfile -t dgt_units < <(systemctl list-unit-files --type=service --no-legend | awk '{print $1}' | grep -i '^dgt.*\\.service' || true)
if [ "${#dgt_units[@]}" -gt 0 ]; then
  log "Fallback restart for units: ${dgt_units[*]}"
  sudo systemctl restart "${dgt_units[@]}" || true
fi

# Warn if there are unexpected services that contain 'dgt' (case-insensitive)
mapfile -t all_dgt_units < <(systemctl list-unit-files --type=service --no-legend | awk '{print $1}' | grep -i 'dgt.*\\.service' | sort -u || true)
unexpected_dgt=()
for unit in "${all_dgt_units[@]:-}"; do
  [[ -z "$unit" ]] && continue  # Skip empty entries
  ul="${unit,,}"
  if [[ "$ul" == "dgtcentaurmods.service" || "$ul" == "dgtstopcontroller.service" ]]; then
    continue
  fi
  unexpected_dgt+=("$unit")
done
if [ "${#unexpected_dgt[@]}" -gt 0 ]; then
  log "WARNING: Unexpected services containing 'dgt' detected: ${unexpected_dgt[*]}"
fi

log "8/8 Ensuring Font.ttc is present (optional step)"
FONT_TARGET="/opt/DGTCentaurMods/resources/Font.ttc"
FONT_SOURCE="$REPO_DIR/tools/card-setup-tool/lib/font/Font.ttc"
if [ ! -f "$FONT_TARGET" ] && [ -f "$FONT_SOURCE" ]; then
  sudo mkdir -p "/opt/DGTCentaurMods/resources"
  sudo cp -f "$FONT_SOURCE" "$FONT_TARGET"
  sudo chmod 0644 "$FONT_TARGET"
  log "Copied Font.ttc to $FONT_TARGET"
fi

log "Rebuild and redeploy complete. Installed: $ART_BASENAME"

