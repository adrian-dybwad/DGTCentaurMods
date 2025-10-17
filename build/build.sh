#!/usr/bin/bash

source config/build.config

# Use /var/tmp for large build artifacts (disk-backed, not tiny RAM /tmp)
BUILD_TMP="/var/tmp"

BASEDIR=`pwd`
PACKAGE="DGTCentaurMods"
INSTALLDIR="/opt/${PACKAGE}"
cd ../

# -------- SQLite (portable) flags --------
# Use pkg-config when present; fall back to system locations.
# We also ensure pkg-config and libsqlite3-dev exist when building Stockfish.
SQLITE_CFLAGS="$(pkg-config --cflags sqlite3 2>/dev/null || echo -I/usr/include)"
SQLITE_LIBS="$(pkg-config --libs sqlite3 2>/dev/null || echo -lsqlite3)"

function detectVersion {
    echo -e "::: Getting version"
    VERSION=`cat ${PACKAGE}/DEBIAN/control | grep Version | cut -d':' -f2 | cut -c2-`
    return
}

function stage {
    STAGE="dgtcentaurmods_${VERSION}_armhf"
    STAGE_DIR="${BUILD_TMP}/${STAGE}"
    echo -e "::: Staging build"
    rm -rf "${STAGE_DIR}"
    cp -r "$(basename "$PWD"/${PACKAGE})" "${STAGE_DIR}"
    return
}

function setPermissions {
    echo -e "::: Setting permissions"
    sudo chown root:root "${STAGE_DIR}/etc"
    sudo chmod 777 "${STAGE_DIR}/opt/${PACKAGE}/engines"
    return
}

function build {
    echo -e "::: Building version ${VERSION}"
    if [ ! -d ${BASEDIR}/releases ]; then mkdir ${BASEDIR}/releases; fi
    rm -f ${BASEDIR}/releases/${STAGE}.deb
    # Use gzip (lighter on tmp space) and correct ownership
    dpkg-deb --root-owner-group -Zgzip --build "${STAGE_DIR}" ${BASEDIR}/releases/${STAGE}.deb
    # Free staging immediately
    sudo rm -rf "${STAGE_DIR}"
    return
}

function insertStockfish {
    REPLY="Y"
    if [ $FULL -eq 1 ]; then
        read -p "Do you want to compile and insert Stockfinsh in this build? (y/n): "
    fi 
    case $REPLY in
        [Yy]* )
            cd "${BUILD_TMP}"
            echo -e "Cloning Stockfish repo"
            rm -rf Stockfish
            git clone $STOCKFISH_REPO

            if [ $(dpkg-query -W -f='${Status}' libsqlite3-dev 2>/dev/null | grep -c "ok installed") -eq 0 ]; then
                sudo apt-get update -y
                sudo apt-get install -y libsqlite3-dev
            fi

            # Patch include if needed
            sed -i 's|^#include "/usr/local/include/sqlite3\.h"|#include <sqlite3.h>|' Stockfish/src/uci.cpp 2>/dev/null || true

            cd Stockfish/src
            # Strip bogus -I pointing to a file (cosmetic)
            sed -i 's|-I/usr/local/include/sqlite3\.h||g' Makefile 2>/dev/null || true
            sed -i 's|-I/usr/local/include/sqlite3\.h||g' ../Makefile 2>/dev/null || true

            make clean
            make -j"$(nproc)" build ARCH=armv7

            mv stockfish stockfish_pi
            cp stockfish_pi "${STAGE_DIR}${INSTALLDIR}/engines"
            return
            ;;
        [Nn]* ) return ;;
    esac
}

function clean {
    echo -e "::: Cleaning"
    sudo rm -rf "${BUILD_TMP}/dgtcentaurmods_"* "${BUILD_TMP}/Stockfish"
    rm -rf ${BASEDIR}/releases
}

function removeDev {
    rm -f "${STAGE_DIR}/opt/${PACKAGE}/config/centaur.ini"
    rm -f "${STAGE_DIR}/opt/${PACKAGE}/db/centaur.db"
}

function main() {
    clean 2>/dev/null
    detectVersion
    stage
    removeDev 2>/dev/null
    setPermissions
    insertStockfish
    build
}

## MAIN ##
case $1 in
    clean* )
        clean
        ;;
    full* )
        FULL=1
        main
        ;;
    * )
        FULL=0
        main
        ;;
esac

exit 0
