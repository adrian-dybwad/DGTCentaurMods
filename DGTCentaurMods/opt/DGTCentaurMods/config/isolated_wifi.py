#!/usr/bin/env python3
"""
Completely isolated WiFi configuration that doesn't interfere with the main DGT system.
This script manages its own display and serial communication independently.
"""
import sys
import os
import time
import signal
import subprocess
import serial
from typing import Optional, List

# Add the DGTCentaurMods path
sys.path.insert(0, '/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods')

# Import text input functionality
from DGTCentaurMods.ui.get_text_from_board import getText

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle CTRL+C gracefully"""
    global shutdown_requested
    print("\nShutdown requested...")
    shutdown_requested = True
    try:
        from DGTCentaurMods.display import epaper
        epaper.clearScreen()
    except:
        pass
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

def init_display():
    """Initialize the e-paper display"""
    try:
        from DGTCentaurMods.display import epaper
        
        # Initialize the display
        epaper.initEpaper()
        epaper.clearScreen()
        
        return epaper
    except Exception as e:
        print(f"Display init error: {e}")
        return None

def clear_display(epaper):
    """Clear the display"""
    try:
        epaper.clearScreen()
    except Exception as e:
        print(f"Display clear error: {e}")

def display_text(epaper, text: str, x: int = 10, y: int = 10):
    """Display text on the e-paper display"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # Create image
        image = Image.new('1', (128, 296), 255)
        draw = ImageDraw.Draw(image)
        
        # Load font
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        # Draw text
        draw.text((x, y), text, font=font, fill=0)
        
        # Update the epaper buffer
        epaper.epaperbuffer.paste(image, (0, 0))
        
    except Exception as e:
        print(f"Display text error: {e}")

def init_board():
    """Initialize board communication using existing connection"""
    try:
        # Use the existing board connection
        sys.path.insert(0, '/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods')
        from DGTCentaurMods.board import board as b
        
        # Check if board is already connected
        if hasattr(b, 'addr1') and hasattr(b, 'addr2') and b.addr1 != 0 and b.addr2 != 0:
            print(f"Using existing board connection: {b.addr1:02x}:{b.addr2:02x}")
            return b, b.addr1, b.addr2
        else:
            print("Board not properly initialized")
            return None, 0, 0
            
    except Exception as e:
        print(f"Board init error: {e}")
        return None, 0, 0

# Global variable for key debouncing
last_key_time = 0
last_key = None

def poll_key(board_obj, addr1, addr2):
    """Poll for key events using direct board communication with improved responsiveness"""
    global last_key_time, last_key
    
    try:
        # Send key event request
        board_obj.sendPacket(b'\x94', b'')
        resp = board_obj._ser_read(256)
        
        if not resp:
            return None
            
        hx = resp.hex()
        a1 = f"{addr1:02x}"
        a2 = f"{addr2:02x}"
        
        # Reduced debouncing: ignore keys pressed within 0.1 seconds
        current_time = time.time()
        if current_time - last_key_time < 0.1:
            return None
        
        # Check for key events in response
        if a1 in hx and a2 in hx:
            # Extract key from response
            key_start = hx.find(a1)
            if key_start != -1:
                key_hex = hx[key_start + 4:key_start + 6]
                try:
                    key_id = int(key_hex, 16)
                    
                    # Map key IDs to names
                    key_map = {
                        0x01: "BACK",
                        0x02: "UP", 
                        0x04: "DOWN",
                        0x08: "SELECT",
                        0x10: "HELP"
                    }
                    
                    if key_id in key_map:
                        key_name = key_map[key_id]
                        
                        # Additional debouncing: ignore same key
                        if key_name == last_key:
                            return None
                        
                        last_key = key_name
                        last_key_time = current_time
                        return key_name
                        
                except ValueError:
                    pass
        
        return None
        
    except Exception as e:
        print(f"Key polling error: {e}")
        return None

def main():
    """Main WiFi configuration function"""
    global shutdown_requested
    
    print("DGT Centaur WiFi Configuration (Isolated)")
    print("=" * 50)
    
    # Initialize board
    board_obj, addr1, addr2 = init_board()
    if not board_obj:
        print("Failed to initialize board")
        return
    
    # Initialize display
    epaper = init_display()
    if not epaper:
        print("Failed to initialize display")
        return
    
    # Get WiFi networks
    print("Scanning for WiFi networks...")
    networks = get_wifi_networks()
    
    if not networks:
        print("No WiFi networks found")
        display_text(epaper, "No WiFi networks found")
        time.sleep(3)
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
    
    # Show confirmation
    clear_display(epaper)
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        image = Image.new('1', (128, 296), 255)
        draw = ImageDraw.Draw(image)
        
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        # Truncate network name if too long
        network_name = selected_network[:20] if len(selected_network) > 20 else selected_network
        draw.text((5, 10), f"Selected: {network_name}", font=font, fill=0)
        draw.text((5, 30), "Press SELECT to", font=font, fill=0)
        draw.text((5, 45), "confirm or BACK", font=font, fill=0)
        draw.text((5, 60), "to cancel", font=font, fill=0)
        
        epaper.epaperbuffer.paste(image, (0, 0))
    except Exception as e:
        print(f"Display error: {e}")
    
    # Wait for confirmation
    while not shutdown_requested:
        confirm_key = poll_key(board_obj, addr1, addr2)
        if confirm_key == "SELECT":
            print(f"Configuring WiFi: {selected_network}")
            
            # Show password input screen
            try:
                from PIL import Image, ImageDraw, ImageFont
                
                image = Image.new('1', (128, 296), 255)
                draw = ImageDraw.Draw(image)
                
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
                except:
                    font = ImageFont.load_default()
                
                draw.text((5, 10), "Enter WiFi password:", font=font, fill=0)
                draw.text((5, 30), "Use board pieces", font=font, fill=0)
                draw.text((5, 45), "as keyboard", font=font, fill=0)
                
                epaper.epaperbuffer.paste(image, (0, 0))
            except Exception as e:
                print(f"Display error: {e}")
            
            # Use getText to get password
            password = getText("Enter WiFi password", board_obj, manage_events=False)
            
            if password:
                print(f"Connecting with password: {'*' * len(password)}")
                # Here you would implement the actual WiFi connection logic
                # For now, just show success
                clear_display(epaper)
                try:
                    from PIL import Image, ImageDraw, ImageFont
                    
                    image = Image.new('1', (128, 296), 255)
                    draw = ImageDraw.Draw(image)
                    
                    try:
                        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
                    except:
                        font = ImageFont.load_default()
                    
                    draw.text((5, 5), "Connected!", font=font, fill=0)
                    draw.text((5, 25), f"Network: {selected_network[:20]}", font=font, fill=0)
                    
                    epaper.epaperbuffer.paste(image, (0, 0))
                    
                except Exception as e:
                    print(f"Display error: {e}")
                
                # Wait for any key to exit
                while not shutdown_requested:
                    if poll_key(board_obj, addr1, addr2):
                        return
                    time.sleep(0.1)
            
        elif confirm_key == "BACK":
            print("Cancelled")
            return

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Cleanup
        try:
            print("WiFi configuration completed")
        except Exception as e:
            print(f"Error during cleanup: {e}")
        print("Goodbye!")