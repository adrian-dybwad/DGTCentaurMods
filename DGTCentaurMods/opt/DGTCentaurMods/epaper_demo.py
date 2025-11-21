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
from epaper import (Manager, CheckerboardWidget, ClockWidget, BatteryWidget, 
                    TextWidget, BallWidget, ChessBoardWidget, GameAnalysisWidget)


class EPaperDemo:
    """Main demo application."""
    
    def __init__(self):
        self.display: Manager = None
        self.running = False
        self.checkerboard = None
        self.clock = None
        self.battery = None
        self.text = None
        self.ball = None
        self.chess_board = None
        self.game_analysis = None
        
        # Ball physics
        self.ball_x = 64  # Start in middle
        self.ball_y = 150
        self.ball_vx = 2  # Velocity in pixels per update
        self.ball_vy = 2
        
        # Chess FEN positions to cycle through
        self.fen_positions = [
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",  # Starting position
            "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",  # Italian Game
            "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R b KQkq - 0 3",  # Ruy Lopez
            "rnbqkb1r/pppp1ppp/5n2/4p3/2PP4/8/PP2PPPP/RNBQKBNR w KQkq e6 0 3",  # Queen's Gambit
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",  # King's Pawn
            "rnbqkb1r/pppppppp/5n2/8/3PP3/8/PPP2PPP/RNBQKBNR b KQkq d3 0 2",  # French Defense
        ]
        self.fen_index = 0
        self.last_fen_update = 0
    
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
        
        # Display is 128x296 pixels
        
        # Clock widget at top (24px high)
        self.clock = ClockWidget(0, 0)
        self.display.add_widget(self.clock)
        
        # Battery widget at top right (32x16)
        self.battery = BatteryWidget(96, 0, level=85)
        self.display.add_widget(self.battery)
        
        # Text widget below clock (128x16)
        self.text = TextWidget(0, 24, 128, 16, text="ePaper Demo")
        self.display.add_widget(self.text)
        
        # Chess board widget (128x128) starting at y=40
        self.chess_board = ChessBoardWidget(0, 40, self.fen_positions[0])
        self.display.add_widget(self.chess_board)
        
        # Game analysis widget below chess board (128x80) at y=168
        self.game_analysis = GameAnalysisWidget(0, 168, 128, 80)
        self.game_analysis.set_score(0.5, "0.5")
        self.game_analysis.set_turn("white")
        self.display.add_widget(self.game_analysis)
        
        # Checkerboard widget at bottom (128x32) at y=248
        self.checkerboard = CheckerboardWidget(0, 248, 128, 32, square_size=4)
        self.display.add_widget(self.checkerboard)
        
        # Ball widget (16x16) - will be positioned dynamically
        self.ball = BallWidget(self.ball_x, self.ball_y, radius=8)
        self.display.add_widget(self.ball)
        
        print("Widgets configured (all widgets added)")
    
    def run(self):
        """Main demo loop."""
        self.setup_signal_handlers()
        
        try:
            self.initialize_display()
            self.setup_widgets()
            
            # Clear screen with initial full refresh
            # print("Clearing screen...")
            # future = self.display._scheduler.submit(full=True)
            # future.result(timeout=5.0)
            # print("Screen cleared")
            
            # Render checkerboard and update display using full refresh
            # print("Rendering checkerboard pattern...")
            # future = self.display.update(full=True)
            # future.result(timeout=5.0)
            # print("Update complete (full refresh) 1")
            # time.sleep(1.0)
            
            print("Display active. Press Ctrl+C to exit")
            
            # Set running flag and keep running to update widgets
            self.running = True
            last_update = time.time()
            self.last_fen_update = time.time()
            
            while self.running:
                current_time = time.time()
                
                # Update ball position every frame (bounce around screen)
                self._update_ball()
                
                # Update chess board FEN every 5 seconds
                if current_time - self.last_fen_update >= 5.0:
                    self._update_chess_fen()
                    self.last_fen_update = current_time
                
                # Update display every 0.5 seconds (or on demand)
                if current_time - last_update >= 0.5:
                    future = self.display.update(full=False)
                    future.result(timeout=5.0)
                    last_update = current_time
                
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
    
    def _update_ball(self):
        """Update ball position with bouncing physics."""
        # Display bounds: 128x296
        # Ball is 16x16 (radius 8, so diameter 16)
        ball_size = 16
        
        # Update position
        self.ball_x += self.ball_vx
        self.ball_y += self.ball_vy
        
        # Bounce off left/right walls
        if self.ball_x <= 0:
            self.ball_x = 0
            self.ball_vx = -self.ball_vx
        elif self.ball_x >= 128 - ball_size:
            self.ball_x = 128 - ball_size
            self.ball_vx = -self.ball_vx
        
        # Bounce off top/bottom walls
        if self.ball_y <= 0:
            self.ball_y = 0
            self.ball_vy = -self.ball_vy
        elif self.ball_y >= 296 - ball_size:
            self.ball_y = 296 - ball_size
            self.ball_vy = -self.ball_vy
        
        # Update ball widget position
        self.ball.set_position(int(self.ball_x), int(self.ball_y))
    
    def _update_chess_fen(self):
        """Update chess board with next FEN position."""
        self.fen_index = (self.fen_index + 1) % len(self.fen_positions)
        self.chess_board.fen = self.fen_positions[self.fen_index]
        # Force re-render
        self.chess_board._last_rendered = None
        print(f"Updated chess board to FEN position {self.fen_index + 1}/{len(self.fen_positions)}")


def main():
    """Entry point."""
    demo = EPaperDemo()
    demo.run()


if __name__ == "__main__":
    main()

