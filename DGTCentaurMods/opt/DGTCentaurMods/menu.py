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
from DGTCentaurMods.display.ui_components import AssetManager

from DGTCentaurMods.board import *
from DGTCentaurMods.display import epaper
from PIL import Image, ImageDraw, ImageFont
from DGTCentaurMods.board.logging import log

menuitem = 1
curmenu = None
selection = ""
centaur_software = "/home/pi/centaur/centaur"

event_key = threading.Event()
idle = False # ensure defined before keyPressed can be called


def keyPressed(id):
    # This functiion receives key presses
    log.info("in menu.py keyPressed: " + str(id))
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
    
    log.info(f"doMenu: {actual_menu}, Title: {actual_title}, Description: {actual_description}")
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
    try:
        event_key.wait()
    except KeyboardInterrupt:
        # Handle Ctrl+C in menu - return special value to trigger shutdown
        event_key.clear()
        return "SHUTDOWN"
    event_key.clear()
    return selection

def changedCallback(piece_event, field, time_in_seconds):
    log.info(f"changedCallback: {piece_event} {field} {time_in_seconds}")
    board.printChessState()


# Turn Leds off, beep, clear DGT Centaur Serial
# Initialise the epaper display - after which functions in epaper.py are available but you can also draw to the
# image epaper.epaperbuffer to change the screen.
board.ledsOff()
board.beep(board.SOUND_POWER_ON)
epaper.initEpaper(1)
statusbar = epaper.statusBar()
statusbar.start()
update = centaur.UpdateSystem()
log.info("Setting checking for updates in 5 mins.")
threading.Timer(300, update.main).start()
# Subscribe to board events. First parameter is the function for key presses. The second is the function for
# field activity
board.subscribeEvents(keyPressed, changedCallback, timeout=900)
#board.printBoardState()

def show_welcome():
    global idle
    epaper.welcomeScreen()
    idle = True
    try:
        event_key.wait()
    except KeyboardInterrupt:
        # Handle Ctrl+C in welcome screen
        event_key.clear()
        raise  # Re-raise to exit program
    event_key.clear()
    idle = False


show_welcome()
epaper.quickClear()


def check_docker_available():
    """Check if Docker is installed and daemon is running."""
    try:
        # Check if docker command exists
        result = subprocess.run(["docker", "--version"], 
                              capture_output=True, text=True, timeout=2)
        if result.returncode != 0:
            return False, "Docker command not found"
        
        # Check if Docker daemon is running
        result = subprocess.run(["docker", "info"], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return False, "Docker daemon is not running"
        
        return True, None
    except FileNotFoundError:
        return False, "Docker is not installed"
    except subprocess.TimeoutExpired:
        return False, "Docker daemon check timed out"
    except Exception as e:
        return False, f"Docker check failed: {str(e)}"


def check_docker_image_exists(image_name="dgtcentaurmods/centaur-bullseye:latest"):
    """Check if Docker image exists."""
    try:
        result = subprocess.run(["docker", "images", "-q", image_name],
                              capture_output=True, text=True, timeout=5)
        return result.returncode == 0 and result.stdout.strip() != ""
    except Exception:
        return False


def build_docker_image(image_name="dgtcentaurmods/centaur-bullseye:latest"):
    """Build Docker image if it doesn't exist."""
    build_script = str(pathlib.Path(__file__).parent.parent.parent.parent / 
                      "build" / "docker" / "build-centaur-container.sh")
    
    if not os.path.exists(build_script):
        log.error(f"Docker build script not found: {build_script}")
        return False, "Build script not found"
    
    log.info("Building Docker image for centaur (this may take a few minutes)...")
    epaper.writeText(0, "Building Docker")
    epaper.writeText(1, "image...")
    
    try:
        result = subprocess.run(["bash", build_script],
                              capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            log.info("Docker image built successfully")
            return True, None
        else:
            log.error(f"Docker build failed: {result.stderr}")
            return False, result.stderr
    except subprocess.TimeoutExpired:
        log.error("Docker build timed out")
        return False, "Build timed out"
    except Exception as e:
        log.error(f"Docker build error: {e}")
        return False, str(e)


def run_centaur_in_docker(centaur_path="/home/pi/centaur/centaur"):
    """Run centaur binary in Docker container with full hardware access."""
    container_process = None
    interrupted = False
    
    def signal_handler(signum, frame):
        """Handle Ctrl+C by killing Docker container"""
        nonlocal container_process, interrupted
        if interrupted:
            # Already handling interrupt, force kill immediately
            if container_process is not None:
                try:
                    container_process.kill()
                except:
                    pass
            # Kill any running containers
            try:
                result = subprocess.run(["docker", "ps", "-q", "--filter", "ancestor=dgtcentaurmods/centaur-bullseye:latest"],
                                      capture_output=True, text=True, timeout=2)
                if result.stdout.strip():
                    container_ids = result.stdout.strip().split('\n')
                    for cid in container_ids:
                        subprocess.run(["docker", "kill", cid], timeout=5)
            except:
                pass
            os._exit(130)
            return
        
        interrupted = True
        if container_process is not None:
            # Try to terminate gracefully
            try:
                container_process.terminate()
            except:
                pass
            
            # Kill any running containers
            try:
                result = subprocess.run(["docker", "ps", "-q", "--filter", "ancestor=dgtcentaurmods/centaur-bullseye:latest"],
                                      capture_output=True, text=True, timeout=2)
                if result.stdout.strip():
                    container_ids = result.stdout.strip().split('\n')
                    for cid in container_ids:
                        subprocess.run(["docker", "kill", cid], timeout=5)
            except:
                pass
            
            # Force kill after delay if still running
            def force_kill_after_delay():
                time.sleep(1.5)
                if container_process.poll() is None:
                    try:
                        container_process.kill()
                    except:
                        pass
                # Kill any remaining containers
                try:
                    result = subprocess.run(["docker", "ps", "-q", "--filter", "ancestor=dgtcentaurmods/centaur-bullseye:latest"],
                                          capture_output=True, text=True, timeout=2)
                    if result.stdout.strip():
                        container_ids = result.stdout.strip().split('\n')
                        for cid in container_ids:
                            subprocess.run(["docker", "kill", cid], timeout=5)
                except:
                    pass
            threading.Thread(target=force_kill_after_delay, daemon=True).start()
    
    # Register signal handler
    original_handler = signal.signal(signal.SIGINT, signal_handler)
    try:
        # Docker run command with full hardware access
        # Mount entire /home/pi/centaur directory (not just the binary) for libraries and resources
        docker_cmd = [
            "sudo", "docker", "run", "--rm",
            "--privileged",
            "--device=/dev/serial0",
            "--device=/dev/gpiomem",
            "--device=/dev/spidev0.0",
            "--device=/dev/spidev0.1",
            "-v", "/home/pi/centaur:/centaur:ro",
            "-v", "/sys/class/gpio:/sys/class/gpio:ro",
            "-w", "/centaur",
            "dgtcentaurmods/centaur-bullseye:latest",
            "/centaur/centaur"  # Explicitly specify the command to run
        ]
        
        log.info(f"Launching centaur in Docker: {' '.join(docker_cmd)}")
        # Run Docker container - don't capture output so binary can interact with terminal/display
        # The centaur binary needs direct access to stdout/stderr for display updates
        container_process = subprocess.Popen(docker_cmd,
                                            stdout=None,  # Don't capture - let it go to terminal
                                            stderr=None)  # Don't capture - let it go to terminal
        
        # Wait for container to complete
        try:
            return_code = container_process.wait()
            
            if return_code != 0:
                log.warning(f"Docker container exited with code {return_code}")
                if return_code == 139:
                    log.error("Segmentation fault in Docker container")
                    log.error("Binary may still be incompatible or missing required files")
                elif return_code == 1:
                    log.error("Docker container failed - check Docker logs")
                else:
                    log.warning(f"Container exited with unexpected code: {return_code}")
            else:
                log.info("Docker container completed successfully")
            
            return return_code
        except KeyboardInterrupt:
            log.info("Docker container interrupted")
            return 130
    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)
        # Clean up any remaining containers
        try:
            result = subprocess.run(["docker", "ps", "-q", "--filter", "ancestor=dgtcentaurmods/centaur-bullseye:latest"],
                                  capture_output=True, text=True, timeout=2)
            if result.stdout.strip():
                container_ids = result.stdout.strip().split('\n')
                for cid in container_ids:
                    subprocess.run(["docker", "kill", cid], timeout=5)
        except:
            pass


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
        epaper.loadingScreen()
        board.pauseEvents()
        board.cleanup(leds_off=True)
        statusbar.stop()

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
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)
        log.info(">>> Reinitializing after external script...")
        epaper.initEpaper()
        log.info(">>> epaper.initEpaper() complete")
        epaper.quickClear()
        log.info(">>> epaper.quickClear() complete")
        board.run_background(start_key_polling=start_key_polling)
        log.info(">>> board.run_background() complete")
        board.unPauseEvents()
        log.info(">>> board.unPauseEvents() complete")
        statusbar.start()
        log.info(">>> statusbar.start() complete")


def bluetooth_pairing():
    """
    Run Bluetooth pairing mode with timeout.
    Displays pairing instructions on e-paper screen.
    
    Returns:
        bool: True if device paired successfully, False on timeout
    """
    from DGTCentaurMods.board.bluetooth_controller import BluetoothController
    
    epaper.clearScreen()
    epaper.writeText(0, "Pair Now use")
    epaper.writeText(1, "any passcode if")
    epaper.writeText(2, "prompted.")
    epaper.writeText(4, "Times out in")
    epaper.writeText(5, "one minute.")
    
    def on_device_detected():
        """Callback when pairing device is detected"""
        epaper.writeText(8, "Pairing...")
    
    # Create Bluetooth controller instance and start pairing with 60 second timeout
    bluetooth_controller = BluetoothController()
    paired = bluetooth_controller.start_pairing(
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
    # epaper.epd.init()
    # time.sleep(0.7)
    # epaper.clearArea(0,0 + shift,128,295)
    # time.sleep(1)
    if result == "SHUTDOWN":
        # Graceful shutdown requested via Ctrl+C
        try:
            statusbar.stop()
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
        epaper.loadingScreen()
        #time.sleep(1)
        board.pauseEvents()
        board.cleanup(leds_off=True)
        statusbar.stop()
        time.sleep(1)
        if os.path.exists(centaur_software):
            # Ensure file is executable (Trixie compatibility)
            try:
                os.chmod(centaur_software, 0o755)
            except Exception as e:
                log.warning(f"Could not set execute permissions on centaur: {e}")
            
            # Check file header to determine file type (file command shows "data")
            # Read first few bytes to identify the format
            file_type = "unknown"
            file_size = 0
            try:
                file_size = os.path.getsize(centaur_software)
                log.info(f"Centaur file size: {file_size} bytes")
                if file_size == 0:
                    log.error("Centaur file is empty!")
                    epaper.writeText(0, "Centaur file empty")
                    time.sleep(2)
                    continue
                with open(centaur_software, "rb") as f:
                    header = f.read(16)
                    if header.startswith(b'\x7fELF'):
                        file_type = "elf"
                        log.info("Centaur file is ELF binary")
                    elif header.startswith(b'#!'):
                        file_type = "script"
                        log.info("Centaur file is a script")
                    elif header.startswith(b'\x03\xf3\r\n') or header.startswith(b'\x16\r\r\n'):
                        file_type = "python_bytecode"
                        log.info("Centaur file appears to be Python bytecode")
                    elif header == b'\x00' * 16:
                        log.warning("Centaur file header is all zeros - file may be corrupted or encrypted")
                        # Check if file has any non-zero content
                        f.seek(0)
                        sample = f.read(min(1024, file_size))
                        if sample == b'\x00' * len(sample):
                            log.error("Centaur file appears to be all zeros - likely corrupted")
                            epaper.writeText(0, "Centaur corrupted")
                            time.sleep(2)
                            continue
                    else:
                        log.warning(f"Centaur file header: {header.hex()[:32]}")
            except Exception as e:
                log.warning(f"Could not read file header: {e}")
            
            # Change to centaur directory (binary may need to run from here for relative resources)
            os.chdir("/home/pi/centaur")
            
            # Execute based on file type
            if file_type == "elf":
                # ELF binary - try Docker first (for Trixie compatibility), fallback to direct execution
                docker_available, docker_error = check_docker_available()
                
                if docker_available:
                    # Check if Docker image exists
                    if not check_docker_image_exists():
                        log.info("Docker image not found, attempting to build...")
                        build_success, build_error = build_docker_image()
                        if not build_success:
                            log.error(f"Failed to build Docker image: {build_error}")
                            epaper.writeText(0, "Docker build")
                            epaper.writeText(1, "failed")
                            time.sleep(3)
                            continue
                    
                    # Run via Docker
                    log.info("Running centaur in Docker container")
                    run_centaur_in_docker(centaur_software)
                else:
                    # Docker not available, try direct execution (may fail on Trixie)
                    log.warning(f"Docker not available: {docker_error}, attempting direct execution")
                    log.warning("Direct execution may fail on Trixie due to binary incompatibility")
                    subprocess.run(["sudo", "sh", "-c", f"exec {centaur_software}"], check=False)
            elif file_type == "python_bytecode":
                # Python bytecode - try running with Python
                log.warning("Attempting to run as Python bytecode (may not work)")
                subprocess.run(["sudo", "python3", centaur_software], check=False)
            else:
                # File header is all zeros - file may be corrupted, encrypted, or need special loader
                # Try using ld.so (dynamic linker) in case it's a valid binary that file doesn't recognize
                log.warning("File header is all zeros - may be corrupted or need special handling")
                log.info("Attempting execution via dynamic linker")
                try:
                    # Try with ld.so in case it's a valid binary
                    subprocess.run(["sudo", "/lib/ld-linux-armhf.so.3", centaur_software], check=False)
                except FileNotFoundError:
                    # Try alternative ld.so path
                    try:
                        subprocess.run(["sudo", "/lib/ld-linux.so.3", centaur_software], check=False)
                    except FileNotFoundError:
                        # Last resort: try direct execution (will likely fail but worth trying)
                        log.error("Could not find dynamic linker, file may be corrupted or incompatible with Trixie")
                        epaper.writeText(0, "Centaur file error")
                        epaper.writeText(1, "Check logs")
                        time.sleep(3)
        else:
            log.error(f"Centaur executable not found at {centaur_software}")
            epaper.writeText(0, "Centaur not found")
            time.sleep(2)
            continue
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
            rc = run_external_script("game/millennium_ble.py", start_key_polling=True)
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
                        rc = run_external_script("game/lichess.py", "Ongoing", game_id, start_key_polling=True)
                else:
                    log.warning("No ongoing games!")
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
                    log.debug('menu active: Challenge')
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
            log.info("Running custom file: " + result)
            os.system("python /home/pi/" + result)

    if result == "About" or result == "BTNHELP":
        selection = ""
        epaper.clearScreen()
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
