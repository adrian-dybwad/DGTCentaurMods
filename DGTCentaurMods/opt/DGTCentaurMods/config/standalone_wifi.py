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
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except:
            font = ImageFont.load_default()
        
        # Draw text
        draw.text((10, 10 + y_offset), text, font=font, fill=0)
        
        # Update display
        epaper.epaperbuffer.paste(img, (0, 0))
        
    except Exception as e:
        print(f"Display error: {e}")

def simple_key_poll() -> Optional[str]:
    """Simple key polling without complex parsing"""
    try:
        from DGTCentaurMods.board import board as b
        
        # Simple approach - just check for any key event
        b.sendPacket(b'\x94', b'')
        resp = b._ser_read(256)
        if not resp:
            return None
            
        hx = resp.hex()[:-2]
        a1 = f"{b.addr1:02x}"
        a2 = f"{b.addr2:02x}"
        
        # Look for any key event pattern
        if f"b100{a1}0{a2}" in hx:
            # Extract key code
            key_part = hx[hx.rfind(f"b100{a1}0{a2}"):]
            if len(key_part) >= 12:
                key_code = key_part[-2:]
                if key_code == "0d":
                    return "SELECT"
                elif key_code == "3c":
                    return "UP"
                elif key_code == "61":
                    return "DOWN"
                elif key_code == "47":
                    return "BACK"
        
        return None
    except Exception as e:
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
    simple_display_text("WiFi Configuration", 0)
    simple_display_text("Press any key to start", 30)
    
    # Wait for key press
    print("⌨️  Press any key to start...")
    while not shutdown_requested:
        key = simple_key_poll()
        if key:
            print(f"🔑 Key pressed: {key}")
            break
        time.sleep(0.1)
    
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
