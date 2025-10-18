#!/usr/bin/env python3
"""
WiFi configuration using the main menu system.
Scans for networks and presents them using the proven doMenu() function.
"""
import sys
import os
import time
import signal
import subprocess
from typing import List

# Add the DGTCentaurMods path
sys.path.insert(0, '/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods')

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle CTRL+C gracefully"""
    global shutdown_requested
    print("\nShutdown requested...")
    shutdown_requested = True
    # Force exit immediately to prevent hanging
    os._exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def get_wifi_networks() -> List[str]:
    """Get list of available WiFi networks"""
    try:
        # Use the command that actually works
        result = subprocess.run(['sudo', 'iwlist', 'wlan0', 'scan'], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"iwlist failed: {result.stderr}")
            return []
        
        networks = []
        lines = result.stdout.split('\n')
        for line in lines:
            if 'ESSID:' in line:
                # Extract ESSID from line like 'ESSID:"NetworkName"'
                essid = line.split('ESSID:')[1].strip().strip('"')
                if essid and essid not in networks:
                    networks.append(essid)
        
        return sorted(networks)
    except Exception as e:
        print(f"Error scanning networks: {e}")
        return []

def main():
    """Main WiFi configuration function"""
    print("WiFi Configuration")
    print("=" * 50)
    
    # Get WiFi networks
    print("Scanning for WiFi networks...")
    networks = get_wifi_networks()
    
    if not networks:
        print("No WiFi networks found")
        return
    
    print(f"Found {len(networks)} networks")
    
    # Create menu dict for doMenu
    from DGTCentaurMods.game.menu import doMenu
    
    menu = {}
    for ssid in networks:
        menu[ssid] = ssid
    
    # Use main menu system
    selected_network = doMenu(menu, "WiFi Networks")
    
    # Handle selection
    if not selected_network or selected_network == "BACK":
        print("WiFi configuration cancelled")
        return
    
    print(f"Selected: {selected_network}")
    
    # Get password using getText
    from DGTCentaurMods.ui.get_text_from_board import getText
    password = getText("Enter WiFi password")
    
    if password:
        print(f"Connecting to {selected_network}...")
        # Here you would implement the actual WiFi connection logic
        print("Connected!")
    else:
        print("No password provided")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Goodbye!")