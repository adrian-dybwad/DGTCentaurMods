# DGTCentaurMods/ui/input_adapters.py
from typing import Optional
import time
import logging
import threading
import queue
from DGTCentaurMods.board import board as b

# Global event and state for WiFi menu
wifi_event_key = threading.Event()
wifi_selection = ""
wifi_menuitem = 0
wifi_curmenu = None

def wifi_button_callback(button_id):
    """Callback function for WiFi menu button events - same pattern as main menu"""
    global wifi_selection, wifi_menuitem, wifi_curmenu, wifi_event_key
    
    if button_id == b.BTNBACK:
        wifi_selection = "BACK"
        wifi_event_key.set()
        return
    elif button_id == b.BTNTICK:
        if wifi_curmenu:
            c = 1
            for k, v in wifi_curmenu.items():
                if c == wifi_menuitem:
                    wifi_selection = k
                    wifi_event_key.set()
                    wifi_menuitem = 1
                    return
                c = c + 1
        else:
            wifi_selection = "BTNTICK"
            wifi_event_key.set()
            return
    elif button_id == b.BTNUP:
        wifi_menuitem = wifi_menuitem - 1
    elif button_id == b.BTNDOWN:
        wifi_menuitem = wifi_menuitem + 1
    elif button_id == b.BTNHELP:
        wifi_selection = "BTNHELP"
        wifi_event_key.set()
        return
    
    # Handle menu bounds
    if wifi_curmenu is None:
        return
    if wifi_menuitem < 1:
        wifi_menuitem = len(wifi_curmenu)
    if wifi_menuitem > len(wifi_curmenu):
        wifi_menuitem = 1
    
    # Update display immediately - same as main menu
    try:
        from DGTCentaurMods.display import epaper
        from PIL import Image, ImageDraw, ImageFont
        
        # Load font
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except:
            font = ImageFont.load_default()
        
        # Create image
        image = Image.new('1', (128, 296), 255)
        draw = ImageDraw.Draw(image)
        
        # Draw title
        draw.text((5, 5), "[ Wi-Fi Networks ]", font=font, fill=0)
        y_start = 25
        
        # Draw menu items
        row = 0
        for k, v in wifi_curmenu.items():
            y_pos = y_start + (row * 20)
            prefix = ">" if (row + 1) == wifi_menuitem else " "
            text = f"{prefix} {str(v)}"
            draw.text((5, y_pos), text, font=font, fill=0)
            row += 1
        
        # Update display
        epaper.epaperbuffer.paste(image, (0, 0))
        
    except Exception as e:
        logging.error(f"Failed to update display: {e}")

def start_wifi_subscription():
    """Start WiFi event subscription using multi-subscriber system"""
    try:
        # Subscribe to events - this will add us to the multi-subscriber list
        b.subscribeEvents(wifi_button_callback, None, timeout=3600)
        logging.debug("Started WiFi event subscription")
        return True
    except Exception as e:
        logging.error(f"Error starting WiFi subscription: {e}")
        return False

def stop_wifi_subscription():
    """Stop WiFi event subscription"""
    try:
        # Unsubscribe from events - this will remove us from the multi-subscriber list
        b.unsubscribeEvents(wifi_button_callback, None)
        logging.debug("Stopped WiFi event subscription")
        return True
    except Exception as e:
        logging.error(f"Error stopping WiFi subscription: {e}")
        return False

def wifi_menu_wait():
    """Wait for WiFi menu event - same pattern as main menu"""
    global wifi_event_key, wifi_selection
    wifi_event_key.wait()
    wifi_event_key.clear()
    return wifi_selection

def do_wifi_menu(menu, title=None):
    """WiFi menu function - same pattern as main menu doMenu()"""
    global wifi_menuitem, wifi_curmenu, wifi_selection, wifi_event_key
    
    # Initialize display
    try:
        from DGTCentaurMods.display import epaper
        epaper.epapermode = 0
        epaper.clearScreen()
    except Exception as e:
        logging.error(f"Failed to initialize epaper display: {e}")
        return None
    
    wifi_selection = ""
    wifi_curmenu = menu
    wifi_menuitem = 1
    
    # Display the menu
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # Load font
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except:
            font = ImageFont.load_default()
        
        # Create image
        image = Image.new('1', (128, 296), 255)
        draw = ImageDraw.Draw(image)
        
        # Draw title
        if title:
            draw.text((5, 5), f"[ {title} ]", font=font, fill=0)
            y_start = 25
        else:
            y_start = 5
        
        # Draw menu items
        row = 0
        for k, v in menu.items():
            y_pos = y_start + (row * 20)
            prefix = ">" if (row + 1) == wifi_menuitem else " "
            text = f"{prefix} {str(v)}"
            draw.text((5, y_pos), text, font=font, fill=0)
            row += 1
        
        # Update display
        epaper.epaperbuffer.paste(image, (0, 0))
        
    except Exception as e:
        logging.error(f"Failed to draw menu: {e}")
        return None
    
    # Wait for selection - same as main menu
    wifi_event_key.wait()
    wifi_event_key.clear()
    return wifi_selection
