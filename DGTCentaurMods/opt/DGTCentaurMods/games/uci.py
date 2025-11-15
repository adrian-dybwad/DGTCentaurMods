"""
UCI Engine Controller

Manages UCI chess engine lifecycle and coordinates between game manager events,
engine moves, and display updates. Handles UI/display, decides when to call engine,
and manages engine lifecycle.

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

import chess
import chess.engine
import sys
import pathlib
import os
import threading
import time
import signal
import configparser
from typing import Optional, Dict
from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.games.manager import ChessGameManager, GameEvent
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log


class UCIEngineController:
    """
    Manages UCI chess engine lifecycle and coordinates game events with engine moves.
    
    Reacts to events from game manager, decides when to call engine, handles UI/display,
    starts new game if pieces are in start position, draws board state, and manages
    engine lifecycle.
    """
    
    def __init__(
        self,
        engine_path: str,
        engine_options: Optional[Dict[str, str]] = None,
        computer_color: Optional[chess.Color] = None
    ):
        """
        Initialize UCI engine controller.
        
        Args:
            engine_path: Path to UCI engine executable
            engine_options: Optional dictionary of UCI options to configure
            computer_color: Optional chess.WHITE or chess.BLACK for computer side
                           If None, determined from command line args
        """
        self._engine_path = engine_path
        self._engine_options = engine_options or {}
        self._computer_color = computer_color or self._determine_computer_color()
        
        # Engine instances
        self._engine: Optional[chess.engine.SimpleEngine] = None
        self._analysis_engine: Optional[chess.engine.SimpleEngine] = None
        
        # Game manager
        self._game_manager: Optional[ChessGameManager] = None
        
        # State
        self._running: bool = False
        self._kill_flag: bool = False
        
        # Register signal handlers for cleanup
        signal.signal(signal.SIGINT, self._cleanup_and_exit)
        try:
            signal.signal(signal.SIGTERM, self._cleanup_and_exit)
        except Exception:
            pass
    
    def _determine_computer_color(self) -> chess.Color:
        """
        Determine computer color from command line arguments.
        
        Returns:
            chess.WHITE or chess.BLACK
        """
        if len(sys.argv) > 1:
            arg = sys.argv[1].lower()
            if arg == "white":
                return chess.WHITE
            elif arg == "black":
                return chess.BLACK
            elif arg == "random":
                import random
                return random.choice([chess.WHITE, chess.BLACK])
        
        # Default: computer plays black
        return chess.BLACK
    
    def start(self) -> None:
        """Start the UCI engine controller and initialize engines."""
        if self._running:
            log.warning("[games.uci] Already running")
            return
        
        log.info(f"[games.uci] Starting UCI controller (computer plays {'White' if self._computer_color else 'Black'})")
        
        # Initialize display
        epaper.initEpaper()
        
        # Initialize engines
        self._initialize_engines()
        
        # Create and subscribe to game manager
        self._game_manager = ChessGameManager()
        self._game_manager.set_game_info(
            event=self._engine_options.get('Description', 'UCI Game'),
            white="Player" if self._computer_color == chess.BLACK else "Engine",
            black="Engine" if self._computer_color == chess.BLACK else "Player"
        )
        
        self._game_manager.subscribe(
            event_callback=self._on_game_event,
            move_callback=self._on_move,
            key_callback=self._on_key_press
        )
        
        self._running = True
        
        # Manually trigger initial game start
        log.info("[games.uci] Triggering initial game start")
        self._on_game_event(GameEvent.NEW_GAME)
        time.sleep(0.5)
        self._on_game_event(GameEvent.WHITE_TURN)
    
    def stop(self) -> None:
        """Stop the UCI engine controller and clean up resources."""
        if not self._running:
            return
        
        log.info("[games.uci] Stopping UCI controller")
        self._kill_flag = True
        self._running = False
        
        # Cleanup engines
        self._cleanup_engines()
        
        # Unsubscribe from game manager
        if self._game_manager is not None:
            self._game_manager.unsubscribe()
            self._game_manager = None
        
        # Cleanup display
        try:
            board.ledsOff()
            board.unPauseEvents()
        except Exception:
            pass
    
    def _initialize_engines(self) -> None:
        """Initialize UCI chess engines."""
        try:
            # Main playing engine
            log.info(f"[games.uci] Initializing engine: {self._engine_path}")
            self._engine = chess.engine.SimpleEngine.popen_uci(self._engine_path)
            
            # Configure engine options if provided
            if self._engine_options:
                log.info(f"[games.uci] Configuring engine with options: {self._engine_options}")
                self._engine.configure(self._engine_options)
            
            # Analysis engine (for evaluation graphs if needed)
            # Use same engine for analysis
            self._analysis_engine = self._engine
            
            log.info("[games.uci] Engines initialized successfully")
        except Exception as e:
            log.error(f"[games.uci] Error initializing engines: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _cleanup_engines(self) -> None:
        """Clean up engine processes."""
        def cleanup_engine(engine, name):
            """Safely quit an engine."""
            if engine is None:
                return
            
            try:
                # Try graceful quit with timeout
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
                    # Force terminate if graceful quit didn't work
                    log.warning(f"[games.uci] {name} quit() timed out, attempting to kill process")
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
                    log.debug(f"[games.uci] {name} quit() raised: {quit_error[0]}")
            except Exception as e:
                log.warning(f"[games.uci] Error cleaning up {name}: {e}")
        
        cleanup_engine(self._engine, "engine")
        cleanup_engine(self._analysis_engine, "analysis_engine")
        
        self._engine = None
        self._analysis_engine = None
    
    def _cleanup_and_exit(self, signum=None, frame=None) -> None:
        """Clean up resources and exit gracefully."""
        log.info("[games.uci] Cleaning up and exiting...")
        self.stop()
        log.info("[games.uci] Goodbye!")
        sys.exit(0)
    
    def _on_game_event(self, event: GameEvent) -> None:
        """
        Handle game events from game manager.
        
        Args:
            event: GameEvent indicating what happened
        """
        if self._kill_flag:
            return
        
        log.info(f"[games.uci] Game event: {event}")
        
        try:
            if event == GameEvent.NEW_GAME:
                self._handle_new_game()
            elif event == GameEvent.WHITE_TURN:
                self._handle_turn(chess.WHITE)
            elif event == GameEvent.BLACK_TURN:
                self._handle_turn(chess.BLACK)
            elif event == GameEvent.RESIGN_GAME:
                if self._game_manager is not None:
                    side = 1 if self._computer_color == chess.WHITE else 2
                    self._game_manager.resign_game(side)
            elif isinstance(event, str) and event.startswith("Termination."):
                self._handle_game_over(event)
        except Exception as e:
            log.error(f"[games.uci] Error handling game event: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_new_game(self) -> None:
        """Handle new game event."""
        log.info("[games.uci] Handling new game")
        
        # Clear any pending computer moves
        if self._game_manager is not None:
            self._game_manager.clear_computer_move()
        
        board.ledsOff()
        
        # Reset board state
        if self._game_manager is not None:
            self._game_manager.reset_board()
        
        # Clear display
        epaper.quickClear()
        
        # Draw starting position
        if self._game_manager is not None:
            self._draw_board(self._game_manager.get_fen())
    
    def _handle_turn(self, turn: chess.Color) -> None:
        """
        Handle turn event.
        
        Args:
            turn: chess.WHITE or chess.BLACK indicating whose turn it is
        """
        log.info(f"[games.uci] Handling turn: {'White' if turn else 'Black'}")
        
        # Draw current board state
        if self._game_manager is not None:
            self._draw_board(self._game_manager.get_fen())
        
        # If it's the computer's turn, get engine move
        if turn == self._computer_color:
            self._get_engine_move()
    
    def _get_engine_move(self) -> None:
        """Get move from engine and set it up for the player to execute."""
        if self._engine is None or self._game_manager is None:
            return
        
        try:
            board_obj = self._game_manager.get_board()
            fen = self._game_manager.get_fen()
            
            log.info(f"[games.uci] Asking engine for move from FEN: {fen}")
            
            # Get move from engine
            limit = chess.engine.Limit(time=5)
            result = self._engine.play(board_obj, limit, info=chess.engine.INFO_ALL)
            
            move = result.move
            move_str = move.uci()
            
            log.info(f"[games.uci] Engine returned move: {move_str}")
            
            # Validate move is legal
            if move not in board_obj.legal_moves:
                log.error(f"[games.uci] ERROR: Move {move_str} is not legal!")
                return
            
            # Set up the move for player to execute
            self._game_manager.set_computer_move(move_str, forced=True)
            
            log.info("[games.uci] Computer move setup complete, waiting for player to move pieces")
            
        except Exception as e:
            log.error(f"[games.uci] Error getting engine move: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_move(self, move: str) -> None:
        """
        Handle move callback from game manager.
        
        Args:
            move: UCI move string
        """
        log.info(f"[games.uci] Move made: {move}")
        
        # Draw updated board state
        if self._game_manager is not None:
            self._draw_board(self._game_manager.get_fen())
    
    def _on_key_press(self, key) -> None:
        """
        Handle key press callback from game manager.
        
        Args:
            key: Key that was pressed
        """
        log.info(f"[games.uci] Key pressed: {key}")
        
        if key == board.Key.BACK:
            self.stop()
            self._kill_flag = True
    
    def _draw_board(self, fen: str) -> None:
        """
        Draw the current board state on the display.
        
        Args:
            fen: FEN string representing the board position
        """
        try:
            log.debug(f"[games.uci] Drawing board with FEN: {fen[:20]}...")
            
            # Parse FEN and draw board
            curfen = str(fen).split()[0]  # Get just the piece placement part
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
                    nfen = nfen + curfen[((rank - 1) * 8) + file]
            
            # Create board image
            lboard = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(lboard)
            chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            # Draw pieces
            for x in range(0, 64):
                pos = (x - 63) * -1
                row = (16 * (pos // 8))
                col = (x % 8) * 16
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
                piece_char = nfen[x]
                if piece_char == "P":
                    px = 16
                elif piece_char == "R":
                    px = 32
                elif piece_char == "N":
                    px = 48
                elif piece_char == "B":
                    px = 64
                elif piece_char == "Q":
                    px = 80
                elif piece_char == "K":
                    px = 96
                elif piece_char == "p":
                    px = 112
                elif piece_char == "r":
                    px = 128
                elif piece_char == "n":
                    px = 144
                elif piece_char == "b":
                    px = 160
                elif piece_char == "q":
                    px = 176
                elif piece_char == "k":
                    px = 192
                else:
                    # Empty square
                    continue
                
                # Draw piece
                piece = chessfont.crop((px, py, px+16, py+16))
                
                # Flip board if computer plays white
                if self._computer_color == chess.WHITE:
                    piece = piece.transpose(Image.FLIP_TOP_BOTTOM)
                    piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
                
                lboard.paste(piece, (col, row))
            
            # Draw board border
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            
            # Display on epaper
            epaper.drawImagePartial(0, 81, lboard)
            
        except Exception as e:
            log.error(f"[games.uci] Error drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_game_over(self, termination: str) -> None:
        """
        Handle game over event.
        
        Args:
            termination: Termination string (e.g., "Termination.CHECKMATE")
        """
        log.info(f"[games.uci] Game over: {termination}")
        
        # Display termination message
        try:
            image = Image.new('1', (128, 12), 255)
            draw = ImageDraw.Draw(image)
            font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
            txt = termination[12:] if termination.startswith("Termination.") else termination
            draw.text((30, 0), txt, font=font12, fill=0)
            epaper.drawImagePartial(0, 221, image)
            time.sleep(0.3)
            image = image.transpose(Image.FLIP_TOP_BOTTOM)
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
            epaper.drawImagePartial(0, 57, image)
            
            # Display result
            epaper.quickClear()
            image = Image.new('1', (128, 292), 255)
            draw = ImageDraw.Draw(image)
            font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
            draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
            
            if self._game_manager is not None:
                try:
                    result = self._game_manager.get_result()
                    draw.text((0, 20), "          " + result, font=font18, fill=0)
                except Exception:
                    draw.text((0, 20), "          Game Over", font=font18, fill=0)
            
            epaper.drawImagePartial(0, 0, image)
            time.sleep(10)
            
        except Exception as e:
            log.error(f"[games.uci] Error displaying game over: {e}")
        
        # Stop controller
        self.stop()


def main():
    """
    Main entry point for UCI engine controller.
    
    Command line arguments:
        argv[1]: Computer color ("white", "black", or "random")
        argv[2]: Engine name (e.g., "stockfish_pi")
        argv[3]: Optional UCI options section name (defaults to "Default")
    """
    if len(sys.argv) < 3:
        print("Usage: uci.py <white|black|random> <engine_name> [options_section]")
        sys.exit(1)
    
    engine_name = sys.argv[2]
    engine_path = str(
        (pathlib.Path(__file__).parent.parent / "engines" / engine_name).resolve()
    )
    
    # Load UCI options if provided
    engine_options = {}
    if len(sys.argv) > 3:
        options_section = sys.argv[3]
        uci_file_path = engine_path + ".uci"
        
        if os.path.exists(uci_file_path):
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(uci_file_path)
            
            if config.has_section(options_section):
                for item in config.items(options_section):
                    engine_options[item[0]] = item[1]
                
                # Filter out non-UCI metadata fields
                NON_UCI_FIELDS = ['Description']
                engine_options = {
                    k: v for k, v in engine_options.items()
                    if k not in NON_UCI_FIELDS
                }
            else:
                log.warning(
                    f"Section '{options_section}' not found in {uci_file_path}, "
                    "using default settings"
                )
        else:
            log.warning(f"UCI file not found: {uci_file_path}, using default settings")
    
    # Create and start controller
    controller = UCIEngineController(
        engine_path=engine_path,
        engine_options=engine_options
    )
    
    try:
        controller.start()
        
        # Main loop
        while controller._running and not controller._kill_flag:
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        log.info("[games.uci] Interrupted by user")
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
