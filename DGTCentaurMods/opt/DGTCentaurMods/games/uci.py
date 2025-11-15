"""
UCI chess engine interface with event-driven game management.

This module provides a clean interface for playing chess against UCI engines
on the DGT Centaur board. It reacts to game manager events, manages engine
lifecycle, handles display updates, and ensures proper opponent move handling.
"""

from DGTCentaurMods.games.manager import GameManager, EVENT_NEW_GAME, EVENT_WHITE_TURN, EVENT_BLACK_TURN
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

# Game state
curturn = 1  # 1 = white, 0 = black
computeronturn = 0  # 0 = black (player white), 1 = white (player black)
kill = 0
firstmove = 1
graphson = 0  # Default to graphs off
scorehistory = []
last_event = None
cleaned_up = False
MAX_SCOREHISTORY_SIZE = 200

# Engine references
aengine = None  # Analysis engine
pengine = None  # Playing engine
manager = None


def do_cleanup():
    """Clean up engines and resources."""
    global cleaned_up, aengine, pengine, manager
    if cleaned_up:
        return
    cleaned_up = True
    
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
        cleanup_engine(aengine, "aengine")
    except:
        pass
    try:
        cleanup_engine(pengine, "pengine")
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
        if manager:
            manager.clear_forced_move()
            manager.stop()
    except:
        pass
    try:
        board.cleanup(leds_off=True)
    except Exception:
        pass


def cleanup_and_exit(signum=None, frame=None):
    """Clean up resources and exit gracefully."""
    global kill, cleaned_up
    if cleaned_up:
        os._exit(0)
    log.info(">>> Cleaning up and exiting...")
    kill = 1
    try:
        do_cleanup()
    except KeyboardInterrupt:
        log.warning(">>> Interrupted during cleanup, forcing exit")
        os._exit(1)
    except Exception as e:
        log.warning(f">>> Error during cleanup: {e}")
    log.info("Goodbye!")
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGINT, cleanup_and_exit)
try:
    signal.signal(signal.SIGTERM, cleanup_and_exit)
except Exception:
    pass

# Detect if we're on Pi Zero 2W (armv7l) and enable graphs
if os.uname().machine == "armv7l":
    graphson = 1

# Parse command line arguments
computerarg = sys.argv[1] if len(sys.argv) > 1 else "white"
if computerarg == "white":
    computeronturn = 0  # Player is white, computer is black
if computerarg == "black":
    computeronturn = 1  # Player is black, computer is white
if computerarg == "random":
    computeronturn = randint(0, 1)

# Engine configuration
enginename = sys.argv[2] if len(sys.argv) > 2 else "stockfish_pi"
log.info(f"enginename: {enginename}")
ENGINE_PATH_NAME = "engines/" + enginename
log.info(f"ENGINE_PATH_NAME: {ENGINE_PATH_NAME}")
CT_800_PATH = "engines/ct800"
log.info(f"CT_800_PATH: {CT_800_PATH}")

# Resolve engine paths
AENGINE_PATH = str((pathlib.Path(__file__).parent.parent / CT_800_PATH).resolve())
PENGINE_PATH = str((pathlib.Path(__file__).parent.parent / ENGINE_PATH_NAME).resolve())
UCI_FILE_PATH = PENGINE_PATH + ".uci"
log.info(f"aengine: {AENGINE_PATH}")
log.info(f"pengine: {PENGINE_PATH}")

# Initialize engines
try:
    aengine = chess.engine.SimpleEngine.popen_uci(AENGINE_PATH, timeout=None)
    pengine = chess.engine.SimpleEngine.popen_uci(PENGINE_PATH)
    log.info(f"aengine: {aengine}")
    log.info(f"pengine: {pengine}")
except Exception as e:
    log.error(f"Error initializing engines: {e}")
    cleanup_and_exit()

# Load UCI options
ucioptionsdesc = "Default"
ucioptions = {}
if len(sys.argv) > 3:
    ucioptionsdesc = sys.argv[3]
    if os.path.exists(UCI_FILE_PATH):
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(UCI_FILE_PATH)
        if config.has_section(ucioptionsdesc):
            log.info(config.items(ucioptionsdesc))
            for item in config.items(ucioptionsdesc):
                ucioptions[item[0]] = item[1]
            NON_UCI_FIELDS = ['Description']
            ucioptions = {k: v for k, v in ucioptions.items() if k not in NON_UCI_FIELDS}
            log.info(ucioptions)
        else:
            log.warning(f"Section '{ucioptionsdesc}' not found in {UCI_FILE_PATH}, falling back to Default")
            if config.has_section("DEFAULT"):
                for item in config.items("DEFAULT"):
                    ucioptions[item[0]] = item[1]
                NON_UCI_FIELDS = ['Description']
                ucioptions = {k: v for k, v in ucioptions.items() if k not in NON_UCI_FIELDS}
            ucioptionsdesc = "Default"
    else:
        log.warning(f"UCI file not found: {UCI_FILE_PATH}, using Default settings")
        ucioptionsdesc = "Default"


def keyCallback(key):
    """Handle key press events."""
    global kill, graphson, firstmove
    log.info("Key event received: " + str(key))
    if key == board.Key.BACK:
        kill = 1
    if key == board.Key.DOWN:
        image = Image.new('1', (128, 80), 255)
        epaper.drawImagePartial(0, 209, image)
        epaper.drawImagePartial(0, 1, image)
        graphson = 0
    if key == board.Key.UP:
        graphson = 1
        firstmove = 1
        if manager and aengine:
            try:
                info = aengine.analyse(manager.get_board(), chess.engine.Limit(time=0.5))
                evaluationGraphs(info)
            except Exception as e:
                log.error(f"Error analyzing position: {e}")


def executeComputerMove(mv):
    """Execute the computer move by setting up LEDs for the player to move pieces."""
    try:
        log.info(f"Setting up computer move: {mv}")
        if not manager:
            log.error("Manager not initialized")
            return
        
        board_obj = manager.get_board()
        log.info(f"Current FEN: {manager.get_fen()}")
        log.info(f"Legal moves: {[str(m) for m in list(board_obj.legal_moves)[:5]]}...")
        
        # Validate the move is legal
        move = chess.Move.from_uci(mv)
        if move not in board_obj.legal_moves:
            log.error(f"ERROR: Move {mv} is not legal! This should not happen.")
            log.error(f"Legal moves: {list(board_obj.legal_moves)}")
            raise ValueError(f"Illegal move: {mv}")
        
        # Set forced move in manager
        log.info(f"Setting up manager for forced move")
        manager.set_forced_move(mv, active=True)
        
        log.info("Computer move setup complete. Waiting for player to move pieces on board.")
        return
    except Exception as e:
        log.error(f"Error in executeComputerMove: {e}")
        import traceback
        traceback.print_exc()


def eventCallback(event):
    """Handle game events from manager."""
    global curturn, kill, scorehistory, last_event, firstmove
    
    log.info(f">>> eventCallback START: event={event}")
    
    # Prevent duplicate NEW_GAME events
    if event == EVENT_NEW_GAME:
        if last_event == EVENT_NEW_GAME:
            log.warning("!!! SKIPPING: Consecutive NEW_GAME events - ignoring to prevent loop !!!")
            return
    last_event = event
    
    try:
        log.info(f"EventCallback triggered with event: {event}")
        
        if event == EVENT_NEW_GAME:
            log.info("EVENT_NEW_GAME: Resetting board to starting position")
            manager.clear_forced_move()
            board.ledsOff()
            scorehistory = []
            curturn = 1
            firstmove = 1
            epaper.pauseEpaper()
            drawBoardLocal(manager.get_fen())
            log.info(f"Board reset. FEN: {manager.get_fen()}")
            if graphson == 1 and aengine:
                try:
                    info = aengine.analyse(manager.get_board(), chess.engine.Limit(time=0.1))
                    evaluationGraphs(info)
                except Exception as e:
                    log.error(f"Error analyzing position: {e}")
            epaper.unPauseEpaper()
        
        if event == EVENT_WHITE_TURN:
            curturn = 1
            log.info(f"WHITE_TURN event: curturn={curturn}, computeronturn={computeronturn}")
            if graphson == 1 and aengine:
                try:
                    info = aengine.analyse(manager.get_board(), chess.engine.Limit(time=0.5))
                    epaper.pauseEpaper()
                    evaluationGraphs(info)
                    epaper.unPauseEpaper()
                except Exception as e:
                    log.error(f"Error analyzing position: {e}")
            drawBoardLocal(manager.get_fen())
            
            if curturn == computeronturn:
                log.info(f"Computer's turn (white)! Current FEN: {manager.get_fen()}")
                if ucioptions != {}:
                    log.info(f"Configuring engine with options: {ucioptions}")
                    pengine.configure(ucioptions)
                limit = chess.engine.Limit(time=5)
                log.info(f"Asking engine to play from FEN: {manager.get_fen()}")
                try:
                    result = pengine.play(manager.get_board(), limit, info=chess.engine.INFO_ALL)
                    log.info(f"Engine returned: {result}")
                    mv = result.move
                    log.info(f"Move extracted: {mv}")
                    log.info(f"Executing move: {str(mv)}")
                    executeComputerMove(str(mv))
                except Exception as e:
                    log.error(f"Error in WHITE_TURN computer move: {e}")
                    import traceback
                    traceback.print_exc()
        
        if event == EVENT_BLACK_TURN:
            curturn = 0
            log.info(f"BLACK_TURN event: curturn={curturn}, computeronturn={computeronturn}")
            if graphson == 1 and aengine:
                try:
                    info = aengine.analyse(manager.get_board(), chess.engine.Limit(time=0.5))
                    epaper.pauseEpaper()
                    evaluationGraphs(info)
                    epaper.unPauseEpaper()
                except Exception as e:
                    log.error(f"Error analyzing position: {e}")
            drawBoardLocal(manager.get_fen())
            
            if curturn == computeronturn:
                log.info(f"Computer's turn (black)! Current FEN: {manager.get_fen()}")
                if ucioptions != {}:
                    log.info(f"Configuring engine with options: {ucioptions}")
                    pengine.configure(ucioptions)
                limit = chess.engine.Limit(time=5)
                log.info(f"Asking engine to play from FEN: {manager.get_fen()}")
                try:
                    result = pengine.play(manager.get_board(), limit, info=chess.engine.INFO_ALL)
                    log.info(f"Engine returned: {result}")
                    mv = result.move
                    log.info(f"Move extracted: {mv}")
                    log.info(f"Executing move: {str(mv)}")
                    executeComputerMove(str(mv))
                except Exception as e:
                    log.error(f"Error in BLACK_TURN computer move: {e}")
                    import traceback
                    traceback.print_exc()
        
        if type(event) == str:
            # Termination events
            if event.startswith("Termination."):
                image = Image.new('1', (128, 12), 255)
                draw = ImageDraw.Draw(image)
                font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
                txt = event[12:]
                draw.text((30, 0), txt, font=font12, fill=0)
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
                result_str = str(manager.get_board().result())
                draw.text((0, 20), "          " + result_str, font=font18, fill=0)
                
                if len(scorehistory) > 0:
                    log.info("there be history")
                    draw.line([(0, 114), (128, 114)], fill=0, width=1)
                    barwidth = 128 / len(scorehistory)
                    if barwidth > 8:
                        barwidth = 8
                    baroffset = 0
                    for i in range(0, len(scorehistory)):
                        if scorehistory[i] >= 0:
                            col = 255
                        else:
                            col = 0
                        draw.rectangle([(baroffset, 114), (baroffset + barwidth, 114 - (scorehistory[i] * 4))], fill=col, outline='black')
                        baroffset = baroffset + barwidth
                
                log.info("drawing")
                epaper.drawImagePartial(0, 0, image)
                time.sleep(10)
                kill = 1
    except Exception as e:
        log.error(f"Error in eventCallback: {e}")
        import traceback
        traceback.print_exc()
        try:
            epaper.unPauseEpaper()
        except:
            pass


def moveCallback(move):
    """Handle move events from manager."""
    try:
        log.info(f"moveCallback: Drawing board for move {move}")
        drawBoardLocal(manager.get_fen())
        log.info("moveCallback: Board drawn successfully")
    except Exception as e:
        log.error(f"Error in moveCallback while drawing board: {e}")
        import traceback
        traceback.print_exc()


def evaluationGraphs(info):
    """Draw evaluation graphs to the screen."""
    global firstmove, graphson, scorehistory, curturn
    
    if "score" not in info:
        log.info("evaluationGraphs: No score in info, skipping")
        return
    
    if graphson == 0:
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
    
    if graphson == 1:
        image = Image.new('1', (128, 80), 255)
        draw = ImageDraw.Draw(image)
        font12 = ImageFont.truetype(AssetManager.get_resource_path("Font.ttc"), 12)
    
    txt = "{:5.1f}".format(sval)
    if sval > 999:
        txt = ""
    if "Mate" in sc:
        txt = "Mate in " + "{:2.0f}".format(abs(sval * 100))
        sval = sval * 100000
    
    if graphson == 1:
        draw.text((50, 12), txt, font=font12, fill=0)
        draw.rectangle([(0, 1), (127, 11)], fill=None, outline='black')
    
    if sval > 12:
        sval = 12
    if sval < -12:
        sval = -12
    
    if firstmove == 0:
        scorehistory.append(sval)
        if len(scorehistory) > MAX_SCOREHISTORY_SIZE:
            scorehistory.pop(0)
    else:
        firstmove = 0
    
    offset = (128 / 25) * (sval + 12)
    if offset < 128:
        if graphson == 1:
            draw.rectangle([(offset, 1), (127, 11)], fill=0, outline='black')
    
    if graphson == 1:
        if len(scorehistory) > 0:
            draw.line([(0, 50), (128, 50)], fill=0, width=1)
            barwidth = 128 / len(scorehistory)
            if barwidth > 8:
                barwidth = 8
            baroffset = 0
            for i in range(0, len(scorehistory)):
                if scorehistory[i] >= 0:
                    col = 255
                else:
                    col = 0
                y_calc = 50 - (scorehistory[i] * 2)
                y0 = min(50, y_calc)
                y1 = max(50, y_calc)
                draw.rectangle([(baroffset, y0), (baroffset + barwidth, y1)], fill=col, outline='black')
                baroffset = baroffset + barwidth
        tmp = image.copy()
        dr2 = ImageDraw.Draw(tmp)
        if curturn == 1:
            dr2.ellipse((119, 14, 126, 21), fill=0, outline=0)
        epaper.drawImagePartial(0, 209, tmp)
        if curturn == 0:
            draw.ellipse((119, 14, 126, 21), fill=0, outline=0)
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        epaper.drawImagePartial(0, 1, image)


def drawBoardLocal(fen):
    """Draw the chess board from FEN string."""
    try:
        log.info(f"drawBoardLocal: Starting to draw board with FEN: {fen[:20]}...")
        global computeronturn
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
            if computeronturn == 1:
                piece = piece.transpose(Image.FLIP_TOP_BOTTOM)
                piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
            lboard.paste(piece, (col, row))
        draw.rectangle([(0, 0), (127, 127)], fill=None, outline='black')
        epaper.drawImagePartial(0, 81, lboard)
    except Exception as e:
        log.error(f"Error in drawBoardLocal: {e}")
        import traceback
        traceback.print_exc()


# Initialize epaper
epaper.initEpaper()

# Set initial turn
curturn = 1

# Create and start game manager
manager = GameManager()
manager.subscribe_event(eventCallback)
manager.subscribe_move(moveCallback)
manager.subscribe_key(keyCallback)
manager.start()

log.info("Game manager subscribed and started")

# Main loop
try:
    while kill == 0:
        time.sleep(0.1)
except KeyboardInterrupt:
    log.info("\n>>> Caught KeyboardInterrupt, cleaning up...")
    cleanup_and_exit()
finally:
    log.info(">>> Final cleanup")
    do_cleanup()

