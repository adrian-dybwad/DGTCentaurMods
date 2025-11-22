#!/usr/bin/env python3
"""
Demo application showcasing the ePaper widget framework.
Demonstrates all available widgets including greyscale backgrounds.
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
from epaper import (Manager, StatusBarWidget, TextWidget, BallWidget, 
                    ChessBoardWidget, GameAnalysisWidget, CheckerboardWidget,
                    WelcomeWidget, GameOverWidget, MenuArrowWidget)


class EPaperDemo:
    """Main demo application showcasing all widgets."""
    
    def __init__(self):
        self.display: Manager = None
        self.running = False
        
        # Widget references
        self.status_bar = None
        self.text_widgets = []  # Multiple text widgets with different backgrounds
        self.ball = None
        self.chess_board = None
        self.game_analysis = None
        self.checkerboard = None
        self.welcome = None
        self.game_over = None
        self.menu_arrow = None
        
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
        
        # Demo mode cycling
        self.demo_mode = 0  # 0=all widgets, 1=greyscale demo, 2=welcome, 3=game_over, 4=menu_arrow, 5=wrapped_text
        self.last_mode_change = 0
        self.mode_duration = 10.0  # Show each mode for 10 seconds
    
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
    
    def setup_widgets_all(self):
        """Create and add all widgets for comprehensive demo."""
        print("Setting up all widgets...")
        
        # Display is 128x296 pixels
        
        # Status bar at top (16px high) - replaces separate clock and battery
        self.status_bar = StatusBarWidget(0, 0)
        self.display.add_widget(self.status_bar)
        # Widget triggers its own update when ready
        self.status_bar.request_update(full=True)
        
        # Text widgets demonstrating greyscale backgrounds (0-5)
        # Each shows a different background dithering level
        text_y = 20
        text_height = 16
        for bg_level in range(6):  # 0-5
            text_widget = TextWidget(
                0, text_y + (bg_level * text_height), 
                128, text_height,
                text=f"Background {bg_level}",
                background=bg_level,
                font_size=12
            )
            self.text_widgets.append(text_widget)
            self.display.add_widget(text_widget)
            # Widget triggers its own update when ready
            text_widget.request_update(full=False)
        
        # Chess board widget (128x128) starting at y=116
        self.chess_board = ChessBoardWidget(0, 116, self.fen_positions[0])
        self.display.add_widget(self.chess_board)
        # Widget triggers its own update when ready
        self.chess_board.request_update(full=False)
        
        # Game analysis widget below chess board (128x80) at y=244
        self.game_analysis = GameAnalysisWidget(0, 244, 128, 80)
        self.game_analysis.set_score(0.5, "0.5")
        self.game_analysis.set_turn("white")
        self.display.add_widget(self.game_analysis)
        # Widget triggers its own update when ready
        self.game_analysis.request_update(full=False)
        
        # Checkerboard widget at bottom (128x32) at y=264
        self.checkerboard = CheckerboardWidget(0, 264, 128, 32, square_size=4)
        self.display.add_widget(self.checkerboard)
        # Widget triggers its own update when ready
        self.checkerboard.request_update(full=False)
        
        # Ball widget (16x16) - will be positioned dynamically
        self.ball = BallWidget(self.ball_x, self.ball_y, radius=8)
        self.display.add_widget(self.ball)
        # Widget triggers its own update when ready
        self.ball.request_update(full=False)
        
        print("All widgets configured and added")
    
    def setup_widgets_greyscale_demo(self):
        """Setup widgets to demonstrate greyscale backgrounds."""
        print("Setting up greyscale background demo...")
        
        # Clear all widgets
        self.display._widgets.clear()
        
        # Status bar at top
        self.status_bar = StatusBarWidget(0, 0)
        self.display.add_widget(self.status_bar)
        self.status_bar.request_update(full=True)
        
        # Large text widgets showing each greyscale level
        demo_texts = [
            ("No background (0)", 0),
            ("Very light (1)", 1),
            ("Light (2)", 2),
            ("Medium (3)", 3),
            ("Heavy (4)", 4),
            ("Solid black (5)", 5),
        ]
        
        y_start = 20
        widget_height = 40
        for idx, (text, bg_level) in enumerate(demo_texts):
            text_widget = TextWidget(
                0, y_start + (idx * widget_height),
                128, widget_height,
                text=text,
                background=bg_level,
                font_size=18
            )
            self.text_widgets.append(text_widget)
            self.display.add_widget(text_widget)
            text_widget.request_update(full=False)
        
        print("Greyscale demo widgets configured")
    
    def setup_widgets_welcome(self):
        """Setup welcome widget demo."""
        print("Setting up welcome widget demo...")
        
        # Clear all widgets
        self.display._widgets.clear()
        
        # Welcome widget fills entire screen
        self.welcome = WelcomeWidget(status_text="DEMO")
        self.display.add_widget(self.welcome)
        self.welcome.request_update(full=True)
        
        print("Welcome widget configured")
    
    def setup_widgets_game_over(self):
        """Setup game over widget demo."""
        print("Setting up game over widget demo...")
        
        # Clear all widgets
        self.display._widgets.clear()
        
        # Status bar at top
        self.status_bar = StatusBarWidget(0, 0)
        self.display.add_widget(self.status_bar)
        if self.status_bar._update_callback:
            self.status_bar.request_update(full=False)
        
        # Game over widget
        self.game_over = GameOverWidget(0, 16, 128, 280)
        self.game_over.set_result("1-0")
        # Create sample score history
        score_history = [0.0, 0.5, 1.0, 0.5, -0.5, -1.0, -0.5, 0.0, 0.5, 1.5, 2.0, 1.5, 1.0, 0.5, 0.0]
        self.game_over.set_score_history(score_history)
        self.display.add_widget(self.game_over)
        self.game_over.request_update(full=False)
        
        print("Game over widget configured")
    
    def setup_widgets_menu_arrow(self):
        """Setup menu arrow widget demo."""
        print("Setting up menu arrow widget demo...")
        
        # Clear all widgets
        self.display._widgets.clear()
        
        # Status bar at top
        self.status_bar = StatusBarWidget(0, 0)
        self.display.add_widget(self.status_bar)
        if self.status_bar._update_callback:
            self.status_bar.request_update(full=False)
        
        # Menu arrow widget - demonstrates menu navigation
        # Arrow widget for 5 menu items, each 16px high, starting at y=20
        menu_item_height = 16
        num_items = 5
        arrow_width = 20  # Width of arrow column
        arrow_height = num_items * menu_item_height
        self.menu_arrow = MenuArrowWidget(0, 20, arrow_width, arrow_height, menu_item_height, num_items)
        self.display.add_widget(self.menu_arrow)
        self.menu_arrow.request_update(full=False)
        
        # Add text widgets for menu items
        menu_items = ["Item 1", "Item 2", "Item 3", "Item 4", "Item 5"]
        for idx, item_text in enumerate(menu_items):
            text_widget = TextWidget(
                20, 20 + (idx * menu_item_height),
                108, menu_item_height,
                text=item_text,
                background=0,
                font_size=14
            )
            self.text_widgets.append(text_widget)
            self.display.add_widget(text_widget)
            text_widget.request_update(full=False)
        
        print("Menu arrow widget configured")
    
    def run(self):
        """Main demo loop."""
        self.setup_signal_handlers()
        
        try:
            self.initialize_display()
            self.setup_widgets_all()
            
            print("Display active. Demo will cycle through different modes.")
            print("Press Ctrl+C to exit")
            
            # Set running flag and keep running to update widgets
            self.running = True
            last_update = time.time()
            self.last_fen_update = time.time()
            self.last_mode_change = time.time()
            
            while self.running:
                current_time = time.time()
                
                # Cycle through demo modes
                if current_time - self.last_mode_change >= self.mode_duration:
                    self._cycle_demo_mode()
                    self.last_mode_change = current_time
                
                # Update ball position every frame (only in all-widgets mode)
                if self.demo_mode == 0 and self.ball:
                    self._update_ball()
                
                # Update chess board FEN every 5 seconds (only in all-widgets mode)
                if self.demo_mode == 0 and current_time - self.last_fen_update >= 5.0:
                    self._update_chess_fen()
                    self.last_fen_update = current_time
                
                # Update game analysis scores (only in all-widgets mode)
                if self.demo_mode == 0 and self.game_analysis:
                    self._update_game_analysis()
                
                # Update menu arrow selection (only in menu-arrow mode)
                if self.demo_mode == 4 and self.menu_arrow:
                    # Simulate menu navigation
                    pass  # Menu arrow handles its own updates via key events
                
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
    
    def setup_widgets_wrapped_text(self):
        """Setup wrapped text widget demo."""
        print("Setting up wrapped text demo...")
        
        # Clear all widgets
        self.display._widgets.clear()
        
        # Status bar at top
        self.status_bar = StatusBarWidget(0, 0)
        self.display.add_widget(self.status_bar)
        if self.status_bar._update_callback:
            self.status_bar.request_update(full=False)
        
        # Long text to demonstrate wrapping
        long_text = (
            "This is a demonstration of the text wrapping feature in the TextWidget. "
            "When wrapText is enabled, the widget automatically wraps text to fit within "
            "its specified width and height. The text is broken into multiple lines "
            "based on word boundaries and the available space. This is useful for "
            "displaying longer descriptions, instructions, or other multi-line content "
            "on the e-paper display."
        )
        
        # Create wrapped text widget with medium background dithering
        wrapped_widget = TextWidget(
            5, 20,  # Position with small margin
            118, 260,  # Width and height to fill most of screen below status bar
            text=long_text,
            background=2,  # Light dither background
            font_size=14,
            wrapText=True
        )
        self.text_widgets.append(wrapped_widget)
        self.display.add_widget(wrapped_widget)
        wrapped_widget.request_update(full=False)
        
        print("Wrapped text widget configured")
    
    def _cycle_demo_mode(self):
        """Cycle through different demo modes."""
        self.demo_mode = (self.demo_mode + 1) % 6
        
        if self.demo_mode == 0:
            print("Mode: All widgets")
            self.setup_widgets_all()
        elif self.demo_mode == 1:
            print("Mode: Greyscale backgrounds")
            self.setup_widgets_greyscale_demo()
        elif self.demo_mode == 2:
            print("Mode: Welcome widget")
            self.setup_widgets_welcome()
        elif self.demo_mode == 3:
            print("Mode: Game over widget")
            self.setup_widgets_game_over()
        elif self.demo_mode == 4:
            print("Mode: Menu arrow widget")
            self.setup_widgets_menu_arrow()
        elif self.demo_mode == 5:
            print("Mode: Wrapped text widget")
            self.setup_widgets_wrapped_text()
    
    def _update_ball(self):
        """Update ball position with bouncing physics."""
        if not self.ball:
            return
            
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
        
        # Update ball widget position (widget triggers its own update)
        self.ball.set_position(int(self.ball_x), int(self.ball_y))
    
    def _update_chess_fen(self):
        """Update chess board with next FEN position."""
        if not self.chess_board:
            return
            
        self.fen_index = (self.fen_index + 1) % len(self.fen_positions)
        # Widget triggers its own update when FEN changes
        self.chess_board.set_fen(self.fen_positions[self.fen_index])
        print(f"Updated chess board to FEN position {self.fen_index + 1}/{len(self.fen_positions)}")
    
    def _update_game_analysis(self):
        """Update game analysis widget with changing scores."""
        if not self.game_analysis:
            return
        
        # Simulate score changes
        import random
        score = random.uniform(-2.0, 2.0)
        score_text = f"{score:+.1f}"
        turn = "white" if random.random() > 0.5 else "black"
        
        # Widgets trigger their own updates
        self.game_analysis.set_score(score, score_text)
        self.game_analysis.set_turn(turn)
        self.game_analysis.add_score_to_history(score)


def main():
    """Entry point."""
    demo = EPaperDemo()
    demo.run()


if __name__ == "__main__":
    main()
