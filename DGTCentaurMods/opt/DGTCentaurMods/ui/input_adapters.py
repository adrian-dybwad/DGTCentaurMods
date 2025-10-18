# DGTCentaurMods/ui/input_adapters.py
from typing import Optional
import time
import logging
import threading
import queue
from DGTCentaurMods.board import board as b

# Global queue for button events
button_queue = queue.Queue()

def wifi_button_callback(button_id):
    """Callback function for WiFi menu button events"""
    global button_queue
    # Map button constants to action strings
    if button_id == b.BTNBACK:
        button_queue.put("BACK")
    elif button_id == b.BTNTICK:
        button_queue.put("SELECT")
    elif button_id == b.BTNUP:
        button_queue.put("UP")
    elif button_id == b.BTNDOWN:
        button_queue.put("DOWN")
    elif button_id == b.BTNHELP:
        button_queue.put("HELP")
    elif button_id == b.BTNPLAY:
        button_queue.put("PLAY")

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

def poll_actions_from_board() -> Optional[str]:
    """Get the next button action from the queue (non-blocking)"""
    global button_queue
    try:
        # Try to get an action from the queue without blocking
        return button_queue.get_nowait()
    except queue.Empty:
        return None
