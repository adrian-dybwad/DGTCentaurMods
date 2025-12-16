"""
Board initialization callback holder.

This module holds a callback function that can be set before importing the board module.
The board module uses this callback to report initialization status during retries.
"""

# Callback for board initialization status updates
# Set this BEFORE importing the board module
init_status_callback = None


def set_callback(callback):
    """Set the initialization status callback.
    
    Args:
        callback: Function that takes a string message argument
    """
    global init_status_callback
    init_status_callback = callback


def notify(message: str):
    """Notify the callback with a status message.
    
    Args:
        message: Status message to display
    """
    if init_status_callback is not None:
        try:
            init_status_callback(message)
        except Exception:
            pass  # Ignore callback errors
