#!/usr/bin/env python3
"""
Text input functionality for DGT Centaur board using buttons.
"""

import time
import logging
from typing import Optional
from PIL import Image, ImageDraw, ImageFont


def getTextFromButtonsAndKeyboard(prompt="Enter text", board_obj=None):
    """
    Get text input from the user using board buttons.
    Returns the entered text or None if cancelled.
    
    Args:
        prompt: The prompt to display to the user
        board_obj: The board object to use for communication (optional)
    """
    from DGTCentaurMods.display import epaper
    
    # Import board functions if board_obj not provided
    if board_obj is None:
        from DGTCentaurMods.board.board import sendPacket, _ser_read, addr1, addr2, pauseEvents, unPauseEvents
    else:
        # Use methods from the provided board object
        sendPacket = board_obj.sendPacket
        _ser_read = board_obj._ser_read
        addr1 = board_obj.addr1
        addr2 = board_obj.addr2
        pauseEvents = board_obj.pauseEvents
        unPauseEvents = board_obj.unPauseEvents
    
    # Character sets for input
    char_sets = [
        "abcdefghijklmnopqrstuvwxyz",  # lowercase
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",  # uppercase  
        "0123456789",                  # numbers
        " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",  # symbols
    ]
    
    current_set = 0
    current_char_index = 0
    typed_text = ""
    
    # Display dimensions
    W, H = 128, 296
    margin = 6
    line_h = 18
    
    def _render():
        nonlocal typed_text, current_set, current_char_index
        
        # Create image
        image = Image.new('1', (W, H), 255)
        draw = ImageDraw.Draw(image)
        
        # Load font
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            font = ImageFont.load_default()
        
        # Draw prompt
        draw.text((margin, margin), prompt, font=font, fill=0)
        
        # Draw current text
        draw.text((margin, margin + line_h), f"Text: {typed_text}_", font=font, fill=0)
        
        # Draw current character set and character
        set_names = ["abc", "ABC", "123", "!@#"]
        draw.text((margin, margin + line_h * 2), f"Set: {set_names[current_set]}", font=font, fill=0)
        draw.text((margin, margin + line_h * 3), f"Char: {char_sets[current_set][current_char_index]}", font=font, fill=0)
        
        # Draw instructions
        draw.text((margin, margin + line_h * 5), "UP/DOWN: navigate", font=font, fill=0)
        draw.text((margin, margin + line_h * 6), "SELECT: add char", font=font, fill=0)
        draw.text((margin, margin + line_h * 7), "BACK: delete", font=font, fill=0)
        draw.text((margin, margin + line_h * 8), "HELP: confirm", font=font, fill=0)
        
        # Update display
        epaper.epaperbuffer.paste(image, (0, 0))
    
    # Initialize display
    epaper.initEpaper()
    epaper.clearScreen()
    _render()
    
    # Pause events to avoid conflicts
    pauseEvents()
    
    try:
        # Text input loop
        while True:
            # Check for button presses
            try:
                sendPacket(b'\x94', b'')
                resp = _ser_read(256)
                
                if resp:
                    hx = resp.hex()
                    a1 = f"{addr1:02x}"
                    a2 = f"{addr2:02x}"
                    
                    # Check for button patterns
                    if "00140a0508000000007d3c" in hx:  # UP
                        current_char_index = (current_char_index - 1) % len(char_sets[current_set])
                        _render()
                    elif "00140a05020000000061" in hx:  # DOWN
                        current_char_index = (current_char_index + 1) % len(char_sets[current_set])
                        _render()
                    elif "00140a0510000000007d17" in hx:  # SELECT/TICK
                        typed_text += char_sets[current_set][current_char_index]
                        _render()
                    elif "00140a0501000000007d47" in hx:  # BACK
                        if typed_text:
                            typed_text = typed_text[:-1]
                            _render()
                    elif "00140a0540000000006d" in hx:  # HELP
                        # Confirm and return
                        unPauseEvents()
                        return typed_text
                    
            except Exception as e:
                logging.debug(f"Error in getText: {e}")
            
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        unPauseEvents()
        return None
    except Exception as e:
        logging.debug(f"Error in getText: {e}")
        unPauseEvents()
        return None


# Alias for backward compatibility
getText = getTextFromButtonsAndKeyboard
