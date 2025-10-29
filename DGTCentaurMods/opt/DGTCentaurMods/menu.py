# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

import configparser
import os
import pathlib
import sys
import threading
import time
import logging
import urllib.request
import json
import socket
import subprocess
import os
from DGTCentaurMods.display.ui_components import AssetManager

try:
    logging.basicConfig(level=logging.DEBUG, filename="/home/pi/debug.log",filemode="w")
except:
    logging.basicConfig(level=logging.DEBUG)

from DGTCentaurMods.board import *
from DGTCentaurMods.display import epaper
from PIL import Image, ImageDraw, ImageFont

menuitem = 1
curmenu = None
selection = ""
centaur_software = "/home/pi/centaur/centaur"

event_key = threading.Event()
idle = False # ensure defined before keyPressed can be called


def keyPressed(id):
    # This functiion receives key presses
    print("in menu.py keyPressed: " + str(id))
    global shift
    global menuitem
    global curmenu
    global selection
    global event_key
    epaper.epapermode = 1    
    if idle:
        if id == board.Key.TICK:
            event_key.set()
            return
    else:
        if id == board.Key.TICK:
            if not curmenu:
                selection = "BTNTICK"
                #print(selection)
                # event_key.set()
                return
            c = 1
            r = ""
            for k, v in curmenu.items():
                if c == menuitem:
                    selection = k
                    #print(selection)
                    event_key.set()
                    menuitem = 1
                    return
                c = c + 1

        if id == board.Key.LONG_PLAY:
            board.shutdown()
            return
        if id == board.Key.DOWN:
            menuitem = menuitem + 1
        if id == board.Key.UP:
            menuitem = menuitem - 1
        if id == board.Key.BACK:
            selection = "BACK"
            event_key.set()
            return
        if id == board.Key.HELP:
            selection = "BTNHELP"
            event_key.set()
            return
        if curmenu is None:
            return
        if menuitem < 1:
            menuitem = len(curmenu)
        if menuitem > len(curmenu):
            menuitem = 1       
        epaper.clearArea(0, 20 + shift, 17, 295)
        draw = ImageDraw.Draw(epaper.epaperbuffer)
        draw.polygon(
            [
                (2, (menuitem * 20 + shift) + 2),
                (2, (menuitem * 20) + 18 + shift),
                (17, (menuitem * 20) + 10 + shift),
            ],
            fill=0,
        )
        draw.line((17, 20 + shift, 17, 295), fill=0, width=1)


quickselect = 0

COLOR_MENU = {"white": "White", "black": "Black", "random": "Random"}

MENU_CONFIG = {
    "EmulateEB": {
        "title": "e-Board",
        "description": "Emulate DGT Classic or Millennium electronic boards for compatibility",
        "items": {"dgtclassic": "DGT REVII", "millennium": "Millennium"}
    },
    "settings": {
        "title": "Settings",
        "description": "Configure WiFi, Bluetooth, sound, updates, and system settings",
        "items": None  # Built dynamically
    },
    "Lichess": {
        "title": "Lichess",
        "description": "Play online games and challenges on Lichess.org with your account",
        "items": {"Rated": "Rated", "Unrated": "Unrated", "Ongoing": "Ongoing", "Challenges": "Challenges"}
    },
    "Engines": {
        "title": "Engines",
        "description": "Play against computer opponents with various difficulty levels",
        "items": None  # Built dynamically
    },
    "HandBrain": {
        "title": "Hand + Brain",
        "description": "Two-player cooperative mode where one sees the board and the other calls moves",
        "items": None  # Built dynamically (uses enginemenu)
    }
}

def doMenu(menu_or_key, title_or_key=None, description=None):
    """
    Display a menu and wait for user selection.
    
    Args:
        menu_or_key: Either a menu dict {"key": "Display"} or a config key string
        title_or_key: Either a title string, a config key, or None
        description: Menu description (optional, can be looked up from config)
    
    Returns:
        Selected menu key or "BACK"
    """
    actual_menu = None
    actual_title = None
    actual_description = None
    
    # Case 1: menu_or_key is a config key (e.g., "EmulateEB" or "Lichess")
    if isinstance(menu_or_key, str) and menu_or_key in MENU_CONFIG:
        config = MENU_CONFIG[menu_or_key]
        actual_menu = config.get("items")
        actual_title = config.get("title")
        actual_description = config.get("description")
    
    # Case 2: menu_or_key is a dict and title_or_key is a config key (e.g., enginemenu, "Engines")
    elif isinstance(menu_or_key, dict) and isinstance(title_or_key, str) and title_or_key in MENU_CONFIG:
        config = MENU_CONFIG[title_or_key]
        actual_menu = menu_or_key
        actual_title = config.get("title")
        actual_description = config.get("description")
    
    # Case 3: Explicit parameters (backward compatible)
    else:
        actual_menu = menu_or_key
        actual_title = title_or_key
        actual_description = description
    
    print(f"doMenu: {actual_menu}, Title: {actual_title}, Description: {actual_description}")
    global shift
    global menuitem
    global curmenu
    global selection
    global quickselect
    global event_key
    epaper.epapermode = 0
    epaper.clearScreen()  
    
    selection = ""
    curmenu = actual_menu
    # Display the given menu
    menuitem = 1
    quickselect = 0    

    quickselect = 1    
    if actual_title:
        row = 2
        shift = 20
        epaper.writeMenuTitle("[ " + actual_title + " ]")
    else:
        shift = 0
        row = 1
    # Print a fresh status bar.
    statusbar.print()
    epaper.pauseEpaper()
    for k, v in actual_menu.items():
        epaper.writeText(row, "    " + str(v))
        row = row + 1
    
    # Display description if provided
    if actual_description and actual_description.strip():
        # Create background rectangle covering the right side area
        description_y = (row * 20) + 2 + shift
        description_height = 108  # Height for description area (allows 9 lines: 9 * 12px)
        draw = ImageDraw.Draw(epaper.epaperbuffer)
        
        # Draw background rectangle covering right side (from vertical line to screen edge)
        draw.rectangle([17, description_y, 127, description_y + description_height], fill=255)
        
        # Position text with more space from vertical line
        description_x = 22  # Start after vertical line (17) with 5px margin
        description_text_y = description_y + 2  # Small margin from top
        
        # Use 16px font for description
        small_font = ImageFont.truetype(epaper.AssetManager.get_resource_path("Font.ttc"), 16)
        
        # Wrap text to fit within the available width
        max_width = 127 - description_x - 2  # Available width minus margins (now 103px)
        words = actual_description.split()
        lines = []
        current_line = ""
        
        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            bbox = draw.textbbox((0, 0), test_line, font=small_font)
            text_width = bbox[2] - bbox[0]
            
            if text_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                    current_line = word
                else:
                    lines.append(word)  # Single word too long, add anyway
        
        if current_line:
            lines.append(current_line)
        
        # Draw each line
        for i, line in enumerate(lines[:9]):  # Limit to 9 lines max (fits in 108px height)
            y_pos = description_text_y + (i * 16)  # 16px line spacing
            draw.text((description_x, y_pos), line, font=small_font, fill=0)
    
    epaper.unPauseEpaper()    
    time.sleep(0.1)
    epaper.clearArea(0, 20 + shift, 17, 295)
    draw = ImageDraw.Draw(epaper.epaperbuffer)
    draw.polygon(
        [
            (2, (menuitem * 20) + 2 + shift),
            (2, (menuitem * 20) + 18 + shift),
            (17, (menuitem * 20) + 10 + shift),
        ],
        fill=0,
    )
    draw.line((17, 20 + shift, 17, 295), fill=0, width=1)
    statusbar.print()         
    event_key.wait()
    event_key.clear()
    return selection

def changedCallback(field):
    print(f"DEBUG: changedCallback: {field}")
    board.printBoardState()


# Turn Leds off, beep, clear DGT Centaur Serial
# Initialise the epaper display - after which functions in epaper.py are available but you can also draw to the
# image epaper.epaperbuffer to change the screen.
board.ledsOff()
board.beep(board.SOUND_POWER_ON)
epaper.initEpaper(1)
statusbar = epaper.statusBar()
statusbar.start()
update = centaur.UpdateSystem()
logging.debug("Setting checking for updates in 5 mins.")
threading.Timer(300, update.main).start()
# Subscribe to board events. First parameter is the function for key presses. The second is the function for
# field activity
board.subscribeEvents(keyPressed, changedCallback, timeout=900)

def show_welcome():
    global idle
    epaper.welcomeScreen()
    idle = True
    event_key.wait()
    event_key.clear()
    idle = False


show_welcome()
epaper.quickClear()


def run_external_script(script_rel_path: str, *args: str, start_key_polling: bool = True) -> int:
    try:
        epaper.loadingScreen()
        board.pauseEvents()
        board.cleanup(leds_off=True)
        statusbar.stop()

        script_path = str((pathlib.Path(__file__).parent / script_rel_path).resolve())
        print(f"script_path: {script_path}")
        cmd = [sys.executable, script_path, *map(str, args)]
        result = subprocess.run(cmd, check=False)
        return result.returncode
    finally:
        print(">>> Reinitializing after external script...")
        epaper.initEpaper()
        print(">>> epaper.initEpaper() complete")
        epaper.quickClear()
        print(">>> epaper.quickClear() complete")
        board.run_background(start_key_polling=start_key_polling)
        print(">>> board.run_background() complete")
        board.unPauseEvents()
        print(">>> board.unPauseEvents() complete")
        statusbar.start()
        print(">>> statusbar.start() complete")


def bluetooth_pairing():
    """
    Run Bluetooth pairing mode with timeout.
    Displays pairing instructions on e-paper screen.
    
    Returns:
        bool: True if device paired successfully, False on timeout
    """
    from DGTCentaurMods.board.bluetooth_utils import BluetoothManager
    
    epaper.clearScreen()
    epaper.writeText(0, "Pair Now use")
    epaper.writeText(1, "any passcode if")
    epaper.writeText(2, "prompted.")
    epaper.writeText(4, "Times out in")
    epaper.writeText(5, "one minute.")
    
    def on_device_detected():
        """Callback when pairing device is detected"""
        epaper.writeText(8, "Pairing...")
    
    # Start pairing with 60 second timeout
    paired = BluetoothManager.start_pairing(
        timeout=60, 
        on_device_detected=on_device_detected
    )
    
    # Show result
    epaper.clearScreen()
    if paired:
        epaper.writeText(0, "Paired!")
        time.sleep(2)
    else:
        epaper.writeText(0, "Pairing timeout")
        time.sleep(2)
    epaper.clearScreen()
    
    return paired


def chromecast_menu():
    """
    Select and start Chromecast display.
    
    Discovers available Chromecasts, presents menu for selection,
    and launches background cchandler process to stream board display.
    """
    import pychromecast
    
    # Kill any existing cchandler processes
    os.system("ps -ef | grep 'cchandler.py' | grep -v grep | awk '{print $2}' | xargs -r kill -9")
    
    # Discover Chromecasts
    epaper.clearScreen()
    epaper.writeText(0, "Discovering...")
    epaper.writeText(1, "Chromecasts...")
    time.sleep(1)
    
    try:
        chromecasts = pychromecast.get_chromecasts()
    except Exception as e:
        epaper.clearScreen()
        epaper.writeText(0, "Discovery failed")
        epaper.writeText(1, str(e)[:20])
        time.sleep(2)
        return
    
    # Build menu of available Chromecasts (cast type only, not audio devices)
    cc_menu = {}
    cc_mapping = {}  # Map menu keys to actual Chromecast objects
    
    for idx, cc in enumerate(chromecasts[0]):
        if cc.device.cast_type == 'cast':
            friendly_name = cc.device.friendly_name
            # Use friendly name as both key and display value
            cc_menu[friendly_name] = friendly_name
            cc_mapping[friendly_name] = cc
    
    if not cc_menu:
        epaper.clearScreen()
        epaper.writeText(0, "No Chromecasts")
        epaper.writeText(1, "found")
        time.sleep(2)
        return
    
    # Let user select Chromecast using main menu system
    result = doMenu(cc_menu, "Chromecast")
    
    if result == "BACK":
        return
    
    # Launch cchandler in background for selected Chromecast
    cchandler_path = str(pathlib.Path(__file__).parent / 'display' / 'cchandler.py')
    cmd = f'{sys.executable} "{cchandler_path}" "{result}" &'
    os.system(cmd)
    
    # Show feedback
    epaper.clearScreen()
    epaper.writeText(0, "Streaming to:")
    # Truncate long names to fit on screen (20 chars per line)
    if len(result) > 20:
        epaper.writeText(1, result[:20])
        if len(result) > 40:
            epaper.writeText(2, result[20:40])
        else:
            epaper.writeText(2, result[20:])
    else:
        epaper.writeText(1, result)
    time.sleep(2)


def connect_to_wifi(ssid, password):
    """
    Connect to a WiFi network by configuring wpa_supplicant.
    
    Args:
        ssid: The network SSID to connect to
        password: The WiFi password
        
    Returns:
        bool: True if configuration succeeded, False otherwise
    """
    import re
    
    try:
        # Generate wpa_supplicant network block
        cmd = f"""sudo sh -c "wpa_passphrase '{ssid}' '{password}'" """
        section = os.popen(cmd).read()
        
        if "ssid" not in section:
            print("Failed to generate network configuration")
            return False
        
        conf_path = "/etc/wpa_supplicant/wpa_supplicant.conf"
        
        # Read current configuration
        with open(conf_path, "r") as f:
            curconf = f.read()
        
        # Remove any existing block for this SSID (non-greedy)
        newconf = re.sub(
            r'network={[^\}]+?ssid="' + re.escape(ssid) + r'"[^\}]+?}\n',
            '',
            curconf,
            flags=re.DOTALL
        )
        
        # Write updated configuration
        with open(conf_path, "w") as f:
            f.write(newconf)
        
        # Append new network block
        with open(conf_path, "a") as f:
            f.write(section)
        
        # Reconfigure wpa_supplicant
        os.system("sudo wpa_cli -i wlan0 reconfigure")
        
        print(f"Successfully configured WiFi for {ssid}")
        return True
        
    except Exception as e:
        print(f"Error connecting to WiFi: {e}")
        return False


def get_lichess_client():
    logging.debug("get_lichess_client")
    import berserk
    import berserk.exceptions
    token = centaur.get_lichess_api()
    if not len(token):
        logging.error('lichess token not defined')
        raise ValueError('lichess token not defined')
    session = berserk.TokenSession(token)
    client = berserk.Client(session=session)
    # just to test if the token is a valid one
    try:
        who = client.account.get()
    except berserk.exceptions.ResponseError:
        logging.error('Lichess API error. Wrong token maybe?')
        raise
    return client


# Handle the menu structure
while True:    
    menu = {}
    if os.path.exists(centaur_software):
        centaur_item = {"Centaur": "DGT Centaur"}
        menu.update(centaur_item)
    menu.update({"pegasus": "DGT Pegasus"})
    if centaur.lichess_api:
        lichess_item = {"Lichess": "Lichess"}
        menu.update(lichess_item)
    if centaur.get_menuEngines() != "unchecked":
        menu.update({"Engines": "Engines"})
    if centaur.get_menuHandBrain() != "unchecked":
        menu.update({"HandBrain": "Hand + Brain"})
    if centaur.get_menu1v1Analysis() != "unchecked":
        menu.update({"1v1Analysis": "1v1 Analysis"})
    if centaur.get_menuEmulateEB() != "unchecked":
        menu.update({"EmulateEB": "e-Board"})
    if centaur.get_menuCast() != "unchecked":
        menu.update({"Cast": "Chromecast"})
    logging.debug("Checking for custom files")
    pyfiles = os.listdir("/home/pi")
    foundpyfiles = 0
    for pyfile in pyfiles:        
        if pyfile[-3:] == ".py" and pyfile != "firstboot.py":
            logging.debug("found custom files")
            foundpyfiles = 1
            break
    logging.debug("Custom file check complete")
    if foundpyfiles == 1:
        menu.update({"Custom": "Custom"})
    if centaur.get_menuSettings() != "unchecked":
        menu.update({"settings": "Settings"})
    if centaur.get_menuAbout() != "unchecked":
        menu.update({"About": "About"})                                
    result = doMenu(menu, "Main menu")
    # epaper.epd.init()
    # time.sleep(0.7)
    # epaper.clearArea(0,0 + shift,128,295)
    # time.sleep(1)
    if result == "BACK":
        board.beep(board.SOUND_POWER_OFF)
        show_welcome()
    if result == "Cast":
        chromecast_menu()
    if result == "Centaur":
        epaper.loadingScreen()
        #time.sleep(1)
        board.pauseEvents()
        board.cleanup(leds_off=True)
        statusbar.stop()
        time.sleep(1)
        os.chdir("/home/pi/centaur")
        os.system("sudo ./centaur")
        # Once started we cannot return to DGTCentaurMods, we can kill that
        time.sleep(3)
        os.system("sudo systemctl stop DGTCentaurMods.service")
        sys.exit()
    if result == "pegasus":
        rc = run_external_script("game/pegasus.py", start_key_polling=True)
    if result == "EmulateEB":
        result = doMenu("EmulateEB")
        if result == "dgtclassic":
            rc = run_external_script("game/eboard.py", start_key_polling=True)
        if result == "millennium":
            rc = run_external_script("game/millenium.py", start_key_polling=True)
    if result == "1v1Analysis":
        rc = run_external_script("game/1v1Analysis.py", start_key_polling=True)
    if result == "settings":
        setmenu = {
            "WiFi": "Wifi Setup",
            "Pairing": "BT Pair",
            "Sound": "Sound",
            "LichessAPI": "Lichess API",
            "reverseshell": "Shell 7777",
            "update": "Update opts",            
            "Shutdown": "Shutdown",
            "Reboot": "Reboot",
        }
        topmenu = False
        while topmenu == False:
            result = doMenu(setmenu, "settings")
            logging.debug(result)
            if result == "update":
                topmenu = False
                while topmenu == False:
                    updatemenu = {"status": "State: " + update.getStatus()}
                    package = "/tmp/dgtcentaurmods_armhf.deb"
                    if update.getStatus() == "enabled":
                        updatemenu.update(
                            {
                                "channel": "Chnl: " + update.getChannel(),
                                "policy": "Plcy: " + update.getPolicy(),
                            }
                        )
                    # Check for .deb files in the /home/pi folder that have been uploaded by webdav
                    updatemenu["lastrelease"] = "Last Release"
                    debfiles = os.listdir("/home/pi")
                    logging.debug("Check for deb files that system can update to")
                    for debfile in debfiles:        
                        if debfile[-4:] == ".deb" and debfile[:15] == "dgtcentaurmods_":
                            logging.debug("Found " + debfile)
                            updatemenu[debfile] = debfile[15:debfile.find("_",15)]                    
                    selection = ""
                    result = doMenu(updatemenu, "Update opts")
                    if result == "status":
                        result = doMenu(
                            {"enable": "Enable", "disable": "Disable"}, "Status"
                        )
                        logging.debug(result)
                        if result == "enable":
                            update.enable()
                        if result == "disable":
                            update.disable()
                            try:
                                os.remove(package)
                            except:
                                pass
                    if result == "channel":
                        result = doMenu({"stable": "Stable", "beta": "Beta"}, "Channel")
                        update.setChannel(result)
                    if result == "policy":
                        result = doMenu(
                            {"always": "Always", "revision": "Revisions"}, "Policy"
                        )
                        update.setPolicy(result)
                    if result == "lastrelease":
                        logging.debug("Last Release")
                        update_source = update.conf.read_value('update', 'source')
                        logging.debug(update_source)
                        url = 'https://raw.githubusercontent.com/{}/master/DGTCentaurMods/DEBIAN/versions'.format(update_source)                   
                        logging.debug(url)
                        ver = None
                        try:
                            with urllib.request.urlopen(url) as versions:
                                ver = json.loads(versions.read().decode())
                                logging.debug(ver)
                        except Exception as e:
                            logging.debug('!! Cannot download update info: ', e)
                        pass
                        if ver != None:
                            logging.debug(ver["stable"]["release"])
                            download_url = 'https://github.com/{}/releases/download/v{}/dgtcentaurmods_{}_armhf.deb'.format(update_source,ver["stable"]["release"],ver["stable"]["release"])
                            logging.debug(download_url)
                            try:
                                urllib.request.urlretrieve(download_url,'/tmp/dgtcentaurmods_armhf.deb')
                                logging.debug("downloaded to /tmp")
                                os.system("cp -f /home/pi/" + result + " /tmp/dgtcentaurmods_armhf.deb")
                                logging.debug("Starting update")
                                update.updateInstall()
                            except:
                                pass
                    if os.path.exists("/home/pi/" + result):
                        logging.debug("User selected .deb file. Doing update")
                        logging.debug("Copying .deb file to /tmp")
                        os.system("cp -f /home/pi/" + result + " /tmp/dgtcentaurmods_armhf.deb")
                        logging.debug("Starting update")
                        update.updateInstall()
                    if selection == "BACK":
                        # Trigger the update system to appply new settings
                        try:
                            os.remove(package)
                        except:
                            pass
                        finally:
                            threading.Thread(target=update.main, args=()).start()
                        topmenu = True
                        logging.debug("return to settings")
                        selection = ""
            topmenu = False
            if selection == "BACK":
                topmenu = True
                result = ""

            if result == "Sound":
                soundmenu = {"On": "On", "Off": "Off"}
                result = doMenu(soundmenu, "Sound")
                if result == "On":
                    centaur.set_sound("on")
                if result == "Off":
                    centaur.set_sound("off")
            if result == "WiFi":
                if network.check_network():
                    wifimenu = {"wpa2": "WPA2-PSK", "wps": "WPS Setup"}
                else:
                    wifimenu = {
                        "wpa2": "WPA2-PSK",
                        "wps": "WPS Setup",
                        "recover": "Recover wifi",
                    }
                if network.check_network():
                    cmd = (
                        'sudo sh -c "'
                        + str(pathlib.Path(__file__).parent.resolve())
                        + '/scripts/wifi_backup.sh backup"'
                    )                    
                    centaur.shell_run(cmd)
                result = doMenu(wifimenu, "Wifi Setup")
                if result != "BACK":
                    if result == "wpa2":
                        # Scan for WiFi networks
                        import subprocess
                        try:
                            scan_result = subprocess.run(['sudo', 'iwlist', 'wlan0', 'scan'], capture_output=True, text=True)
                            if scan_result.returncode == 0:
                                networks = []
                                lines = scan_result.stdout.split('\n')
                                for line in lines:
                                    if 'ESSID:' in line:
                                        essid = line.split('ESSID:')[1].strip().strip('"')
                                        if essid and essid not in networks:
                                            networks.append(essid)
                                
                                if networks:
                                    # Create menu for networks
                                    network_menu = {}
                                    for ssid in sorted(networks):
                                        network_menu[ssid] = ssid
                                    
                                    # Use doMenu to select network
                                    selected_network = doMenu(network_menu, "WiFi Networks")
                                    
                                    if selected_network and selected_network != "BACK":
                                        # Get password using getText
                                        from DGTCentaurMods.ui.get_text_from_board import getText
                                        password = getText("Enter WiFi password")
                                        #password = board.getText("Enter WiFi password")
                                        
                                        if password:
                                            epaper.writeText(0, f"Connecting to")
                                            epaper.writeText(1, selected_network)
                                            # Connect to the network
                                            if connect_to_wifi(selected_network, password):
                                                epaper.writeText(3, "Connected!")
                                            else:
                                                epaper.writeText(3, "Connection failed!")
                                            time.sleep(2)
                                        else:
                                            epaper.writeText(0, "No password provided")
                                            time.sleep(2)

                                else:
                                    epaper.writeText(0, "No networks found")
                                    time.sleep(2)
                            else:
                                epaper.writeText(0, "Scan failed")
                                time.sleep(2)
                        except Exception as e:
                            epaper.writeText(0, f"Error: {str(e)[:20]}")
                            time.sleep(2)
                    if result == "wps":
                        if network.check_network():
                            selection = ""
                            curmenu = None
                            IP = network.check_network()
                            epaper.clearScreen()
                            epaper.writeText(0, "Network is up.")
                            epaper.writeText(1, "Press OK to")
                            epaper.writeText(2, "disconnect")
                            epaper.writeText(4, IP)
                            timeout = time.time() + 15
                            while time.time() < timeout:
                                if selection == "BTNTICK":
                                    network.wps_disconnect_all()
                                    break
                                time.sleep(2)
                        else:
                            wpsMenu = {"connect": "Connect wifi"}
                            result = doMenu(wpsMenu, "WPS")
                            if result == "connect":
                                epaper.clearScreen()
                                epaper.writeText(0, "Press WPS button")
                                network.wps_connect()
                    if result == "recover":
                        selection = ""
                        cmd = (
                            'sudo sh -c "'
                            + str(pathlib.Path(__file__).parent.resolve())
                            + '/scripts/wifi_backup.sh restore"'
                        )
                        centaur.shell_run(cmd)                    
                        timeout = time.time() + 20
                        epaper.clearScreen()
                        epaper.writeText(0, "Waiting for")
                        epaper.writeText(1, "network...")
                        while not network.check_network() and time.time() < timeout:
                            time.sleep(1)
                        if not network.check_network():
                            epaper.writeText(1, "Failed to restore...")
                            time.sleep(4)

            if result == "Pairing":
                bluetooth_pairing()
            if result == "LichessAPI":
                rc = run_external_script("config/lichesstoken.py", start_key_polling=True)
            if result == "Shutdown":
                # Stop statusbar
                statusbar.stop()
                
                # Pause events and cleanup board
                board.pauseEvents()
                board.cleanup(leds_off=False)  # LEDs handled by shutdown()
                
                # Execute shutdown (handles LEDs, e-paper, controller sleep)
                board.shutdown()
                
                # Exit cleanly
                sys.exit()
            if result == "Reboot":
                board.beep(board.SOUND_POWER_OFF)
                epaper.epd.init()
                epaper.epd.HalfClear()
                time.sleep(5)
                epaper.stopEpaper()
                time.sleep(2)
                
                # LED cascade pattern h1→h8 (squares 0 to 7) for reboot
                try:
                    for i in range(0, 8):
                        board.led(i, intensity=5)
                        time.sleep(0.2)
                except Exception:
                    pass
                
                board.pauseEvents()
                board.cleanup(leds_off=True)
                os.system("/sbin/shutdown -r now &")
                sys.exit()
            if result == "reverseshell":
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("0.0.0.0", 7777))
                s.listen(1)
                conn, addr = s.accept()
                conn.send(b'With great power comes great responsibility! Use this if you\n')
                conn.send(b'can\'t get into ssh for some reason. Otherwise use ssh!\n')
                conn.send(b'\nBy using this you agree that a modified DGT Centaur Mods board\n')
                conn.send(b'is the best chessboard in the world.\n')
                conn.send(b'----------------------------------------------------------------------\n')                
                os.dup2(conn.fileno(),0)
                os.dup2(conn.fileno(),1)
                os.dup2(conn.fileno(),2)
                p=subprocess.call(["/bin/bash","-i"])
    if result == "Lichess":
        result = doMenu("Lichess")
        logging.debug('menu active: lichess')
        if result != "BACK":
            if result == "Ongoing":
                logging.debug('menu active: Ongoing')
                client = get_lichess_client()
                ongoing_games = client.games.get_ongoing(10)
                ongoing_menu = {}
                logging.debug(f"{ongoing_menu}")
                for game in ongoing_games:
                    gameid = game["gameId"]
                    opponent = game['opponent']['id']
                    if game['color'] == 'white':
                        desc = f"{client.account.get()['username']} vs. {opponent}"
                    else:
                        desc = f" {opponent} vs. {client.account.get()['username']}"
                    ongoing_menu[gameid] = desc
                logging.debug(f"ongoing menu: {ongoing_menu}")
                if len(ongoing_menu) > 0:
                    result = doMenu(ongoing_menu, "Current games:")
                    if result != "BACK":
                        logging.debug(f"menu current games")
                        game_id = result
                        logging.debug(f"staring lichess")
                        rc = run_external_script("game/lichess.py", "Ongoing", game_id, start_key_polling=True)
                else:
                    logging.warning("No ongoing games!")
                    epaper.writeText(1, "No ongoing games!")
                    time.sleep(3)


            elif result == "Challenges":
                client = get_lichess_client()
                challenge_menu = {}
                # very ugly call, there is no adequate method in berserk's API,
                # see https://github.com/rhgrant10/berserk/blob/master/berserk/todo.md
                challenges = client._r.get('api/challenge')
                for challenge in challenges['in']:
                    challenge_menu[f"{challenge['id']}:in"] = f"in: {challenge['challenger']['id']}"
                for challenge in challenges['out']:
                    challenge_menu[f"{challenge['id']}:out"] = f"out: {challenge['destUser']['id']}"
                result = doMenu(challenge_menu, "Challenges")
                if result != "BACK":
                    logging.debug('menu active: Challenge')
                    game_id, challenge_direction = result.split(":")
                    rc = run_external_script("game/lichess.py", "Challenge", game_id, challenge_direction, start_key_polling=True)

            else:  # new Rated or Unrated
                if result == "Rated":
                    rated = True
                else:
                    assert result == "Unrated", "Wrong game type"  #nie można rzucać wyjątków, bo cała aplikacja się sypie
                    rated = False
                result = doMenu(COLOR_MENU, "Color")
                if result != "BACK":
                    color = result
                    timemenu = {
                        "10 , 5": "10+5 minutes",
                        "15 , 10": "15+10 minutes",
                        "30 , 0": "30 minutes",
                        "30 , 20": "30+20 minutes",
                        "45 , 45": "45+45 minutes",
                        "60 , 20": "60+20 minutes",
                        "60 , 30": "60+30 minutes",
                        "90 , 30": "90+30 minutes",
                    }
                    result = doMenu(timemenu, "Time")

                    if result != "BACK":
                        # split time and increment '10 , 5' -> ['10', '5']
                        seek_time = result.split(",")
                        gtime = int(seek_time[0])
                        gincrement = int(seek_time[1])
                        rc = run_external_script("game/lichess.py", "New", gtime, gincrement, rated, color, start_key_polling=True)
    if result == "Engines":
        enginemenu = {"stockfish": "Stockfish"}
        # Pick up the engines from the engines folder and build the menu
        enginepath = str(pathlib.Path(__file__).parent.resolve()) + "/engines/"
        enginefiles = os.listdir(enginepath)
        enginefiles = list(
            filter(lambda x: os.path.isfile(enginepath + x), os.listdir(enginepath))
        )        
        for f in enginefiles:
            fn = str(f)
            if "." not in fn:
                # If this file don't have an extension then it is an engine
                enginemenu[fn] = fn
        result = doMenu(enginemenu, "Engines")
        logging.debug("Engines")
        logging.debug(result)
        if result == "stockfish":
            color = doMenu(COLOR_MENU, "Stockfish", "World's strongest open-source engine")
            logging.debug(color)
            # Current game will launch the screen for the current
            if color != "BACK":
                ratingmenu = {
                    "2850": "Pure",
                    "1350": "1350 ELO",
                    "1500": "1500 ELO",
                    "1700": "1700 ELO",
                    "1800": "1800 ELO",
                    "2000": "2000 ELO",
                    "2200": "2200 ELO",
                    "2400": "2400 ELO",
                    "2600": "2600 ELO",
                }
                elo = doMenu(ratingmenu, "ELO")
                if elo != "BACK":
                    rc = run_external_script("game/stockfish.py", color, elo, start_key_polling=True)
        else:
            if result != "BACK":
                # There are two options here. Either a file exists in the engines folder as enginename.uci which will give us menu options, or one doesn't and we run it as default
                enginefile = enginepath + result
                ucifile = enginepath + result + ".uci"
                
                # Get engine description from .uci file if it exists
                engine_desc = None
                # Check both engines/ and defaults/engines/ directories for .uci files
                ucifile_paths = [
                    enginepath + result + ".uci",  # engines/ directory
                    str(pathlib.Path(__file__).parent.resolve()) + "/defaults/engines/" + result + ".uci"  # defaults/engines/ directory
                ]
                for ucifile_path in ucifile_paths:
                    if os.path.exists(ucifile_path):
                        config = configparser.ConfigParser()
                        config.read(ucifile_path)
                        if 'DEFAULT' in config and 'Description' in config['DEFAULT']:
                            engine_desc = config['DEFAULT']['Description']
                        break
                
                color = doMenu(COLOR_MENU, result, engine_desc)
                # Current game will launch the screen for the current
                print("ucifile: " + ucifile)
                if color != "BACK":
                    if os.path.exists(ucifile):
                        # Read the uci file and build a menu
                        config = configparser.ConfigParser()
                        config.read(ucifile)
                        logging.debug(config.sections())
                        smenu = {}
                        for sect in config.sections():
                            smenu[sect] = sect
                        sec = doMenu(smenu, result)
                        if sec != "BACK":
                            rc = run_external_script("uci.py", color, result, sec, start_key_polling=True)
                    else:
                        # With no uci file we just call the engine
                        rc = run_external_script("uci.py", color, result, start_key_polling=True)
    if result == "HandBrain":
        # Pick up the engines from the engines folder and build the menu
        enginemenu = {}
        enginepath = str(pathlib.Path(__file__).parent.resolve()) + "/engines/"
        enginefiles = os.listdir(enginepath)
        enginefiles = list(
            filter(lambda x: os.path.isfile(enginepath + x), os.listdir(enginepath))
        )
        logging.debug(enginefiles)
        for f in enginefiles:
            fn = str(f)
            if ".uci" not in fn:
                # If this file is not .uci then assume it is an engine
                enginemenu[fn] = fn
        result = doMenu(enginemenu, "HandBrain")
        logging.debug(result)
        if result != "BACK":
            # There are two options here. Either a file exists in the engines folder as enginename.uci which will give us menu options, or one doesn't and we run it as default
            enginefile = enginepath + result
            ucifile = enginepath + result + ".uci"
            
            # Get engine description from .uci file if it exists
            engine_desc = None
            # Check both engines/ and defaults/engines/ directories for .uci files
            ucifile_paths = [
                enginepath + result + ".uci",  # engines/ directory
                str(pathlib.Path(__file__).parent.resolve()) + "/defaults/engines/" + result + ".uci"  # defaults/engines/ directory
            ]
            for ucifile_path in ucifile_paths:
                if os.path.exists(ucifile_path):
                    config = configparser.ConfigParser()
                    config.read(ucifile_path)
                    if 'DEFAULT' in config and 'Description' in config['DEFAULT']:
                        engine_desc = config['DEFAULT']['Description']
                    break
            
            color = doMenu(COLOR_MENU, result, engine_desc)
            # Current game will launch the screen for the current
            if color != "BACK":
                if os.path.exists(ucifile):
                    # Read the uci file and build a menu
                    config = configparser.ConfigParser()
                    config.read(ucifile)
                    logging.debug(config.sections())
                    smenu = {}
                    for sect in config.sections():
                        smenu[sect] = sect
                    sec = doMenu(smenu, result)
                    if sec != "BACK":
                        rc = run_external_script("game/handbrain.py", color, result, sec, start_key_polling=True)
                else:
                    # With no uci file we just call the engine
                    rc = run_external_script("game/handbrain.py", color, result, start_key_polling=True)
    if result == "Custom":
        pyfiles = os.listdir("/home/pi")
        menuitems = {}
        for pyfile in pyfiles:        
            if pyfile[-3:] == ".py" and pyfile != "firstboot.py":                
                menuitems[pyfile] = pyfile
        result = doMenu(menuitems,"Custom Scripts")
        if result.find("..") < 0:
            logging.debug("Running custom file: " + result)
            os.system("python /home/pi/" + result)

    if result == "About" or result == "BTNHELP":
        selection = ""
        epaper.clearScreen()
        statusbar.print()
        version = os.popen(
            "dpkg -l | grep dgtcentaurmods | tr -s ' ' | cut -d' ' -f3"
        ).read()
        epaper.writeText(1, "Get support:")
        epaper.writeText(9, "DGTCentaur")
        epaper.writeText(10, "      Mods")
        epaper.writeText(11, "Ver:" + version)        
        qr = Image.open(AssetManager.get_resource_path("qr-support.png"))
        qr = qr.resize((128, 128))
        epaper.epaperbuffer.paste(qr, (0, 42))
        timeout = time.time() + 15
        while selection == "" and time.time() < timeout:
            if selection == "BTNTICK" or selection == "BTNBACK":
                break
        epaper.clearScreen()        
