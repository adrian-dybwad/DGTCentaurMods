#!/usr/bin/env python3
# Display progress of DGTCentaurMods installation on first boot
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# GPLv3-or-later. See LICENSE in the project root.

import os
import time
import subprocess
import threading
from pathlib import Path

# ----------------------------
# Helpers
# ----------------------------

def run(cmd, check=True, env=None):
    """Run a shell command, log it, and optionally enforce success."""
    print(f"+ {cmd}")
    res = subprocess.run(cmd, shell=True, env=env)
    if check and res.returncode != 0:
        raise SystemExit(f"Command failed ({res.returncode}): {cmd}")
    return res.returncode

def write_epaper(line, text):
    # Lazy import to avoid import failures before packages exist
    global epaper
    try:
        epaper.writeText(line, text)
    except Exception as e:
        print(f"[epaper] writeText failed: {e}")

# ----------------------------
# Wait for network (keep legacy behavior)
# ----------------------------
time.sleep(30)

# Noninteractive apt for scripts
env_noask = dict(os.environ)
env_noask["DEBIAN_FRONTEND"] = "noninteractive"

# ----------------------------
# System updates & dependencies (trixie-friendly)
# ----------------------------
# Use apt-get (stable API) rather than apt (human CLI).
run("apt-get update", env=env_noask)

# Core build/runtime bits
# - python3, python3-pip (for general usage)
# - libopenjp2-7, libtiff6 (runtime for Pillow on trixie)
# - Prefer distro Python packages to avoid pip wrapper/wheel issues on Py3.11
run("apt-get install -y python3 python3-pip", env=env_noask)
run("apt-get install -y libopenjp2-7 libtiff6", env=env_noask)

# Python libs via distro (avoids pip warning/compilation on trixie)
# pillow -> python3-pil, pyserial -> python3-serial, spidev -> python3-spidev
run("apt-get install -y python3-pil python3-serial python3-spidev", env=env_noask)

# Optional: keep pip tooling up to date (won't trigger the old wrapper path)
# Comment out if you want to avoid any internet fetch here.
run("python3 -m pip install --upgrade --no-input pip setuptools wheel", check=False)

# ----------------------------
# Now that Python deps exist, import epaper libs
# ----------------------------
try:
    from lib import epaper
except Exception as e:
    print(f"[warn] epaper lib not ready yet: {e}")
    # Provide a small shim so the rest of the script can continue
    class _SB:
        def start(self): pass
        def stop(self): pass
        def print(self): pass
    class _EP:
        def initEpaper(self): pass
        def statusBar(self): return _SB()
        def writeText(self, *_a, **_k): pass
        def clearScreen(self): pass
    epaper = _EP()

# ----------------------------
# Epaper status UI
# ----------------------------
epaper.initEpaper()
sb = epaper.statusBar()
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

msg = threading.Thread(target=status, args=())
msg.daemon = True
msg.start()
time.sleep(0.5)

# ----------------------------
# Steps show on e-paper
# ----------------------------
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

# Install the packaged .deb if present
deb_path = Path("/boot/DGTCentaurMods_armhf.deb")
if deb_path.exists():
    run(f"apt-get -y install {deb_path}", env=env_noask)
else:
    print(f"[warn] Package not found: {deb_path} (skipping)")

# Stop legacy/named service if it exists; ignore failure if not present
run("systemctl stop DGTCentaurMods.service", check=False)

# Tear down status UI
animate = False
sb.stop()
time.sleep(2)
epaper.clearScreen()
time.sleep(1)

# Disable & remove firstboot service (best-effort)
run("systemctl disable firstboot.service", check=False)
write_epaper(3, "    Rebooting")
run("rm -rf /etc/systemd/system/firstboot.service", check=False)
print("Setup done")

time.sleep(5)
run("reboot")
