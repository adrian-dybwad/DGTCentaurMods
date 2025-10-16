#!/usr/bin/bash

source config/build.config

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
    echo -e "::: Staging build"
    cp -r $(basename "$PWD"/${PACKAGE}) /tmp/${STAGE}
    return
}

function setPermissions {
    echo -e "::: Setting permissions"
    sudo chown root.root /tmp/${STAGE}/etc
    sudo chmod 777 /tmp/${STAGE}/opt/${PACKAGE}/engines
    return
}

function build {
    echo -e "::: Building version ${VERSION}"
    if [ ! -d ${BASEDIR}/releases ]; then mkdir ${BASEDIR}/releases; fi
    dpkg-deb --build /tmp/${STAGE} ${BASEDIR}/releases/${STAGE}.deb
    return
}

function insertStockfish {
    REPLY="Y"
    if [ $FULL -eq 1 ]; then
        read -p "Do you want to compile and insert Stockfinsh in this build? (y/n): "
    fi
    case $REPLY in
        [Yy]* )
            cd /tmp
            echo -e "Cloning Stockfish repo"
            git clone $STOCKFISH_REPO

            # Ensure sqlite headers & pkg-config exist for portable flags
            if ! dpkg-query -W -f='${Status}' libsqlite3-dev 2>/dev/null | grep -q "ok installed"; then
                sudo apt-get update -y
                sudo apt-get install -y libsqlite3-dev
            fi
            if ! command -v pkg-config >/dev/null 2>&1; then
                sudo apt-get update -y
                sudo apt-get install -y pkg-config
            fi

            # Recompute flags now that pkg-config may exist
            SQLITE_CFLAGS="$(pkg-config --cflags sqlite3 2>/dev/null || echo -I/usr/include)"
            SQLITE_LIBS="$(pkg-config --libs sqlite3 2>/dev/null || echo -lsqlite3)"

            # Patch bad absolute include if present (switch to #include <sqlite3.h>)
            # This avoids /usr/local/include/sqlite3.h hardcoding in third-party sources.
            if grep -Rq '^#include "/usr/local/include/sqlite3\.h"' /tmp/Stockfish/src 2>/dev/null; then
                echo "::: Patching Stockfish sqlite include"
                sed -i 's|^#include "/usr/local/include/sqlite3\.h"|#include <sqlite3.h>|' /tmp/Stockfish/src/uci.cpp 2>/dev/null || true
            fi

            cd /tmp/Stockfish/src
            make clean

            # Build with portable SQLite flags; also pass them to linker.
            # You can add ARCH_FLAGS (e.g., -mfpu=neon-vfpv4) if desired.
            CXXFLAGS="${CXXFLAGS} ${SQLITE_CFLAGS}" \
            LDFLAGS="${LDFLAGS} ${SQLITE_LIBS}" \
            make -j"$(nproc)" build ARCH=armv7 COMP=gcc ARCH_FLAGS="-mfpu=neon-vfpv4"

            # Verify binary exists before moving
            if [ ! -f stockfish ]; then
                echo "ERROR: Stockfish build failed (no stockfish binary). See build log above."
                exit 1
            fi

            mv stockfish stockfish_pi
            cp stockfish_pi /tmp/${STAGE}${INSTALLDIR}/engines
            return
            ;;
        [Nn]* ) return
            ;;
    esac
}

function clean {
    echo -e "::: Cleaning"
    sudo rm -rf /tmp/dgtcentaurmods*
    rm -rf ${BASEDIR}/releases
    rm -rf /tmp/Stockfish
}

function removeDev {
    #All files in repo that are used in development stage are removed here
    rm /tmp/${STAGE}/opt/${PACKAGE}/config/centaur.ini
    rm /tmp/${STAGE}/opt/${PACKAGE}/db/centaur.db
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
