"""
UCI chess engine interface with event-driven architecture.

Reacts to game events, manages engine lifecycle, handles UI/display,
and coordinates between the game manager and chess engines.

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
import time
import threading
import pathlib
import configparser
from random import randint
from typing import Optional

import chess
import chess.engine
from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.games.manager import GameManager, GameEvent
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log

# Constants
MAX_SCOREHISTORY_SIZE = 200


class UCIEngine:
    """
    Manages UCI chess engine lifecycle and move calculation.
    
    Handles engine startup, configuration, move calculation, and cleanup.
    """
    
    def __init__(self, engine_path: str, analysis_engine_path: Optional[str] = None):
        """
        Initialize UCI engine.
        
        Args:
            engine_path: Path to main chess engine executable
            analysis_engine_path: Optional path to analysis engine (for evaluation graphs)
        """
        self._engine_path = engine_path
        self._analysis_engine_path = analysis_engine_path
        self._engine: Optional[chess.engine.SimpleEngine] = None
        self._analysis_engine: Optional[chess.engine.SimpleEngine] = None
        self._uci_options = {}
        self._cleaned_up = False
    
    def start(self, uci_options: dict = None):
        """
        Start the engines.
        
        Args:
            uci_options: Dictionary of UCI options to configure
        """
        if uci_options:
            self._uci_options = uci_options
        
        try:
            log.info(f"Starting engine: {self._engine_path}")
            self._engine = chess.engine.SimpleEngine.popen_uci(self._engine_path)
            
            if self._uci_options:
                log.info(f"Configuring engine with options: {self._uci_options}")
                self._engine.configure(self._uci_options)
            
            if self._analysis_engine_path:
                log.info(f"Starting analysis engine: {self._analysis_engine_path}")
                self._analysis_engine = chess.engine.SimpleEngine.popen_uci(
                    self._analysis_engine_path, timeout=None
                )
        except Exception as e:
            log.error(f"Error starting engine: {e}")
            raise
    
    def calculate_move(self, board_state: chess.Board, time_limit: float = 5.0) -> Optional[chess.Move]:
        """
        Calculate the best move for the current position.
        
        Args:
            board_state: Current chess board state
            time_limit: Time limit in seconds for move calculation
        
        Returns:
            Best move or None if calculation fails
        """
        if not self._engine:
            log.error("Engine not started")
            return None
        
        try:
            limit = chess.engine.Limit(time=time_limit)
            result = self._engine.play(board_state, limit, info=chess.engine.INFO_ALL)
            return result.move
        except Exception as e:
            log.error(f"Error calculating move: {e}")
            return None
    
    def analyze(self, board_state: chess.Board, time_limit: float = 0.5) -> Optional[dict]:
        """
        Analyze the current position for evaluation.
        
        Args:
            board_state: Current chess board state
            time_limit: Time limit in seconds for analysis
        
        Returns:
            Analysis info dict or None if analysis fails
        """
        engine = self._analysis_engine if self._analysis_engine else self._engine
        if not engine:
            return None
        
        try:
            limit = chess.engine.Limit(time=time_limit)
            info = engine.analyse(board_state, limit)
            return info
        except Exception as e:
            log.error(f"Error analyzing position: {e}")
            return None
    
    def cleanup(self):
        """Clean up engines safely."""
        if self._cleaned_up:
            return
        
        self._cleaned_up = True
        
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
                    except KeyboardInterrupt:
                        quit_error.append("KeyboardInterrupt")
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
                    except:
                        try:
                            if hasattr(engine, 'transport') and hasattr(engine.transport, 'proc'):
                                engine.transport.proc.kill()
                            elif hasattr(engine, 'proc'):
                                engine.proc.kill()
                        except:
                            pass
                elif quit_error:
                    log.debug(f"{name} quit() raised: {quit_error[0]}")
            except KeyboardInterrupt:
                log.warning(f"{name} interrupted during cleanup setup")
            except Exception as e:
                log.warning(f"Error cleaning up {name}: {e}")
        
        cleanup_engine(self._engine, "engine")
        cleanup_engine(self._analysis_engine, "analysis_engine")


class UCIGame:
    """
    Main UCI game controller.
    
    Coordinates between game manager, engines, and display.
    """
    
    def __init__(self, player_color: str, engine_name: str, uci_options_desc: str = "Default"):
        """
        Initialize UCI game.
        
        Args:
            player_color: "white", "black", or "random"
            engine_name: Name of engine executable (without path)
            uci_options_desc: Description/section name for UCI options
        """
        # Determine computer color
        if player_color == "white":
            self._computer_color = chess.BLACK
        elif player_color == "black":
            self._computer_color = chess.WHITE
        else:  # random
            self._computer_color = randint(0, 1)
        
        # Setup engine paths
        engine_dir = pathlib.Path(__file__).parent.parent / "engines"
        ct800_path = str((engine_dir / "ct800").resolve())
        engine_path = str((engine_dir / engine_name).resolve())
        uci_file_path = engine_path + ".uci"
        
        log.info(f"Engine path: {engine_path}")
        log.info(f"Analysis engine path: {ct800_path}")
        log.info(f"UCI options file: {uci_file_path}")
        
        # Load UCI options
        uci_options = {}
        if os.path.exists(uci_file_path):
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(uci_file_path)
            
            section = uci_options_desc if config.has_section(uci_options_desc) else "Default"
            if config.has_section(section):
                for key, value in config.items(section):
                    if key != 'Description':
                        uci_options[key] = value
                log.info(f"Loaded UCI options from section '{section}': {uci_options}")
            else:
                log.warning(f"Section '{uci_options_desc}' not found, using Default")
        
        # Initialize components
        self._game_manager = GameManager()
        self._engine = UCIEngine(engine_path, ct800_path)
        self._engine.start(uci_options)
        
        # Game state
        self._kill_event = threading.Event()
        self._current_turn = chess.WHITE
        self._graphs_enabled = os.uname().machine == "armv7l"  # Enable on Pi Zero 2W
        self._score_history = []
        self._first_move = True
        
        # Setup game info
        white_name = "Player" if self._computer_color == chess.BLACK else engine_name
        black_name = engine_name if self._computer_color == chess.BLACK else "Player"
        self._game_manager.set_game_info(
            source="uci",
            event=uci_options_desc,
            white=white_name,
            black=black_name
        )
        
        # Subscribe to events
        self._game_manager.subscribe_event(self._on_game_event)
        self._game_manager.subscribe_move(self._on_move)
        self._game_manager.subscribe_key(self._on_key)
        self._game_manager.subscribe_takeback(self._on_takeback)
        
        # Initialize display
        epaper.initEpaper()
    
    def _on_game_event(self, event: GameEvent, data: dict):
        """Handle game events."""
        try:
            log.info(f"[UCIGame] Event: {event}, data: {data}")
            
            if event == GameEvent.NEW_GAME:
                self._handle_new_game()
            elif event == GameEvent.WHITE_TURN:
                self._handle_turn(chess.WHITE)
            elif event == GameEvent.BLACK_TURN:
                self._handle_turn(chess.BLACK)
            elif event == GameEvent.GAME_OVER:
                self._handle_game_over(data)
            elif event == GameEvent.RESIGN:
                self._handle_resign(data)
            elif event == GameEvent.REQUEST_DRAW:
                self._handle_draw()
        
        except Exception as e:
            log.error(f"[UCIGame] Error handling game event: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_new_game(self):
        """Handle new game event."""
        log.info("[UCIGame] New game started")
        self._score_history = []
        self._first_move = True
        self._current_turn = chess.WHITE
        
        epaper.quickClear()
        epaper.pauseEpaper()
        self._draw_board(self._game_manager.get_fen())
        
        if self._graphs_enabled:
            info = self._engine.analyze(self._game_manager.get_board(), time_limit=0.1)
            if info:
                self._draw_evaluation_graphs(info)
        
        epaper.unPauseEpaper()
    
    def _handle_turn(self, turn: chess.Color):
        """Handle turn change event."""
        self._current_turn = turn
        log.info(f"[UCIGame] Turn: {'White' if turn == chess.WHITE else 'Black'}")
        
        # Draw board
        self._draw_board(self._game_manager.get_fen())
        
        # Show evaluation graphs if enabled
        if self._graphs_enabled:
            info = self._engine.analyze(self._game_manager.get_board(), time_limit=0.5)
            if info:
                epaper.pauseEpaper()
                self._draw_evaluation_graphs(info)
                epaper.unPauseEpaper()
        
        # If it's the computer's turn, calculate and set move
        if turn == self._computer_color:
            log.info("[UCIGame] Computer's turn - calculating move")
            move = self._engine.calculate_move(self._game_manager.get_board(), time_limit=5.0)
            if move:
                uci_move = move.uci()
                log.info(f"[UCIGame] Computer move: {uci_move}")
                self._game_manager.set_forced_move(uci_move, forced=True)
            else:
                log.error("[UCIGame] Failed to calculate move")
    
    def _handle_game_over(self, data: dict):
        """Handle game over event."""
        termination = data.get('termination', 'Unknown')
        result = data.get('result', 'Unknown')
        
        log.info(f"[UCIGame] Game over: {termination}, result: {result}")
        
        # Display termination message
        image = Image.new('1', (128, 12), 255)
        draw = ImageDraw.Draw(image)
        font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
        txt = termination.replace("Termination.", "")
        draw.text((30, 0), txt, font=font12, fill=0)
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
                baroffset += barwidth
        
        epaper.drawImagePartial(0, 0, image)
        time.sleep(10)
        
        self._kill_event.set()
    
    def _handle_resign(self, data: dict):
        """Handle resignation."""
        result = data.get('result', 'Unknown')
        log.info(f"[UCIGame] Resignation: {result}")
        self._kill_event.set()
    
    def _handle_draw(self):
        """Handle draw offer/acceptance."""
        log.info("[UCIGame] Draw")
        self._kill_event.set()
    
    def _on_move(self, move: str):
        """Handle move event."""
        log.info(f"[UCIGame] Move made: {move}")
        self._draw_board(self._game_manager.get_fen())
    
    def _on_key(self, key: board.Key):
        """Handle key press event."""
        log.info(f"[UCIGame] Key pressed: {key}")
        
        if key == board.Key.BACK:
            self._kill_event.set()
        elif key == board.Key.DOWN:
            # Disable graphs
            self._graphs_enabled = False
            image = Image.new('1', (128, 80), 255)
            epaper.drawImagePartial(0, 209, image)
            epaper.drawImagePartial(0, 1, image)
        elif key == board.Key.UP:
            # Enable graphs
            self._graphs_enabled = True
            self._first_move = True
            info = self._engine.analyze(self._game_manager.get_board(), time_limit=0.5)
            if info:
                self._draw_evaluation_graphs(info)
    
    def _on_takeback(self):
        """Handle takeback event."""
        log.info("[UCIGame] Takeback detected")
        self._game_manager.clear_forced_move()
        board.ledsOff()
        
        # Switch turn and trigger appropriate event
        if self._current_turn == chess.WHITE:
            self._current_turn = chess.BLACK
            self._handle_turn(chess.BLACK)
        else:
            self._current_turn = chess.WHITE
            self._handle_turn(chess.WHITE)
    
    def _draw_board(self, fen: str):
        """
        Draw the chess board on the display.
        
        Args:
            fen: FEN string representing the board position
        """
        try:
            log.info(f"[UCIGame] Drawing board with FEN: {fen[:20]}...")
            
            # Parse FEN
            curfen = str(fen).split()[0]  # Get only position part
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
                    nfen += curfen[((rank - 1) * 8) + file]
            
            # Draw board
            lboard = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(lboard)
            chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            for x in range(64):
                pos = (x - 63) * -1
                row = (16 * (pos // 8))
                col = (x % 8) * 16
                px = 0
                r = x // 8
                c = x % 8
                py = 0
                
                # Determine square color
                if (r // 2 == r / 2 and c // 2 == c / 2) or (r // 2 != r / 2 and c // 2 != c / 2):
                    py += 16
                
                # Map piece to sprite position
                piece = nfen[x]
                piece_map = {
                    'P': 16, 'R': 32, 'N': 48, 'B': 64, 'Q': 80, 'K': 96,
                    'p': 112, 'r': 128, 'n': 144, 'b': 160, 'q': 176, 'k': 192
                }
                px = piece_map.get(piece, 0)
                
                if px > 0:
                    piece_img = chessfont.crop((px, py, px + 16, py + 16))
                    if self._computer_color == chess.WHITE:
                        piece_img = piece_img.transpose(Image.FLIP_TOP_BOTTOM)
                        piece_img = piece_img.transpose(Image.FLIP_LEFT_RIGHT)
                    lboard.paste(piece_img, (col, row))
            
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            epaper.drawImagePartial(0, 81, lboard)
        
        except Exception as e:
            log.error(f"[UCIGame] Error drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_evaluation_graphs(self, info: dict):
        """
        Draw evaluation graphs on the display.
        
        Args:
            info: Analysis info from engine
        """
        if "score" not in info:
            return
        
        if not self._graphs_enabled:
            image = Image.new('1', (128, 80), 255)
            epaper.drawImagePartial(0, 209, image)
            epaper.drawImagePartial(0, 1, image)
            return
        
        # Parse score
        sc = str(info["score"])
        sval = 0
        
        if "Mate" in sc:
            sval = sc[13:24]
            sval = sval[1:sval.find(")")]
        else:
            sval = sc[11:24]
            sval = sval[1:sval.find(")")]
        
        sval = float(sval)
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
                draw.rectangle([(baroffset, y0), (baroffset + barwidth, y1)], fill=col, outline='black')
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
    
    def run(self):
        """Run the UCI game."""
        log.info("[UCIGame] Starting UCI game")
        
        # Start game manager
        self._game_manager.start()
        
        # Check for starting position and trigger new game if needed
        current_state = bytearray(board.getChessState())
        starting_state = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')
        
        if bytearray(current_state) == starting_state:
            log.info("[UCIGame] Starting position detected, triggering new game")
            self._game_manager.reset_game()
        
        # Main loop
        try:
            while not self._kill_event.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
            self._kill_event.set()
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources."""
        log.info("[UCIGame] Cleaning up")
        
        try:
            board.ledsOff()
        except:
            pass
        
        try:
            board.unPauseEvents()
        except:
            pass
        
        try:
            self._game_manager.clear_forced_move()
        except:
            pass
        
        try:
            self._game_manager.stop()
        except:
            pass
        
        try:
            self._engine.cleanup()
        except:
            pass
        
        try:
            board.cleanup(leds_off=True)
        except:
            pass
        
        log.info("[UCIGame] Cleanup complete")


def cleanup_and_exit(signum=None, frame=None):
    """Signal handler for graceful exit."""
    log.info(">>> Cleaning up and exiting...")
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
    uci_options_desc = sys.argv[3] if len(sys.argv) > 3 else "Default"
    
    log.info(f"Player color: {player_color}")
    log.info(f"Engine: {engine_name}")
    log.info(f"UCI options: {uci_options_desc}")
    
    # Create and run game
    game = UCIGame(player_color, engine_name, uci_options_desc)
    
    try:
        game.run()
    except KeyboardInterrupt:
        log.info("\n>>> Interrupted, cleaning up...")
    except Exception as e:
        log.error(f"Error running game: {e}")
        import traceback
        traceback.print_exc()
    finally:
        game.cleanup()
        log.info("Goodbye!")


if __name__ == "__main__":
    main()

