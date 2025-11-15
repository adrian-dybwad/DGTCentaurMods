"""
UCI engine integration for playing chess games.

This module provides a clean interface for playing chess games using UCI engines
without DGT Centaur Adaptive Play.

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
import signal
import time
import threading
import pathlib
import configparser
from random import randint
from typing import Optional, Dict, Any
from PIL import Image, ImageDraw, ImageFont

import chess
import chess.engine

from DGTCentaurMods.games.manager import GameManager, GameEvent
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log


class UCIEngineConfig:
    """Manages UCI engine configuration."""
    
    NON_UCI_FIELDS = ['Description']
    
    def __init__(self, uci_file_path: str, section_name: str = "Default"):
        """
        Initialize UCI engine configuration.
        
        Args:
            uci_file_path: Path to UCI configuration file
            section_name: Section name in config file (default: "Default")
        """
        self.uci_file_path = uci_file_path
        self.section_name = section_name
        self.options: Dict[str, str] = {}
        self._load_config()
    
    def _load_config(self):
        """Load configuration from UCI file."""
        if not os.path.exists(self.uci_file_path):
            log.warning(f"UCI file not found: {self.uci_file_path}, using Default settings")
            self.section_name = "Default"
            return
        
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(self.uci_file_path)
        
        if config.has_section(self.section_name):
            log.info(f"Loading UCI options from section '{self.section_name}'")
            for item in config.items(self.section_name):
                self.options[item[0]] = item[1]
            
            # Filter out non-UCI metadata fields
            self.options = {
                k: v for k, v in self.options.items() 
                if k not in self.NON_UCI_FIELDS
            }
            log.info(f"UCI options: {self.options}")
        else:
            log.warning(
                f"Section '{self.section_name}' not found in {self.uci_file_path}, "
                f"falling back to Default"
            )
            if config.has_section("DEFAULT"):
                for item in config.items("DEFAULT"):
                    self.options[item[0]] = item[1]
                self.options = {
                    k: v for k, v in self.options.items() 
                    if k not in self.NON_UCI_FIELDS
                }
            self.section_name = "Default"


class EngineManager:
    """Manages UCI engine instances."""
    
    def __init__(self, analysis_engine_path: str, play_engine_path: str):
        """
        Initialize engine manager.
        
        Args:
            analysis_engine_path: Path to analysis engine executable
            play_engine_path: Path to playing engine executable
        """
        self.analysis_engine_path = analysis_engine_path
        self.play_engine_path = play_engine_path
        self.analysis_engine: Optional[chess.engine.SimpleEngine] = None
        self.play_engine: Optional[chess.engine.SimpleEngine] = None
        self._initialize_engines()
    
    def _initialize_engines(self):
        """Initialize both engine instances."""
        log.info(f"Initializing analysis engine: {self.analysis_engine_path}")
        self.analysis_engine = chess.engine.SimpleEngine.popen_uci(
            self.analysis_engine_path, 
            timeout=None
        )
        
        log.info(f"Initializing play engine: {self.play_engine_path}")
        self.play_engine = chess.engine.SimpleEngine.popen_uci(
            self.play_engine_path
        )
        
        log.info(f"Analysis engine: {self.analysis_engine}")
        log.info(f"Play engine: {self.play_engine}")
    
    def cleanup(self):
        """Clean up engine resources."""
        self._cleanup_engine(self.analysis_engine, "analysis_engine")
        self._cleanup_engine(self.play_engine, "play_engine")
    
    def _cleanup_engine(
        self, 
        engine: Optional[chess.engine.SimpleEngine], 
        name: str
    ):
        """
        Safely quit an engine, with fallback to terminate/kill if needed.
        
        Args:
            engine: Engine instance to clean up
            name: Name for logging purposes
        """
        if engine is None:
            return
        
        try:
            # Try graceful quit with timeout using threading to avoid blocking
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
            thread.join(timeout=1.0)  # Wait max 1 second
            
            if not quit_done.is_set() or thread.is_alive():
                # Force terminate if graceful quit didn't work
                log.warning(f"{name} quit() timed out, attempting to kill process")
                thread.join(timeout=0.1)
                # Try to access the underlying process
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


class ScoreHistory:
    """Manages evaluation score history for graphs."""
    
    MAX_SIZE = 200
    
    def __init__(self):
        """Initialize score history."""
        self.scores: list = []
    
    def add(self, score: float):
        """Add a score to history, maintaining max size."""
        self.scores.append(score)
        if len(self.scores) > self.MAX_SIZE:
            self.scores.pop(0)
    
    def clear(self):
        """Clear all scores."""
        self.scores = []
    
    def get_all(self) -> list:
        """Get all scores."""
        return self.scores


class BoardRenderer:
    """Handles board rendering to epaper display."""
    
    def __init__(self, computer_side: int):
        """
        Initialize board renderer.
        
        Args:
            computer_side: 0 for black, 1 for white
        """
        self.computer_side = computer_side
    
    def draw_board(self, fen: str):
        """
        Draw chess board from FEN string.
        
        Args:
            fen: FEN string representing board position
        """
        try:
            log.info(f"drawBoardLocal: Starting to draw board with FEN: {fen[:20]}...")
            curfen = str(fen)
            curfen = curfen.replace("/", "")
            curfen = curfen.replace("1", " ")
            curfen = curfen.replace("2", "  ")
            curfen = curfen.replace("3", "   ")
            curfen = curfen.replace("4", "    ")
            curfen = curfen.replace("5", "     ")
            curfen = curfen.replace("6", "      ")
            curfen = curfen.replace("7", "       ")
            curfen = curfen.replace("8", "        ")
            
            nfen = ""
            for row in range(8, 0, -1):
                for col in range(0, 8):
                    nfen = nfen + curfen[((row - 1) * 8) + col]
            
            lboard = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(lboard)
            chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            for x in range(0, 64):
                pos = (x - 63) * -1
                row_pos = (16 * (pos // 8))
                col_pos = (x % 8) * 16
                px = 0
                r = x // 8
                c = x % 8
                py = 0
                
                # Determine square color
                if (r // 2 == r / 2 and c // 2 == c / 2):
                    py = py + 16
                if (r // 2 != r / 2 and c // 2 == c / 2):
                    py = py + 16
                
                # Determine piece sprite position
                piece_map = {
                    "P": 16, "R": 32, "N": 48, "B": 64, "Q": 80, "K": 96,
                    "p": 112, "r": 128, "n": 144, "b": 160, "q": 176, "k": 192
                }
                px = piece_map.get(nfen[x], 0)
                
                piece = chessfont.crop((px, py, px+16, py+16))
                if self.computer_side == 1:
                    piece = piece.transpose(Image.FLIP_TOP_BOTTOM)
                    piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
                
                lboard.paste(piece, (col_pos, row_pos))
            
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            epaper.drawImagePartial(0, 81, lboard)
        except Exception as e:
            log.error(f"Error in drawBoardLocal: {e}")
            import traceback
            traceback.print_exc()


class EvaluationGraphRenderer:
    """Handles evaluation graph rendering."""
    
    def __init__(self, score_history: ScoreHistory):
        """
        Initialize evaluation graph renderer.
        
        Args:
            score_history: Score history instance
        """
        self.score_history = score_history
        self.is_first_move = True
    
    def render(self, info: Dict[str, Any], current_turn: int, graphs_enabled: bool):
        """
        Draw evaluation graphs to the screen.
        
        Args:
            info: Engine analysis info dictionary
            current_turn: Current turn (0=black, 1=white)
            graphs_enabled: Whether graphs are enabled
        """
        if "score" not in info:
            log.info("evaluationGraphs: No score in info, skipping")
            return
        
        if not graphs_enabled:
            image = Image.new('1', (128, 80), 255)
            epaper.drawImagePartial(0, 209, image)
            epaper.drawImagePartial(0, 1, image)
            return
        
        # Parse score
        score_str = str(info["score"])
        score_value = 0
        
        if "Mate" in score_str:
            mate_str = score_str[13:24]
            mate_str = mate_str[1:mate_str.find(")")]
            score_value = float(mate_str)
        else:
            score_str_clean = score_str[11:24]
            score_str_clean = score_str_clean[1:score_str_clean.find(")")]
            score_value = float(score_str_clean)
        
        score_value = score_value / 100
        if "BLACK" in score_str:
            score_value = score_value * -1
        
        # Draw evaluation bars
        image = Image.new('1', (128, 80), 255)
        draw = ImageDraw.Draw(image)
        font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
        
        text = "{:5.1f}".format(score_value)
        if score_value > 999:
            text = ""
        if "Mate" in score_str:
            text = "Mate in " + "{:2.0f}".format(abs(score_value * 100))
            score_value = score_value * 100000
        
        draw.text((50, 12), text, font=font12, fill=0)
        draw.rectangle([(0, 1), (127, 11)], fill=None, outline='black')
        
        # Calculate indicator position
        if score_value > 12:
            score_value = 12
        if score_value < -12:
            score_value = -12
        
        if not self.is_first_move:
            self.score_history.add(score_value)
        else:
            self.is_first_move = False
        
        offset = (128 / 25) * (score_value + 12)
        if offset < 128:
            draw.rectangle([(offset, 1), (127, 11)], fill=0, outline='black')
        
        # Bar chart view
        if len(self.score_history.scores) > 0:
            draw.line([(0, 50), (128, 50)], fill=0, width=1)
            bar_width = 128 / len(self.score_history.scores)
            if bar_width > 8:
                bar_width = 8
            
            bar_offset = 0
            for score in self.score_history.scores:
                color = 255 if score >= 0 else 0
                y_calc = 50 - (score * 2)
                y0 = min(50, y_calc)
                y1 = max(50, y_calc)
                draw.rectangle(
                    [(bar_offset, y0), (bar_offset + bar_width, y1)],
                    fill=color,
                    outline='black'
                )
                bar_offset = bar_offset + bar_width
        
        tmp = image.copy()
        dr2 = ImageDraw.Draw(tmp)
        if current_turn == 1:
            dr2.ellipse((119, 14, 126, 21), fill=0, outline=0)
        epaper.drawImagePartial(0, 209, tmp)
        
        if current_turn == 0:
            draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
        
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        epaper.drawImagePartial(0, 1, image)


class UCIEngine:
    """
    Main UCI engine game manager.
    
    Manages a chess game using UCI engines for computer play.
    """
    
    def __init__(
        self, 
        player_color: str = "white",
        engine_name: str = "stockfish_pi",
        uci_options_section: str = "Default"
    ):
        """
        Initialize UCI engine game.
        
        Args:
            player_color: "white", "black", or "random" for player color
            engine_name: Name of engine to use
            uci_options_section: Section name in UCI config file
        """
        # Determine computer side
        if player_color == "white":
            self.computer_side = 0  # Player is white, computer is black
        elif player_color == "black":
            self.computer_side = 1  # Player is black, computer is white
        else:  # random
            self.computer_side = randint(0, 1)
        
        # Setup paths
        base_path = pathlib.Path(__file__).parent.parent
        ct800_path = base_path / "engines" / "ct800"
        engine_path = base_path / "engines" / engine_name
        uci_file_path = str(engine_path) + ".uci"
        
        log.info(f"Engine name: {engine_name}")
        log.info(f"Analysis engine path: {ct800_path}")
        log.info(f"Play engine path: {engine_path}")
        log.info(f"UCI file path: {uci_file_path}")
        
        # Initialize components
        self.engine_manager = EngineManager(
            str(ct800_path.resolve()),
            str(engine_path.resolve())
        )
        self.uci_config = UCIEngineConfig(uci_file_path, uci_options_section)
        self.game_manager = GameManager()
        self.score_history = ScoreHistory()
        self.board_renderer = BoardRenderer(self.computer_side)
        self.graph_renderer = EvaluationGraphRenderer(self.score_history)
        
        # Game state
        self.current_turn = 1  # 1 = white, 0 = black
        self.should_stop = False
        self.graphs_enabled = os.uname().machine == "armv7l"  # Enable for Pi Zero 2W
        self.last_event: Optional[GameEvent] = None
        self.is_cleaned_up = False
        
        # Setup game info
        if self.computer_side == 0:
            self.game_manager.set_game_info(
                self.uci_config.section_name, "", "", "Player", engine_name
            )
        else:
            self.game_manager.set_game_info(
                self.uci_config.section_name, "", "", engine_name, "Player"
            )
        
        # Register signal handlers
        signal.signal(signal.SIGINT, self._cleanup_and_exit)
        try:
            signal.signal(signal.SIGTERM, self._cleanup_and_exit)
        except Exception:
            pass
    
    def _cleanup_and_exit(self, signum=None, frame=None):
        """Clean up resources and exit gracefully."""
        if self.is_cleaned_up:
            os._exit(0)
        
        log.info(">>> Cleaning up and exiting...")
        self.should_stop = True
        try:
            self._cleanup()
        except KeyboardInterrupt:
            log.warning(">>> Interrupted during cleanup, forcing exit")
            os._exit(1)
        except Exception as e:
            log.warning(f">>> Error during cleanup: {e}")
        log.info("Goodbye!")
        sys.exit(0)
    
    def _cleanup(self):
        """Perform cleanup operations."""
        if self.is_cleaned_up:
            return
        self.is_cleaned_up = True
        
        # Clean up engines
        self.engine_manager.cleanup()
        
        # Clean up board
        try:
            board.ledsOff()
        except:
            pass
        
        try:
            board.unPauseEvents()
        except:
            pass
        
        try:
            self.game_manager.reset_move_state()
        except:
            pass
        
        try:
            self.game_manager.unsubscribe_game()
        except:
            pass
        
        try:
            board.cleanup(leds_off=True)
        except:
            pass
    
    def _handle_key_callback(self, key):
        """Handle key press events."""
        log.info("Key event received: " + str(key))
        if key == board.Key.BACK:
            self.should_stop = True
        elif key == board.Key.DOWN:
            self.graphs_enabled = False
            image = Image.new('1', (128, 80), 255)
            epaper.drawImagePartial(0, 209, image)
            epaper.drawImagePartial(0, 1, image)
        elif key == board.Key.UP:
            self.graphs_enabled = True
            self.graph_renderer.is_first_move = True
            info = self.engine_manager.analysis_engine.analyse(
                self.game_manager.get_board(), 
                chess.engine.Limit(time=0.5)
            )
            self.graph_renderer.render(info, self.current_turn, self.graphs_enabled)
    
    def _execute_computer_move(self, move_uci: str):
        """
        Execute the computer move by setting up LEDs and flags.
        
        Args:
            move_uci: Move in UCI format
        """
        try:
            log.info(f"Setting up computer move: {move_uci}")
            board_obj = self.game_manager.get_board()
            log.info(f"Current FEN: {self.game_manager.get_fen()}")
            log.info(f"Legal moves: {[str(m) for m in list(board_obj.legal_moves)[:5]]}...")
            
            # Validate the move is legal
            move = chess.Move.from_uci(move_uci)
            if move not in board_obj.legal_moves:
                log.error(f"ERROR: Move {move_uci} is not legal! This should not happen.")
                log.error(f"Legal moves: {list(board_obj.legal_moves)}")
                raise ValueError(f"Illegal move: {move_uci}")
            
            # Use game manager to handle LED setup and state management
            log.info("Setting up game manager for forced move")
            self.game_manager.computer_move(move_uci)
            
            log.info("Computer move setup complete. Waiting for player to move pieces on board.")
        except Exception as e:
            log.error(f"Error in executeComputerMove: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_event_callback(self, event):
        """Handle game event callbacks."""
        log.info(f">>> eventCallback START: event={event}")
        
        # Prevent duplicate NEW_GAME events
        if event == GameEvent.NEW_GAME:
            log.warning("!!! WARNING: NEW_GAME event triggered !!!")
            if self.last_event == GameEvent.NEW_GAME:
                log.warning("!!! SKIPPING: Consecutive NEW_GAME events - ignoring to prevent loop !!!")
                return
        self.last_event = event
        
        try:
            log.info(f"EventCallback triggered with event: {event}")
            
            if event == GameEvent.NEW_GAME:
                log.info("EVENT_NEW_GAME: Resetting board to starting position")
                log.info("Clearing pending computer move setup")
                self.game_manager.reset_move_state()
                board.ledsOff()
                self.game_manager.reset_board()
                epaper.quickClear()
                self.score_history.clear()
                self.current_turn = 1
                self.graph_renderer.is_first_move = True
                
                epaper.pauseEpaper()
                self.board_renderer.draw_board(self.game_manager.get_fen())
                log.info(f"Board reset. FEN: {self.game_manager.get_fen()}")
                
                if self.graphs_enabled:
                    info = self.engine_manager.analysis_engine.analyse(
                        self.game_manager.get_board(), 
                        chess.engine.Limit(time=0.1)
                    )
                    self.graph_renderer.render(info, self.current_turn, self.graphs_enabled)
                
                epaper.unPauseEpaper()
            
            elif event == GameEvent.WHITE_TURN:
                self.current_turn = 1
                log.info(f"WHITE_TURN event: current_turn={self.current_turn}, computer_side={self.computer_side}")
                
                if self.graphs_enabled:
                    info = self.engine_manager.analysis_engine.analyse(
                        self.game_manager.get_board(), 
                        chess.engine.Limit(time=0.5)
                    )
                    epaper.pauseEpaper()
                    self.graph_renderer.render(info, self.current_turn, self.graphs_enabled)
                    epaper.unPauseEpaper()
                
                self.board_renderer.draw_board(self.game_manager.get_fen())
                
                if self.current_turn == self.computer_side:
                    self._play_computer_move()
            
            elif event == GameEvent.BLACK_TURN:
                self.current_turn = 0
                log.info(f"BLACK_TURN event: current_turn={self.current_turn}, computer_side={self.computer_side}")
                
                if self.graphs_enabled:
                    info = self.engine_manager.analysis_engine.analyse(
                        self.game_manager.get_board(), 
                        chess.engine.Limit(time=0.5)
                    )
                    epaper.pauseEpaper()
                    self.graph_renderer.render(info, self.current_turn, self.graphs_enabled)
                    epaper.unPauseEpaper()
                
                self.board_renderer.draw_board(self.game_manager.get_fen())
                
                if self.current_turn == self.computer_side:
                    self._play_computer_move()
            
            elif event == GameEvent.RESIGN_GAME:
                self.game_manager.resign_game(self.computer_side + 1)
            
            elif isinstance(event, str) and event.startswith("Termination."):
                self._handle_game_termination(event)
        
        except Exception as e:
            log.error(f"Error in eventCallback: {e}")
            import traceback
            traceback.print_exc()
            try:
                epaper.unPauseEpaper()
            except:
                pass
    
    def _play_computer_move(self):
        """Play a move using the UCI engine."""
        log.info(f"Computer's turn! Current FEN: {self.game_manager.get_fen()}")
        
        # Configure engine with UCI options
        if self.uci_config.options:
            log.info(f"Configuring engine with options: {self.uci_config.options}")
            self.engine_manager.play_engine.configure(self.uci_config.options)
        
        limit = chess.engine.Limit(time=5)
        log.info(f"Asking engine to play from FEN: {self.game_manager.get_fen()}")
        
        try:
            result = self.engine_manager.play_engine.play(
                self.game_manager.get_board(), 
                limit, 
                info=chess.engine.INFO_ALL
            )
            log.info(f"Engine returned: {result}")
            move = result.move
            log.info(f"Move extracted: {move}")
            log.info(f"Executing move: {str(move)}")
            self._execute_computer_move(str(move))
        except Exception as e:
            log.error(f"Error in computer move: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_game_termination(self, termination: str):
        """Handle game termination event."""
        # Display termination message
        image = Image.new('1', (128, 12), 255)
        draw = ImageDraw.Draw(image)
        font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
        txt = termination[12:]
        draw.text((30, 0), txt, font=font12, fill=0)
        epaper.drawImagePartial(0, 221, image)
        time.sleep(0.3)
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        epaper.drawImagePartial(0, 57, image)
        epaper.quickClear()
        
        # Display end screen
        log.info("displaying end screen")
        image = Image.new('1', (128, 292), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
        draw.text((0, 20), "          " + self.game_manager.get_result(), font=font18, fill=0)
        
        # Draw score history graph if available
        if len(self.score_history.scores) > 0:
            log.info("there be history")
            draw.line([(0, 114), (128, 114)], fill=0, width=1)
            bar_width = 128 / len(self.score_history.scores)
            if bar_width > 8:
                bar_width = 8
            
            bar_offset = 0
            for score in self.score_history.scores:
                color = 255 if score >= 0 else 0
                draw.rectangle(
                    [(bar_offset, 114), (bar_offset + bar_width, 114 - (score * 4))],
                    fill=color,
                    outline='black'
                )
                bar_offset = bar_offset + bar_width
        
        log.info("drawing")
        epaper.drawImagePartial(0, 0, image)
        time.sleep(10)
        self.should_stop = True
    
    def _handle_move_callback(self, move: str):
        """Handle move callback."""
        try:
            log.info(f"moveCallback: Drawing board for move {move}")
            self.board_renderer.draw_board(self.game_manager.get_fen())
            log.info("moveCallback: Board drawn successfully")
        except Exception as e:
            log.error(f"Error in moveCallback while drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_takeback_callback(self):
        """Handle takeback callback."""
        log.info("Takeback detected - clearing computer move setup")
        self.game_manager.reset_move_state()
        board.ledsOff()
        
        # Switch turn
        self.current_turn = 1 if self.current_turn == 0 else 0
        
        # Trigger appropriate turn event
        if self.current_turn == 0:
            self._handle_event_callback(GameEvent.BLACK_TURN)
        else:
            self._handle_event_callback(GameEvent.WHITE_TURN)
    
    def run(self):
        """Run the UCI engine game."""
        # Activate the epaper
        epaper.initEpaper()
        
        # Set initial turn
        self.current_turn = 1
        
        # Subscribe to game manager
        self.game_manager.subscribe_game(
            self._handle_event_callback,
            self._handle_move_callback,
            self._handle_key_callback,
            self._handle_takeback_callback
        )
        log.info("Game manager subscribed")
        
        # Manually trigger game start for UCI mode
        log.info("Triggering NEW_GAME event")
        self._write_text(0, "Starting game...")
        self._write_text(1, "              ")
        time.sleep(1)
        self._handle_event_callback(GameEvent.NEW_GAME)
        time.sleep(1)
        log.info("Game started, triggering initial turn")
        log.info("Triggering initial white turn")
        self._handle_event_callback(GameEvent.WHITE_TURN)
        
        try:
            while not self.should_stop:
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
            self._cleanup_and_exit()
        finally:
            log.info(">>> Final cleanup")
            self._cleanup()
    
    def _write_text(self, row: int, text: str):
        """Write text on a given line number."""
        image = Image.new('1', (128, 20), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        draw.text((0, 0), text, font=font18, fill=0)
        epaper.drawImagePartial(0, (row * 20), image)


def main():
    """Main entry point for UCI engine game."""
    # Parse command line arguments
    player_color = sys.argv[1] if len(sys.argv) > 1 else "white"
    engine_name = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    uci_options_section = sys.argv[3] if len(sys.argv) > 3 else "Default"
    
    # Create and run UCI engine
    uci_engine = UCIEngine(player_color, engine_name, uci_options_section)
    uci_engine.run()


if __name__ == "__main__":
    main()

