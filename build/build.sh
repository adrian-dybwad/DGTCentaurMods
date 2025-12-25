#!/usr/bin/env bash
set -euo pipefail

# Build a .deb from the repo's Debian staging root `packaging/deb-root/`.
#
# This script is intentionally repo-relative and does not assume a particular
# checkout folder name.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Use /var/tmp for large build artifacts (disk-backed, not tiny RAM /tmp)
BUILD_TMP="/var/tmp"
RELEASES_DIR="${SCRIPT_DIR}/releases"

DEB_ROOT="${REPO_ROOT}/packaging/deb-root"
CONTROL_FILE="${DEB_ROOT}/DEBIAN/control"

# Debian package name (control: Package) is not the same as the install dir.
OPT_DIR_NAME="universalchess"
INSTALLDIR="/opt/${OPT_DIR_NAME}"

function detectVersion {
    echo "::: Getting version/package from ${CONTROL_FILE}"
    if [ ! -f "${CONTROL_FILE}" ]; then
        echo "Missing Debian control file: ${CONTROL_FILE}" >&2
        exit 1
    fi

    DEB_PACKAGE_NAME="$(awk -F': *' '$1 == \"Package\" {print $2}' \"${CONTROL_FILE}\" | head -n1)"
    VERSION="$(awk -F': *' '$1 == \"Version\" {print $2}' \"${CONTROL_FILE}\" | head -n1)"

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

function removeDev {
    # Best-effort removal of runtime/dev artifacts that should not ship in a .deb.
    rm -f "${STAGE_DIR}${INSTALLDIR}/config/centaur.ini" || true
    rm -f "${STAGE_DIR}${INSTALLDIR}/db/centaur.db" || true
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
    setPermissions
    prepareEngines
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
