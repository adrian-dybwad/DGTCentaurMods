"""
UCI chess engine interface for DGTCentaurMods.

This module:
- Reacts to events from games/manager.py
- Decides when to call the chess engine
- Handles UI/display updates
- Starts new games when pieces are in starting position
- Draws current board state on display
- Manages engine lifecycle
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
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.games.manager import GameManager, GameEvent
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log


class UCIEngine:
    """
    UCI chess engine interface that manages engine lifecycle and move generation.
    """
    
    def __init__(
        self,
        engine_path: str,
        analysis_engine_path: Optional[str] = None,
        uci_options: Optional[dict] = None
    ):
        """
        Initialize UCI engine interface.
        
        Args:
            engine_path: Path to the main chess engine executable
            analysis_engine_path: Optional path to analysis engine (for evaluation graphs)
            uci_options: Dictionary of UCI options to configure
        """
        self.engine_path = engine_path
        self.analysis_engine_path = analysis_engine_path
        self.uci_options = uci_options or {}
        
        self.engine: Optional[chess.engine.SimpleEngine] = None
        self.analysis_engine: Optional[chess.engine.SimpleEngine] = None
        self.computer_color: Optional[bool] = None  # True for white, False for black
        self.running = False
        
    def set_computer_color(self, color: bool):
        """
        Set which color the computer plays.
        
        Args:
            color: True for white, False for black
        """
        self.computer_color = color
    
    def start(self):
        """Start the engines."""
        if self.running:
            return
        
        try:
            log.info(f"[UCIEngine] Starting engine: {self.engine_path}")
            self.engine = chess.engine.SimpleEngine.popen_uci(self.engine_path, timeout=None)
            
            if self.uci_options:
                log.info(f"[UCIEngine] Configuring engine with options: {self.uci_options}")
                self.engine.configure(self.uci_options)
            
            if self.analysis_engine_path:
                log.info(f"[UCIEngine] Starting analysis engine: {self.analysis_engine_path}")
                self.analysis_engine = chess.engine.SimpleEngine.popen_uci(
                    self.analysis_engine_path,
                    timeout=None
                )
            
            self.running = True
            log.info("[UCIEngine] Engines started successfully")
        except Exception as e:
            log.error(f"[UCIEngine] Error starting engines: {e}")
            raise
    
    def stop(self):
        """Stop the engines gracefully."""
        if not self.running:
            return
        
        log.info("[UCIEngine] Stopping engines")
        self.running = False
        
        def cleanup_engine(engine, name: str):
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
                    log.warning(f"[UCIEngine] {name} quit() timed out, attempting to kill process")
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
                    log.debug(f"[UCIEngine] {name} quit() raised: {quit_error[0]}")
            except Exception as e:
                log.warning(f"[UCIEngine] Error cleaning up {name}: {e}")
        
        cleanup_engine(self.engine, "engine")
        cleanup_engine(self.analysis_engine, "analysis_engine")
        
        self.engine = None
        self.analysis_engine = None
        log.info("[UCIEngine] Engines stopped")
    
    def play_move(self, board: chess.Board, time_limit: float = 5.0) -> Optional[chess.Move]:
        """
        Get a move from the engine for the given board position.
        
        Args:
            board: Current chess board position
            time_limit: Time limit in seconds for engine to think
            
        Returns:
            Move object or None if error
        """
        if not self.running or self.engine is None:
            return None
        
        try:
            limit = chess.engine.Limit(time=time_limit)
            result = self.engine.play(board, limit, info=chess.engine.INFO_ALL)
            return result.move
        except Exception as e:
            log.error(f"[UCIEngine] Error getting move: {e}")
            return None
    
    def analyze(self, board: chess.Board, time_limit: float = 0.5) -> Optional[dict]:
        """
        Analyze position using analysis engine.
        
        Args:
            board: Current chess board position
            time_limit: Time limit in seconds for analysis
            
        Returns:
            Analysis info dict or None if error
        """
        if not self.running or self.analysis_engine is None:
            return None
        
        try:
            limit = chess.engine.Limit(time=time_limit)
            info = self.analysis_engine.analyse(board, limit)
            return info
        except Exception as e:
            log.error(f"[UCIEngine] Error analyzing position: {e}")
            return None


class UCIGame:
    """
    Main UCI game controller that coordinates game manager and engine.
    """
    
    def __init__(
        self,
        engine_path: str,
        analysis_engine_path: Optional[str] = None,
        computer_color: str = "white",
        uci_options: Optional[dict] = None
    ):
        """
        Initialize UCI game.
        
        Args:
            engine_path: Path to chess engine executable
            analysis_engine_path: Optional path to analysis engine
            computer_color: "white", "black", or "random"
            uci_options: Dictionary of UCI options
        """
        # Determine computer color
        if computer_color == "random":
            import random
            computer_color_bool = random.choice([True, False])
        elif computer_color == "black":
            computer_color_bool = False
        else:
            computer_color_bool = True
        
        # Initialize engine
        self.engine = UCIEngine(engine_path, analysis_engine_path, uci_options)
        self.engine.set_computer_color(computer_color_bool)
        
        # Initialize game manager
        self.game_manager = GameManager(
            event_callback=self._on_game_event,
            move_callback=self._on_move_made,
            key_callback=self._on_key_pressed
        )
        
        self.running = False
        self.kill_flag = threading.Event()
        self._cleanup_done = False
        
        # Display state
        self.graphs_enabled = os.uname().machine == "armv7l"  # Enable on Pi Zero 2W
        
    def _on_game_event(self, event: GameEvent, event_data: dict):
        """Handle game events from game manager."""
        try:
            log.info(f"[UCIGame] Event received: {event.name}")
            
            if event == GameEvent.NEW_GAME:
                log.info("[UCIGame] New game started")
                epaper.quickClear()
                self._draw_board(self.game_manager.get_fen())
                
            elif event == GameEvent.WHITE_TURN:
                log.info("[UCIGame] White's turn")
                self._draw_board(self.game_manager.get_fen())
                
                # Check if it's computer's turn
                if self.engine.computer_color == chess.WHITE:
                    self._play_computer_move()
                elif self.graphs_enabled and self.engine.analysis_engine:
                    # Show evaluation graphs
                    info = self.engine.analyze(self.game_manager.get_board(), time_limit=0.5)
                    if info:
                        self._draw_evaluation_graphs(info)
                
            elif event == GameEvent.BLACK_TURN:
                log.info("[UCIGame] Black's turn")
                self._draw_board(self.game_manager.get_fen())
                
                # Check if it's computer's turn
                if self.engine.computer_color == chess.BLACK:
                    self._play_computer_move()
                elif self.graphs_enabled and self.engine.analysis_engine:
                    # Show evaluation graphs
                    info = self.engine.analyze(self.game_manager.get_board(), time_limit=0.5)
                    if info:
                        self._draw_evaluation_graphs(info)
                
            elif event == GameEvent.GAME_OVER:
                log.info(f"[UCIGame] Game over: {event_data.get('result', 'Unknown')}")
                self._draw_game_over_screen(event_data)
                time.sleep(10)
                self.stop()
                
            elif event == GameEvent.TAKEBACK:
                log.info("[UCIGame] Takeback detected")
                self._draw_board(self.game_manager.get_fen())
                # Re-trigger turn event
                if self.game_manager.get_board().turn == chess.WHITE:
                    self._on_game_event(GameEvent.WHITE_TURN, {"fen": self.game_manager.get_fen()})
                else:
                    self._on_game_event(GameEvent.BLACK_TURN, {"fen": self.game_manager.get_fen()})
                    
        except Exception as e:
            log.error(f"[UCIGame] Error handling game event: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_move_made(self, move: str):
        """Handle move made callback."""
        try:
            log.info(f"[UCIGame] Move made: {move}")
            self._draw_board(self.game_manager.get_fen())
        except Exception as e:
            log.error(f"[UCIGame] Error handling move: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_key_pressed(self, key: int):
        """Handle key press callback."""
        try:
            log.info(f"[UCIGame] Key pressed: {key}")
            if key == board.Key.BACK:
                self.stop()
        except Exception as e:
            log.error(f"[UCIGame] Error handling key press: {e}")
    
    def _play_computer_move(self):
        """Get and execute computer move."""
        try:
            log.info("[UCIGame] Computer's turn - requesting move")
            board_obj = self.game_manager.get_board()
            move = self.engine.play_move(board_obj, time_limit=5.0)
            
            if move:
                move_str = move.uci()
                log.info(f"[UCIGame] Engine returned move: {move_str}")
                self.game_manager.set_computer_move(move_str, forced=True)
            else:
                log.error("[UCIGame] Engine returned no move")
        except Exception as e:
            log.error(f"[UCIGame] Error playing computer move: {e}")
            import traceback
            traceback.print_exc()
    
    def _draw_board(self, fen: str):
        """Draw chess board on display."""
        try:
            epaper.drawFen(fen, startrow=2)
        except Exception as e:
            log.error(f"[UCIGame] Error drawing board: {e}")
    
    def _draw_evaluation_graphs(self, info: dict):
        """Draw evaluation graphs on display."""
        # This is a simplified version - full implementation would match original
        # For now, just log that analysis is available
        if "score" in info:
            log.debug(f"[UCIGame] Evaluation: {info['score']}")
    
    def _draw_game_over_screen(self, event_data: dict):
        """Draw game over screen."""
        try:
            result = event_data.get("result", "Unknown")
            termination = event_data.get("termination", "")
            
            image = Image.new('1', (128, 292), 255)
            draw = ImageDraw.Draw(image)
            font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
            
            draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
            draw.text((0, 20), "          " + result, font=font18, fill=0)
            
            epaper.drawImagePartial(0, 0, image)
        except Exception as e:
            log.error(f"[UCIGame] Error drawing game over screen: {e}")
    
    def start(self):
        """Start the UCI game."""
        if self.running:
            return
        
        log.info("[UCIGame] Starting UCI game")
        
        # Initialize display
        epaper.initEpaper()
        
        # Start engine
        self.engine.start()
        
        # Start game manager
        self.game_manager.start()
        
        self.running = True
        self.kill_flag.clear()
        
        log.info("[UCIGame] UCI game started")
    
    def stop(self):
        """Stop the UCI game."""
        if self._cleanup_done:
            return
        
        self._cleanup_done = True
        log.info("[UCIGame] Stopping UCI game")
        self.running = False
        self.kill_flag.set()
        
        # Stop game manager
        try:
            self.game_manager.stop()
        except Exception as e:
            log.warning(f"[UCIGame] Error stopping game manager: {e}")
        
        # Stop engine
        try:
            self.engine.stop()
        except Exception as e:
            log.warning(f"[UCIGame] Error stopping engine: {e}")
        
        # Cleanup board
        try:
            board.ledsOff()
            board.unPauseEvents()
            board.cleanup(leds_off=True)
        except Exception as e:
            log.warning(f"[UCIGame] Error cleaning up board: {e}")
        
        log.info("[UCIGame] UCI game stopped")
    
    def run(self):
        """Run the UCI game main loop."""
        self.start()
        
        try:
            while self.running and not self.kill_flag.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("[UCIGame] Keyboard interrupt received in main loop")
        except Exception as e:
            log.error(f"[UCIGame] Error in main loop: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.stop()


def load_uci_options(engine_path: str, options_section: str = "Default") -> dict:
    """
    Load UCI options from .uci file.
    
    Args:
        engine_path: Path to engine executable
        options_section: Section name in UCI file (default: "Default")
        
    Returns:
        Dictionary of UCI options
    """
    uci_file_path = engine_path + ".uci"
    uci_options = {}
    
    if os.path.exists(uci_file_path):
        try:
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(uci_file_path)
            
            if config.has_section(options_section):
                for item in config.items(options_section):
                    uci_options[item[0]] = item[1]
                
                # Filter out non-UCI metadata fields
                NON_UCI_FIELDS = ['Description']
                uci_options = {k: v for k, v in uci_options.items() if k not in NON_UCI_FIELDS}
            else:
                log.warning(f"Section '{options_section}' not found in {uci_file_path}, using Default")
                if config.has_section("Default"):
                    for item in config.items("Default"):
                        uci_options[item[0]] = item[1]
                    NON_UCI_FIELDS = ['Description']
                    uci_options = {k: v for k, v in uci_options.items() if k not in NON_UCI_FIELDS}
        except Exception as e:
            log.warning(f"Error loading UCI options from {uci_file_path}: {e}")
    else:
        log.warning(f"UCI file not found: {uci_file_path}, using default settings")
    
    return uci_options


# Global reference to game instance for signal handler
_game_instance: Optional[UCIGame] = None

def cleanup_and_exit(signum=None, frame=None):
    """Cleanup handler for signals."""
    global _game_instance
    log.info(">>> Signal received, cleaning up and exiting...")
    if _game_instance:
        try:
            _game_instance.stop()
        except Exception as e:
            log.warning(f"Error during signal cleanup: {e}")
    sys.exit(0)


def main():
    """Main entry point for UCI game."""
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, cleanup_and_exit)
    try:
        signal.signal(signal.SIGTERM, cleanup_and_exit)
    except Exception:
        pass
    
    # Parse command line arguments
    computer_color = sys.argv[1] if len(sys.argv) > 1 else "white"
    engine_name = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    uci_options_section = sys.argv[3] if len(sys.argv) > 3 else "Default"
    
    log.info(f"[UCI] Starting with computer_color={computer_color}, engine={engine_name}")
    
    # Resolve engine paths
    base_path = pathlib.Path(__file__).parent.parent
    engine_path = str((base_path / "engines" / engine_name).resolve())
    analysis_engine_path = str((base_path / "engines" / "ct800").resolve())
    
    log.info(f"[UCI] Engine path: {engine_path}")
    log.info(f"[UCI] Analysis engine path: {analysis_engine_path}")
    
    # Load UCI options
    uci_options = load_uci_options(engine_path, uci_options_section)
    
    # Create and run game
    global _game_instance
    game = UCIGame(
        engine_path=engine_path,
        analysis_engine_path=analysis_engine_path,
        computer_color=computer_color,
        uci_options=uci_options
    )
    _game_instance = game
    
    try:
        game.run()
    except KeyboardInterrupt:
        log.info("[UCI] Keyboard interrupt received")
    except Exception as e:
        log.error(f"[UCI] Error running game: {e}")
        import traceback
        traceback.print_exc()
    finally:
        game.stop()
        _game_instance = None
        log.info("[UCI] Exiting")


if __name__ == "__main__":
    main()

