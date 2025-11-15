"""
UCI Chess Engine Handler

Handles UCI engine integration, reacting to game manager events,
deciding when to call the engine, managing engine lifecycle, and handling UI/display.

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

import sys
import os
import signal
import pathlib
import configparser
import threading
import time
import chess
import chess.engine
from typing import Optional, Any
from random import randint
from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.games.manager import GameManager, GameEvent
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log


class UCIHandler:
    """
    Handles UCI engine integration and UI display.
    
    Reacts to game manager events, decides when to call the engine,
    manages engine lifecycle, and handles display updates.
    """
    
    def __init__(self, player_color: str, engine_name: str, engine_options_desc: str = "Default"):
        """
        Initialize UCI handler.
        
        Args:
            player_color: "white", "black", or "random"
            engine_name: Name of the engine executable
            engine_options_desc: Section name in .uci config file
        """
        self._kill_flag = False
        self._cleaned_up = False
        
        # Determine which side computer plays
        if player_color == "white":
            self._computer_side = chess.WHITE
        elif player_color == "black":
            self._computer_side = chess.BLACK
        else:  # random
            self._computer_side = chess.WHITE if randint(0, 1) == 0 else chess.BLACK
        
        # Initialize engines
        self._analysis_engine: Optional[chess.engine.SimpleEngine] = None
        self._play_engine: Optional[chess.engine.SimpleEngine] = None
        self._engine_options = {}
        
        self._initialize_engines(engine_name, engine_options_desc)
        
        # Initialize game manager
        self._manager = GameManager()
        self._manager.subscribe(
            event_callback=self._on_event,
            move_callback=self._on_move,
            key_callback=self._on_key,
            takeback_callback=self._on_takeback
        )
        
        # Set game info
        if self._computer_side == chess.WHITE:
            self._manager.set_game_info(engine_options_desc, "", "", engine_name, "Player")
        else:
            self._manager.set_game_info(engine_options_desc, "", "", "Player", engine_name)
        
        # Display state
        self._graphs_enabled = os.uname().machine == "armv7l"  # Enable on Pi Zero 2W
        self._score_history = []
        self._current_turn = chess.WHITE
        self._first_move = True
        
        # Initialize display
        epaper.initEpaper()
    
    def _initialize_engines(self, engine_name: str, options_desc: str) -> None:
        """Initialize analysis and play engines."""
        # Determine engine paths
        engines_dir = pathlib.Path(__file__).parent.parent / "engines"
        ct800_path = str((engines_dir / "ct800").resolve())
        engine_path = str((engines_dir / engine_name).resolve())
        uci_file_path = engine_path + ".uci"
        
        log.info(f"Analysis engine: {ct800_path}")
        log.info(f"Play engine: {engine_path}")
        
        # Start engines
        try:
            self._analysis_engine = chess.engine.SimpleEngine.popen_uci(ct800_path, timeout=None)
            self._play_engine = chess.engine.SimpleEngine.popen_uci(engine_path)
        except Exception as e:
            log.error(f"Failed to start engines: {e}")
            raise
        
        # Load engine options from config file
        if os.path.exists(uci_file_path):
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(uci_file_path)
            
            if config.has_section(options_desc):
                for key, value in config.items(options_desc):
                    if key != 'Description':
                        self._engine_options[key] = value
            elif config.has_section("DEFAULT"):
                for key, value in config.items("DEFAULT"):
                    if key != 'Description':
                        self._engine_options[key] = value
        
        # Configure play engine with options
        if self._engine_options:
            log.info(f"Configuring engine with options: {self._engine_options}")
            self._play_engine.configure(self._engine_options)
    
    def run(self) -> None:
        """Run the UCI handler main loop."""
        # Start the game
        log.info("Starting new game")
        self._write_text(0, "Starting game...")
        self._write_text(1, "              ")
        time.sleep(1)
        
        self._manager.reset_game()
        time.sleep(1)
        
        try:
            while not self._kill_flag:
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("Interrupted, cleaning up...")
        finally:
            self._cleanup()
    
    def _on_event(self, event: GameEvent) -> None:
        """Handle game events from manager."""
        try:
            if event == GameEvent.NEW_GAME:
                log.info("NEW_GAME event")
                self._manager.clear_forced_move()
                board.ledsOff()
                epaper.quickClear()
                self._score_history = []
                self._current_turn = chess.WHITE
                self._first_move = True
                
                epaper.pauseEpaper()
                self._draw_board(self._manager.get_fen())
                
                if self._graphs_enabled and self._analysis_engine:
                    info = self._analysis_engine.analyse(
                        self._manager.get_board(),
                        chess.engine.Limit(time=0.1)
                    )
                    self._draw_evaluation_graphs(info)
                
                epaper.unPauseEpaper()
            
            elif event == GameEvent.WHITE_TURN:
                self._current_turn = chess.WHITE
                log.info(f"WHITE_TURN: computer_side={self._computer_side}")
                
                if self._graphs_enabled and self._analysis_engine:
                    info = self._analysis_engine.analyse(
                        self._manager.get_board(),
                        chess.engine.Limit(time=0.5)
                    )
                    epaper.pauseEpaper()
                    self._draw_evaluation_graphs(info)
                    epaper.unPauseEpaper()
                
                self._draw_board(self._manager.get_fen())
                
                if self._current_turn == self._computer_side:
                    self._play_computer_move()
            
            elif event == GameEvent.BLACK_TURN:
                self._current_turn = chess.BLACK
                log.info(f"BLACK_TURN: computer_side={self._computer_side}")
                
                if self._graphs_enabled and self._analysis_engine:
                    info = self._analysis_engine.analyse(
                        self._manager.get_board(),
                        chess.engine.Limit(time=0.5)
                    )
                    epaper.pauseEpaper()
                    self._draw_evaluation_graphs(info)
                    epaper.unPauseEpaper()
                
                self._draw_board(self._manager.get_fen())
                
                if self._current_turn == self._computer_side:
                    self._play_computer_move()
            
            elif event == GameEvent.RESIGN_GAME:
                side = 1 if self._computer_side == chess.WHITE else 2
                self._manager.resign(side)
            
            elif event == GameEvent.GAME_OVER:
                self._handle_game_over()
        
        except Exception as e:
            log.error(f"Error in event callback: {e}")
            import traceback
            traceback.print_exc()
            try:
                epaper.unPauseEpaper()
            except:
                pass
    
    def _on_move(self, move: str) -> None:
        """Handle move callback from manager."""
        try:
            log.info(f"Move made: {move}")
            self._draw_board(self._manager.get_fen())
        except Exception as e:
            log.error(f"Error in move callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_key(self, key: Any) -> None:
        """Handle key press events."""
        log.info(f"Key event: {key}")
        
        if key == board.Key.BACK:
            self._kill_flag = True
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
            if self._analysis_engine:
                info = self._analysis_engine.analyse(
                    self._manager.get_board(),
                    chess.engine.Limit(time=0.5)
                )
                self._draw_evaluation_graphs(info)
    
    def _on_takeback(self) -> None:
        """Handle takeback callback."""
        log.info("Takeback detected")
        self._manager.clear_forced_move()
        board.ledsOff()
        
        # Switch turn and trigger appropriate event
        self._current_turn = not self._current_turn
        if self._current_turn == chess.WHITE:
            self._on_event(GameEvent.WHITE_TURN)
        else:
            self._on_event(GameEvent.BLACK_TURN)
    
    def _play_computer_move(self) -> None:
        """Get and execute computer move."""
        try:
            log.info(f"Computer's turn. FEN: {self._manager.get_fen()}")
            
            # Configure engine if needed
            if self._engine_options:
                self._play_engine.configure(self._engine_options)
            
            # Get move from engine
            limit = chess.engine.Limit(time=5)
            result = self._play_engine.play(
                self._manager.get_board(),
                limit,
                info=chess.engine.INFO_ALL
            )
            
            move = result.move
            move_str = str(move)
            log.info(f"Engine move: {move_str}")
            
            # Set as forced move
            self._manager.set_forced_move(move_str)
        
        except Exception as e:
            log.error(f"Error getting computer move: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_board(self, fen: str) -> None:
        """Draw chess board to display."""
        try:
            # Parse FEN
            fen_clean = fen.split()[0].replace("/", "")
            fen_clean = fen_clean.replace("1", " ")
            fen_clean = fen_clean.replace("2", "  ")
            fen_clean = fen_clean.replace("3", "   ")
            fen_clean = fen_clean.replace("4", "    ")
            fen_clean = fen_clean.replace("5", "     ")
            fen_clean = fen_clean.replace("6", "      ")
            fen_clean = fen_clean.replace("7", "       ")
            fen_clean = fen_clean.replace("8", "        ")
            
            # Reorder for display (flip vertically)
            display_fen = ""
            for rank in range(8, 0, -1):
                for file in range(8):
                    idx = ((rank - 1) * 8) + file
                    display_fen += fen_clean[idx]
            
            # Draw board
            board_img = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(board_img)
            chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            for x in range(64):
                pos = (x - 63) * -1
                row = 16 * (pos // 8)
                col = (x % 8) * 16
                
                # Calculate sprite position
                r = x // 8
                c = x % 8
                py = 0
                if (r // 2 == r / 2 and c // 2 == c / 2):
                    py = 16
                if (r // 2 != r / 2 and c // 2 == c / 2):
                    py = 16
                
                px = 0
                piece_char = display_fen[x]
                piece_map = {
                    'P': 16, 'R': 32, 'N': 48, 'B': 64, 'Q': 80, 'K': 96,
                    'p': 112, 'r': 128, 'n': 144, 'b': 160, 'q': 176, 'k': 192
                }
                px = piece_map.get(piece_char, 0)
                
                if px > 0:
                    piece = chessfont.crop((px, py, px + 16, py + 16))
                    if self._computer_side == chess.WHITE:
                        piece = piece.transpose(Image.FLIP_TOP_BOTTOM)
                        piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
                    board_img.paste(piece, (col, row))
            
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            epaper.drawImagePartial(0, 81, board_img)
        
        except Exception as e:
            log.error(f"Error drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_evaluation_graphs(self, info: dict) -> None:
        """Draw evaluation graphs to display."""
        if not self._graphs_enabled:
            image = Image.new('1', (128, 80), 255)
            epaper.drawImagePartial(0, 209, image)
            epaper.drawImagePartial(0, 1, image)
            return
        
        if "score" not in info:
            return
        
        # Parse score
        score_str = str(info["score"])
        score_val = 0
        
        if "Mate" in score_str:
            mate_str = score_str[13:24]
            mate_str = mate_str[1:mate_str.find(")")]
            score_val = float(mate_str)
            score_val = score_val / 100
        else:
            score_str_val = score_str[11:24]
            score_str_val = score_str_val[1:score_str_val.find(")")]
            score_val = float(score_str_val)
            score_val = score_val / 100
        
        if "BLACK" in score_str:
            score_val = score_val * -1
        
        # Draw evaluation display
        image = Image.new('1', (128, 80), 255)
        draw = ImageDraw.Draw(image)
        font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
        
        txt = "{:5.1f}".format(score_val)
        if score_val > 999:
            txt = ""
        if "Mate" in score_str:
            txt = "Mate in " + "{:2.0f}".format(abs(score_val * 100))
            score_val = score_val * 100000
        
        draw.text((50, 12), txt, font=font12, fill=0)
        draw.rectangle([(0, 1), (127, 11)], fill=None, outline='black')
        
        # Clamp score for display
        if score_val > 12:
            score_val = 12
        if score_val < -12:
            score_val = -12
        
        # Update score history
        if not self._first_move:
            self._score_history.append(score_val)
            if len(self._score_history) > 200:
                self._score_history.pop(0)
        else:
            self._first_move = False
        
        # Draw indicator
        offset = (128 / 25) * (score_val + 12)
        if offset < 128:
            draw.rectangle([(offset, 1), (127, 11)], fill=0, outline='black')
        
        # Draw bar chart
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
                draw.rectangle([(baroffset, y0), (baroffset + barwidth, y1)],
                              fill=col, outline='black')
                baroffset += barwidth
        
        # Draw turn indicator
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
    
    def _handle_game_over(self) -> None:
        """Handle game over event."""
        try:
            result = self._manager.get_result()
            
            # Display termination message
            termination = "GAME OVER"
            image = Image.new('1', (128, 12), 255)
            draw = ImageDraw.Draw(image)
            font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
            draw.text((30, 0), termination, font=font12, fill=0)
            epaper.drawImagePartial(0, 221, image)
            time.sleep(0.3)
            image = image.transpose(Image.FLIP_TOP_BOTTOM)
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
            epaper.drawImagePartial(0, 57, image)
            
            epaper.quickClear()
            
            # Display end screen
            image = Image.new('1', (128, 292), 255)
            draw = ImageDraw.Draw(image)
            font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
            draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
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
                    draw.rectangle([(baroffset, 114),
                                  (baroffset + barwidth, 114 - (score * 4))],
                                 fill=col, outline='black')
                    baroffset += barwidth
            
            epaper.drawImagePartial(0, 0, image)
            time.sleep(10)
            self._kill_flag = True
        
        except Exception as e:
            log.error(f"Error handling game over: {e}")
            import traceback
            traceback.print_exc()
    
    def _write_text(self, row: int, text: str) -> None:
        """Write text to display."""
        image = Image.new('1', (128, 20), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        draw.text((0, 0), text, font=font18, fill=0)
        epaper.drawImagePartial(0, (row * 20), image)
    
    def _cleanup(self) -> None:
        """Clean up resources."""
        if self._cleaned_up:
            return
        
        self._cleaned_up = True
        self._kill_flag = True
        
        log.info("Cleaning up UCI handler...")
        
        # Clean up engines
        def cleanup_engine(engine, name):
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
                    try:
                        if hasattr(engine, 'transport') and hasattr(engine.transport, 'proc'):
                            engine.transport.proc.terminate()
                            engine.transport.proc.wait(timeout=0.5)
                        elif hasattr(engine, 'proc'):
                            engine.proc.terminate()
                            engine.proc.wait(timeout=0.5)
                    except:
                        try:
                            if hasattr(engine, 'transport') and hasattr(engine.transport, 'proc'):
                                engine.transport.proc.kill()
                            elif hasattr(engine, 'proc'):
                                engine.proc.kill()
                        except:
                            pass
            except Exception as e:
                log.warning(f"Error cleaning up {name}: {e}")
        
        cleanup_engine(self._analysis_engine, "analysis_engine")
        cleanup_engine(self._play_engine, "play_engine")
        
        # Clean up board
        try:
            board.ledsOff()
        except:
            pass
        
        try:
            board.unPauseEvents()
        except:
            pass
        
        # Clean up manager
        try:
            self._manager.clear_forced_move()
        except:
            pass
        
        try:
            self._manager.unsubscribe()
        except:
            pass
        
        try:
            board.cleanup(leds_off=True)
        except:
            pass
        
        log.info("Cleanup complete")


def cleanup_and_exit(signum=None, frame=None):
    """Signal handler for graceful exit."""
    log.info("Received signal, exiting...")
    sys.exit(0)


def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGINT, cleanup_and_exit)
    try:
        signal.signal(signal.SIGTERM, cleanup_and_exit)
    except Exception:
        pass
    
    # Parse command line arguments
    player_color = sys.argv[1] if len(sys.argv) > 1 else "white"
    engine_name = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    engine_options_desc = sys.argv[3] if len(sys.argv) > 3 else "Default"
    
    log.info(f"Player color: {player_color}")
    log.info(f"Engine name: {engine_name}")
    log.info(f"Engine options: {engine_options_desc}")
    
    # Create and run handler
    handler = UCIHandler(player_color, engine_name, engine_options_desc)
    handler.run()


if __name__ == "__main__":
    main()

