#!/usr/bin/env bash
set -euo pipefail

# Build a .deb from the repo's Debian staging root `packaging/deb-root/`.
#
# This script is intentionally repo-relative and does not assume a particular
# checkout folder name.
#
# Usage:
#   ./build.sh              - Build package (standard)
#   ./build.sh --with-lc0   - Build package with lc0/Maia engine (takes ~30 min on Pi)
#   ./build.sh clean        - Clean build artifacts

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Parse arguments
BUILD_LC0=false
for arg in "$@"; do
    case "$arg" in
        --with-lc0)
            BUILD_LC0=true
            ;;
    esac
done

# Use /var/tmp for large build artifacts (disk-backed, not tiny RAM /tmp)
BUILD_TMP="/var/tmp"
RELEASES_DIR="${SCRIPT_DIR}/releases"

function _find_control_file {
    # Prefer the new layout first, then fall back to any DEBIAN/control found.
    local preferred="${REPO_ROOT}/packaging/deb-root/DEBIAN/control"
    if [ -f "${preferred}" ]; then
        echo "${preferred}"
        return 0
    fi

    # Search for a Debian control file in a bounded depth to avoid scanning the world.
    # Note: macOS/BSD find supports -maxdepth; Debian find also supports it.
    local found
    found="$(find "${REPO_ROOT}" -maxdepth 5 -type f -path '*/DEBIAN/control' 2>/dev/null | head -n1 || true)"
    if [ -n "${found}" ] && [ -f "${found}" ]; then
        echo "${found}"
        return 0
    fi

    return 1
}

CONTROL_FILE="$(_find_control_file || true)"
if [ -z "${CONTROL_FILE}" ] || [ ! -f "${CONTROL_FILE}" ]; then
    echo "Missing Debian control file under repo root: ${REPO_ROOT}" >&2
    echo "Expected one of:" >&2
    echo "  - ${REPO_ROOT}/packaging/deb-root/DEBIAN/control" >&2
    echo "  - <any path matching */DEBIAN/control within 5 levels>" >&2
    exit 1
fi

# Debian staging root is the parent directory of DEBIAN/
DEB_ROOT="$(cd "$(dirname "${CONTROL_FILE}")/.." && pwd)"

# Debian package name (control: Package) is not the same as the install dir.
OPT_DIR_NAME="universalchess"
INSTALLDIR="/opt/${OPT_DIR_NAME}"

function detectVersion {
    echo "::: Getting version/package from ${CONTROL_FILE}"
    # CONTROL_FILE is resolved early and must exist by this point.

    # Use grep/cut to avoid awk quoting issues across environments.
    DEB_PACKAGE_NAME="$(grep -m1 '^Package:' "${CONTROL_FILE}" | cut -d':' -f2- | xargs)"
    VERSION="$(grep -m1 '^Version:' "${CONTROL_FILE}" | cut -d':' -f2- | xargs)"

    if [ -z "${DEB_PACKAGE_NAME}" ] || [ -z "${VERSION}" ]; then
        echo "Failed to parse Package/Version from ${CONTROL_FILE}" >&2
        exit 1
    fi
}

function stage {
    # Multi-arch package - use 'all' architecture for a pure-Python payload.
    STAGE_ARCH="all"
    STAGE="${DEB_PACKAGE_NAME}_${VERSION}_${STAGE_ARCH}"
    STAGE_DIR="${BUILD_TMP}/${STAGE}"

    echo "::: Staging build at ${STAGE_DIR}"
    rm -rf "${STAGE_DIR}"
    mkdir -p "${STAGE_DIR}"

    # Copy Debian staging root into temp stage dir (portable across GNU/BSD tar).
    (cd "${DEB_ROOT}" && tar -cf - .) | (cd "${STAGE_DIR}" && tar -xf -)

    # Ensure the installed python package is present under /opt/universalchess.
    # The canonical source lives in the repo at src/universalchess (src-layout).
    mkdir -p "${STAGE_DIR}${INSTALLDIR}"
    (
      cd "${REPO_ROOT}/src/universalchess" \
        && tar --exclude="__pycache__" --exclude="*.pyc" -cf - .
    ) | (cd "${STAGE_DIR}${INSTALLDIR}" && tar -xf -)

    # Set Architecture to 'all' for multi-arch package
    python3 - <<PY
from pathlib import Path
p = Path("${STAGE_DIR}") / "DEBIAN" / "control"
lines = p.read_text(encoding="utf-8").splitlines(True)
out = []
replaced = False
for line in lines:
    if line.startswith("Architecture:"):
        out.append("Architecture: all\\n")
        replaced = True
    else:
        out.append(line)
if not replaced:
    out.append("Architecture: all\\n")
p.write_text("".join(out), encoding="utf-8")
PY
}

function setPermissions {
    echo "::: Setting permissions"
    # Ensure maintainer scripts are executable if present
    if [ -d "${STAGE_DIR}/DEBIAN" ]; then
        chmod 0755 "${STAGE_DIR}/DEBIAN/"post* "${STAGE_DIR}/DEBIAN/"pre* 2>/dev/null || true
    fi

    # Some setups expect /opt/universalchess/engines writable for engine installs.
    if [ -d "${STAGE_DIR}${INSTALLDIR}/engines" ]; then
        chmod 0777 "${STAGE_DIR}${INSTALLDIR}/engines" || true
    fi
}

function prepareEngines {
    # Remove any compiled Stockfish binaries from staging.
    # Stockfish will be installed from system package during postinst.
    echo "::: Preparing engines directory"
    rm -f "${STAGE_DIR}${INSTALLDIR}/engines/stockfish" \
          "${STAGE_DIR}${INSTALLDIR}/engines/stockfish_pi" \
          "${STAGE_DIR}${INSTALLDIR}/engines/stockfish_pi_arm64" \
          "${STAGE_DIR}${INSTALLDIR}/engines/stockfish_pi_armhf" || true
    echo "::: Stockfish will be installed from system package during installation"
}

function buildLc0 {
    if [[ "$BUILD_LC0" != "true" ]]; then
        echo "::: Skipping lc0 build (use --with-lc0 to include)"
        return 0
    fi
    
    echo "::: Building lc0/Maia engine (this may take 20-30 minutes on Raspberry Pi)..."
    
    local lc0_build_script="${SCRIPT_DIR}/engines/build-lc0.sh"
    local lc0_output_dir="${STAGE_DIR}${INSTALLDIR}/engines"
    
    if [[ ! -x "$lc0_build_script" ]]; then
        echo "ERROR: lc0 build script not found: $lc0_build_script" >&2
        exit 1
    fi
    
    # Create engines directory if it doesn't exist
    mkdir -p "$lc0_output_dir"
    
    # Run the lc0 build script
    if ! "$lc0_build_script" "$lc0_output_dir"; then
        echo "ERROR: lc0 build failed" >&2
        exit 1
    fi
    
    echo "::: lc0/Maia engine built successfully"
    ls -la "${lc0_output_dir}/lc0" 2>/dev/null || true
    ls -la "${lc0_output_dir}/maia_weights/" 2>/dev/null || true
}

function removeDev {
    # Best-effort removal of runtime/dev artifacts that should not ship in a .deb.
    rm -f "${STAGE_DIR}${INSTALLDIR}/config/centaur.ini" || true
    rm -f "${STAGE_DIR}${INSTALLDIR}/db/centaur.db" || true
}

function createVersionFile {
    # Create VERSION file for update checker to read
    echo "::: Creating VERSION file"
    echo "${VERSION}" > "${STAGE_DIR}${INSTALLDIR}/VERSION"
}

function build {
    echo "::: Building ${DEB_PACKAGE_NAME} version ${VERSION}"
    mkdir -p "${RELEASES_DIR}"
    rm -f "${RELEASES_DIR}/${STAGE}.deb"

    dpkg-deb --root-owner-group -Zgzip --build "${STAGE_DIR}" "${RELEASES_DIR}/${STAGE}.deb"

    # Free staging immediately
    rm -rf "${STAGE_DIR}"
}

function clean {
    echo "::: Cleaning"
    rm -rf "${BUILD_TMP}/universal-chess_"* "${BUILD_TMP}/dgtcentaurmods_"* 2>/dev/null || true
    rm -rf "${RELEASES_DIR}" 2>/dev/null || true
}

function main {
    clean 2>/dev/null || true
    detectVersion
    stage
    removeDev
    createVersionFile
    setPermissions
    prepareEngines
    buildLc0
    build
}

case "${1:-}" in
    clean* )
        clean
        ;;
    * )
        main
        ;;
esac
