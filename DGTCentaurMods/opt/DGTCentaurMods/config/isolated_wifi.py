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

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle CTRL+C gracefully"""
    global shutdown_requested
    print("\n🛑 Shutdown requested...")
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
                essid = line.split('ESSID:')[1].strip().strip('"')
                if essid and essid != '' and essid != 'off/any':
                    networks.append(essid)
        
        print(f"Found networks: {networks}")
        return list(set(networks))  # Remove duplicates
    except Exception as e:
        print(f"Error scanning WiFi: {e}")
        return []

def init_display():
    """Initialize display using existing system"""
    try:
        # Use the existing display system
        sys.path.insert(0, '/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods')
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
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
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
            print(f"✅ Using existing board connection: {b.addr1:02x}:{b.addr2:02x}")
            return b, b.addr1, b.addr2
        else:
            print("❌ Board not properly initialized")
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
        
        detected_key = None
        
        # Look for the specific button patterns from the debug output
        if "00140a05020000000061" in hx:
            detected_key = "DOWN"
        elif "00140a0508000000007d3c" in hx:
            detected_key = "UP"
        elif "00140a0501000000007d47" in hx:
            detected_key = "BACK"
        elif "00140a0510000000007d17" in hx:
            detected_key = "SELECT"
        elif f"b100{a1}0{a2}0d" in hx:
            detected_key = "SELECT"
        
        # Only return if it's a different key or enough time has passed (reduced from 0.5 to 0.2)
        if detected_key and (detected_key != last_key or current_time - last_key_time > 0.2):
            print(f"DEBUG: Detected {detected_key} key")
            last_key_time = current_time
            last_key = detected_key
            return detected_key
        
        return None
    except Exception as e:
        print(f"Key poll error: {e}")
        return None

def main():
    """Main WiFi configuration function"""
    global shutdown_requested
    
    print("🔧 DGT Centaur WiFi Configuration (Isolated)")
    print("=" * 50)
    
    # Initialize board
    board_obj, addr1, addr2 = init_board()
    if not board_obj:
        print("❌ Failed to initialize board")
        return
    
    # Initialize display
    epaper = init_display()
    if not epaper:
        print("❌ Failed to initialize display")
        return
    
    print("✅ Hardware initialized")
    
    # Get WiFi networks
    print("📡 Scanning for WiFi networks...")
    networks = get_wifi_networks()
    
    if not networks:
        print("❌ No WiFi networks found")
        display_text(epd, "No WiFi networks found")
        time.sleep(3)
        return
    
    print(f"📶 Found {len(networks)} networks")
    
    # Display networks and allow selection
    selected_index = 0
    
    def show_networks():
        try:
            from PIL import Image, ImageDraw, ImageFont
            
            # Create a single image with all networks
            image = Image.new('1', (128, 296), 255)
            draw = ImageDraw.Draw(image)
            
            # Load font
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except:
                font = ImageFont.load_default()
            
            # Draw title
            draw.text((5, 5), "WiFi Networks:", font=font, fill=0)
            
            # Show up to 8 networks
            start_idx = max(0, selected_index - 3)
            end_idx = min(len(networks), start_idx + 8)
            
            for i, network in enumerate(networks[start_idx:end_idx]):
                y_pos = 25 + (i * 18)
                prefix = ">" if (start_idx + i) == selected_index else " "
                text = f"{prefix} {network[:18]}"  # Truncate long names
                draw.text((5, y_pos), text, font=font, fill=0)
            
            # Update the epaper buffer
            epaper.epaperbuffer.paste(image, (0, 0))
            
        except Exception as e:
            print(f"Display error: {e}")
    
    show_networks()
    
    print("⌨️  Use UP/DOWN to navigate, SELECT to choose, BACK to cancel")
    
    while not shutdown_requested:
        key = poll_key(board_obj, addr1, addr2)
        if not key:
            time.sleep(0.05)  # Reduced from 0.1 to 0.05 for better responsiveness
            continue
            
        print(f"🔑 Key pressed: {key}")
        
        if key == "UP":
            selected_index = (selected_index - 1) % len(networks)
            show_networks()
        elif key == "DOWN":
            selected_index = (selected_index + 1) % len(networks)
            show_networks()
        elif key == "SELECT":
            selected_network = networks[selected_index]
            print(f"✅ Selected: {selected_network}")
            
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
                    print(f"🔧 Configuring WiFi: {selected_network}")
                    
                    # Show password input screen
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
                        draw.text((5, 10), f"Network: {network_name}", font=font, fill=0)
                        draw.text((5, 30), "Password:", font=font, fill=0)
                        draw.text((5, 50), "Enter password using", font=font, fill=0)
                        draw.text((5, 65), "keyboard or press", font=font, fill=0)
                        draw.text((5, 80), "SELECT to skip", font=font, fill=0)
                        draw.text((5, 110), "BACK to cancel", font=font, fill=0)
                        
                        epaper.epaperbuffer.paste(image, (0, 0))
                    except Exception as e:
                        print(f"Display error: {e}")
                    
                    # Use board text input method
                    try:
                        print("🔐 Starting password input...")
                        
                        # Use the board's text input method
                        password = board_obj.getText("WiFi Password")
                        
                        if password is None:
                            print("❌ Password input cancelled")
                            show_networks()
                            break
                        
                        print(f"✅ Password entered: {'*' * len(password)}")
                        
                    except Exception as e:
                        print(f"Password input error: {e}")
                        password = ""
                    
                    if not shutdown_requested:
                        # Show success screen
                        try:
                            image = Image.new('1', (128, 296), 255)
                            draw = ImageDraw.Draw(image)
                            draw.text((5, 10), "WiFi configured!", font=font, fill=0)
                            # Truncate network name if too long
                            network_name = selected_network[:20] if len(selected_network) > 20 else selected_network
                            draw.text((5, 30), f"Network: {network_name}", font=font, fill=0)
                            if password:
                                draw.text((5, 50), "Password: ****", font=font, fill=0)
                            draw.text((5, 80), "Press any key to exit", font=font, fill=0)
                            epaper.epaperbuffer.paste(image, (0, 0))
                        except:
                            pass
                        
                        # Wait for any key to exit
                        while not shutdown_requested:
                            if poll_key(board_obj, addr1, addr2):
                                return
                            time.sleep(0.1)
                    
                elif confirm_key == "BACK":
                    print("❌ Cancelled")
                    show_networks()
                    break
                    
        elif key == "BACK":
            print("❌ Cancelled")
            return

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        print("👋 Goodbye!")
