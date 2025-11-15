#!/usr/bin/env python3
# Display progress of DGTCentaurMods installation on first boot
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
# GPLv3-or-later. See LICENSE in the project root.

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# --------------------------------------------------
# Constants & globals
# --------------------------------------------------

DEFAULT_DEB = Path("/boot/firmware/DGTCentaurMods_armhf.deb")
EXTRACT_DIR = Path("/tmp/dgtcm_firstboot")

service = None
widgets = None


# --------------------------------------------------
# Helper functions
# --------------------------------------------------

def run(cmd, check=True, env=None):
    """Run a shell command and log it."""
    print(f"+ {cmd}")
    res = subprocess.run(cmd, shell=True, env=env)
    if check and res.returncode != 0:
        raise SystemExit(f"Command failed ({res.returncode}): {cmd}")
    return res.returncode


def write_epaper(line, text):
    global widgets
    if widgets is None:
        return
    try:
        widgets.write_text(line, text)
    except Exception as e:
        print(f"[epaper] write_text failed: {e}")


def _extract_package(deb_path: Path, extract_dir: Path) -> Path:
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    run(f"dpkg-deb -x {deb_path} {extract_dir}")
    opt_path = extract_dir / "opt"
    if not opt_path.exists():
        raise FileNotFoundError(f"Extracted package missing opt directory: {opt_path}")
    opt_str = str(opt_path)
    if opt_str not in sys.path:
        sys.path.insert(0, opt_str)
    importlib.invalidate_caches()
    return opt_path


def _bootstrap_display_modules(deb_path: Path = DEFAULT_DEB,
                               extract_dir: Path = EXTRACT_DIR):
    try:
        from DGTCentaurMods.display.epaper_service import service as svc, widgets as w  # type: ignore
        return svc, w
    except ModuleNotFoundError:
        if not deb_path.exists():
            raise
        _extract_package(deb_path, extract_dir)
        from DGTCentaurMods.display.epaper_service import service as svc, widgets as w  # type: ignore
        return svc, w


# --------------------------------------------------
# Main workflow
# --------------------------------------------------

def main():
    global service, widgets

    service, widgets = _bootstrap_display_modules()

    # Wait for network and package managers to settle
    time.sleep(30)

    env_noask = dict(os.environ)
    env_noask["DEBIAN_FRONTEND"] = "noninteractive"

    service.init()
    sb = widgets.status_bar()
    sb.start()
    sb.print()

    animate = True
    progress = "Preparing      "

    def status():
        nonlocal animate, progress
        while animate:
            for a in ["/", "-", "\\", "|"]:
                write_epaper(1, progress + "[" + a + "]")
                time.sleep(1)
                if not animate:
                    break

    msg = threading.Thread(target=status, daemon=True)
    msg.start()
    time.sleep(0.5)

    write_epaper(3, "[1/3] Setup OS")
    run("sleep 10")

    progress = "Updating       "
    write_epaper(4, "[2/3] Updating")
    write_epaper(5, "    Raspberry Pi OS")
    run("apt-get update", env=env_noask)
    run("apt-get -y full-upgrade", env=env_noask)

    progress = "Installing     "
    write_epaper(6, "[3/3] Installing")
    write_epaper(7, "    DGTCM")

    if DEFAULT_DEB.exists():
        run(f"apt-get -y install {DEFAULT_DEB}", env=env_noask)
    else:
        print(f"[warn] Package not found: {DEFAULT_DEB} (skipping)")

    run("systemctl stop DGTCentaurMods.service", check=False)

    animate = False
    msg.join(timeout=0.1)
    sb.stop()
    time.sleep(2)
    widgets.clear_screen()
    time.sleep(1)

    run("systemctl disable firstboot.service", check=False)
    write_epaper(3, "    Rebooting")
    run("rm -rf /etc/systemd/system/firstboot.service", check=False)
    print("Setup done")

    time.sleep(5)
    service.shutdown()
    run("reboot")


if __name__ == "__main__":
    main()

