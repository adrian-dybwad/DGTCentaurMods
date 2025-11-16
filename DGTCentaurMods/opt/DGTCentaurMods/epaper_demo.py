#!/usr/bin/env python3
"""
Demo application showcasing the new ePaper widget framework.

Features:
- 24 pixel high clock that updates every second
- Fake battery meter that cycles through levels
- Text that changes every 5 seconds
"""

import signal
import sys
import time

from epaper import DisplayManager
from epaper.widgets import BatteryWidget, ClockWidget, TextWidget


def main():
    """Run the ePaper demo."""
    # Create display manager
    display = DisplayManager()
    
    # Initialize display
    print("Initializing display...")
    display.init()
    print("Display initialized")
    
    # Create widgets
    # Clock: 24 pixels high at top left
    clock = ClockWidget(x=0, y=0, height=24, font_size=20)
    
    # Battery: top right
    battery = BatteryWidget(x=98, y=6, width=30, height=12)
    
    # Text: below clock, changes every 5 seconds
    text = TextWidget(x=0, y=30, width=128, height=40, font_size=18, text="Starting demo...")
    
    # Add widgets to display
    display.add_widget(clock)
    display.add_widget(battery)
    display.add_widget(text)
    
    # Initial full refresh
    print("Performing initial full refresh...")
    display.update(force_full=True)
    print("Demo started!")
    
    # Text messages that cycle every 5 seconds
    text_messages = [
        "Hello World!",
        "ePaper Demo",
        "Widget Framework",
        "Auto-refresh",
        "Second by second",
    ]
    text_index = 0
    last_text_change = time.time()
    
    # Battery level simulation
    battery_level = 100
    battery_direction = -1  # Decreasing
    
    # Signal handler for graceful shutdown
    def signal_handler(sig, frame):
        print("\nShutting down...")
        display.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Main loop
    try:
        while True:
            current_time = time.time()
            
            # Update text every 5 seconds
            if current_time - last_text_change >= 5.0:
                text.set_text(text_messages[text_index])
                text_index = (text_index + 1) % len(text_messages)
                last_text_change = current_time
                print(f"Text changed to: {text_messages[text_index - 1]}")
            
            # Update battery level (cycle 0-100)
            battery_level += battery_direction * 2
            if battery_level <= 0:
                battery_level = 0
                battery_direction = 1
            elif battery_level >= 100:
                battery_level = 100
                battery_direction = -1
            battery.set_level(battery_level)
            
            # Update display (framework handles dirty region detection)
            display.update()
            
            # Sleep for 1 second (clock updates every second)
            time.sleep(1.0)
    
    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down display...")
        display.shutdown()
        print("Demo complete")


if __name__ == "__main__":
    main()
