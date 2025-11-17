#!/usr/bin/env python3
"""
Demo application showcasing the ePaper widget framework.
Uses only the new epaper framework - no legacy dependencies.
"""

import time
import signal
import sys
from . import Manager, ClockWidget, BatteryWidget, TextWidget, BallWidget


class EPaperDemo:
    """Main demo application."""
    
    def __init__(self):
        self.display: Manager = None
        self.running = False
        self.clock = None
        self.battery = None
        self.text = None
        self.ball = None
        
        # Animation state
        self.ball_vx = 2
        self.ball_vy = 2
        self.text_update_counter = 0
        self.start_time = None
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(sig, frame):
            print("\nShutting down...")
            self.running = False
            if self.display:
                self.display.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def initialize_display(self):
        """Initialize the ePaper display."""
        print("Initializing ePaper display...")
        self.display = Manager()
        self.display.init()
        print("Display initialized successfully")
    
    def setup_widgets(self):
        """Create and add widgets to the display."""
        print("Setting up widgets...")
        
        # Clock widget at top-left (24px high)
        self.clock = ClockWidget(0, 0)
        self.display.add_widget(self.clock)
        
        # Battery widget below clock
        self.battery = BatteryWidget(0, 24, level=75)
        self.display.add_widget(self.battery)
        
        # Text widget filling most of the screen
        self.text = TextWidget(0, 40, 128, 200, "ePaper Framework Demo\nInitializing...")
        self.display.add_widget(self.text)
        
        # Bouncing ball widget (added last so it renders on top)
        self.ball = BallWidget(64, 150, radius=8)
        self.display.add_widget(self.ball)
        
        print("Widgets configured")
    
    def update_ball(self):
        """Update ball position with wall bouncing."""
        new_x = self.ball.x + self.ball_vx
        new_y = self.ball.y + self.ball_vy
        
        # Bounce off left/right walls
        if new_x <= 0 or new_x >= 128 - self.ball.width:
            self.ball_vx = -self.ball_vx
            new_x = max(0, min(128 - self.ball.width, new_x))
        
        # Bounce off top/bottom walls
        if new_y <= 0 or new_y >= 296 - self.ball.height:
            self.ball_vy = -self.ball_vy
            new_y = max(0, min(296 - self.ball.height, new_y))
        
        self.ball.set_position(new_x, new_y)
    
    def update_text(self, elapsed_seconds):
        """Update text widget every 5 seconds."""
        if int(elapsed_seconds) % 5 == 0 and int(elapsed_seconds) != self.text_update_counter:
            self.text_update_counter = int(elapsed_seconds)
            
            # Create multi-line text to fill screen
            lines = [
                f"Time: {int(elapsed_seconds)}s",
                f"Counter: {self.text_update_counter}",
                "",
                "A" * 20,
                "B" * 20,
                "C" * 20,
                "D" * 20,
                "E" * 20,
                "",
                f"Ball: ({self.ball.x}, {self.ball.y})",
                f"Speed: ({self.ball_vx}, {self.ball_vy})",
            ]
            self.text.set_text("\n".join(lines))
    
    def update_battery(self, elapsed_seconds):
        """Animate battery level (demo only - not real battery)."""
        # Simulate battery level changing over time (75% ± 10%)
        import math
        level = int(75 + 10 * math.sin(elapsed_seconds / 10))
        self.battery.set_level(level)
    
    def run(self):
        """Main demo loop."""
        self.setup_signal_handlers()
        
        try:
            self.initialize_display()
            self.setup_widgets()
            
            print("Demo started!")
            print("Press Ctrl+C to exit")
            
            self.start_time = time.time()
            self.running = True
            
            while self.running:
                elapsed = time.time() - self.start_time
                
                # Update widgets
                self.update_ball()
                self.update_text(elapsed)
                self.update_battery(elapsed)
                
                # Refresh display
                self.display.update()
                
                # Control frame rate
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"Error in demo: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.display:
                print("Shutting down display...")
                self.display.shutdown()
            print("Demo complete")


def main():
    """Entry point."""
    demo = EPaperDemo()
    demo.run()


if __name__ == "__main__":
    main()

