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


class EngineManager:
    """Manages chess engine instances and configuration."""
    
    def __init__(self, engine_name: str, uci_options_desc: str = "Default"):
        self.engine_name = engine_name
        self.uci_options_desc = uci_options_desc
        self.uci_options = {}
        self.analysis_engine = None
        self.play_engine = None
        self._initialize_engines()
        self._load_uci_options()
    
    def _initialize_engines(self):
        """Initialize analysis and play engines."""
        engine_path_name = f"engines/{self.engine_name}"
        ct800_path = "engines/ct800"
        
        base_path = pathlib.Path(__file__).parent.parent
        analysis_engine_path = str((base_path / ct800_path).resolve())
        play_engine_path = str((base_path / engine_path_name).resolve())
        
        log.info(f"Analysis engine: {analysis_engine_path}")
        log.info(f"Play engine: {play_engine_path}")
        
        self.analysis_engine = chess.engine.SimpleEngine.popen_uci(
            analysis_engine_path, timeout=None
        )
        self.play_engine = chess.engine.SimpleEngine.popen_uci(play_engine_path)
    
    def _load_uci_options(self):
        """Load UCI options from configuration file."""
        base_path = pathlib.Path(__file__).parent.parent
        uci_file_path = str((base_path / f"engines/{self.engine_name}.uci").resolve())
        
        if os.path.exists(uci_file_path):
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(uci_file_path)
            
            if config.has_section(self.uci_options_desc):
                log.info(f"Loading UCI options from section: {self.uci_options_desc}")
                for item in config.items(self.uci_options_desc):
                    self.uci_options[item[0]] = item[1]
                
                # Filter out non-UCI metadata fields
                non_uci_fields = ['Description']
                self.uci_options = {
                    k: v for k, v in self.uci_options.items() 
                    if k not in non_uci_fields
                }
                log.info(f"UCI options: {self.uci_options}")
            else:
                log.warning(
                    f"Section '{self.uci_options_desc}' not found in {uci_file_path}, "
                    f"falling back to Default"
                )
                if config.has_section("DEFAULT"):
                    for item in config.items("DEFAULT"):
                        self.uci_options[item[0]] = item[1]
                    non_uci_fields = ['Description']
                    self.uci_options = {
                        k: v for k, v in self.uci_options.items() 
                        if k not in non_uci_fields
                    }
                self.uci_options_desc = "Default"
        else:
            log.warning(f"UCI file not found: {uci_file_path}, using Default settings")
            self.uci_options_desc = "Default"
    
    def configure_play_engine(self):
        """Configure play engine with UCI options."""
        if self.uci_options:
            log.info(f"Configuring engine with options: {self.uci_options}")
            self.play_engine.configure(self.uci_options)
    
    def get_move(self, chess_board, time_limit: float = 5.0):
        """Get move from play engine."""
        limit = chess.engine.Limit(time=time_limit)
        log.info(f"Asking engine to play from FEN: {chess_board.fen()}")
        try:
            result = self.play_engine.play(
                chess_board, limit, info=chess.engine.INFO_ALL
            )
            log.info(f"Engine returned: {result}")
            move = result.move
            log.info(f"Move extracted: {move}")
            return str(move)
        except Exception as e:
            log.error(f"Error getting move from engine: {e}")
            raise
    
    def analyze_position(self, chess_board, time_limit: float = 0.5):
        """Analyze position with analysis engine."""
        try:
            info = self.analysis_engine.analyse(
                chess_board, chess.engine.Limit(time=time_limit)
            )
            return info
        except Exception as e:
            log.error(f"Error analyzing position: {e}")
            return None
    
    def cleanup(self):
        """Clean up engine resources."""
        def cleanup_engine(engine, name):
            """Safely quit an engine, with fallback to terminate/kill if needed."""
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
        
        cleanup_engine(self.analysis_engine, "analysis_engine")
        cleanup_engine(self.play_engine, "play_engine")


class EvaluationDisplay:
    """Manages evaluation graph display on epaper."""
    
    MAX_SCORE_HISTORY_SIZE = 200
    
    def __init__(self):
        self.score_history = []
        self.is_first_move = True
        self.graphs_enabled = self._detect_graphs_capability()
    
    def _detect_graphs_capability(self) -> bool:
        """Detect if system can handle graphs (Pi Zero 2 W is armv7l)."""
        if os.uname().machine == "armv7l":
            return True
        return False
    
    def enable_graphs(self):
        """Enable evaluation graphs."""
        self.graphs_enabled = True
        self.is_first_move = True
    
    def disable_graphs(self):
        """Disable evaluation graphs."""
        self.graphs_enabled = False
        image = Image.new('1', (128, 80), 255)
        epaper.drawImagePartial(0, 209, image)
        epaper.drawImagePartial(0, 1, image)
    
    def _extract_score_value(self, info) -> tuple:
        """Extract score value from engine analysis info."""
        if "score" not in info:
            return None, None
        
        score_str = str(info["score"])
        is_mate = "Mate" in score_str
        
        if is_mate:
            score_part = score_str[13:24]
            score_part = score_part[1:score_part.find(")")]
        else:
            score_part = score_str[11:24]
            score_part = score_part[1:score_part.find(")")]
        
        try:
            score_value = float(score_part)
            score_value = score_value / 100
            
            if "BLACK" in score_str:
                score_value = score_value * -1
            
            return score_value, is_mate
        except (ValueError, IndexError):
            return None, None
    
    def _format_score_text(self, score_value: float, is_mate: bool) -> str:
        """Format score value as display text."""
        if is_mate:
            return f"Mate in {abs(score_value * 100):2.0f}"
        
        if score_value > 999:
            return ""
        
        return f"{score_value:5.1f}"
    
    def _clamp_score_for_display(self, score_value: float) -> float:
        """Clamp score value for display purposes."""
        if score_value > 12:
            return 12
        if score_value < -12:
            return -12
        return score_value
    
    def _draw_evaluation_bar(self, score_value: float, is_mate: bool, current_turn: int):
        """Draw evaluation bar indicator."""
        if not self.graphs_enabled:
            return
        
        image = Image.new('1', (128, 80), 255)
        draw = ImageDraw.Draw(image)
        font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
        
        score_text = self._format_score_text(score_value, is_mate)
        draw.text((50, 12), score_text, font=font12, fill=0)
        draw.rectangle([(0, 1), (127, 11)], fill=None, outline='black')
        
        # Calculate indicator position
        display_score = self._clamp_score_for_display(score_value)
        if is_mate:
            display_score = display_score * 100000
        
        offset = (128 / 25) * (display_score + 12)
        if offset < 128:
            draw.rectangle([(offset, 1), (127, 11)], fill=0, outline='black')
        
        # Draw score history bar chart
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
                    fill=color, outline='black'
                )
                bar_offset += bar_width
        
        # Draw turn indicator
        tmp = image.copy()
        dr2 = ImageDraw.Draw(tmp)
        if current_turn == 1:  # White's turn
            dr2.ellipse((119, 14, 126, 21), fill=0, outline=0)
        epaper.drawImagePartial(0, 209, tmp)
        
        if current_turn == 0:  # Black's turn
            draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
        
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        epaper.drawImagePartial(0, 1, image)
    
    def display_evaluation(self, info, current_turn: int):
        """Display evaluation graphs based on engine analysis."""
        score_value, is_mate = self._extract_score_value(info)
        
        if score_value is None:
            log.info("evaluationGraphs: No score in info, skipping")
            return
        
        if not self.graphs_enabled:
            self.disable_graphs()
            return
        
        # Add to history if not first move
        if not self.is_first_move:
            self.score_history.append(score_value)
            if len(self.score_history) > self.MAX_SCORE_HISTORY_SIZE:
                self.score_history.pop(0)
        else:
            self.is_first_move = False
        
        self._draw_evaluation_bar(score_value, is_mate, current_turn)


class BoardDisplay:
    """Manages chess board display on epaper."""
    
    def __init__(self, computer_color: int):
        self.computer_color = computer_color  # 0 = black, 1 = white
    
    def _parse_fen_to_piece_array(self, fen: str) -> str:
        """Parse FEN string to piece array representation."""
        fen_str = str(fen)
        fen_str = fen_str.replace("/", "")
        fen_str = fen_str.replace("1", " ")
        fen_str = fen_str.replace("2", "  ")
        fen_str = fen_str.replace("3", "   ")
        fen_str = fen_str.replace("4", "    ")
        fen_str = fen_str.replace("5", "     ")
        fen_str = fen_str.replace("6", "      ")
        fen_str = fen_str.replace("7", "       ")
        fen_str = fen_str.replace("8", "        ")
        
        # Reorder for display (rank 8 to rank 1)
        piece_array = ""
        for rank in range(8, 0, -1):
            for file in range(0, 8):
                piece_array += fen_str[((rank - 1) * 8) + file]
        
        return piece_array
    
    def _get_piece_sprite_coords(self, piece_char: str) -> tuple:
        """Get sprite coordinates for piece character."""
        piece_coords = {
            "P": 16, "R": 32, "N": 48, "B": 64, "Q": 80, "K": 96,
            "p": 112, "r": 128, "n": 144, "b": 160, "q": 176, "k": 192
        }
        return piece_coords.get(piece_char, 0)
    
    def _get_square_background_offset(self, square_index: int) -> int:
        """Get background offset for square (light/dark squares)."""
        row = square_index // 8
        col = square_index % 8
        offset = 0
        
        if (row // 2 == row / 2 and col // 2 == col / 2):
            offset = 16
        if (row // 2 != row / 2 and col // 2 == col / 2):
            offset = 16
        
        return offset
    
    def draw_board(self, fen: str):
        """Draw chess board from FEN string."""
        try:
            log.info(f"drawBoardLocal: Starting to draw board with FEN: {fen[:20]}...")
            
            piece_array = self._parse_fen_to_piece_array(fen)
            board_image = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(board_image)
            chess_font = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            for square_index in range(64):
                display_pos = (square_index - 63) * -1
                row = 16 * (display_pos // 8)
                col = (square_index % 8) * 16
                
                piece_char = piece_array[square_index]
                piece_x = self._get_piece_sprite_coords(piece_char)
                piece_y = self._get_square_background_offset(square_index)
                
                if piece_x > 0:  # Only draw if piece exists
                    piece_sprite = chess_font.crop(
                        (piece_x, piece_y, piece_x + 16, piece_y + 16)
                    )
                    
                    # Flip board if computer is white
                    if self.computer_color == 1:
                        piece_sprite = piece_sprite.transpose(Image.FLIP_TOP_BOTTOM)
                        piece_sprite = piece_sprite.transpose(Image.FLIP_LEFT_RIGHT)
                    
                    board_image.paste(piece_sprite, (col, row))
            
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            epaper.drawImagePartial(0, 81, board_image)
            
        except Exception as e:
            log.error(f"Error in drawBoardLocal: {e}")
            import traceback
            traceback.print_exc()


class UCIGameController:
    """Main controller for UCI chess game."""
    
    def __init__(self, player_color: str, engine_name: str, uci_options_desc: str = "Default"):
        self.current_turn = 1  # 1 = white, 0 = black
        self.computer_color = self._determine_computer_color(player_color)
        self.kill_flag = False
        self.last_event = None
        self.cleaned_up = False
        
        self.engine_manager = EngineManager(engine_name, uci_options_desc)
        self.evaluation_display = EvaluationDisplay()
        self.board_display = BoardDisplay(self.computer_color)
        self.game_manager = manager.GameManager()
        
        self._setup_signal_handlers()
        self._setup_game_info()
    
    def _determine_computer_color(self, player_color: str) -> int:
        """Determine computer color based on player color argument."""
        if player_color == "white":
            return 0  # Player is white, computer is black
        elif player_color == "black":
            return 1  # Player is black, computer is white
        else:  # random
            return randint(0, 1)
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for cleanup."""
        signal.signal(signal.SIGINT, self._cleanup_and_exit)
        try:
            signal.signal(signal.SIGTERM, self._cleanup_and_exit)
        except Exception:
            pass
    
    def _setup_game_info(self):
        """Setup game information for database."""
        if self.computer_color == 0:
            self.game_manager.set_game_info(
                self.engine_manager.uci_options_desc, "", "", "Player", self.engine_manager.engine_name
            )
        else:
            self.game_manager.set_game_info(
                self.engine_manager.uci_options_desc, "", "", 
                self.engine_manager.engine_name, "Player"
            )
    
    def _cleanup_and_exit(self, signum=None, frame=None):
        """Clean up resources and exit gracefully."""
        if self.cleaned_up:
            os._exit(0)
        
        log.info(">>> Cleaning up and exiting...")
        self.kill_flag = True
        
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
        if self.cleaned_up:
            return
        
        self.cleaned_up = True
        
        try:
            self.engine_manager.cleanup()
        except Exception:
            pass
        
        try:
            board.ledsOff()
        except Exception:
            pass
        
        try:
            board.unPauseEvents()
        except Exception:
            pass
        
        try:
            self.game_manager.reset_move_state()
        except Exception:
            pass
        
        try:
            self.game_manager.unsubscribe_game()
        except Exception:
            pass
        
        try:
            board.cleanup(leds_off=True)
        except Exception:
            pass
    
    def _write_text_local(self, row: int, text: str):
        """Write text on given line number."""
        image = Image.new('1', (128, 20), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        draw.text((0, 0), text, font=font18, fill=0)
        epaper.drawImagePartial(0, (row * 20), image)
    
    def _execute_computer_move(self, move_uci: str):
        """Execute computer move by setting up LEDs and flags."""
        try:
            log.info(f"Setting up computer move: {move_uci}")
            chess_board = self.game_manager.get_board()
            log.info(f"Current FEN: {self.game_manager.get_fen()}")
            log.info(f"Legal moves: {[str(m) for m in list(chess_board.legal_moves)[:5]]}...")
            
            # Validate move is legal
            move = chess.Move.from_uci(move_uci)
            if move not in chess_board.legal_moves:
                log.error(f"ERROR: Move {move_uci} is not legal! This should not happen.")
                log.error(f"Legal moves: {list(chess_board.legal_moves)}")
                raise ValueError(f"Illegal move: {move_uci}")
            
            log.info(f"Setting up game manager for forced move")
            self.game_manager.computer_move(move_uci)
            
            log.info("Computer move setup complete. Waiting for player to move pieces on board.")
            
        except Exception as e:
            log.error(f"Error in _execute_computer_move: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_new_game_event(self):
        """Handle new game event."""
        log.info("EVENT_NEW_GAME: Resetting board to starting position")
        self.game_manager.reset_move_state()
        board.ledsOff()
        self.game_manager.reset_board()
        epaper.quickClear()
        
        self.evaluation_display.score_history = []
        self.current_turn = 1
        self.evaluation_display.is_first_move = True
        
        epaper.pauseEpaper()
        self.board_display.draw_board(self.game_manager.get_fen())
        log.info(f"Board reset. FEN: {self.game_manager.get_fen()}")
        
        if self.evaluation_display.graphs_enabled:
            info = self.engine_manager.analyze_position(
                self.game_manager.get_board(), time_limit=0.1
            )
            if info:
                self.evaluation_display.display_evaluation(info, self.current_turn)
        
        epaper.unPauseEpaper()
    
    def _handle_turn_event(self, event_type: int):
        """Handle turn event (white or black)."""
        self.current_turn = 1 if event_type == manager.EVENT_WHITE_TURN else 0
        
        log.info(
            f"Turn event: current_turn={self.current_turn}, "
            f"computer_color={self.computer_color}"
        )
        
        if self.evaluation_display.graphs_enabled:
            info = self.engine_manager.analyze_position(
                self.game_manager.get_board(), time_limit=0.5
            )
            if info:
                epaper.pauseEpaper()
                self.evaluation_display.display_evaluation(info, self.current_turn)
                epaper.unPauseEpaper()
        
        self.board_display.draw_board(self.game_manager.get_fen())
        
        # Check if it's computer's turn
        if self.current_turn == self.computer_color:
            self._handle_computer_turn()
    
    def _handle_computer_turn(self):
        """Handle computer's turn to move."""
        log.info(f"Computer's turn! Current FEN: {self.game_manager.get_fen()}")
        
        self.engine_manager.configure_play_engine()
        
        try:
            move_uci = self.engine_manager.get_move(
                self.game_manager.get_board(), time_limit=5.0
            )
            log.info(f"Executing move: {move_uci}")
            self._execute_computer_move(move_uci)
        except Exception as e:
            log.error(f"Error in computer turn: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_game_termination(self, termination_string: str):
        """Handle game termination event."""
        termination_text = termination_string[12:] if termination_string.startswith("Termination.") else termination_string
        
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
        
        # Display end screen
        log.info("displaying end screen")
        image = Image.new('1', (128, 292), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
        draw.text((0, 20), "          " + self.game_manager.get_result(), font=font18, fill=0)
        
        # Draw score history if available
        if len(self.evaluation_display.score_history) > 0:
            log.info("there be history")
            draw.line([(0, 114), (128, 114)], fill=0, width=1)
            bar_width = 128 / len(self.evaluation_display.score_history)
            if bar_width > 8:
                bar_width = 8
            
            bar_offset = 0
            for score in self.evaluation_display.score_history:
                color = 255 if score >= 0 else 0
                draw.rectangle(
                    [(bar_offset, 114), 
                     (bar_offset + bar_width, 114 - (score * 4))],
                    fill=color, outline='black'
                )
                bar_offset += bar_width
        
        log.info("drawing")
        epaper.drawImagePartial(0, 0, image)
        time.sleep(10)
        self.kill_flag = True
    
    def _event_callback(self, event):
        """Handle game events from game manager."""
        log.info(f">>> eventCallback START: event={event}")
        
        # Prevent duplicate NEW_GAME events
        if event == manager.EVENT_NEW_GAME:
            log.warning("!!! WARNING: NEW_GAME event triggered !!!")
            if self.last_event == manager.EVENT_NEW_GAME:
                log.warning("!!! SKIPPING: Consecutive NEW_GAME events - ignoring to prevent loop !!!")
                return
        
        self.last_event = event
        
        try:
            log.info(f"EventCallback triggered with event: {event}")
            
            if event == manager.EVENT_NEW_GAME:
                self._handle_new_game_event()
            
            elif event == manager.EVENT_WHITE_TURN:
                self._handle_turn_event(manager.EVENT_WHITE_TURN)
            
            elif event == manager.EVENT_BLACK_TURN:
                self._handle_turn_event(manager.EVENT_BLACK_TURN)
            
            elif event == manager.EVENT_RESIGN_GAME:
                self.game_manager.resign_game(self.computer_color + 1)
            
            elif isinstance(event, str) and event.startswith("Termination."):
                self._handle_game_termination(event)
        
        except Exception as e:
            log.error(f"Error in eventCallback: {e}")
            import traceback
            traceback.print_exc()
            try:
                epaper.unPauseEpaper()
            except Exception:
                pass
    
    def _move_callback(self, move_uci: str):
        """Handle move callback from game manager."""
        try:
            log.info(f"moveCallback: Drawing board for move {move_uci}")
            self.board_display.draw_board(self.game_manager.get_fen())
            log.info("moveCallback: Board drawn successfully")
        except Exception as e:
            log.error(f"Error in moveCallback while drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _key_callback(self, key):
        """Handle key press callback."""
        log.info("Key event received: " + str(key))
        
        if key == board.Key.BACK:
            self.kill_flag = True
        
        if key == board.Key.DOWN:
            self.evaluation_display.disable_graphs()
        
        if key == board.Key.UP:
            self.evaluation_display.enable_graphs()
            self.evaluation_display.is_first_move = True
            info = self.engine_manager.analyze_position(
                self.game_manager.get_board(), time_limit=0.5
            )
            if info:
                self.evaluation_display.display_evaluation(info, self.current_turn)
    
    def _takeback_callback(self):
        """Handle takeback callback."""
        log.info("Takeback detected - clearing computer move setup")
        self.game_manager.reset_move_state()
        board.ledsOff()
        
        # Switch turn
        self.current_turn = 0 if self.current_turn == 1 else 1
        
        # Trigger appropriate turn event
        if self.current_turn == 0:
            self._event_callback(manager.EVENT_BLACK_TURN)
        else:
            self._event_callback(manager.EVENT_WHITE_TURN)
    
    def run(self):
        """Run the UCI game."""
        # Initialize epaper
        epaper.initEpaper()
        
        # Set initial turn
        self.current_turn = 1
        
        # Subscribe to game manager
        self.game_manager.subscribe_game(
            self._event_callback, 
            self._move_callback, 
            self._key_callback, 
            self._takeback_callback
        )
        log.info("Game manager subscribed")
        
        # Manually trigger game start for UCI mode
        log.info("Triggering NEW_GAME event")
        self._write_text_local(0, "Starting game...")
        self._write_text_local(1, "              ")
        time.sleep(1)
        self._event_callback(manager.EVENT_NEW_GAME)
        time.sleep(1)
        log.info("Game started, triggering initial turn")
        log.info("Triggering initial white turn")
        self._event_callback(manager.EVENT_WHITE_TURN)
        
        try:
            while not self.kill_flag:
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
            self._cleanup_and_exit()
        finally:
            log.info(">>> Final cleanup")
            self._cleanup()


def main():
    """Main entry point for UCI game."""
    # Expect first argument to be 'white', 'black', or 'random' for player color
    player_color = sys.argv[1] if len(sys.argv) > 1 else "white"
    
    # Second argument is engine name
    engine_name = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    log.info(f"Engine name: {engine_name}")
    
    # Third argument is UCI options description (section name in .uci file)
    uci_options_desc = sys.argv[3] if len(sys.argv) > 3 else "Default"
    
    controller = UCIGameController(player_color, engine_name, uci_options_desc)
    controller.run()


if __name__ == "__main__":
    main()

