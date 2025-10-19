#!/usr/bin/env python3
"""
Text input functionality for DGT Centaur board using board pieces as a virtual keyboard.
This module provides a getText function that takes a title parameter.
"""

import time
import logging
import signal
import sys
import os
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

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


def getText(title="Enter text", board_obj=None, manage_events=True):
    """
    Enter text using the board as a virtual keyboard.
    Uses event-based system with blocking .wait() for immediate response.
    BACK deletes, TICK confirms, UP/DOWN switch pages.
    
    Args:
        title: The title/prompt to display to the user
        board_obj: The board object to use for communication (optional)
        manage_events: Whether to manage event subscriptions (default True)
    """
    print(f"getText function called with title='{title}', board_obj={board_obj is not None}, manage_events={manage_events}")
    
    from DGTCentaurMods.display import epaper
    from DGTCentaurMods.ui import input_adapters
    
    global screenbuffer
    
    # Import board functions if board_obj not provided
    if board_obj is None:
        from DGTCentaurMods.board.board import (
            getBoardState, clearSerial, 
            sendPacket, _ser_read, addr1, addr2, beep, SOUND_GENERAL, 
            SOUND_WRONG, BTNBACK, BTNTICK, BTNUP, BTNDOWN, clearScreen,
            writeTextToBuffer, writeText, font18, screenbuffer
        )
    else:
        # Use methods from the provided board object
        getBoardState = board_obj.getBoardState
        clearSerial = board_obj.clearSerial
        sendPacket = board_obj.sendPacket
        _ser_read = board_obj._ser_read
        addr1 = board_obj.addr1
        addr2 = board_obj.addr2
        beep = board_obj.beep
        SOUND_GENERAL = board_obj.SOUND_GENERAL
        SOUND_WRONG = board_obj.SOUND_WRONG
        BTNBACK = board_obj.BTNBACK
        BTNTICK = board_obj.BTNTICK
        BTNUP = board_obj.BTNUP
        BTNDOWN = board_obj.BTNDOWN
        clearScreen = board_obj.clearScreen
        writeTextToBuffer = board_obj.writeTextToBuffer
        writeText = board_obj.writeText
        font18 = board_obj.font18
        screenbuffer = board_obj.screenbuffer
    
    # Initialize display
    print(f"Initializing display for text input: {title}")
    try:
        # Use the existing epaper system - just clear the buffer
        epaper.epaperbuffer.paste(Image.new('1', (128, 296), 255), (0, 0))
        print("Display buffer cleared")
    except Exception as e:
        print(f"Display initialization error: {e}")
        return None
    
    try:
        # Start event subscription
        if manage_events:
            if not start_text_input_subscription():
                print("Failed to start text input subscription")
                return None

        clearstate = [0] * 64
        printableascii = (
            " !\"#$%&'()*+,-./0123456789:;<=>?@"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
            "abcdefghijklmnopqrstuvwxyz{|}~"
            + (" " * (64 * 2 - 95))
        )
        charpage = 1
        typed = ""
        changed = True

        res = getBoardState()
        if not isinstance(res, list) or len(res) != 64:
            res = [0] * 64

        clearSerial()

        def _render():
            nonlocal typed, charpage
            global screenbuffer
            print(f"Rendering text input UI: '{typed}' (page {charpage})")
            # Create image with correct dimensions for the display
            image = Image.new('1', (128, 296), 255)
            draw = ImageDraw.Draw(image)
            draw.text((0, 20), title, font=font18, fill=0)
            draw.rectangle([(0, 39), (128, 61)], outline=0, fill=255)
            tt = typed[-11:] if len(typed) > 11 else typed
            draw.text((0, 40), tt, font=font18, fill=0)
            page_start = (charpage - 1) * 64
            lchars = [printableascii[i] for i in range(page_start, page_start + 64)]
            for row in range(8):
                for col in range(8):
                    ch = lchars[row * 8 + col]
                    draw.text((col * 16, 80 + row * 20), ch, font=font18, fill=0)
            screenbuffer = image.copy()
            # Update the display buffer - background thread will handle refresh
            epaper.epaperbuffer.paste(image, (0, 0))
            print("Display buffer updated")

        print("Starting main input loop...")
        _render()
        start_time = time.time()
        timeout_seconds = 300  # 5 minute timeout
        
        while True:
            # Check for shutdown request
            if shutdown_requested:
                print("Shutdown requested, exiting text input")
                return None
            
            # Check for timeout
            if time.time() - start_time > timeout_seconds:
                print("Text input timeout")
                return None
            
            # Blocking wait for ANY event (button or field)
            print("Waiting for event...")
            event_received = input_adapters.text_input_event.wait(timeout=60)
            
            if not event_received:
                print("Event timeout, continuing...")
                continue

            print(f"event_received {event_received}")    
            print(f"text_input_event_type {input_adapters.text_input_event_type}")
            print(f"text_input_button {input_adapters.text_input_button}")
            print(f"text_input_field {input_adapters.text_input_field}")
            print(f"BTNBACK {BTNBACK}")
            print(f"BTNTICK {BTNTICK}")
            print(f"BTNUP {BTNUP}")
            print(f"BTNDOWN {BTNDOWN}")

            text_input_event.clear()

            print(f"text_input_event_type {text_input_event_type}")
            print(f"text_input_button {input_adapters.text_input_button}")
            print(f"text_input_field {input_adapters.text_input_field}")
            print(f"BTNBACK {BTNBACK}")
            print(f"BTNTICK {BTNTICK}")
            print(f"BTNUP {BTNUP}")
            print(f"BTNDOWN {BTNDOWN}")
            
            if input_adapters.text_input_event_type == 'button':
                btn = input_adapters.text_input_button
                print(f"Button event received: {btn}")
                
                if btn == BTNBACK:
                    if typed:
                        typed = typed[:-1]
                        beep(SOUND_GENERAL)
                        changed = True
                        print(f"Deleted character, typed now: '{typed}'")
                    else:
                        beep(SOUND_WRONG)
                        print("No characters to delete")
                elif btn == BTNTICK:
                    beep(SOUND_GENERAL)
                    clearScreen()
                    time.sleep(0.2)
                    print(f"Text input confirmed: '{typed}'")
                    return typed
                elif btn == BTNUP and charpage != 1:
                    charpage = 1
                    beep(SOUND_GENERAL)
                    changed = True
                    print("Switched to page 1")
                elif btn == BTNDOWN and charpage != 2:
                    charpage = 2
                    beep(SOUND_GENERAL)
                    changed = True
                    print("Switched to page 2")
                    
            elif input_adapters.text_input_event_type == 'field':
                field = input_adapters.text_input_field
                print(f"Field event received: {field}")
                
                # Process field event for piece placement
                if 0 <= field < 64:
                    base = (charpage - 1) * 64
                    ch = printableascii[base + field]
                    typed += ch
                    beep(SOUND_GENERAL)
                    print(f"Piece placed on field {field}, added char '{ch}'")
                    changed = True

            if changed:
                _render()
                changed = False

    finally:
        if manage_events:
            stop_text_input_subscription()