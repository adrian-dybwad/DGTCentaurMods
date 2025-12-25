#!/usr/bin/bash

source config/build.config

# Use /var/tmp for large build artifacts (disk-backed, not tiny RAM /tmp)
BUILD_TMP="/var/tmp"

BASEDIR=`pwd`
PACKAGE="DGTCentaurMods"
INSTALLDIR="/opt/${PACKAGE}"
cd ../


function detectVersion {
    echo -e "::: Getting version"
    VERSION=`cat ${PACKAGE}/DEBIAN/control | grep Version | cut -d':' -f2 | cut -c2-`
    return
}

function stage {
    # Multi-arch package - use 'all' architecture
    STAGE="dgtcentaurmods_${VERSION}_all"
    STAGE_DIR="${BUILD_TMP}/${STAGE}"
    echo -e "::: Staging multi-arch build"
    rm -rf "${STAGE_DIR}"
    cp -r "$(basename "$PWD"/${PACKAGE})" "${STAGE_DIR}"
    
    # Set Architecture to 'all' for multi-arch package
    sed -i "s/^Architecture:.*/Architecture: all/" "${STAGE_DIR}/DEBIAN/control"
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

function prepareEngines {
    # Remove any compiled Stockfish binaries from staging
    # Stockfish will be installed from system package during postinst
    echo -e "::: Preparing engines directory"
    rm -f "${STAGE_DIR}${INSTALLDIR}/engines/stockfish"
    rm -f "${STAGE_DIR}${INSTALLDIR}/engines/stockfish_pi"
    rm -f "${STAGE_DIR}${INSTALLDIR}/engines/stockfish_pi_arm64"
    rm -f "${STAGE_DIR}${INSTALLDIR}/engines/stockfish_pi_armhf"
    echo -e "::: Stockfish will be installed from system package during installation"
}

function clean {
    echo -e "::: Cleaning"
    sudo rm -rf "${BUILD_TMP}/dgtcentaurmods_"*
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
    prepareEngines
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
