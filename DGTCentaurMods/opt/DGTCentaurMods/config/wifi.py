# Connect to a Wifi Network
#
# (license header unchanged)

from DGTCentaurMods.game.menu import doMenu
from DGTCentaurMods.board import board
import os, time, sys, re

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

# Use the existing main menu system - it already works perfectly
print("Starting WiFi menu using main menu system...")

# Convert networks list to menu format
menu = {}
for ssid in networks.keys():
    menu[ssid] = ssid

# Use the existing main menu system
answer = doMenu(menu, "Wi-Fi Networks")

# Convert answer back to network name
if answer == "BACK":
    answer = None

print("++++++++++++++++++++++++++++++")
print(answer)
print("++++++++++++++++++++++++++++++")

# User backed out
if not answer:
    sys.exit(0)

# Get password using board text input
from DGTCentaurMods.ui.get_text_from_board import getText

print("About to start password input...")

try:
    print("Calling getText function...")
    password = getText("WiFi Password", board, manage_events=False)
    print(f"getText returned: {password}")
except Exception as e:
    print(f"Error in password input: {e}")
    password = ""
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
