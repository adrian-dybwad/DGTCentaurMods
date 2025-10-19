# DGTCentaurMods/ui/input_adapters.py
from typing import Optional
import time
import logging
import threading
import queue
from DGTCentaurMods.board import board as b

# Text input event system
text_input_event = threading.Event()
text_input_event_type = None  # 'button' or 'field'
text_input_button = 0
text_input_field = -1

def text_input_button_callback(button_id):
    """Callback for text input button events"""
    global text_input_button, text_input_event, text_input_event_type
    
    print(f"DEBUG: text_input_button_callback called with button_id: {button_id}")
    print(f"DEBUG: text_input_button: {text_input_button}")
    print(f"DEBUG: text_input_event_type: {text_input_event_type}")
    print(f"DEBUG: text_input_event: {text_input_event}")
    print(f"DEBUG: text_input_event.set(): {text_input_event.set()}")
    print(f"DEBUG: logging.debug(f\"Text input button callback: {button_id}\")")
    print(f"DEBUG: b.subscribeEvents(text_input_button_callback, text_input_field_callback, timeout=3600)")
    print(f"DEBUG: logging.debug(\"Started text input event subscription\")")

    text_input_button = button_id
    text_input_event_type = 'button'
    text_input_event.set()
    logging.debug(f"Text input button callback: {button_id}")

def text_input_field_callback(field):
    """Callback for text input field events"""
    global text_input_field, text_input_event, text_input_event_type

    print(f"DEBUG: text_input_field_callback called with field: {field}")
    print(f"DEBUG: text_input_field: {text_input_field}")
    print(f"DEBUG: text_input_event_type: {text_input_event_type}")
    print(f"DEBUG: text_input_event: {text_input_event}")
    print(f"DEBUG: text_input_event.set(): {text_input_event.set()}")
    print(f"DEBUG: logging.debug(f\"Text input field callback: {field}\")")
    print(f"DEBUG: b.subscribeEvents(text_input_button_callback, text_input_field_callback, timeout=3600)")
    print(f"DEBUG: logging.debug(\"Started text input event subscription\")")
    text_input_field = field
    text_input_event_type = 'field'
    text_input_event.set()
    logging.debug(f"Text input field callback: {field}")

def start_text_input_subscription():
    """Start text input event subscription"""
    try:
        b.subscribeEvents(text_input_button_callback, text_input_field_callback, timeout=3600)
        logging.debug("Started text input event subscription")
        return True
    except Exception as e:
        logging.error(f"Error starting text input subscription: {e}")
        return False

def stop_text_input_subscription():
    """Stop text input event subscription"""
    try:
        b.unsubscribeEvents(text_input_button_callback, text_input_field_callback)
        logging.debug("Stopped text input event subscription")
        return True
    except Exception as e:
        logging.error(f"Error stopping text input subscription: {e}")
        return False
