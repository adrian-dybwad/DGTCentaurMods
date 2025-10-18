# Connect to a Wifi Network
#
# (license header unchanged)

from DGTCentaurMods.ui.epaper_menu import select_from_list_epaper
from DGTCentaurMods.ui.input_adapters import poll_actions_from_board
from DGTCentaurMods.board import board
import os, time, sys, re
import threading
import queue
from typing import Optional

# OPTIONAL: the e-paper menu does its own init/clear; this is not required:
# board.initScreen()
# time.sleep(1)

# Create a robust polling function that doesn't rely on pause/unpause
wifi_button_queue = queue.Queue()
wifi_event_thread = None
wifi_callback_active = False

def wifi_button_callback(button_id):
    """Direct callback for WiFi menu button events"""
    global wifi_button_queue
    if button_id == board.BTNBACK:
        wifi_button_queue.put("BACK")
    elif button_id == board.BTNTICK:
        wifi_button_queue.put("SELECT")
    elif button_id == board.BTNUP:
        wifi_button_queue.put("UP")
    elif button_id == board.BTNDOWN:
        wifi_button_queue.put("DOWN")
    elif button_id == board.BTNHELP:
        wifi_button_queue.put("HELP")
    elif button_id == board.BTNPLAY:
        wifi_button_queue.put("PLAY")

def start_wifi_direct_polling():
    """Start direct event subscription for WiFi menu"""
    global wifi_callback_active
    if not wifi_callback_active:
        wifi_callback_active = True
        # Subscribe to events with a long timeout, just like the main menu
        board.subscribeEvents(wifi_button_callback, None, timeout=3600)
        return True
    return False

def stop_wifi_direct_polling():
    """Stop WiFi event subscription"""
    global wifi_callback_active
    if wifi_callback_active:
        wifi_callback_active = False
        # Pause events to stop our subscription
        board.pauseEvents()
        time.sleep(0.1)  # Brief pause to ensure events are stopped
        board.unPauseEvents()
        return True
    return False

def poll_wifi_actions() -> Optional[str]:
    """Get the next button action from the WiFi queue (non-blocking)"""
    global wifi_button_queue
    try:
        return wifi_button_queue.get_nowait()
    except queue.Empty:
        return None

print("Testing key loop...")
import time

# Test board communication more thoroughly
print("Board address info:")
print(f"  addr1: 0x{board.addr1:02x}")
print(f"  addr2: 0x{board.addr2:02x}")
print(f"  Serial port: {getattr(board, 'ser', 'Not available')}")

# Check if board addresses are valid (not 0x00, 0x00)
if board.addr1 == 0x00 and board.addr2 == 0x00:
    print("WARNING: Board addresses are 0x00, 0x00 - board discovery may have failed!")
    print("Attempting to reinitialize board communication...")
    
    # Try to reinitialize board communication
    try:
        # Clear any existing data
        board._ser_read(1000)
        
        # Send initialization sequence
        board._ser_write(bytearray(b'\x4d'))
        board._ser_read(1000)
        board._ser_write(bytearray(b'\x4e'))
        board._ser_read(1000)
        
        # Try to discover address again
        resp = ""
        timeout = time.time() + 10  # 10 second timeout
        while len(resp) < 4 and time.time() < timeout:
            board._ser_write(bytearray(b'\x87\x00\x00\x07'))
            resp = board._ser_read(1000)
            if len(resp) > 3:
                board.addr1 = resp[3]
                board.addr2 = resp[4]
                print(f"  Rediscovered address: 0x{board.addr1:02x}, 0x{board.addr2:02x}")
                break
            time.sleep(0.1)
        
        if board.addr1 == 0x00 and board.addr2 == 0x00:
            print("  FAILED: Could not rediscover board address")
        else:
            print("  SUCCESS: Board address rediscovered")
            
    except Exception as e:
        print(f"  Board reinitialization error: {e}")

# Test raw board communication
print("Testing raw board communication...")
try:
    board.sendPacket(b'\x83', b'')
    resp = board._ser_read(256)
    print(f"  Board state response: {resp.hex() if resp else 'No response'}")
except Exception as e:
    print(f"  Board state error: {e}")

try:
    board.sendPacket(b'\x94', b'')
    resp = board._ser_read(256)
    print(f"  Key event response: {resp.hex() if resp else 'No response'}")
    
    # Try multiple key event requests to see if we get any response
    print("  Testing multiple key event requests...")
    for i in range(5):
        board.sendPacket(b'\x94', b'')
        resp = board._ser_read(256)
        if resp:
            print(f"    Attempt {i+1}: {resp.hex()}")
        else:
            print(f"    Attempt {i+1}: No response")
        time.sleep(0.1)
        
except Exception as e:
    print(f"  Key event error: {e}")

key_count = 0
print("Testing key detection loop...")
for i in range(50):
    act = poll_actions_from_board()
    if act:
        print(f"KEY[{i}]: {act}")
        key_count += 1
    if i % 10 == 0:
        print(f"  Progress: {i}/50 attempts")
    time.sleep(0.1)

print(f"Key detection test: {key_count} keys detected out of 50 attempts")
if key_count == 0:
    print("WARNING: No keys detected! Board communication may be failing.")
    print("Possible causes:")
    print("  1. Board not connected or powered")
    print("  2. Serial port issues")
    print("  3. Board address discovery failed")
    print("  4. Board firmware issues")
    
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

# Use direct event subscription like the main menu does
print("Starting WiFi menu with direct event polling...")
start_wifi_direct_polling()

try:
    answer = select_from_list_epaper(
        options=list(networks.keys()),
        title="Wi-Fi Networks",
        poll_action=poll_wifi_actions,
        highlight_index=0,
        lines_per_page=7,
        font_size=18,
    )
except Exception as e:
    print(f"Error in WiFi menu: {e}")
    answer = None
finally:
    print("Stopping WiFi direct polling...")
    stop_wifi_direct_polling()

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
