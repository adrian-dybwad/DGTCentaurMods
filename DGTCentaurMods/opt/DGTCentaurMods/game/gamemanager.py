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

# TODO

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


# Some useful constants
EVENT_NEW_GAME = 1
EVENT_BLACK_TURN = 2
EVENT_WHITE_TURN = 3
EVENT_REQUEST_DRAW = 4
EVENT_RESIGN_GAME = 5

kill = 0
startstate = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')
newgame = 0
last_new_game_time = 0
keycallbackfunction = None
movecallbackfunction = None
eventcallbackfunction = None
takebackcallbackfunction = None
cboard = chess.Board()
curturn = 1
sourcesq = -1
othersourcesq = -1
legalsquares = []
pausekeys = 0
computermove = ""
forcemove = 0
source = ""
gamedbid = -1
session = None
showingpromotion = False

gameinfo_event = ""
gameinfo_site = ""
gameinfo_round = ""
gameinfo_white = ""
gameinfo_black = ""

inmenu = 0
boardstates = []
must_check_new_game = False

# Correction mode state variables
correction_mode = False
correction_expected_state = None
correction_iteration = 0
original_fieldcallback = None

st = board.getBoardState()
for i in range(0, 64):
    if st[i] == 1:
        board.led(i, intensity=5)
    else:
        board.led(i, intensity=1)
    time.sleep(0.05)
    
def collectBoardState():
    # Append the board state to boardstates
    global boardstates
    print(f"[gamemanager.collectBoardState] Collecting board state")
    boardstates.append(board.getBoardState())

def waitForPromotionChoice():
    """Wait for user to select promotion piece via button press"""
    key = board.wait_for_key_up(timeout=60)
    if key == board.Key.BACK:
        return "n"  # Knight
    elif key == board.Key.TICK:
        return "b"  # Bishop
    elif key == board.Key.UP:
        return "q"  # Queen
    elif key == board.Key.DOWN:
        return "r"  # Rook
    else:
        return "q"  # Default to queen on timeout/other    

def checkLastBoardState():
    # If the current board state is the state of the board from the move before
    # then a takeback is in progress
    global boardstates
    global gamebid
    global session
    global cboard
    global takebackcallbackfunction
    global curturn
    global must_check_new_game
    if takebackcallbackfunction != None:
        print(f"[gamemanager.checkLastBoardState] Checking last board state")
        c = board.getBoardState()
        print(f"[gamemanager.checkLastBoardState] Current board state: {c}")
        print(f"[gamemanager.checkLastBoardState] Last board state: {boardstates[len(boardstates) - 2]}")
        if c == boardstates[len(boardstates) - 2]:    
            board.ledsOff()            
            boardstates = boardstates[:-1] 
            # For a takeback we need to remove the last move logged to the database,
            # update the fen. Switch the turn and alert the calling script of a takeback
            lastmovemade = session.query(models.GameMove).order_by(models.GameMove.id.desc()).first()
            session.delete(lastmovemade)
            session.commit()
            cboard.pop()
            paths.write_fen_log(cboard.fen())            
            if curturn == 0:
                curturn = 1
            else:
                curturn = 0
            board.beep(board.SOUND_GENERAL)
            takebackcallbackfunction()
            
            # Verify board is correct after takeback
            time.sleep(0.2)
            current = board.getBoardState()
            if not validate_board_state(current, boardstates[-1] if boardstates else None):
                print("[gamemanager.checkLastBoardState] Board state incorrect after takeback, entering correction mode")
                enter_correction_mode()
            
            return True   
    else:
        print(f"[gamemanager.checkLastBoardState] No takeback detected")
        must_check_new_game = True
    return False    

def validate_board_state(current_state, expected_state):
    """
    Validate board state by comparing piece presence.
    Returns True if board matches expected state.
    
    Args:
        current_state: Current board state from getBoardState()
        expected_state: Expected board state to compare against
    
    Returns:
        bool: True if states match, False otherwise
    """
    if current_state is None or expected_state is None:
        return False
    
    if len(current_state) != 64 or len(expected_state) != 64:
        return False
    
    return bytearray(current_state) == bytearray(expected_state)

def enter_correction_mode():
    """
    Enter correction mode to guide user in fixing board state.
    Pauses and resumes events to reset the event queue.
    """
    global correction_mode, correction_expected_state, correction_iteration
    correction_mode = True
    correction_expected_state = boardstates[-1] if boardstates else None
    correction_iteration = 0
    board.pauseEvents()
    time.sleep(0.1)
    board.unPauseEvents()
    print("[gamemanager.enter_correction_mode] Entered correction mode")

def exit_correction_mode():
    """
    Exit correction mode and resume normal game flow.
    """
    global correction_mode, correction_expected_state
    correction_mode = False
    correction_expected_state = None
    print("[gamemanager.exit_correction_mode] Exited correction mode")

def provide_correction_guidance(current_state, expected_state):
    """
    Provide LED guidance to correct misplaced pieces using Hungarian algorithm.
    
    Computes optimal pairing between misplaced pieces using linear_sum_assignment
    for minimal total movement distance, then lights up LEDs to guide the user.
    
    Args:
        current_state: Current board state from getBoardState()
        expected_state: Expected board state
    """
    if current_state is None or expected_state is None:
        return
    
    if len(current_state) != 64 or len(expected_state) != 64:
        return
    
    # Helper functions for distance calculation
    def _rc(idx):
        """Convert square index to (row, col)"""
        return (idx // 8), (idx % 8)
    
    def _dist(a, b):
        """Manhattan distance between two squares"""
        ar, ac = _rc(a)
        br, bc = _rc(b)
        return abs(ar - br) + abs(ac - bc)
    
    # Compute diffs to find misplaced pieces
    missing_origins = []  # Squares that should have pieces but don't
    wrong_locations = []  # Squares that have pieces but shouldn't
    
    for i in range(64):
        if expected_state[i] == 1 and current_state[i] == 0:
            missing_origins.append(i)
        elif expected_state[i] == 0 and current_state[i] == 1:
            wrong_locations.append(i)
    
    if len(missing_origins) == 0 and len(wrong_locations) == 0:
        # Board is correct
        board.ledsOff()
        return
    
    print(f"[gamemanager.provide_correction_guidance] Found {len(wrong_locations)} wrong pieces, {len(missing_origins)} missing pieces")
    
    # Guide one piece at a time
    if len(wrong_locations) > 0 and len(missing_origins) > 0:
        # Use Hungarian algorithm for optimal pairing
        n_wrong = len(wrong_locations)
        n_missing = len(missing_origins)
        
        if n_wrong == 1 and n_missing == 1:
            # Simple case - just pair the only two
            from_idx = wrong_locations[0]
            to_idx = missing_origins[0]
        else:
            # Create cost matrix based on Manhattan distances
            costs = np.zeros((n_wrong, n_missing))
            for i, wl in enumerate(wrong_locations):
                for j, mo in enumerate(missing_origins):
                    costs[i, j] = _dist(wl, mo)
            
            # Find optimal assignment
            row_ind, col_ind = linear_sum_assignment(costs)
            
            # Guide the first pair
            from_idx = wrong_locations[row_ind[0]]
            to_idx = missing_origins[col_ind[0]]
        
        board.ledsOff()
        board.ledFromTo(from_idx, to_idx, intensity=5)
        print(f"[gamemanager.provide_correction_guidance] Guiding piece from {chess.square_name(from_idx)} to {chess.square_name(to_idx)}")
    else:
        # Only pieces missing or only extra pieces
        if len(missing_origins) > 0:
            # Light up the squares where pieces should be
            board.ledsOff()
            for idx in missing_origins:
                board.led(idx, intensity=5)
            print(f"[gamemanager.provide_correction_guidance] Pieces missing at: {[chess.square_name(sq) for sq in missing_origins]}")
        elif len(wrong_locations) > 0:
            # Light up the squares where pieces shouldn't be
            board.ledsOff()
            for idx in wrong_locations:
                board.led(idx, intensity=5)
            print(f"[gamemanager.provide_correction_guidance] Extra pieces at: {[chess.square_name(sq) for sq in wrong_locations]}")


def _check_misplaced_pieces(current_state):
    """
    Check if pieces are misplaced compared to the expected board state.
    
    Iteratively uses Hungarian algorithm to guide optimal piece corrections.
    Provides LED guidance and waits for corrections with change detection.
    Supports user escape via BACK key after several iterations.
    
    Args:
        current_state: The initial current board state to check
    """
    global boardstates, correction_iteration
    
    if not boardstates or len(boardstates) == 0:
        return
    
    expected_state = boardstates[-1]
    
    if expected_state is None or len(expected_state) != 64:
        return
    
    # Check if already correct
    if bytearray(current_state) == bytearray(expected_state):
        print(f"[gamemanager._check_misplaced_pieces] Board already correct")
        board.ledsOff()
        return
    
    print(f"[gamemanager._check_misplaced_pieces] Misplaced pieces detected")
    print(f"[gamemanager._check_misplaced_pieces] Expected: {board.printBoardState(expected_state)}")
    print(f"[gamemanager._check_misplaced_pieces] Current:  {board.printBoardState(current_state)}")
    
    # Iteratively check and guide until all pieces are correctly placed
    max_iterations = 100
    iteration = 0
    
    # Helper function for distance calculation
    def _dist(a, b):
        """Manhattan distance between two squares"""
        ar, ac = (a // 8), (a % 8)
        br, bc = (b // 8), (b % 8)
        return abs(ar - br) + abs(ac - bc)
    
    while iteration < max_iterations:
        iteration += 1
        correction_iteration = iteration
        
        # Get fresh board state for this iteration
        if iteration == 1:
            current = current_state
        else:
            current = board.getBoardState()
        
        if current is None or len(current) != 64:
            print(f"[gamemanager._check_misplaced_pieces] Invalid current state length: {len(current) if current else 'None'}")
            board.ledsOff()
            return
        
        # Check if states match
        if bytearray(current) == bytearray(expected_state):
            print(f"[gamemanager._check_misplaced_pieces] All pieces correctly placed after {iteration} iteration(s)")
            board.ledsOff()
            return
        
        # Compute mismatches
        missing_origins = []
        wrong_locations = []
        
        for i in range(64):
            if expected_state[i] == 1 and current[i] == 0:
                missing_origins.append(i)
            elif expected_state[i] == 0 and current[i] == 1:
                wrong_locations.append(i)
        
        mismatch_count = len(missing_origins) + len(wrong_locations)
        
        if mismatch_count == 0:
            print(f"[gamemanager._check_misplaced_pieces] All pieces correctly placed after {iteration} iteration(s)")
            board.ledsOff()
            return
        
        # Guide one piece at a time
        if len(wrong_locations) > 0 and len(missing_origins) > 0:
            # Pair wrong→missing by nearest-neighbor (Manhattan distance)
            best_pair = None
            best_d = 1 << 30
            for wl in wrong_locations:
                for mo in missing_origins:
                    d = _dist(wl, mo)
                    if d < best_d:
                        best_d = d
                        best_pair = (wl, mo)
            
            if best_pair:
                from_idx, to_idx = best_pair
                board.ledsOff()
                board.ledFromTo(from_idx, to_idx, intensity=5)
                print(f"[gamemanager._check_misplaced_pieces] Iteration {iteration}: Guiding piece from {from_idx} to {to_idx}")
        else:
            # Only pieces missing or only extra pieces
            if len(missing_origins) > 0:
                # Light up the squares where pieces should be
                board.ledsOff()
                for idx in missing_origins:
                    board.led(idx, intensity=5)
                print(f"[gamemanager._check_misplaced_pieces] Iteration {iteration}: Pieces missing at: {missing_origins}")
            elif len(wrong_locations) > 0:
                # Light up the squares where pieces shouldn't be
                board.ledsOff()
                for idx in wrong_locations:
                    board.led(idx, intensity=5)
                print(f"[gamemanager._check_misplaced_pieces] Iteration {iteration}: Extra pieces at: {wrong_locations}")
        
        # Wait for user to make the correction before checking again
        time.sleep(0.5)
    
    print(f"[gamemanager._check_misplaced_pieces] Warning: Max iterations ({max_iterations}) reached, exiting")
    board.ledsOff()


def guideMisplacedPiece(field, sourcesq, othersourcesq, vpiece):
    """
    Guide the user to correct misplaced pieces using LED indicators.
    
    Enters correction mode which intercepts field callbacks and provides
    LED guidance until the board state matches the expected state.
    
    Args:
        field: The square where the illegal piece was placed
        sourcesq: The source square of the current player's piece being moved
        othersourcesq: The source square of an opponent's piece that was lifted
        vpiece: Whether the piece belongs to the current player (1) or opponent (0)
    """
    print(f"[gamemanager.guideMisplacedPiece] Entering correction mode for field {field}")
    enter_correction_mode()
    current_state = board.getBoardState()
    if boardstates and len(boardstates) > 0:
        provide_correction_guidance(current_state, boardstates[-1])

def correction_fieldcallback(piece_event, field_hex, square, time_in_seconds):
    """
    Wrapper that intercepts field events during correction mode.
    Validates board state and only passes through to normal game flow when correct.
    
    Args:
        piece_event: 0 for lift, 1 for place
        field_hex: Hex value of the field
        square: Square index (0-63)
        time_in_seconds: Time of the event
    """
    global correction_mode, correction_expected_state, boardstates, cboard, original_fieldcallback
    
    if not correction_mode:
        # Normal flow - pass through to original callback
        return fieldcallback(piece_event, field_hex, square, time_in_seconds)
    
    # In correction mode: check if board now matches expected after each event
    current_state = board.getBoardState()
    
    if validate_board_state(current_state, correction_expected_state):
        # Board is now correct!
        print("[gamemanager.correction_fieldcallback] Board corrected, exiting correction mode")
        board.ledsOff()
        board.beep(board.SOUND_GENERAL)
        exit_correction_mode()
        # Don't process this event through normal flow, just exit correction
        return
    
    # Still incorrect, update guidance
    provide_correction_guidance(current_state, correction_expected_state)

def keycallback(key_pressed):
    # Receives the key pressed and passes back to the script calling game manager
    # Here we make an exception though and takeover control of the ? key. We can use this
    # key to present a menu for draw offers or resigning.
    global keycallbackfunction
    global eventcallbackfunction
    global inmenu
    if keycallbackfunction != None:
        if inmenu == 0 and key_pressed != board.Key.HELP:
            keycallbackfunction(key_pressed)
        if inmenu == 0 and key_pressed == board.Key.HELP:
            # If we're not already in the menu and the user presses the question mark
            # key then let's bring up the menu
            inmenu = 1
            epaper.resignDrawMenu(14)
        if inmenu == 1 and key_pressed == board.Key.BACK:
            epaper.writeText(14,"                   ")
        if inmenu == 1 and key_pressed == board.Key.UP:
            epaper.writeText(14,"                   ")
            eventcallbackfunction(EVENT_REQUEST_DRAW)
            inmenu = 0
        if inmenu == 1 and key_pressed == board.Key.DOWN:
            epaper.writeText(14,"                   ")
            eventcallbackfunction(EVENT_RESIGN_GAME)
            inmenu = 0

def fieldcallback(piece_event, field, time_in_seconds):
    # Receives field events. Positive is a field lift, negative is a field place. Numbering 0 = a1, 63 = h8
    # Use this to calculate moves
    field = square + 1 # Convert to positive field number
    if piece_event == 1: # PLACE
        field = ((square + 1) * -1) # Convert to negative field number

    print(f"[gamemanager.fieldcallback] piece_event={piece_event} field_hex={field} field={field} time_in_seconds={time_in_seconds}")
    global cboard
    global curturn
    global movecallbackfunction
    global sourcesq
    global othersourcesq
    global legalsquares
    global eventcallbackfunction
    global newgame
    global pausekeys
    global computermove
    global forcemove
    global source
    global gamedbid
    global session
    global showingpromotion
    lift = 0
    place = 0
    if piece_event == 0:
        lift = 1
    else:
        place = 1
    #     field = field * -1
    # field = field - 1
    # No extra index remapping here; LED helpers expect chess indices 0(a1)..63(h8)
    # Check the piece colour against the current turn
    print(f"[gamemanager.fieldcallback] Field: {field}")
    pc = cboard.color_at(field)
    print(f"[gamemanager.fieldcallback] Piece colour: {pc}")
    vpiece = 0
    if curturn == 0 and pc == False:
        vpiece = 1
    if curturn == 1 and pc == True:
        vpiece = 1
    squarerow = (field // 8)
    squarecol = (field % 8)
    squarecol = 7 - squarecol
    fieldname = chr(ord("a") + (7 - squarecol)) + chr(ord("1") + squarerow)
    print(f"[gamemanager.fieldcallback] Fieldname: {fieldname}")
    legalmoves = cboard.legal_moves
    lmoves = list(legalmoves)
    if lift == 1 and field not in legalsquares and sourcesq < 0 and vpiece == 1:
        # Generate a list of places this piece can move to
        lifted = 1
        legalsquares = []
        legalsquares.append(field)
        sourcesq = field
        for x in range(0, 64):
            sqxr = (x // 8)
            sqxc = (x % 8)
            sqxc = 7 - sqxc
            fx = chr(ord("a") + (7 - sqxc)) + chr(ord("1") + sqxr)
            tm = fieldname + fx
            found = 0
            try:
                for q in range(0,len(lmoves)):
                    if str(tm[0:4]) == str(lmoves[q])[0:4]:
                        found = 1
                        break
            except:
                pass
            if found == 1:
                legalsquares.append(x)
    # Track opposing side lifts so we can guide returning them if moved
    if lift == 1 and vpiece == 0:
        othersourcesq = field
    # If opponent piece is placed back on original square, turn LEDs off and reset
    if place == 1 and vpiece == 0 and othersourcesq >= 0 and field == othersourcesq:
        board.ledsOff()
        othersourcesq = -1
    if forcemove == 1 and lift == 1 and vpiece == 1:
        # If this is a forced move (computer move) then the piece lifted should equal the start of computermove
        # otherwise set legalsquares so they can just put the piece back down! If it is the correct piece then
        # adjust legalsquares so to only include the target square
        if fieldname != computermove[0:2]:
            # Forced move but wrong piece lifted
            legalsquares = []
            legalsquares.append(field)
        else:
            # Forced move, correct piece lifted, limit legal squares
            target = computermove[2:4]
            # Convert the text in target to the field number
            sqcol = ord(target[0:1]) - ord('a')
            sqrow = ord(target[1:2]) - ord('1')
            tsq = (sqrow * 8) + (sqcol)
            legalsquares = []
            legalsquares.append(tsq)
    if place == 1 and field not in legalsquares:
        board.beep(board.SOUND_WRONG_MOVE)
        print(f"[gamemanager.fieldcallback] Piece placed on illegal square {field}")
        is_takeback = checkLastBoardState()
        if not is_takeback:
            guideMisplacedPiece(field, sourcesq, othersourcesq, vpiece)
    
    print(f"[gamemanager.fieldcallback] must_check_new_game: {must_check_new_game}")
    print(f"[gamemanager.fieldcallback] field: {field}")
    print(f"[gamemanager.fieldcallback] legalsquares: {legalsquares}")
    if place == 1 and field in legalsquares:
        print(f"[gamemanager.fieldcallback] Making move")
        newgame = 0
        if field == sourcesq:
            # Piece has simply been placed back
            board.ledsOff()
            sourcesq = -1
            legalsquares = []
        else:
            # Piece has been moved
            squarerow = (sourcesq // 8)
            squarecol = (sourcesq % 8)
            squarecol = 7 - squarecol
            fromname = chr(ord("a") + (7 - squarecol)) + chr(ord("1") + squarerow)
            squarerow = (field // 8)
            squarecol = (field % 8)
            squarecol = 7 - squarecol
            toname = chr(ord("a") + (7 - squarecol)) + chr(ord("1") + squarerow)
            # Promotion
            # If this is a WPAWN and squarerow is 7
            # or a BPAWN and squarerow is 0
            pname = str(cboard.piece_at(sourcesq))
            pr = ""
            if (field // 8) == 7 and pname == "P":
                screenback = epaper.epaperbuffer.copy()
                #Beep
                board.beep(board.SOUND_GENERAL)
                if forcemove == 0:
                    showingpromotion = True
                    epaper.promotionOptions(13)
                    pausekeys = 1
                    time.sleep(1)
                    pr = waitForPromotionChoice()
                    epaper.epaperbuffer = screenback.copy()
                    showingpromotion = False
                    pausekeys = 2
            if (field // 8) == 0 and pname == "p":
                screenback = epaper.epaperbuffer.copy()
                #Beep
                board.beep(board.SOUND_GENERAL)
                if forcemove == 0:
                    showingpromotion = True
                    epaper.promotionOptions(13)
                    pausekeys = 1
                    time.sleep(1)
                    pr = waitForPromotionChoice()
                    showingpromotion = False
                    epaper.epaperbuffer = screenback.copy()
                    pausekeys = 2
                    
            if forcemove == 1:
                mv = computermove
            else:
                mv = fromname + toname + pr
            # Make the move and update fen.log
            cboard.push(chess.Move.from_uci(mv))
            paths.write_fen_log(cboard.fen())
            gamemove = models.GameMove(
                gameid=gamedbid,
                move=mv,
                fen=str(cboard.fen())
            )
            session.add(gamemove)
            session.commit()
            collectBoardState()
            legalsquares = []
            sourcesq = -1
            board.ledsOff()
            forcemove = 0
            if movecallbackfunction != None:
                movecallbackfunction(mv)
            board.beep(board.SOUND_GENERAL)
            # Also light up the square moved to
            board.led(field)
            # Check the outcome
            outc = cboard.outcome(claim_draw=True)
            if outc == None or outc == "None" or outc == 0:
                # Switch the turn
                if curturn == 0:
                    curturn = 1
                    if eventcallbackfunction != None:
                        eventcallbackfunction(EVENT_WHITE_TURN)
                else:
                    curturn = 0
                    if eventcallbackfunction != None:
                        eventcallbackfunction(EVENT_BLACK_TURN)
            else:
                board.beep(board.SOUND_GENERAL)
                # Depending on the outcome we can update the game information for the result
                resultstr = str(cboard.result())
                tg = session.query(models.Game).filter(models.Game.id == gamedbid).first()
                tg.result = resultstr
                session.flush()
                session.commit()
                eventcallbackfunction(str(outc.termination))

def resignGame(sideresigning):
    # Take care of updating the data for a resigned game and callback to the program with the
    # winner. sideresigning = 1 for white, 2 for black
    resultstr = ""
    if sideresigning == 1:
        resultstr = "0-1"
    else:
        resultstr = "1-0"
    tg = session.query(models.Game).filter(models.Game.id == gamedbid).first()
    tg.result = resultstr
    session.flush()
    session.commit()
    eventcallbackfunction("Termination.RESIGN")
    
def getResult():
    # Looks up the result of the last game and returns it
    gamedata = session.execute(
        select(models.Game.created_at, models.Game.source, models.Game.event, models.Game.site, models.Game.round,
        models.Game.white, models.Game.black, models.Game.result, models.Game.id).
        order_by(models.Game.id.desc())
    ).first()
    return str(gamedata["result"])

def drawGame():
    # Take care of updating the data for a drawn game
    tg = session.query(models.Game).filter(models.Game.id == gamedbid).first()
    tg.result = "1/2-1/2"
    session.flush()
    session.commit()
    eventcallbackfunction("Termination.DRAW")

def gameThread(eventCallback, moveCallback, keycallbacki, takebackcallbacki):
    # The main thread handles the actual chess game functionality and calls back to
    # eventCallback with game events and
    # moveCallback with the actual moves made
    global kill
    global startstate
    global newgame
    global cboard
    global curturn
    global keycallbackfunction
    global movecallbackfunction
    global eventcallbackfunction
    global takebackcallbackfunction
    global pausekeys
    global source
    global gamedbid
    global session
    global gameinfo_event
    global gameinfo_site
    global gameinfo_round
    global gameinfo_white
    global gameinfo_black
    global must_check_new_game
    keycallbackfunction = keycallbacki
    movecallbackfunction = moveCallback
    eventcallbackfunction = eventCallback
    takebackcallbackfunction = takebackcallbacki
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
    pausekeys = 0
    while kill == 0:
        # Detect if a new game has begun
        if newgame == 0:
            if t < 5:
                t = t + 1
            else:
                try:
                    # Debug: Log board state comparison
                    #print(f"DEBUG: Board state check - current_state length: {len(current_state)}, startstate length: {len(startstate)}")
                    #print(f"DEBUG: States equal: {bytearray(current_state) == startstate}")
                    # Always refresh current_state before comparing to avoid stale reads
                    current_state = None
                    if must_check_new_game:
                        current_state = board.getBoardState()
                        _check_misplaced_pieces(current_state)
                        must_check_new_game = False
                    if current_state != None and bytearray(current_state) == startstate:
                        # Also validate chess board is in starting position to ensure new game trigger
                        if cboard.fen() != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1":
                            print("DEBUG: Board state matches start, but FEN doesn't - not triggering NEW_GAME")
                            t = 0
                            continue
                        
                        # Debounce NEW_GAME detection to avoid rapid retriggers
                        global last_new_game_time
                        now = time.time()
                        if now - last_new_game_time < 1.0:
                            t = 0
                            continue
                        last_new_game_time = now
                        print("DEBUG: Detected starting position - triggering NEW_GAME")
                        newgame = 1
                        curturn = 1
                        cboard = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
                        paths.write_fen_log(cboard.fen())
                        board.beep(board.SOUND_GENERAL)
                        time.sleep(0.3)
                        board.beep(board.SOUND_GENERAL)
                        board.ledsOff()
                        eventCallback(EVENT_NEW_GAME)
                        eventCallback(EVENT_WHITE_TURN)
                        # Log a new game in the db
                        game = models.Game(
                            source=source,
                            event=gameinfo_event,
                            site=gameinfo_site,
                            round=gameinfo_round,
                            white=gameinfo_white,
                            black=gameinfo_black
                        )
                        print(game)
                        session.add(game)
                        session.commit()                        
                        # Get the max game id as that is this game id and fill it into gamedbid
                        gamedbid = session.query(func.max(models.Game.id)).scalar()
                        # Now make an entry in GameMove for this start state
                        gamemove = models.GameMove(
                            gameid = gamedbid,
                            move = '',
                            fen = str(cboard.fen())
                        )
                        session.add(gamemove)
                        session.commit()
                        boardstates = []
                        collectBoardState()
                    t = 0
                except Exception as e:
                    print(f"DEBUG: Error in board state check: {e}")
                    # If it's a concurrency error, skip this check cycle
                    if "Another blocking request" in str(e):
                        print("DEBUG: Skipping board state check due to concurrent request")
                    pass
        if pausekeys == 1:
            board.pauseEvents()
        if pausekeys == 2:
            board.unPauseEvents()
            pausekeys = 0
        time.sleep(0.1)

def clockThread():
    # This thread just decrements the clock and updates the epaper
    global whitetime
    global blacktime
    global curturn
    global kill
    global cboard
    global showingpromotion
    while kill == 0:
        time.sleep(2) # epaper refresh rate means we can only have an accuracy of around 2 seconds :(
        if whitetime > 0 and curturn == 1 and cboard.fen() != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1":
            whitetime = whitetime - 2
        if blacktime > 0 and curturn == 0:
            blacktime = blacktime - 2
        wmin = whitetime // 60
        wsec = whitetime % 60
        bmin = blacktime // 60
        bsec = blacktime % 60
        timestr = "{:02d}".format(wmin) + ":" + "{:02d}".format(wsec) + "       " + "{:02d}".format(
            bmin) + ":" + "{:02d}".format(bsec)
        if showingpromotion == False:
            epaper.writeText(13, timestr)

whitetime = 0
blacktime = 0
def setClock(white,black):
    # Set the clock
    global whitetime
    global blacktime
    whitetime = white
    blacktime = black

def startClock():
    # Start the clock. It writes to line 13
    wmin = whitetime // 60
    wsec = whitetime % 60
    bmin = blacktime // 60
    bsec = blacktime % 60
    timestr = "{:02d}".format(wmin) + ":" + "{:02d}".format(wsec) + "       " + "{:02d}".format(bmin) + ":" + "{:02d}".format(bsec)
    epaper.writeText(13,timestr)
    clockthread = threading.Thread(target=clockThread, args=())
    clockthread.daemon = True
    clockthread.start()

def computerMove(mv, forced = True):
    # Set the computer move that the player is expected to make
    # in the format b2b4 , g7g8q , etc
    global computermove
    global forcemove
    if len(mv) < 4:
        return
    # First set the globals so that the thread knows there is a computer move
    computermove = mv
    if forced == True:
        forcemove = 1
    # Next indicate this on the board. First convert the text representation to the field number
    fromnum = ((ord(mv[1:2]) - ord("1")) * 8) + (ord(mv[0:1]) - ord("a"))
    tonum = ((ord(mv[3:4]) - ord("1")) * 8) + (ord(mv[2:3]) - ord("a"))
    # Then light it up!
    board.ledFromTo(fromnum,tonum)  

def setGameInfo(gi_event,gi_site,gi_round,gi_white,gi_black):
    # Call before subscribing if you want to set further information about the game for the PGN files
    global gameinfo_event
    global gameinfo_site
    global gameinfo_round
    global gameinfo_white
    global gameinfo_black
    gameinfo_event = gi_event
    gameinfo_site = gi_site
    gameinfo_round = gi_round
    gameinfo_white = gi_white
    gameinfo_black = gi_black

def subscribeGame(eventCallback, moveCallback, keyCallback, takebackCallback = None):
    # Subscribe to the game manager
    global source
    global gamedbid
    global session
    global boardstates
    
    boardstates = []
    #board.getBoardState()
    #board.getBoardState()
    collectBoardState()
    
    source = inspect.getsourcefile(sys._getframe(1))
    Session = sessionmaker(bind=models.engine)
    session = Session()

    # TODO: This is a hack to clear the serial buffer. It should be done in the board thread.
    #board.clearSerial()
    gamethread = threading.Thread(target=gameThread, args=([eventCallback, moveCallback, keyCallback, takebackCallback]))
    gamethread.daemon = True
    gamethread.start()

def unsubscribeGame():
    # Stops the game manager
    global kill
    board.ledsOff()
    kill = 1
