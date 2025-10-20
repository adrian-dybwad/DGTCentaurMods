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


def getText(title="Enter text"):
    """
    Enter text using the board as a virtual keyboard.
    Uses event-based system with blocking .wait() for immediate response.
    BACK deletes, TICK confirms, UP/DOWN switch pages.
    
    This function automatically disables the main menu handler during text input
    and re-enables it when done.
    
    Args:
        title: The title/prompt to display to the user
    """
    print(f"getText function called with title='{title}'")
    
    try:
        from DGTCentaurMods.display import epaper
        print("Imported epaper successfully")
        from DGTCentaurMods.ui import input_adapters
        print("Imported input_adapters successfully")
        from DGTCentaurMods.board import board
        print("Imported board successfully")
        #from DGTCentaurMods.ui.shared_state import main_menu_disabled
        #print("Imported main_menu_disabled successfully")
    except ImportError as e:
        print(f"ERROR: Import failed: {e}")
        import traceback
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error during imports: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    try:
        # Disable main menu handler
        #try:
        #    main_menu_disabled = True
        #    print("Main menu handler disabled")
        #except Exception as e:
        #    print(f"ERROR: Failed to disable main menu handler: {e}")
        #    import traceback
        #    traceback.print_exc()
        #    return None
        
        try:
            # Start event subscription
            if not input_adapters.start_text_input_subscription():
                print("ERROR: Failed to start text input subscription")
                return None
            print("Event subscription started successfully")

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

            try:
                res = board.getBoardState()
                if not isinstance(res, list) or len(res) != 64:
                    res = [0] * 64
                print("Board state retrieved successfully")
            except Exception as e:
                print(f"ERROR: Failed to get board state: {e}")
                import traceback
                traceback.print_exc()
                res = [0] * 64

            try:
                board.clearSerial()
                print("Serial cleared successfully")
            except Exception as e:
                print(f"ERROR: Failed to clear serial: {e}")
                import traceback
                traceback.print_exc()

            def _render():
                nonlocal typed, charpage
                try:
                    print(f"Rendering text input UI: '{typed}' (page {charpage})")
                    # Create image with correct dimensions for the display
                    image = Image.new('1', (128, 296), 255)
                    draw = ImageDraw.Draw(image)
                    draw.text((0, 20), title, font=board.font18, fill=0)
                    draw.rectangle([(0, 39), (128, 61)], outline=0, fill=255)
                    tt = typed[-11:] if len(typed) > 11 else typed
                    draw.text((0, 40), tt, font=board.font18, fill=0)
                    page_start = (charpage - 1) * 64
                    lchars = [printableascii[i] for i in range(page_start, page_start + 64)]
                    for row in range(8):
                        for col in range(8):
                            ch = lchars[row * 8 + col]
                            draw.text((col * 16, 80 + row * 20), ch, font=board.font18, fill=0)
                    # Update the display buffer - background thread will handle refresh
                    epaper.epaperbuffer.paste(image, (0, 0))
                    print("Display buffer updated")
                except Exception as e:
                    print(f"ERROR: Failed to render display: {e}")
                    import traceback
                    traceback.print_exc()

            try:
                print("Starting main input loop...")
                _render()
                start_time = time.time()
                timeout_seconds = 300  # 5 minute timeout
                
                while True:
                    try:
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

                        input_adapters.text_input_event.clear()

                        if input_adapters.text_input_event_type == 'button':
                            btn = input_adapters.text_input_button
                            print(f"Button event received: {btn}")
                            
                            try:
                                if btn == board.BTNBACK:
                                    if typed:
                                        typed = typed[:-1]
                                        board.beep(board.SOUND_GENERAL)
                                        changed = True
                                        print(f"Deleted character, typed now: '{typed}'")
                                    else:
                                        board.beep(board.SOUND_WRONG)
                                        print("No characters to delete")
                                elif btn == board.BTNTICK:
                                    board.beep(board.SOUND_GENERAL)
                                    board.clearScreen()
                                    time.sleep(0.2)
                                    print(f"Text input confirmed: '{typed}'")
                                    return typed
                                elif btn == board.BTNUP and charpage != 1:
                                    charpage = 1
                                    board.beep(board.SOUND_GENERAL)
                                    changed = True
                                    print("Switched to page 1")
                                elif btn == board.BTNDOWN and charpage != 2:
                                    charpage = 2
                                    board.beep(board.SOUND_GENERAL)
                                    changed = True
                                    print("Switched to page 2")
                            except Exception as e:
                                print(f"ERROR: Failed to handle button event {btn}: {e}")
                                import traceback
                                traceback.print_exc()
                                
                        elif input_adapters.text_input_event_type == 'field':
                            field = input_adapters.text_input_field
                            print(f"Field event received: {field}")
                            
                            try:
                                # Process field event for piece placement
                                if 0 <= field < 64:
                                    base = (charpage - 1) * 64
                                    ch = printableascii[base + field]
                                    typed += ch
                                    board.beep(board.SOUND_GENERAL)
                                    print(f"Piece placed on field {field}, added char '{ch}'")
                                    changed = True
                            except Exception as e:
                                print(f"ERROR: Failed to handle field event {field}: {e}")
                                import traceback
                                traceback.print_exc()

                        if changed:
                            try:
                                _render()
                                changed = False
                            except Exception as e:
                                print(f"ERROR: Failed to re-render after change: {e}")
                                import traceback
                                traceback.print_exc()
                                changed = False
                    except Exception as e:
                        print(f"ERROR: Unexpected error in main event loop: {e}")
                        import traceback
                        traceback.print_exc()
                        # Continue the loop to avoid hanging
                        continue
                        
            except Exception as e:
                print(f"ERROR: Failed to start main input loop: {e}")
                import traceback
                traceback.print_exc()
                return None

        except Exception as e:
            print(f"ERROR: Unexpected error in event subscription logic: {e}")
            import traceback
            traceback.print_exc()
            return None

        finally:
            # Always stop event subscription
            try:
                input_adapters.stop_text_input_subscription()
                print("Event subscription stopped successfully")
            except Exception as e:
                print(f"ERROR: Failed to stop event subscription: {e}")
                import traceback
                traceback.print_exc()
            
    except Exception as e:
        print(f"ERROR: Unexpected error in main text input logic: {e}")
        import traceback
        traceback.print_exc()
        return None
            
    finally:
        # Always re-enable main menu handler
        # try:
        #     main_menu_disabled = False
        #     print("Main menu handler re-enabled")
        # except Exception as e:
        #     print(f"ERROR: Failed to re-enable main menu handler: {e}")
        #     import traceback
        #     traceback.print_exc()