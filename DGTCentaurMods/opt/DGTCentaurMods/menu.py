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
import urllib.request
import json
import socket
import subprocess
import signal
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple
from DGTCentaurMods.asset_manager import AssetManager

from DGTCentaurMods.board import *
from DGTCentaurMods.board.sync_centaur import command
from DGTCentaurMods.epaper import SplashScreen, TextWidget
from DGTCentaurMods.epaper.menu_widget import MenuWidget, MenuEntry
from PIL import Image
from DGTCentaurMods.board.logging import log

menuitem = 1
curmenu = None
selection = ""
centaur_software = "/home/pi/centaur/centaur"
game_folder = "games"

event_key = threading.Event()
_active_menu_widget: Optional[MenuWidget] = None
idle = False # ensure defined before keyPressed can be called

# Constants matching old widgets module
STATUS_BAR_HEIGHT = 16
TITLE_GAP = 8
TITLE_HEIGHT = 26
TITLE_TOP = STATUS_BAR_HEIGHT + TITLE_GAP
MENU_TOP = TITLE_TOP + TITLE_HEIGHT
MENU_ROW_HEIGHT = 20
MENU_BODY_TOP_WITH_TITLE = MENU_TOP
MENU_BODY_TOP_NO_TITLE = STATUS_BAR_HEIGHT + TITLE_GAP
DESCRIPTION_GAP = 8

def keyPressed(id):
    # This function receives key presses
    global menuitem
    global curmenu
    global selection
    global event_key
    global _active_menu_widget
    
    log.info(f">>> keyPressed: key_id={id}, _active_menu_widget={_active_menu_widget is not None}")
    
    # If menu widget is active, let it handle the key
    if _active_menu_widget is not None:
        handled = _active_menu_widget.handle_key(id)
        log.info(f">>> keyPressed: menu widget.handle_key returned {handled}")
        if handled:
            return  # Widget handled the key
    
    # Original key handling for non-menu contexts
    if idle:
        if id == board.Key.TICK:
            event_key.set()
            return
    else:
        if id == board.Key.TICK:
            if not curmenu:
                selection = "BTNTICK"
                #log.info(selection)
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
            shutdown("Long Press Shutdown")
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
        if _active_menu_widget:
            _active_menu_widget.set_selection(menuitem - 1)


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
    
    log.info(f">>> doMenu: {actual_menu}, Title: {actual_title}, Description: {actual_description}")
    global menuitem
    global curmenu
    global selection
    global quickselect
    global event_key
    
    selection = ""
    curmenu = actual_menu
    # Display the given menu
    menuitem = 1
    quickselect = 0    

    quickselect = 1    
    ordered_menu = list(actual_menu.items()) if actual_menu else []
    
    # Convert menu items to MenuEntry format
    menu_entries = [MenuEntry(key=k, label=v) for k, v in ordered_menu]
    
    initial_index = 0
    if ordered_menu:
        initial_index = max(0, min(len(ordered_menu) - 1, menuitem - 1))
    
    # Define callbacks for registering/unregistering the menu widget
    def register_menu_widget(widget):
        global _active_menu_widget
        _active_menu_widget = widget
    
    def unregister_menu_widget():
        global _active_menu_widget
        _active_menu_widget = None
    
    # Create menu widget (positioned below status bar)
    menu_widget = MenuWidget(
        x=0,
        y=STATUS_BAR_HEIGHT,  # Start below status bar
        width=128,
        height=296 - STATUS_BAR_HEIGHT,  # Remaining height after status bar
        title=actual_title,
        entries=menu_entries,
        description=actual_description,  # Pass menu-level description as fallback
        selected_index=initial_index,
        register_callback=register_menu_widget,
        unregister_callback=unregister_menu_widget
    )

    board.display_manager.add_widget(menu_widget)
    log.info(f">>> doMenu: created MenuWidget with {len(menu_entries)} entries, selected_index={initial_index}")
    
    menuitem = (initial_index + 1) if ordered_menu else 1
    
    
    # Use menu widget to wait for selection
    try:
        result = menu_widget.wait_for_selection(initial_index)
        log.info(f">>> doMenu: menu widget returned result='{result}'")
        
        # Map widget result to menu selection
        if result == "SELECTED":
            # Get the selected menu key from the widget's current selection index
            selected_idx = menu_widget.selected_index
            if ordered_menu and selected_idx < len(ordered_menu):
                selection = ordered_menu[selected_idx][0]
            else:
                selection = "BACK"
        elif result == "BACK":
            selection = "BACK"
        elif result == "HELP":
            selection = "BTNHELP"
        else:
            selection = "BACK"
        
        board.display_manager.clear_widgets()
        
        log.info(f">>> doMenu: returning selection='{selection}'")
        return selection
    except KeyboardInterrupt:
        log.info(">>> doMenu: KeyboardInterrupt caught")
        board.display_manager.clear_widgets()
        board.display_manager.add_widget(SplashScreen(message="   Shutdown"))
        return "SHUTDOWN"

def changedCallback(piece_event, field, time_in_seconds):
    log.info(f"changedCallback: {piece_event} {field} {time_in_seconds}")
    board.printChessState()


# Create a simple statusbar class
update = centaur.UpdateSystem()
log.info("Setting checking for updates in 5 mins.")
threading.Timer(300, update.main).start()


def show_welcome():
    global idle
    
    splash_screen = SplashScreen(message="   Press [✓]")
    board.display_manager.add_widget(splash_screen)
    
    idle = True
    try:
        event_key.wait()
        log.info(">>> show_welcome() event_key.wait() RETURNED - key was pressed")
    except KeyboardInterrupt:
        log.info(">>> show_welcome() KeyboardInterrupt caught")
        event_key.clear()
        raise  # Re-raise to exit program
    event_key.clear()
    idle = False
    
def run_external_script(script_rel_path: str, *args: str, start_key_polling: bool = True) -> int:
    process = None
    interrupted = False
    
    def signal_handler(signum, frame):
        """Handle Ctrl+C by terminating the subprocess - NO LOGGING to avoid reentrant calls"""
        nonlocal process, interrupted
        if interrupted:
            # Already handling interrupt, force kill immediately and exit
            if process is not None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except:
                    try:
                        process.kill()
                    except:
                        pass
            os._exit(130)
            return
        
        interrupted = True
        if process is not None:
            # Try to terminate gracefully (no blocking wait in signal handler)
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except:
                try:
                    process.terminate()
                except:
                    pass
            
            # Start a background thread to kill if it doesn't exit quickly
            def force_kill_after_delay():
                time.sleep(1.5)
                if process.poll() is None:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except:
                        try:
                            process.kill()
                        except:
                            pass
            threading.Thread(target=force_kill_after_delay, daemon=True).start()
        # Don't block or log - let the main wait() handle completion
    
    # Register signal handler for graceful shutdown
    original_handler = signal.signal(signal.SIGINT, signal_handler)
    try:
        splash_screen = SplashScreen(message="     Loading")
        promise = board.display_manager.add_widget(splash_screen)
        if promise:
            try:
                promise.result(timeout=10.0)
            except Exception as e:
                log.warning(f"Error displaying splash screen: {e}")
        
        board.pauseEvents()
        board.cleanup(leds_off=True)

        script_path = str((pathlib.Path(__file__).parent / script_rel_path).resolve())
        log.info(f"script_path: {script_path}")
        cmd = [sys.executable, script_path, *map(str, args)]
        
        # Start process in its own process group so we can kill all children
        process = subprocess.Popen(cmd, preexec_fn=os.setsid)
        
        try:
            result = process.wait()
            return result
        except KeyboardInterrupt:
            log.info(">>> KeyboardInterrupt caught, subprocess should already be terminated")
            if process is not None:
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
            return 130  # Standard exit code for SIGINT
    finally:
        log.info(">>> run_external_script() cleanup complete")
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)
        log.info(">>> Reinitializing after external script...")
        promise = board.init_display()
        if promise:
            try:
                promise.result(timeout=10.0)
            except Exception as e:
                log.warning(f"Error initializing display: {e}")
        log.info(">>> display manager initialized")
        board.run_background(start_key_polling=start_key_polling)
        log.info(">>> board.run_background() complete")
        board.unPauseEvents()
        log.info(">>> board.unPauseEvents() complete")
  

def reset_bluetooth():
    """
    Remove all Bluetooth pairings and reset Bluetooth state.
    
    This clears all paired devices to start fresh. Useful when switching
    between different phone/tablet connections or troubleshooting pairing issues.
    """
    from DGTCentaurMods.rfcomm_manager import RfcommManager
    
    clear_screen()
    write_text(0, "Resetting")
    write_text(1, "Bluetooth...")
    
    removed_count = 0
    
    controller = RfcommManager()
    paired_devices = controller.get_paired_devices()
    
    for device in paired_devices:
        if controller.remove_device(device['address']):
            removed_count += 1
            log.info(f"Removed paired device: {device['address']}")
    
    # Show result
    clear_screen()
    if removed_count > 0:
        write_text(0, f"Removed {removed_count}")
        write_text(1, "device(s)")
    else:
        write_text(0, "No paired")
        write_text(1, "devices found")
    time.sleep(2)
    clear_screen()


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
    clear_screen()
    write_text(0, "Discovering...")
    write_text(1, "Chromecasts...")
    time.sleep(1)
    
    try:
        chromecasts = pychromecast.get_chromecasts()
    except Exception as e:
        clear_screen()
        write_text(0, "Discovery failed")
        write_text(1, str(e)[:20])
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
        clear_screen()
        write_text(0, "No Chromecasts")
        write_text(1, "found")
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
    clear_screen()
    write_text(0, "Streaming to:")
    # Truncate long names to fit on screen (20 chars per line)
    if len(result) > 20:
        write_text(1, result[:20])
        if len(result) > 40:
            write_text(2, result[20:40])
        else:
            write_text(2, result[20:])
    else:
        write_text(1, result)
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
        # Use subprocess.run for proper resource cleanup
        result = subprocess.run(
            ["sudo", "sh", "-c", f"wpa_passphrase '{ssid}' '{password}'"],
            capture_output=True,
            text=True,
            timeout=5
        )
        section = result.stdout if result.returncode == 0 else ""
        
        if "ssid" not in section:
            log.error("Failed to generate network configuration")
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
        
        log.info(f"Successfully configured WiFi for {ssid}")
        return True
        
    except Exception as e:
        log.error(f"Error connecting to WiFi: {e}")
        return False


def get_lichess_client():
    log.debug("get_lichess_client")
    import berserk
    import berserk.exceptions
    token = centaur.get_lichess_api()
    if not len(token):
        log.error('lichess token not defined')
        raise ValueError('lichess token not defined')
    session = berserk.TokenSession(token)
    client = berserk.Client(session=session)
    # just to test if the token is a valid one
    try:
        who = client.account.get()
    except berserk.exceptions.ResponseError:
        log.error('Lichess API error. Wrong token maybe?')
        raise
    return client

def shutdown(message, reboot=False):
    board.display_manager.clear_widgets(addStatusBar=False)
    promise = board.display_manager.add_widget(SplashScreen(message=message))
    promise.result(timeout=10.0)
    board.shutdown(reboot=reboot)

# Handle the menu structure
# Only run menu loop if menu.py is executed directly (not when imported)
if __name__ == "__main__":  
    # Subscribe to board events. First parameter is the function for key presses. The second is the function for
    # field activity
    promise = board.init_display()
    if promise:
        try:
            promise.result(timeout=10.0)
        except Exception as e:
            log.warning(f"Error initializing display: {e}")
    board.subscribeEvents(keyPressed, changedCallback, timeout=900)
    board._events_initialized = True  # Mark as initialized to prevent re-initialization
    board.printChessState()
    resp = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    log.debug(f"Menu: RESPONSE FROM F0 - {' '.join(f'{b:02x}' for b in resp)}")
    resp = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F4)
    log.debug(f"Menu: RESPONSE FROM F4 - {' '.join(f'{b:02x}' for b in resp)}")
    resp = board.sendCommand(command.DGT_BUS_SEND_96)
    log.debug(f"Menu: RESPONSE FROM 96 - {' '.join(f'{b:02x}' for b in resp)}")
    resp = board.sendCommand(command.DGT_BUS_SEND_STATE)
    log.debug(f"Menu: RESPONSE FROM 82 - {' '.join(f'{b:02x}' for b in resp)}")

    resp = board.sendCommand(command.DGT_BUS_SEND_CHANGES)
    log.debug(f"Menu: RESPONSE FROM 83 - {' '.join(f'{b:02x}' for b in resp)}")
    resp = board.sendCommand(command.DGT_BUS_POLL_KEYS)
    log.debug(f"Menu: RESPONSE FROM 94 - {' '.join(f'{b:02x}' for b in resp)}")
    show_welcome()  # Show welcome screen first, wait for tick
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
        log.debug("Checking for custom files")
        pyfiles = os.listdir("/home/pi")
        foundpyfiles = 0
        for pyfile in pyfiles:        
            if pyfile[-3:] == ".py" and pyfile != "firstboot.py":
                log.debug("found custom files")
                foundpyfiles = 1
                break
        log.debug("Custom file check complete")
        if foundpyfiles == 1:
            menu.update({"Custom": "Custom"})
        if centaur.get_menuSettings() != "unchecked":
            menu.update({"settings": "Settings"})
        if centaur.get_menuAbout() != "unchecked":
            menu.update({"About": "About"})                                
        result = doMenu(menu, "Main menu")
        # Historical note: previous firmware called into the raw epaper driver here.
        # time.sleep(0.7)
        # time.sleep(1)
        if result == "SHUTDOWN":
            # Graceful shutdown requested via Ctrl+C
            try:
                board.cleanup(leds_off=True)
                board.pauseEvents()
            except:
                pass
            break
        if result == "BACK":
            board.beep(board.SOUND_POWER_OFF)
            show_welcome()
        if result == "Cast":
            chromecast_menu()
        if result == "Centaur":
            loading_screen()
            #time.sleep(1)
            board.pauseEvents()
            board.cleanup(leds_off=True)
            time.sleep(1)
            if os.path.exists(centaur_software):
                # Ensure file is executable (Trixie compatibility)
                try:
                    os.chmod(centaur_software, 0o755)
                except Exception as e:
                    log.warning(f"Could not set execute permissions on centaur: {e}")
                # Change directory and use relative path (bypasses sudo secure_path, Trixie compatibility)
                # Don't restore directory since we exit immediately after
                os.chdir("/home/pi/centaur")
                # Use os.system to launch interactive application (blocks until process completes)
                os.system("sudo ./centaur")
            else:
                log.error(f"Centaur executable not found at {centaur_software}")
                write_text(0, "Centaur not found")
                time.sleep(2)
                continue
            # Once started we cannot return to DGTCentaurMods, we can kill that
            time.sleep(3)
            os.system("sudo systemctl stop DGTCentaurMods.service")
            sys.exit()
        if result == "pegasus":
            rc = run_external_script(f"{game_folder}/pegasus.py", start_key_polling=True)
        if result == "EmulateEB":
            result = doMenu("EmulateEB")
            if result == "dgtclassic":
                rc = run_external_script(f"{game_folder}/eboard.py", start_key_polling=True)
            if result == "millennium":
                rc = run_external_script(f"{game_folder}/millennium.py", start_key_polling=True)
        if result == "1v1Analysis":
            rc = run_external_script(f"{game_folder}/1v1Analysis.py", start_key_polling=True)
        if result == "settings":
            setmenu = {
                "WiFi": "Wifi Setup",
                "ResetBluetooth": "Reset BT",
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
                log.debug(result)
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
                        log.debug("Check for deb files that system can update to")
                        for debfile in debfiles:        
                            if debfile[-4:] == ".deb" and debfile[:15] == "dgtcentaurmods_":
                                log.debug("Found " + debfile)
                                updatemenu[debfile] = debfile[15:debfile.find("_",15)]                    
                        selection = ""
                        result = doMenu(updatemenu, "Update opts")
                        if result == "status":
                            result = doMenu(
                                {"enable": "Enable", "disable": "Disable"}, "Status"
                            )
                            log.debug(result)
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
                            log.debug("Last Release")
                            update_source = update.conf.read_value('update', 'source')
                            log.debug(update_source)
                            url = 'https://raw.githubusercontent.com/{}/master/DGTCentaurMods/DEBIAN/versions'.format(update_source)                   
                            log.debug(url)
                            ver = None
                            try:
                                with urllib.request.urlopen(url) as versions:
                                    ver = json.loads(versions.read().decode())
                                    log.debug(ver)
                            except Exception as e:
                                log.debug('!! Cannot download update info: ', e)
                            pass
                            if ver != None:
                                log.debug(ver["stable"]["release"])
                                download_url = 'https://github.com/{}/releases/download/v{}/dgtcentaurmods_{}_armhf.deb'.format(update_source,ver["stable"]["release"],ver["stable"]["release"])
                                log.debug(download_url)
                                try:
                                    urllib.request.urlretrieve(download_url,'/tmp/dgtcentaurmods_armhf.deb')
                                    log.debug("downloaded to /tmp")
                                    os.system("cp -f /home/pi/" + result + " /tmp/dgtcentaurmods_armhf.deb")
                                    log.debug("Starting update")
                                    update.updateInstall()
                                except:
                                    pass
                        if os.path.exists("/home/pi/" + result):
                            log.debug("User selected .deb file. Doing update")
                            log.debug("Copying .deb file to /tmp")
                            os.system("cp -f /home/pi/" + result + " /tmp/dgtcentaurmods_armhf.deb")
                            log.debug("Starting update")
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
                            log.debug("return to settings")
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
                                                write_text(0, f"Connecting to")
                                                write_text(1, selected_network)
                                                # Connect to the network
                                                if connect_to_wifi(selected_network, password):
                                                    write_text(3, "Connected!")
                                                else:
                                                    write_text(3, "Connection failed!")
                                                time.sleep(2)
                                            else:
                                                write_text(0, "No password provided")
                                                time.sleep(2)

                                    else:
                                        write_text(0, "No networks found")
                                        time.sleep(2)
                                else:
                                    write_text(0, "Scan failed")
                                    time.sleep(2)
                            except Exception as e:
                                write_text(0, f"Error: {str(e)[:20]}")
                                time.sleep(2)
                        if result == "wps":
                            if network.check_network():
                                selection = ""
                                curmenu = None
                                IP = network.check_network()
                                clear_screen()
                                write_text(0, "Network is up.")
                                write_text(1, "Press OK to")
                                write_text(2, "disconnect")
                                write_text(4, IP)
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
                                    clear_screen()
                                    write_text(0, "Press WPS button")
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
                            clear_screen()
                            write_text(0, "Waiting for")
                            write_text(1, "network...")
                            while not network.check_network() and time.time() < timeout:
                                time.sleep(1)
                            if not network.check_network():
                                write_text(1, "Failed to restore...")
                                time.sleep(4)

                if result == "ResetBluetooth":
                    reset_bluetooth()
                if result == "LichessAPI":
                    rc = run_external_script("config/lichesstoken.py", start_key_polling=True)
                if result == "Shutdown":
                    shutdown("     Shutdown")
                if result == "Reboot":
                
                    # LED cascade pattern h1→h8 (squares 0 to 7) for reboot
                    try:
                        for i in range(0, 8):
                            board.led(i, repeat=0)
                            time.sleep(0.2)
                    except Exception:
                        pass
                        
                    shutdown("     Rebooting", True)

                    #os.system("/sbin/shutdown -r now &")
                    #sys.exit()
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
            log.debug('menu active: lichess')
            if result != "BACK":
                if result == "Ongoing":
                    log.debug('menu active: Ongoing')
                    client = get_lichess_client()
                    ongoing_games = client.games.get_ongoing(10)
                    ongoing_menu = {}
                    log.debug(f"{ongoing_menu}")
                    for game in ongoing_games:
                        gameid = game["gameId"]
                        opponent = game['opponent']['id']
                        if game['color'] == 'white':
                            desc = f"{client.account.get()['username']} vs. {opponent}"
                        else:
                            desc = f" {opponent} vs. {client.account.get()['username']}"
                        ongoing_menu[gameid] = desc
                    log.debug(f"ongoing menu: {ongoing_menu}")
                    if len(ongoing_menu) > 0:
                        result = doMenu(ongoing_menu, "Current games:")
                        if result != "BACK":
                            log.debug(f"menu current games")
                            game_id = result
                            log.debug(f"staring lichess")
                            rc = run_external_script(f"{game_folder}/lichess.py", "Ongoing", game_id, start_key_polling=True)
                    else:
                        log.warning("No ongoing games!")
                        write_text(1, "No ongoing games!")
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
                        log.debug('menu active: Challenge')
                        game_id, challenge_direction = result.split(":")
                        rc = run_external_script(f"{game_folder}/lichess.py", "Challenge", game_id, challenge_direction, start_key_polling=True)

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
                            rc = run_external_script(f"{game_folder}/lichess.py", "New", gtime, gincrement, rated, color, start_key_polling=True)
        if result == "Engines":
            enginemenu = {}
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
            log.debug("Engines")
            log.debug(result)
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
                log.info("ucifile: " + ucifile)
                if color != "BACK":
                    if os.path.exists(ucifile):
                        # Read the uci file and build a menu
                        config = configparser.ConfigParser()
                        config.read(ucifile)
                        log.debug(config.sections())
                        smenu = {}
                        for sect in config.sections():
                            smenu[sect] = sect
                        sec = doMenu(smenu, result)
                        if sec != "BACK":
                            rc = run_external_script(f"{game_folder}/uci.py", color, result, sec, start_key_polling=True)
                    else:
                        # With no uci file we just call the engine
                        rc = run_external_script(f"{game_folder}/uci.py", color, result, start_key_polling=True)
        if result == "HandBrain":
            # Pick up the engines from the engines folder and build the menu
            enginemenu = {}
            enginepath = str(pathlib.Path(__file__).parent.resolve()) + "/engines/"
            enginefiles = os.listdir(enginepath)
            enginefiles = list(
                filter(lambda x: os.path.isfile(enginepath + x), os.listdir(enginepath))
            )
            log.debug(enginefiles)
            for f in enginefiles:
                fn = str(f)
                if ".uci" not in fn:
                    # If this file is not .uci then assume it is an engine
                    enginemenu[fn] = fn
            result = doMenu(enginemenu, "HandBrain")
            log.debug(result)
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
                        log.info(config.sections())
                        smenu = {}
                        for sect in config.sections():
                            smenu[sect] = sect
                        sec = doMenu(smenu, result)
                        if sec != "BACK":
                            rc = run_external_script(f"{game_folder}/handbrain.py", color, result, sec, start_key_polling=True)
                    else:
                        # With no uci file we just call the engine
                        rc = run_external_script(f"{game_folder}/handbrain.py", color, result, start_key_polling=True)
        if result == "Custom":
            pyfiles = os.listdir("/home/pi")
            menuitems = {}
            for pyfile in pyfiles:        
                if pyfile[-3:] == ".py" and pyfile != "firstboot.py":                
                    menuitems[pyfile] = pyfile
            result = doMenu(menuitems,"Custom Scripts")
            if result.find("..") < 0:
                log.info("Running custom file: " + result)
                os.system("python /home/pi/" + result)

        if result == "About" or result == "BTNHELP":
            selection = ""
            clear_screen()
            statusbar.print()
            # Use subprocess.run for proper resource cleanup
            result = subprocess.run(
                ["dpkg", "-l"],
                capture_output=True,
                text=True,
                timeout=5
            )
            version = ""
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'dgtcentaurmods' in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            version = parts[2]
                            break
            write_text(1, "Get support:")
            write_text(9, "DGTCentaur")
            write_text(10, "      Mods")
            write_text(11, "Ver:" + version)        
            qr = Image.open(AssetManager.get_resource_path("qr-support.png")).resize((128, 128))
            manager = _get_display_manager()
            canvas = manager._framebuffer.get_canvas()
            canvas.paste(qr, (0, 42))
            log.warning("About screen: Calling manager.update(full=True) - will cause flashing refresh")
            manager.update(full=True)
            timeout = time.time() + 15
            while selection == "" and time.time() < timeout:
                if selection == "BTNTICK" or selection == "BTNBACK":
                    break
            #clear_screen()        

