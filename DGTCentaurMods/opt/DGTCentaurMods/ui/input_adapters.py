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
original_callback = None
original_field_callback = None

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

def start_wifi_event_subscription():
    """Start subscribing to board events for WiFi configuration"""
    global current_callback, original_callback, original_field_callback
    
    if current_callback is None:
        # Store the original callback (main menu's callback)
        original_callback = getattr(b.subscribeEvents, '_original_keycallback', None)
        original_field_callback = getattr(b.subscribeEvents, '_original_fieldcallback', None)
        
        # Set our callback as the current one
        current_callback = button_event_callback
        
        # Subscribe to events with a long timeout
        b.subscribeEvents(button_event_callback, None, timeout=3600)  # 1 hour timeout
        logging.debug("Started WiFi event subscription")
        return True
    return False

def stop_wifi_event_subscription():
    """Stop the WiFi event subscription and restore original menu callback"""
    global current_callback, original_callback, original_field_callback
    
    if current_callback is not None:
        # Pause events to stop our subscription
        b.pauseEvents()
        
        # Restore the original menu callback if it exists
        if original_callback is not None:
            b.subscribeEvents(original_callback, original_field_callback, timeout=900)
            logging.debug("Restored original menu event subscription")
        
        current_callback = None
        original_callback = None
        original_field_callback = None
        logging.debug("Stopped WiFi event subscription")

def poll_actions_from_board() -> Optional[str]:
    """Get the next button action from the queue (non-blocking)"""
    global button_queue
    try:
        # Try to get an action from the queue without blocking
        return button_queue.get_nowait()
    except queue.Empty:
        return None

# Alternative approach: Direct polling without hijacking the main menu
def poll_actions_direct() -> Optional[str]:
    """Direct polling approach that doesn't interfere with main menu events"""
    try:
        # Send key event request directly to the board
        b.sendPacket(b'\x94', b'')
        resp = b._ser_read(1000)
        resp = bytearray(resp)
        
        # Check for button presses using the same logic as the main events thread
        if len(resp) >= 6:
            addr1 = b.addr1
            addr2 = b.addr2
            
            # Check for different button presses
            if (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0510000000007d17"):
                return "SELECT"  # TICK
            elif (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0508000000007d3c"):
                return "UP"  # UP
            elif (resp.hex()[:-2] == "b10010" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a05020000000061"):
                return "DOWN"  # DOWN
            elif (resp.hex()[:-2] == "b10011" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0510000000007d47"):
                return "BACK"  # BACK
            elif (resp.hex()[:-2] == "b10010" + "{:02x}".format(addr1) + "{:02x}".format(addr2) + "00140a0540000000006d"):
                return "HELP"  # HELP
                
    except Exception as e:
        logging.debug(f"Error in direct polling: {e}")
    
    return None
