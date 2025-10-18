# Connect to a Wifi Network
#
# (license header unchanged)

from DGTCentaurMods.ui.epaper_menu import select_from_list_epaper
from DGTCentaurMods.ui.input_adapters import start_wifi_subscription, stop_wifi_subscription, do_wifi_menu
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

# Use the event-based WiFi menu (same pattern as main menu)
print("Starting WiFi menu with event-based system...")

# Convert networks list to menu format
menu = {}
for i, ssid in enumerate(networks.keys()):
    menu[f"network_{i}"] = ssid

# Initialize WiFi menu state before subscribing
from DGTCentaurMods.ui.input_adapters import wifi_curmenu, wifi_menuitem
wifi_curmenu = menu
wifi_menuitem = 1

# Start WiFi subscription
if start_wifi_subscription():
    try:
        # Use event-based menu
        answer = do_wifi_menu(menu, "Wi-Fi Networks")
        
        # Convert answer back to network name
        if answer and answer != "BACK":
            answer = menu[answer]
        else:
            answer = None
            
    except Exception as e:
        print(f"Error in WiFi menu: {e}")
        answer = None
    finally:
        # Always stop WiFi subscription when done
        stop_wifi_subscription()
        print("WiFi subscription stopped")
else:
    print("Failed to start WiFi subscription")
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
