# UCI Engine Handler
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

"""
UCI engine handler that reacts to game manager events, decides when to call engines,
handles UI/display updates, and manages engine lifecycle.

This module focuses solely on engine interaction and UI updates, delegating
all game state management to the GameManager.
"""

import chess
import chess.engine
import threading
import time
import sys
import pathlib
import os
import signal
from typing import Optional
from DGTCentaurMods.games.manager import GameManager, EVENT_NEW_GAME, EVENT_WHITE_TURN, EVENT_BLACK_TURN, EVENT_GAME_OVER, EVENT_MOVE_MADE, EVENT_PROMOTION_NEEDED
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log


class UCIHandler:
    """
    Handles UCI engine interaction, UI updates, and engine lifecycle.
    
    Reacts to events from GameManager and decides when to call engines.
    Manages display updates and engine process lifecycle.
    """
    
    def __init__(self, engine_path: str, player_color: str = "white", engine_options: Optional[dict] = None):
        """
        Initialize UCI handler.
        
        Args:
            engine_path: Path to UCI engine executable
            player_color: "white" or "black" - which color the human plays
            engine_options: Optional dict of UCI options to configure engine
        """
        self._engine_path = engine_path
        self._player_color = player_color.lower()
        self._engine_options = engine_options or {}
        
        # Determine which side the engine plays
        self._engine_plays_white = (self._player_color == "black")
        self._engine_plays_black = (self._player_color == "white")
        
        # Engine instance
        self._engine: Optional[chess.engine.SimpleEngine] = None
        
        # Game manager
        self._manager: Optional[GameManager] = None
        
        # Control flags
        self._kill = False
        self._cleaned_up = False
        
        # Current turn tracking
        self._current_turn_is_white = True
        
    def start(self):
        """Start the UCI handler and initialize engine."""
        log.info(f"[UCIHandler] Starting with engine: {self._engine_path}, player: {self._player_color}")
        
        # Initialize engine
        try:
            self._engine = chess.engine.SimpleEngine.popen_uci(self._engine_path)
            if self._engine_options:
                log.info(f"[UCIHandler] Configuring engine with options: {self._engine_options}")
                self._engine.configure(self._engine_options)
        except Exception as e:
            log.error(f"[UCIHandler] Failed to start engine: {e}")
            raise
            
        # Initialize game manager
        self._manager = GameManager()
        self._manager.subscribe(
            event_callback=self._on_event,
            move_callback=self._on_move,
            key_callback=self._on_key
        )
        
        # Initialize display
        epaper.initEpaper()
        
        # Register signal handlers for cleanup
        signal.signal(signal.SIGINT, self._cleanup_and_exit)
        try:
            signal.signal(signal.SIGTERM, self._cleanup_and_exit)
        except Exception:
            pass
            
        log.info("[UCIHandler] UCI handler started successfully")
        
    def stop(self):
        """Stop the UCI handler and clean up resources."""
        self._kill = True
        self._cleanup()
        
    def _cleanup(self):
        """Clean up engine and game manager resources."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        
        log.info("[UCIHandler] Cleaning up resources...")
        
        # Clean up engine
        if self._engine is not None:
            try:
                self._cleanup_engine(self._engine)
            except Exception as e:
                log.warning(f"[UCIHandler] Error cleaning up engine: {e}")
            self._engine = None
            
        # Clean up game manager
        if self._manager is not None:
            try:
                self._manager.unsubscribe()
            except Exception as e:
                log.warning(f"[UCIHandler] Error unsubscribing from manager: {e}")
            self._manager = None
            
        # Clean up board
        try:
            board.ledsOff()
            board.cleanup(leds_off=True)
        except Exception as e:
            log.warning(f"[UCIHandler] Error cleaning up board: {e}")
            
        log.info("[UCIHandler] Cleanup complete")
        
    def _cleanup_engine(self, engine: chess.engine.SimpleEngine):
        """
        Safely quit an engine with timeout.
        
        Args:
            engine: The engine instance to quit
        """
        if engine is None:
            return
            
        try:
            quit_done = threading.Event()
            quit_error = []
            
            def quit_thread():
                try:
                    engine.quit()
                    quit_done.set()
                except Exception as e:
                    quit_error.append(str(e))
                    quit_done.set()
                    
            thread = threading.Thread(target=quit_thread, daemon=True)
            thread.start()
            thread.join(timeout=1.0)
            
            if not quit_done.is_set() or thread.is_alive():
                log.warning("[UCIHandler] Engine quit() timed out, attempting to kill process")
                thread.join(timeout=0.1)
                try:
                    if hasattr(engine, 'transport') and hasattr(engine.transport, 'proc'):
                        engine.transport.proc.terminate()
                        engine.transport.proc.wait(timeout=0.5)
                    elif hasattr(engine, 'proc'):
                        engine.proc.terminate()
                        engine.proc.wait(timeout=0.5)
                except Exception:
                    try:
                        if hasattr(engine, 'transport') and hasattr(engine.transport, 'proc'):
                            engine.transport.proc.kill()
                        elif hasattr(engine, 'proc'):
                            engine.proc.kill()
                    except Exception:
                        pass
            elif quit_error:
                log.debug(f"[UCIHandler] Engine quit() raised: {quit_error[0]}")
        except Exception as e:
            log.warning(f"[UCIHandler] Error during engine cleanup: {e}")
            
    def _cleanup_and_exit(self, signum=None, frame=None):
        """Signal handler for cleanup and exit."""
        if self._cleaned_up:
            os._exit(0)
        log.info("[UCIHandler] Signal received, cleaning up and exiting...")
        self._kill = True
        try:
            self._cleanup()
        except KeyboardInterrupt:
            log.warning("[UCIHandler] Interrupted during cleanup, forcing exit")
            os._exit(1)
        except Exception as e:
            log.warning(f"[UCIHandler] Error during cleanup: {e}")
        log.info("[UCIHandler] Goodbye!")
        sys.exit(0)
        
    def _on_event(self, event: int):
        """
        Handle game events from GameManager.
        
        Args:
            event: Event constant from GameManager
        """
        try:
            log.info(f"[UCIHandler] Event received: {event}")
            
            if event == EVENT_NEW_GAME:
                self._handle_new_game()
            elif event == EVENT_WHITE_TURN:
                self._handle_white_turn()
            elif event == EVENT_BLACK_TURN:
                self._handle_black_turn()
            elif event == EVENT_GAME_OVER:
                self._handle_game_over()
            elif event == EVENT_PROMOTION_NEEDED:
                self._handle_promotion()
            else:
                log.debug(f"[UCIHandler] Unhandled event: {event}")
                
        except Exception as e:
            log.error(f"[UCIHandler] Error handling event {event}: {e}")
            import traceback
            traceback.print_exc()
            
    def _on_move(self, move: str):
        """
        Handle move made on the board.
        
        Args:
            move: UCI move string
        """
        try:
            log.info(f"[UCIHandler] Move made: {move}")
            self._update_display()
        except Exception as e:
            log.error(f"[UCIHandler] Error handling move: {e}")
            
    def _on_key(self, key_pressed: int):
        """
        Handle key press from board.
        
        Args:
            key_pressed: Key constant from board module
        """
        try:
            log.info(f"[UCIHandler] Key pressed: {key_pressed}")
            if key_pressed == board.Key.BACK:
                self._kill = True
        except Exception as e:
            log.error(f"[UCIHandler] Error handling key: {e}")
            
    def _handle_new_game(self):
        """Handle new game event - reset display and prepare for game."""
        log.info("[UCIHandler] New game started")
        self._current_turn_is_white = True
        epaper.quickClear()
        self._update_display()
        
    def _handle_white_turn(self):
        """Handle white's turn - call engine if engine plays white."""
        log.info("[UCIHandler] White's turn")
        self._current_turn_is_white = True
        self._update_display()
        
        if self._engine_plays_white:
            self._call_engine()
            
    def _handle_black_turn(self):
        """Handle black's turn - call engine if engine plays black."""
        log.info("[UCIHandler] Black's turn")
        self._current_turn_is_white = False
        self._update_display()
        
        if self._engine_plays_black:
            self._call_engine()
            
    def _handle_game_over(self):
        """Handle game over event - display result and stop."""
        log.info("[UCIHandler] Game over")
        if self._manager is not None:
            board_obj = self._manager.get_board()
            outcome = board_obj.outcome(claim_draw=True)
            if outcome is not None:
                result = str(board_obj.result())
                termination = str(outcome.termination)
                log.info(f"[UCIHandler] Game result: {result}, termination: {termination}")
                self._display_game_over(result, termination)
        self._kill = True
        
    def _handle_promotion(self):
        """Handle promotion event - prompt user for promotion choice."""
        log.info("[UCIHandler] Promotion needed")
        # Default to queen - could be extended to prompt user
        # For now, manager defaults to queen
        
    def _call_engine(self):
        """
        Call the engine to make a move.
        Runs in a separate thread to avoid blocking.
        """
        if self._engine is None or self._manager is None:
            return
            
        def engine_thread():
            try:
                log.info("[UCIHandler] Calling engine for move")
                board_obj = self._manager.get_board()
                
                # Configure engine options if needed
                if self._engine_options:
                    self._engine.configure(self._engine_options)
                    
                # Request move from engine
                limit = chess.engine.Limit(time=5)
                result = self._engine.play(board_obj, limit, info=chess.engine.INFO_ALL)
                
                if result.move is not None:
                    move_str = str(result.move)
                    log.info(f"[UCIHandler] Engine move: {move_str}")
                    self._manager.set_forced_move(move_str)
                else:
                    log.warning("[UCIHandler] Engine returned no move")
                    
            except Exception as e:
                log.error(f"[UCIHandler] Error calling engine: {e}")
                import traceback
                traceback.print_exc()
                
        thread = threading.Thread(target=engine_thread, daemon=True)
        thread.start()
        
    def _update_display(self):
        """Update the display with current board state."""
        if self._manager is None:
            return
            
        try:
            fen = self._manager.get_fen()
            self._draw_board(fen)
        except Exception as e:
            log.error(f"[UCIHandler] Error updating display: {e}")
            
    def _draw_board(self, fen: str):
        """
        Draw the chess board to the display.
        
        Args:
            fen: FEN string representation of board position
        """
        try:
            # Parse FEN and draw pieces
            curfen = str(fen).split()[0]  # Get position part only
            curfen = curfen.replace("/", "")
            curfen = curfen.replace("1", " ")
            curfen = curfen.replace("2", "  ")
            curfen = curfen.replace("3", "   ")
            curfen = curfen.replace("4", "    ")
            curfen = curfen.replace("5", "     ")
            curfen = curfen.replace("6", "      ")
            curfen = curfen.replace("7", "       ")
            curfen = curfen.replace("8", "        ")
            
            # Reverse ranks for display (rank 8 first)
            nfen = ""
            for rank in range(8, 0, -1):
                for file in range(0, 8):
                    nfen = nfen + curfen[((rank - 1) * 8) + file]
                    
            # Create board image
            from PIL import Image, ImageDraw
            lboard = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(lboard)
            chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            # Draw pieces
            for x in range(0, 64):
                pos = (x - 63) * -1
                row = (16 * (pos // 8))
                col = (x % 8) * 16
                px = 0
                r = x // 8
                c = x % 8
                py = 0
                
                # Determine square color
                if (r // 2 == r / 2 and c // 2 == c / 2):
                    py = py + 16
                if (r // 2 != r / 2 and c // 2 != c / 2):
                    py = py + 16
                    
                # Map piece symbols to sprite positions
                piece = nfen[x]
                if piece == "P":
                    px = 16
                elif piece == "R":
                    px = 32
                elif piece == "N":
                    px = 48
                elif piece == "B":
                    px = 64
                elif piece == "Q":
                    px = 80
                elif piece == "K":
                    px = 96
                elif piece == "p":
                    px = 112
                elif piece == "r":
                    px = 128
                elif piece == "n":
                    px = 144
                elif piece == "b":
                    px = 160
                elif piece == "q":
                    px = 176
                elif piece == "k":
                    px = 192
                else:
                    # Empty square - skip (board background is already white)
                    continue
                    
                piece_img = chessfont.crop((px, py, px+16, py+16))
                
                # Flip board if engine plays white (player sees from black's perspective)
                if self._engine_plays_white:
                    piece_img = piece_img.transpose(Image.FLIP_TOP_BOTTOM)
                    piece_img = piece_img.transpose(Image.FLIP_LEFT_RIGHT)
                    
                lboard.paste(piece_img, (col, row))
                
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            epaper.drawImagePartial(0, 81, lboard)
            
        except Exception as e:
            log.error(f"[UCIHandler] Error drawing board: {e}")
            import traceback
            traceback.print_exc()
            
    def _display_game_over(self, result: str, termination: str):
        """
        Display game over screen.
        
        Args:
            result: Game result string ("1-0", "0-1", "1/2-1/2")
            termination: Termination reason
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
            image = Image.new('1', (128, 292), 255)
            draw = ImageDraw.Draw(image)
            font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
            draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
            draw.text((0, 20), "          " + result, font=font18, fill=0)
            draw.text((0, 40), termination[12:] if termination.startswith("Termination.") else termination, font=font18, fill=0)
            epaper.drawImagePartial(0, 0, image)
            time.sleep(10)
        except Exception as e:
            log.error(f"[UCIHandler] Error displaying game over: {e}")
            
    def run(self):
        """Main run loop - keep handler alive until stopped."""
        try:
            while not self._kill:
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("[UCIHandler] Keyboard interrupt received")
            self._kill = True
        finally:
            self._cleanup()


def main():
    """Main entry point for UCI handler."""
    if len(sys.argv) < 2:
        print("Usage: uci.py <engine_path> [player_color] [options_section]")
        sys.exit(1)
        
    engine_path = sys.argv[1]
    player_color = sys.argv[2] if len(sys.argv) > 2 else "white"
    
    # Parse engine options if provided
    engine_options = {}
    if len(sys.argv) > 3:
        # Could parse UCI options file here similar to existing uci.py
        pass
        
    handler = UCIHandler(engine_path, player_color, engine_options)
    handler.start()
    
    try:
        handler.run()
    except Exception as e:
        log.error(f"[UCIHandler] Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        handler.stop()


if __name__ == "__main__":
    main()

