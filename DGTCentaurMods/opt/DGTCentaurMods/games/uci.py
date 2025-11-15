"""
UCI Chess Engine Handler - Reacts to game manager events and manages engine lifecycle.

This module subscribes to game manager events, decides when to call the chess engine,
handles UI/display updates, draws the board state, and manages engine lifecycle.

This file is part of the DGTCentaur Mods open source software
( https://github.com/EdNekebno/DGTCentaur )

DGTCentaur Mods is free software: you can redistribute
it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version.

DGTCentaur Mods is distributed in the hope that it will
be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this file.  If not, see

https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md

This and any other notices must remain intact and unaltered in any
distribution, modification, variant, or derivative of this software.
"""

import os
import sys
import time
import signal
import threading
import pathlib
import configparser
from typing import Optional, List
from random import randint

import chess
import chess.engine
from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.games import manager
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log

# Maximum score history size to prevent memory leaks
MAX_SCOREHISTORY_SIZE = 200


class UCIHandler:
    """
    Handles UCI engine communication and UI updates.
    
    Subscribes to game manager events, manages engine lifecycle,
    decides when to call engine, and handles display updates.
    """
    
    def __init__(self, computer_color: str = "white", engine_name: str = "stockfish_pi",
                 engine_options_desc: str = "Default"):
        """
        Initialize UCI handler.
        
        Args:
            computer_color: "white", "black", or "random" - which side the computer plays
            engine_name: Name of the engine executable (without path)
            engine_options_desc: Section name in .uci config file for engine options
        """
        self._kill = False
        self._cleaned_up = False
        
        # Determine computer color
        if computer_color == "white":
            self._computer_color = chess.WHITE
        elif computer_color == "black":
            self._computer_color = chess.BLACK
        elif computer_color == "random":
            self._computer_color = randint(0, 1)
        else:
            self._computer_color = chess.WHITE
        
        # Engine setup
        self._engine_name = engine_name
        self._engine_options_desc = engine_options_desc
        self._aengine: Optional[chess.engine.SimpleEngine] = None  # Analysis engine
        self._pengine: Optional[chess.engine.SimpleEngine] = None  # Playing engine
        self._engine_options = {}
        
        # Game state
        self._current_turn = chess.WHITE
        self._first_move = True
        self._score_history: List[float] = []
        self._graphs_enabled = os.uname().machine == "armv7l"  # Enable on Pi Zero 2W
        
        # Get game manager instance
        self._manager = manager.get_manager()
        
        # Setup signal handlers for clean exit
        signal.signal(signal.SIGINT, self._cleanup_and_exit)
        try:
            signal.signal(signal.SIGTERM, self._cleanup_and_exit)
        except Exception:
            pass
    
    def _load_engine_options(self) -> None:
        """Load engine options from .uci config file."""
        engine_path = pathlib.Path(__file__).parent.parent / "engines" / f"{self._engine_name}.uci"
        
        if not engine_path.exists():
            log.warning(f"UCI config file not found: {engine_path}, using default settings")
            return
        
        try:
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(str(engine_path))
            
            if config.has_section(self._engine_options_desc):
                for key, value in config.items(self._engine_options_desc):
                    if key != 'Description':  # Skip non-UCI metadata
                        self._engine_options[key] = value
                log.info(f"Loaded engine options from {self._engine_options_desc}: {self._engine_options}")
            elif config.has_section("DEFAULT"):
                for key, value in config.items("DEFAULT"):
                    if key != 'Description':
                        self._engine_options[key] = value
                log.info(f"Using DEFAULT engine options: {self._engine_options}")
        except Exception as e:
            log.error(f"Error loading engine options: {e}")
    
    def _initialize_engines(self) -> None:
        """Initialize chess engines."""
        try:
            # Analysis engine (CT-800)
            ct800_path = pathlib.Path(__file__).parent.parent / "engines" / "ct800"
            self._aengine = chess.engine.SimpleEngine.popen_uci(str(ct800_path.resolve()), timeout=None)
            log.info(f"Analysis engine initialized: {self._aengine}")
            
            # Playing engine
            engine_path = pathlib.Path(__file__).parent.parent / "engines" / self._engine_name
            self._pengine = chess.engine.SimpleEngine.popen_uci(str(engine_path.resolve()))
            log.info(f"Playing engine initialized: {self._pengine}")
            
            # Configure playing engine with options
            if self._engine_options:
                self._pengine.configure(self._engine_options)
                log.info(f"Configured engine with options: {self._engine_options}")
        except Exception as e:
            log.error(f"Error initializing engines: {e}")
            raise
    
    def _cleanup_engines(self) -> None:
        """Safely cleanup chess engines."""
        def cleanup_engine(engine, name):
            """Safely quit an engine with timeout."""
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
                    log.warning(f"{name} quit() timed out, attempting to kill process")
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
                    log.debug(f"{name} quit() raised: {quit_error[0]}")
            except Exception as e:
                log.warning(f"Error cleaning up {name}: {e}")
        
        cleanup_engine(self._aengine, "aengine")
        cleanup_engine(self._pengine, "pengine")
        self._aengine = None
        self._pengine = None
    
    def _cleanup_and_exit(self, signum=None, frame=None) -> None:
        """Clean up resources and exit gracefully."""
        if self._cleaned_up:
            os._exit(0)
        
        log.info(">>> Cleaning up and exiting...")
        self._kill = True
        
        try:
            self._do_cleanup()
        except KeyboardInterrupt:
            log.warning(">>> Interrupted during cleanup, forcing exit")
            os._exit(1)
        except Exception as e:
            log.warning(f">>> Error during cleanup: {e}")
        
        log.info("Goodbye!")
        sys.exit(0)
    
    def _do_cleanup(self) -> None:
        """Perform cleanup operations."""
        if self._cleaned_up:
            return
        
        self._cleaned_up = True
        
        try:
            board.ledsOff()
        except Exception:
            pass
        
        try:
            board.unPauseEvents()
        except Exception:
            pass
        
        try:
            self._manager.reset_move_state()
        except Exception:
            pass
        
        try:
            manager.unsubscribe_game()
        except Exception:
            pass
        
        try:
            board.cleanup(leds_off=True)
        except Exception:
            pass
        
        self._cleanup_engines()
    
    def _event_callback(self, event) -> None:
        """Handle game manager events."""
        try:
            log.info(f"[UCIHandler] Event received: {event}")
            
            if event == manager.EVENT_NEW_GAME:
                log.info("[UCIHandler] NEW_GAME event")
                self._manager.reset_move_state()
                board.ledsOff()
                epaper.quickClear()
                self._score_history = []
                self._current_turn = chess.WHITE
                self._first_move = True
                epaper.pauseEpaper()
                self._draw_board(self._manager.get_fen())
                log.info(f"Board reset. FEN: {self._manager.get_fen()}")
                
                if self._graphs_enabled and self._aengine:
                    try:
                        info = self._aengine.analyse(self._manager.get_board(), chess.engine.Limit(time=0.1))
                        self._draw_evaluation_graphs(info)
                    except Exception as e:
                        log.error(f"Error in analysis: {e}")
                
                epaper.unPauseEpaper()
            
            elif event == manager.EVENT_WHITE_TURN:
                self._current_turn = chess.WHITE
                log.info(f"[UCIHandler] WHITE_TURN event, computer_color={self._computer_color}")
                
                if self._graphs_enabled and self._aengine:
                    try:
                        info = self._aengine.analyse(self._manager.get_board(), chess.engine.Limit(time=0.5))
                        epaper.pauseEpaper()
                        self._draw_evaluation_graphs(info)
                        epaper.unPauseEpaper()
                    except Exception as e:
                        log.error(f"Error in analysis: {e}")
                
                self._draw_board(self._manager.get_fen())
                
                if self._current_turn == self._computer_color:
                    self._play_computer_move()
            
            elif event == manager.EVENT_BLACK_TURN:
                self._current_turn = chess.BLACK
                log.info(f"[UCIHandler] BLACK_TURN event, computer_color={self._computer_color}")
                
                if self._graphs_enabled and self._aengine:
                    try:
                        info = self._aengine.analyse(self._manager.get_board(), chess.engine.Limit(time=0.5))
                        epaper.pauseEpaper()
                        self._draw_evaluation_graphs(info)
                        epaper.unPauseEpaper()
                    except Exception as e:
                        log.error(f"Error in analysis: {e}")
                
                self._draw_board(self._manager.get_fen())
                
                if self._current_turn == self._computer_color:
                    self._play_computer_move()
            
            elif event == manager.EVENT_RESIGN_GAME:
                side = 1 if self._computer_color == chess.WHITE else 2
                self._manager.resign_game(side)
            
            elif isinstance(event, str) and event.startswith("Termination."):
                self._handle_game_over(event)
        
        except Exception as e:
            log.error(f"Error in event callback: {e}")
            import traceback
            traceback.print_exc()
            try:
                epaper.unPauseEpaper()
            except Exception:
                pass
    
    def _move_callback(self, move: str) -> None:
        """Handle move events from game manager."""
        try:
            log.info(f"[UCIHandler] Move callback: {move}")
            self._draw_board(self._manager.get_fen())
        except Exception as e:
            log.error(f"Error in move callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _takeback_callback(self) -> None:
        """Handle takeback events."""
        log.info("[UCIHandler] Takeback callback")
        self._manager.reset_move_state()
        board.ledsOff()
        
        # Switch turn and trigger appropriate event
        if self._current_turn == chess.WHITE:
            self._current_turn = chess.BLACK
            self._event_callback(manager.EVENT_BLACK_TURN)
        else:
            self._current_turn = chess.WHITE
            self._event_callback(manager.EVENT_WHITE_TURN)
    
    def _key_callback(self, key) -> None:
        """Handle key press events."""
        log.info(f"[UCIHandler] Key event: {key}")
        
        if key == board.Key.BACK:
            self._kill = True
        elif key == board.Key.DOWN:
            # Disable graphs
            image = Image.new('1', (128, 80), 255)
            epaper.drawImagePartial(0, 209, image)
            epaper.drawImagePartial(0, 1, image)
            self._graphs_enabled = False
        elif key == board.Key.UP:
            # Enable graphs
            self._graphs_enabled = True
            self._first_move = True
            if self._aengine:
                try:
                    info = self._aengine.analyse(self._manager.get_board(), chess.engine.Limit(time=0.5))
                    self._draw_evaluation_graphs(info)
                except Exception as e:
                    log.error(f"Error in analysis: {e}")
    
    def _play_computer_move(self) -> None:
        """Get move from engine and set it up for the player to make."""
        if not self._pengine:
            log.error("Playing engine not initialized")
            return
        
        try:
            log.info(f"[UCIHandler] Computer's turn! Current FEN: {self._manager.get_fen()}")
            
            # Configure engine with options if needed
            if self._engine_options:
                self._pengine.configure(self._engine_options)
            
            # Get move from engine
            limit = chess.engine.Limit(time=5)
            result = self._pengine.play(self._manager.get_board(), limit, info=chess.engine.INFO_ALL)
            move = result.move
            move_str = move.uci()
            
            log.info(f"[UCIHandler] Engine returned move: {move_str}")
            
            # Validate move is legal
            if move not in self._manager.get_board().legal_moves:
                log.error(f"ERROR: Move {move_str} is not legal!")
                raise ValueError(f"Illegal move: {move_str}")
            
            # Set up the move for player to make
            self._manager.set_computer_move(move_str, forced=True)
            log.info(f"[UCIHandler] Computer move setup complete: {move_str}")
            
        except Exception as e:
            log.error(f"Error getting computer move: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_board(self, fen: str) -> None:
        """Draw the current board state on the display."""
        try:
            log.info(f"[UCIHandler] Drawing board with FEN: {fen[:20]}...")
            
            # Parse FEN and convert to display format
            curfen = str(fen).split()[0]  # Get just the position part
            curfen = curfen.replace("/", "")
            curfen = curfen.replace("1", " ")
            curfen = curfen.replace("2", "  ")
            curfen = curfen.replace("3", "   ")
            curfen = curfen.replace("4", "    ")
            curfen = curfen.replace("5", "     ")
            curfen = curfen.replace("6", "      ")
            curfen = curfen.replace("7", "       ")
            curfen = curfen.replace("8", "        ")
            
            # Reorder for display (rank 8 to rank 1)
            nfen = ""
            for rank in range(8, 0, -1):
                for file in range(0, 8):
                    nfen = nfen + curfen[((rank - 1) * 8) + file]
            
            # Create board image
            lboard = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(lboard)
            chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            for x in range(0, 64):
                pos = (x - 63) * -1
                row = (16 * (pos // 8))
                col = (x % 8) * 16
                px = 0
                r = x // 8
                c = x % 8
                py = 0
                
                # Checkerboard pattern
                if (r // 2 == r / 2 and c // 2 == c / 2):
                    py = py + 16
                if (r // 2 != r / 2 and c // 2 == c / 2):
                    py = py + 16
                
                # Map piece characters to sprite positions
                piece_char = nfen[x]
                if piece_char == "P":
                    px = 16
                elif piece_char == "R":
                    px = 32
                elif piece_char == "N":
                    px = 48
                elif piece_char == "B":
                    px = 64
                elif piece_char == "Q":
                    px = 80
                elif piece_char == "K":
                    px = 96
                elif piece_char == "p":
                    px = 112
                elif piece_char == "r":
                    px = 128
                elif piece_char == "n":
                    px = 144
                elif piece_char == "b":
                    px = 160
                elif piece_char == "q":
                    px = 176
                elif piece_char == "k":
                    px = 192
                
                if piece_char != " ":
                    piece = chessfont.crop((px, py, px+16, py+16))
                    if self._computer_color == chess.WHITE:
                        piece = piece.transpose(Image.FLIP_TOP_BOTTOM)
                        piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
                    lboard.paste(piece, (col, row))
            
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            epaper.drawImagePartial(0, 81, lboard)
            
        except Exception as e:
            log.error(f"Error drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_evaluation_graphs(self, info) -> None:
        """Draw evaluation graphs to the screen."""
        if "score" not in info:
            log.info("No score in info, skipping graphs")
            return
        
        if not self._graphs_enabled:
            image = Image.new('1', (128, 80), 255)
            epaper.drawImagePartial(0, 209, image)
            epaper.drawImagePartial(0, 1, image)
            return
        
        try:
            sc = str(info["score"])
            sval = 0
            
            if "Mate" in sc:
                sval_str = sc[13:24]
                sval_str = sval_str[1:sval_str.find(")")]
                sval = float(sval_str)
            else:
                sval_str = sc[11:24]
                sval_str = sval_str[1:sval_str.find(")")]
                sval = float(sval_str)
            
            sval = sval / 100
            if "BLACK" in sc:
                sval = sval * -1
            
            # Draw evaluation bars
            image = Image.new('1', (128, 80), 255)
            draw = ImageDraw.Draw(image)
            font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
            
            txt = "{:5.1f}".format(sval)
            if sval > 999:
                txt = ""
            if "Mate" in sc:
                txt = "Mate in " + "{:2.0f}".format(abs(sval * 100))
                sval = sval * 100000
            
            draw.text((50, 12), txt, font=font12, fill=0)
            draw.rectangle([(0, 1), (127, 11)], fill=None, outline='black')
            
            # Calculate indicator position
            if sval > 12:
                sval = 12
            if sval < -12:
                sval = -12
            
            if not self._first_move:
                self._score_history.append(sval)
                if len(self._score_history) > MAX_SCOREHISTORY_SIZE:
                    self._score_history.pop(0)
            else:
                self._first_move = False
            
            offset = (128 / 25) * (sval + 12)
            if offset < 128:
                draw.rectangle([(offset, 1), (127, 11)], fill=0, outline='black')
            
            # Bar chart view
            if len(self._score_history) > 0:
                draw.line([(0, 50), (128, 50)], fill=0, width=1)
                barwidth = 128 / len(self._score_history)
                if barwidth > 8:
                    barwidth = 8
                baroffset = 0
                for score in self._score_history:
                    col = 255 if score >= 0 else 0
                    y_calc = 50 - (score * 2)
                    y0 = min(50, y_calc)
                    y1 = max(50, y_calc)
                    draw.rectangle([(baroffset, y0), (baroffset + barwidth, y1)], fill=col, outline='black')
                    baroffset = baroffset + barwidth
            
            tmp = image.copy()
            dr2 = ImageDraw.Draw(tmp)
            if self._current_turn == chess.WHITE:
                dr2.ellipse((119, 14, 126, 21), fill=0, outline=0)
            epaper.drawImagePartial(0, 209, tmp)
            
            if self._current_turn == chess.BLACK:
                draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
            
            image = image.transpose(Image.FLIP_TOP_BOTTOM)
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
            epaper.drawImagePartial(0, 1, image)
        
        except Exception as e:
            log.error(f"Error drawing evaluation graphs: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_game_over(self, termination: str) -> None:
        """Handle game over event."""
        try:
            termination_type = termination[12:]  # Remove "Termination." prefix
            
            # Display termination message
            image = Image.new('1', (128, 12), 255)
            draw = ImageDraw.Draw(image)
            font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
            draw.text((30, 0), termination_type, font=font12, fill=0)
            epaper.drawImagePartial(0, 221, image)
            time.sleep(0.3)
            image = image.transpose(Image.FLIP_TOP_BOTTOM)
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
            epaper.drawImagePartial(0, 57, image)
            epaper.quickClear()
            
            # Display end screen
            log.info("Displaying end screen")
            image = Image.new('1', (128, 292), 255)
            draw = ImageDraw.Draw(image)
            font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
            draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
            
            # Get result from manager
            result = "Unknown"
            try:
                # Try to get result from board
                outcome = self._manager.get_board().outcome(claim_draw=True)
                if outcome:
                    result = str(self._manager.get_board().result())
            except Exception:
                pass
            
            draw.text((0, 20), "          " + result, font=font18, fill=0)
            
            # Draw score history if available
            if len(self._score_history) > 0:
                draw.line([(0, 114), (128, 114)], fill=0, width=1)
                barwidth = 128 / len(self._score_history)
                if barwidth > 8:
                    barwidth = 8
                baroffset = 0
                for score in self._score_history:
                    col = 255 if score >= 0 else 0
                    y_calc = 114 - (score * 4)
                    y0 = min(114, y_calc)
                    y1 = max(114, y_calc)
                    draw.rectangle([(baroffset, y0), (baroffset + barwidth, y1)], fill=col, outline='black')
                    baroffset = baroffset + barwidth
            
            epaper.drawImagePartial(0, 0, image)
            time.sleep(10)
            self._kill = True
        
        except Exception as e:
            log.error(f"Error handling game over: {e}")
            import traceback
            traceback.print_exc()
    
    def start(self) -> None:
        """Start the UCI handler."""
        try:
            # Initialize epaper
            epaper.initEpaper()
            
            # Load engine options
            self._load_engine_options()
            
            # Initialize engines
            self._initialize_engines()
            
            # Set game info
            if self._computer_color == chess.WHITE:
                self._manager.set_game_info(self._engine_options_desc, "", "", self._engine_name, "Player")
            else:
                self._manager.set_game_info(self._engine_options_desc, "", "", "Player", self._engine_name)
            
            # Subscribe to manager events
            self._manager.subscribe_event(self._event_callback)
            self._manager.subscribe_move(self._move_callback)
            self._manager.subscribe_key(self._key_callback)
            self._manager.subscribe_takeback(self._takeback_callback)
            
            # Start manager
            self._manager.start()
            
            log.info("[UCIHandler] UCI handler started")
            
            # Trigger initial game start
            log.info("Triggering NEW_GAME event")
            self._write_text(0, "Starting game...")
            self._write_text(1, "              ")
            time.sleep(1)
            self._event_callback(manager.EVENT_NEW_GAME)
            time.sleep(1)
            # Only trigger WHITE_TURN if computer is NOT white (let player move first)
            # If computer is white, wait for manager to detect starting position and trigger turn
            if self._computer_color != chess.WHITE:
                self._event_callback(manager.EVENT_WHITE_TURN)
            
            # Main loop
            while not self._kill:
                time.sleep(0.1)
        
        except KeyboardInterrupt:
            log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
            self._cleanup_and_exit()
        except Exception as e:
            log.error(f"Error in UCI handler: {e}")
            import traceback
            traceback.print_exc()
            self._cleanup_and_exit()
        finally:
            log.info(">>> Final cleanup")
            self._do_cleanup()
    
    def _write_text(self, row: int, txt: str) -> None:
        """Write text on a given line number."""
        image = Image.new('1', (128, 20), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        draw.text((0, 0), txt, font=font18, fill=0)
        epaper.drawImagePartial(0, (row * 20), image)


def main():
    """Main entry point for UCI handler."""
    # Parse command line arguments
    computer_color = sys.argv[1] if len(sys.argv) > 1 else "white"
    engine_name = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    engine_options_desc = sys.argv[3] if len(sys.argv) > 3 else "Default"
    
    log.info(f"Starting UCI handler: computer_color={computer_color}, engine={engine_name}, options={engine_options_desc}")
    
    handler = UCIHandler(computer_color, engine_name, engine_options_desc)
    handler.start()


if __name__ == "__main__":
    main()

