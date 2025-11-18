#!/usr/bin/env python3
"""
Demo application showcasing the ePaper widget framework.
Uses only the new epaper framework - no legacy dependencies.
"""

import time
import signal
import sys
import os
import logging

# Configure logging to show INFO level and above
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Add current directory to path to import epaper package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from epaper import Manager, CheckerboardWidget


class EPaperDemo:
    """Main demo application."""
    
    def __init__(self):
        self.display: Manager = None
        self.running = False
        self.checkerboard = None
    
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
        
        # Checkerboard widget covering full frame (128x296)
        self.checkerboard = CheckerboardWidget(0, 0, 128, 296)
        self.display.add_widget(self.checkerboard)
        
        print("Widgets configured (checkerboard only)")
    
    def run(self):
        """Main demo loop."""
        self.setup_signal_handlers()
        
        try:
            self.initialize_display()
            self.setup_widgets()
            
            # Clear screen with initial full refresh
            print("Clearing screen...")
            future = self.display._scheduler.submit(full=True)
            future.result(timeout=5.0)
            print("Screen cleared")
            
            # Render checkerboard and update display
            print("Rendering checkerboard pattern...")
            future = self.display.update()
            future.result(timeout=5.0)
            print("Update complete")
            
            # Final full refresh to ensure display completes
            print("Performing final full refresh...")
            future = self.display._scheduler.submit(full=True)
            future.result(timeout=5.0)
            print("Final refresh complete")
            
            print("Checkerboard displayed. Press Ctrl+C to exit")
            
            # Keep running to maintain display
            while self.running:
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

