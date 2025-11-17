#!/usr/bin/env python3
"""
Demo application showcasing the new ePaper widget framework.

Features:
- 24 pixel high clock that updates every second
- Fake battery meter that cycles through levels
- Text that changes every 5 seconds
- Bouncing ball animation
- Screen filled with text
"""

import logging
import random
import signal
import sys
import time

from epaper import DisplayManager
from epaper.widgets import BallWidget, BatteryWidget, ClockWidget, TextWidget

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


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
    
    # Bouncing ball
    ball = BallWidget(x=64, y=150, radius=6)
    
    # Fill screen with text widgets
    # Create multiple text widgets to fill the screen
    text_widgets = []
    font_size = 12
    line_height = 16
    start_y = 30
    lines = [
        "ePaper Demo",
        "Bouncing Ball",
        "Widget Framework",
        "Auto-refresh",
        "Second by second",
        "Filled Screen",
        "Multiple Widgets",
        "Real-time Updates",
        "Region Tracking",
        "Partial Refresh",
        "Full Control",
        "Smooth Animation",
    ]
    
    # Add text widgets to fill available space
    y_pos = start_y
    for i, line in enumerate(lines):
        if y_pos + line_height > display.height - 20:  # Leave some space at bottom
            break
        text_widget = TextWidget(
            x=0,
            y=y_pos,
            width=128,
            height=line_height,
            font_size=font_size,
            text=line
        )
        text_widgets.append(text_widget)
        y_pos += line_height
    
    # Add all widgets to display
    # Add ball last so it renders on top of text
    display.add_widget(clock)
    display.add_widget(battery)
    for text_widget in text_widgets:
        display.add_widget(text_widget)
    display.add_widget(ball)  # Add ball last so it appears on top
    
    # Initial full refresh
    print("Performing initial full refresh...")
    display.update(force_full=True)
    print("Demo started!")
    
    # Ball physics
    ball_x = 64.0
    ball_y = 150.0
    ball_vx = 2.0
    ball_vy = 1.5
    ball_radius = 6
    
    # Battery level simulation
    battery_level = 100
    battery_direction = -1  # Decreasing
    
    # Text update counter
    text_update_counter = 0
    
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
            # Update ball position
            ball_x += ball_vx
            ball_y += ball_vy
            
            # Bounce off walls
            if ball_x - ball_radius <= 0 or ball_x + ball_radius >= display.width:
                ball_vx = -ball_vx
                ball_x = max(ball_radius, min(display.width - ball_radius, ball_x))
            
            if ball_y - ball_radius <= 0 or ball_y + ball_radius >= display.height:
                ball_vy = -ball_vy
                ball_y = max(ball_radius, min(display.height - ball_radius, ball_y))
            
            # Update ball widget position
            ball.set_position(int(ball_x), int(ball_y))
            
            # Update battery level (cycle 0-100)
            battery_level += battery_direction * 2
            if battery_level <= 0:
                battery_level = 0
                battery_direction = 1
            elif battery_level >= 100:
                battery_level = 100
                battery_direction = -1
            battery.set_level(battery_level)
            
            # Update text widgets occasionally (every 10 frames)
            text_update_counter += 1
            if text_update_counter >= 10 and text_widgets:
                # Randomly update one text widget
                random_text = random.choice(text_widgets)
                new_texts = [
                    "Updated!",
                    "Changed!",
                    "New Text",
                    "Refresh!",
                    "Dynamic!",
                ]
                random_text.set_text(random.choice(new_texts))
                text_update_counter = 0
            
            # Update display (framework handles dirty region detection)
            display.update()
            
            # Sleep for shorter interval for smoother animation (100ms)
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down display...")
        try:
            display.shutdown()
        except Exception as e:
            print(f"Error during shutdown: {e}")
        print("Demo complete")


if __name__ == "__main__":
    main()
