"""
UCI chess engine interface for playing against computer engines.

This module handles engine lifecycle, UI/display updates, and reacts to
game manager events to decide when to call the engine.

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
import pathlib
import configparser
import signal
import threading
import time
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


class UCIEngine:
    """
    Manages UCI chess engine lifecycle and gameplay.
    
    Reacts to game manager events to decide when to call the engine,
    handles UI/display updates, and manages engine processes.
    """
    
    def __init__(self, player_color: str, engine_name: str, engine_options_desc: str = "Default"):
        """
        Initialize UCI engine interface.
        
        Args:
            player_color: "white", "black", or "random" - which color the player plays
            engine_name: Name of the engine executable (e.g., "stockfish_pi")
            engine_options_desc: Section name in .uci config file for engine options
        """
        # Determine computer color
        if player_color == "white":
            self._computer_color = chess.BLACK
        elif player_color == "black":
            self._computer_color = chess.WHITE
        elif player_color == "random":
            self._computer_color = chess.WHITE if randint(0, 1) == 1 else chess.BLACK
        else:
            self._computer_color = chess.BLACK  # Default
        
        self._engine_name = engine_name
        self._engine_options_desc = engine_options_desc
        
        # Engine instances
        self._analysis_engine: Optional[chess.engine.SimpleEngine] = None
        self._play_engine: Optional[chess.engine.SimpleEngine] = None
        self._engine_options = {}
        
        # Game manager
        self._manager = GameManager()
        
        # State
        self._running = True
        self._current_turn = chess.WHITE
        
        # Load engine configuration
        self._load_engine_config()
        
        # Initialize engines
        self._init_engines()
        
        # Initialize display
        epaper.initEpaper()
        
        # Subscribe to game manager events (this starts the manager)
        self._manager.subscribe(
            event_callback=self._on_game_event,
            move_callback=self._on_move_made,
            key_callback=self._on_key_pressed
        )
        
        # Check for starting position after a short delay to allow board to initialize
        time.sleep(0.5)
        self._check_starting_position()
    
    def _load_engine_config(self):
        """Load engine options from .uci config file."""
        engines_dir = pathlib.Path(__file__).parent.parent / "engines"
        engine_path = engines_dir / self._engine_name
        uci_file_path = str(engine_path) + ".uci"
        
        if os.path.exists(uci_file_path):
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(uci_file_path)
            
            if config.has_section(self._engine_options_desc):
                self._engine_options = dict(config.items(self._engine_options_desc))
            elif config.has_section("DEFAULT"):
                self._engine_options = dict(config.items("DEFAULT"))
                self._engine_options_desc = "Default"
            
            # Filter out non-UCI metadata fields
            NON_UCI_FIELDS = ['Description']
            self._engine_options = {k: v for k, v in self._engine_options.items() 
                                  if k not in NON_UCI_FIELDS}
            log.info(f"[UCIEngine] Loaded engine options: {self._engine_options}")
        else:
            log.warning(f"[UCIEngine] UCI config file not found: {uci_file_path}")
    
    def _init_engines(self):
        """Initialize analysis and play engines."""
        engines_dir = pathlib.Path(__file__).parent.parent / "engines"
        ct800_path = str((engines_dir / "ct800").resolve())
        play_engine_path = str((engines_dir / self._engine_name).resolve())
        
        try:
            self._analysis_engine = chess.engine.SimpleEngine.popen_uci(ct800_path, timeout=None)
            log.info(f"[UCIEngine] Analysis engine initialized: {ct800_path}")
        except Exception as e:
            log.error(f"[UCIEngine] Failed to initialize analysis engine: {e}")
        
        try:
            self._play_engine = chess.engine.SimpleEngine.popen_uci(play_engine_path)
            log.info(f"[UCIEngine] Play engine initialized: {play_engine_path}")
            
            # Configure engine with options
            if self._engine_options:
                self._play_engine.configure(self._engine_options)
                log.info(f"[UCIEngine] Engine configured with options")
        except Exception as e:
            log.error(f"[UCIEngine] Failed to initialize play engine: {e}")
            raise
    
    def _check_starting_position(self):
        """Check if board is in starting position and start game if so."""
        current_state = board.getChessState()
        starting_state = GameManager.STARTING_STATE
        
        if current_state and bytearray(current_state) == starting_state:
            log.info("[UCIEngine] Starting position detected - starting new game")
            self._on_game_event(GameEvent.NEW_GAME, {"fen": GameManager.STARTING_FEN})
            time.sleep(0.5)
            self._on_game_event(GameEvent.WHITE_TURN, {"fen": GameManager.STARTING_FEN})
    
    def _on_game_event(self, event: GameEvent, data: dict):
        """
        Handle game events from the manager.
        
        Args:
            event: GameEvent enum
            data: Event data dictionary
        """
        log.info(f"[UCIEngine] Game event: {event.name}")
        
        try:
            if event == GameEvent.NEW_GAME:
                self._handle_new_game(data)
            elif event == GameEvent.WHITE_TURN:
                self._current_turn = chess.WHITE
                self._handle_turn_change()
            elif event == GameEvent.BLACK_TURN:
                self._current_turn = chess.BLACK
                self._handle_turn_change()
            elif event == GameEvent.GAME_OVER:
                self._handle_game_over(data)
            elif event == GameEvent.TAKEBACK:
                self._handle_takeback()
        except Exception as e:
            log.error(f"[UCIEngine] Error handling game event: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_new_game(self, data: dict):
        """Handle new game event."""
        log.info("[UCIEngine] New game started")
        fen = data.get("fen", GameManager.STARTING_FEN)
        self._draw_board(fen)
    
    def _handle_turn_change(self):
        """Handle turn change - decide if engine should move."""
        self._draw_board(self._manager.get_fen())
        
        if self._current_turn == self._computer_color:
            # Computer's turn - get move from engine
            self._get_computer_move()
        else:
            # Player's turn - wait for move
            log.info(f"[UCIEngine] Waiting for player move ({'White' if self._current_turn == chess.WHITE else 'Black'})")
    
    def _handle_game_over(self, data: dict):
        """Handle game over event."""
        result = data.get("result", "Unknown")
        termination = data.get("termination", "Unknown")
        log.info(f"[UCIEngine] Game over: {result} ({termination})")
        
        # Display game over screen
        self._draw_game_over_screen(result, termination)
        
        # Stop after delay
        time.sleep(10)
        self._running = False
    
    def _handle_takeback(self):
        """Handle takeback event."""
        log.info("[UCIEngine] Takeback detected")
        self._manager.clear_forced_move()
        self._draw_board(self._manager.get_fen())
    
    def _on_move_made(self, move: str):
        """Handle move made event."""
        log.info(f"[UCIEngine] Move made: {move}")
        self._draw_board(self._manager.get_fen())
    
    def _on_key_pressed(self, key: board.Key):
        """Handle key press events."""
        log.info(f"[UCIEngine] Key pressed: {key}")
        if key == board.Key.BACK:
            self._running = False
    
    def _get_computer_move(self):
        """Get move from engine and set it as forced move."""
        if not self._play_engine:
            log.error("[UCIEngine] Play engine not available")
            return
        
        try:
            log.info(f"[UCIEngine] Getting computer move (color: {'White' if self._computer_color == chess.WHITE else 'Black'})")
            
            # Configure engine options if needed
            if self._engine_options:
                self._play_engine.configure(self._engine_options)
            
            # Get move from engine
            limit = chess.engine.Limit(time=5)
            result = self._play_engine.play(self._manager.get_board(), limit, info=chess.engine.INFO_ALL)
            
            move = result.move
            move_str = move.uci()
            log.info(f"[UCIEngine] Engine move: {move_str}")
            
            # Set as forced move
            self._manager.set_forced_move(move_str)
            
        except Exception as e:
            log.error(f"[UCIEngine] Error getting computer move: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_board(self, fen: str):
        """
        Draw the current board state on the display.
        
        Args:
            fen: FEN string representing board position
        """
        try:
            log.info(f"[UCIEngine] Drawing board: {fen[:30]}...")
            
            # Parse FEN to extract piece positions
            fen_parts = fen.split()
            fen_board = fen_parts[0]
            
            # Convert FEN to display format
            curfen = fen_board.replace("/", "")
            for num in range(1, 9):
                curfen = curfen.replace(str(num), " " * num)
            
            # Reorder for display (rank 8 to rank 1)
            nfen = ""
            for rank in range(8, 0, -1):
                for file in range(0, 8):
                    nfen += curfen[((rank - 1) * 8) + file]
            
            # Create board image
            board_image = Image.new('1', (128, 128), 255)
            draw = ImageDraw.Draw(board_image)
            chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
            
            # Draw pieces
            for square_idx in range(64):
                pos = (square_idx - 63) * -1
                row = (16 * (pos // 8))
                col = (square_idx % 8) * 16
                
                piece_char = nfen[square_idx]
                if piece_char == " ":
                    continue
                
                # Calculate sprite position
                px, py = self._get_piece_sprite_pos(piece_char, square_idx)
                
                # Crop piece sprite
                piece_sprite = chessfont.crop((px, py, px + 16, py + 16))
                
                # Flip if computer is white (board orientation)
                if self._computer_color == chess.WHITE:
                    piece_sprite = piece_sprite.transpose(Image.FLIP_TOP_BOTTOM)
                    piece_sprite = piece_sprite.transpose(Image.FLIP_LEFT_RIGHT)
                
                board_image.paste(piece_sprite, (col, row))
            
            # Draw board border
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
            
            # Display on epaper
            epaper.drawImagePartial(0, 81, board_image)
            
        except Exception as e:
            log.error(f"[UCIEngine] Error drawing board: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_piece_sprite_pos(self, piece_char: str, square_idx: int) -> tuple[int, int]:
        """
        Get sprite position for a piece character.
        
        Args:
            piece_char: Piece character (P, R, N, B, Q, K or lowercase)
            square_idx: Square index for determining square color
            
        Returns:
            (px, py) sprite coordinates
        """
        px = 0
        py = 0
        
        # Calculate square color (for background)
        r = square_idx // 8
        c = square_idx % 8
        if (r // 2 == r / 2 and c // 2 == c / 2) or (r // 2 != r / 2 and c // 2 != c / 2):
            py = 16
        
        # Map piece to sprite x position
        piece_map = {
            'P': 16, 'R': 32, 'N': 48, 'B': 64, 'Q': 80, 'K': 96,
            'p': 112, 'r': 128, 'n': 144, 'b': 160, 'q': 176, 'k': 192
        }
        
        px = piece_map.get(piece_char, 0)
        return px, py
    
    def _draw_game_over_screen(self, result: str, termination: str):
        """Draw game over screen."""
        try:
            image = Image.new('1', (128, 292), 255)
            draw = ImageDraw.Draw(image)
            font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
            
            draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
            draw.text((0, 20), "          " + result, font=font18, fill=0)
            
            epaper.drawImagePartial(0, 0, image)
        except Exception as e:
            log.error(f"[UCIEngine] Error drawing game over screen: {e}")
    
    def run(self):
        """Run the UCI engine interface."""
        try:
            while self._running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("[UCIEngine] Interrupted by user")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources."""
        log.info("[UCIEngine] Cleaning up...")
        self._running = False
        
        # Clean up engines
        self._cleanup_engine(self._analysis_engine, "analysis")
        self._cleanup_engine(self._play_engine, "play")
        
        # Clean up manager
        self._manager.unsubscribe()
        
        # Clean up hardware
        try:
            board.ledsOff()
        except:
            pass
        
        log.info("[UCIEngine] Cleanup complete")
    
    def _cleanup_engine(self, engine: Optional[chess.engine.SimpleEngine], name: str):
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
                log.warning(f"[UCIEngine] {name} engine quit() timed out, attempting to kill")
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
            
            if quit_error:
                log.debug(f"[UCIEngine] {name} engine quit() raised: {quit_error[0]}")
        except Exception as e:
            log.warning(f"[UCIEngine] Error cleaning up {name} engine: {e}")


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
    engine_options_desc = sys.argv[3] if len(sys.argv) > 3 else "Default"
    
    log.info(f"[UCI] Starting UCI engine interface")
    log.info(f"[UCI] Player color: {player_color}, Engine: {engine_name}, Options: {engine_options_desc}")
    
    try:
        uci = UCIEngine(player_color, engine_name, engine_options_desc)
        uci.run()
    except Exception as e:
        log.error(f"[UCI] Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

