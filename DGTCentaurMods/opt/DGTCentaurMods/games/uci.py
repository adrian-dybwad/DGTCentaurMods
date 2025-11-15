"""
UCI chess engine interface with event-driven game management.

Reacts to events from games.manager, manages engine lifecycle,
handles UI/display, and starts new games when pieces are in starting position.
"""

import chess
import chess.engine
import sys
import os
import pathlib
import threading
import time
import signal
import configparser
from random import randint
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.games import manager
from DGTCentaurMods.display import epaper
from DGTCentaurMods.display.ui_components import AssetManager
from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log

# Game state
_kill = False
_curturn = 1
_computer_on_turn = 0  # 0 = black, 1 = white
_first_move = 1
_graphs_on = 0
_score_history = []
MAX_SCOREHISTORY_SIZE = 200

# Engines
_aengine: Optional[chess.engine.SimpleEngine] = None
_pengine: Optional[chess.engine.SimpleEngine] = None
_uci_options = {}
_uci_options_desc = "Default"

# Manager
_game_manager: Optional[manager.GameManager] = None
_cleaned_up = False


def cleanup_and_exit(signum=None, frame=None):
    """Clean up resources and exit gracefully."""
    global _cleaned_up, _kill
    if _cleaned_up:
        os._exit(0)
    
    log.info(">>> Cleaning up and exiting...")
    _kill = True
    
    try:
        do_cleanup()
    except KeyboardInterrupt:
        log.warning(">>> Interrupted during cleanup, forcing exit")
        os._exit(1)
    except Exception as e:
        log.warning(f">>> Error during cleanup: {e}")
    
    log.info("Goodbye!")
    sys.exit(0)


def do_cleanup():
    """Perform cleanup of engines and resources."""
    global _cleaned_up, _game_manager, _aengine, _pengine
    if _cleaned_up:
        return
    
    _cleaned_up = True
    
    def cleanup_engine(engine, name):
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
        cleanup_engine(_aengine, "aengine")
    except:
        pass
    
    try:
        cleanup_engine(_pengine, "pengine")
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
        if _game_manager:
            _game_manager.unsubscribe()
    except:
        pass
    
    try:
        board.cleanup(leds_off=True)
    except:
        pass


# Register signal handlers
signal.signal(signal.SIGINT, cleanup_and_exit)
try:
    signal.signal(signal.SIGTERM, cleanup_and_exit)
except Exception:
    pass


def main():
    """Main entry point for UCI mode."""
    global _kill, _curturn, _computer_on_turn, _graphs_on
    global _aengine, _pengine, _uci_options, _uci_options_desc, _game_manager
    
    # Parse command line arguments
    # Arg1: side (white|black|random)
    computer_arg = sys.argv[1] if len(sys.argv) > 1 else "white"
    if computer_arg == "white":
        _computer_on_turn = 1  # Computer plays white
    elif computer_arg == "black":
        _computer_on_turn = 0  # Computer plays black
    elif computer_arg == "random":
        _computer_on_turn = randint(0, 1)
    
    # Arg2: engine name
    engine_name = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
    log.info(f"Engine name: {engine_name}")
    
    ENGINE_PATH_NAME = f"engines/{engine_name}"
    CT_800_PATH = "engines/ct800"
    
    # Resolve engine paths
    base_path = pathlib.Path(__file__).parent.parent
    AENGINE_PATH = str((base_path / CT_800_PATH).resolve())
    PENGINE_PATH = str((base_path / ENGINE_PATH_NAME).resolve())
    UCI_FILE_PATH = PENGINE_PATH + ".uci"
    
    log.info(f"aengine: {AENGINE_PATH}")
    log.info(f"pengine: {PENGINE_PATH}")
    
    # Start engines
    try:
        _aengine = chess.engine.SimpleEngine.popen_uci(AENGINE_PATH, timeout=None)
        _pengine = chess.engine.SimpleEngine.popen_uci(PENGINE_PATH)
    except Exception as e:
        log.error(f"Failed to start engines: {e}")
        cleanup_and_exit()
        return
    
    # Load UCI options
    if len(sys.argv) > 3:
        _uci_options_desc = sys.argv[3]
        if os.path.exists(UCI_FILE_PATH):
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(UCI_FILE_PATH)
            if config.has_section(_uci_options_desc):
                for item in config.items(_uci_options_desc):
                    _uci_options[item[0]] = item[1]
                NON_UCI_FIELDS = ['Description']
                _uci_options = {k: v for k, v in _uci_options.items() 
                               if k not in NON_UCI_FIELDS}
            else:
                log.warning(f"Section '{_uci_options_desc}' not found, using Default")
                if config.has_section("DEFAULT"):
                    for item in config.items("DEFAULT"):
                        _uci_options[item[0]] = item[1]
                    NON_UCI_FIELDS = ['Description']
                    _uci_options = {k: v for k, v in _uci_options.items() 
                                   if k not in NON_UCI_FIELDS}
                _uci_options_desc = "Default"
        else:
            log.warning(f"UCI file not found: {UCI_FILE_PATH}")
    
    # Enable graphs on Pi Zero 2W
    if os.uname().machine == "armv7l":
        _graphs_on = 1
    
    # Initialize epaper
    epaper.initEpaper()
    
    # Set game info
    if _computer_on_turn == 0:
        manager.get_manager().set_game_info(_uci_options_desc, "", "", "Player", engine_name)
    else:
        manager.get_manager().set_game_info(_uci_options_desc, "", "", engine_name, "Player")
    
    # Subscribe to game manager
    _game_manager = manager.get_manager()
    _game_manager.subscribe(
        event_callback=event_callback,
        move_callback=move_callback,
        key_callback=key_callback,
        takeback_callback=takeback_callback
    )
    
    log.info("Game manager subscribed")
    
    # Check if board is in starting position
    current_state = board.getChessState()
    starting_state = bytearray(
        b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01'
    )
    
    if bytearray(current_state) == starting_state:
        log.info("Starting position detected on startup - game will start automatically")
    else:
        log.info("Board not in starting position - waiting for pieces to be placed")
        write_text_local(0, "Place pieces")
        write_text_local(1, "in start pos")
    
    # Main loop
    try:
        while not _kill:
            time.sleep(0.1)
    except KeyboardInterrupt:
        log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
        cleanup_and_exit()
    finally:
        log.info(">>> Final cleanup")
        do_cleanup()


def event_callback(event):
    """Handle game events from manager."""
    global _curturn, _kill, _score_history, _first_move, _graphs_on
    
    log.info(f"EventCallback triggered with event: {event}")
    
    try:
        if event == manager.EVENT_NEW_GAME:
            log.info("EVENT_NEW_GAME: Resetting board")
            _game_manager.clear_forced_move()
            board.ledsOff()
            epaper.quickClear()
            _score_history = []
            _curturn = 1
            _first_move = 1
            
            epaper.pauseEpaper()
            draw_board_local(_game_manager.get_fen())
            
            if _graphs_on == 1 and _aengine:
                try:
                    info = _aengine.analyse(_game_manager.get_board(), 
                                           chess.engine.Limit(time=0.1))
                    evaluation_graphs(info)
                except Exception as e:
                    log.error(f"Error analyzing position: {e}")
            
            epaper.unPauseEpaper()
        
        elif event == manager.EVENT_WHITE_TURN:
            _curturn = 1
            log.info(f"WHITE_TURN event: curturn={_curturn}, computer_on_turn={_computer_on_turn}")
            
            if _graphs_on == 1 and _aengine:
                try:
                    info = _aengine.analyse(_game_manager.get_board(), 
                                           chess.engine.Limit(time=0.5))
                    epaper.pauseEpaper()
                    evaluation_graphs(info)
                    epaper.unPauseEpaper()
                except Exception as e:
                    log.error(f"Error analyzing position: {e}")
            
            draw_board_local(_game_manager.get_fen())
            
            if _curturn == _computer_on_turn:
                execute_computer_move()
        
        elif event == manager.EVENT_BLACK_TURN:
            _curturn = 0
            log.info(f"BLACK_TURN event: curturn={_curturn}, computer_on_turn={_computer_on_turn}")
            
            if _graphs_on == 1 and _aengine:
                try:
                    info = _aengine.analyse(_game_manager.get_board(), 
                                           chess.engine.Limit(time=0.5))
                    epaper.pauseEpaper()
                    evaluation_graphs(info)
                    epaper.unPauseEpaper()
                except Exception as e:
                    log.error(f"Error analyzing position: {e}")
            
            draw_board_local(_game_manager.get_fen())
            
            if _curturn == _computer_on_turn:
                execute_computer_move()
        
        elif event == manager.EVENT_RESIGN_GAME:
            # Handle resignation
            pass
        
        elif isinstance(event, str) and event.startswith("Termination."):
            # Game over
            display_game_over(event)
            _kill = 1
    
    except Exception as e:
        log.error(f"Error in eventCallback: {e}")
        import traceback
        traceback.print_exc()
        try:
            epaper.unPauseEpaper()
        except:
            pass


def move_callback(move_str):
    """Handle move callbacks from manager."""
    try:
        log.info(f"moveCallback: Drawing board for move {move_str}")
        draw_board_local(_game_manager.get_fen())
    except Exception as e:
        log.error(f"Error in moveCallback: {e}")
        import traceback
        traceback.print_exc()


def key_callback(key):
    """Handle key press events."""
    global _kill, _graphs_on, _first_move
    
    log.info(f"Key event received: {str(key)}")
    
    if key == board.Key.BACK:
        _kill = 1
    elif key == board.Key.DOWN:
        image = Image.new('1', (128, 80), 255)
        epaper.drawImagePartial(0, 209, image)
        epaper.drawImagePartial(0, 1, image)
        _graphs_on = 0
    elif key == board.Key.UP:
        _graphs_on = 1
        _first_move = 1
        if _aengine:
            try:
                info = _aengine.analyse(_game_manager.get_board(), 
                                       chess.engine.Limit(time=0.5))
                evaluation_graphs(info)
            except Exception as e:
                log.error(f"Error analyzing position: {e}")


def takeback_callback():
    """Handle takeback callbacks."""
    log.info("Takeback detected - clearing computer move setup")
    _game_manager.clear_forced_move()
    board.ledsOff()
    
    global _curturn
    # Turn already switched by manager
    if _curturn == 0:
        event_callback(manager.EVENT_BLACK_TURN)
    else:
        event_callback(manager.EVENT_WHITE_TURN)


def execute_computer_move():
    """Execute computer move by setting up forced move."""
    global _pengine, _uci_options
    
    if not _pengine:
        log.error("No engine available")
        return
    
    try:
        log.info(f"Computer's turn! Current FEN: {_game_manager.get_fen()}")
        
        if _uci_options:
            log.info(f"Configuring engine with options: {_uci_options}")
            _pengine.configure(_uci_options)
        
        limit = chess.engine.Limit(time=5)
        log.info(f"Asking engine to play from FEN: {_game_manager.get_fen()}")
        
        result = _pengine.play(_game_manager.get_board(), limit, 
                              info=chess.engine.INFO_ALL)
        move = result.move
        move_str = str(move)
        
        log.info(f"Engine returned move: {move_str}")
        
        # Validate move is legal
        if move not in _game_manager.get_board().legal_moves:
            log.error(f"ERROR: Move {move_str} is not legal!")
            return
        
        # Set forced move
        _game_manager.set_forced_move(move_str)
        log.info("Computer move setup complete. Waiting for player to move pieces.")
        
    except Exception as e:
        log.error(f"Error in execute_computer_move: {e}")
        import traceback
        traceback.print_exc()


def evaluation_graphs(info):
    """Draw evaluation graphs to the screen."""
    global _first_move, _graphs_on, _score_history, _curturn
    
    if "score" not in info:
        log.info("evaluationGraphs: No score in info, skipping")
        return
    
    if _graphs_on == 0:
        image = Image.new('1', (128, 80), 255)
        epaper.drawImagePartial(0, 209, image)
        epaper.drawImagePartial(0, 1, image)
        return
    
    sval = 0
    sc = str(info["score"])
    
    if "Mate" in sc:
        sval = 10000
        sval_str = sc[13:24]
        sval_str = sval_str[1:sval_str.find(")")]
    else:
        sval_str = sc[11:24]
        sval_str = sval_str[1:sval_str.find(")")]
    
    try:
        sval = float(sval_str)
    except ValueError:
        sval = 0
    
    sval = sval / 100
    if "BLACK" in sc:
        sval = sval * -1
    
    image = Image.new('1', (128, 80), 255)
    draw = ImageDraw.Draw(image)
    font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
    
    txt = "{:5.1f}".format(sval)
    if sval > 999:
        txt = ""
    if "Mate" in sc:
        txt = "Mate in " + "{:2.0f}".format(abs(sval * 100))
        sval = sval * 100000
    
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
        draw.rectangle([(offset, 1), (127, 11)], fill=0, outline='black')
    
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
            draw.rectangle([(baroffset, y0), (baroffset + barwidth, y1)], 
                          fill=col, outline='black')
            baroffset = baroffset + barwidth
    
    tmp = image.copy()
    dr2 = ImageDraw.Draw(tmp)
    if _curturn == 1:
        dr2.ellipse((119, 14, 126, 21), fill=0, outline=0)
    epaper.drawImagePartial(0, 209, tmp)
    
    if _curturn == 0:
        draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
    
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    image = image.transpose(Image.FLIP_LEFT_RIGHT)
    epaper.drawImagePartial(0, 1, image)


def write_text_local(row, txt):
    """Write text on a given line number."""
    image = Image.new('1', (128, 20), 255)
    draw = ImageDraw.Draw(image)
    font18 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 18)
    draw.text((0, 0), txt, font=font18, fill=0)
    epaper.drawImagePartial(0, (row * 20), image)


def draw_board_local(fen):
    """Draw chess board from FEN string."""
    try:
        log.info(f"drawBoardLocal: Starting to draw board with FEN: {fen[:20]}...")
        global _computer_on_turn
        
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
            
            piece_map = {
                "P": 16, "R": 32, "N": 48, "B": 64, "Q": 80, "K": 96,
                "p": 112, "r": 128, "n": 144, "b": 160, "q": 176, "k": 192
            }
            
            if nfen[x] in piece_map:
                px = piece_map[nfen[x]]
            
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


def display_game_over(termination):
    """Display game over screen."""
    global _score_history
    
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
    
    # Get result from database
    result = "Unknown"
    try:
        from DGTCentaurMods.db import models
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind=models.engine)
        session = Session()
        game_data = session.query(models.Game).order_by(models.Game.id.desc()).first()
        if game_data and game_data.result:
            result = game_data.result
        session.close()
    except Exception as e:
        log.error(f"Error getting result: {e}")
    
    draw.text((0, 20), "          " + result, font=font18, fill=0)
    
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
            draw.rectangle([(baroffset, 114), 
                          (baroffset + barwidth, 114 - (_score_history[i] * 4))],
                         fill=col, outline='black')
            baroffset = baroffset + barwidth
    
    log.info("drawing")
    epaper.drawImagePartial(0, 0, image)
    time.sleep(10)


if __name__ == "__main__":
    main()

