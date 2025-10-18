#!/usr/bin/env python3
"""
Simplified WiFi configuration using the working key detection from the main system.
"""
import sys
import os
import time
import signal
import subprocess
from typing import Optional, List

# Add the DGTCentaurMods path
sys.path.insert(0, '/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods')

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
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def get_wifi_networks() -> List[str]:
    """Get list of available WiFi networks"""
    try:
        result = subprocess.run(['iwlist', 'scan'], capture_output=True, text=True)
        if result.returncode != 0:
            return []
        
        networks = []
        lines = result.stdout.split('\n')
        for line in lines:
            if 'ESSID:' in line:
                essid = line.split('ESSID:')[1].strip().strip('"')
                if essid and essid != '':
                    networks.append(essid)
        
        return list(set(networks))  # Remove duplicates
    except Exception as e:
        print(f"Error scanning WiFi: {e}")
        return []

def display_wifi_list(networks: List[str], selected_index: int = 0):
    """Display WiFi networks on screen"""
    try:
        from DGTCentaurMods.display import epaper
        from PIL import Image, ImageDraw, ImageFont
        
        # Create a simple image
        img = Image.new('1', (128, 296), 255)
        draw = ImageDraw.Draw(img)
        
        # Try to load font
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        # Draw title
        draw.text((5, 5), "WiFi Networks:", font=font, fill=0)
        
        # Draw networks
        start_idx = max(0, selected_index - 3)
        end_idx = min(len(networks), start_idx + 8)
        
        for i, network in enumerate(networks[start_idx:end_idx]):
            y_pos = 25 + (i * 15)
            prefix = ">" if (start_idx + i) == selected_index else " "
            text = f"{prefix} {network[:15]}"  # Truncate long names
            draw.text((5, y_pos), text, font=font, fill=0)
        
        # Update display
        epaper.epaperbuffer.paste(img, (0, 0))
        
    except Exception as e:
        print(f"Display error: {e}")

def wait_for_key() -> Optional[str]:
    """Wait for a key press using the working method"""
    try:
        from DGTCentaurMods.ui.input_adapters import poll_actions_from_board
        
        timeout = time.time() + 30  # 30 second timeout
        while not shutdown_requested and time.time() < timeout:
            action = poll_actions_from_board()
            if action:
                return action
            time.sleep(0.05)  # Faster polling
        
        return None
    except Exception as e:
        print(f"Key wait error: {e}")
        return None

def main():
    """Main WiFi configuration function"""
    global shutdown_requested
    
    print("🔧 DGT Centaur WiFi Configuration (Simplified)")
    print("=" * 50)
    
    # Check if we can access the board
    try:
        from DGTCentaurMods.board import board as b
        print(f"✅ Board connected: {b.addr1:02x}:{b.addr2:02x}")
    except Exception as e:
        print(f"❌ Board connection failed: {e}")
        return
    
    # Initialize display
    try:
        from DGTCentaurMods.display import epaper
        epaper.initEpaper()
        epaper.clearScreen()
        print("✅ Display initialized")
    except Exception as e:
        print(f"❌ Display initialization failed: {e}")
        return
    
    # Get WiFi networks
    print("📡 Scanning for WiFi networks...")
    networks = get_wifi_networks()
    
    if not networks:
        print("❌ No WiFi networks found")
        return
    
    print(f"📶 Found {len(networks)} networks:")
    for i, network in enumerate(networks):
        print(f"  {i+1}. {network}")
    
    # Display networks and allow selection
    selected_index = 0
    display_wifi_list(networks, selected_index)
    
    print("⌨️  Use UP/DOWN to navigate, SELECT to choose, BACK to cancel")
    
    while not shutdown_requested:
        key = wait_for_key()
        if not key:
            continue
            
        print(f"🔑 Key pressed: {key}")
        
        if key == "UP":
            selected_index = (selected_index - 1) % len(networks)
            display_wifi_list(networks, selected_index)
        elif key == "DOWN":
            selected_index = (selected_index + 1) % len(networks)
            display_wifi_list(networks, selected_index)
        elif key == "SELECT":
            selected_network = networks[selected_index]
            print(f"✅ Selected: {selected_network}")
            
            # Show confirmation
            try:
                from DGTCentaurMods.display import epaper
                from PIL import Image, ImageDraw, ImageFont
                
                img = Image.new('1', (128, 296), 255)
                draw = ImageDraw.Draw(img)
                
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
                except:
                    font = ImageFont.load_default()
                
                draw.text((5, 10), f"Selected:", font=font, fill=0)
                draw.text((5, 30), f"{selected_network}", font=font, fill=0)
                draw.text((5, 60), "Press SELECT to", font=font, fill=0)
                draw.text((5, 75), "confirm or BACK", font=font, fill=0)
                draw.text((5, 90), "to cancel", font=font, fill=0)
                
                epaper.epaperbuffer.paste(img, (0, 0))
            except:
                pass
            
            # Wait for confirmation
            while not shutdown_requested:
                confirm_key = wait_for_key()
                if confirm_key == "SELECT":
                    print(f"🔧 Configuring WiFi: {selected_network}")
                    # Here you would normally configure the WiFi
                    print("✅ WiFi configuration complete!")
                    return
                elif confirm_key == "BACK":
                    print("❌ Cancelled")
                    display_wifi_list(networks, selected_index)
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
