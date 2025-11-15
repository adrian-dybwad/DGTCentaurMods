"""
UCI chess engine interface for DGTCentaurMods.

This module provides a clean UCI interface that:
- Reacts to events from GameManager
- Manages engine lifecycle
- Handles UI/display updates
- Decides when to call the engine
- Detects starting position for new game
- Handles graceful shutdown with Ctrl+C
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
import time
import signal
import configparser
from PIL import Image, ImageDraw, ImageFont
from random import randint
from typing import Optional

# Global state
_kill = False
_cleaned_up = False
_computer_on_turn = 0  # 0 = black, 1 = white
_cur_turn = 1  # 1 = white, 0 = black
_manager: Optional[GameManager] = None
_analysis_engine: Optional[chess.engine.SimpleEngine] = None
_player_engine: Optional[chess.engine.SimpleEngine] = None
_graphs_on = 0  # Default to graphs off
_score_history = []
_first_move = 1
MAX_SCOREHISTORY_SIZE = 200


def _cleanup_engine(engine: Optional[chess.engine.SimpleEngine], name: str):
    """Safely quit an engine with timeout"""
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


def _do_cleanup():
    """Clean up all resources"""
    global _cleaned_up
    if _cleaned_up:
        return
    _cleaned_up = True
    
    try:
        _cleanup_engine(_analysis_engine, "analysis_engine")
    except:
        pass
    
    try:
        _cleanup_engine(_player_engine, "player_engine")
    except:
        pass
    
    try:
        board.ledsOff()
    except:
        pass
    
    try:
        board.unPauseEvents()
    except:
        pass
    
    try:
        if _manager:
            _manager.stop()
    except:
        pass
    
    try:
        board.cleanup(leds_off=True)
    except:
        pass


def _cleanup_and_exit(signum=None, frame=None):
    """Clean up resources and exit gracefully"""
    global _kill, _cleaned_up
    if _cleaned_up:
        os._exit(0)
    
    log.info(">>> Cleaning up and exiting...")
    _kill = True
    try:
        _do_cleanup()
    except KeyboardInterrupt:
        log.warning(">>> Interrupted during cleanup, forcing exit")
        os._exit(1)
    except Exception as e:
        log.warning(f">>> Error during cleanup: {e}")
    log.info("Goodbye!")
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGINT, _cleanup_and_exit)
try:
    signal.signal(signal.SIGTERM, _cleanup_and_exit)
except Exception:
    pass


def _write_text_local(row: int, txt: str):
    """Write text on a given line number"""
    image = Image.new('1', (128, 20), 255)
    draw = ImageDraw.Draw(image)
    font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
    draw.text((0, 0), txt, font=font18, fill=0)
    epaper.drawImagePartial(0, (row * 20), image)


def _draw_board_local(fen: str):
    """Draw the chess board on the display"""
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
        for a in range(8, 0, -1):
            for b in range(0, 8):
                nfen = nfen + curfen[((a - 1) * 8) + b]
        lboard = Image.new('1', (128, 128), 255)
        draw = ImageDraw.Draw(lboard)
        chessfont = Image.open(AssetManager.get_resource_path("chesssprites.bmp"))
        for x in range(0, 64):
            pos = (x - 63) * -1
            row = (16 * (pos // 8))
            col = (x % 8) * 16
            px = 0
            r = x // 8
            c = x % 8
            py = 0
            if (r // 2 == r / 2 and c // 2 == c / 2):
                py = py + 16
            if (r // 2 != r / 2 and c // 2 == c / 2):
                py = py + 16
            if nfen[x] == "P":
                px = 16
            if nfen[x] == "R":
                px = 32
            if nfen[x] == "N":
                px = 48
            if nfen[x] == "B":
                px = 64
            if nfen[x] == "Q":
                px = 80
            if nfen[x] == "K":
                px = 96
            if nfen[x] == "p":
                px = 112
            if nfen[x] == "r":
                px = 128
            if nfen[x] == "n":
                px = 144
            if nfen[x] == "b":
                px = 160
            if nfen[x] == "q":
                px = 176
            if nfen[x] == "k":
                px = 192
            piece = chessfont.crop((px, py, px + 16, py + 16))
            if _computer_on_turn == 1:
                piece = piece.transpose(Image.FLIP_TOP_BOTTOM)
                piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
            lboard.paste(piece, (col, row))
        draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
        epaper.drawImagePartial(0, 81, lboard)
    except Exception as e:
        log.error(f"Error in drawBoardLocal: {e}")
        import traceback
        traceback.print_exc()


def _evaluation_graphs(info):
    """Draw evaluation graphs to the screen"""
    global _first_move, _graphs_on, _score_history, _cur_turn
    
    if "score" not in info:
        log.info("evaluationGraphs: No score in info, skipping")
        return
    
    if _graphs_on == 0:
        image = Image.new('1', (128, 80), 255)
        epaper.drawImagePartial(0, 209, image)
        epaper.drawImagePartial(0, 1, image)
    
    sval = 0
    sc = str(info["score"])
    if "Mate" in sc:
        sval = 10000
        sval = sc[13:24]
        sval = sval[1:sval.find(")")]
    else:
        sval = sc[11:24]
        sval = sval[1:sval.find(")")]
    sval = float(sval)
    sval = sval / 100
    if "BLACK" in sc:
        sval = sval * -1
    
    if _graphs_on == 1:
        image = Image.new('1', (128, 80), 255)
        draw = ImageDraw.Draw(image)
        font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
    
    txt = "{:5.1f}".format(sval)
    if sval > 999:
        txt = ""
    if "Mate" in sc:
        txt = "Mate in " + "{:2.0f}".format(abs(sval * 100))
        sval = sval * 100000
    
    if _graphs_on == 1:
        draw.text((50, 12), txt, font=font12, fill=0)
        draw.rectangle([(0, 1), (127, 11)], fill=None, outline='black')
    
    if sval > 12:
        sval = 12
    if sval < -12:
        sval = -12
    
    if _first_move == 0:
        _score_history.append(sval)
        if len(_score_history) > MAX_SCOREHISTORY_SIZE:
            _score_history.pop(0)
    else:
        _first_move = 0
    
    offset = (128 / 25) * (sval + 12)
    if offset < 128:
        if _graphs_on == 1:
            draw.rectangle([(offset, 1), (127, 11)], fill=0, outline='black')
    
    if _graphs_on == 1:
        if len(_score_history) > 0:
            draw.line([(0, 50), (128, 50)], fill=0, width=1)
            barwidth = 128 / len(_score_history)
            if barwidth > 8:
                barwidth = 8
            baroffset = 0
            for i in range(0, len(_score_history)):
                if _score_history[i] >= 0:
                    col = 255
                else:
                    col = 0
                y_calc = 50 - (_score_history[i] * 2)
                y0 = min(50, y_calc)
                y1 = max(50, y_calc)
                draw.rectangle([(baroffset, y0), (baroffset + barwidth, y1)], fill=col, outline='black')
                baroffset = baroffset + barwidth
        tmp = image.copy()
        dr2 = ImageDraw.Draw(tmp)
        if _cur_turn == 1:
            dr2.ellipse((119, 14, 126, 21), fill=0, outline=0)
        epaper.drawImagePartial(0, 209, tmp)
        if _cur_turn == 0:
            draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        epaper.drawImagePartial(0, 1, image)


def _execute_computer_move(mv: str):
    """Execute the computer move by setting up LEDs and flags"""
    try:
        log.info(f"Setting up computer move: {mv}")
        board_obj = _manager.get_board()
        log.info(f"Current FEN: {_manager.get_fen()}")
        log.info(f"Legal moves: {[str(m) for m in list(board_obj.legal_moves)[:5]]}...")
        
        # Validate the move is legal
        move = chess.Move.from_uci(mv)
        if move not in board_obj.legal_moves:
            log.error(f"ERROR: Move {mv} is not legal! This should not happen.")
            log.error(f"Legal moves: {list(board_obj.legal_moves)}")
            raise ValueError(f"Illegal move: {mv}")
        
        # Use manager to set up forced move
        log.info(f"Setting up manager for forced move")
        _manager.set_forced_move(mv)
        
        log.info("Computer move setup complete. Waiting for player to move pieces on board.")
        return
    except Exception as e:
        log.error(f"Error in executeComputerMove: {e}")
        import traceback
        traceback.print_exc()


def _event_callback(event: GameEvent, *args):
    """Handle game events from GameManager"""
    global _cur_turn, _kill, _score_history, _first_move
    
    try:
        log.info(f"EventCallback triggered with event: {event}")
        
        if event == GameEvent.NEW_GAME:
            log.info("EVENT_NEW_GAME: Resetting board to starting position")
            _manager.clear_forced_move()
            board.ledsOff()
            epaper.quickClear()
            _score_history = []
            _cur_turn = 1
            _first_move = 1
            epaper.pauseEpaper()
            _draw_board_local(_manager.get_fen())
            log.info(f"Board reset. FEN: {_manager.get_fen()}")
            if _graphs_on == 1 and _analysis_engine:
                info = _analysis_engine.analyse(_manager.get_board(), chess.engine.Limit(time=0.1))
                _evaluation_graphs(info)
            epaper.unPauseEpaper()
        
        elif event == GameEvent.WHITE_TURN:
            _cur_turn = 1
            log.info(f"WHITE_TURN event: curturn={_cur_turn}, computeronturn={_computer_on_turn}")
            if _graphs_on == 1 and _analysis_engine:
                info = _analysis_engine.analyse(_manager.get_board(), chess.engine.Limit(time=0.5))
                epaper.pauseEpaper()
                _evaluation_graphs(info)
                epaper.unPauseEpaper()
            _draw_board_local(_manager.get_fen())
            
            if _cur_turn == _computer_on_turn:
                log.info(f"Computer's turn! Current FEN: {_manager.get_fen()}")
                if _player_engine:
                    limit = chess.engine.Limit(time=5)
                    log.info(f"Asking engine to play from FEN: {_manager.get_fen()}")
                    try:
                        mv = _player_engine.play(_manager.get_board(), limit, info=chess.engine.INFO_ALL)
                        log.info(f"Engine returned: {mv}")
                        mv = mv.move
                        log.info(f"Move extracted: {mv}")
                        log.info(f"Executing move: {str(mv)}")
                        _execute_computer_move(str(mv))
                    except Exception as e:
                        log.error(f"Error in WHITE_TURN computer move: {e}")
                        import traceback
                        traceback.print_exc()
        
        elif event == GameEvent.BLACK_TURN:
            _cur_turn = 0
            log.info(f"BLACK_TURN event: curturn={_cur_turn}, computeronturn={_computer_on_turn}")
            if _graphs_on == 1 and _analysis_engine:
                info = _analysis_engine.analyse(_manager.get_board(), chess.engine.Limit(time=0.5))
                epaper.pauseEpaper()
                _evaluation_graphs(info)
                epaper.unPauseEpaper()
            _draw_board_local(_manager.get_fen())
            
            if _cur_turn == _computer_on_turn:
                log.info(f"Computer's turn! Current FEN: {_manager.get_fen()}")
                if _player_engine:
                    limit = chess.engine.Limit(time=5)
                    log.info(f"Asking engine to play from FEN: {_manager.get_fen()}")
                    try:
                        mv = _player_engine.play(_manager.get_board(), limit, info=chess.engine.INFO_ALL)
                        log.info(f"Engine returned: {mv}")
                        mv = mv.move
                        log.info(f"Move extracted: {mv}")
                        log.info(f"Executing move: {str(mv)}")
                        _execute_computer_move(str(mv))
                    except Exception as e:
                        log.error(f"Error in BLACK_TURN computer move: {e}")
                        import traceback
                        traceback.print_exc()
        
        elif event == GameEvent.GAME_OVER:
            result_str = args[0] if args else "Unknown"
            termination = args[1] if len(args) > 1 else "Unknown"
            
            if termination.startswith("Termination."):
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
                
                log.info("displaying end screen")
                image = Image.new('1', (128, 292), 255)
                draw = ImageDraw.Draw(image)
                font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
                draw.text((0, 0), "   GAME OVER", font=font18, fill=0)
                draw.text((0, 20), "          " + result_str, font=font18, fill=0)
                if len(_score_history) > 0:
                    log.info("there be history")
                    draw.line([(0, 114), (128, 114)], fill=0, width=1)
                    barwidth = 128 / len(_score_history)
                    if barwidth > 8:
                        barwidth = 8
                    baroffset = 0
                    for i in range(0, len(_score_history)):
                        if _score_history[i] >= 0:
                            col = 255
                        else:
                            col = 0
                        draw.rectangle([(baroffset, 114), (baroffset + barwidth, 114 - (_score_history[i] * 4))], fill=col, outline='black')
                        baroffset = baroffset + barwidth
                log.info("drawing")
                epaper.drawImagePartial(0, 0, image)
                time.sleep(10)
                _kill = 1
        
        elif event == GameEvent.RESIGN:
            _kill = 1
        
    except Exception as e:
        log.error(f"Error in eventCallback: {e}")
        import traceback
        traceback.print_exc()
        try:
            epaper.unPauseEpaper()
        except:
            pass


def _move_callback(move: str):
    """Handle move events from GameManager"""
    try:
        log.info(f"moveCallback: Drawing board for move {move}")
        _draw_board_local(_manager.get_fen())
        log.info("moveCallback: Board drawn successfully")
    except Exception as e:
        log.error(f"Error in moveCallback while drawing board: {e}")
        import traceback
        traceback.print_exc()


def _key_callback(key):
    """Handle key press events"""
    global _kill, _graphs_on, _first_move
    
    log.info("Key event received: " + str(key))
    if key == board.Key.BACK:
        _kill = 1
    if key == board.Key.DOWN:
        image = Image.new('1', (128, 80), 255)
        epaper.drawImagePartial(0, 209, image)
        epaper.drawImagePartial(0, 1, image)
        _graphs_on = 0
    if key == board.Key.UP:
        _graphs_on = 1
        _first_move = 1
        if _analysis_engine:
            info = _analysis_engine.analyse(_manager.get_board(), chess.engine.Limit(time=0.5))
            _evaluation_graphs(info)


def _takeback_callback():
    """Handle takeback events"""
    log.info("Takeback detected - clearing computer move setup")
    _manager.clear_forced_move()
    board.ledsOff()
    global _cur_turn
    
    # Switch turn
    if _cur_turn == 1:
        _cur_turn = 0
    else:
        _cur_turn = 1
    
    # Trigger appropriate turn event
    if _cur_turn == 0:
        _event_callback(GameEvent.BLACK_TURN)
    else:
        _event_callback(GameEvent.WHITE_TURN)


def main():
    """Main entry point"""
    global _manager, _analysis_engine, _player_engine, _computer_on_turn, _kill
    
    # Parse command line arguments
    computer_arg = sys.argv[1] if len(sys.argv) > 1 else "white"
    if computer_arg == "white":
        _computer_on_turn = 1  # Computer is white
    elif computer_arg == "black":
        _computer_on_turn = 0  # Computer is black
    elif computer_arg == "random":
        _computer_on_turn = randint(0, 1)
    
    # Engine name
    engine_name = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    log.info("enginename: " + engine_name)
    
    ENGINE_PATH_NAME = "engines/" + engine_name
    log.info("ENGINE_PATH_NAME: " + ENGINE_PATH_NAME)
    CT_800_PATH = "engines/ct800"
    log.info("CT_800_PATH: " + CT_800_PATH)
    
    # Engine paths
    AENGINE_PATH = str((pathlib.Path(__file__).parent.parent / CT_800_PATH).resolve())
    PENGINE_PATH = str((pathlib.Path(__file__).parent.parent / ENGINE_PATH_NAME).resolve())
    UCI_FILE_PATH = PENGINE_PATH + ".uci"
    log.info(f"aengine: {AENGINE_PATH}")
    log.info(f"pengine: {PENGINE_PATH}")
    
    # Initialize engines
    try:
        _analysis_engine = chess.engine.SimpleEngine.popen_uci(AENGINE_PATH, timeout=None)
        _player_engine = chess.engine.SimpleEngine.popen_uci(PENGINE_PATH)
        log.info(f"analysis_engine: {_analysis_engine}")
        log.info(f"player_engine: {_player_engine}")
    except Exception as e:
        log.error(f"Error initializing engines: {e}")
        sys.exit(1)
    
    # UCI options
    uci_options_desc = "Default"
    uci_options = {}
    if len(sys.argv) > 3:
        uci_options_desc = sys.argv[3]
        if os.path.exists(UCI_FILE_PATH):
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(UCI_FILE_PATH)
            if config.has_section(uci_options_desc):
                log.info(config.items(uci_options_desc))
                for item in config.items(uci_options_desc):
                    uci_options[item[0]] = item[1]
                NON_UCI_FIELDS = ['Description']
                uci_options = {k: v for k, v in uci_options.items() if k not in NON_UCI_FIELDS}
                log.info(uci_options)
            else:
                log.warning(f"Section '{uci_options_desc}' not found in {UCI_FILE_PATH}, falling back to Default")
                if config.has_section("DEFAULT"):
                    for item in config.items("DEFAULT"):
                        uci_options[item[0]] = item[1]
                    NON_UCI_FIELDS = ['Description']
                    uci_options = {k: v for k, v in uci_options.items() if k not in NON_UCI_FIELDS}
                uci_options_desc = "Default"
        else:
            log.warning(f"UCI file not found: {UCI_FILE_PATH}, using Default settings")
            uci_options_desc = "Default"
    
    # Configure player engine
    if uci_options and _player_engine:
        log.info(f"Configuring engine with options: {uci_options}")
        _player_engine.configure(uci_options)
    
    # Enable graphs on Pi Zero 2 W
    if os.uname().machine == "armv7l":
        _graphs_on = 1
    
    # Initialize display
    epaper.initEpaper()
    
    # Create and start game manager
    _manager = GameManager()
    
    # Set game info
    if _computer_on_turn == 0:
        _manager.set_game_info(uci_options_desc, "", "", "Player", engine_name)
    else:
        _manager.set_game_info(uci_options_desc, "", "", engine_name, "Player")
    
    # Subscribe to manager events
    _manager.subscribe_events(_event_callback)
    _manager.subscribe_moves(_move_callback)
    _manager.subscribe_keys(_key_callback)
    _manager.subscribe_takeback(_takeback_callback)
    
    # Start manager
    _manager.start()
    log.info("Game manager started")
    
    # Main loop
    try:
        while not _kill:
            time.sleep(0.1)
    except KeyboardInterrupt:
        log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
        _cleanup_and_exit()
    finally:
        log.info(">>> Final cleanup")
        _do_cleanup()


if __name__ == "__main__":
    main()

