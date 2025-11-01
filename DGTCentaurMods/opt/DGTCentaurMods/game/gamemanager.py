# This script manages a chess game, passing events and moves back to the calling script with callbacks
# The calling script is expected to manage the display itself using epaper.py
# Calling script initialises with subscribeGame(eventCallback, moveCallback, keyCallback)
# eventCallback feeds back events such as start of game, gameover
# moveCallback feeds back the chess moves made on the board
# keyCallback feeds back key presses from keys under the display

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

from DGTCentaurMods.board import *
from DGTCentaurMods.display import epaper
from DGTCentaurMods.db import models
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, func
from scipy.optimize import linear_sum_assignment
import threading
import time
import chess
import sys
import inspect
from DGTCentaurMods.config import paths


# Event constants
EVENT_NEW_GAME = 1
EVENT_BLACK_TURN = 2
EVENT_WHITE_TURN = 3
EVENT_REQUEST_DRAW = 4
EVENT_RESIGN_GAME = 5

# Starting board state (all pieces in starting position)
START_STATE = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class GameState:
    """Centralized game state management"""
    def __init__(self):
        self.kill = False
        self.newgame = 0
        self.last_new_game_time = 0
        self.cboard = chess.Board()
        self.curturn = 1  # 1 = white, 0 = black (always sync with cboard.turn)
        self.sourcesq = -1  # Square where current player lifted piece
        self.legalsquares = []  # Legal destination squares for current player's piece
        self.computermove = ""  # UCI move string for forced computer move
        self.forcemove = 0  # 1 if waiting for player to execute computer move
        self.gamedbid = -1
        self.showingpromotion = False
        self.pausekeys = 0
        self.inmenu = 0
        self.boardstates = []  # History of board states for takeback detection
        self.must_check_new_game = False
        
        # Correction mode
        self.correction_mode = False
        self.correction_expected_state = None
        
        # Game info
        self.gameinfo_event = ""
        self.gameinfo_site = ""
        self.gameinfo_round = ""
        self.gameinfo_white = ""
        self.gameinfo_black = ""
        
        # Callbacks
        self.keycallbackfunction = None
        self.movecallbackfunction = None
        self.eventcallbackfunction = None
        self.takebackcallbackfunction = None
        
        # Database
        self.session = None
        self.source = ""


_game_state = GameState()

# Public API: expose commonly accessed globals for backward compatibility
cboard = _game_state.cboard
curturn = _game_state.curturn
forcemove = _game_state.forcemove
computermove = _game_state.computermove


def _square_to_notation(square):
    """Convert square index (0-63) to chess notation (e.g., 'e4')"""
    row = square // 8
    col = square % 8
    board_col = 7 - col
    board_row = row
    return chr(ord('a') + board_col) + chr(ord('1') + board_row)


def _notation_to_square(notation):
    """Convert chess notation (e.g., 'e4') to square index (0-63)"""
    if len(notation) < 2:
        return -1
    col_char = notation[0]
    row_char = notation[1]
    board_col = ord(col_char) - ord('a')
    board_row = ord(row_char) - ord('1')
    col = 7 - board_col
    square = board_row * 8 + col
    return square


def _collect_board_state():
    """Append the current board state to boardstates"""
    _game_state.boardstates.append(board.getBoardState())


def _validate_board_state(current_state, expected_state):
    """Check if board state matches expected state"""
    if current_state is None or expected_state is None:
        return False
    if len(current_state) != 64 or len(expected_state) != 64:
        return False
    return bytearray(current_state) == bytearray(expected_state)


def _enter_correction_mode():
    """Enter correction mode to guide user in fixing board state"""
    if _game_state.correction_mode:
        return
    
    # Don't enter correction during a move
    if _game_state.sourcesq >= 0:
        return
    
    _game_state.correction_mode = True
    if _game_state.boardstates and len(_game_state.boardstates) > 0:
        _game_state.correction_expected_state = _game_state.boardstates[-1]
    else:
        _game_state.correction_expected_state = START_STATE


def _exit_correction_mode():
    """Exit correction mode"""
    _game_state.correction_mode = False
    _game_state.correction_expected_state = None


def _provide_correction_guidance(current_state, expected_state):
    """Provide LED guidance to correct misplaced pieces using Hungarian algorithm"""
    if current_state is None or expected_state is None:
        return
    if len(current_state) != 64 or len(expected_state) != 64:
        return
    
    def _rc(idx):
        return (idx // 8), (idx % 8)
    
    def _dist(a, b):
        ar, ac = _rc(a)
        br, bc = _rc(b)
        return abs(ar - br) + abs(ac - bc)
    
    # Find pieces that are misplaced
    missing_pieces = []  # Pieces that should be present but aren't
    extra_pieces = []  # Pieces that are present but shouldn't be
    
    for i in range(64):
        if expected_state[i] == 1 and current_state[i] == 0:
            missing_pieces.append(i)
        elif expected_state[i] == 0 and current_state[i] == 1:
            extra_pieces.append(i)
    
    # Use Hungarian algorithm to find optimal pairing
    if len(missing_pieces) == len(extra_pieces) and len(missing_pieces) > 0:
        cost_matrix = []
        for missing in missing_pieces:
            row = []
            for extra in extra_pieces:
                row.append(_dist(missing, extra))
            cost_matrix.append(row)
        
        if cost_matrix:
            try:
                row_indices, col_indices = linear_sum_assignment(cost_matrix)
                board.ledsOff()
                for idx in range(len(row_indices)):
                    missing_idx = missing_pieces[row_indices[idx]]
                    extra_idx = extra_pieces[col_indices[idx]]
                    board.led(missing_idx, intensity=5)
                    board.led(extra_idx, intensity=5)
            except:
                pass
    
    # Handle pieces that don't have matches
    if len(missing_pieces) > len(extra_pieces):
        unmatched = missing_pieces[len(extra_pieces):]
        for idx in unmatched:
            board.led(idx, intensity=5)
    
    if len(extra_pieces) > len(missing_pieces):
        unmatched = extra_pieces[len(missing_pieces):]
        for idx in unmatched:
            board.led(idx, intensity=5)


def _process_move(move_uci, move, from_sq, to_sq):
    """Process a valid move: update board, database, and switch turns"""
    _exit_correction_mode()
    
    _game_state.cboard.push(move)
    paths.write_fen_log(_game_state.cboard.fen())
    
    # Sync curturn with chess board's turn
    _game_state.curturn = 1 if _game_state.cboard.turn else 0
    
    # Database logging
    if _game_state.gamedbid >= 0 and _game_state.session:
        gamemove = models.GameMove(
            gameid=_game_state.gamedbid,
            move=move_uci,
            fen=str(_game_state.cboard.fen())
        )
        _game_state.session.add(gamemove)
        _game_state.session.commit()
    
    # Collect new board state after move
    time.sleep(0.2)  # Let board stabilize
    _collect_board_state()
    
    # Reset move tracking
    _game_state.legalsquares = []
    _game_state.sourcesq = -1
    _game_state.forcemove = 0
    board.ledsOff()
    
    # Callbacks
    if _game_state.movecallbackfunction:
        _game_state.movecallbackfunction(move_uci)
    
    board.beep(board.SOUND_GENERAL)
    board.led(to_sq)
    
    # Check outcome and emit turn events
    outc = _game_state.cboard.outcome(claim_draw=True)
    if outc is None:
        if _game_state.curturn == 1:
            if _game_state.eventcallbackfunction:
                _game_state.eventcallbackfunction(EVENT_WHITE_TURN)
        else:
            if _game_state.eventcallbackfunction:
                _game_state.eventcallbackfunction(EVENT_BLACK_TURN)
    else:
        board.beep(board.SOUND_GENERAL)
        resultstr = str(_game_state.cboard.result())
        if _game_state.gamedbid >= 0 and _game_state.session:
            tg = _game_state.session.query(models.Game).filter(models.Game.id == _game_state.gamedbid).first()
            if tg:
                tg.result = resultstr
                _game_state.session.commit()
        if _game_state.eventcallbackfunction:
            _game_state.eventcallbackfunction(str(outc.termination))


def waitForPromotionChoice():
    """Wait for user to select promotion piece via button press"""
    screenback = epaper.epaperbuffer.copy()
    epaper.promotionOptions(13)
    _game_state.pausekeys = 1
    key = board.wait_for_key_up(timeout=60)
    _game_state.pausekeys = 2
    epaper.epaperbuffer = screenback.copy()
    
    if key == board.Key.UP:
        return "q"
    elif key == board.Key.DOWN:
        return "r"
    elif key == board.Key.LEFT:
        return "b"
    elif key == board.Key.RIGHT:
        return "n"
    else:
        return "q"


def checkLastBoardState():
    """Check if board state matches previous move (takeback detection)"""
    if _game_state.takebackcallbackfunction is None:
        _game_state.must_check_new_game = True
        return False
    
    if len(_game_state.boardstates) < 2:
        return False
    
    current = board.getBoardState()
    previous = _game_state.boardstates[-2]
    
    if bytearray(current) == bytearray(previous):
        board.ledsOff()
        _game_state.boardstates = _game_state.boardstates[:-1]
        
        # Remove last move from database
        if _game_state.session:
            lastmovemade = _game_state.session.query(models.GameMove).order_by(models.GameMove.id.desc()).first()
            if lastmovemade:
                _game_state.session.delete(lastmovemade)
                _game_state.session.commit()
        
        _game_state.cboard.pop()
        paths.write_fen_log(_game_state.cboard.fen())
        
        # Sync turn
        _game_state.curturn = 1 if _game_state.cboard.turn else 0
        
        board.beep(board.SOUND_GENERAL)
        if _game_state.takebackcallbackfunction:
            _game_state.takebackcallbackfunction()
        
        return True
    
    return False


def correction_fieldcallback(piece_event, field_hex, square, time_in_seconds):
    """Wrapper that intercepts field events during correction mode"""
    if not _game_state.correction_mode:
        return fieldcallback(piece_event, field_hex, square, time_in_seconds)
    
    # In correction mode - check if board now matches expected
    current_state = board.getBoardState()
    
    if _validate_board_state(current_state, _game_state.correction_expected_state):
        board.ledsOff()
        board.beep(board.SOUND_GENERAL)
        _exit_correction_mode()
        return
    
    # Still incorrect - update guidance
    _provide_correction_guidance(current_state, _game_state.correction_expected_state)


def keycallback(key_pressed):
    """Handle key press events"""
    if _game_state.keycallbackfunction:
        if _game_state.inmenu == 0 and key_pressed != board.Key.HELP:
            _game_state.keycallbackfunction(key_pressed)
        
        if _game_state.inmenu == 0 and key_pressed == board.Key.HELP:
            _game_state.inmenu = 1
            epaper.resignDrawMenu(14)
        
        if _game_state.inmenu == 1 and key_pressed == board.Key.BACK:
            epaper.writeText(14, "                   ")
            _game_state.inmenu = 0
        
        if _game_state.inmenu == 1 and key_pressed == board.Key.UP:
            epaper.writeText(14, "                   ")
            if _game_state.eventcallbackfunction:
                _game_state.eventcallbackfunction(EVENT_REQUEST_DRAW)
            _game_state.inmenu = 0
        
        if _game_state.inmenu == 1 and key_pressed == board.Key.DOWN:
            epaper.writeText(14, "                   ")
            if _game_state.eventcallbackfunction:
                _game_state.eventcallbackfunction(EVENT_RESIGN_GAME)
            _game_state.inmenu = 0


def fieldcallback(piece_event, field_hex, square, time_in_seconds):
    """Handle piece movement events from the board"""
    field = square + 1
    if piece_event == 1:  # PLACE
        field = ((square + 1) * -1)
    
    lift = field >= 0
    place = not lift
    
    if place:
        field = abs(field)
    field = field - 1
    
    # Get piece color at this square
    pc = _game_state.cboard.color_at(field)
    
    # Determine if this is current player's piece (curturn: 1=white, 0=black)
    vpiece = 0
    if _game_state.curturn == 0 and pc == False:  # Black's turn, black piece
        vpiece = 1
    if _game_state.curturn == 1 and pc == True:  # White's turn, white piece
        vpiece = 1
    
    fieldname = _square_to_notation(field)
    legalmoves = list(_game_state.cboard.legal_moves)
    
    # Handle piece lift for current player
    if lift and field not in _game_state.legalsquares and _game_state.sourcesq < 0 and vpiece == 1:
        _game_state.legalsquares = [field]
        _game_state.sourcesq = field
        
        # Generate legal destination squares
        for x in range(0, 64):
            fx = _square_to_notation(x)
            tm = fieldname + fx
            for move in legalmoves:
                if str(move)[0:4] == tm[0:4]:
                    _game_state.legalsquares.append(x)
                    break
    
    # Handle forced computer moves
    if _game_state.forcemove == 1 and lift and vpiece == 1:
        if fieldname != _game_state.computermove[0:2]:
            _game_state.legalsquares = [field]
        else:
            target = _game_state.computermove[2:4]
            tsq = _notation_to_square(target)
            _game_state.legalsquares = [tsq]
    
    # Handle valid move completion (current player)
    if place and field in _game_state.legalsquares and vpiece == 1:
        if field == _game_state.sourcesq:
            # Piece placed back - cancel move
            board.ledsOff()
            _game_state.sourcesq = -1
            _game_state.legalsquares = []
        else:
            # Valid move
            fromname = _square_to_notation(_game_state.sourcesq)
            toname = _square_to_notation(field)
            
            # Check for promotion
            pname = str(_game_state.cboard.piece_at(_game_state.sourcesq))
            pr = ""
            if (field // 8) == 7 and pname == "P":
                screenback = epaper.epaperbuffer.copy()
                board.beep(board.SOUND_GENERAL)
                if _game_state.forcemove == 0:
                    _game_state.showingpromotion = True
                    epaper.promotionOptions(13)
                    _game_state.pausekeys = 1
                    time.sleep(1)
                    pr = waitForPromotionChoice()
                    epaper.epaperbuffer = screenback.copy()
                    _game_state.showingpromotion = False
                    _game_state.pausekeys = 2
            if (field // 8) == 0 and pname == "p":
                screenback = epaper.epaperbuffer.copy()
                board.beep(board.SOUND_GENERAL)
                if _game_state.forcemove == 0:
                    _game_state.showingpromotion = True
                    epaper.promotionOptions(13)
                    _game_state.pausekeys = 1
                    time.sleep(1)
                    pr = waitForPromotionChoice()
                    _game_state.showingpromotion = False
                    epaper.epaperbuffer = screenback.copy()
                    _game_state.pausekeys = 2
            
            if _game_state.forcemove == 1:
                mv = _game_state.computermove
            else:
                mv = fromname + toname + pr
            
            try:
                move = chess.Move.from_uci(mv)
                if move in _game_state.cboard.legal_moves:
                    _process_move(mv, move, _game_state.sourcesq, field)
                    return
            except:
                pass
    
    # Handle illegal placements (current player's pieces)
    if place and field not in _game_state.legalsquares and vpiece == 1:
        if _game_state.sourcesq >= 0:
            board.beep(board.SOUND_WRONG_MOVE)
            is_takeback = checkLastBoardState()
            if not is_takeback:
                _enter_correction_mode()
                current_state = board.getBoardState()
                if _game_state.boardstates and len(_game_state.boardstates) > 0:
                    _provide_correction_guidance(current_state, _game_state.boardstates[-1])
            else:
                _game_state.sourcesq = -1
                _game_state.legalsquares = []
        else:
            board.ledsOff()
            _game_state.legalsquares = []
            _game_state.sourcesq = -1
    
    # Handle opponent moves (pieces not belonging to current player)
    if lift and vpiece == 0:
        # Opponent piece lifted - we'll detect the move when placed
        pass
    
    if place and vpiece == 0:
        # Opponent piece placed - try to detect and process move
        current_state = board.getBoardState()
        expected_state = _game_state.boardstates[-1] if _game_state.boardstates else START_STATE
        
        if current_state and expected_state:
            # Find what changed
            from_squares = []
            to_squares = []
            for i in range(64):
                if expected_state[i] == 1 and current_state[i] == 0:
                    from_squares.append(i)
                elif expected_state[i] == 0 and current_state[i] == 1:
                    to_squares.append(i)
            
            if len(from_squares) == 1 and len(to_squares) == 1:
                from_sq = from_squares[0]
                to_sq = to_squares[0]
                
                # Verify this is an opponent piece
                piece_color = _game_state.cboard.color_at(from_sq)
                if piece_color is not None:
                    is_opponent = (_game_state.curturn == 1 and piece_color == False) or (_game_state.curturn == 0 and piece_color == True)
                    
                    if is_opponent:
                        fromname = _square_to_notation(from_sq)
                        toname = _square_to_notation(to_sq)
                        
                        # Check for promotion
                        piece_at_from = _game_state.cboard.piece_at(from_sq)
                        if piece_at_from:
                            pname = str(piece_at_from)
                            pr = ""
                            if (to_sq // 8) == 7 and pname == "P":
                                pr = "q"
                            elif (to_sq // 8) == 0 and pname == "p":
                                pr = "q"
                            
                            move_uci = fromname + toname + pr
                            
                            try:
                                move = chess.Move.from_uci(move_uci)
                                if move in _game_state.cboard.legal_moves:
                                    _process_move(move_uci, move, from_sq, to_sq)
                                    return
                            except:
                                pass
        
        # Opponent move not valid - enter correction
        _enter_correction_mode()
        current_state = board.getBoardState()
        if _game_state.boardstates and len(_game_state.boardstates) > 0:
            _provide_correction_guidance(current_state, _game_state.boardstates[-1])


def setGameInfo(event, site, round_num, white, black):
    """Set game information for database logging"""
    _game_state.gameinfo_event = event
    _game_state.gameinfo_site = site
    _game_state.gameinfo_round = round_num
    _game_state.gameinfo_white = white
    _game_state.gameinfo_black = black


def computerMove(mv):
    """Set up a forced computer move that player must execute"""
    _game_state.forcemove = 1
    _game_state.computermove = mv


def resignGame(side):
    """Handle game resignation"""
    if _game_state.gamedbid >= 0 and _game_state.session:
        tg = _game_state.session.query(models.Game).filter(models.Game.id == _game_state.gamedbid).first()
        if tg:
            if side == 1:
                tg.result = "0-1"
            else:
                tg.result = "1-0"
            _game_state.session.commit()


def gameThread(eventCallback, moveCallback, keycallbacki, takebackcallbacki):
    """Main game thread that handles game events and board monitoring"""
    _game_state.keycallbackfunction = keycallbacki
    _game_state.movecallbackfunction = moveCallback
    _game_state.eventcallbackfunction = eventCallback
    _game_state.takebackcallbackfunction = takebackcallbacki
    
    # Initialize database
    engine = create_engine(paths.db_path())
    Session = sessionmaker(bind=engine)
    _game_state.session = Session()
    _game_state.source = inspect.stack()[1].filename
    
    board.ledsOff()
    board.subscribeEvents(keycallback, correction_fieldcallback)
    
    t = 0
    _game_state.pausekeys = 0
    
    while not _game_state.kill:
        # Detect new game
        if _game_state.newgame == 0:
            if t < 5:
                t = t + 1
            else:
                try:
                    current_state = None
                    if _game_state.must_check_new_game:
                        current_state = board.getBoardState()
                        _game_state.must_check_new_game = False
                    
                    if current_state and bytearray(current_state) == START_STATE:
                        if _game_state.cboard.fen() != START_FEN:
                            t = 0
                            continue
                        
                        # Debounce
                        now = time.time()
                        if now - _game_state.last_new_game_time < 1.0:
                            t = 0
                            continue
                        
                        board.ledsOff()
                        _exit_correction_mode()
                        _game_state.last_new_game_time = now
                        
                        _game_state.newgame = 1
                        _game_state.curturn = 1
                        _game_state.cboard = chess.Board(START_FEN)
                        paths.write_fen_log(_game_state.cboard.fen())
                        board.beep(board.SOUND_GENERAL)
                        time.sleep(0.3)
                        board.beep(board.SOUND_GENERAL)
                        board.ledsOff()
                        
                        if _game_state.eventcallbackfunction:
                            _game_state.eventcallbackfunction(EVENT_NEW_GAME)
                            _game_state.eventcallbackfunction(EVENT_WHITE_TURN)
                        
                        # Log new game in database
                        game = models.Game(
                            source=_game_state.source,
                            event=_game_state.gameinfo_event,
                            site=_game_state.gameinfo_site,
                            round=_game_state.gameinfo_round,
                            white=_game_state.gameinfo_white,
                            black=_game_state.gameinfo_black
                        )
                        _game_state.session.add(game)
                        _game_state.session.commit()
                        
                        _game_state.gamedbid = _game_state.session.query(func.max(models.Game.id)).scalar()
                        gamemove = models.GameMove(
                            gameid=_game_state.gamedbid,
                            move='',
                            fen=str(_game_state.cboard.fen())
                        )
                        _game_state.session.add(gamemove)
                        _game_state.session.commit()
                        _game_state.boardstates = []
                        _collect_board_state()
                    t = 0
                except Exception as e:
                    if "Another blocking request" not in str(e):
                        print(f"Error in board state check: {e}")
                    pass
        
        if _game_state.pausekeys == 1:
            board.pauseEvents()
        else:
            board.unPauseEvents()
        
        time.sleep(0.1)


def subscribeGame(eventCallback, moveCallback, keyCallback, takebackCallback=None):
    """Subscribe to game events and start the game thread"""
    _game_state.kill = False
    thread = threading.Thread(target=gameThread, args=(eventCallback, moveCallback, keyCallback, takebackCallback))
    thread.daemon = True
    thread.start()


def unsubscribeGame():
    """Stop the game manager"""
    board.ledsOff()
    _game_state.kill = True


def collectBoardState():
    """Public API for collecting board state"""
    _collect_board_state()
