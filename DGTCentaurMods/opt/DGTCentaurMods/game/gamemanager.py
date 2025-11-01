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
from sqlalchemy import create_engine, MetaData, func, select
from scipy.optimize import linear_sum_assignment
import threading
import time
import chess
import sys
import inspect
import numpy as np
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
        self.curturn = 1  # 1 = white, 0 = black
        self.sourcesq = -1
        self.othersourcesq = -1  # Track opponent piece lifts
        self.legalsquares = []
        self.computermove = ""
        self.forcemove = 0
        self.gamedbid = -1
        self.showingpromotion = False
        self.pausekeys = 0
        self.inmenu = 0
        self.boardstates = []
        self.must_check_new_game = False
        
        # Game info
        self.gameinfo_event = ""
        self.gameinfo_site = ""
        self.gameinfo_round = ""
        self.gameinfo_white = ""
        self.gameinfo_black = ""
        
        # Correction mode
        self.correction_mode = False
        self.correction_expected_state = None
        self.correction_iteration = 0
        
        # Opponent move tracking (key fix for the bug)
        self.pending_opponent_move = None  # Stores (from_sq, to_sq, time) when detected during opponent turn
        self.opponent_move_state = None  # Board state when opponent move was detected
        
        # Callbacks
        self.keycallbackfunction = None
        self.movecallbackfunction = None
        self.eventcallbackfunction = None
        self.takebackcallbackfunction = None
        
        # Database
        self.session = None
        self.source = ""


# Global game state instance
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
    # Convert to board coordinate system (0,0 is a1)
    board_col = 7 - col
    board_row = row
    return chr(ord('a') + board_col) + chr(ord('1') + board_row)


def _notation_to_square(notation):
    """Convert chess notation (e.g., 'e4') to square index (0-63)"""
    if len(notation) < 2:
        return -1
    col = ord(notation[0]) - ord('a')
    row = ord(notation[1]) - ord('1')
    board_col = 7 - col
    square = row * 8 + board_col
    return square


def _validate_board_state(current_state, expected_state):
    """Validate board state by comparing piece presence"""
    if current_state is None or expected_state is None:
        return False
    if len(current_state) != 64 or len(expected_state) != 64:
        return False
    return bytearray(current_state) == bytearray(expected_state)


def _collect_board_state():
    """Append the current board state to boardstates"""
    print(f"[gamemanager._collect_board_state] Collecting board state")
    _game_state.boardstates.append(board.getBoardState())


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
    
    missing_origins = []
    wrong_locations = []
    
    for i in range(64):
        if expected_state[i] == 1 and current_state[i] == 0:
            missing_origins.append(i)
        elif expected_state[i] == 0 and current_state[i] == 1:
            wrong_locations.append(i)
    
    if len(missing_origins) == 0 and len(wrong_locations) == 0:
        board.ledsOff()
        return
    
    print(f"[gamemanager._provide_correction_guidance] Found {len(wrong_locations)} wrong pieces, {len(missing_origins)} missing pieces")
    
    if len(wrong_locations) > 0 and len(missing_origins) > 0:
        n_wrong = len(wrong_locations)
        n_missing = len(missing_origins)
        
        if n_wrong == 1 and n_missing == 1:
            from_idx = wrong_locations[0]
            to_idx = missing_origins[0]
        else:
            costs = np.zeros((n_wrong, n_missing))
            for i, wl in enumerate(wrong_locations):
                for j, mo in enumerate(missing_origins):
                    costs[i, j] = _dist(wl, mo)
            row_ind, col_ind = linear_sum_assignment(costs)
            from_idx = wrong_locations[row_ind[0]]
            to_idx = missing_origins[col_ind[0]]
        
        board.ledsOff()
        board.ledFromTo(board.rotateField(from_idx), board.rotateField(to_idx), intensity=5)
        print(f"[gamemanager._provide_correction_guidance] Guiding piece from {chess.square_name(from_idx)} to {chess.square_name(to_idx)}")
    else:
        if len(missing_origins) > 0:
            board.ledsOff()
            for idx in missing_origins:
                board.led(board.rotateField(idx), intensity=5)
            print(f"[gamemanager._provide_correction_guidance] Pieces missing at: {[chess.square_name(sq) for sq in missing_origins]}")
        elif len(wrong_locations) > 0:
            board.ledsOff()
            for idx in wrong_locations:
                board.led(board.rotateField(idx), intensity=5)
            print(f"[gamemanager._provide_correction_guidance] Extra pieces at: {[chess.square_name(sq) for sq in wrong_locations]}")


def _enter_correction_mode():
    """Enter correction mode to guide user in fixing board state"""
    # Don't enter correction mode if we're in the middle of processing a valid move
    if _game_state.sourcesq >= 0 and len(_game_state.legalsquares) > 1:
        print("[gamemanager._enter_correction_mode] Skipping correction - valid move in progress")
        return
    
    _game_state.correction_mode = True
    # Use the most recent board state as the expected state
    # This should represent the last known good position
    if _game_state.boardstates and len(_game_state.boardstates) > 0:
        _game_state.correction_expected_state = _game_state.boardstates[-1]
        print(f"[gamemanager._enter_correction_mode] Using boardstate[-1] as expected state (total states: {len(_game_state.boardstates)})")
    else:
        _game_state.correction_expected_state = None
        print("[gamemanager._enter_correction_mode] Warning: No board states available")
    _game_state.correction_iteration = 0
    board.pauseEvents()
    time.sleep(0.1)
    board.unPauseEvents()
    print("[gamemanager._enter_correction_mode] Entered correction mode")


def _exit_correction_mode():
    """Exit correction mode and check for pending opponent moves"""
    _game_state.correction_mode = False
    correction_expected = _game_state.correction_expected_state
    _game_state.correction_expected_state = None
    print("[gamemanager._exit_correction_mode] Exited correction mode")
    
    # KEY FIX: After exiting correction mode, check for any pending opponent move
    # This handles the case where opponent made a move but correction mode was entered
    time.sleep(0.3)  # Give board state time to stabilize
    
    # First, try to detect opponent move from current board state
    if _check_and_process_opponent_move():
        print("[gamemanager._exit_correction_mode] Successfully processed opponent move after correction")
        return
    
    # If no move detected but we were tracking an opponent move, check if it's still valid
    if _game_state.othersourcesq >= 0:
        current_state = board.getBoardState()
        if current_state and correction_expected:
            # Check if board shows a completed opponent move
            from_squares = []
            to_squares = []
            for i in range(64):
                if correction_expected[i] == 1 and current_state[i] == 0:
                    from_squares.append(i)
                elif correction_expected[i] == 0 and current_state[i] == 1:
                    to_squares.append(i)
            
            # If we have a from and to square, and the from matches what we were tracking
            if len(from_squares) == 1 and from_squares[0] == _game_state.othersourcesq:
                if len(to_squares) == 1:
                    to_sq = to_squares[0]
                    fromname = _square_to_notation(_game_state.othersourcesq)
                    toname = _square_to_notation(to_sq)
                    
                    piece_at_from = _game_state.cboard.piece_at(_game_state.othersourcesq)
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
                                print(f"[gamemanager._exit_correction_mode] Detected opponent move after correction: {move_uci}")
                                _process_move(move_uci, move, _game_state.othersourcesq, to_sq)
                                _game_state.othersourcesq = -1
                                _game_state.opponent_move_state = None
                                return
                        except Exception as e:
                            print(f"[gamemanager._exit_correction_mode] Error processing opponent move: {e}")
    
    # If we were tracking an opponent move but can't detect it, reset tracking
    if _game_state.othersourcesq >= 0:
        print("[gamemanager._exit_correction_mode] Could not detect opponent move, resetting tracking")
        _game_state.othersourcesq = -1
        _game_state.opponent_move_state = None


def _check_and_process_opponent_move():
    """
    Check if the current board state represents a valid opponent move.
    This is the key fix for the bug where opponent moves are forgotten after correction.
    """
    if not _game_state.boardstates or len(_game_state.boardstates) == 0:
        return False
    
    current_state = board.getBoardState()
    expected_state = _game_state.boardstates[-1]
    
    if current_state is None or expected_state is None:
        return False
    if len(current_state) != 64 or len(expected_state) != 64:
        return False
    
    # If board matches expected state, no move detected
    if bytearray(current_state) == bytearray(expected_state):
        return False
    
    # Find squares where pieces changed
    from_squares = []
    to_squares = []
    
    for i in range(64):
        if expected_state[i] == 1 and current_state[i] == 0:
            from_squares.append(i)
        elif expected_state[i] == 0 and current_state[i] == 1:
            to_squares.append(i)
    
    if len(from_squares) != 1:
        return False
    
    from_sq = from_squares[0]
    
    # Check if piece at from_sq belongs to opponent
    pc = _game_state.cboard.color_at(from_sq)
    if pc is None:
        return False
    
    # Check if it's the opponent's turn
    opponent_turn = (_game_state.curturn == 0 and pc == True) or (_game_state.curturn == 1 and pc == False)
    if not opponent_turn:
        return False
    
    # Determine destination square
    if len(to_squares) == 1:
        to_sq = to_squares[0]
    else:
        # Try to find destination from legal moves
        legal_moves_from = [m for m in _game_state.cboard.legal_moves if m.from_square == from_sq]
        if len(legal_moves_from) == 1:
            to_sq = legal_moves_from[0].to_square
        elif len(legal_moves_from) == 0:
            return False
        else:
            # Multiple legal moves - try to match by piece type
            piece_at_from = _game_state.cboard.piece_at(from_sq)
            if piece_at_from is None:
                return False
            
            candidate_to_squares = []
            for sq in range(64):
                if current_state[sq] == 1 and expected_state[sq] == 0:
                    piece_at_sq = _game_state.cboard.piece_at(sq)
                    if piece_at_sq == piece_at_from:
                        candidate_to_squares.append(sq)
            
            if len(candidate_to_squares) == 1:
                to_sq = candidate_to_squares[0]
            else:
                return False
    
    # Construct move
    fromname = _square_to_notation(from_sq)
    toname = _square_to_notation(to_sq)
    
    # Check for promotion
    pname = str(_game_state.cboard.piece_at(from_sq))
    pr = ""
    if (to_sq // 8) == 7 and pname == "P":
        pr = "q"
    elif (to_sq // 8) == 0 and pname == "p":
        pr = "q"
    
    move_uci = fromname + toname + pr
    
    # Validate and process move
    try:
        move = chess.Move.from_uci(move_uci)
        if move in _game_state.cboard.legal_moves:
            print(f"[gamemanager._check_and_process_opponent_move] Detected valid opponent move: {move_uci}")
            _process_move(move_uci, move, from_sq, to_sq)
            return True
    except Exception as e:
        print(f"[gamemanager._check_and_process_opponent_move] Error: {e}")
        import traceback
        traceback.print_exc()
    
    return False


def _process_move(move_uci, move, from_sq, to_sq):
    """Process a valid move: update board, database, and switch turns"""
    # Ensure correction mode is off when processing a valid move
    if _game_state.correction_mode:
        print("[gamemanager._process_move] Exiting correction mode before processing move")
        _game_state.correction_mode = False
        _game_state.correction_expected_state = None
    
    _game_state.cboard.push(move)
    paths.write_fen_log(_game_state.cboard.fen())
    
    gamemove = models.GameMove(
        gameid=_game_state.gamedbid,
        move=move_uci,
        fen=str(_game_state.cboard.fen())
    )
    _game_state.session.add(gamemove)
    _game_state.session.commit()
    
    # Give board sensors time to stabilize after move
    time.sleep(0.2)
    
    # Collect the new board state after move
    _collect_board_state()
    
    _game_state.legalsquares = []
    _game_state.sourcesq = -1
    _game_state.othersourcesq = -1
    _game_state.forcemove = 0
    board.ledsOff()
    
    if _game_state.movecallbackfunction is not None:
        _game_state.movecallbackfunction(move_uci)
    
    board.beep(board.SOUND_GENERAL)
    board.led(to_sq)
    
    # Check outcome and switch turns
    outc = _game_state.cboard.outcome(claim_draw=True)
    if outc is None or outc == "None" or outc == 0:
        if _game_state.curturn == 0:
            _game_state.curturn = 1
            if _game_state.eventcallbackfunction is not None:
                _game_state.eventcallbackfunction(EVENT_WHITE_TURN)
        else:
            _game_state.curturn = 0
            if _game_state.eventcallbackfunction is not None:
                _game_state.eventcallbackfunction(EVENT_BLACK_TURN)
    else:
        board.beep(board.SOUND_GENERAL)
        resultstr = str(_game_state.cboard.result())
        tg = _game_state.session.query(models.Game).filter(models.Game.id == _game_state.gamedbid).first()
        tg.result = resultstr
        _game_state.session.flush()
        _game_state.session.commit()
        if _game_state.eventcallbackfunction is not None:
            _game_state.eventcallbackfunction(str(outc.termination))


def waitForPromotionChoice():
    """Wait for user to select promotion piece via button press"""
    key = board.wait_for_key_up(timeout=60)
    if key == board.Key.BACK:
        return "n"
    elif key == board.Key.TICK:
        return "b"
    elif key == board.Key.UP:
        return "q"
    elif key == board.Key.DOWN:
        return "r"
    else:
        return "q"


def checkLastBoardState():
    """Check if board state matches previous move (takeback detection)"""
    if _game_state.takebackcallbackfunction is None:
        _game_state.must_check_new_game = True
        return False
    
    if len(_game_state.boardstates) < 2:
        return False
    
    print(f"[gamemanager.checkLastBoardState] Checking last board state")
    current = board.getBoardState()
    previous = _game_state.boardstates[-2]
    
    print(f"[gamemanager.checkLastBoardState] Current board state: {current}")
    print(f"[gamemanager.checkLastBoardState] Previous board state: {previous}")
    
    if bytearray(current) == bytearray(previous):
        board.ledsOff()
        _game_state.boardstates = _game_state.boardstates[:-1]
        
        # Remove last move from database
        lastmovemade = _game_state.session.query(models.GameMove).order_by(models.GameMove.id.desc()).first()
        if lastmovemade:
            _game_state.session.delete(lastmovemade)
            _game_state.session.commit()
        
        _game_state.cboard.pop()
        paths.write_fen_log(_game_state.cboard.fen())
        
        # Switch turn
        if _game_state.curturn == 0:
            _game_state.curturn = 1
        else:
            _game_state.curturn = 0
        
        board.beep(board.SOUND_GENERAL)
        if _game_state.takebackcallbackfunction is not None:
            _game_state.takebackcallbackfunction()
        
        # Verify board is correct after takeback
        time.sleep(0.2)
        current_check = board.getBoardState()
        if not _validate_board_state(current_check, _game_state.boardstates[-1] if _game_state.boardstates else None):
            print("[gamemanager.checkLastBoardState] Board state incorrect after takeback, entering correction mode")
            _enter_correction_mode()
        
        return True
    
    return False


def correction_fieldcallback(piece_event, field_hex, square, time_in_seconds):
    """
    Wrapper that intercepts field events during correction mode.
    Validates board state and checks for opponent moves when exiting correction.
    """
    if not _game_state.correction_mode:
        # Normal flow - pass through to fieldcallback
        return fieldcallback(piece_event, field_hex, square, time_in_seconds)
    
    # In correction mode: First check if this is part of a valid move in progress
    # If the current player has a piece lifted (sourcesq >= 0), allow normal flow
    # This prevents correction mode from interfering with valid moves
    field = square + 1
    if piece_event == 1:  # PLACE
        field = ((square + 1) * -1)
    place = field < 0
    if place:
        field = abs(field)
    field = field - 1
    
    # If player has a piece lifted and is placing it, check if it's a valid move
    if place and _game_state.sourcesq >= 0:
        # Check if placing on a legal square
        # If sourcesq is set and we're in correction mode but making a valid move,
        # we should exit correction and let normal flow handle it
        if field in _game_state.legalsquares:
            print("[gamemanager.correction_fieldcallback] Valid move in progress during correction, exiting correction mode")
            _game_state.correction_mode = False
            _game_state.correction_expected_state = None
            # Continue with normal fieldcallback
            return fieldcallback(piece_event, field_hex, square, time_in_seconds)
        elif field == _game_state.sourcesq:
            # Placing back on source - this is allowed, exit correction
            print("[gamemanager.correction_fieldcallback] Piece placed back, exiting correction mode")
            _game_state.correction_mode = False
            _game_state.correction_expected_state = None
            return fieldcallback(piece_event, field_hex, square, time_in_seconds)
    
    # In correction mode: check if board now matches expected after each event
    current_state = board.getBoardState()
    
    if _validate_board_state(current_state, _game_state.correction_expected_state):
        # Board is now correct!
        print("[gamemanager.correction_fieldcallback] Board corrected, exiting correction mode")
        board.ledsOff()
        board.beep(board.SOUND_GENERAL)
        _exit_correction_mode()
        # Don't process this event as it was just a correction move
        return
    
    # Still incorrect, update guidance
    _provide_correction_guidance(current_state, _game_state.correction_expected_state)


def keycallback(key_pressed):
    """Handle key press events"""
    if _game_state.keycallbackfunction is not None:
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
            if _game_state.eventcallbackfunction is not None:
                _game_state.eventcallbackfunction(EVENT_REQUEST_DRAW)
            _game_state.inmenu = 0
        
        if _game_state.inmenu == 1 and key_pressed == board.Key.DOWN:
            epaper.writeText(14, "                   ")
            if _game_state.eventcallbackfunction is not None:
                _game_state.eventcallbackfunction(EVENT_RESIGN_GAME)
            _game_state.inmenu = 0


def fieldcallback(piece_event, field_hex, square, time_in_seconds):
    """Handle piece movement events from the board"""
    field = square + 1
    if piece_event == 1:  # PLACE
        field = ((square + 1) * -1)
    
    print(f"[gamemanager.fieldcallback] piece_event={piece_event} field_hex={field_hex} square={square} field={field} time_in_seconds={time_in_seconds}")
    
    lift = field >= 0
    place = not lift
    
    if place:
        field = abs(field)
    field = field - 1
    
    print(f"[gamemanager.fieldcallback] Field: {field}")
    pc = _game_state.cboard.color_at(field)
    print(f"[gamemanager.fieldcallback] Piece colour: {pc}")
    
    # Check if this is the current player's piece
    vpiece = 0
    if _game_state.curturn == 0 and pc == False:
        vpiece = 1
    if _game_state.curturn == 1 and pc == True:
        vpiece = 1
    
    fieldname = _square_to_notation(field)
    print(f"[gamemanager.fieldcallback] Fieldname: {fieldname}")
    
    legalmoves = _game_state.cboard.legal_moves
    lmoves = list(legalmoves)
    
    # Handle piece lift for current player
    if lift and field not in _game_state.legalsquares and _game_state.sourcesq < 0 and vpiece == 1:
        _game_state.legalsquares = [field]
        _game_state.sourcesq = field
        
        # Generate legal destination squares
        for x in range(0, 64):
            fx = _square_to_notation(x)
            tm = fieldname + fx
            found = False
            try:
                for q in range(0, len(lmoves)):
                    if str(tm[0:4]) == str(lmoves[q])[0:4]:
                        found = True
                        break
            except:
                pass
            if found:
                _game_state.legalsquares.append(x)
    
    # Track opponent piece lifts and detect opponent moves
    if lift and vpiece == 0:
        _game_state.othersourcesq = field
        # Store the board state when opponent piece is lifted (before their move)
        if _game_state.opponent_move_state is None:
            _game_state.opponent_move_state = board.getBoardState()
    
    # Handle opponent piece placement
    if place and vpiece == 0:
        if _game_state.othersourcesq >= 0 and field == _game_state.othersourcesq:
            # Placed back on original square - cancel tracking
            board.ledsOff()
            _game_state.othersourcesq = -1
            _game_state.opponent_move_state = None
        else:
            # Opponent piece placed on a different square - check if it's a valid move
            if _game_state.othersourcesq >= 0:
                # Try to detect and process the opponent move
                from_sq = _game_state.othersourcesq
                to_sq = field
                
                # Check if this could be a valid move
                fromname = _square_to_notation(from_sq)
                toname = _square_to_notation(to_sq)
                
                # Check for promotion
                piece_at_from = _game_state.cboard.piece_at(from_sq)
                if piece_at_from is None:
                    _game_state.othersourcesq = -1
                    _game_state.opponent_move_state = None
                    return
                
                pname = str(piece_at_from)
                pr = ""
                if (to_sq // 8) == 7 and pname == "P":
                    pr = "q"  # Default to queen for opponent promotions
                elif (to_sq // 8) == 0 and pname == "p":
                    pr = "q"  # Default to queen for opponent promotions
                
                move_uci = fromname + toname + pr
                
                # Check if this is a legal move
                try:
                    move = chess.Move.from_uci(move_uci)
                    if move in _game_state.cboard.legal_moves:
                        # Valid opponent move detected!
                        print(f"[gamemanager.fieldcallback] Detected opponent move: {move_uci}")
                        _process_move(move_uci, move, from_sq, to_sq)
                        _game_state.othersourcesq = -1
                        _game_state.opponent_move_state = None
                        return
                    else:
                        # Illegal move - enter correction mode
                        print(f"[gamemanager.fieldcallback] Opponent piece placed on illegal square {field}")
                        _enter_correction_mode()
                        current_state = board.getBoardState()
                        if _game_state.boardstates and len(_game_state.boardstates) > 0:
                            _provide_correction_guidance(current_state, _game_state.boardstates[-1])
                        _game_state.othersourcesq = -1
                        _game_state.opponent_move_state = None
                except Exception as e:
                    print(f"[gamemanager.fieldcallback] Error processing opponent move: {e}")
                    _game_state.othersourcesq = -1
                    _game_state.opponent_move_state = None
    
    # Handle forced moves (computer moves)
    if _game_state.forcemove == 1 and lift and vpiece == 1:
        if fieldname != _game_state.computermove[0:2]:
            _game_state.legalsquares = [field]
        else:
            target = _game_state.computermove[2:4]
            tsq = _notation_to_square(target)
            _game_state.legalsquares = [tsq]
    
    # Handle illegal placements (only for current player's pieces, not opponent's)
    if place and field not in _game_state.legalsquares and vpiece == 1:
        board.beep(board.SOUND_WRONG_MOVE)
        print(f"[gamemanager.fieldcallback] Piece placed on illegal square {field}")
        is_takeback = checkLastBoardState()
        if not is_takeback:
            # Only enter correction mode if we actually have a piece lifted
            if _game_state.sourcesq >= 0:
                _enter_correction_mode()
                current_state = board.getBoardState()
                if _game_state.boardstates and len(_game_state.boardstates) > 0:
                    _provide_correction_guidance(current_state, _game_state.boardstates[-1])
            else:
                # No piece was lifted, so just reset
                board.ledsOff()
                _game_state.legalsquares = []
                _game_state.sourcesq = -1
    
    # Handle valid move completion
    if place and field in _game_state.legalsquares:
        print(f"[gamemanager.fieldcallback] Making move")
        _game_state.newgame = 0
        
        if field == _game_state.sourcesq:
            # Piece placed back
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
            
            # Process the move
            move = chess.Move.from_uci(mv)
            _process_move(mv, move, _game_state.sourcesq, field)


def resignGame(sideresigning):
    """Handle game resignation"""
    resultstr = "0-1" if sideresigning == 1 else "1-0"
    tg = _game_state.session.query(models.Game).filter(models.Game.id == _game_state.gamedbid).first()
    tg.result = resultstr
    _game_state.session.flush()
    _game_state.session.commit()
    if _game_state.eventcallbackfunction is not None:
        _game_state.eventcallbackfunction("Termination.RESIGN")


def getResult():
    """Get the result of the last game"""
    gamedata = _game_state.session.execute(
        select(models.Game.created_at, models.Game.source, models.Game.event, models.Game.site, models.Game.round,
        models.Game.white, models.Game.black, models.Game.result, models.Game.id).
        order_by(models.Game.id.desc())
    ).first()
    return str(gamedata["result"])


def drawGame():
    """Handle game draw"""
    tg = _game_state.session.query(models.Game).filter(models.Game.id == _game_state.gamedbid).first()
    tg.result = "1/2-1/2"
    _game_state.session.flush()
    _game_state.session.commit()
    if _game_state.eventcallbackfunction is not None:
        _game_state.eventcallbackfunction("Termination.DRAW")


def gameThread(eventCallback, moveCallback, keycallbacki, takebackcallbacki):
    """Main game thread that handles game events and board monitoring"""
    _game_state.keycallbackfunction = keycallbacki
    _game_state.movecallbackfunction = moveCallback
    _game_state.eventcallbackfunction = eventCallback
    _game_state.takebackcallbackfunction = takebackcallbacki
    
    board.ledsOff()
    print(f"[gamemanager.gameThread] Subscribing to events")
    print(f"[gamemanager.gameThread] Keycallback: {keycallback}")
    print(f"[gamemanager.gameThread] Fieldcallback: correction_fieldcallback (wraps fieldcallback)")
    
    try:
        board.subscribeEvents(keycallback, correction_fieldcallback)
    except Exception as e:
        print(f"[gamemanager.gameThread] error: {e}")
        print(f"[gamemanager.gameThread] error: {sys.exc_info()[1]}")
        return
    
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
                    
                    if current_state is not None and bytearray(current_state) == START_STATE:
                        if _game_state.cboard.fen() != START_FEN:
                            print("DEBUG: Board state matches start, but FEN doesn't - not triggering NEW_GAME")
                            t = 0
                            continue
                        
                        # Debounce
                        now = time.time()
                        if now - _game_state.last_new_game_time < 1.0:
                            t = 0
                            continue
                        
                        board.ledsOff()
                        _game_state.correction_mode = False
                        _game_state.correction_expected_state = None
                        _game_state.last_new_game_time = now
                        
                        print("DEBUG: Detected starting position - triggering NEW_GAME")
                        _game_state.newgame = 1
                        _game_state.curturn = 1
                        _game_state.cboard = chess.Board(START_FEN)
                        paths.write_fen_log(_game_state.cboard.fen())
                        board.beep(board.SOUND_GENERAL)
                        time.sleep(0.3)
                        board.beep(board.SOUND_GENERAL)
                        board.ledsOff()
                        
                        eventCallback(EVENT_NEW_GAME)
                        eventCallback(EVENT_WHITE_TURN)
                        
                        # Log new game in database
                        game = models.Game(
                            source=_game_state.source,
                            event=_game_state.gameinfo_event,
                            site=_game_state.gameinfo_site,
                            round=_game_state.gameinfo_round,
                            white=_game_state.gameinfo_white,
                            black=_game_state.gameinfo_black
                        )
                        print(game)
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
                    print(f"DEBUG: Error in board state check: {e}")
                    if "Another blocking request" in str(e):
                        print("DEBUG: Skipping board state check due to concurrent request")
                    pass
        
        if _game_state.pausekeys == 1:
            board.pauseEvents()
        if _game_state.pausekeys == 2:
            board.unPauseEvents()
            _game_state.pausekeys = 0
        
        time.sleep(0.1)


def clockThread():
    """Clock thread that decrements time and updates display"""
    global whitetime, blacktime
    while not _game_state.kill:
        time.sleep(2)
        if whitetime > 0 and _game_state.curturn == 1 and _game_state.cboard.fen() != START_FEN:
            whitetime = whitetime - 2
        if blacktime > 0 and _game_state.curturn == 0:
            blacktime = blacktime - 2
        
        wmin = whitetime // 60
        wsec = whitetime % 60
        bmin = blacktime // 60
        bsec = blacktime % 60
        timestr = f"{wmin:02d}:{wsec:02d}       {bmin:02d}:{bsec:02d}"
        if not _game_state.showingpromotion:
            epaper.writeText(13, timestr)


whitetime = 0
blacktime = 0


def setClock(white, black):
    """Set the clock times"""
    global whitetime, blacktime
    whitetime = white
    blacktime = black


def startClock():
    """Start the clock thread"""
    wmin = whitetime // 60
    wsec = whitetime % 60
    bmin = blacktime // 60
    bsec = blacktime % 60
    timestr = f"{wmin:02d}:{wsec:02d}       {bmin:02d}:{bsec:02d}"
    epaper.writeText(13, timestr)
    clockthread = threading.Thread(target=clockThread, args=())
    clockthread.daemon = True
    clockthread.start()


def computerMove(mv, forced=True):
    """Set a computer move that the player is expected to make"""
    if len(mv) < 4:
        return
    _game_state.computermove = mv
    if forced:
        _game_state.forcemove = 1
    
    fromnum = ((ord(mv[1:2]) - ord("1")) * 8) + (ord(mv[0:1]) - ord("a"))
    tonum = ((ord(mv[3:4]) - ord("1")) * 8) + (ord(mv[2:3]) - ord("a"))
    board.ledFromTo(fromnum, tonum)


def setGameInfo(gi_event, gi_site, gi_round, gi_white, gi_black):
    """Set game information for PGN files"""
    _game_state.gameinfo_event = gi_event
    _game_state.gameinfo_site = gi_site
    _game_state.gameinfo_round = gi_round
    _game_state.gameinfo_white = gi_white
    _game_state.gameinfo_black = gi_black


def subscribeGame(eventCallback, moveCallback, keyCallback, takebackCallback=None):
    """Subscribe to the game manager"""
    _game_state.boardstates = []
    _collect_board_state()
    
    _game_state.source = inspect.getsourcefile(sys._getframe(1))
    Session = sessionmaker(bind=models.engine)
    _game_state.session = Session()
    
    gamethread = threading.Thread(target=gameThread, args=([eventCallback, moveCallback, keyCallback, takebackCallback]))
    gamethread.daemon = True
    gamethread.start()


def unsubscribeGame():
    """Stop the game manager"""
    board.ledsOff()
    _game_state.kill = True


# Public API: Export collectBoardState for backward compatibility
def collectBoardState():
    _collect_board_state()
