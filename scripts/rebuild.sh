#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

usage() {
  echo "Usage: $0 [-b <branch|tag>]"
  echo "  -b <branch|tag>  Branch or tag to build (default: main)"
  exit 1
}

BRANCH_OR_TAG="main"

while getopts "b:h" opt; do
  case $opt in
    b) BRANCH_OR_TAG="$OPTARG" ;;
    h) usage ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))

# Always work repo-relative (portable across checkout folder names)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SCRIPTS_DIR="${REPO_DIR}/scripts"
RELEASES_DIR="${SCRIPTS_DIR}/releases"

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "Repository not found at $REPO_DIR (expecting a git repo)." >&2
  exit 1
fi

log "1/4 Updating repository and switching to '$BRANCH_OR_TAG'"
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

log "2/4 Building package from '$BRANCH_OR_TAG'"
cd "$SCRIPTS_DIR"
./build.sh "$BRANCH_OR_TAG"

log "3/4 Locating latest .deb artifact"
# Multi-arch package uses _all.deb
artifact=$(ls -1t "$RELEASES_DIR"/universal-chess_*_all.deb 2>/dev/null | head -n1 || true)
if [ -z "${artifact:-}" ] || [ ! -f "$artifact" ]; then
  echo "No .deb artifact found in $RELEASES_DIR" >&2
  exit 1
fi
log "Found artifact: $(basename "$artifact")"

log "4/4 Copying artifact to /tmp and installing"
ART_BASENAME="$(basename "$artifact")"
TMP_ART="/tmp/$ART_BASENAME"
sudo cp -f "$artifact" "$TMP_ART"
sudo apt-get -y install "$TMP_ART"

log "Rebuild and redeploy complete. Installed: $ART_BASENAME"

