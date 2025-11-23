# DGTCentaurMods/ui/simple_text_input.py
from typing import Optional, Callable
from PIL import Image, ImageDraw, ImageFont
import time
import logging
import signal
import sys
import os

from DGTCentaurMods.display.epaper_service import service

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle CTRL+C gracefully"""
    global shutdown_requested
    print("\n🛑 Shutdown requested...")
    shutdown_requested = True
    # Force exit immediately
    os._exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

ActionPoller = Callable[[], Optional[str]]  # "UP"/"DOWN"/"SELECT"/"BACK"/None

def simple_text_input(
    title: str = "Enter Password",
    poll_action: ActionPoller = lambda: None,
    initial_text: str = "",
    max_length: int = 20,
    font_size: int = 18,
    timeout_seconds: float = 60.0,
) -> Optional[str]:
    """
    Simple text input using only button navigation.
    More reliable than getText as it doesn't rely on board state detection.
    """
    from DGTCentaurMods.asset_manager import AssetManager

    # Load fonts
    def load_font(sz: int):
        try:
            return ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), sz)
        except Exception:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", sz)

    font = load_font(font_size)
    font_small = load_font(font_size - 2)

    # Character sets for input
    char_sets = [
        "abcdefghijklmnopqrstuvwxyz",  # lowercase
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",  # uppercase  
        "0123456789",                  # numbers
        " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",  # symbols
    ]
    
    current_set = 0
    current_char_index = 0
    typed_text = initial_text
    cursor_pos = len(typed_text)
    
    # Display dimensions
    W, H = 128, 296
    margin = 6
    line_h = font_size + 4
    
    def _render():
        nonlocal typed_text, current_set, current_char_index, cursor_pos

        img = Image.new("1", (W, H), 255)
        draw = ImageDraw.Draw(img)
        
        # Title
        draw.text((margin, margin), title, font=font_small, fill=0)
        
        # Text input area
        draw.rectangle([margin, margin + line_h, W - margin, margin + line_h * 2], outline=0, fill=255)
        
        # Display typed text with cursor
        display_text = typed_text
        if len(display_text) > 15:  # Truncate if too long
            display_text = "..." + display_text[-12:]
        
        draw.text((margin + 2, margin + line_h + 2), display_text, font=font, fill=0)
        
        # Character set display
        char_set = char_sets[current_set]
        char_y = margin + line_h * 3
        
        # Show current character set name
        set_names = ["abc", "ABC", "123", "!@#"]
        draw.text((margin, char_y), f"Set: {set_names[current_set]}", font=font_small, fill=0)
        
        # Show current character highlighted
        char_x = margin
        char_y += line_h
        for i, char in enumerate(char_set[:16]):  # Show first 16 chars
            if i == current_char_index:
                # Highlight current character
                draw.rectangle([char_x - 1, char_y - 1, char_x + 12, char_y + line_h - 1], fill=0)
                fill_color = 255
            else:
                fill_color = 0
            draw.text((char_x, char_y), char, font=font_small, fill=fill_color)
            char_x += 14
            if char_x > W - margin - 14:
                char_x = margin
                char_y += line_h
        
        # Instructions
        instructions = "↑↓: navigate  ←: back  →: select"
        draw.text((margin, H - margin - line_h), instructions, font=font_small, fill=0)
        
        service.blit(img)

    # Initial render
    service.init()
    _render()
    
    start_time = time.time()
    last_action_time = time.time()
    
    while True:
        # Check for shutdown request
        if shutdown_requested:
            logging.info("Text input cancelled by user")
            return None
            
        # Check timeout
        if time.time() - start_time > timeout_seconds:
            logging.warning("Text input timed out")
            return None
            
        try:
            act = poll_action()
        except Exception as e:
            logging.error(f"Error in poll_action: {e}")
            time.sleep(0.01)
            continue
            
        if act is None:
            time.sleep(0.01)
            continue
            
        # Debounce rapid button presses
        now = time.time()
        if now - last_action_time < 0.1:  # 100ms debounce
            continue
        last_action_time = now
        
        char_set = char_sets[current_set]
        
        if act == "UP":
            current_char_index = (current_char_index - 1) % len(char_set)
            _render()
        elif act == "DOWN":
            current_char_index = (current_char_index + 1) % len(char_set)
            _render()
        elif act == "BACK":
            if len(typed_text) > 0:
                typed_text = typed_text[:-1]
                cursor_pos = len(typed_text)
                _render()
            else:
                # Empty text, exit
                return None
        elif act == "SELECT":
            if len(char_set) > 0:
                # Add character
                if len(typed_text) < max_length:
                    typed_text += char_set[current_char_index]
                    cursor_pos = len(typed_text)
                    _render()
                else:
                    # Text too long, cycle through character sets
                    current_set = (current_set + 1) % len(char_sets)
                    current_char_index = 0
                    _render()
            else:
                # Confirm text entry
                return typed_text
        elif act == "HELP":  # Use HELP button to confirm
            return typed_text
        elif act == "PLAY":  # Use PLAY button to cycle character sets
            current_set = (current_set + 1) % len(char_sets)
            current_char_index = 0
            _render()
