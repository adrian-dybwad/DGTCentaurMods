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
from epaper import Manager, ClockWidget, BatteryWidget, ChessBoardWidget, GameAnalysisWidget


class EPaperDemo:
    """Main demo application."""
    
    def __init__(self):
        self.display: Manager = None
        self.running = False
        self.clock = None
        self.battery = None
        self.chess_board = None
        self.analysis = None
        
        # Animation state
        self.analysis_update_counter = 0
        self.start_time = None
        self.current_fen_index = 0
        self.fen_positions = [
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
            "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
        ]
    
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
        
        # Chess board widget only (128x128) - testing in isolation
        self.chess_board = ChessBoardWidget(0, 0, self.fen_positions[0])
        self.display.add_widget(self.chess_board)
        
        # Disabled other widgets for isolation testing
        # self.clock = ClockWidget(0, 0)
        # self.display.add_widget(self.clock)
        # self.battery = BatteryWidget(0, 24, level=75)
        # self.display.add_widget(self.battery)
        # self.analysis = GameAnalysisWidget(0, 168)
        # self.display.add_widget(self.analysis)
        
        print("Widgets configured (chess board only)")
    
    def update_chess_board(self, elapsed_seconds):
        """Update chess board position every 3 seconds."""
        if int(elapsed_seconds) % 3 == 0:
            fen_index = (int(elapsed_seconds) // 3) % len(self.fen_positions)
            if fen_index != self.current_fen_index:
                self.current_fen_index = fen_index
                self.chess_board.set_fen(self.fen_positions[fen_index])
    
    def update_analysis(self, elapsed_seconds):
        """Update analysis widget with simulated evaluation."""
        import math
        
        # Only update analysis every 0.5 seconds to reduce refresh frequency
        if int(elapsed_seconds * 2) != getattr(self, '_last_analysis_update', -1):
            self._last_analysis_update = int(elapsed_seconds * 2)
            
            # Simulate evaluation score oscillating
            base_score = 0.5 * math.sin(elapsed_seconds / 5.0) * 5.0
            self.analysis.set_score(base_score)
            self.analysis.add_score_to_history(base_score)
            
            # Alternate turn every 2 seconds
            turn = "white" if (int(elapsed_seconds) // 2) % 2 == 0 else "black"
            self.analysis.set_turn(turn)
    
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
            
            # Clear screen with initial full refresh
            print("Clearing screen...")
            future = self.display._scheduler.submit(full=True)
            future.result(timeout=5.0)
            print("Screen cleared")
            
            # Incrementally construct board 4 squares at a time
            print("Constructing board 4 squares at a time...")
            print("Press Ctrl+C to exit")
            
            self.running = True
            
            # Start with 0 squares, add 4 every 3 seconds
            for square_count in range(0, 65, 4):  # 0, 4, 8, 12, ..., 64
                if not self.running:
                    break
                
                # Set max square index (cap at 64)
                max_squares = min(square_count, 64)
                self.chess_board.set_max_square_index(max_squares)
                
                # Render and update display (uses partial refresh)
                self.display.update()
                
                if square_count > 0:
                    start_rank = (square_count - 4) // 8
                    start_file = (square_count - 4) % 8
                    end_rank = (max_squares - 1) // 8
                    end_file = (max_squares - 1) % 8
                    print(f"Added squares {square_count-3}-{max_squares}/64: ({start_rank},{start_file}) to ({end_rank},{end_file})")
                
                # Wait 3 seconds before adding next batch
                if max_squares < 64:
                    time.sleep(3.0)
            
            print("Board construction complete!")
            
            # Second full refresh at the end to ensure display completes
            print("Performing final full refresh...")
            self.display.update()
            future = self.display._scheduler.submit(full=True)
            future.result(timeout=5.0)
            print("Final refresh complete")
            
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

