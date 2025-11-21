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
from DGTCentaurMods.epaper import Manager, ChessBoardWidget, GameAnalysisWidget
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
        
        # Display manager and widgets
        self.display_manager = None
        self.chess_board_widget = None
        self.game_analysis_top = None
        self.game_analysis_bottom = None
        
        # Set game info
        if self.computer_color == chess.BLACK:
            manager.setGameInfo(self.uci_options_desc, "", "", "Player", self.engine_name)
        else:
            manager.setGameInfo(self.uci_options_desc, "", "", self.engine_name, "Player")
    
    def _init_display(self):
        """Initialize display manager and widgets."""
        self.display_manager = Manager()
        self.display_manager.init()
        
        # Create chess board widget at y=81 (matching current top=81)
        # Start with initial position
        initial_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        self.chess_board_widget = ChessBoardWidget(0, 81, initial_fen)
        self.display_manager.add_widget(self.chess_board_widget)
        
        # Create game analysis widget at top (y=1) and bottom (y=209)
        # Top widget for current evaluation
        self.game_analysis_top = GameAnalysisWidget(0, 1, 128, 80)
        self.display_manager.add_widget(self.game_analysis_top)
        
        # Bottom widget for flipped evaluation
        self.game_analysis_bottom = GameAnalysisWidget(0, 209, 128, 80)
        self.display_manager.add_widget(self.game_analysis_bottom)
        
        # Initial display update
        self.display_manager.update(full=True).result(timeout=10.0)
    
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
        
        # Clean up display
        try:
            if self.display_manager:
                # Remove widgets
                if self.chess_board_widget and self.chess_board_widget in self.display_manager._widgets:
                    self.display_manager._widgets.remove(self.chess_board_widget)
                if self.game_analysis_top and self.game_analysis_top in self.display_manager._widgets:
                    self.display_manager._widgets.remove(self.game_analysis_top)
                if self.game_analysis_bottom and self.game_analysis_bottom in self.display_manager._widgets:
                    self.display_manager._widgets.remove(self.game_analysis_bottom)
                self.display_manager.shutdown()
        except Exception as e:
            log.error(f"Error cleaning up display: {e}")
        
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
    
    def _handle_new_game(self):
        """Handle new game event."""
        log.info("EVENT_NEW_GAME: Resetting board to starting position")
        manager.resetMoveState()
        board.ledsOff()
        manager.resetBoard()
        
        # Clear screen by resetting widgets
        if self.chess_board_widget:
            self.chess_board_widget.set_fen(manager.getFEN())
        if self.game_analysis_top:
            self.game_analysis_top.clear_history()
            self.game_analysis_top.set_score(0.0, "0.0")
        if self.game_analysis_bottom:
            self.game_analysis_bottom.clear_history()
            self.game_analysis_bottom.set_score(0.0, "0.0")
        if self.display_manager:
            self.display_manager.update(full=True).result(timeout=10.0)
        
        self.score_history = []
        self.current_turn = chess.WHITE
        self.is_first_move = True
        
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
                self._draw_evaluation_graphs(info)
        
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
                self._draw_evaluation_graphs(info)
        
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
        
        # Draw to framebuffer directly
        if self.display_manager:
            canvas = self.display_manager._framebuffer.get_canvas()
            canvas.paste(image, (0, 221))
            self.display_manager.update(full=False).result(timeout=5.0)
            time.sleep(0.3)
            
            image = image.transpose(Image.FLIP_TOP_BOTTOM)
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
            canvas.paste(image, (0, 57))
            self.display_manager.update(full=False).result(timeout=5.0)
        
        # Clear screen by resetting widgets
        if self.chess_board_widget:
            self.chess_board_widget.set_fen(manager.getFEN())
        if self.game_analysis_top:
            self.game_analysis_top.clear_history()
            self.game_analysis_top.set_score(0.0, "0.0")
        if self.game_analysis_bottom:
            self.game_analysis_bottom.clear_history()
            self.game_analysis_bottom.set_score(0.0, "0.0")
        if self.display_manager:
            self.display_manager.update(full=True).result(timeout=10.0)
        
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
                    outline=0
                )
                bar_offset += bar_width
        
        # Draw to framebuffer directly
        if self.display_manager:
            canvas = self.display_manager._framebuffer.get_canvas()
            canvas.paste(image, (0, 0))
            self.display_manager.update(full=True).result(timeout=10.0)
    
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
        
        # Format score text
        score_text = "{:5.1f}".format(score_value)
        if score_value > 999:
            score_text = ""
        
        score_str = str(info["score"])
        if "Mate" in score_str:
            mate_moves = abs(score_value * 100)
            score_text = "Mate in " + "{:2.0f}".format(mate_moves)
            score_value = score_value * 100000
        
        # Clamp score for display
        display_score = score_value
        if display_score > 12:
            display_score = 12
        if display_score < -12:
            display_score = -12
        
        # Add to history
        if self.is_first_move == 0:
            self.score_history.append(display_score)
            # Limit history size to prevent memory leak
            MAX_HISTORY_SIZE = 200
            if len(self.score_history) > MAX_HISTORY_SIZE:
                self.score_history.pop(0)
        else:
            self.is_first_move = 0
        
        # Update top widget (normal orientation)
        if self.game_analysis_top:
            self.game_analysis_top.set_score(display_score, score_text)
            turn_str = "white" if self.current_turn == chess.WHITE else "black"
            self.game_analysis_top.set_turn(turn_str)
        
        # Update bottom widget (flipped orientation)
        if self.game_analysis_bottom:
            # For bottom widget, flip the score and turn
            flipped_score = -display_score
            flipped_turn = "black" if self.current_turn == chess.WHITE else "white"
            self.game_analysis_bottom.set_score(flipped_score, score_text)
            self.game_analysis_bottom.set_turn(flipped_turn)
        
        # Sync history to widgets (only add new score, don't rebuild entire history)
        # The widgets maintain their own history, we just need to add the new score
        if self.is_first_move == 0:
            if self.game_analysis_top:
                self.game_analysis_top.add_score_to_history(display_score)
            if self.game_analysis_bottom:
                self.game_analysis_bottom.add_score_to_history(-display_score)
        
        # Update display
        if self.display_manager:
            self.display_manager.update(full=False).result(timeout=5.0)
    
    def _clear_evaluation_graphs(self):
        """Clear evaluation graphs from screen."""
        if self.game_analysis_top:
            self.game_analysis_top.clear_history()
            self.game_analysis_top.set_score(0.0, "0.0")
        if self.game_analysis_bottom:
            self.game_analysis_bottom.clear_history()
            self.game_analysis_bottom.set_score(0.0, "0.0")
        if self.display_manager:
            self.display_manager.update(full=False).result(timeout=5.0)
    
    def _write_text(self, row: int, text: str):
        """Write text on a given line number."""
        # Text display is handled by widgets, skip for now
        # This was only used for "Starting game..." message
        pass
    
    def _draw_board(self, fen: str):
        """Draw the chess board from FEN string."""
        try:
            if self.chess_board_widget and self.display_manager:
                self.chess_board_widget.set_fen(fen)
                self.display_manager.update(full=False).result(timeout=5.0)
        except Exception as e:
            log.error(f"Error in _draw_board: {e}")
            import traceback
            traceback.print_exc()
    
    def run(self):
        """Run the UCI game."""
        # Initialize display
        self._init_display()
        
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

