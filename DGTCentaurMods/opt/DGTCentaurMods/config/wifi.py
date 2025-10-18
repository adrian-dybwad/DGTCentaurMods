# Connect to a Wifi Network
#
# (license header unchanged)

from DGTCentaurMods.ui.epaper_menu import select_from_list_epaper
from DGTCentaurMods.ui.input_adapters import poll_actions_from_board
from DGTCentaurMods.board import board
import os, time, sys, re

# OPTIONAL: the e-paper menu does its own init/clear; this is not required:
# board.initScreen()
# time.sleep(1)

# Scan for SSIDs
cmd = "sudo iwlist wlan0 scan | grep 'ESSID'"
out = os.popen(cmd).read()

# Extract ESSIDs
essids = re.findall(r'ESSID:"(.*?)"', out)
# Remove empties & dups
unique_essids = sorted({s for s in essids if s})

networks = {ssid: ssid for ssid in unique_essids}
print("----------------------------------------------------------")
print(networks)
print("----------------------------------------------------------")

# Pause event poller while the menu reads the UART
try:
    board.pauseEvents()
except Exception:
    pass

try:
    answer = select_from_list_epaper(
        options=list(networks.keys()),
        title="Wi-Fi Networks",
        poll_action=poll_actions_from_board,
        lines_per_page=7,
        font_size=18,
    )
finally:
    try:
        board.unPauseEvents()
    except Exception:
        pass

print("++++++++++++++++++++++++++++++")
print(answer)
print("++++++++++++++++++++++++++++++")

# User backed out
if not answer:
    sys.exit(0)

# Get password (getText() already pauses events internally in your updated board.py)
password = board.getText("Wifi Password")
print(password)

if password == "":
    sys.exit(0)

# Add or replace the network block in wpa_supplicant, then reconfigure
cmd = f"""sudo sh -c "wpa_passphrase '{answer}' '{password}'" """
section = os.popen(cmd).read()

if "ssid" in section:
    conf_path = "/etc/wpa_supplicant/wpa_supplicant.conf"
    with open(conf_path, "r") as f:
        curconf = f.read()

    # Remove any existing block for this SSID (non-greedy)
    newconf = re.sub(
        r'network={[^\}]+?ssid="' + re.escape(answer) + r'"[^\}]+?}\n',
        '',
        curconf,
        flags=re.DOTALL
    )

    with open(conf_path, "w") as f:
        f.write(newconf)

    with open(conf_path, "a") as f:
        f.write(section)

    os.system("sudo wpa_cli -i wlan0 reconfigure")
