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
from DGTCentaurMods.epaper import ChessBoardWidget, GameAnalysisWidget, SplashScreen, GameOverWidget
from DGTCentaurMods.board import *
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
import signal
from concurrent.futures import Future

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
        self.last_event = None
        self.is_cleaned_up = False
        
        # UCI options
        self.uci_options = {}
        self._load_uci_options()
        
        self.chess_board_widget = None
        self.game_analysis = None
        
        # Set game info
        if self.computer_color == chess.BLACK:
            manager.setGameInfo(self.uci_options_desc, "", "", "Player", self.engine_name)
        else:
            manager.setGameInfo(self.uci_options_desc, "", "", self.engine_name, "Player")
    
    def _init_display(self):
        
        # Create chess board widget at y=16 (below status bar)
        # Start with initial position
        self.chess_board_widget = ChessBoardWidget(0, 16, manager.STARTING_FEN)
        board.display_manager.add_widget(self.chess_board_widget)
        
        # Determine bottom color based on board orientation
        # If board is flipped (flip=True), black is at bottom; if not flipped, white is at bottom
        # Note: White at bottom = not flipped, Black at bottom = flipped (terminology)
        bottom_color = "black" if self.chess_board_widget.flip else "white"
        
        # Create game analysis widget at bottom (y=144, which is 16+128)
        # Widget will adjust scores internally based on bottom_color
        # Pass analysis engine so widget can call it directly
        self.game_analysis = GameAnalysisWidget(0, 144, 128, 80, bottom_color=bottom_color, analysis_engine=self.analysis_engine)
        board.display_manager.add_widget(self.game_analysis)
        
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

        board.display_manager.clear_widgets()
        future = board.display_manager.add_widget(SplashScreen(message="Goodbye from UCI"))
        if future:
            try:
                future.result(timeout=10.0)
            except Exception as e:
                log.warning(f"Error displaying splash screen: {e}")

        # Clean up engines
        self._cleanup_engines()
        if self.game_analysis:
            try:
                self.game_analysis._stop_analysis_worker()
            except Exception as e:
                log.warning(f"Error stopping analysis worker: {e}")
        
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
            self._update_analysis_widget(board_obj)
    
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
                self._handle_turn(chess.WHITE)
            elif event == manager.EVENT_BLACK_TURN:
                self._handle_turn(chess.BLACK)
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
        # Widgets will trigger updates automatically via request_update()
        if self.chess_board_widget:
            self.chess_board_widget.set_fen(manager.getFEN())
        if self.game_analysis:
            self.game_analysis.reset()
        # Status bar widget updates itself automatically
        
        self.current_turn = chess.WHITE
        self.is_first_move = True
        
        self._draw_board(manager.getFEN())
        
        log.info(f"Board reset. FEN: {manager.getFEN()}")
        
        if self.graphs_enabled:
            board_obj = manager.getBoard()
            self._update_analysis_widget(board_obj)
        
    
    def _handle_turn(self, turn: chess.Color):
        """Handle turn event."""
        self.current_turn = turn
        turn_name = "WHITE" if turn == chess.WHITE else "BLACK"
        log.info(f"{turn_name} turn: current_turn={self.current_turn}, computer_color={self.computer_color}")
        
        if self.graphs_enabled:
            board_obj = manager.getBoard()
            self._update_analysis_widget(board_obj)
        
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

        log.info(f"Game termination event: {termination_event}")
        termination_type = termination_event[12:]  # Remove "Termination." prefix
        
        board.display_manager.clear_widgets()

        """Draw the game over screen using GameOverWidget."""
        
        # Create game over widget
        result = manager.getResult()
        game_over_widget = GameOverWidget(0, 0, 128, 296)
        game_over_widget.set_result(result)
        # Get score history from analysis widget
        if self.game_analysis:
            game_over_widget.set_score_history(self.game_analysis.get_score_history())
        else:
            game_over_widget.set_score_history([])
        board.display_manager.add_widget(game_over_widget)
        
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
        
        # Remove last score from analysis history to keep it in sync with game state
        if self.game_analysis:
            self.game_analysis.remove_last_score()
        
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
    
    def _update_analysis_widget(self, board_obj):
        """Trigger analysis widget to analyze position."""
        if not self.graphs_enabled:
            if self.game_analysis:
                self.game_analysis.reset()
            return
        
        # Widget handles engine call, parsing, formatting, and history management
        if self.game_analysis and board_obj is not None:
            current_turn_str = "white" if self.current_turn == chess.WHITE else "black"
            # Determine time limit: shorter for first move, longer for subsequent moves
            time_limit = 0.1 if self.is_first_move else 0.5
            self.game_analysis.analyze_position(board_obj, current_turn_str, self.is_first_move, time_limit)
            # Mark that we've processed at least one move
            if self.is_first_move:
                self.is_first_move = False
    
    def _clear_evaluation_graphs(self):
        """Clear evaluation graphs from screen."""
        if self.game_analysis:
            self.game_analysis.clear_history()
            self.game_analysis.set_score(0.0, "0.0")
        
    def _draw_board(self, fen: str):
        """Draw the chess board from FEN string."""
        try:
            if self.chess_board_widget:
                self.chess_board_widget.set_fen(fen)
                log.debug(f"_draw_board: Updated chess board widget with FEN: {fen[:20]}...")
            else:
                log.warning("_draw_board: chess_board_widget is None!")
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
        #display_manager.add_widget(SplashScreen(message="   Starting game..."))
        #time.sleep(1)
        self._handle_game_event(manager.EVENT_NEW_GAME)
        #time.sleep(1)
        log.info("Game started, triggering initial turn")
        log.info("Triggering initial white turn")
        self._handle_game_event(manager.EVENT_WHITE_TURN)
        
        # Main loop
        try:
            while not self.should_stop:
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("\n>>> Caught KeyboardInterrupt...")
        finally:
            log.info(">>> Final cleanup")
            self.cleanup()
            log.info(">>> UCI Game: Goodbye!")
            os._exit(0)


def cleanup_and_exit(signum=None, frame=None):
    """Clean up resources and exit gracefully."""
    global _uci_game_instance
    if _uci_game_instance is not None:
        _uci_game_instance.cleanup()
    log.info("Goodbye!")
    os._exit(0)


# Register signal handlers
signal.signal(signal.SIGINT, cleanup_and_exit)
try:
    signal.signal(signal.SIGTERM, cleanup_and_exit)
except Exception:
    pass


def main():
    """Main entry point for UCI game."""
    # Parse command line arguments
    promise = board.init_display()
    if promise:
        try:
            promise.result(timeout=10.0)
        except Exception as e:
            log.warning(f"Error initializing display: {e}")
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

