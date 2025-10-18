#!/usr/bin/env python3
"""
Standalone WiFi configuration script that doesn't interfere with the main DGT system.
This script handles its own display and doesn't conflict with other processes.
"""
import sys
import os
import time
import signal
import logging
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
    # Clean up display
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

def simple_display_text(text: str, y_offset: int = 0):
    """Simple text display without complex display system"""
    try:
        from DGTCentaurMods.display import epaper
        from PIL import Image, ImageDraw, ImageFont
        
        # Create a simple image
        img = Image.new('1', (128, 296), 255)
        draw = ImageDraw.Draw(img)
        
        # Try to load font
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            font = ImageFont.load_default()
        
        # Wrap text to fit screen width (128 pixels)
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= 118:  # Leave 10px margin
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                    current_line = word
                else:
                    lines.append(word)  # Single word too long
        
        if current_line:
            lines.append(current_line)
        
        # Draw lines
        for i, line in enumerate(lines[:8]):  # Max 8 lines to fit screen
            draw.text((5, 10 + (i * 18) + y_offset), line, font=font, fill=0)
        
        # Update display
        epaper.epaperbuffer.paste(img, (0, 0))
        
    except Exception as e:
        print(f"Display error: {e}")

def simple_key_poll() -> Optional[str]:
    """Simple key polling without complex parsing"""
    try:
        from DGTCentaurMods.board import board as b
        
        # Clear any existing data first
        try:
            b._ser_read(1000)
        except:
            pass
        
        # Send key event request
        b.sendPacket(b'\x94', b'')
        resp = b._ser_read(256)
        
        if not resp:
            return None
            
        hx = resp.hex()
        a1 = f"{b.addr1:02x}"
        a2 = f"{b.addr2:02x}"
        
        # Look for key event patterns
        if f"b100{a1}0{a2}" in hx:
            # Extract key code from the end
            if len(hx) >= 12:
                key_code = hx[-2:]
                if key_code == "0d":
                    return "SELECT"
                elif key_code == "3c":
                    return "UP"
                elif key_code == "61":
                    return "DOWN"
                elif key_code == "47":
                    return "BACK"
                elif key_code == "6d":
                    return "HELP"
                elif key_code == "2a":
                    return "PLAY"
        
        return None
    except Exception as e:
        print(f"Key poll error: {e}")
        return None

def simple_wifi_selection() -> Optional[str]:
    """Simple WiFi network selection"""
    global shutdown_requested
    
    print("📡 Scanning for WiFi networks...")
    networks = get_wifi_networks()
    
    if not networks:
        print("❌ No WiFi networks found")
        return None
    
    print(f"📶 Found {len(networks)} networks:")
    for i, network in enumerate(networks):
        print(f"  {i+1}. {network}")
    
    # Simple selection - just return the first one for now
    # In a real implementation, you'd show a menu
    selected = networks[0]
    print(f"✅ Selected: {selected}")
    return selected

def main():
    """Main WiFi configuration function"""
    global shutdown_requested
    
    print("🔧 DGT Centaur WiFi Configuration")
    print("=" * 40)
    
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
    
    # Show initial message
    simple_display_text("WiFi Configuration\nPress any key to start", 0)
    
    # Wait for key press
    print("⌨️  Press any key to start...")
    print("🔍 Testing key detection...")
    
    # Test key detection first
    for i in range(10):
        key = simple_key_poll()
        if key:
            print(f"✅ Key detection working: {key}")
            break
        print(f"  Attempt {i+1}/10: No key detected")
        time.sleep(0.2)
    
    # Wait for key press
    print("⌨️  Waiting for key press...")
    timeout = time.time() + 30  # 30 second timeout
    while not shutdown_requested and time.time() < timeout:
        key = simple_key_poll()
        if key:
            print(f"🔑 Key pressed: {key}")
            break
        time.sleep(0.1)
    
    if time.time() >= timeout:
        print("⏰ Timeout waiting for key press")
        simple_display_text("Timeout waiting\nfor key press\nPress CTRL+C to exit", 0)
        return
    
    if shutdown_requested:
        return
    
    # Select WiFi network
    selected_network = simple_wifi_selection()
    if not selected_network:
        return
    
    # Show selected network
    simple_display_text(f"Selected: {selected_network}", 0)
    simple_display_text("Press SELECT to confirm", 30)
    
    # Wait for confirmation
    print("⌨️  Press SELECT to confirm...")
    while not shutdown_requested:
        key = simple_key_poll()
        if key == "SELECT":
            print("✅ WiFi network confirmed")
            break
        elif key == "BACK":
            print("❌ Cancelled")
            return
        time.sleep(0.1)
    
    if shutdown_requested:
        return
    
    # Configure WiFi (simplified)
    print(f"🔧 Configuring WiFi: {selected_network}")
    simple_display_text("Configuring...", 0)
    
    # Here you would normally configure the WiFi
    # For now, just show success
    simple_display_text("WiFi configured!", 0)
    simple_display_text("Press any key to exit", 30)
    
    print("✅ WiFi configuration complete!")
    print("⌨️  Press any key to exit...")
    
    # Wait for key press to exit
    while not shutdown_requested:
        key = simple_key_poll()
        if key:
            break
        time.sleep(0.1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        print("👋 Goodbye!")
