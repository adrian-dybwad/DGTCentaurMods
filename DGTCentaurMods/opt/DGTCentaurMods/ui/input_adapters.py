# DGTCentaurMods/ui/input_adapters.py
from typing import Optional
import time
import logging
import threading
import queue
from DGTCentaurMods.board import board as b

# Global queue for button events
button_queue = queue.Queue()
current_callback = None

def button_event_callback(button_id):
    """Callback function for button events from the main board system"""
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

def start_event_subscription():
    """Start subscribing to board events for button detection"""
    global current_callback
    if current_callback is None:
        current_callback = button_event_callback
        # Subscribe to events with a long timeout
        b.subscribeEvents(button_event_callback, None, timeout=3600)  # 1 hour timeout
        logging.debug("Started event subscription for button detection")

def stop_event_subscription():
    """Stop the event subscription"""
    global current_callback
    if current_callback is not None:
        # Pause events to stop the subscription
        b.pauseEvents()
        current_callback = None
        logging.debug("Stopped event subscription for button detection")

def poll_actions_from_board() -> Optional[str]:
    """Get the next button action from the queue (non-blocking)"""
    global button_queue
    try:
        # Try to get an action from the queue without blocking
        return button_queue.get_nowait()
    except queue.Empty:
        return None
