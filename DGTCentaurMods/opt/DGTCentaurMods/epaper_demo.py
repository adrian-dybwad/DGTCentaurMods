#!/usr/bin/env python3
"""
Demo application for ePaper widget framework.
"""

import time
import signal
from epaper import DisplayManager, ClockWidget, BatteryWidget, TextWidget, BallWidget


display = None


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    global display
    if display:
        print("\nShutting down...")
        display.shutdown()
    exit(0)


def main():
    """Main demo function."""
    global display
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    display = DisplayManager()
    
    try:
        print("Initializing display...")
        display.init()
        print("Display initialized")
        
        # Add widgets
        clock = ClockWidget(0, 0)
        battery = BatteryWidget(0, 16, level=75)
        text = TextWidget(0, 32, 128, 200, "Hello World")
        ball = BallWidget(64, 150, radius=8)
        
        display.add_widget(clock)
        display.add_widget(battery)
        display.add_widget(text)
        display.add_widget(ball)  # Add ball last so it renders on top
        
        print("Demo started!")
        
        # Animation variables
        ball_vx = 2
        ball_vy = 2
        text_counter = 0
        start_time = time.time()
        
        while True:
            # Update ball position
            new_x = ball.x + ball_vx
            new_y = ball.y + ball_vy
            
            # Bounce off walls
            if new_x <= 0 or new_x >= 128 - ball.width:
                ball_vx = -ball_vx
                new_x = max(0, min(128 - ball.width, new_x))
            if new_y <= 0 or new_y >= 296 - ball.height:
                ball_vy = -ball_vy
                new_y = max(0, min(296 - ball.height, new_y))
            
            ball.set_position(new_x, new_y)
            
            # Change text every 5 seconds
            elapsed = time.time() - start_time
            if int(elapsed) % 5 == 0 and int(elapsed) != text_counter:
                text_counter = int(elapsed)
                text.set_text(f"Time: {int(elapsed)}s\nCounter: {text_counter}\n" + 
                            "A" * 20 + "\n" + "B" * 20 + "\n" + "C" * 20)
            
            # Update display
            display.update()
            
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        pass
    finally:
        if display:
            print("Shutting down display...")
            display.shutdown()
        print("Demo complete")


if __name__ == "__main__":
    main()
