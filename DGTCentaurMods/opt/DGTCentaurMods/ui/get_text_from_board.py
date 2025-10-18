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
    Pauses events; robust against short/partial serial reads.
    BACK deletes, TICK confirms, UP/DOWN switch pages.
    
    Args:
        title: The title/prompt to display to the user
        board_obj: The board object to use for communication (optional)
        manage_events: Whether to pause/unpause events (default True)
    """
    print(f"getText function called with title='{title}', board_obj={board_obj is not None}, manage_events={manage_events}")
    
    from DGTCentaurMods.display import epaper
    
    global screenbuffer
    
    # Import board functions if board_obj not provided
    if board_obj is None:
        from DGTCentaurMods.board.board import (
            pauseEvents, unPauseEvents, getBoardState, clearSerial, 
            sendPacket, _ser_read, addr1, addr2, beep, SOUND_GENERAL, 
            SOUND_WRONG, BTNBACK, BTNTICK, BTNUP, BTNDOWN, clearScreen,
            writeTextToBuffer, writeText, font18, screenbuffer
        )
    else:
        # Use methods from the provided board object
        pauseEvents = board_obj.pauseEvents
        unPauseEvents = board_obj.unPauseEvents
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
    epaper.initEpaper()
    epaper.clearScreen()
    print("Display initialized and cleared")
    
    try:
        if manage_events:
            try:
                pauseEvents()
            except Exception:
                pass

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
        # Skip the "remove pieces" check for now
        # if res != clearstate:
        #     writeTextToBuffer(0, "Remove board")
        #     writeText(1, "pieces")
        #     deadline = time.time() + 20
        #     while time.time() < deadline:
        #         time.sleep(0.4)
        #         res = getBoardState()
        #         if isinstance(res, list) and len(res) == 64 and res == clearstate:
        #             break

        clearSerial()

        def _render():
            nonlocal typed, charpage
            global screenbuffer
            print(f"Rendering text input UI: '{typed}' (page {charpage})")
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
            # Remove the image transformations that cause distortion
            # Just use the image directly without flipping
            epaper.epaperbuffer.paste(image, (0, 0))
            # Force a display refresh
            try:
                epaper.refresh()
                print("Display refreshed successfully")
            except Exception as e:
                print(f"Display refresh failed: {e}")

        def _read_fields_and_type():
            nonlocal typed, charpage
            try:
                sendPacket(b'\x83', b'')
                resp = _ser_read(10000)
                if len(resp) >= 2 and resp[0] == 133 and resp[1] == 0:
                    i = 0
                    while i < len(resp) - 1:
                        tag = resp[i]
                        if tag == 65:  # placed
                            fieldHex = resp[i + 1]
                            if 0 <= fieldHex < 64:
                                base = (charpage - 1) * 64
                                ch = printableascii[base + fieldHex]
                                typed += ch
                                beep(SOUND_GENERAL)
                                print(f"Piece placed on field {fieldHex}, added char '{ch}'")
                                return True
                            i += 2
                        elif tag == 64:  # lifted
                            i += 2
                        else:
                            i += 1
            except Exception as e:
                print(f"Error in _read_fields_and_type: {e}")
            return False

        def _read_buttons():
            try:
                from DGTCentaurMods.ui.input_adapters import poll_actions_from_board
                action = poll_actions_from_board()
                if action:
                    print(f"poll_actions_from_board returned: {action}")
                if action == "BACK":
                    print("Detected BACK button")
                    return BTNBACK
                elif action == "SELECT":
                    print("Detected SELECT button")
                    return BTNTICK
                elif action == "UP":
                    print("Detected UP button")
                    return BTNUP
                elif action == "DOWN":
                    print("Detected DOWN button")
                    return BTNDOWN
            except Exception as e:
                print(f"Error in _read_buttons: {e}")
            return 0

        print("Starting main input loop...")
        _render()
        last_draw = 0.0
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
                
            try:
                typed_changed = _read_fields_and_type()
                btn = _read_buttons()
                
                if btn != 0:
                    print(f"Button pressed: {btn}")
                
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
                
                if typed_changed:
                    print(f"Piece detected, typed now: '{typed}'")

                if changed or typed_changed or (time.time() - last_draw) > 0.5:
                    _render()
                    last_draw = time.time()
                    changed = False

            except Exception as e:
                print(f"Error in main loop: {e}")
                
            time.sleep(0.05)

    finally:
        if manage_events:
            try:
                unPauseEvents()
            except Exception:
                pass