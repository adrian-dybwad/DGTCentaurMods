# Pure UCI chess game mode without DGT Centaur Adaptive Play
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

"""
UCI game mode for playing chess against UCI engines.

This module provides a clean interface for playing chess games using
UCI engines, with support for evaluation graphs, computer moves, and
game state management.
"""

from DGTCentaurMods.games.manager import GameManager, EVENT_NEW_GAME, EVENT_WHITE_TURN, EVENT_BLACK_TURN, EVENT_RESIGN_GAME
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
from typing import Optional, Dict


# Constants
MAX_SCORE_HISTORY_SIZE = 200
EVALUATION_ANALYSIS_TIME = 0.5
COMPUTER_MOVE_TIME_LIMIT = 5
GRAPH_ANALYSIS_TIME_QUICK = 0.1
GRAPH_ANALYSIS_TIME_NORMAL = 0.5
END_SCREEN_DISPLAY_TIME = 10


class UCIGameController:
    """
    Controller for UCI chess games.
    
    Manages engine interactions, display updates, and game flow
    for playing chess against UCI engines.
    """
    
    def __init__(self, player_color: str, engine_name: str, uci_options_description: str = "Default"):
        """
        Initialize UCI game controller.
        
        Args:
            player_color: "white", "black", or "random"
            engine_name: Name of the UCI engine to use
            uci_options_description: Section name in UCI config file
        """
        self._game_manager = GameManager()
        self._current_turn = 1  # 1 = white, 0 = black
        self._computer_color = self._determine_computer_color(player_color)
        self._kill_flag = False
        self._graphs_enabled = self._should_enable_graphs()
        self._first_move = True
        self._score_history = []
        self._last_event = None
        self._cleaned_up = False
        
        # Engine setup
        self._engine_name = engine_name
        self._analysis_engine = None
        self._playing_engine = None
        self._uci_options = {}
        self._uci_options_description = uci_options_description
        
        self._initialize_engines()
        self._load_uci_options()
        self._setup_signal_handlers()
    
    def _determine_computer_color(self, player_color: str) -> int:
        """
        Determine which color the computer plays.
        
        Args:
            player_color: "white", "black", or "random"
        
        Returns:
            0 if computer plays black, 1 if computer plays white
        """
        if player_color == "white":
            return 0  # Player is white, computer is black
        elif player_color == "black":
            return 1  # Player is black, computer is white
        elif player_color == "random":
            return randint(0, 1)
        else:
            return 0  # Default to computer playing black
    
    def _should_enable_graphs(self) -> bool:
        """
        Determine if evaluation graphs should be enabled.
        
        Returns:
            True if graphs should be enabled (Pi Zero 2 W), False otherwise
        """
        return os.uname().machine == "armv7l"
    
    def _initialize_engines(self):
        """Initialize UCI chess engines."""
        base_path = pathlib.Path(__file__).parent.parent
        ct800_path = str((base_path / "engines/ct800").resolve())
        engine_path = str((base_path / f"engines/{self._engine_name}").resolve())
        
        log.info(f"Engine name: {self._engine_name}")
        log.info(f"Analysis engine path: {ct800_path}")
        log.info(f"Playing engine path: {engine_path}")
        
        self._analysis_engine = chess.engine.SimpleEngine.popen_uci(ct800_path, timeout=None)
        self._playing_engine = chess.engine.SimpleEngine.popen_uci(engine_path)
        
        log.info(f"Analysis engine: {self._analysis_engine}")
        log.info(f"Playing engine: {self._playing_engine}")
    
    def _load_uci_options(self):
        """Load UCI engine options from configuration file."""
        base_path = pathlib.Path(__file__).parent.parent
        uci_file_path = str((base_path / f"engines/{self._engine_name}.uci").resolve())
        
        if not os.path.exists(uci_file_path):
            log.warning(f"UCI file not found: {uci_file_path}, using Default settings")
            self._uci_options_description = "Default"
            return
        
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(uci_file_path)
        
        if config.has_section(self._uci_options_description):
            log.info(config.items(self._uci_options_description))
            for key, value in config.items(self._uci_options_description):
                self._uci_options[key] = value
            
            # Filter out non-UCI metadata fields
            NON_UCI_FIELDS = ['Description']
            self._uci_options = {k: v for k, v in self._uci_options.items() if k not in NON_UCI_FIELDS}
            log.info(self._uci_options)
        else:
            log.warning(f"Section '{self._uci_options_description}' not found in {uci_file_path}, falling back to Default")
            if config.has_section("DEFAULT"):
                for key, value in config.items("DEFAULT"):
                    self._uci_options[key] = value
                NON_UCI_FIELDS = ['Description']
                self._uci_options = {k: v for k, v in self._uci_options.items() if k not in NON_UCI_FIELDS}
            self._uci_options_description = "Default"
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._cleanup_and_exit)
        try:
            signal.signal(signal.SIGTERM, self._cleanup_and_exit)
        except Exception:
            pass
    
    def _cleanup_and_exit(self, signum=None, frame=None):
        """Clean up resources and exit gracefully."""
        if self._cleaned_up:
            os._exit(0)
        
        log.info(">>> Cleaning up and exiting...")
        self._kill_flag = True
        
        try:
            self._cleanup_resources()
        except KeyboardInterrupt:
            log.warning(">>> Interrupted during cleanup, forcing exit")
            os._exit(1)
        except Exception as e:
            log.warning(f">>> Error during cleanup: {e}")
        
        log.info("Goodbye!")
        sys.exit(0)
    
    def _cleanup_resources(self):
        """Clean up all resources."""
        if self._cleaned_up:
            return
        
        self._cleaned_up = True
        
        # Clean up engines
        self._cleanup_engine(self._analysis_engine, "analysis_engine")
        self._analysis_engine = None
        self._cleanup_engine(self._playing_engine, "playing_engine")
        self._playing_engine = None
        
        # Clean up board and game manager
        try:
            board.ledsOff()
        except Exception:
            pass
        
        try:
            board.unPauseEvents()
        except Exception:
            pass
        
        try:
            self._game_manager.resetMoveState()
        except Exception:
            pass
        
        try:
            self._game_manager.unsubscribeGame()
        except Exception:
            pass
        
        try:
            board.cleanup(leds_off=True)
        except Exception:
            pass
    
    def _cleanup_engine(self, engine: Optional[chess.engine.SimpleEngine], name: str):
        """
        Safely quit an engine with timeout and fallback to terminate/kill.
        
        Args:
            engine: Engine to clean up
            name: Name for logging
        """
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
        except KeyboardInterrupt:
            log.warning(f"{name} interrupted during cleanup setup")
        except Exception as e:
            log.warning(f"Error cleaning up {name}: {e}")
    
    def _key_callback(self, key):
        """
        Handle key press events.
        
        Args:
            key: Key that was pressed
        """
        log.info("Key event received: " + str(key))
        
        if key == board.Key.BACK:
            self._kill_flag = True
        
        if key == board.Key.DOWN:
            self._clear_evaluation_graphs()
            self._graphs_enabled = False
        
        if key == board.Key.UP:
            self._graphs_enabled = True
            self._first_move = True
            info = self._analysis_engine.analyse(
                self._game_manager.getBoard(),
                chess.engine.Limit(time=EVALUATION_ANALYSIS_TIME)
            )
            self._draw_evaluation_graphs(info)
    
    def _clear_evaluation_graphs(self):
        """Clear evaluation graphs from display."""
        image = Image.new('1', (128, 80), 255)
        epaper.drawImagePartial(0, 209, image)
        epaper.drawImagePartial(0, 1, image)
    
    def _event_callback(self, event):
        """
        Handle game events.
        
        Args:
            event: Game event (EVENT_NEW_GAME, EVENT_WHITE_TURN, etc.)
        """
        log.info(f">>> eventCallback START: event={event}")
        
        if event == EVENT_NEW_GAME:
            if self._last_event == EVENT_NEW_GAME:
                log.warning("!!! SKIPPING: Consecutive NEW_GAME events - ignoring to prevent loop !!!")
                return
            self._last_event = event
            self._handle_new_game_event()
            return
        
        self._last_event = event
        
        try:
            if event == EVENT_WHITE_TURN:
                self._handle_white_turn_event()
            elif event == EVENT_BLACK_TURN:
                self._handle_black_turn_event()
            elif event == EVENT_RESIGN_GAME:
                self._game_manager.resignGame(self._computer_color + 1)
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
    
    def _handle_new_game_event(self):
        """Handle NEW_GAME event."""
        log.info("EVENT_NEW_GAME: Resetting board to starting position")
        self._game_manager.resetMoveState()
        board.ledsOff()
        self._game_manager.resetBoard()
        epaper.quickClear()
        self._score_history = []
        self._current_turn = 1
        self._first_move = True
        
        epaper.pauseEpaper()
        self._draw_board(self._game_manager.getFEN())
        log.info(f"Board reset. FEN: {self._game_manager.getFEN()}")
        
        if self._graphs_enabled:
            info = self._analysis_engine.analyse(
                self._game_manager.getBoard(),
                chess.engine.Limit(time=GRAPH_ANALYSIS_TIME_QUICK)
            )
            self._draw_evaluation_graphs(info)
        
        epaper.unPauseEpaper()
    
    def _handle_white_turn_event(self):
        """Handle WHITE_TURN event."""
        self._current_turn = 1
        log.info(f"WHITE_TURN event: curturn={self._current_turn}, computer_color={self._computer_color}")
        
        if self._graphs_enabled:
            info = self._analysis_engine.analyse(
                self._game_manager.getBoard(),
                chess.engine.Limit(time=GRAPH_ANALYSIS_TIME_NORMAL)
            )
            epaper.pauseEpaper()
            self._draw_evaluation_graphs(info)
            epaper.unPauseEpaper()
        
        self._draw_board(self._game_manager.getFEN())
        
        if self._current_turn == self._computer_color:
            self._execute_computer_move()
    
    def _handle_black_turn_event(self):
        """Handle BLACK_TURN event."""
        self._current_turn = 0
        log.info(f"BLACK_TURN event: curturn={self._current_turn}, computer_color={self._computer_color}")
        
        if self._graphs_enabled:
            info = self._analysis_engine.analyse(
                self._game_manager.getBoard(),
                chess.engine.Limit(time=GRAPH_ANALYSIS_TIME_NORMAL)
            )
            epaper.pauseEpaper()
            self._draw_evaluation_graphs(info)
            epaper.unPauseEpaper()
        
        self._draw_board(self._game_manager.getFEN())
        
        if self._current_turn == self._computer_color:
            self._execute_computer_move()
    
    def _execute_computer_move(self):
        """Execute computer's move."""
        log.info(f"Computer's turn! Current FEN: {self._game_manager.getFEN()}")
        
        if self._uci_options:
            log.info(f"Configuring engine with options: {self._uci_options}")
            self._playing_engine.configure(self._uci_options)
        
        limit = chess.engine.Limit(time=COMPUTER_MOVE_TIME_LIMIT)
        log.info(f"Asking engine to play from FEN: {self._game_manager.getFEN()}")
        
        try:
            result = self._playing_engine.play(
                self._game_manager.getBoard(),
                limit,
                info=chess.engine.INFO_ALL
            )
            log.info(f"Engine returned: {result}")
            move = result.move
            log.info(f"Move extracted: {move}")
            log.info(f"Executing move: {str(move)}")
            self._setup_computer_move(str(move))
        except Exception as e:
            log.error(f"Error in computer move: {e}")
            import traceback
            traceback.print_exc()
    
    def _setup_computer_move(self, move_uci: str):
        """
        Set up computer move for player to execute on board.
        
        Args:
            move_uci: Move in UCI format
        """
        try:
            log.info(f"Setting up computer move: {move_uci}")
            board_obj = self._game_manager.getBoard()
            log.info(f"Current FEN: {self._game_manager.getFEN()}")
            log.info(f"Legal moves: {[str(m) for m in list(board_obj.legal_moves)[:5]]}...")
            
            # Validate the move is legal
            move = chess.Move.from_uci(move_uci)
            if move not in board_obj.legal_moves:
                log.error(f"ERROR: Move {move_uci} is not legal! This should not happen.")
                log.error(f"Legal moves: {list(board_obj.legal_moves)}")
                raise ValueError(f"Illegal move: {move_uci}")
            
            log.info(f"Setting up game manager for forced move")
            self._game_manager.computerMove(move_uci)
            
            log.info("Computer move setup complete. Waiting for player to move pieces on board.")
        except Exception as e:
            log.error(f"Error in setup_computer_move: {e}")
            import traceback
            traceback.print_exc()
    
    def _move_callback(self, move):
        """
        Handle completed move.
        
        Args:
            move: Move in UCI format
        """
        try:
            log.info(f"moveCallback: Drawing board for move {move}")
            self._draw_board(self._game_manager.getFEN())
            log.info("moveCallback: Board drawn successfully")
        except Exception as e:
            log.error(f"Error in moveCallback while drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _takeback_callback(self):
        """Handle takeback event."""
        log.info("Takeback detected - clearing computer move setup")
        self._game_manager.resetMoveState()
        board.ledsOff()
        
        # Switch turn
        if self._current_turn == 1:
            self._current_turn = 0
        else:
            self._current_turn = 1
        
        # Trigger appropriate turn event
        if self._current_turn == 0:
            self._event_callback(EVENT_BLACK_TURN)
        else:
            self._event_callback(EVENT_WHITE_TURN)
    
    def _draw_evaluation_graphs(self, analysis_info):
        """
        Draw evaluation graphs to the screen.
        
        Args:
            analysis_info: Analysis info from engine
        """
        if "score" not in analysis_info:
            log.info("evaluationGraphs: No score in info, skipping")
            return
        
        if not self._graphs_enabled:
            self._clear_evaluation_graphs()
            return
        
        score_value = self._extract_score_value(analysis_info["score"])
        
        # Draw evaluation bars
        image = Image.new('1', (128, 80), 255)
        draw = ImageDraw.Draw(image)
        font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
        
        score_text = self._format_score_text(score_value, analysis_info["score"])
        
        draw.text((50, 12), score_text, font=font12, fill=0)
        draw.rectangle([(0, 1), (127, 11)], fill=None, outline='black')
        
        # Calculate indicator position
        score_value = max(-12, min(12, score_value))
        
        if not self._first_move:
            self._score_history.append(score_value)
            if len(self._score_history) > MAX_SCORE_HISTORY_SIZE:
                self._score_history.pop(0)
        else:
            self._first_move = False
        
        indicator_offset = (128 / 25) * (score_value + 12)
        if indicator_offset < 128:
            draw.rectangle([(indicator_offset, 1), (127, 11)], fill=0, outline='black')
        
        # Draw bar chart
        self._draw_score_history_bars(draw, image)
        
        # Draw turn indicator
        tmp = image.copy()
        dr2 = ImageDraw.Draw(tmp)
        if self._current_turn == 1:
            dr2.ellipse((119, 14, 126, 21), fill=0, outline=0)
        epaper.drawImagePartial(0, 209, tmp)
        
        if self._current_turn == 0:
            draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
        
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        epaper.drawImagePartial(0, 1, image)
    
    def _extract_score_value(self, score_obj) -> float:
        """
        Extract numeric score value from score object.
        
        Args:
            score_obj: Score object from engine
        
        Returns:
            Score value as float (in pawns)
        """
        score_str = str(score_obj)
        
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
        
        if "BLACK" in score_str:
            score_value = score_value * -1
        
        return score_value
    
    def _format_score_text(self, score_value: float, score_obj) -> str:
        """
        Format score text for display.
        
        Args:
            score_value: Numeric score value
            score_obj: Score object from engine
        
        Returns:
            Formatted score text string
        """
        score_str = str(score_obj)
        
        if score_value > 999:
            return ""
        
        if "Mate" in score_str:
            return "Mate in " + f"{abs(score_value * 100):2.0f}"
        
        return f"{score_value:5.1f}"
    
    def _draw_score_history_bars(self, draw: ImageDraw.Draw, image: Image.Image):
        """
        Draw score history bar chart.
        
        Args:
            draw: ImageDraw object
            image: Image to draw on
        """
        if len(self._score_history) == 0:
            return
        
        draw.line([(0, 50), (128, 50)], fill=0, width=1)
        bar_width = 128 / len(self._score_history)
        if bar_width > 8:
            bar_width = 8
        
        bar_offset = 0
        for score in self._score_history:
            color = 255 if score >= 0 else 0
            y_calc = 50 - (score * 2)
            y0 = min(50, y_calc)
            y1 = max(50, y_calc)
            draw.rectangle([(bar_offset, y0), (bar_offset + bar_width, y1)], fill=color, outline='black')
            bar_offset = bar_offset + bar_width
    
    def _draw_board(self, fen: str):
        """
        Draw chess board to display.
        
        Args:
            fen: FEN string of board position
        """
        try:
            log.info(f"drawBoardLocal: Starting to draw board with FEN: {fen[:20]}...")
            processed_fen = self._process_fen_for_display(fen)
            
            board_image = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(board_image)
            chess_font = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            for square_index in range(64):
                position = (square_index - 63) * -1
                row = 16 * (position // 8)
                col = (square_index % 8) * 16
                
                piece_x, piece_y = self._get_piece_sprite_coords(processed_fen[square_index], square_index)
                
                piece_sprite = chess_font.crop((piece_x, piece_y, piece_x + 16, piece_y + 16))
                
                if self._computer_color == 1:
                    piece_sprite = piece_sprite.transpose(Image.FLIP_TOP_BOTTOM)
                    piece_sprite = piece_sprite.transpose(Image.FLIP_LEFT_RIGHT)
                
                board_image.paste(piece_sprite, (col, row))
            
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            epaper.drawImagePartial(0, 81, board_image)
        except Exception as e:
            log.error(f"Error in drawBoardLocal: {e}")
            import traceback
            traceback.print_exc()
    
    def _process_fen_for_display(self, fen: str) -> str:
        """
        Process FEN string for board display.
        
        Args:
            fen: FEN string
        
        Returns:
            Processed FEN string with pieces only
        """
        processed = str(fen)
        processed = processed.replace("/", "")
        processed = processed.replace("1", " ")
        processed = processed.replace("2", "  ")
        processed = processed.replace("3", "   ")
        processed = processed.replace("4", "    ")
        processed = processed.replace("5", "     ")
        processed = processed.replace("6", "      ")
        processed = processed.replace("7", "       ")
        processed = processed.replace("8", "        ")
        
        # Reorder for display (flip rows)
        reordered = ""
        for row in range(8, 0, -1):
            for col in range(0, 8):
                reordered = reordered + processed[((row - 1) * 8) + col]
        
        return reordered
    
    def _get_piece_sprite_coords(self, piece_char: str, square_index: int) -> tuple:
        """
        Get sprite coordinates for a piece.
        
        Args:
            piece_char: Piece character (P, R, N, B, Q, K or lowercase)
            square_index: Square index (0-63)
        
        Returns:
            Tuple of (x, y) sprite coordinates
        """
        piece_x = 0
        piece_y = 0
        
        # Calculate background color based on square
        row = square_index // 8
        col = square_index % 8
        if (row // 2 == row / 2 and col // 2 == col / 2) or (row // 2 != row / 2 and col // 2 == col / 2):
            piece_y = 16
        
        # Map piece to sprite coordinates
        piece_map = {
            "P": (16, piece_y),
            "R": (32, piece_y),
            "N": (48, piece_y),
            "B": (64, piece_y),
            "Q": (80, piece_y),
            "K": (96, piece_y),
            "p": (112, piece_y),
            "r": (128, piece_y),
            "n": (144, piece_y),
            "b": (160, piece_y),
            "q": (176, piece_y),
            "k": (192, piece_y),
        }
        
        return piece_map.get(piece_char, (0, piece_y))
    
    def _handle_game_termination(self, termination: str):
        """
        Handle game termination event.
        
        Args:
            termination: Termination string (e.g., "Termination.CHECKMATE")
        """
        termination_text = termination[12:]  # Remove "Termination." prefix
        
        # Display termination message
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
        draw.text((0, 20), "          " + self._game_manager.getResult(), font=font18, fill=0)
        
        if len(self._score_history) > 0:
            log.info("there be history")
            draw.line([(0, 114), (128, 114)], fill=0, width=1)
            bar_width = 128 / len(self._score_history)
            if bar_width > 8:
                bar_width = 8
            
            bar_offset = 0
            for score in self._score_history:
                color = 255 if score >= 0 else 0
                draw.rectangle(
                    [(bar_offset, 114), (bar_offset + bar_width, 114 - (score * 4))],
                    fill=color,
                    outline='black'
                )
                bar_offset = bar_offset + bar_width
        
        log.info("drawing")
        epaper.drawImagePartial(0, 0, image)
        time.sleep(END_SCREEN_DISPLAY_TIME)
        self._kill_flag = True
    
    def run(self):
        """Run the UCI game."""
        # Set game info
        if self._computer_color == 0:
            self._game_manager.setGameInfo(
                self._uci_options_description, "", "", "Player", self._engine_name
            )
        else:
            self._game_manager.setGameInfo(
                self._uci_options_description, "", "", self._engine_name, "Player"
            )
        
        # Initialize epaper
        epaper.initEpaper()
        
        # Set initial turn
        self._current_turn = 1
        
        # Subscribe to game manager
        self._game_manager.subscribeGame(
            self._event_callback,
            self._move_callback,
            self._key_callback,
            self._takeback_callback
        )
        log.info("Game manager subscribed")
        
        # Manually trigger game start
        log.info("Triggering NEW_GAME event")
        self._write_text(0, "Starting game...")
        self._write_text(1, "              ")
        time.sleep(1)
        self._event_callback(EVENT_NEW_GAME)
        time.sleep(1)
        log.info("Game started, triggering initial turn")
        log.info("Triggering initial white turn")
        self._event_callback(EVENT_WHITE_TURN)
        
        # Main loop
        try:
            while not self._kill_flag:
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
            self._cleanup_and_exit()
        finally:
            log.info(">>> Final cleanup")
            self._cleanup_resources()
    
    def _write_text(self, row: int, text: str):
        """
        Write text on a given line number.
        
        Args:
            row: Row number (0-based)
            text: Text to write
        """
        image = Image.new('1', (128, 20), 255)
        draw = ImageDraw.Draw(image)
        font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
        draw.text((0, 0), text, font=font18, fill=0)
        epaper.drawImagePartial(0, (row * 20), image)


def run_uci_game(player_color: str = "white", engine_name: str = "stockfish_pi", uci_options_description: str = "Default"):
    """
    Run a UCI chess game.
    
    Args:
        player_color: "white", "black", or "random"
        engine_name: Name of the UCI engine to use
        uci_options_description: Section name in UCI config file
    """
    controller = UCIGameController(player_color, engine_name, uci_options_description)
    controller.run()


if __name__ == "__main__":
    # Parse command line arguments
    player_color_arg = sys.argv[1] if len(sys.argv) > 1 else "white"
    engine_name_arg = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    uci_options_arg = sys.argv[3] if len(sys.argv) > 3 else "Default"
    
    run_uci_game(player_color_arg, engine_name_arg, uci_options_arg)

