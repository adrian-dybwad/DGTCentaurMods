# UCI chess engine interface with event-driven architecture
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

from DGTCentaurMods.games.manager import GameManager, GameEvent
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.sync_centaur import Key
from DGTCentaurMods.board.logging import log

import time
import chess
import chess.engine
import sys
import pathlib
import os
import threading
import signal
import configparser
from PIL import Image, ImageDraw, ImageFont
from typing import Optional
from random import randint


class UCIEngine:
    """
    UCI chess engine handler that reacts to game manager events,
    manages engine lifecycle, and handles UI/display updates.
    """
    
    def __init__(self, player_color: str = "white", engine_name: str = "stockfish_pi", 
                 engine_options_desc: str = "Default"):
        """
        Initialize UCI engine handler.
        
        Args:
            player_color: "white", "black", or "random"
            engine_name: Name of the engine executable
            engine_options_desc: Section name in .uci config file
        """
        # Determine computer color
        if player_color == "white":
            self._computer_color = chess.BLACK  # Player is white, computer is black
        elif player_color == "black":
            self._computer_color = chess.WHITE  # Player is black, computer is white
        elif player_color == "random":
            self._computer_color = chess.WHITE if randint(0, 1) == 0 else chess.BLACK
        else:
            self._computer_color = chess.BLACK  # Default
        
        # Engine paths
        engines_dir = pathlib.Path(__file__).parent.parent / "engines"
        ct800_path = engines_dir / "ct800"
        engine_path = engines_dir / engine_name
        uci_file_path = engine_path.with_suffix(".uci")
        
        self._engine_name = engine_name
        self._engine_path = str(engine_path.resolve())
        self._analysis_engine_path = str(ct800_path.resolve())
        self._uci_file_path = str(uci_file_path)
        
        # Engine instances
        self._analysis_engine: Optional[chess.engine.SimpleEngine] = None
        self._play_engine: Optional[chess.engine.SimpleEngine] = None
        
        # Engine options
        self._engine_options = self._load_engine_options(engine_options_desc)
        
        # Game manager
        self._game_manager = GameManager()
        self._game_manager.subscribe(
            event_callback=self._on_game_event,
            move_callback=self._on_move,
            key_callback=self._on_key_press,
            takeback_callback=self._on_takeback
        )
        
        # State
        self._running = False
        self._current_turn = chess.WHITE
        self._cleaned_up = False
        
        # Display state
        self._graphs_enabled = os.uname().machine == "armv7l"  # Enable on Pi Zero 2W
        self._score_history = []
        self._max_score_history = 200
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
        except Exception:
            pass
    
    def _load_engine_options(self, options_desc: str) -> dict:
        """Load engine options from .uci config file."""
        options = {}
        
        if not os.path.exists(self._uci_file_path):
            log.warning(f"UCI file not found: {self._uci_file_path}, using default settings")
            return options
        
        try:
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(self._uci_file_path)
            
            section = options_desc if config.has_section(options_desc) else "Default"
            if config.has_section(section):
                for key, value in config.items(section):
                    if key != 'Description':  # Skip metadata fields
                        options[key] = value
        except Exception as e:
            log.warning(f"Error loading engine options: {e}")
        
        return options
    
    def _signal_handler(self, signum, frame):
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        log.info(">>> Received shutdown signal, cleaning up...")
        self.stop()
        sys.exit(0)
    
    def start(self):
        """Start the UCI engine handler."""
        if self._running:
            return
        
        log.info(f"[UCIEngine] Starting with computer color: {'WHITE' if self._computer_color == chess.WHITE else 'BLACK'}")
        
        # Initialize engines
        try:
            self._analysis_engine = chess.engine.SimpleEngine.popen_uci(
                self._analysis_engine_path, timeout=None
            )
            log.info(f"[UCIEngine] Analysis engine started: {self._analysis_engine_path}")
        except Exception as e:
            log.error(f"[UCIEngine] Failed to start analysis engine: {e}")
            self._analysis_engine = None
        
        try:
            self._play_engine = chess.engine.SimpleEngine.popen_uci(self._engine_path)
            log.info(f"[UCIEngine] Play engine started: {self._engine_path}")
            
            # Configure engine options
            if self._engine_options:
                log.info(f"[UCIEngine] Configuring engine with options: {self._engine_options}")
                self._play_engine.configure(self._engine_options)
        except Exception as e:
            log.error(f"[UCIEngine] Failed to start play engine: {e}")
            self._play_engine = None
        
        # Set game info
        if self._computer_color == chess.WHITE:
            self._game_manager.set_game_info(
                event=self._engine_options.get('Description', 'Default'),
                white=self._engine_name,
                black="Player"
            )
        else:
            self._game_manager.set_game_info(
                event=self._engine_options.get('Description', 'Default'),
                white="Player",
                black=self._engine_name
            )
        
        # Initialize display
        epaper.initEpaper()
        
        # Start game manager
        self._game_manager.start()
        self._running = True
        
        # Check if board is in starting position and trigger new game
        current_state = board.getChessState()
        if self._is_starting_position(current_state):
            log.info("[UCIEngine] Board in starting position, triggering new game")
            self._on_game_event(GameEvent.NEW_GAME, None)
            time.sleep(0.5)
            self._on_game_event(GameEvent.WHITE_TURN, None)
        else:
            # Manually trigger game start
            log.info("[UCIEngine] Triggering NEW_GAME event")
            self._write_text(0, "Starting game...")
            self._write_text(1, "              ")
            time.sleep(1)
            self._on_game_event(GameEvent.NEW_GAME, None)
            time.sleep(1)
            self._on_game_event(GameEvent.WHITE_TURN, None)
        
        log.info("[UCIEngine] Started successfully")
    
    def stop(self):
        """Stop the UCI engine handler and clean up resources."""
        if self._cleaned_up:
            return
        
        self._cleaned_up = True
        self._running = False
        
        log.info("[UCIEngine] Cleaning up...")
        
        # Clean up engines
        self._cleanup_engine(self._analysis_engine, "analysis_engine")
        self._cleanup_engine(self._play_engine, "play_engine")
        
        # Clean up board
        try:
            board.ledsOff()
        except Exception:
            pass
        
        try:
            board.unPauseEvents()
        except Exception:
            pass
        
        # Stop game manager
        try:
            self._game_manager.stop()
        except Exception:
            pass
        
        # Clean up async driver
        try:
            board.cleanup(leds_off=True)
        except Exception:
            pass
        
        log.info("[UCIEngine] Cleanup complete")
    
    def _cleanup_engine(self, engine: Optional[chess.engine.SimpleEngine], name: str):
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
                log.warning(f"[UCIEngine] {name} quit() timed out, attempting to kill process")
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
        except Exception as e:
            log.warning(f"[UCIEngine] Error cleaning up {name}: {e}")
    
    def run(self):
        """Run the main loop."""
        try:
            self.start()
            while self._running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
            self.stop()
        finally:
            self.stop()
    
    def _on_game_event(self, event: GameEvent, termination: Optional[str]):
        """Handle game events from the manager."""
        try:
            log.info(f"[UCIEngine] Game event: {event}")
            
            if event == GameEvent.NEW_GAME:
                self._handle_new_game()
            elif event == GameEvent.WHITE_TURN:
                self._current_turn = chess.WHITE
                self._handle_turn()
            elif event == GameEvent.BLACK_TURN:
                self._current_turn = chess.BLACK
                self._handle_turn()
            elif event == GameEvent.RESIGN_GAME:
                self._game_manager.resign(1 if self._computer_color == chess.WHITE else 2)
            elif event == GameEvent.REQUEST_DRAW:
                self._game_manager.draw()
            elif event == GameEvent.GAME_OVER and termination:
                self._handle_game_over(termination)
        except Exception as e:
            log.error(f"[UCIEngine] Error handling game event: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_move(self, move: str):
        """Handle move completion."""
        try:
            log.info(f"[UCIEngine] Move completed: {move}")
            self._draw_board()
        except Exception as e:
            log.error(f"[UCIEngine] Error handling move: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_key_press(self, key: Key):
        """Handle key press events."""
        try:
            log.info(f"[UCIEngine] Key pressed: {key}")
            
            if key == Key.BACK:
                self.stop()
                sys.exit(0)
            elif key == Key.DOWN:
                # Disable graphs
                self._graphs_enabled = False
                image = Image.new('1', (128, 80), 255)
                epaper.drawImagePartial(0, 209, image)
                epaper.drawImagePartial(0, 1, image)
            elif key == Key.UP:
                # Enable graphs
                self._graphs_enabled = True
                if self._analysis_engine:
                    try:
                        info = self._analysis_engine.analyse(
                            self._game_manager.get_board(),
                            chess.engine.Limit(time=0.5)
                        )
                        self._draw_evaluation_graphs(info)
                    except Exception as e:
                        log.error(f"[UCIEngine] Error drawing graphs: {e}")
        except Exception as e:
            log.error(f"[UCIEngine] Error handling key press: {e}")
    
    def _on_takeback(self):
        """Handle takeback event."""
        try:
            log.info("[UCIEngine] Takeback detected")
            self._game_manager.clear_forced_move()
            board.ledsOff()
            
            # Switch turn back
            if self._current_turn == chess.WHITE:
                self._current_turn = chess.BLACK
                self._on_game_event(GameEvent.BLACK_TURN, None)
            else:
                self._current_turn = chess.WHITE
                self._on_game_event(GameEvent.WHITE_TURN, None)
        except Exception as e:
            log.error(f"[UCIEngine] Error handling takeback: {e}")
    
    def _handle_new_game(self):
        """Handle new game event."""
        log.info("[UCIEngine] Handling new game")
        
        self._game_manager.clear_forced_move()
        board.ledsOff()
        self._game_manager.get_board().reset()
        epaper.quickClear()
        self._score_history = []
        
        epaper.pauseEpaper()
        self._draw_board()
        
        if self._graphs_enabled and self._analysis_engine:
            try:
                info = self._analysis_engine.analyse(
                    self._game_manager.get_board(),
                    chess.engine.Limit(time=0.1)
                )
                self._draw_evaluation_graphs(info)
            except Exception as e:
                log.error(f"[UCIEngine] Error drawing initial graphs: {e}")
        
        epaper.unPauseEpaper()
    
    def _handle_turn(self):
        """Handle turn change event."""
        log.info(f"[UCIEngine] Handling turn: {'WHITE' if self._current_turn == chess.WHITE else 'BLACK'}")
        
        # Draw evaluation graphs if enabled
        if self._graphs_enabled and self._analysis_engine:
            try:
                info = self._analysis_engine.analyse(
                    self._game_manager.get_board(),
                    chess.engine.Limit(time=0.5)
                )
                epaper.pauseEpaper()
                self._draw_evaluation_graphs(info)
                epaper.unPauseEpaper()
            except Exception as e:
                log.error(f"[UCIEngine] Error drawing graphs: {e}")
        
        # Draw board
        self._draw_board()
        
        # Check if it's computer's turn
        if self._current_turn == self._computer_color:
            self._play_computer_move()
    
    def _play_computer_move(self):
        """Play computer's move."""
        if not self._play_engine:
            log.error("[UCIEngine] Play engine not available")
            return
        
        try:
            log.info(f"[UCIEngine] Computer's turn - calculating move from FEN: {self._game_manager.get_fen()}")
            
            # Configure engine options if needed
            if self._engine_options:
                self._play_engine.configure(self._engine_options)
            
            # Calculate move
            limit = chess.engine.Limit(time=5)
            result = self._play_engine.play(
                self._game_manager.get_board(),
                limit,
                info=chess.engine.INFO_ALL
            )
            
            move = result.move
            move_str = str(move)
            log.info(f"[UCIEngine] Engine returned move: {move_str}")
            
            # Set forced move in game manager
            self._game_manager.set_forced_move(move_str, forced=True)
            
        except Exception as e:
            log.error(f"[UCIEngine] Error playing computer move: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_game_over(self, termination: str):
        """Handle game over event."""
        log.info(f"[UCIEngine] Game over: {termination}")
        
        # Display termination message
        termination_text = termination.replace("Termination.", "")
        image = Image.new('1', (128, 12), 255)
        draw = ImageDraw.Draw(image)
        font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
        draw.text((30, 0), termination_text, font=font12, fill=0)
        epaper.drawImagePartial(0, 221, image)
        time.sleep(0.3)
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        epaper.drawImagePartial(0, 57, image)
        
        # Display end screen
        epaper.quickClear()
        image = Image.new('1', (128, 292), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
        
        # Get result
        result = self._game_manager.get_board().result()
        draw.text((0, 20), "          " + result, font=font18, fill=0)
        
        # Draw score history if available
        if len(self._score_history) > 0:
            draw.line([(0, 114), (128, 114)], fill=0, width=1)
            barwidth = min(128 / len(self._score_history), 8)
            baroffset = 0
            for score in self._score_history:
                col = 255 if score >= 0 else 0
                draw.rectangle([
                    (baroffset, 114),
                    (baroffset + barwidth, 114 - (score * 4))
                ], fill=col, outline='black')
                baroffset += barwidth
        
        epaper.drawImagePartial(0, 0, image)
        time.sleep(10)
        
        self.stop()
    
    def _draw_board(self):
        """Draw the current board state on the display."""
        try:
            fen = self._game_manager.get_fen()
            log.debug(f"[UCIEngine] Drawing board with FEN: {fen[:20]}...")
            
            # Parse FEN
            fen_parts = fen.split()
            fen_board = fen_parts[0].replace("/", "")
            fen_board = fen_board.replace("1", " ")
            fen_board = fen_board.replace("2", "  ")
            fen_board = fen_board.replace("3", "   ")
            fen_board = fen_board.replace("4", "    ")
            fen_board = fen_board.replace("5", "     ")
            fen_board = fen_board.replace("6", "      ")
            fen_board = fen_board.replace("7", "       ")
            fen_board = fen_board.replace("8", "        ")
            
            # Reorder for display (rank 8 to rank 1)
            nfen = ""
            for rank in range(8, 0, -1):
                for file in range(0, 8):
                    nfen += fen_board[((rank - 1) * 8) + file]
            
            # Draw board
            lboard = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(lboard)
            chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            for x in range(64):
                pos = (x - 63) * -1
                row = 16 * (pos // 8)
                col = (x % 8) * 16
                px = 0
                r = x // 8
                c = x % 8
                py = 0
                
                # Checkerboard pattern
                if (r // 2 == r / 2 and c // 2 == c / 2) or (r // 2 != r / 2 and c // 2 != c / 2):
                    py = 16
                
                # Piece sprites
                piece_char = nfen[x]
                piece_offsets = {
                    'P': 16, 'R': 32, 'N': 48, 'B': 64, 'Q': 80, 'K': 96,
                    'p': 112, 'r': 128, 'n': 144, 'b': 160, 'q': 176, 'k': 192
                }
                px = piece_offsets.get(piece_char, 0)
                
                if px > 0:
                    piece = chessfont.crop((px, py, px + 16, py + 16))
                    # Flip pieces if computer is white
                    if self._computer_color == chess.WHITE:
                        piece = piece.transpose(Image.FLIP_TOP_BOTTOM)
                        piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
                    lboard.paste(piece, (col, row))
            
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            epaper.drawImagePartial(0, 81, lboard)
            
        except Exception as e:
            log.error(f"[UCIEngine] Error drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_evaluation_graphs(self, info: dict):
        """Draw evaluation graphs on the display."""
        if not self._graphs_enabled:
            return
        
        if "score" not in info:
            return
        
        try:
            image = Image.new('1', (128, 80), 255)
            draw = ImageDraw.Draw(image)
            font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
            
            # Parse score
            score_str = str(info["score"])
            sval = 0.0
            
            if "Mate" in score_str:
                mate_str = score_str[13:24]
                mate_str = mate_str[1:mate_str.find(")")]
                sval = float(mate_str)
                sval = sval / 100
            else:
                cp_str = score_str[11:24]
                cp_str = cp_str[1:cp_str.find(")")]
                sval = float(cp_str) / 100
            
            if "BLACK" in score_str:
                sval = sval * -1
            
            # Draw evaluation text
            txt = f"{sval:5.1f}"
            if abs(sval) > 999:
                txt = ""
            if "Mate" in score_str:
                txt = f"Mate in {abs(sval * 100):2.0f}"
                sval = sval * 100000
            
            draw.text((50, 12), txt, font=font12, fill=0)
            draw.rectangle([(0, 1), (127, 11)], fill=None, outline='black')
            
            # Clamp score for display
            if sval > 12:
                sval = 12
            if sval < -12:
                sval = -12
            
            # Add to history
            if len(self._score_history) == 0:  # First move
                self._score_history.append(sval)
            else:
                self._score_history.append(sval)
            
            # Limit history size
            if len(self._score_history) > self._max_score_history:
                self._score_history.pop(0)
            
            # Draw indicator bar
            offset = (128 / 25) * (sval + 12)
            if offset < 128:
                draw.rectangle([(offset, 1), (127, 11)], fill=0, outline='black')
            
            # Draw bar chart
            if len(self._score_history) > 0:
                draw.line([(0, 50), (128, 50)], fill=0, width=1)
                barwidth = min(128 / len(self._score_history), 8)
                baroffset = 0
                for score in self._score_history:
                    col = 255 if score >= 0 else 0
                    y_calc = 50 - (score * 2)
                    y0 = min(50, y_calc)
                    y1 = max(50, y_calc)
                    draw.rectangle([
                        (baroffset, y0),
                        (baroffset + barwidth, y1)
                    ], fill=col, outline='black')
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
            
        except Exception as e:
            log.error(f"[UCIEngine] Error drawing evaluation graphs: {e}")
            import traceback
            traceback.print_exc()
    
    def _write_text(self, row: int, text: str):
        """Write text to a specific row on the display."""
        image = Image.new('1', (128, 20), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        draw.text((0, 0), text, font=font18, fill=0)
        epaper.drawImagePartial(0, (row * 20), image)
    
    def _is_starting_position(self, state) -> bool:
        """Check if board is in starting position."""
        STARTING_STATE = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')
        if state is None or len(state) != 64:
            return False
        return bytearray(state) == STARTING_STATE


def main():
    """Main entry point for UCI engine."""
    # Parse command line arguments
    player_color = sys.argv[1] if len(sys.argv) > 1 else "white"
    engine_name = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    engine_options_desc = sys.argv[3] if len(sys.argv) > 3 else "Default"
    
    # Create and run UCI engine
    uci = UCIEngine(player_color, engine_name, engine_options_desc)
    try:
        uci.run()
    except KeyboardInterrupt:
        log.info("\n>>> KeyboardInterrupt received")
        uci.stop()
    except Exception as e:
        log.error(f"[UCIEngine] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        uci.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()

