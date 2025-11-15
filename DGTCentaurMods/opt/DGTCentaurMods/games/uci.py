# Play pure UCI without DGT Centaur Adaptive Play
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

from DGTCentaurMods.games import manager
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log

import time
import chess
import chess.engine
import sys
import pathlib
import os
import threading
from random import randint
import configparser
from PIL import Image, ImageDraw, ImageFont
import signal


class UCIGame:
    """Manages a UCI chess game against an engine."""
    
    def __init__(self, player_color: str, engine_name: str, uci_options_desc: str = "Default"):
        self.player_color = player_color
        self.engine_name = engine_name
        self.uci_options_desc = uci_options_desc
        
        # Determine computer color
        if player_color == "white":
            self.computer_color = chess.BLACK
        elif player_color == "black":
            self.computer_color = chess.WHITE
        else:  # random
            self.computer_color = randint(0, 1)
        
        # Initialize engines
        self._initialize_engines()
        
        # Game state
        self.current_turn = chess.WHITE
        self.should_stop = False
        self.is_first_move = True
        self.graphs_enabled = self._should_enable_graphs()
        self.score_history = []
        self.last_event = None
        self.is_cleaned_up = False
        
        # UCI options
        self.uci_options = {}
        self._load_uci_options()
        
        # Set game info
        if self.computer_color == chess.BLACK:
            manager.setGameInfo(self.uci_options_desc, "", "", "Player", self.engine_name)
        else:
            manager.setGameInfo(self.uci_options_desc, "", "", self.engine_name, "Player")
    
    def _should_enable_graphs(self) -> bool:
        """Determine if evaluation graphs should be enabled based on hardware."""
        try:
            machine = os.uname().machine
            return machine == "armv7l"  # Pi Zero 2 W
        except:
            return False
    
    def _initialize_engines(self):
        """Initialize analysis and playing engines."""
        log.info(f"Engine name: {self.engine_name}")
        
        engine_path_name = f"engines/{self.engine_name}"
        ct800_path = "engines/ct800"
        
        # Get absolute paths
        base_path = pathlib.Path(__file__).parent.parent
        self.analysis_engine_path = str((base_path / ct800_path).resolve())
        self.playing_engine_path = str((base_path / engine_path_name).resolve())
        self.uci_file_path = self.playing_engine_path + ".uci"
        
        log.info(f"Analysis engine: {self.analysis_engine_path}")
        log.info(f"Playing engine: {self.playing_engine_path}")
        
        self.analysis_engine = chess.engine.SimpleEngine.popen_uci(
            self.analysis_engine_path,
            timeout=None
        )
        self.playing_engine = chess.engine.SimpleEngine.popen_uci(
            self.playing_engine_path
        )
        
        log.info(f"Analysis engine initialized: {self.analysis_engine}")
        log.info(f"Playing engine initialized: {self.playing_engine}")
    
    def _load_uci_options(self):
        """Load UCI options from configuration file."""
        if not os.path.exists(self.uci_file_path):
            log.warning(f"UCI file not found: {self.uci_file_path}, using Default settings")
            self.uci_options_desc = "Default"
            return
        
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(self.uci_file_path)
        
        if config.has_section(self.uci_options_desc):
            log.info(f"Loading UCI options from section: {self.uci_options_desc}")
            for key, value in config.items(self.uci_options_desc):
                self.uci_options[key] = value
            
            # Filter out non-UCI metadata fields
            non_uci_fields = ['Description']
            self.uci_options = {
                k: v for k, v in self.uci_options.items()
                if k not in non_uci_fields
            }
            log.info(f"UCI options: {self.uci_options}")
        else:
            log.warning(f"Section '{self.uci_options_desc}' not found, falling back to Default")
            if config.has_section("DEFAULT"):
                for key, value in config.items("DEFAULT"):
                    self.uci_options[key] = value
                non_uci_fields = ['Description']
                self.uci_options = {
                    k: v for k, v in self.uci_options.items()
                    if k not in non_uci_fields
                }
            self.uci_options_desc = "Default"
    
    def _cleanup_engines(self):
        """Safely cleanup engine processes."""
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
        
        try:
            cleanup_engine(self.analysis_engine, "analysis_engine")
        except:
            pass
        
        try:
            cleanup_engine(self.playing_engine, "playing_engine")
        except:
            pass
    
    def cleanup(self):
        """Clean up all resources."""
        if self.is_cleaned_up:
            return
        
        self.is_cleaned_up = True
        self.should_stop = True
        
        # Clean up engines
        self._cleanup_engines()
        
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
            manager.resetMoveState()
        except:
            pass
        
        try:
            manager.unsubscribeGame()
        except:
            pass
        
        try:
            board.cleanup(leds_off=True)
        except:
            pass
    
    def _handle_key_press(self, key):
        """Handle key press events."""
        log.info(f"Key event received: {key}")
        
        if key == board.Key.BACK:
            self.should_stop = True
        elif key == board.Key.DOWN:
            self._clear_evaluation_graphs()
            self.graphs_enabled = False
        elif key == board.Key.UP:
            self.graphs_enabled = True
            self.is_first_move = True
            board_obj = manager.getBoard()
            if board_obj is not None:
                info = self.analysis_engine.analyse(
                    board_obj,
                    chess.engine.Limit(time=0.5)
                )
                self._draw_evaluation_graphs(info)
    
    def _execute_computer_move(self, uci_move: str):
        """Execute the computer move by setting up LEDs and flags."""
        try:
            log.info(f"Setting up computer move: {uci_move}")
            board_obj = manager.getBoard()
            
            if board_obj is None:
                log.error("Cannot get board object")
                return
            
            log.info(f"Current FEN: {manager.getFEN()}")
            log.info(f"Legal moves: {[str(m) for m in list(board_obj.legal_moves)[:5]]}...")
            
            # Validate the move is legal
            move = chess.Move.from_uci(uci_move)
            if move not in board_obj.legal_moves:
                log.error(f"ERROR: Move {uci_move} is not legal!")
                log.error(f"Legal moves: {list(board_obj.legal_moves)}")
                raise ValueError(f"Illegal move: {uci_move}")
            
            # Use manager to set up forced move
            log.info(f"Setting up manager for forced move")
            manager.computerMove(uci_move)
            
            log.info("Computer move setup complete. Waiting for player to move pieces on board.")
        except Exception as e:
            log.error(f"Error in _execute_computer_move: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_game_event(self, event):
        """Handle game events from the manager."""
        log.info(f">>> eventCallback START: event={event}")
        
        if event == manager.EVENT_NEW_GAME:
            log.warning("!!! WARNING: NEW_GAME event triggered !!!")
            if self.last_event == manager.EVENT_NEW_GAME:
                log.warning("!!! SKIPPING: Consecutive NEW_GAME events - ignoring to prevent loop !!!")
                return
        
        self.last_event = event
        
        try:
            log.info(f"EventCallback triggered with event: {event}")
            
            if event == manager.EVENT_NEW_GAME:
                self._handle_new_game()
            elif event == manager.EVENT_WHITE_TURN:
                self._handle_white_turn()
            elif event == manager.EVENT_BLACK_TURN:
                self._handle_black_turn()
            elif event == manager.EVENT_RESIGN_GAME:
                manager.resignGame(self.computer_color + 1)
            elif isinstance(event, str) and event.startswith("Termination."):
                self._handle_game_termination(event)
        except Exception as e:
            log.error(f"Error in _handle_game_event: {e}")
            import traceback
            traceback.print_exc()
            try:
                epaper.unPauseEpaper()
            except:
                pass
    
    def _handle_new_game(self):
        """Handle new game event."""
        log.info("EVENT_NEW_GAME: Resetting board to starting position")
        manager.resetMoveState()
        board.ledsOff()
        manager.resetBoard()
        epaper.quickClear()
        
        self.score_history = []
        self.current_turn = chess.WHITE
        self.is_first_move = True
        
        epaper.pauseEpaper()
        self._draw_board(manager.getFEN())
        
        log.info(f"Board reset. FEN: {manager.getFEN()}")
        
        if self.graphs_enabled:
            board_obj = manager.getBoard()
            if board_obj is not None:
                info = self.analysis_engine.analyse(
                    board_obj,
                    chess.engine.Limit(time=0.1)
                )
                self._draw_evaluation_graphs(info)
        
        epaper.unPauseEpaper()
    
    def _handle_white_turn(self):
        """Handle white's turn."""
        self.current_turn = chess.WHITE
        log.info(f"WHITE_TURN event: current_turn={self.current_turn}, computer_color={self.computer_color}")
        
        if self.graphs_enabled:
            board_obj = manager.getBoard()
            if board_obj is not None:
                info = self.analysis_engine.analyse(
                    board_obj,
                    chess.engine.Limit(time=0.5)
                )
                epaper.pauseEpaper()
                self._draw_evaluation_graphs(info)
                epaper.unPauseEpaper()
        
        self._draw_board(manager.getFEN())
        
        if self.current_turn == self.computer_color:
            self._play_computer_move()
    
    def _handle_black_turn(self):
        """Handle black's turn."""
        self.current_turn = chess.BLACK
        log.info(f"BLACK_TURN event: current_turn={self.current_turn}, computer_color={self.computer_color}")
        
        if self.graphs_enabled:
            board_obj = manager.getBoard()
            if board_obj is not None:
                info = self.analysis_engine.analyse(
                    board_obj,
                    chess.engine.Limit(time=0.5)
                )
                epaper.pauseEpaper()
                self._draw_evaluation_graphs(info)
                epaper.unPauseEpaper()
        
        self._draw_board(manager.getFEN())
        
        if self.current_turn == self.computer_color:
            self._play_computer_move()
    
    def _play_computer_move(self):
        """Play the computer's move."""
        log.info(f"Computer's turn! Current FEN: {manager.getFEN()}")
        
        # Configure engine with UCI options
        if self.uci_options:
            log.info(f"Configuring engine with options: {self.uci_options}")
            self.playing_engine.configure(self.uci_options)
        
        limit = chess.engine.Limit(time=5)
        log.info(f"Asking engine to play from FEN: {manager.getFEN()}")
        
        try:
            board_obj = manager.getBoard()
            if board_obj is None:
                log.error("Cannot get board object for computer move")
                return
            
            result = self.playing_engine.play(
                board_obj,
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
    
    def _handle_game_termination(self, termination_event: str):
        """Handle game termination event."""
        termination_type = termination_event[12:]  # Remove "Termination." prefix
        
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
        self._draw_end_screen()
        time.sleep(10)
        self.should_stop = True
    
    def _draw_end_screen(self):
        """Draw the game over screen."""
        image = Image.new('1', (128, 292), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        
        draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
        result = manager.getResult()
        draw.text((0, 20), "          " + result, font=font18, fill=0)
        
        # Draw score history if available
        if len(self.score_history) > 0:
            log.info("Drawing score history")
            draw.line([(0, 114), (128, 114)], fill=0, width=1)
            bar_width = 128 / len(self.score_history)
            if bar_width > 8:
                bar_width = 8
            
            bar_offset = 0
            for score in self.score_history:
                color = 255 if score >= 0 else 0
                draw.rectangle(
                    [(bar_offset, 114), (bar_offset + bar_width, 114 - (score * 4))],
                    fill=color,
                    outline='black'
                )
                bar_offset += bar_width
        
        epaper.drawImagePartial(0, 0, image)
    
    def _handle_move(self, move_uci: str):
        """Handle a move made on the board."""
        try:
            log.info(f"moveCallback: Drawing board for move {move_uci}")
            self._draw_board(manager.getFEN())
            log.info("moveCallback: Board drawn successfully")
        except Exception as e:
            log.error(f"Error in _handle_move while drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_takeback(self):
        """Handle takeback event."""
        log.info("Takeback detected - clearing computer move setup")
        manager.resetMoveState()
        board.ledsOff()
        
        # Switch turn
        if self.current_turn == chess.WHITE:
            self.current_turn = chess.BLACK
        else:
            self.current_turn = chess.WHITE
        
        # Trigger appropriate turn event
        if self.current_turn == chess.BLACK:
            self._handle_game_event(manager.EVENT_BLACK_TURN)
        else:
            self._handle_game_event(manager.EVENT_WHITE_TURN)
    
    def _extract_score_value(self, score_info) -> float:
        """Extract score value from engine analysis info."""
        score_str = str(score_info["score"])
        
        if "Mate" in score_str:
            # Extract mate value
            mate_str = score_str[13:24]
            mate_str = mate_str[1:mate_str.find(")")]
            score_value = float(mate_str)
            score_value = score_value / 100
        else:
            # Extract centipawn value
            cp_str = score_str[11:24]
            cp_str = cp_str[1:cp_str.find(")")]
            score_value = float(cp_str)
            score_value = score_value / 100
        
        # Negate if black is winning
        if "BLACK" in score_str:
            score_value = score_value * -1
        
        return score_value
    
    def _draw_evaluation_graphs(self, info):
        """Draw evaluation graphs to the screen."""
        if "score" not in info:
            log.info("evaluationGraphs: No score in info, skipping")
            return
        
        if not self.graphs_enabled:
            self._clear_evaluation_graphs()
            return
        
        score_value = self._extract_score_value(info)
        
        # Draw evaluation bars
        image = Image.new('1', (128, 80), 255)
        draw = ImageDraw.Draw(image)
        font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
        
        # Format score text
        score_text = "{:5.1f}".format(score_value)
        if score_value > 999:
            score_text = ""
        
        score_str = str(info["score"])
        if "Mate" in score_str:
            mate_moves = abs(score_value * 100)
            score_text = "Mate in " + "{:2.0f}".format(mate_moves)
            score_value = score_value * 100000
        
        draw.text((50, 12), score_text, font=font12, fill=0)
        draw.rectangle([(0, 1), (127, 11)], fill=None, outline='black')
        
        # Calculate indicator position
        if score_value > 12:
            score_value = 12
        if score_value < -12:
            score_value = -12
        
        # Add to history
        if self.is_first_move == 0:
            self.score_history.append(score_value)
            # Limit history size to prevent memory leak
            MAX_HISTORY_SIZE = 200
            if len(self.score_history) > MAX_HISTORY_SIZE:
                self.score_history.pop(0)
        else:
            self.is_first_move = 0
        
        # Draw indicator
        offset = (128 / 25) * (score_value + 12)
        if offset < 128:
            draw.rectangle([(offset, 1), (127, 11)], fill=0, outline='black')
        
        # Draw bar chart
        if len(self.score_history) > 0:
            draw.line([(0, 50), (128, 50)], fill=0, width=1)
            bar_width = 128 / len(self.score_history)
            if bar_width > 8:
                bar_width = 8
            
            bar_offset = 0
            for score in self.score_history:
                color = 255 if score >= 0 else 0
                y_calc = 50 - (score * 2)
                y0 = min(50, y_calc)
                y1 = max(50, y_calc)
                draw.rectangle(
                    [(bar_offset, y0), (bar_offset + bar_width, y1)],
                    fill=color,
                    outline='black'
                )
                bar_offset += bar_width
        
        # Draw turn indicator
        tmp = image.copy()
        dr2 = ImageDraw.Draw(tmp)
        if self.current_turn == chess.WHITE:
            dr2.ellipse((119, 14, 126, 21), fill=0, outline=0)
        epaper.drawImagePartial(0, 209, tmp)
        
        if self.current_turn == chess.BLACK:
            draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
        
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        epaper.drawImagePartial(0, 1, image)
    
    def _clear_evaluation_graphs(self):
        """Clear evaluation graphs from screen."""
        image = Image.new('1', (128, 80), 255)
        epaper.drawImagePartial(0, 209, image)
        epaper.drawImagePartial(0, 1, image)
    
    def _write_text(self, row: int, text: str):
        """Write text on a given line number."""
        image = Image.new('1', (128, 20), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        draw.text((0, 0), text, font=font18, fill=0)
        epaper.drawImagePartial(0, (row * 20), image)
    
    def _draw_board(self, fen: str):
        """Draw the chess board from FEN string."""
        try:
            log.info(f"_draw_board: Starting to draw board with FEN: {fen[:20]}...")
            
            # Parse FEN - get only the position part (before first space)
            # FEN format: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            fen_str = str(fen)
            # Split by space and take only the position part (first part)
            position_part = fen_str.split()[0] if ' ' in fen_str else fen_str
            curfen = position_part.replace("/", "")
            curfen = curfen.replace("1", " ")
            curfen = curfen.replace("2", "  ")
            curfen = curfen.replace("3", "   ")
            curfen = curfen.replace("4", "    ")
            curfen = curfen.replace("5", "     ")
            curfen = curfen.replace("6", "      ")
            curfen = curfen.replace("7", "       ")
            curfen = curfen.replace("8", "        ")
            
            # Reorder for display (rank 8 to rank 1, matching original code)
            nfen = ""
            for rank in range(8, 0, -1):
                for file in range(0, 8):
                    nfen = nfen + curfen[((rank - 1) * 8) + file]
            
            # Draw board
            lboard = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(lboard)
            chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            # Create a gray dithering pattern for dark squares
            # Use a 2x2 checkerboard pattern to simulate gray in 1-bit mode
            gray_square = Image.new('1', (16, 16), 255)  # Start with white
            gray_draw = ImageDraw.Draw(gray_square)
            # Create a dithering pattern: alternate pixels in a checkerboard
            for i in range(0, 16, 2):
                for j in range(0, 16, 2):
                    # Create a 2x2 pattern: top-left and bottom-right black
                    gray_draw.point((i, j), 0)  # Black pixel
                    gray_draw.point((i+1, j+1), 0)  # Black pixel
                    # Leave (i+1, j) and (i, j+1) as white (255)
            
            for x in range(0, 64):
                pos = (x - 63) * -1
                row = (16 * (pos // 8))
                col = (x % 8) * 16
                px = 0
                r = x // 8
                c = x % 8
                py = 0
                
                # Determine if this is a dark square using checkerboard pattern
                # Dark square if (row + col) is odd
                is_dark_square = ((r + c) % 2 == 1)
                
                # Set py for sprite sheet row (py=0 for white squares, py=16 for gray squares)
                if is_dark_square:
                    py = 16
                    # Draw gray square background for dark squares using dithering pattern
                    lboard.paste(gray_square, (col, row))
                
                # Determine piece sprite
                piece_char = nfen[x]
                piece_x_offset = {
                    "P": 16, "R": 32, "N": 48, "B": 64, "Q": 80, "K": 96,
                    "p": 112, "r": 128, "n": 144, "b": 160, "q": 176, "k": 192
                }.get(piece_char, 0)
                
                if piece_char != " ":
                    piece = chessfont.crop((piece_x_offset, py, piece_x_offset + 16, py + 16))
                    if self.computer_color == chess.WHITE:
                        piece = piece.transpose(Image.FLIP_TOP_BOTTOM)
                        piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
                    lboard.paste(piece, (col, row))
            
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            epaper.drawImagePartial(0, 81, lboard)
        except Exception as e:
            log.error(f"Error in _draw_board: {e}")
            import traceback
            traceback.print_exc()
    
    def run(self):
        """Run the UCI game."""
        # Initialize epaper
        epaper.initEpaper()
        
        # Set initial turn
        self.current_turn = chess.WHITE
        
        # Subscribe to game manager
        manager.subscribeGame(
            self._handle_game_event,
            self._handle_move,
            self._handle_key_press,
            self._handle_takeback
        )
        log.info("Game manager subscribed")
        
        # Manually trigger game start for UCI mode
        log.info("Triggering NEW_GAME event")
        self._write_text(0, "Starting game...")
        self._write_text(1, "              ")
        time.sleep(1)
        self._handle_game_event(manager.EVENT_NEW_GAME)
        time.sleep(1)
        log.info("Game started, triggering initial turn")
        log.info("Triggering initial white turn")
        self._handle_game_event(manager.EVENT_WHITE_TURN)
        
        # Main loop
        try:
            while not self.should_stop:
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
            self.cleanup()
        finally:
            log.info(">>> Final cleanup")
            self.cleanup()


def cleanup_and_exit(signum=None, frame=None):
    """Clean up resources and exit gracefully."""
    global _uci_game_instance
    if _uci_game_instance is not None:
        _uci_game_instance.cleanup()
    log.info("Goodbye!")
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGINT, cleanup_and_exit)
try:
    signal.signal(signal.SIGTERM, cleanup_and_exit)
except Exception:
    pass


def main():
    """Main entry point for UCI game."""
    # Parse command line arguments
    player_color = sys.argv[1] if len(sys.argv) > 1 else "white"
    engine_name = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    uci_options_desc = sys.argv[3] if len(sys.argv) > 3 else "Default"
    
    global _uci_game_instance
    _uci_game_instance = UCIGame(player_color, engine_name, uci_options_desc)
    
    try:
        _uci_game_instance.run()
    except Exception as e:
        log.error(f"Error running UCI game: {e}")
        import traceback
        traceback.print_exc()
        _uci_game_instance.cleanup()


if __name__ == "__main__":
    main()

