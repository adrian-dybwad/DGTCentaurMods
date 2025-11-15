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
from DGTCentaurMods.board.logging import log, logging


# Event constants
EVENT_NEW_GAME = 1
EVENT_BLACK_TURN = 2
EVENT_WHITE_TURN = 3
EVENT_REQUEST_DRAW = 4
EVENT_RESIGN_GAME = 5

# Board constants
BOARD_SIZE = 64
BOARD_WIDTH = 8
PROMOTION_ROW_WHITE = 7
PROMOTION_ROW_BLACK = 0
INVALID_SQUARE = -1

# Clock constants
SECONDS_PER_MINUTE = 60
CLOCK_DECREMENT_SECONDS = 2
CLOCK_DISPLAY_LINE = 13
PROMOTION_DISPLAY_LINE = 13

# Move constants
MIN_UCI_MOVE_LENGTH = 4

# Game constants
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# Threading lock for critical sections
_game_lock = threading.Lock()

kill = 0
startstate = bytearray(b'\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01')
keycallbackfunction = None
movecallbackfunction = None
eventcallbackfunction = None
takebackcallbackfunction = None
cboard = chess.Board()
curturn = 1
sourcesq = -1
othersourcesq = -1
legalsquares = []
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

# Correction mode state variables
correction_mode = False
correction_expected_state = None
correction_just_exited = False  # Flag to suppress stale events immediately after correction mode exits

def collectBoardState():
    # Append the board state to boardstates
    global boardstates
    global cboard
    log.info(f"[gamemanager.collectBoardState] Collecting board state")
    boardstates.append(board.getChessState())
    print(cboard)

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
    global gamedbid
    global session
    global cboard
    global takebackcallbackfunction
    global curturn
    
    # Validate we can perform takeback
    if takebackcallbackfunction is None:
        return False
    
    # Need at least 2 board states (initial + at least one move)
    if len(boardstates) <= 1:
        log.info(f"[gamemanager.checkLastBoardState] Not enough moves to takeback")
        return False
    
    # Check if we're trying to takeback the initial position
    if len(cboard.move_stack) == 0:
        log.info(f"[gamemanager.checkLastBoardState] Cannot takeback initial position")
        return False
    
    with _game_lock:
        if takebackcallbackfunction is not None and len(boardstates) > 1:
            log.info(f"[gamemanager.checkLastBoardState] Checking last board state")
            current_state = board.getChessState()
            log.info(f"[gamemanager.checkLastBoardState] Current board state:")
            board.printChessState(current_state)
            log.info(f"[gamemanager.checkLastBoardState] Last board state:")
            board.printChessState(boardstates[len(boardstates) - 2])
            if current_state == boardstates[len(boardstates) - 2]:    
                board.ledsOff()            
                boardstates = boardstates[:-1] 
                # For a takeback we need to remove the last move logged to the database,
                # update the fen. Switch the turn and alert the calling script of a takeback
                lastmovemade = session.query(models.GameMove).order_by(models.GameMove.id.desc()).first()
                session.delete(lastmovemade)
                session.commit()
                try:
                    cboard.pop()
                    paths.write_fen_log(cboard.fen())
                    _switch_turn()
                    board.beep(board.SOUND_GENERAL)
                    _safe_callback(takebackcallbackfunction)
                except Exception as e:
                    log.error(f"[gamemanager.checkLastBoardState] Error during takeback: {e}")
                    # Try to restore state
                    try:
                        session.rollback()
                    except:
                        pass
                    return False
                
                # Verify board is correct after takeback
                time.sleep(0.2)
                current = board.getChessState()
                if not validate_board_state(current, boardstates[-1] if boardstates else None):
                    log.info("[gamemanager.checkLastBoardState] Board state incorrect after takeback, entering correction mode")
                    enter_correction_mode()
                
                return True   
        else:
            log.info(f"[gamemanager.checkLastBoardState] No takeback detected")
    return False    

def validate_board_state(current_state, expected_state):
    """
    Validate board state by comparing piece presence.
    Returns True if board matches expected state.
    
    Args:
        current_state: Current board state from getChessState()
        expected_state: Expected board state to compare against
    
    Returns:
        bool: True if states match, False otherwise
    """
    if current_state is None or expected_state is None:
        return False
    
    if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
        return False
    
    return bytearray(current_state) == bytearray(expected_state)

def _uci_to_squares(uci_move):
    """
    Convert UCI move string to square indices.
    
    Args:
        uci_move: UCI move string (e.g., "e2e4")
    
    Returns:
        tuple: (from_square, to_square) as integers (0-63)
    """
    if len(uci_move) < MIN_UCI_MOVE_LENGTH:
        return None, None
    fromnum = ((ord(uci_move[1:2]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[0:1]) - ord("a"))
    tonum = ((ord(uci_move[3:4]) - ord("1")) * BOARD_WIDTH) + (ord(uci_move[2:3]) - ord("a"))
    return fromnum, tonum

def _switch_turn():
    """Switch the current turn (0->1 or 1->0)."""
    global curturn
    curturn = 1 - curturn

def _switch_turn_with_event():
    """Switch the current turn and trigger appropriate event callback."""
    global curturn, eventcallbackfunction
    # Switch turn inside lock
    with _game_lock:
        if curturn == 0:
            curturn = 1
            event_to_trigger = EVENT_WHITE_TURN
        else:
            curturn = 0
            event_to_trigger = EVENT_BLACK_TURN
    
    # Call callback OUTSIDE lock to avoid deadlock if callback accesses gamemanager
    # Callbacks may call gamemanager functions which could try to acquire the same lock
    _safe_callback(eventcallbackfunction, event_to_trigger)

def _update_game_result(resultstr, termination, context=""):
    """
    Update game result in database and trigger event callback.
    
    Args:
        resultstr: Result string (e.g., "1-0", "0-1", "1/2-1/2")
        termination: Termination string for event callback (e.g., "Termination.RESIGN", "Termination.DRAW")
        context: Context string for logging (function name)
    """
    global gamedbid, session, eventcallbackfunction
    with _game_lock:
        try:
            tg = session.query(models.Game).filter(models.Game.id == gamedbid).first()
            if tg is not None:
                tg.result = resultstr
                session.flush()
                session.commit()
            else:
                log.warning(f"[gamemanager.{context}] Game with id {gamedbid} not found in database, cannot update result")
        except Exception as e:
            log.error(f"[gamemanager.{context}] Database error updating result: {e}")
            session.rollback()
    
    # Call callback OUTSIDE lock to avoid deadlock if callback accesses gamemanager
    # Callbacks may call gamemanager functions (like getBoard(), getFEN()) which could try to acquire the same lock
    _safe_callback(eventcallbackfunction, termination)

def _handle_promotion(field, piece_name, forcemove):
    """
    Handle pawn promotion by prompting user for piece choice.
    
    Args:
        field: Target square index
        piece_name: Piece symbol ("P" for white, "p" for black)
        forcemove: Whether this is a forced move (no user prompt)
    
    Returns:
        str: Promotion piece suffix ("q", "r", "b", "n") or empty string
    """
    global showingpromotion
    
    # Check if promotion is needed
    is_white_promotion = (field // BOARD_WIDTH) == PROMOTION_ROW_WHITE and piece_name == "P"
    is_black_promotion = (field // BOARD_WIDTH) == PROMOTION_ROW_BLACK and piece_name == "p"
    
    if not (is_white_promotion or is_black_promotion):
        return ""
    
    board.beep(board.SOUND_GENERAL)
    if forcemove == 0:
        screenback = epaper.epaperbuffer.copy()
        showingpromotion = True
        epaper.promotionOptions(PROMOTION_DISPLAY_LINE)
        promotion_choice = waitForPromotionChoice()
        showingpromotion = False
        epaper.epaperbuffer = screenback.copy()
        return promotion_choice
    return ""

def _format_time(white_seconds, black_seconds):
    """
    Format time display string for clock.
    
    Args:
        white_seconds: White player's remaining seconds
        black_seconds: Black player's remaining seconds
    
    Returns:
        str: Formatted time string "MM:SS       MM:SS"
    """
    wmin = white_seconds // SECONDS_PER_MINUTE
    wsec = white_seconds % SECONDS_PER_MINUTE
    bmin = black_seconds // SECONDS_PER_MINUTE
    bsec = black_seconds % SECONDS_PER_MINUTE
    return "{:02d}".format(wmin) + ":" + "{:02d}".format(wsec) + "       " + "{:02d}".format(bmin) + ":" + "{:02d}".format(bsec)

def _calculate_legal_squares(field):
    """
    Calculate legal destination squares for a piece at the given field.
    
    Args:
        field: Source square index (0-63)
    
    Returns:
        list: List of legal destination square indices, including the source square
    """
    global cboard
    legalmoves = cboard.legal_moves
    legalsquares = [field]  # Include source square
    
    for move in legalmoves:
        if move.from_square == field:
            legalsquares.append(move.to_square)
    
    return legalsquares

def _reset_move_state():
    """
    Reset move-related state variables after a move is completed.
    """
    global legalsquares, sourcesq, forcemove
    legalsquares = []
    sourcesq = -1
    board.ledsOff()
    forcemove = 0

def _is_board_in_starting_position():
    """
    Check if physical board is in starting position.
    
    Returns:
        bool: True if board matches starting position
    """
    current_state = board.getChessState()
    if current_state is None or len(current_state) != BOARD_SIZE:
        return False
    return bytearray(current_state) == startstate

def _is_game_active():
    """
    Check if game is in active state (not ended, not in correction mode).
    Allows moves when board is in starting position (game setup).
    
    Returns:
        bool: True if game is active and can accept moves, or if setting up starting position
    """
    global cboard, correction_mode, gamedbid
    
    # If board is in starting position, allow moves (game setup or reset)
    if _is_board_in_starting_position():
        return True
    
    # Otherwise, check normal game state
    return (cboard.outcome() is None and 
            not correction_mode and
            gamedbid >= 0)

def _safe_callback(callback_func, *args, **kwargs):
    """
    Safely execute a callback function with error handling.
    
    Args:
        callback_func: Callback function to execute
        *args: Positional arguments for callback
        **kwargs: Keyword arguments for callback
    
    Returns:
        bool: True if callback executed successfully, False otherwise
    """
    if callback_func is None:
        return False
    try:
        callback_func(*args, **kwargs)
        return True
    except Exception as e:
        log.error(f"[gamemanager._safe_callback] Callback error: {e}")
        import traceback
        traceback.print_exc()
        return False

def _double_beep():
    """
    Play two beeps with a short delay between them.
    Used for game start/reset notifications.
    """
    board.beep(board.SOUND_GENERAL)
    time.sleep(0.3)
    board.beep(board.SOUND_GENERAL)

def enter_correction_mode():
    """
    Enter correction mode to guide user in fixing board state.
    Pauses and resumes events to reset the event queue.
    """
    global correction_mode, correction_expected_state, forcemove, computermove
    global correction_just_exited
    correction_mode = True
    correction_expected_state = boardstates[-1] if boardstates else None
    correction_just_exited = False  # Clear flag when entering correction mode
    log.warning(f"[gamemanager.enter_correction_mode] Entered correction mode (forcemove={forcemove}, computermove={computermove})")

def exit_correction_mode():
    """
    Exit correction mode and resume normal game flow.
    Restores forced move LEDs if a forced move was pending.
    Resets move state variables to ensure clean state after correction.
    """
    global correction_mode, correction_expected_state, forcemove, computermove
    global sourcesq, legalsquares, othersourcesq, correction_just_exited
    correction_mode = False
    correction_expected_state = None
    correction_just_exited = True  # Set flag to suppress stale events immediately after exit
    log.warning("[gamemanager.exit_correction_mode] Exited correction mode")
    
    # Reset move state variables to ensure clean state after correction
    # The correction process may have left these in an inconsistent state,
    # so reset them so the next move starts fresh
    sourcesq = -1
    legalsquares = []
    othersourcesq = -1
    
    # If there was a forced move pending, restore the LEDs
    if forcemove and computermove and len(computermove) >= MIN_UCI_MOVE_LENGTH:
        fromnum, tonum = _uci_to_squares(computermove)
        if fromnum is not None and tonum is not None:
            board.ledFromTo(fromnum, tonum)
            log.info(f"[gamemanager.exit_correction_mode] Restored forced move LEDs: {computermove}")

def provide_correction_guidance(current_state, expected_state):
    """
    Provide LED guidance to correct misplaced pieces using Hungarian algorithm.
    
    Computes optimal pairing between misplaced pieces using linear_sum_assignment
    for minimal total movement distance, then lights up LEDs to guide the user.
    
    Args:
        current_state: Current board state from getChessState()
        expected_state: Expected board state
    """
    if current_state is None or expected_state is None:
        return
    
    if len(current_state) != BOARD_SIZE or len(expected_state) != BOARD_SIZE:
        return
    
    # Helper functions for distance calculation
    def _rc(idx):
        """Convert square index to (row, col)"""
        return (idx // BOARD_WIDTH), (idx % BOARD_WIDTH)
    
    def _dist(a, b):
        """Manhattan distance between two squares"""
        ar, ac = _rc(a)
        br, bc = _rc(b)
        return abs(ar - br) + abs(ac - bc)
    
    # Compute diffs to find misplaced pieces
    missing_origins = []  # Squares that should have pieces but don't
    wrong_locations = []  # Squares that have pieces but shouldn't
    
    for i in range(BOARD_SIZE):
        if expected_state[i] == 1 and current_state[i] == 0:
            missing_origins.append(i)
        elif expected_state[i] == 0 and current_state[i] == 1:
            wrong_locations.append(i)
    
    if len(missing_origins) == 0 and len(wrong_locations) == 0:
        # Board is correct
        board.ledsOff()
        return
    
    log.warning(f"[gamemanager.provide_correction_guidance] Found {len(wrong_locations)} wrong pieces, {len(missing_origins)} missing pieces")
    
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
        log.warning(f"[gamemanager.provide_correction_guidance] Guiding piece from {chess.square_name(from_idx)} to {chess.square_name(to_idx)}")
    else:
        # Only pieces missing or only extra pieces
        if len(missing_origins) > 0:
            # Light up the squares where pieces should be
            board.ledsOff()
            for idx in missing_origins:
                board.led(idx, intensity=5)
            log.warning(f"[gamemanager.provide_correction_guidance] Pieces missing at: {[chess.square_name(sq) for sq in missing_origins]}")
        elif len(wrong_locations) > 0:
            # Light up the squares where pieces shouldn't be
            board.ledsOff()
            for idx in wrong_locations:
                board.led(idx, intensity=5)
            log.warning(f"[gamemanager.provide_correction_guidance] Extra pieces at: {[chess.square_name(sq) for sq in wrong_locations]}")

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
    log.warning(f"[gamemanager.guideMisplacedPiece] Entering correction mode for field {field}")
    enter_correction_mode()
    current_state = board.getChessState()
    if boardstates and len(boardstates) > 0:
        provide_correction_guidance(current_state, boardstates[-1])

def correction_fieldcallback(piece_event, field, time_in_seconds):
    """
    Wrapper that intercepts field events during correction mode.
    Validates board state and only passes through to normal game flow when correct.
    
    Args:
        piece_event: 0 for lift, 1 for place
        field: Square index (0-63)
        time_in_seconds: Time of the event
    """
    global correction_mode, correction_expected_state, boardstates, cboard
    
    if not correction_mode:
        # Normal flow - pass through to original callback
        return fieldcallback(piece_event, field, time_in_seconds)
    
    # In correction mode: check if board now matches expected after each event
    current_state = board.getChessState()

    # Check if board is in starting position (new game detection)
    if current_state is not None and len(current_state) == BOARD_SIZE:
        if bytearray(current_state) == startstate:
            log.info("[gamemanager.correction_fieldcallback] Starting position detected while in correction mode - exiting correction and triggering new game check")
            board.ledsOff()
            board.beep(board.SOUND_GENERAL)
            exit_correction_mode()
            _reset_game()
            return
     
    log.info(f"[gamemanager.correction_fieldcallback] Current state:")
    board.printChessState(current_state, logging.ERROR)
    log.info(f"[gamemanager.correction_fieldcallback] Correction expected state:")
    board.printChessState(correction_expected_state)
    if validate_board_state(current_state, correction_expected_state):
        # Board is now correct!
        log.info("[gamemanager.correction_fieldcallback] Board corrected, exiting correction mode")
        board.beep(board.SOUND_GENERAL)
        # Don't turn off LEDs here - let exit_correction_mode() restore forced move LEDs if needed
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
    # Receives field events. piece_event: 0 = lift, 1 = place. Numbering 0 = a1, 63 = h8
    # Use this to calculate moves
    global cboard
    global curturn
    global movecallbackfunction
    global sourcesq
    global othersourcesq
    global legalsquares
    global eventcallbackfunction
    global computermove
    global forcemove
    global gamedbid
    global session

    fieldname = chess.square_name(field)
    piece_color = cboard.color_at(field)

    log.info(f"[gamemanager.fieldcallback] piece_event={piece_event} field={field} fieldname={fieldname} color_at={'White' if piece_color else 'Black'} time_in_seconds={time_in_seconds}")

    lift = (piece_event == 0)
    place = (piece_event == 1)
    
    # Check if board is currently in starting position (setup phase)
    # Check on lift to allow setup moves, but also check on place to detect when reset is complete
    is_setting_up = _is_board_in_starting_position()
    
    # Check if piece color matches current turn
    # vpiece = 1 if piece belongs to current player, 0 otherwise
    # During setup, allow any piece to be moved
    vpiece = ((curturn == 0) == (piece_color == False)) or ((curturn == 1) == (piece_color == True))
    if is_setting_up:
        vpiece = 1  # Allow any piece during setup
    
    if lift and field not in legalsquares and sourcesq < 0 and vpiece:
        # During setup, allow piece to be placed anywhere
        if is_setting_up:
            legalsquares = list(range(BOARD_SIZE))  # Allow any square during setup
        else:
            # Generate a list of places this piece can move to
            legalsquares = _calculate_legal_squares(field)
        sourcesq = field
    # Track opposing side lifts so we can guide returning them if moved
    if lift and not vpiece:
        othersourcesq = field
    # If opponent piece is placed back on original square, turn LEDs off and reset
    if place and not vpiece and othersourcesq >= 0 and field == othersourcesq:
        board.ledsOff()
        othersourcesq = -1
    if forcemove and lift and vpiece:
        # If this is a forced move (computer move) then the piece lifted should equal the start of computermove
        # otherwise set legalsquares so they can just put the piece back down! If it is the correct piece then
        # adjust legalsquares so to only include the target square
        if fieldname != computermove[0:2]:
            # Forced move but wrong piece lifted
            legalsquares = [field]
        else:
            # Forced move, correct piece lifted, limit legal squares
            target = computermove[2:4]
            tsq = chess.parse_square(target)
            legalsquares = [tsq]
    # Ignore PLACE events without a corresponding LIFT (stale events from before reset)
    # This prevents triggering correction mode when a PLACE event arrives after reset
    # but before the piece is lifted again in the new game state
    # Allow opponent piece placement back (othersourcesq >= 0) and forced moves
    global correction_just_exited
    if place and sourcesq < 0 and othersourcesq < 0:
        # After correction mode exits, there may be stale PLACE events from the correction process
        # Ignore them unless it's a forced move source square (which we handle separately)
        if correction_just_exited:
            # Check if this is the forced move source square - if so, we'll handle it below
            # Otherwise, ignore it as a stale event from correction
            if forcemove and computermove and len(computermove) >= MIN_UCI_MOVE_LENGTH:
                forced_source = chess.parse_square(computermove[0:2])
                if field != forced_source:
                    log.info(f"[gamemanager.fieldcallback] Ignoring stale PLACE event after correction exit for field {field} (not forced move source)")
                    correction_just_exited = False  # Clear flag after ignoring first stale event
                    return
            else:
                log.info(f"[gamemanager.fieldcallback] Ignoring stale PLACE event after correction exit for field {field}")
                correction_just_exited = False  # Clear flag after ignoring first stale event
                return
        
        # For forced moves, also ignore stale PLACE events on the source square
        # (the forced move source square) before the LIFT has been processed
        if forcemove == 1 and computermove and len(computermove) >= MIN_UCI_MOVE_LENGTH:
            forced_source = chess.parse_square(computermove[0:2])
            if field == forced_source:
                log.info(f"[gamemanager.fieldcallback] Ignoring stale PLACE event for forced move source field {field} (no corresponding LIFT)")
                correction_just_exited = False  # Clear flag
                return
        if not forcemove:
            log.info(f"[gamemanager.fieldcallback] Ignoring stale PLACE event for field {field} (no corresponding LIFT)")
            correction_just_exited = False  # Clear flag
            return
    
    # Clear the flag once we process a valid event (LIFT)
    if lift:
        correction_just_exited = False
    
    if place and field not in legalsquares:
        # During setup, allow any placement - don't trigger warnings
        if is_setting_up:
            # Just reset move state and allow placement
            sourcesq = -1
            legalsquares = []
            return
        
        board.beep(board.SOUND_WRONG_MOVE)
        log.warning(f"[gamemanager.fieldcallback] Piece placed on illegal square {field}")
        is_takeback = checkLastBoardState()
        if not is_takeback:
            guideMisplacedPiece(field, sourcesq, othersourcesq, vpiece)
    
    # Check for starting position detection on ANY placement (not just legal squares)
    # This allows detection even when pieces are being reset manually
    if place:
        if _is_board_in_starting_position():
            log.info("[gamemanager.fieldcallback] Starting position detected after piece placement")
            board.ledsOff()
            _reset_move_state()
            # If a game was in progress, reset it; otherwise prepare for new game
            with _game_lock:
                if gamedbid >= 0:
                    log.info("[gamemanager.fieldcallback] Resetting active game for new game")
                _reset_game()
            return
    
    if place and field in legalsquares:
        
        # Check if game is still active before processing move
        # After reset, allow first move even if gamedbid isn't fully set yet
        # Check if this is likely the first move after reset (cboard is at starting position)
        is_first_move_after_reset = (cboard.fen() == STARTING_FEN and 
                                     len(cboard.move_stack) == 0 and
                                     cboard.outcome() is None)
        
        if not _is_game_active() and not is_first_move_after_reset:
            log.warning(f"[gamemanager.fieldcallback] Attempted move after game ended or in correction mode")
            board.beep(board.SOUND_WRONG_MOVE)
            return
        
        log.info(f"[gamemanager.fieldcallback] Making move")
        if field == sourcesq:
            # Piece has simply been placed back
            board.ledsOff()
            sourcesq = -1
            legalsquares = []
        else:
            # Piece has been moved - prepare move string first
            fromname = chess.square_name(sourcesq)
            toname = chess.square_name(field)
            mv = None  # Initialize move variable
            
            # Use lock for critical section
            with _game_lock:
                # Double-check game is still active after acquiring lock
                if not _is_game_active():
                    log.warning(f"[gamemanager.fieldcallback] Game ended while processing move")
                    return
                
                piece_name = str(cboard.piece_at(sourcesq))
                promotion_suffix = _handle_promotion(field, piece_name, forcemove)
                
                if forcemove:
                    mv = computermove
                else:
                    mv = fromname + toname + promotion_suffix
                
                # Validate and execute move with error handling
                try:
                    cboard.push(chess.Move.from_uci(mv))
                except ValueError as e:
                    log.error(f"[gamemanager.fieldcallback] Invalid move {mv}: {e}")
                    board.beep(board.SOUND_WRONG_MOVE)
                    return
                except Exception as e:
                    log.error(f"[gamemanager.fieldcallback] Unexpected error executing move {mv}: {e}")
                    import traceback
                    traceback.print_exc()
                    board.beep(board.SOUND_WRONG_MOVE)
                    return
                
                # Update fen.log
                paths.write_fen_log(cboard.fen())
                
                # Database operations in transaction
                try:
                    # Ensure gamedbid is set (should be set by _reset_game, but check for safety)
                    if gamedbid < 0:
                        log.error("[gamemanager.fieldcallback] gamedbid not set, cannot record move")
                        # Try to get the latest game ID
                        gamedbid = session.query(func.max(models.Game.id)).scalar()
                        if gamedbid is None or gamedbid < 0:
                            log.error("[gamemanager.fieldcallback] No game found in database")
                            cboard.pop()  # Rollback move
                            board.beep(board.SOUND_WRONG_MOVE)
                            return
                    
                    # Record the move in database
                    move_fen = str(cboard.fen())
                    gamemove = models.GameMove(
                        gameid=gamedbid,
                        move=mv,
                        fen=move_fen
                    )
                    session.add(gamemove)
                    session.commit()
                    log.info(f"[gamemanager.fieldcallback] Recorded move {mv} in database with FEN: {move_fen}")
                    
                    # Record board state after move
                    current_state = board.getChessState()
                    if current_state is not None:
                        boardstates.append(current_state)
                        log.info(f"[gamemanager.fieldcallback] Recorded board state after move {mv}")
                    else:
                        log.warning("[gamemanager.fieldcallback] Could not get board state after move")
                except Exception as e:
                    log.error(f"[gamemanager.fieldcallback] Database error: {e}")
                    session.rollback()
                    # Rollback the move on the board as well
                    try:
                        cboard.pop()
                    except:
                        pass
                    board.beep(board.SOUND_WRONG_MOVE)
                    return
                
                _reset_move_state()
                board.beep(board.SOUND_GENERAL)
                # Also light up the square moved to
                board.led(field)
                
                # Check the outcome
                outcome = cboard.outcome(claim_draw=True)
                if outcome is None:
                    # Switch the turn and trigger event callback
                    # This is critical for computer moves - external code listens for EVENT_BLACK_TURN/EVENT_WHITE_TURN
                    _switch_turn_with_event()
                    log.info(f"[gamemanager.fieldcallback] Turn switched, current turn: {curturn} ({'White' if curturn == 1 else 'Black'})")
                else:
                    board.beep(board.SOUND_GENERAL)
                    # Update game result in database and trigger callback
                    resultstr = str(cboard.result())
                    termination = str(outcome.termination)
                    _update_game_result(resultstr, termination, "fieldcallback")
            
            # Call move callback OUTSIDE the lock to avoid deadlock
            # Move callback may call gamemanager functions (like getBoard(), getFEN()) which could try to acquire the same lock
            if mv is not None:
                _safe_callback(movecallbackfunction, mv)

def resignGame(sideresigning):
    # Take care of updating the data for a resigned game and callback to the program with the
    # winner. sideresigning = 1 for white, 2 for black
    # Input validation
    if sideresigning not in [1, 2]:
        log.warning(f"[gamemanager.resignGame] Invalid sideresigning value: {sideresigning}")
        return
    
    # Check if game is still active
    if not _is_game_active():
        log.warning(f"[gamemanager.resignGame] Cannot resign - game not active")
        return
    
    resultstr = "0-1" if sideresigning == 1 else "1-0"
    _update_game_result(resultstr, "Termination.RESIGN", "resignGame")
    
def getResult():
    # Looks up the result of the last game and returns it
    gamedata = session.execute(
        select(models.Game.created_at, models.Game.source, models.Game.event, models.Game.site, models.Game.round,
        models.Game.white, models.Game.black, models.Game.result, models.Game.id).
        order_by(models.Game.id.desc())
    ).first()
    if gamedata is not None:
        return str(gamedata.result)
    else:
        return "Unknown"

def drawGame():
    # Take care of updating the data for a drawn game
    # Check if game is still active
    if not _is_game_active():
        log.warning(f"[gamemanager.drawGame] Cannot draw - game not active")
        return
    
    _update_game_result("1/2-1/2", "Termination.DRAW", "drawGame")

def gameThread(eventCallback, moveCallback, keycallbacki, takebackcallbacki):
    # The main thread handles the actual chess game functionality and calls back to
    # eventCallback with game events and
    # moveCallback with the actual moves made
    global kill
    global keycallbackfunction
    global movecallbackfunction
    global eventcallbackfunction
    global takebackcallbackfunction
    keycallbackfunction = keycallbacki
    movecallbackfunction = moveCallback
    eventcallbackfunction = eventCallback
    takebackcallbackfunction = takebackcallbacki
    board.ledsOff()
    log.info(f"[gamemanager.gameThread] Subscribing to events")
    log.info(f"[gamemanager.gameThread] Keycallback: {keycallback}")
    log.info(f"[gamemanager.gameThread] Fieldcallback: correction_fieldcallback (wraps fieldcallback)")
    try:
        board.subscribeEvents(keycallback, correction_fieldcallback)
    except Exception as e:
        log.error(f"[gamemanager.gameThread] error: {e}")
        log.error(f"[gamemanager.gameThread] error: {sys.exc_info()[1]}")
        return
    while kill == 0:
        time.sleep(0.1)

def _reset_game():
    try:
        global boardstates
        global curturn
        global cboard
        global paths
        global source
        global gameinfo_event
        global gameinfo_site
        global gameinfo_round
        global gameinfo_white
        global gameinfo_black
        global sourcesq
        global legalsquares
        global othersourcesq
        global forcemove
        global computermove
        global correction_mode
        global correction_just_exited
        global correction_expected_state
        global gamedbid
        
        log.info("DEBUG: Detected starting position - triggering NEW_GAME")
        # Exit correction mode if active
        if correction_mode:
            correction_mode = False
            correction_expected_state = None
            correction_just_exited = False
            log.info("[gamemanager._reset_game] Exiting correction mode for game reset")
        
        # Reset move-related state variables to prevent stale values from previous game/correction
        resetMoveState()
        curturn = 1
        cboard.reset()
        
        # Clear boardstates and record starting position state
        boardstates = []
        
        # Verify board is in starting position before recording
        current_board_state = board.getChessState()
        if current_board_state is not None and bytearray(current_board_state) == startstate:
            boardstates.append(current_board_state)
            log.info("[gamemanager._reset_game] Recorded starting position in boardstates")
        else:
            log.warning("[gamemanager._reset_game] Board state doesn't match starting position, recording anyway")
            if current_board_state is not None:
                boardstates.append(current_board_state)
        
        paths.write_fen_log(cboard.fen())
        _double_beep()
        board.ledsOff()
        _safe_callback(eventcallbackfunction, EVENT_NEW_GAME)
        _safe_callback(eventcallbackfunction, EVENT_WHITE_TURN)
        
        # Log a new game in the db
        game = models.Game(
            source=source,
            event=gameinfo_event,
            site=gameinfo_site,
            round=gameinfo_round,
            white=gameinfo_white,
            black=gameinfo_black
        )
        log.info(f"[gamemanager._reset_game] Creating new game: {game}")
        session.add(game)
        session.commit()                        
        # Get the max game id as that is this game id and fill it into gamedbid
        gamedbid = session.query(func.max(models.Game.id)).scalar()
        log.info(f"[gamemanager._reset_game] New game ID: {gamedbid}")
        
        # Record the starting position in GameMove with STARTING_FEN
        gamemove = models.GameMove(
            gameid = gamedbid,
            move = '',
            fen = STARTING_FEN  # Use constant to ensure consistency
        )
        session.add(gamemove)
        session.commit()
        log.info(f"[gamemanager._reset_game] Recorded starting position in database: {STARTING_FEN}")
    except Exception as e:
        log.error(f"Error resetting game: {e}")
        import traceback
        traceback.print_exc()
        pass

def clockThread():
    # This thread just decrements the clock and updates the epaper
    global whitetime
    global blacktime
    global curturn
    global kill
    global cboard
    global showingpromotion
    while kill == 0:
        time.sleep(CLOCK_DECREMENT_SECONDS)  # epaper refresh rate means we can only have an accuracy of around 2 seconds
        
        # Check if game is over - stop clock if so
        with _game_lock:
            outcome = cboard.outcome()
            if outcome is not None:
                # Game is over, stop clock but continue updating display
                if not showingpromotion:
                    timestr = _format_time(whitetime, blacktime)
                    epaper.writeText(CLOCK_DISPLAY_LINE, timestr)
                continue
        
        # Only decrement clock if game is active
        with _game_lock:
            if whitetime > 0 and curturn == 1 and cboard.fen() != STARTING_FEN:
                whitetime = whitetime - CLOCK_DECREMENT_SECONDS
            if blacktime > 0 and curturn == 0:
                blacktime = blacktime - CLOCK_DECREMENT_SECONDS
        
        if not showingpromotion:
            timestr = _format_time(whitetime, blacktime)
            epaper.writeText(CLOCK_DISPLAY_LINE, timestr)

whitetime = 0
blacktime = 0
def setClock(white,black):
    # Set the clock
    global whitetime
    global blacktime
    whitetime = white
    blacktime = black

def startClock():
    # Start the clock. It writes to CLOCK_DISPLAY_LINE
    timestr = _format_time(whitetime, blacktime)
    epaper.writeText(CLOCK_DISPLAY_LINE, timestr)
    clockthread = threading.Thread(target=clockThread, args=())
    clockthread.daemon = True
    clockthread.start()

def computerMove(mv, forced = True):
    # Set the computer move that the player is expected to make
    # in the format b2b4 , g7g8q , etc
    global computermove
    global forcemove
    
    # Input validation
    if not mv or len(mv) < MIN_UCI_MOVE_LENGTH:
        log.warning(f"[gamemanager.computerMove] Invalid move format: {mv}")
        return
    
    # Validate UCI format (basic check)
    if not (mv[0].islower() and mv[1].isdigit() and mv[2].islower() and mv[3].isdigit()):
        log.warning(f"[gamemanager.computerMove] Invalid UCI move format: {mv}")
        return
    
    # Check if game is active
    if not _is_game_active():
        log.warning(f"[gamemanager.computerMove] Cannot set forced move - game not active")
        return
    
    with _game_lock:
        # Check if a move is already in progress
        if sourcesq >= 0:
            log.warning(f"[gamemanager.computerMove] Move already in progress, cannot set forced move")
            return
        
        # First set the globals so that the thread knows there is a computer move
        computermove = mv
        if forced:
            forcemove = 1
        # Next indicate this on the board by converting UCI to square indices and lighting LEDs
        fromnum, tonum = _uci_to_squares(mv)
        if fromnum is not None and tonum is not None:
            board.ledFromTo(fromnum, tonum)  

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

def getBoard():
    """Get the current chess board state."""
    global cboard
    with _game_lock:
        return cboard

def getFEN():
    """Get current board position as FEN string."""
    global cboard
    with _game_lock:
        return cboard.fen()

def resetMoveState():
    """Reset all move-related state variables (forcemove, computermove, sourcesq, legalsquares)."""
    global forcemove, computermove, sourcesq, legalsquares, othersourcesq
    forcemove = 0
    computermove = ""
    sourcesq = -1
    legalsquares = []
    othersourcesq = -1

def resetBoard():
    """Reset the chess board to starting position."""
    global cboard
    cboard.reset()

def setBoard(board):
    """Set the chess board state (primarily for testing)."""
    global cboard
    cboard = board

def subscribeGame(eventCallback, moveCallback, keyCallback, takebackCallback = None):
    # Subscribe to the game manager
    global source
    global gamedbid
    global session
    global boardstates
    
    boardstates = []
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
    global session
    board.ledsOff()
    kill = 1
    # Clean up database session
    if session is not None:
        try:
            session.close()
            session = None
        except Exception:
            session = None
