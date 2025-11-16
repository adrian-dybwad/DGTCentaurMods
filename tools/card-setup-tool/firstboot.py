#!/usr/bin/env python3
# Display progress of DGTCentaurMods installation on first boot
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
# GPLv3-or-later. See LICENSE in the project root.

import os
import time
import subprocess
import threading
from pathlib import Path
from DGTCentaurMods.display.epaper_service import service, widgets

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
    try:
        widgets.write_text(line, text)
    except Exception as e:
        print(f"[epaper] writeText failed: {e}")

# --------------------------------------------------
# Wait for network
# --------------------------------------------------
time.sleep(30)

env_noask = dict(os.environ)
env_noask["DEBIAN_FRONTEND"] = "noninteractive"

# --------------------------------------------------
# System updates & dependencies (trixie-safe)
# --------------------------------------------------
run("apt-get update", env=env_noask)
run("apt-get install -y python3 python3-pip", env=env_noask)
run("apt-get install -y libopenjp2-7 libtiff6", env=env_noask)
run("apt-get install -y python3-pil python3-serial python3-spidev", env=env_noask)

# Debian 13 marks Python as externally-managed (PEP 668).
# We skip any pip upgrades here and rely solely on distro packages.
pass

# --------------------------------------------------
# e-paper UI
# --------------------------------------------------
service.init()
sb = widgets.status_bar()
sb.start()
sb.print()

animate = True
progress = "Preparing      "

def status():
    global animate, progress
    while animate:
        for a in ["/", "-", "\\", "|"]:
            write_epaper(1, progress + "[" + a + "]")
            time.sleep(1)

msg = threading.Thread(target=status)
msg.daemon = True
msg.start()
time.sleep(0.5)

# --------------------------------------------------
# Steps
# --------------------------------------------------
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

deb_path = Path("/boot/firmware/DGTCentaurMods_armhf.deb")
if deb_path.exists():
    run(f"apt-get -y install {deb_path}", env=env_noask)
else:
    print(f"[warn] Package not found: {deb_path} (skipping)")

run("systemctl stop DGTCentaurMods.service", check=False)

animate = False
sb.stop()
time.sleep(2)
widgets.clear_screen()
time.sleep(1)

run("systemctl disable firstboot.service", check=False)
write_epaper(3, "    Rebooting")
run("rm -rf /etc/systemd/system/firstboot.service", check=False)
print("Setup done")

time.sleep(5)
run("reboot")
