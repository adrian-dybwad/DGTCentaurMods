"""
UCI engine interface for chess games.

Manages engine lifecycle, UI/display, and reacts to game events from GameManager.
"""

from DGTCentaurMods.games.manager import GameManager, GameEvent
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log
import chess
import chess.engine
import sys
import pathlib
import os
import threading
import signal
import time
import configparser
from random import randint
from PIL import Image, ImageDraw, ImageFont
from typing import Optional


class UCIEngine:
    """
    UCI engine interface for playing chess against an engine.
    
    Manages engine lifecycle, display updates, and reacts to game events.
    """
    
    def __init__(self, player_color: str, engine_name: str, uci_options_desc: Optional[str] = None):
        """
        Initialize UCI engine interface.
        
        Args:
            player_color: 'white', 'black', or 'random' for player's color
            engine_name: Name of the engine executable
            uci_options_desc: Optional UCI options description/section name
        """
        # Determine player and computer colors
        if player_color == "white":
            self._computer_color = chess.BLACK  # Computer plays black
            self._player_color = chess.WHITE
        elif player_color == "black":
            self._computer_color = chess.WHITE  # Computer plays white
            self._player_color = chess.BLACK
        elif player_color == "random":
            self._computer_color = randint(0, 1)
            self._player_color = not self._computer_color
        else:
            self._computer_color = chess.BLACK
            self._player_color = chess.WHITE
        
        self._engine_name = engine_name
        self._uci_options_desc = uci_options_desc or "Default"
        
        # Engine instances
        self._analysis_engine: Optional[chess.engine.SimpleEngine] = None
        self._play_engine: Optional[chess.engine.SimpleEngine] = None
        
        # Game manager
        self._manager = GameManager()
        
        # State
        self._kill = False
        self._current_turn = chess.WHITE
        self._uci_options = {}
        self._score_history = []
        self._graphs_enabled = os.uname().machine == "armv7l"  # Enable on Pi Zero 2W
        self._first_move = True
        
        # Cleanup flag
        self._cleaned_up = False
        
        # Initialize engines
        self._initialize_engines()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._cleanup_and_exit)
        try:
            signal.signal(signal.SIGTERM, self._cleanup_and_exit)
        except Exception:
            pass
        
        # Subscribe to game manager events
        self._manager.subscribe_event(self._on_game_event)
        self._manager.subscribe_move(self._on_move)
        self._manager.subscribe_key(self._on_key)
        
        # Initialize display
        epaper.initEpaper()
    
    def _initialize_engines(self):
        """Initialize chess engines."""
        # Engine paths
        base_path = pathlib.Path(__file__).parent.parent
        ct800_path = str((base_path / "engines" / "ct800").resolve())
        engine_path = str((base_path / "engines" / self._engine_name).resolve())
        uci_file_path = engine_path + ".uci"
        
        log.info(f"Analysis engine: {ct800_path}")
        log.info(f"Play engine: {engine_path}")
        
        # Initialize analysis engine (for evaluation graphs)
        try:
            self._analysis_engine = chess.engine.SimpleEngine.popen_uci(ct800_path, timeout=None)
        except Exception as e:
            log.error(f"Error initializing analysis engine: {e}")
        
        # Initialize play engine
        try:
            self._play_engine = chess.engine.SimpleEngine.popen_uci(engine_path)
        except Exception as e:
            log.error(f"Error initializing play engine: {e}")
            raise
        
        # Load UCI options
        self._load_uci_options(uci_file_path)
        
        # Set game info
        if self._computer_color == chess.WHITE:
            self._manager.set_game_info(
                event=self._uci_options_desc,
                white=self._engine_name,
                black="Player"
            )
        else:
            self._manager.set_game_info(
                event=self._uci_options_desc,
                white="Player",
                black=self._engine_name
            )
    
    def _load_uci_options(self, uci_file_path: str):
        """Load UCI options from file."""
        if not os.path.exists(uci_file_path):
            log.warning(f"UCI file not found: {uci_file_path}, using default settings")
            return
        
        try:
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(uci_file_path)
            
            if config.has_section(self._uci_options_desc):
                for item in config.items(self._uci_options_desc):
                    self._uci_options[item[0]] = item[1]
            elif config.has_section("DEFAULT"):
                for item in config.items("DEFAULT"):
                    self._uci_options[item[0]] = item[1]
                self._uci_options_desc = "Default"
            
            # Filter out non-UCI metadata fields
            NON_UCI_FIELDS = ['Description']
            self._uci_options = {k: v for k, v in self._uci_options.items() if k not in NON_UCI_FIELDS}
            
            log.info(f"Loaded UCI options: {self._uci_options}")
        except Exception as e:
            log.error(f"Error loading UCI options: {e}")
    
    def _on_game_event(self, event: GameEvent):
        """Handle game events from manager."""
        try:
            if event == GameEvent.NEW_GAME:
                log.info("NEW_GAME event received")
                self._handle_new_game()
            elif event == GameEvent.WHITE_TURN:
                self._current_turn = chess.WHITE
                log.info(f"WHITE_TURN event: current_turn={self._current_turn}, computer_color={self._computer_color}")
                self._handle_turn_change()
            elif event == GameEvent.BLACK_TURN:
                self._current_turn = chess.BLACK
                log.info(f"BLACK_TURN event: current_turn={self._current_turn}, computer_color={self._computer_color}")
                self._handle_turn_change()
            elif event == GameEvent.GAME_OVER:
                self._handle_game_over()
            elif event == GameEvent.TAKEBACK:
                self._handle_takeback()
        except Exception as e:
            log.error(f"Error handling game event: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_move(self, move: str):
        """Handle move events from manager."""
        try:
            log.info(f"Move made: {move}")
            self._draw_board()
        except Exception as e:
            log.error(f"Error handling move: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_key(self, key: board.Key):
        """Handle key press events."""
        try:
            log.info(f"Key pressed: {key}")
            if key == board.Key.BACK:
                self._kill = True
            elif key == board.Key.DOWN:
                self._graphs_enabled = False
                self._clear_graphs()
            elif key == board.Key.UP:
                self._graphs_enabled = True
                self._first_move = True
                if self._analysis_engine:
                    info = self._analysis_engine.analyse(
                        self._manager.get_board(),
                        chess.engine.Limit(time=0.5)
                    )
                    self._draw_evaluation_graphs(info)
        except Exception as e:
            log.error(f"Error handling key: {e}")
    
    def _handle_new_game(self):
        """Handle new game event."""
        log.info("Handling new game")
        self._manager.reset_move_state()
        board.ledsOff()
        self._manager.reset_move_state()
        epaper.quickClear()
        self._score_history = []
        self._current_turn = chess.WHITE
        self._first_move = True
        self._draw_board()
        
        if self._graphs_enabled and self._analysis_engine:
            try:
                info = self._analysis_engine.analyse(
                    self._manager.get_board(),
                    chess.engine.Limit(time=0.1)
                )
                self._draw_evaluation_graphs(info)
            except Exception as e:
                log.error(f"Error drawing initial evaluation: {e}")
    
    def _handle_turn_change(self):
        """Handle turn change event."""
        self._draw_board()
        
        # Draw evaluation graphs if enabled
        if self._graphs_enabled and self._analysis_engine:
            try:
                info = self._analysis_engine.analyse(
                    self._manager.get_board(),
                    chess.engine.Limit(time=0.5)
                )
                epaper.pauseEpaper()
                self._draw_evaluation_graphs(info)
                epaper.unPauseEpaper()
            except Exception as e:
                log.error(f"Error drawing evaluation: {e}")
        
        # Check if it's computer's turn
        if self._current_turn == self._computer_color:
            self._make_computer_move()
    
    def _handle_game_over(self):
        """Handle game over event."""
        log.info("Game over")
        result = self._manager.get_board().result()
        
        # Display termination message
        outcome = self._manager.get_board().outcome(claim_draw=True)
        if outcome:
            termination = str(outcome.termination)
            self._display_termination(termination)
        
        # Display end screen
        self._display_end_screen(result)
        
        # Wait before exiting
        time.sleep(10)
        self._kill = True
    
    def _handle_takeback(self):
        """Handle takeback event."""
        log.info("Takeback detected")
        self._manager.reset_move_state()
        board.ledsOff()
        
        # Update turn
        if self._current_turn == chess.WHITE:
            self._current_turn = chess.BLACK
        else:
            self._current_turn = chess.WHITE
        
        # Trigger turn event
        if self._current_turn == chess.WHITE:
            self._on_game_event(GameEvent.WHITE_TURN)
        else:
            self._on_game_event(GameEvent.BLACK_TURN)
    
    def _make_computer_move(self):
        """Make computer's move."""
        if not self._play_engine:
            log.error("Play engine not available")
            return
        
        try:
            log.info(f"Computer's turn! Current FEN: {self._manager.get_fen()}")
            
            # Configure engine with UCI options
            if self._uci_options:
                self._play_engine.configure(self._uci_options)
            
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
            
            # Set forced move for player to execute
            self._manager.set_forced_move(move_str, forced=True)
            
        except Exception as e:
            log.error(f"Error making computer move: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_board(self):
        """Draw the current board state on the display."""
        try:
            fen = self._manager.get_fen()
            log.debug(f"Drawing board with FEN: {fen[:20]}...")
            
            # Parse FEN
            fen_parts = fen.split()
            board_fen = fen_parts[0]
            
            # Convert FEN to display format
            board_fen = board_fen.replace("/", "")
            for i in range(1, 9):
                board_fen = board_fen.replace(str(i), " " * i)
            
            # Rotate board for display (rank 8 at top)
            nfen = ""
            for rank in range(8, 0, -1):
                for file in range(8):
                    idx = ((rank - 1) * 8) + file
                    nfen += board_fen[idx]
            
            # Draw board
            board_img = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(board_img)
            chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            for square_idx in range(64):
                pos = (square_idx - 63) * -1
                row = 16 * (pos // 8)
                col = (square_idx % 8) * 16
                
                # Calculate sprite position
                r = square_idx // 8
                c = square_idx % 8
                px = 0
                py = 0
                
                # Checkerboard pattern
                if (r // 2 == r / 2 and c // 2 == c / 2) or (r // 2 != r / 2 and c // 2 != c / 2):
                    py = 16
                
                # Piece sprite offset
                piece_char = nfen[square_idx]
                piece_offsets = {
                    'P': 16, 'R': 32, 'N': 48, 'B': 64, 'Q': 80, 'K': 96,
                    'p': 112, 'r': 128, 'n': 144, 'b': 160, 'q': 176, 'k': 192
                }
                px = piece_offsets.get(piece_char, 0)
                
                # Draw piece
                if px > 0:
                    piece = chessfont.crop((px, py, px + 16, py + 16))
                    if self._computer_color == chess.WHITE:
                        piece = piece.transpose(Image.FLIP_TOP_BOTTOM)
                        piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
                    board_img.paste(piece, (col, row))
            
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            epaper.drawImagePartial(0, 81, board_img)
            
        except Exception as e:
            log.error(f"Error drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_evaluation_graphs(self, info):
        """Draw evaluation graphs."""
        if not self._graphs_enabled:
            return
        
        try:
            if "score" not in info:
                return
            
            # Parse score
            score_str = str(info["score"])
            score_val = 0
            
            if "Mate" in score_str:
                mate_str = score_str[13:24]
                mate_str = mate_str[1:mate_str.find(")")]
                score_val = float(mate_str)
                score_val = score_val * 100000
            else:
                score_str_val = score_str[11:24]
                score_str_val = score_str_val[1:score_str_val.find(")")]
                score_val = float(score_str_val)
                score_val = score_val / 100
            
            if "BLACK" in score_str:
                score_val = score_val * -1
            
            # Add to history
            if not self._first_move:
                self._score_history.append(score_val)
                if len(self._score_history) > 200:
                    self._score_history.pop(0)
            else:
                self._first_move = False
            
            # Draw graphs
            image = Image.new('1', (128, 80), 255)
            draw = ImageDraw.Draw(image)
            font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
            
            # Score text
            txt = "{:5.1f}".format(score_val)
            if score_val > 999:
                txt = ""
            if "Mate" in score_str:
                txt = "Mate in " + "{:2.0f}".format(abs(score_val / 100000))
            
            draw.text((50, 12), txt, font=font12, fill=0)
            draw.rectangle([(0, 1), (127, 11)], fill=None, outline='black')
            
            # Score indicator
            clamped_score = max(-12, min(12, score_val))
            offset = (128 / 25) * (clamped_score + 12)
            if offset < 128:
                draw.rectangle([(offset, 1), (127, 11)], fill=0, outline='black')
            
            # Bar chart
            if len(self._score_history) > 0:
                draw.line([(0, 50), (128, 50)], fill=0, width=1)
                barwidth = min(8, 128 / len(self._score_history))
                baroffset = 0
                for score in self._score_history:
                    y_calc = 50 - (score * 2)
                    y0 = min(50, y_calc)
                    y1 = max(50, y_calc)
                    col = 255 if score >= 0 else 0
                    draw.rectangle([(baroffset, y0), (baroffset + barwidth, y1)], fill=col, outline='black')
                    baroffset += barwidth
            
            # Turn indicator
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
    
    def _clear_graphs(self):
        """Clear evaluation graphs."""
        image = Image.new('1', (128, 80), 255)
        epaper.drawImagePartial(0, 209, image)
        epaper.drawImagePartial(0, 1, image)
    
    def _display_termination(self, termination: str):
        """Display game termination message."""
        try:
            termination_text = termination[12:] if termination.startswith("Termination.") else termination
            
            image = Image.new('1', (128, 12), 255)
            draw = ImageDraw.Draw(image)
            font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
            draw.text((30, 0), termination_text, font=font12, fill=0)
            epaper.drawImagePartial(0, 221, image)
            time.sleep(0.3)
            image = image.transpose(Image.FLIP_TOP_BOTTOM)
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
            epaper.drawImagePartial(0, 57, image)
            epaper.quickClear()
        except Exception as e:
            log.error(f"Error displaying termination: {e}")
    
    def _display_end_screen(self, result: str):
        """Display end game screen."""
        try:
            image = Image.new('1', (128, 292), 255)
            draw = ImageDraw.Draw(image)
            font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
            
            draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
            draw.text((0, 20), "          " + result, font=font18, fill=0)
            
            # Score history graph
            if len(self._score_history) > 0:
                draw.line([(0, 114), (128, 114)], fill=0, width=1)
                barwidth = min(8, 128 / len(self._score_history))
                baroffset = 0
                for score in self._score_history:
                    col = 255 if score >= 0 else 0
                    y_calc = 114 - (score * 4)
                    y0 = min(114, y_calc)
                    y1 = max(114, y_calc)
                    draw.rectangle([(baroffset, y0), (baroffset + barwidth, y1)], fill=col, outline='black')
                    baroffset += barwidth
            
            epaper.drawImagePartial(0, 0, image)
        except Exception as e:
            log.error(f"Error displaying end screen: {e}")
    
    def _cleanup_engines(self):
        """Clean up engine processes."""
        def cleanup_engine(engine, name):
            """Safely quit an engine."""
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
            except Exception as e:
                log.warning(f"Error cleaning up {name}: {e}")
        
        cleanup_engine(self._analysis_engine, "analysis_engine")
        cleanup_engine(self._play_engine, "play_engine")
    
    def _cleanup_and_exit(self, signum=None, frame=None):
        """Clean up resources and exit gracefully."""
        if self._cleaned_up:
            os._exit(0)
        
        log.info(">>> Cleaning up and exiting...")
        self._kill = True
        self._cleaned_up = True
        
        try:
            self._cleanup_engines()
            board.ledsOff()
            board.unPauseEvents()
            self._manager.reset_move_state()
            self._manager.stop()
            board.cleanup(leds_off=True)
        except KeyboardInterrupt:
            log.warning(">>> Interrupted during cleanup, forcing exit")
            os._exit(1)
        except Exception as e:
            log.warning(f">>> Error during cleanup: {e}")
        
        log.info("Goodbye!")
        sys.exit(0)
    
    def run(self):
        """Run the UCI engine interface."""
        try:
            # Start game manager
            self._manager.start()
            
            # Check for starting position and trigger new game if needed
            current_state = bytearray(board.getChessState())
            starting_state = bytearray(
                b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
                b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
            )
            if bytearray(current_state) == starting_state:
                log.info("Starting position detected, triggering new game")
                self._on_game_event(GameEvent.NEW_GAME)
                time.sleep(0.5)
                self._on_game_event(GameEvent.WHITE_TURN)
            
            # Main loop
            while not self._kill:
                time.sleep(0.1)
        
        except KeyboardInterrupt:
            log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
            self._cleanup_and_exit()
        except Exception as e:
            log.error(f"Error in main loop: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._cleanup_and_exit()


def main():
    """Main entry point."""
    # Parse arguments (same as original uci.py)
    player_color = sys.argv[1] if len(sys.argv) > 1 else "white"
    engine_name = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    uci_options_desc = sys.argv[3] if len(sys.argv) > 3 else None
    
    log.info(f"Starting UCI engine: player={player_color}, engine={engine_name}, options={uci_options_desc}")
    
    uci = UCIEngine(player_color, engine_name, uci_options_desc)
    uci.run()


if __name__ == "__main__":
    main()

