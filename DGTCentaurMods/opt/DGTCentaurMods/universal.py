#!/usr/bin/env python3
# Universal Bluetooth Relay
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

"""
Universal Bluetooth Relay with BLE and RFCOMM Support

This relay connects to a target device via Bluetooth Classic SPP (RFCOMM)
and relays data between that device and a client connected to this relay.
Also provides BLE service matching millennium.py for host connections.

BLE Implementation:
- Uses direct D-Bus/BlueZ GATT implementation (no thirdparty dependencies)
- Matches the working millennium_sniffer.py implementation
- Supports BLE without pairing (like real Millennium board)
- Supports RFCOMM with pairing (Serial Port Profile)

Usage:
    python3 universal.py
"""

import argparse
import sys
import os
import time
import threading
import signal
import random
import psutil
from enum import Enum, auto
from typing import Optional, List

# Initialize display FIRST, before board module is imported
# This allows showing a splash screen while the board initializes
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.epaper import Manager, SplashScreen, IconMenuWidget, IconMenuEntry, KeyboardWidget
from DGTCentaurMods.epaper.status_bar import STATUS_BAR_HEIGHT

# Load resources BEFORE any widgets are created
# This must happen synchronously at import time
def _initialize_resources():
    """Load resources and inject into widget modules.
    
    Must be called before any widgets are created, as widgets
    rely on module-level resources being set.
    """
    try:
        from DGTCentaurMods.resources import ResourceLoader
        from DGTCentaurMods.epaper import text as text_module
        from DGTCentaurMods.epaper import chess_board as chess_board_module
        from DGTCentaurMods.epaper import splash_screen as splash_screen_module
        from DGTCentaurMods.epaper import icon_button as icon_button_module
        from DGTCentaurMods.epaper import keyboard as keyboard_module
        
        # Create resource loader
        loader = ResourceLoader("/opt/DGTCentaurMods/resources", "/home/pi/resources")
        
        # Set resource loader on modules that need fonts
        text_module.set_resource_loader(loader)
        keyboard_module.set_resource_loader(loader)
        
        # Load and set chess sprites
        sprites = loader.get_chess_sprites()
        if sprites:
            chess_board_module.set_chess_sprites(sprites)
        
        # Load and set knight logos at common sizes
        for size in [100, 80, 36, 24, 20]:  # Splash screen (100), menu buttons (80), icon buttons
            logo, mask = loader.get_knight_logo(size)
            if logo and mask:
                icon_button_module.set_knight_logo(size, logo, mask)
                if size == 100:
                    splash_screen_module.set_knight_logo(logo, mask)
        
        log.info("[Startup] Resources loaded and injected into widget modules")
    except Exception as e:
        log.error(f"[Startup] Failed to initialize resources: {e}", exc_info=True)

# Initialize resources synchronously before any widgets are created
_initialize_resources()

# Initialize display immediately
_early_display_manager: Optional[Manager] = None
_startup_splash: Optional[SplashScreen] = None

def _wait_for_display_promise(promise, operation_name: str, timeout: float = 10.0):
    """Wait for a display promise in the background and log any errors.
    
    This allows the main thread to continue while display operations complete.
    Errors are logged but don't block startup.
    
    Args:
        promise: The Future to wait on
        operation_name: Description of the operation for logging
        timeout: Maximum time to wait in seconds
    """
    import threading
    def _wait():
        try:
            if promise:
                result = promise.result(timeout=timeout)
                log.debug(f"[Display] {operation_name} completed: {result}")
        except Exception as e:
            log.warning(f"[Display] {operation_name} failed: {e}")
    
    thread = threading.Thread(target=_wait, daemon=True)
    thread.start()

def _on_display_refresh(image):
    """Callback for display refreshes - writes image to web static folder.
    
    Used by the web dashboard to mirror the e-paper display.
    Deferred import to avoid loading AssetManager at startup.
    """
    try:
        from DGTCentaurMods.managers import AssetManager
        AssetManager.write_epaper_static_jpg(image)
    except Exception as e:
        log.debug(f"Failed to write epaper.jpg: {e}")

def _init_display_early():
    """Initialize display and show splash screen before board initialization.
    
    Display operations are queued and monitored in background threads,
    allowing the main thread to continue with other startup tasks while
    the e-paper display catches up (the initial Clear() takes ~3 seconds).
    """
    global _early_display_manager, _startup_splash
    try:
        _early_display_manager = Manager(on_refresh=_on_display_refresh)
        promise = _early_display_manager.initialize()
        # Don't block - monitor in background thread
        _wait_for_display_promise(promise, "initialize", timeout=10.0)
        
        # Show splash screen immediately (full screen, no status bar)
        _early_display_manager.clear_widgets(addStatusBar=False)
        _startup_splash = SplashScreen(message="Starting...", leave_room_for_status_bar=False)
        promise = _early_display_manager.add_widget(_startup_splash)
        # Don't block - monitor in background thread
        _wait_for_display_promise(promise, "add_splash", timeout=10.0)
    except Exception as e:
        log.warning(f"Early display initialization failed: {e}")

# Initialize display before importing board
_init_display_early()

# Set up board init status callback before importing board module
# This allows the splash screen to update during board initialization retries
def _board_init_status_callback(message: str):
    """Callback for board initialization status updates."""
    if _startup_splash:
        _startup_splash.set_message(message)

# Set the callback in the init_callback module BEFORE importing board
# This module is imported by board.py and doesn't trigger board initialization
from DGTCentaurMods.board import init_callback
init_callback.set_callback(_board_init_status_callback)

# Now import board module - this triggers SyncCentaur initialization and waits for ready
from DGTCentaurMods.board import board

# Transfer the early display manager to board module so it's available globally
if _early_display_manager is not None:
    board.display_manager = _early_display_manager

# Board is now ready - update splash
if _startup_splash:
    _startup_splash.set_message("Loading...")

# Continue with remaining imports
import time as _import_time
_import_start = _import_time.time()

if _startup_splash:
    _startup_splash.set_message("Bluetooth...")
import bluetooth
log.debug(f"[Import timing] bluetooth: {(_import_time.time() - _import_start)*1000:.0f}ms"); _import_start = _import_time.time()

if _startup_splash:
    _startup_splash.set_message("GLib...")
from gi.repository import GLib
log.debug(f"[Import timing] GLib: {(_import_time.time() - _import_start)*1000:.0f}ms"); _import_start = _import_time.time()

if _startup_splash:
    _startup_splash.set_message("Chess...")
import chess
log.debug(f"[Import timing] chess: {(_import_time.time() - _import_start)*1000:.0f}ms"); _import_start = _import_time.time()

import chess.engine
log.debug(f"[Import timing] chess.engine: {(_import_time.time() - _import_start)*1000:.0f}ms"); _import_start = _import_time.time()

import pathlib
log.debug(f"[Import timing] pathlib: {(_import_time.time() - _import_start)*1000:.0f}ms"); _import_start = _import_time.time()

if _startup_splash:
    _startup_splash.set_message("Graphics...")
from PIL import Image, ImageDraw, ImageFont
log.debug(f"[Import timing] PIL: {(_import_time.time() - _import_start)*1000:.0f}ms"); _import_start = _import_time.time()

if _startup_splash:
    _startup_splash.set_message("Managers...")
from DGTCentaurMods.managers import (
    RfcommManager,
    BleManager,
    RelayManager,
    ProtocolManager,
    DisplayManager,
    MenuManager,
    MenuSelection,
    is_break_result,
    find_entry_index,
    ConnectionManager,
)
log.debug(f"[Import timing] managers: {(_import_time.time() - _import_start)*1000:.0f}ms")

# All imports complete
if _startup_splash:
    _startup_splash.set_message("Initializing...")

# App States
class AppState(Enum):
    MENU = auto()      # Showing main menu
    GAME = auto()      # In game/chess mode
    SETTINGS = auto()  # In settings submenu


# Display dimensions
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 296

# Path to original DGT Centaur software
CENTAUR_SOFTWARE = "/home/pi/centaur/centaur"


# Global state
running = True
kill = 0
client_connected = False
app_state = AppState.MENU  # Current application state
protocol_manager = None  # ProtocolManager instance
display_manager = None  # DisplayManager for game UI widgets
_last_message = None  # Last message sent via sendMessage
relay_mode = False  # Whether relay mode is enabled (connects to relay target)
mainloop = None  # GLib mainloop for BLE
rfcomm_manager = None  # RfcommManager for RFCOMM pairing
ble_manager = None  # BleManager for BLE GATT services
relay_manager = None  # RelayManager for shadow target connections
_connection_manager: Optional[ConnectionManager] = None  # Initialized in main()

# Menu state - managed by MenuManager singleton
_menu_manager: Optional[MenuManager] = None  # Initialized in main()
_return_to_positions_menu = False  # Flag to signal return to positions menu from game
_is_position_game = False  # Flag to track if current game is a position (practice) game
_switch_to_normal_game = False  # Flag to signal switch from position game to normal game
_pending_ble_client_type: str = None  # Flag for BLE connection when between menus
_last_position_category_index = 0  # Remember last selected category in positions menu
_last_position_index = 0  # Remember last selected position in positions menu
_last_position_category = None  # Remember last selected category name for direct return

# Keyboard state (for WiFi password entry etc.)
_active_keyboard_widget = None

# Socket references
server_sock = None
client_sock = None

# Args (stored globally after parsing for access in callbacks)
_args = None

# Game settings (user-configurable via settings menu)
# These are loaded from centaur.ini on startup and saved when changed
_game_settings = {
    'engine': 'stockfish_pi',  # Default engine
    'elo': 'Default',          # Default ELO level
    'player_color': 'white',   # white, black, or random
    'time_control': 0,         # Time per player in minutes (0 = disabled/untimed)
    # System settings (cannot be changed during a game)
    'analysis_mode': True,     # Enable analysis engine (creates analysis widget even if hidden)
    # Display settings (widgets to show during game)
    'show_board': True,        # Show chess board widget
    'show_clock': True,        # Show clock/turn indicator widget
    'show_analysis': True,     # Show analysis widget (score bar + graph)
    'show_graph': True,        # Show history graph in analysis widget
}

# Available time control options (in minutes)
TIME_CONTROL_OPTIONS = [0, 1, 3, 5, 10, 15, 30, 60, 90]

# Settings section name in centaur.ini
SETTINGS_SECTION = 'game'

# Cached engine data
_available_engines: List[str] = []
_engine_elo_levels: dict = {}  # engine_name -> list of ELO levels


# ============================================================================
# Settings Persistence
# ============================================================================

def _load_game_settings():
    """Load game settings from centaur.ini.
    
    Reads engine, elo, and player_color from the [game] section.
    Uses defaults if not present.
    """
    global _game_settings
    
    try:
        from DGTCentaurMods.board.settings import Settings
        
        _game_settings['engine'] = Settings.read(SETTINGS_SECTION, 'engine', 'stockfish_pi')
        _game_settings['elo'] = Settings.read(SETTINGS_SECTION, 'elo', 'Default')
        _game_settings['player_color'] = Settings.read(SETTINGS_SECTION, 'player_color', 'white')
        time_control_str = Settings.read(SETTINGS_SECTION, 'time_control', '0')
        try:
            _game_settings['time_control'] = int(time_control_str)
        except ValueError:
            _game_settings['time_control'] = 0
        
        # Load display settings (booleans stored as 'true'/'false' strings)
        # Default to 'true' if not present or if value is empty/invalid
        def load_bool_setting(key: str) -> bool:
            value = Settings.read(SETTINGS_SECTION, key, 'true')
            # Treat empty string, 'false', or '0' as False; everything else as True
            if value.lower() in ('false', '0', ''):
                return False
            return True
        
        # Load system settings (analysis mode)
        _game_settings['analysis_mode'] = load_bool_setting('analysis_mode')
        
        _game_settings['show_board'] = load_bool_setting('show_board')
        _game_settings['show_clock'] = load_bool_setting('show_clock')
        _game_settings['show_analysis'] = load_bool_setting('show_analysis')
        _game_settings['show_graph'] = load_bool_setting('show_graph')

        log.info(f"[Settings] Loaded: engine={_game_settings['engine']}, "
                 f"elo={_game_settings['elo']}, color={_game_settings['player_color']}, "
                 f"time_control={_game_settings['time_control']} min, "
                 f"analysis_mode={_game_settings['analysis_mode']}")
        log.info(f"[Settings] Display: board={_game_settings['show_board']}, "
                 f"clock={_game_settings['show_clock']}, analysis={_game_settings['show_analysis']}, "
                 f"graph={_game_settings['show_graph']}")
    except Exception as e:
        log.warning(f"[Settings] Error loading game settings: {e}, using defaults")


def _save_game_setting(key: str, value):
    """Save a single game setting to centaur.ini.
    
    Args:
        key: Setting key (engine, elo, player_color, show_board, etc.)
        value: Setting value (string or boolean - booleans stored as 'true'/'false')
    """
    try:
        from DGTCentaurMods.board.settings import Settings
        
        # Convert to string for storage
        if isinstance(value, bool):
            str_value = 'true' if value else 'false'
        else:
            str_value = str(value)
        
        Settings.write(SETTINGS_SECTION, key, str_value)
        log.debug(f"[Settings] Saved {key}={str_value}")
    except Exception as e:
        log.warning(f"[Settings] Error saving {key}={value}: {e}")


# ============================================================================
# Game Resume Functions
# ============================================================================

def _get_incomplete_game() -> Optional[dict]:
    """Check if there's an incomplete game that can be resumed.
    
    An incomplete game is one where result is NULL (not completed, not abandoned).
    Games marked with '*' are explicitly abandoned and should not be resumed.
    
    Returns:
        Dictionary with game data if found, None otherwise.
        Dict contains: id, source, fen (last position), moves (list of move strings),
                      white_clock, black_clock (seconds remaining, or None if not stored)
    """
    try:
        from sqlalchemy.orm import sessionmaker
        from DGTCentaurMods.db import models
        
        Session = sessionmaker(bind=models.engine)
        session = Session()
        
        try:
            # Get the most recent game with NULL result (incomplete, not abandoned)
            game = session.query(models.Game).filter(
                models.Game.result == None  # NULL means in progress
            ).order_by(models.Game.id.desc()).first()
            
            if game is None:
                log.debug("[Resume] No incomplete games found")
                return None
            
            # Get all moves for this game
            moves = session.query(models.GameMove).filter(
                models.GameMove.gameid == game.id
            ).order_by(models.GameMove.id.asc()).all()
            
            if not moves:
                log.debug(f"[Resume] Game {game.id} has no moves, cannot resume")
                return None
            
            # Get the last FEN position and clock times
            last_move = moves[-1]
            last_fen = last_move.fen
            
            # Get clock times from the last move (may be None for older games)
            white_clock = getattr(last_move, 'white_clock', None)
            black_clock = getattr(last_move, 'black_clock', None)

            # Extract move list (skip empty starting move if present)
            move_list = [m.move for m in moves if m.move]
            
            # Extract eval scores for analysis history (skip moves without eval)
            eval_scores = [getattr(m, 'eval_score', None) for m in moves if m.move and getattr(m, 'eval_score', None) is not None]
            
            # Only resume if there are actual moves played (not just starting position)
            if not move_list:
                log.debug(f"[Resume] Game {game.id} has no actual moves (only starting position), not resuming")
                return None
            
            log.info(f"[Resume] Found incomplete game: id={game.id}, source={game.source}, "
                    f"moves={len(move_list)}, last_fen={last_fen[:30]}...")
            if white_clock is not None and black_clock is not None:
                log.info(f"[Resume] Clock times: white={white_clock}s, black={black_clock}s")
            if eval_scores:
                log.info(f"[Resume] Eval scores: {len(eval_scores)} positions")
            
            return {
                'id': game.id,
                'source': game.source,
                'fen': last_fen,
                'moves': move_list,
                'white': game.white,
                'black': game.black,
                'white_clock': white_clock,
                'black_clock': black_clock,
                'eval_scores': eval_scores
            }
        finally:
            session.close()
            
    except Exception as e:
        log.error(f"[Resume] Error checking for incomplete game: {e}")
        return None


def _resume_game(game_data: dict) -> bool:
    """Resume an incomplete game.
    
    Sets up the GameManager with the saved game state and starts game mode.
    Checks if physical board matches the resumed position and enters correction
    mode if not. If it's the engine's turn, triggers the engine to move.
    
    Args:
        game_data: Dictionary from _get_incomplete_game()
        
    Returns:
        True if game was successfully resumed, False otherwise
    """
    global protocol_manager, app_state
    
    try:
        import chess
        from DGTCentaurMods.managers import EVENT_WHITE_TURN, EVENT_BLACK_TURN
        
        log.info(f"[Resume] Resuming game {game_data['id']}...")
        
        # Start game mode with the resume position FEN so display shows correct position immediately
        _start_game_mode(starting_fen=game_data['fen'])
        
        if protocol_manager is None or protocol_manager.game_manager is None:
            log.error("[Resume] Failed to start game mode")
            return False
        
        gm = protocol_manager.game_manager
        
        # Set the database game ID so updates go to the right record
        gm.game_db_id = game_data['id']
        
        # Replay all the moves to get to the current position
        for move_uci in game_data['moves']:
            try:
                move = chess.Move.from_uci(move_uci)
                if move in gm.chess_board.legal_moves:
                    gm.chess_board.push(move)
                else:
                    log.warning(f"[Resume] Illegal move in history: {move_uci}")
            except Exception as move_error:
                log.warning(f"[Resume] Error replaying move {move_uci}: {move_error}")
        
        # Verify we reached the expected position
        current_fen = gm.chess_board.fen()
        if current_fen != game_data['fen']:
            log.warning(f"[Resume] FEN mismatch after replay. Expected: {game_data['fen']}, Got: {current_fen}")
        
        log.info(f"[Resume] Game resumed successfully at position: {current_fen[:50]}...")
        
        # Update the display to show the current position
        if protocol_manager:
            protocol_manager._update_display()
        
        # Restore clock times if available
        white_clock = game_data.get('white_clock')
        black_clock = game_data.get('black_clock')
        if white_clock is not None and black_clock is not None and display_manager:
            display_manager.set_clock_times(white_clock, black_clock)
            log.info(f"[Resume] Clock times restored: white={white_clock}s, black={black_clock}s")
        
        # Restore eval score history if available
        eval_scores = game_data.get('eval_scores', [])
        if eval_scores and display_manager:
            display_manager.set_score_history(eval_scores)
            log.info(f"[Resume] Eval scores restored: {len(eval_scores)} positions")
        
        # Check if physical board matches the resumed position
        current_physical_state = board.getChessState()
        expected_logical_state = gm._chess_board_to_state(gm.chess_board)
        
        if current_physical_state is not None and expected_logical_state is not None:
            if not gm._validate_board_state(current_physical_state, expected_logical_state):
                log.warning("[Resume] Physical board does not match resumed position, entering correction mode")
                gm._enter_correction_mode()
                gm._provide_correction_guidance(current_physical_state, expected_logical_state)
            else:
                log.info("[Resume] Physical board matches resumed position")
                # Board is correct - trigger turn event to prompt engine if it's engine's turn
                if gm.event_callback is not None:
                    if gm.chess_board.turn == chess.WHITE:
                        log.info("[Resume] Triggering WHITE turn event")
                        gm.event_callback(EVENT_WHITE_TURN)
                    else:
                        log.info("[Resume] Triggering BLACK turn event")
                        gm.event_callback(EVENT_BLACK_TURN)
        else:
            log.warning("[Resume] Could not validate physical board state")
        
        return True
        
    except Exception as e:
        log.error(f"[Resume] Error resuming game: {e}")
        return False


# ============================================================================
# Position Loading Functions
# ============================================================================

def _parse_position_entry(value: str) -> tuple:
    """Parse a position entry from positions.ini.
    
    Format: FEN | hint_move (hint_move is optional)
    
    Args:
        value: Raw value from INI file
        
    Returns:
        Tuple of (fen, hint_move) where hint_move may be None
    """
    if '|' in value:
        parts = value.split('|', 1)
        fen = parts[0].strip()
        hint_move = parts[1].strip() if len(parts) > 1 else None
        # Validate hint_move format (UCI: 4-5 chars like e2e4 or a7a8q)
        if hint_move and (len(hint_move) < 4 or len(hint_move) > 5):
            log.warning(f"[Positions] Invalid hint move format: {hint_move}")
            hint_move = None
        return (fen, hint_move)
    else:
        return (value.strip(), None)


def _load_positions_config() -> dict:
    """Load predefined positions from positions.ini.
    
    Returns:
        Dictionary with category names as keys and dict of {name: (fen, hint_move)} as values.
        hint_move is None if not specified.
        Example: {'test': {'en_passant': ('fen...', 'e5d6')}, 'puzzles': {...}}
    """
    import configparser
    
    positions = {}
    
    # Try runtime path first, then development path
    config_paths = [
        pathlib.Path("/opt/DGTCentaurMods/config/positions.ini"),
        pathlib.Path(__file__).parent / "defaults" / "config" / "positions.ini"
    ]
    
    config_file = None
    for path in config_paths:
        if path.exists():
            config_file = path
            break
    
    if config_file is None:
        log.warning("[Positions] positions.ini not found")
        return positions
    
    try:
        config = configparser.ConfigParser()
        config.read(str(config_file))
        
        for section in config.sections():
            positions[section] = {}
            for name, value in config.items(section):
                fen, hint_move = _parse_position_entry(value)
                # Validate FEN has 6 fields
                if len(fen.split()) == 6:
                    positions[section][name] = (fen, hint_move)
                else:
                    log.warning(f"[Positions] Invalid FEN for {section}/{name}: {fen}")
        
        log.info(f"[Positions] Loaded {sum(len(v) for v in positions.values())} positions from {len(positions)} categories")
        
    except Exception as e:
        log.error(f"[Positions] Error loading positions.ini: {e}")
    
    return positions


def _start_from_position(fen: str, position_name: str, hint_move: str = None) -> bool:
    """Start a game from a predefined position.
    
    Sets up the game with the given FEN position and enters correction mode
    to guide the user in setting up the physical board.
    
    Position games are practice/testing and are NOT saved to the database.
    Back button returns directly to menu without resign prompt.
    
    Args:
        fen: FEN string of the position to load
        position_name: Display name of the position (for logging)
        hint_move: Optional UCI move string (e.g., 'e2e4') to show as LED hint
        
    Returns:
        True if position was loaded successfully, False otherwise
    """
    global protocol_manager, app_state, display_manager
    
    try:
        import chess
        from DGTCentaurMods.managers import EVENT_WHITE_TURN, EVENT_BLACK_TURN
        
        log.info(f"[Positions] Loading position: {position_name}")
        log.info(f"[Positions] FEN: {fen}")
        if hint_move:
            log.info(f"[Positions] Hint move: {hint_move}")
        
        # Validate FEN
        try:
            test_board = chess.Board(fen)
        except ValueError as e:
            log.error(f"[Positions] Invalid FEN: {e}")
            return False
        
        # Validate hint move if provided
        hint_from_sq = None
        hint_to_sq = None
        if hint_move and len(hint_move) >= 4:
            try:
                hint_from_sq = chess.parse_square(hint_move[0:2])
                hint_to_sq = chess.parse_square(hint_move[2:4])
                # Validate move is legal in this position
                hint_chess_move = chess.Move.from_uci(hint_move)
                if hint_chess_move not in test_board.legal_moves:
                    log.warning(f"[Positions] Hint move {hint_move} is not legal in position")
                    hint_from_sq = None
                    hint_to_sq = None
            except (ValueError, IndexError) as e:
                log.warning(f"[Positions] Invalid hint move format {hint_move}: {e}")
                hint_from_sq = None
                hint_to_sq = None
        
        # Start game mode with position game flag (disables DB, changes back behavior)
        _start_game_mode(starting_fen=fen, is_position_game=True)
        
        if protocol_manager is None or protocol_manager.game_manager is None:
            log.error("[Positions] Failed to start game mode")
            return False
        
        gm = protocol_manager.game_manager
        
        # Set the board to the loaded position
        gm.chess_board.set_fen(fen)
        
        log.info(f"[Positions] Position loaded: {gm.chess_board.fen()}")
        
        # Update the display to show the position
        if protocol_manager:
            protocol_manager._update_display()
        
        # Check if physical board matches the loaded position
        current_physical_state = board.getChessState()
        expected_logical_state = gm._chess_board_to_state(gm.chess_board)
        
        if current_physical_state is not None and expected_logical_state is not None:
            if not gm._validate_board_state(current_physical_state, expected_logical_state):
                log.info("[Positions] Physical board does not match position, entering correction mode")
                board.beep(board.SOUND_GENERAL, event_type='game_event')
                
                # Store hint for after correction mode exits
                if hint_from_sq is not None and hint_to_sq is not None:
                    gm.set_pending_hint(hint_from_sq, hint_to_sq)
                
                gm._enter_correction_mode()
                gm._provide_correction_guidance(current_physical_state, expected_logical_state)
            else:
                log.info("[Positions] Physical board matches position")
                board.beep(board.SOUND_GENERAL, event_type='game_event')
                
                # Check if position is already a terminal state (checkmate, stalemate, etc.)
                outcome = gm.chess_board.outcome(claim_draw=True)
                if outcome is not None:
                    # Game is already over - show game over screen
                    result_string = str(gm.chess_board.result())
                    termination = str(outcome.termination).replace("Termination.", "")
                    log.info(f"[Positions] Position is already terminal: {termination} ({result_string})")
                    
                    # Show game over screen via display manager
                    if display_manager:
                        display_manager.show_game_over(result_string, termination)
                else:
                    # Show hint LEDs if provided
                    if hint_from_sq is not None and hint_to_sq is not None:
                        log.info(f"[Positions] Showing hint LEDs: {hint_move} ({hint_from_sq} -> {hint_to_sq})")
                        board.ledFromTo(hint_from_sq, hint_to_sq, repeat=0)
                    
                    # Board is correct - trigger turn event
                    if gm.event_callback is not None:
                        if gm.chess_board.turn == chess.WHITE:
                            log.info("[Positions] White to move")
                            gm.event_callback(EVENT_WHITE_TURN)
                        else:
                            log.info("[Positions] Black to move")
                            gm.event_callback(EVENT_BLACK_TURN)
        else:
            log.warning("[Positions] Could not validate physical board state")
        
        return True
        
    except Exception as e:
        log.error(f"[Positions] Error loading position: {e}")
        return False


# ============================================================================
# Engine/Settings Helpers
# ============================================================================

def _load_available_engines() -> List[str]:
    """Load list of available engines from .uci files.
    
    Returns:
        List of engine names (without .uci extension)
    """
    global _available_engines, _engine_elo_levels
    
    if _available_engines:
        return _available_engines
    
    engines_dir = pathlib.Path("/opt/DGTCentaurMods/engines")
    uci_dir = pathlib.Path("/opt/DGTCentaurMods/config/engines")
    
    # Fallback to development paths
    if not uci_dir.exists():
        base_path = pathlib.Path(__file__).parent
        uci_dir = base_path / "defaults" / "engines"
    
    if not uci_dir.exists():
        log.warning(f"[Settings] UCI config directory not found: {uci_dir}")
        return ['stockfish_pi']  # Default fallback
    
    engines = []
    for uci_file in uci_dir.glob("*.uci"):
        engine_name = uci_file.stem
        engines.append(engine_name)
        
        # Also load ELO levels for this engine
        _load_engine_elo_levels(engine_name, uci_file)
    
    _available_engines = sorted(engines)
    log.info(f"[Settings] Found {len(_available_engines)} engines: {_available_engines}")
    return _available_engines


def _load_engine_elo_levels(engine_name: str, uci_path: pathlib.Path) -> List[str]:
    """Load ELO levels from an engine's .uci file.
    
    Args:
        engine_name: Name of the engine
        uci_path: Path to the .uci file
        
    Returns:
        List of ELO level names (section headers from .uci file)
    """
    global _engine_elo_levels
    
    if engine_name in _engine_elo_levels:
        return _engine_elo_levels[engine_name]
    
    levels = ['Default']  # Always include Default
    
    try:
        import configparser
        config = configparser.ConfigParser()
        config.read(str(uci_path))
        
        for section in config.sections():
            if section != 'DEFAULT':
                levels.append(section)
        
        _engine_elo_levels[engine_name] = levels
        log.debug(f"[Settings] Engine {engine_name} ELO levels: {levels}")
    except Exception as e:
        log.warning(f"[Settings] Error loading ELO levels from {uci_path}: {e}")
        _engine_elo_levels[engine_name] = ['Default']
    
    return _engine_elo_levels[engine_name]


def _get_engine_elo_levels(engine_name: str) -> List[str]:
    """Get ELO levels for an engine.
    
    Args:
        engine_name: Name of the engine
        
    Returns:
        List of ELO level names
    """
    global _engine_elo_levels
    
    if engine_name in _engine_elo_levels:
        return _engine_elo_levels[engine_name]
    
    # Try to load from .uci file
    uci_dir = pathlib.Path("/opt/DGTCentaurMods/config/engines")
    if not uci_dir.exists():
        base_path = pathlib.Path(__file__).parent
        uci_dir = base_path / "defaults" / "engines"
    
    uci_path = uci_dir / f"{engine_name}.uci"
    if uci_path.exists():
        return _load_engine_elo_levels(engine_name, uci_path)
    
    return ['Default']


# ============================================================================
# Menu Functions
# ============================================================================

def create_main_menu_entries(centaur_available: bool = True) -> List[IconMenuEntry]:
    """Create the standard main menu entry configuration.
    
    Layout (top to bottom):
    1. Universal - prominent top button with large centered knight icon (2x height)
       Uses vertical layout (icon on top, text below)
    2. Settings - standard height, horizontal layout
    3. Original Centaur - smaller bottom option (2/3 height, smaller knight)
    
    Args:
        centaur_available: Whether DGT Centaur software is available
        
    Returns:
        List of IconMenuEntry for main menu
    """
    entries = []
    
    # Universal at top - prominent with large centered knight icon
    # Vertical layout: icon centered on top, text centered below
    entries.append(IconMenuEntry(
        key="Universal",
        label="PLAY",
        icon_name="universal_logo",
        enabled=True,
        height_ratio=2.0,
        icon_size=80,
        layout="vertical",
        font_size=32,  # Larger text for prominent button
        bold=True
    ))
    
    # Settings in middle - standard height, horizontal layout
    entries.append(IconMenuEntry(
        key="Settings",
        label="Settings",
        icon_name="settings",
        enabled=True,
        height_ratio=1.0,
        layout="horizontal",
        font_size=16
    ))
    
    # Original Centaur at bottom - smaller (2/3 height)
    if centaur_available:
        entries.append(IconMenuEntry(
            key="Centaur",
            label="Original\nCentaur",
            icon_name="centaur",
            enabled=True,
            height_ratio=0.67,
            icon_size=28,
            layout="horizontal",
            font_size=14  # Smaller text for compact button
        ))
    
    return entries


def create_settings_entries() -> List[IconMenuEntry]:
    """Create entries for the settings submenu.
    
    Uses current values from _game_settings for engine, elo, color, and timed_mode.
    Multi-line labels are used to show the setting name and current value.
    Time control shows current setting and opens a selection menu.

    Returns:
        List of IconMenuEntry for settings menu
    """
    engine_label = f"{_game_settings['engine'].capitalize()}"
    elo_label = f"ELO {_game_settings['elo']}"
    color_label = f"{_game_settings['player_color'].capitalize()}"
    
    # Time control: show current setting, icon indicates enabled/disabled
    time_control = _game_settings['time_control']
    if time_control == 0:
        time_label = "Time\nDisabled"
        time_icon = "timer"
    else:
        time_label = f"Time\n{time_control} min"
        time_icon = "timer_checked"
    
    return [
        IconMenuEntry(key="Positions", label="Positions", icon_name="positions", enabled=True, font_size=12, height_ratio=0.8),
        IconMenuEntry(key="Engine", label=engine_label, icon_name="engine", enabled=True, font_size=12, height_ratio=0.8),
        IconMenuEntry(key="ELO", label=elo_label, icon_name="elo", enabled=True, font_size=12, height_ratio=0.8),
        IconMenuEntry(key="Color", label=color_label, icon_name="color", enabled=True, font_size=12, height_ratio=0.8),
        IconMenuEntry(key="TimeControl", label=time_label, icon_name=time_icon, enabled=True, font_size=12, height_ratio=0.8),
        IconMenuEntry(key="System", label="System", icon_name="system", enabled=True, font_size=12, height_ratio=0.8),
    ]


def create_system_entries() -> List[IconMenuEntry]:
    """Create entries for the system submenu.
    
    Includes sound, WiFi, sleep timer, shutdown, and reboot options.
    Sleep timer uses checked box icon when enabled, empty box when disabled.

    Returns:
        List of IconMenuEntry for system menu
    """
    # Get current inactivity timeout for display
    timeout = board.get_inactivity_timeout()
    if timeout == 0:
        timeout_label = "Sleep Timer\nDisabled"
        timeout_icon = "timer"  # Empty box
    else:
        timeout_label = f"Sleep Timer\n{timeout // 60} min"
        timeout_icon = "timer_checked"  # Checked box
    
    # Analysis mode checkbox
    analysis_mode_icon = "checkbox_checked" if _game_settings['analysis_mode'] else "checkbox_empty"
    
    return [
        IconMenuEntry(key="Display", label="Display", icon_name="display", enabled=True),
        IconMenuEntry(key="WiFi", label="WiFi", icon_name="wifi", enabled=True),
        IconMenuEntry(key="Bluetooth", label="Bluetooth", icon_name="bluetooth", enabled=True),
        IconMenuEntry(key="Accounts", label="Accounts", icon_name="account", enabled=True),
        IconMenuEntry(key="Sound", label="Sound", icon_name="sound", enabled=True),
        IconMenuEntry(key="AnalysisMode", label="Analysis\nMode", icon_name=analysis_mode_icon, enabled=True),
        IconMenuEntry(key="Inactivity", label=timeout_label, icon_name=timeout_icon, enabled=True),
        IconMenuEntry(key="ResetSettings", label="Reset\nSettings", icon_name="cancel", enabled=True),
        IconMenuEntry(key="Shutdown", label="Shutdown", icon_name="shutdown", enabled=True),
        IconMenuEntry(key="Reboot", label="Reboot", icon_name="reboot", enabled=True),
    ]


def _show_menu(entries: List[IconMenuEntry], initial_index: int = 0) -> str:
    """Display a menu and wait for selection.

    Uses the MenuManager singleton for menu management.

    Args:
        entries: List of menu entry configurations to display
        initial_index: Index of the entry to select initially (for returning to parent menus)

    Returns:
        Selected entry key, "BACK", "HELP", "SHUTDOWN", "CLIENT_CONNECTED", or "PIECE_MOVED"
    """
    global _menu_manager

    # Clamp initial_index to valid range
    if initial_index < 0 or initial_index >= len(entries):
        initial_index = 0

    # Clear existing widgets and add status bar
    board.display_manager.clear_widgets()

    # Use the MenuManager to show the menu
    result = _menu_manager.show_menu(entries, initial_index=initial_index)
    return result.key


def _start_game_mode(starting_fen: str = None, is_position_game: bool = False):
    """Transition from menu to game mode.

    Initializes game handler and display manager, shows chess widgets.
    Uses settings from _game_settings (configurable via Settings menu).
    
    Args:
        starting_fen: FEN string for initial position. If None, uses standard starting position.
        is_position_game: If True, this is a practice position game:
                         - Database saving is disabled
                         - Back button returns directly to menu (no resign prompt)
    """
    global app_state, protocol_manager, display_manager, _game_settings, _is_position_game

    log.info(f"[App] Transitioning to GAME mode (position_game={is_position_game})")
    _is_position_game = is_position_game
    app_state = AppState.GAME
    
    # Determine if we should save to database
    # Position games are practice and should not be saved
    save_to_database = not is_position_game
    
    # Get current game settings
    engine_name = _game_settings['engine']
    engine_elo = _game_settings['elo']
    player_color_setting = _game_settings['player_color']
    
    # Check if this is 2-player mode (no engine opponent)
    is_two_player = player_color_setting == "2player"
    
    # Check if this is Hand+Brain mode (engine provides piece hints, plays opponent)
    is_hand_brain = player_color_setting == "handbrain"

    # Determine player color for standalone engine
    if is_two_player:
        # In 2-player mode, human plays both sides, no engine opponent
        player_color = chess.WHITE  # Doesn't matter, engine won't play
        log.info("[App] 2-player mode: no engine opponent")
    elif is_hand_brain:
        # In Hand+Brain mode, human plays white by default, engine plays black
        player_color = chess.WHITE
        log.info("[App] Hand+Brain mode: engine provides hints and plays black")
    elif player_color_setting == "random":
        player_color = chess.WHITE if random.randint(0, 1) == 0 else chess.BLACK
        log.info(f"[App] Random color selected: {'white' if player_color == chess.WHITE else 'black'}")
    else:
        player_color = chess.WHITE if player_color_setting == "white" else chess.BLACK

    # Get analysis engine path (only if analysis mode is enabled)
    base_path = pathlib.Path(__file__).parent
    analysis_mode = _game_settings['analysis_mode']
    analysis_engine_path = str((base_path / "engines/ct800").resolve()) if analysis_mode else None

    # Create DisplayManager - handles all game widgets (chess board, analysis, clock)
    # Analysis runs in a background thread so it doesn't block move processing
    display_manager = DisplayManager(
        flip_board=False,
        show_analysis=_game_settings['show_analysis'],
        analysis_engine_path=analysis_engine_path,
        on_exit=lambda: _return_to_menu("Menu exit"),
        hand_brain_mode=is_hand_brain,
        initial_fen=starting_fen,
        time_control=_game_settings['time_control'],
        show_board=_game_settings['show_board'],
        show_clock=_game_settings['show_clock'],
        show_graph=_game_settings['show_graph'],
        analysis_mode=analysis_mode
    )
    log.info(f"[App] DisplayManager initialized (time_control={_game_settings['time_control']} min, "
             f"analysis_mode={analysis_mode}, "
             f"board={_game_settings['show_board']}, clock={_game_settings['show_clock']}, "
             f"analysis={_game_settings['show_analysis']}, "
             f"graph={_game_settings['show_graph']})")

    # Display update callback for ProtocolManager
    def update_display(fen):
        """Update display manager with new position.
        
        Analysis is triggered but runs in a background thread, so it doesn't
        block move validation or recording. Also updates the clock turn indicator.
        """
        if display_manager:
            display_manager.update_position(fen)
            # Trigger analysis (runs asynchronously in background thread)
            try:
                board_obj = chess.Board(fen)
                display_manager.analyze_position(board_obj)
                # Update clock turn indicator based on whose turn it is
                current_turn = "white" if board_obj.turn == chess.WHITE else "black"
                display_manager.set_clock_active(current_turn)
            except Exception as e:
                log.debug(f"Error triggering analysis: {e}")

    # Back menu result handler
    def _on_back_menu_result(result: str):
        """Handle result from back menu (resign/draw/cancel/exit).
        
        In 2-player mode, result can be 'resign_white' or 'resign_black' to
        indicate which side is resigning.
        """
        # Reset the kings-in-center menu flag (in case this was triggered by that menu)
        protocol_manager.reset_kings_in_center_menu_flag()
        
        if result == "resign":
            protocol_manager.handle_resign()
            _return_to_menu("Resigned")
        elif result == "resign_white":
            protocol_manager.handle_resign(chess.WHITE)
            _return_to_menu("White Resigned")
        elif result == "resign_black":
            protocol_manager.handle_resign(chess.BLACK)
            _return_to_menu("Black Resigned")
        elif result == "draw":
            protocol_manager.handle_draw()
            _return_to_menu("Draw")
        elif result == "exit":
            board.shutdown(reason="User selected 'exit' from game menu")
        # cancel is handled by DisplayManager (restores display)
    
    # For position games, back button returns to positions menu
    def _on_position_game_back():
        """Handle back press for position games - signal return to positions menu.
        
        We can't call _handle_positions_menu() directly here because we're inside
        the key callback chain and _show_menu() would block waiting for key events
        from the same callback thread. Instead, set a flag and let the main loop handle it.
        """
        global app_state, _return_to_positions_menu
        log.info("[App] Position game back pressed - signaling return to positions menu")
        _cleanup_game()
        _return_to_positions_menu = True
        app_state = AppState.SETTINGS

    # Brain hint callback for Hand+Brain mode
    def _on_brain_hint(piece_symbol: str, squares: list):
        """Handle brain hint from engine analysis.
        
        Updates the display with the suggested piece type and lights up
        squares containing that piece type.
        """
        if display_manager:
            display_manager.set_brain_hint(piece_symbol)
        # Light up squares with the suggested piece type
        if squares:
            board.ledArray(squares, repeat=20)
    
    # Create ProtocolManager with user-configured settings
    # Note: Key and field events are routed through universal.py's callbacks
    # In 2-player mode, don't pass an engine name so no engine opponent is used
    protocol_manager = ProtocolManager(
        sendMessage_callback=sendMessage,
        client_type=None,
        compare_mode=relay_mode,
        standalone_engine_name=None if is_two_player else engine_name,
        player_color=player_color,
        engine_elo=engine_elo,
        display_update_callback=update_display,
        save_to_database=save_to_database,
        hand_brain_mode=is_hand_brain,
        brain_hint_callback=_on_brain_hint if is_hand_brain else None,
        takeback_callback=display_manager.remove_last_analysis_score
    )
    log.info(f"[App] ProtocolManager created: engine={None if is_two_player else engine_name}, elo={engine_elo}, color={player_color_setting}, hand_brain={is_hand_brain}, save_to_db={save_to_database}")
    
    # Wire up GameManager callbacks to DisplayManager
    protocol_manager.set_on_promotion_needed(display_manager.show_promotion_menu)
    
    # For position games, skip the resign/draw menu and return directly
    if is_position_game:
        protocol_manager.set_on_back_pressed(_on_position_game_back)
    else:
        # In 2-player mode, show separate resign options for white and black
        protocol_manager.set_on_back_pressed(lambda: display_manager.show_back_menu(
            _on_back_menu_result, 
            is_two_player=protocol_manager.is_two_player_mode
        ))
    
    # Kings-in-center gesture (DGT resign/draw) - only for 2-player mode
    # In engine games, moving kings to center would just trigger correction mode
    # Uses the same back menu as the BACK button - just with a beep to confirm gesture
    if is_two_player and not is_position_game:
        def _on_kings_in_center():
            board.beep(board.SOUND_GENERAL, event_type='game_event')  # Beep to confirm gesture recognized
            display_manager.show_back_menu(_on_back_menu_result, is_two_player=True)
        protocol_manager.set_on_kings_in_center(_on_kings_in_center)
        # Cancel callback simulates BACK key press to properly dismiss menu
        protocol_manager.set_on_kings_in_center_cancel(display_manager.cancel_menu)
    
    # King-lift resign gesture - works in any game mode for human player's king
    # When king is held off board for 3+ seconds, show resign confirmation
    def _on_king_lift_resign_result(result: str):
        """Handle result from king-lift resign menu."""
        # Reset the menu flag
        protocol_manager.reset_king_lift_resign_menu_flag()
        
        if result == "resign":
            # Get the color of the king that was lifted
            king_color = protocol_manager.get_king_lifted_color()
            if king_color is not None:
                protocol_manager.handle_resign(king_color)
                color_name = "White" if king_color == chess.WHITE else "Black"
                _return_to_menu(f"{color_name} Resigned")
            else:
                # Fallback - shouldn't happen but handle gracefully
                protocol_manager.handle_resign()
                _return_to_menu("Resigned")
        # cancel is handled by DisplayManager (restores display)
    
    def _on_king_lift_resign(king_color):
        """Handle king-lift resign gesture."""
        display_manager.show_king_lift_resign_menu(king_color, _on_king_lift_resign_result)
    
    protocol_manager.set_on_king_lift_resign(_on_king_lift_resign)
    protocol_manager.set_on_king_lift_resign_cancel(display_manager.cancel_menu)
    
    # Terminal position callback - triggered when correction mode exits on a position
    # that is already checkmate, stalemate, or insufficient material
    def _on_terminal_position(result: str, termination: str):
        """Handle terminal position detection after correction mode exits."""
        log.info(f"[App] Terminal position detected: {termination} ({result})")
        display_manager.show_game_over(result, termination)
    
    protocol_manager.set_on_terminal_position(_on_terminal_position)
    
    # Wire up display bridge to connect GameManager with DisplayManager
    # Provides consolidated interface for: clock times, eval scores, alerts, position updates
    protocol_manager.set_display_bridge(display_manager)
    
    # Wire up flag callback for when a player's time expires
    def _on_flag(color: str):
        """Handle time expiration - ends the game."""
        log.info(f"[App] {color.capitalize()} flagged (time expired)")
        protocol_manager.handle_flag(color)
        display_manager.stop_clock()
        # Game over will be shown via the event callback when handle_flag triggers termination event
    
    display_manager.set_on_flag(_on_flag)
    
    # Wire up event callback to handle game events
    from DGTCentaurMods.managers import EVENT_NEW_GAME, EVENT_WHITE_TURN, EVENT_BLACK_TURN
    _clock_started = False
    def _on_game_event(event):
        nonlocal _clock_started
        global _switch_to_normal_game, _is_position_game
        if event == EVENT_NEW_GAME:
            display_manager.reset_analysis()
            # Reset clock started flag for new game
            _clock_started = False
            # If we're in a position game and the starting position is set up,
            # signal transition to normal game mode
            if _is_position_game:
                log.info("[App] Starting position detected in position game - signaling switch to normal game")
                _switch_to_normal_game = True
        elif event == EVENT_WHITE_TURN or event == EVENT_BLACK_TURN:
            # Handle turn events for clock management
            active_color = "white" if event == EVENT_WHITE_TURN else "black"
            if not _clock_started:
                # Start the clock on the first turn event (game has truly started)
                display_manager.start_clock(active_color)
                _clock_started = True
                log.debug(f"[App] Clock started, {active_color} to move")
            else:
                # Switch clock on subsequent turn events
                display_manager.switch_clock_turn()
        elif isinstance(event, str) and event.startswith("Termination."):
            # Game ended (checkmate, stalemate, resign, draw, etc.)
            termination_type = event[12:]  # Remove "Termination." prefix
            result = protocol_manager.get_result()
            log.info(f"[App] Game terminated: {termination_type}, result={result}")
            display_manager.stop_clock()
            display_manager.show_game_over(result, termination_type)
    protocol_manager._external_event_callback = _on_game_event
    
    # Register protocol_manager with ConnectionManager - this also processes any queued data
    _connection_manager.set_protocol_manager(protocol_manager)


def _cleanup_game():
    """Clean up game handler and display manager.
    
    Used when exiting a game, whether returning to menu or positions menu.
    """
    global protocol_manager, display_manager, _pending_piece_events, _is_position_game
    
    # Clear position game flag
    _is_position_game = False
    
    # Clear any stale pending piece events from previous game
    _pending_piece_events.clear()
    
    # Clear ConnectionManager handler and pending data
    _connection_manager.clear_handler()
    
    # Clean up game handler
    if protocol_manager is not None:
        try:
            protocol_manager.cleanup()
        except Exception as e:
            log.debug(f"Error cleaning up game handler: {e}")
        protocol_manager = None
    
    # Clean up display manager
    if display_manager is not None:
        try:
            display_manager.cleanup()
        except Exception as e:
            log.debug(f"Error cleaning up display manager: {e}")
        display_manager = None


def _return_to_menu(reason: str):
    """Return from game mode to menu mode.

    Cleans up game handler and display manager. For position games, returns to
    the positions menu. For regular games, returns to the main menu.

    Args:
        reason: Reason for returning to menu (for logging)
    """
    global app_state, _return_to_positions_menu, _is_position_game

    # Check if this was a position game BEFORE cleanup clears the flag
    was_position_game = _is_position_game

    log.info(f"[App] Returning to menu: {reason} (was_position_game={was_position_game})")
    _cleanup_game()
    
    if was_position_game:
        # Return to positions menu, not main menu
        _return_to_positions_menu = True
        app_state = AppState.SETTINGS
    else:
        app_state = AppState.MENU


def _handle_settings():
    """Handle the Settings submenu.
    
    Displays settings options and handles their selection.
    Includes game settings (Engine, ELO, Color) and system settings (Sound, Shutdown, Reboot).
    """
    global app_state, _game_settings
    from DGTCentaurMods.board import centaur
    
    app_state = AppState.SETTINGS
    last_selected = 0  # Track last selected index for returning from submenus
    
    while app_state == AppState.SETTINGS:
        entries = create_settings_entries()
        result = _show_menu(entries, initial_index=last_selected)
        
        # Update last_selected for when we return from a submenu
        last_selected = find_entry_index(entries, result)
        
        # Handle special results that should break out of all menus
        if is_break_result(result):
            app_state = AppState.MENU
            return result
        
        if result == "BACK":
            app_state = AppState.MENU
            return
        
        if result == "SHUTDOWN":
            _shutdown("Shutdown")
            return
        
        if result == "Engine":
            # Engine selection submenu
            engines = _load_available_engines()
            engine_entries = []
            for engine in engines:
                # Mark current selection
                label = f"* {engine}" if engine == _game_settings['engine'] else engine
                engine_entries.append(
                    IconMenuEntry(key=engine, label=label, icon_name="engine", enabled=True)
                )
            
            engine_result = _show_menu(engine_entries)
            if is_break_result(engine_result):
                app_state = AppState.MENU
                return engine_result
            if engine_result not in ["BACK", "SHUTDOWN", "HELP"]:
                old_engine = _game_settings['engine']
                _save_game_setting('engine', engine_result)
                log.info(f"[Settings] Engine changed: {old_engine} -> {engine_result}")
                # Reset ELO to Default when engine changes
                _save_game_setting('elo', 'Default')
                board.beep(board.SOUND_GENERAL, event_type='key_press')
        
        elif result == "ELO":
            # ELO selection submenu (depends on selected engine)
            current_engine = _game_settings['engine']
            elo_levels = _get_engine_elo_levels(current_engine)
            elo_entries = []
            for elo in elo_levels:
                # Mark current selection
                label = f"* {elo}" if elo == _game_settings['elo'] else elo
                elo_entries.append(
                    IconMenuEntry(key=elo, label=label, icon_name="elo", enabled=True)
                )
            
            elo_result = _show_menu(elo_entries)
            if is_break_result(elo_result):
                app_state = AppState.MENU
                return elo_result
            if elo_result not in ["BACK", "SHUTDOWN", "HELP"]:
                old_elo = _game_settings['elo']
                _save_game_setting('elo', elo_result)
                log.info(f"[Settings] ELO changed: {old_elo} -> {elo_result}")
                board.beep(board.SOUND_GENERAL, event_type='key_press')
        
        elif result == "Color":
            # Player color selection submenu
            color_entries = [
                IconMenuEntry(
                    key="white",
                    label="* White" if _game_settings['player_color'] == 'white' else "White",
                    icon_name="white_piece",
                    enabled=True
                ),
                IconMenuEntry(
                    key="black",
                    label="* Black" if _game_settings['player_color'] == 'black' else "Black",
                    icon_name="black_piece",
                    enabled=True
                ),
                IconMenuEntry(
                    key="random",
                    label="* Random" if _game_settings['player_color'] == 'random' else "Random",
                    icon_name="random",
                    enabled=True
                ),
                IconMenuEntry(
                    key="2player",
                    label="* 2 Player" if _game_settings['player_color'] == '2player' else "2 Player",
                    icon_name="universal_logo",
                    enabled=True
                ),
                IconMenuEntry(
                    key="handbrain",
                    label="* Hand+Brain" if _game_settings['player_color'] == 'handbrain' else "Hand+Brain",
                    icon_name="engine",
                    enabled=True
                ),
            ]
            
            color_result = _show_menu(color_entries)
            if is_break_result(color_result):
                app_state = AppState.MENU
                return color_result
            if color_result in ["white", "black", "random", "2player", "handbrain"]:
                old_color = _game_settings['player_color']
                _save_game_setting('player_color', color_result)
                log.info(f"[Settings] Player color changed: {old_color} -> {color_result}")
                board.beep(board.SOUND_GENERAL, event_type='key_press')
                # Start game immediately after selecting color/game type
                app_state = AppState.MENU
                _start_game_mode()
                return  # Exit settings to enter game mode
        
        elif result == "TimeControl":
            # Time control selection submenu
            time_entries = []
            current_time = _game_settings['time_control']
            
            for minutes in TIME_CONTROL_OPTIONS:
                is_selected = (minutes == current_time)
                # Icon indicates selection - no need for star prefix
                label = "Disabled" if minutes == 0 else f"{minutes} min"
                icon = "timer_checked" if is_selected else "timer"
                
                time_entries.append(
                    IconMenuEntry(key=str(minutes), label=label, icon_name=icon, enabled=True)
                )
            
            time_result = _show_menu(time_entries)
            if is_break_result(time_result):
                app_state = AppState.MENU
                return time_result
            if time_result not in ["BACK", "SHUTDOWN", "HELP"]:
                try:
                    new_time = int(time_result)
                    old_time = _game_settings['time_control']
                    _save_game_setting('time_control', str(new_time))
                    _game_settings['time_control'] = new_time
                    log.info(f"[Settings] Time control changed: {old_time} -> {new_time} min")
                    board.beep(board.SOUND_GENERAL, event_type='key_press')
                except ValueError:
                    pass
            # Stay in settings menu to allow further configuration
        
        elif result == "Positions":
            position_result = _handle_positions_menu()
            if is_break_result(position_result):
                app_state = AppState.MENU
                return position_result
            if position_result:
                # Position was loaded, exit settings and go to game
                return
        
        elif result == "System":
            system_result = _handle_system_menu()
            if is_break_result(system_result):
                app_state = AppState.MENU
                return system_result


def _handle_display_settings():
    """Handle the Display settings submenu.
    
    Shows checkboxes for each widget that can be shown/hidden during game.
    Settings take effect on the next game start.
    
    Returns:
        Break result if user triggered a break action, None otherwise
    """
    global _game_settings
    
    while True:
        # Build entries with current settings
        entries = [
            IconMenuEntry(
                key="show_board",
                label="Board",
                icon_name="checkbox_checked" if _game_settings['show_board'] else "checkbox_empty",
                enabled=True
            ),
            IconMenuEntry(
                key="show_clock",
                label="Clock",
                icon_name="checkbox_checked" if _game_settings['show_clock'] else "checkbox_empty",
                enabled=True
            ),
            IconMenuEntry(
                key="show_analysis",
                label="Analysis",
                icon_name="checkbox_checked" if _game_settings['show_analysis'] else "checkbox_empty",
                enabled=True
            ),
            IconMenuEntry(
                key="show_graph",
                label="Graph",
                icon_name="checkbox_checked" if _game_settings['show_graph'] else "checkbox_empty",
                enabled=_game_settings['show_analysis']  # Only enabled if analysis is on
            ),
        ]
        
        result = _show_menu(entries)
        
        if is_break_result(result):
            return result
        
        if result == "BACK":
            return None
        
        # Toggle the selected setting
        if result in _game_settings and isinstance(_game_settings[result], bool):
            new_value = not _game_settings[result]
            _game_settings[result] = new_value
            _save_game_setting(result, new_value)
            log.info(f"[Display] {result} changed to {new_value}")
            board.beep(board.SOUND_GENERAL, event_type='key_press')
            # Continue loop to show updated menu


def _handle_reset_settings():
    """Handle reset all settings to defaults.
    
    Shows a confirmation dialog, then clears all entries in the [game] section
    of centaur.ini and reloads settings with defaults.
    
    Returns:
        Break result if user triggered a break action, None otherwise
    """
    global _game_settings
    
    # Confirmation menu
    entries = [
        IconMenuEntry(key="confirm", label="Reset All\nSettings?", icon_name="cancel", enabled=True),
        IconMenuEntry(key="cancel", label="Cancel", icon_name="cancel", enabled=True),
    ]
    
    result = _show_menu(entries)
    
    if is_break_result(result):
        return result
    
    if result == "confirm":
        try:
            from DGTCentaurMods.board.settings import Settings
            import configparser
            
            # Read the current config
            config = configparser.ConfigParser()
            config.read(Settings.configfile)
            
            # Clear all options in the [game] section
            if config.has_section(SETTINGS_SECTION):
                for key in list(config.options(SETTINGS_SECTION)):
                    config.remove_option(SETTINGS_SECTION, key)
                Settings.write_config(config)
                log.info("[Settings] Cleared all game settings from centaur.ini")
            
            # Reset in-memory settings to defaults
            _game_settings['engine'] = 'stockfish_pi'
            _game_settings['elo'] = 'Default'
            _game_settings['player_color'] = 'white'
            _game_settings['time_control'] = 0
            _game_settings['analysis_mode'] = True
            _game_settings['show_board'] = True
            _game_settings['show_clock'] = True
            _game_settings['show_analysis'] = True
            _game_settings['show_graph'] = True

            # Reload from file (which will use defaults since section is empty)
            _load_game_settings()
            
            board.beep(board.SOUND_GENERAL, event_type='key_press')
            log.info("[Settings] Settings reset to defaults")
            
        except Exception as e:
            log.error(f"[Settings] Error resetting settings: {e}")
            board.beep(board.SOUND_WRONG_MOVE, event_type='error')
    
    return None


def _handle_positions_menu(return_to_last_position: bool = False) -> bool:
    """Handle the Positions submenu.
    
    Shows categories of predefined positions, then positions within that category.
    Loads the selected position and starts a game.
    
    Uses nested loops so that pressing BACK from position details returns to
    the category menu, and pressing BACK from category menu exits entirely.
    
    Args:
        return_to_last_position: If True, skip category menu and go directly to the
                                 last selected position in the last selected category.
    
    Returns:
        True if a position was loaded (caller should exit settings), False otherwise
    """
    global _last_position_category_index, _last_position_index, _last_position_category
    
    positions = _load_positions_config()
    
    if not positions:
        log.warning("[Positions] No positions available")
        board.beep(board.SOUND_WRONG_MOVE, event_type='error')
        return False
    
    # Map category names to specific icons
    category_icons = {
        'test': 'positions_test',
        'puzzles': 'positions_puzzles',
        'endgames': 'positions_endgames',
        'custom': 'positions_custom',
    }
    
    # Build category entries once
    category_entries = []
    for category in positions.keys():
        # Capitalize category name for display
        display_name = category.replace('_', ' ').title()
        count = len(positions[category])
        # Use category-specific icon if available, otherwise default to positions
        icon_name = category_icons.get(category, 'positions')
        category_entries.append(IconMenuEntry(
            key=category,
            label=f"{display_name}\n({count})",
            icon_name=icon_name,
            enabled=True,
            font_size=14,
            height_ratio=1.5  # Taller buttons for two lines of text
        ))
    
    # Use stored category index for returning from position list
    last_category_index = _last_position_category_index
    
    # If returning to last position, skip category menu and go directly to positions
    skip_category_menu = return_to_last_position and _last_position_category is not None
    
    # Outer loop for category menu - pressing BACK here exits positions menu
    while True:
        if skip_category_menu:
            # Use stored category from last position game
            category_result = _last_position_category
            skip_category_menu = False  # Only skip once
        else:
            category_result = _show_menu(category_entries, initial_index=last_category_index)
            
            if is_break_result(category_result):
                return category_result
            if category_result in ["BACK", "SHUTDOWN", "HELP"]:
                return False
        
        # Update last_category_index for when we return from position list
        last_category_index = find_entry_index(category_entries, category_result)
        _last_position_category_index = last_category_index
        
        # Show positions in selected category
        category = category_result
        if category not in positions:
            continue
        
        # Build position entries for selected category
        position_entries = []
        for name, fen in positions[category].items():
            # Format name for display - wrap text at word boundaries only if needed
            display_name = name.replace('_', ' ').title()
            
            # Only wrap if text is too long to fit on one line
            # Available width after icon is ~72px, font size 12 = ~6px/char = ~12 chars
            # Use 11 as threshold to be safe
            if len(display_name) <= 11:
                # Short enough to fit on one line
                wrapped_text = display_name
                num_lines = 1
            else:
                # Need to wrap - use ~10 chars per line
                max_line_width = 10
                wrapped_lines = []
                words = display_name.split()
                current_line = ""
                
                for word in words:
                    if not current_line:
                        current_line = word
                    elif len(current_line) + 1 + len(word) <= max_line_width:
                        current_line += " " + word
                    else:
                        wrapped_lines.append(current_line)
                        current_line = word
                if current_line:
                    wrapped_lines.append(current_line)
                
                wrapped_text = '\n'.join(wrapped_lines)
                num_lines = len(wrapped_lines)
            
            # Adjust height ratio based on number of lines
            # 1 line = 1.0, 2 lines = 1.5, 3+ lines = 2.0
            if num_lines <= 1:
                height_ratio = 1.0
            elif num_lines == 2:
                height_ratio = 1.5
            else:
                height_ratio = 2.0
            
            # Determine icon based on position name for test category, else use category icon
            if category == 'test':
                # Map test position names to specific icons
                if 'en_passant' in name:
                    position_icon = 'en_passant'
                elif 'castling' in name:
                    position_icon = 'castling'
                elif 'promotion' in name:
                    position_icon = 'promotion'
                else:
                    position_icon = 'positions_test'
            else:
                position_icon = category_icons.get(category, 'positions')
            
            position_entries.append(IconMenuEntry(
                key=name,
                label=wrapped_text,
                icon_name=position_icon,
                enabled=True,
                font_size=12,
                height_ratio=height_ratio
            ))
        
        # Determine initial position index
        # Use stored index if returning to same category, otherwise start at 0
        if return_to_last_position and category == _last_position_category:
            initial_position_index = _last_position_index
        else:
            initial_position_index = 0
        
        # Inner loop for position details - pressing BACK returns to category menu
        position_result = _show_menu(position_entries, initial_index=initial_position_index)

        if is_break_result(position_result):
            return position_result
        if position_result in ["BACK", "HELP"]:
            # Go back to category menu (continue outer loop)
            # last_category_index already set, so category will be pre-selected
            # Clear last position category so we don't skip category menu next time
            _last_position_category = None
            continue
        elif position_result == "SHUTDOWN":
            return False
        
        # Load the selected position
        if position_result in positions[category]:
            fen, hint_move = positions[category][position_result]
            display_name = position_result.replace('_', ' ').title()
            
            # Store the category and position for returning later
            _last_position_category = category
            _last_position_index = find_entry_index(position_entries, position_result)
            
            if _start_from_position(fen, display_name, hint_move):
                return True


def _get_current_wifi_status() -> tuple:
    """Get current WiFi connection status.
    
    Returns:
        Tuple of (ssid, ip_address) or (None, None) if not connected
    """
    import subprocess
    
    try:
        result = subprocess.run(['iwgetid', '-r'], capture_output=True, text=True, timeout=5)
        ssid = result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
    except Exception:
        ssid = None
    
    ip_address = None
    if ssid:
        try:
            result = subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=5)
            ips = result.stdout.strip().split()
            ip_address = ips[0] if ips else None
        except Exception:
            pass
    
    return ssid, ip_address


def _scan_wifi_networks() -> List[dict]:
    """Scan for available WiFi networks.
    
    Returns:
        List of dicts with 'ssid' and 'signal' keys, sorted by signal strength
    """
    import subprocess
    import re
    
    networks = []
    
    try:
        # Show scanning message (full screen, no status bar)
        board.display_manager.clear_widgets(addStatusBar=False)
        promise = board.display_manager.add_widget(SplashScreen(message="Scanning...", leave_room_for_status_bar=False))
        if promise:
            try:
                promise.result(timeout=5.0)
            except Exception:
                pass
        
        # Use iwlist for scanning - more reliable than nmcli
        result = subprocess.run(
            ['sudo', 'iwlist', 'wlan0', 'scan'],
            capture_output=True, text=True, timeout=30
        )
        
        log.debug(f"[WiFi] iwlist return code: {result.returncode}")
        if result.stderr:
            log.debug(f"[WiFi] iwlist stderr: {result.stderr}")
        
        if result.returncode == 0:
            seen_ssids = set()
            current_ssid = None
            current_signal = 0
            current_security = ""
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                
                # New cell - save previous if exists
                if line.startswith('Cell '):
                    if current_ssid and current_ssid not in seen_ssids:
                        seen_ssids.add(current_ssid)
                        networks.append({
                            'ssid': current_ssid,
                            'signal': current_signal,
                            'security': current_security
                        })
                    current_ssid = None
                    current_signal = 0
                    current_security = ""
                
                # Extract SSID
                if 'ESSID:' in line:
                    match = re.search(r'ESSID:"([^"]*)"', line)
                    if match:
                        current_ssid = match.group(1)
                
                # Extract signal quality
                if 'Quality=' in line:
                    match = re.search(r'Quality=(\d+)/(\d+)', line)
                    if match:
                        quality = int(match.group(1))
                        max_quality = int(match.group(2))
                        current_signal = int((quality / max_quality) * 100)
                
                # Extract encryption
                if 'Encryption key:on' in line:
                    current_security = "WPA"
            
            # Don't forget the last network
            if current_ssid and current_ssid not in seen_ssids:
                seen_ssids.add(current_ssid)
                networks.append({
                    'ssid': current_ssid,
                    'signal': current_signal,
                    'security': current_security
                })
            
            # Sort by signal strength (strongest first)
            networks.sort(key=lambda x: x['signal'], reverse=True)
            log.info(f"[WiFi] Found {len(networks)} networks")
        else:
            log.error(f"[WiFi] iwlist failed: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        log.error("[WiFi] Network scan timed out")
    except Exception as e:
        log.error(f"[WiFi] Error scanning networks: {e}")
        import traceback
        log.error(traceback.format_exc())

    return networks


def _connect_to_wifi(ssid: str, password: str = None) -> bool:
    """Connect to a WiFi network.
    
    Args:
        ssid: Network SSID to connect to
        password: Network password (None for open networks)
    
    Returns:
        True if connection successful, False otherwise
    """
    import subprocess
    
    try:
        # Show connecting message (full screen, no status bar)
        board.display_manager.clear_widgets(addStatusBar=False)
        promise = board.display_manager.add_widget(SplashScreen(message="Connecting...", leave_room_for_status_bar=False))
        if promise:
            try:
                promise.result(timeout=5.0)
            except Exception:
                pass
        
        if password:
            result = subprocess.run(
                ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
                capture_output=True, text=True, timeout=30
            )
        else:
            result = subprocess.run(
                ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid],
                capture_output=True, text=True, timeout=30
            )
        
        if result.returncode == 0:
            log.info(f"[WiFi] Connected to {ssid}")
            board.beep(board.SOUND_GENERAL, event_type='key_press')
            return True
        else:
            log.error(f"[WiFi] Failed to connect: {result.stderr}")
            board.beep(board.SOUND_WRONG, event_type='error')
            return False
            
    except subprocess.TimeoutExpired:
        log.error("[WiFi] Connection timed out")
        board.beep(board.SOUND_WRONG, event_type='error')
        return False
    except Exception as e:
        log.error(f"[WiFi] Error connecting: {e}")
        board.beep(board.SOUND_WRONG, event_type='error')
        return False


def _get_wifi_password_from_board(ssid: str) -> Optional[str]:
    """Get WiFi password using board piece input.

    Displays a keyboard widget on the e-paper where each board square
    corresponds to a character. Lifting and placing a piece on a square
    types that character.

    Args:
        ssid: SSID to display in the title

    Returns:
        Password string or None if cancelled
    """
    global _active_keyboard_widget
    
    log.info(f"[WiFi] Opening keyboard for password entry: {ssid}")
    
    # Clear display and show keyboard widget
    board.display_manager.clear_widgets(addStatusBar=False)
    
    # Create keyboard widget
    keyboard = KeyboardWidget(title=f"Password: {ssid[:10]}", max_length=64)
    _active_keyboard_widget = keyboard
    
    # Add widget to display
    promise = board.display_manager.add_widget(keyboard)
    if promise:
        try:
            promise.result(timeout=2.0)
        except Exception:
            pass
    
    # Wait for user input (blocking)
    try:
        result = keyboard.wait_for_input(timeout=300.0)
        log.info(f"[WiFi] Keyboard input complete, got {'password' if result else 'cancelled'}")
        return result
    finally:
        # Clear keyboard widget reference
        _active_keyboard_widget = None


def _handle_wifi_settings():
    """Handle WiFi settings submenu.

    Shows WiFi status information with a toggle for enable/disable.
    Displays:
    - SSID, IP address, signal strength, frequency
    - Scan button for connecting to networks
    - Enable toggle (checkbox style)
    
    Uses the wifi_info module for status queries and control.
    Subscribes to WiFi status updates to refresh the display when
    connection status changes (connect, disconnect, signal change).
    """
    global _menu_manager
    from DGTCentaurMods.epaper import wifi_info
    
    last_selected = 1  # Default to Scan button (first selectable after status display)
    
    # Callback to refresh menu when WiFi status changes
    def _on_wifi_status_change(status: dict):
        """Refresh the menu when WiFi status changes."""
        if _menu_manager.active_widget is not None:
            log.debug(f"[WiFi Settings] Status changed, refreshing menu: connected={status.get('connected')}")
            _menu_manager.cancel_selection("WIFI_REFRESH")
    
    # Subscribe to WiFi status updates
    wifi_info.subscribe(_on_wifi_status_change)
    
    try:
        while True:
            # Get current status
            wifi_status = wifi_info.get_wifi_status()
            
            # Format status label
            status_label = wifi_info.format_status_label(wifi_status)
            
            # Determine WiFi status icon based on actual state
            # Uses same logic as WiFiStatusWidget from status bar
            is_enabled = wifi_status['enabled']
            is_connected = wifi_status['connected']
            signal = wifi_status.get('signal', 0)
            
            if not is_enabled:
                status_icon = "wifi_disabled"
            elif not is_connected:
                status_icon = "wifi_disconnected"
            elif signal >= 70:
                status_icon = "wifi_strong"
            elif signal >= 40:
                status_icon = "wifi_medium"
            else:
                status_icon = "wifi_weak"
            
            # Enable toggle uses checkbox icon
            enable_icon = "timer_checked" if is_enabled else "timer"
            enable_label = "Enabled" if is_enabled else "Disabled"

            wifi_entries = [
                # Status info display with dynamic WiFi icon (non-selectable)
                IconMenuEntry(
                    key="Info",
                    label=status_label,
                    icon_name=status_icon,
                    enabled=True,
                    selectable=False,
                    height_ratio=1.8,
                    icon_size=52,
                    layout="vertical",
                    font_size=12,
                    border_width=1
                ),
                # Scan button
                IconMenuEntry(
                    key="Scan",
                    label="Scan",
                    icon_name="wifi",
                    enabled=True,
                    selectable=True,
                    height_ratio=0.9,
                    icon_size=28,
                    layout="horizontal",
                    font_size=14
                ),
                # Enable/Disable toggle (checkbox style)
                IconMenuEntry(
                    key="Toggle",
                    label=enable_label,
                    icon_name=enable_icon,
                    enabled=True,
                    selectable=True,
                    height_ratio=0.7,
                    layout="horizontal",
                    font_size=14
                ),
            ]

            wifi_result = _show_menu(wifi_entries, initial_index=last_selected)

            # Handle break results - exit to main loop
            if is_break_result(wifi_result):
                return wifi_result

            # Handle refresh from WiFi status change
            if wifi_result == "WIFI_REFRESH":
                # Keep current selection and rebuild menu
                continue

            # Update last_selected for when we return from a submenu
            last_selected = find_entry_index(wifi_entries, wifi_result)

            if wifi_result in ["BACK", "SHUTDOWN", "HELP"]:
                return

            if wifi_result == "Scan":
                _handle_wifi_scan()
            elif wifi_result == "Toggle":
                # Toggle WiFi state
                if is_enabled:
                    wifi_info.disable_wifi()
                else:
                    if wifi_info.enable_wifi():
                        board.beep(board.SOUND_GENERAL, event_type='key_press')
    finally:
        # Always unsubscribe when exiting the menu
        wifi_info.unsubscribe(_on_wifi_status_change)


def _handle_wifi_scan():
    """Handle WiFi network scanning and selection."""
    log.info("[WiFi] Starting network scan...")
    networks = _scan_wifi_networks()
    log.info(f"[WiFi] Scan complete, found {len(networks)} networks")

    if not networks:
        # Show no networks found message (full screen, no status bar)
        board.display_manager.clear_widgets(addStatusBar=False)
        promise = board.display_manager.add_widget(SplashScreen(message="No networks found", leave_room_for_status_bar=False))
        if promise:
            try:
                promise.result(timeout=2.0)
            except Exception:
                pass
        time.sleep(2)
        return

    # Create menu entries for networks
    network_entries = []
    for net in networks[:10]:  # Limit to 10 networks
        # Signal strength determines icon (icon indicates strength visually)
        signal = net['signal']
        if signal >= 70:
            icon_name = "wifi_strong"
        elif signal >= 40:
            icon_name = "wifi_medium"
        else:
            icon_name = "wifi_weak"

        # Truncate SSID if too long - no signal text, icon shows strength
        ssid_display = net['ssid'][:18] if len(net['ssid']) > 18 else net['ssid']

        network_entries.append(
            IconMenuEntry(key=net['ssid'], label=ssid_display, icon_name=icon_name, enabled=True, font_size=14)
        )
        log.debug(f"[WiFi] Added network entry: {net['ssid']} ({signal}%)")

    log.info(f"[WiFi] Showing menu with {len(network_entries)} entries")
    network_result = _show_menu(network_entries)
    log.info(f"[WiFi] Menu result: {network_result}")

    if is_break_result(network_result):
        return network_result
    if network_result in ["BACK", "SHUTDOWN", "HELP"]:
        return
    
    # User selected a network - find it in the list
    selected_network = None
    for net in networks:
        if net['ssid'] == network_result:
            selected_network = net
            break
    
    if not selected_network:
        return
    
    # Check if network needs password
    needs_password = selected_network.get('security', '') != ''
    
    if needs_password:
        # Get password using board input
        password = _get_wifi_password_from_board(selected_network['ssid'])
        if password is None:
            return
        _connect_to_wifi(selected_network['ssid'], password)
    else:
        _connect_to_wifi(selected_network['ssid'])


def _handle_bluetooth_settings():
    """Handle Bluetooth settings submenu.
    
    Shows Bluetooth status information with a toggle for enable/disable.
    Displays:
    - Device name and MAC address
    - Connection status and connected client type
    - Advertised host names
    - Enable toggle (checkbox style)
    
    Uses the bluetooth_status module for status queries and control.
    """
    from DGTCentaurMods.epaper import bluetooth_status
    
    def build_entries():
        """Build Bluetooth settings menu entries."""
        device_name = _args.device_name if _args else 'DGT PEGASUS'
        bt_status = bluetooth_status.get_bluetooth_status(
            device_name=device_name,
            ble_manager=ble_manager,
            rfcomm_connected=client_connected
        )
        status_label = bluetooth_status.format_status_label(bt_status)
        advertised_label = bluetooth_status.get_advertised_names_label()
        is_enabled = bt_status['enabled']
        
        return [
            IconMenuEntry(
                key="Info", label=status_label, icon_name="bluetooth",
                enabled=True, selectable=False, height_ratio=1.5, icon_size=36,
                layout="vertical", font_size=11, border_width=1
            ),
            IconMenuEntry(
                key="Names", label=advertised_label, icon_name="bluetooth",
                enabled=True, selectable=False, height_ratio=1.2, icon_size=24,
                layout="vertical", font_size=10, border_width=1
            ),
            IconMenuEntry(
                key="Toggle", label="Enabled" if is_enabled else "Disabled",
                icon_name="timer_checked" if is_enabled else "timer",
                enabled=True, selectable=True, height_ratio=0.8, layout="horizontal", font_size=14
            ),
        ]
    
    def handle_selection(result: MenuSelection):
        """Handle Bluetooth toggle."""
        if result.key == "Toggle":
            device_name = _args.device_name if _args else 'DGT PEGASUS'
            bt_status = bluetooth_status.get_bluetooth_status(
                device_name=device_name, ble_manager=ble_manager, rfcomm_connected=client_connected
            )
            if bt_status['enabled']:
                bluetooth_status.disable_bluetooth()
            else:
                if bluetooth_status.enable_bluetooth():
                    board.beep(board.SOUND_GENERAL, event_type='key_press')
        return None  # Continue loop
    
    return _menu_manager.run_menu_loop(build_entries, handle_selection, initial_index=2)


def _handle_sound_settings():
    """Handle sound settings submenu.
    
    Shows individual sound settings with toggle checkboxes:
    - Piece events (beep on piece lift/place)
    - Game events (beep on check, checkmate, etc.)
    - Errors (beep on invalid moves)
    - Key press (beep on button press)
    - Master enable (global on/off)
    
    Uses the sound_settings module for settings management.
    """
    from DGTCentaurMods.epaper import sound_settings
    
    def build_entries():
        """Build sound settings menu entries."""
        settings = sound_settings.get_sound_settings()
        return [
            IconMenuEntry(
                key="piece_event", label="Piece Events",
                icon_name="timer_checked" if settings['piece_event'] else "timer",
                enabled=True, selectable=True, height_ratio=0.8, layout="horizontal", font_size=14
            ),
            IconMenuEntry(
                key="game_event", label="Game Events",
                icon_name="timer_checked" if settings['game_event'] else "timer",
                enabled=True, selectable=True, height_ratio=0.8, layout="horizontal", font_size=14
            ),
            IconMenuEntry(
                key="error", label="Errors",
                icon_name="timer_checked" if settings['error'] else "timer",
                enabled=True, selectable=True, height_ratio=0.8, layout="horizontal", font_size=14
            ),
            IconMenuEntry(
                key="key_press", label="Key Press",
                icon_name="timer_checked" if settings['key_press'] else "timer",
                enabled=True, selectable=True, height_ratio=0.8, layout="horizontal", font_size=14
            ),
            IconMenuEntry(
                key="enabled", label="Sound Enabled",
                icon_name="timer_checked" if settings['enabled'] else "timer",
                enabled=True, selectable=True, height_ratio=0.8, layout="horizontal", font_size=14, bold=True
            ),
        ]
    
    def handle_selection(result: MenuSelection):
        """Handle sound setting toggle."""
        if result.key in sound_settings.SOUND_SETTINGS:
            new_value = sound_settings.toggle_sound_setting(result.key)
            if new_value and result.key == 'enabled':
                # Play beep to confirm sound is enabled
                board.beep(board.SOUND_GENERAL)
        return None  # Continue loop
    
    return _menu_manager.run_menu_loop(build_entries, handle_selection, initial_index=4)


def _handle_system_menu():
    """Handle system submenu (display, sound, WiFi, Bluetooth, sleep timer, reset, shutdown, reboot)."""
    
    def handle_selection(result: MenuSelection):
        """Handle system menu selection."""
        # Route to submenus - propagate break results
        # Use is_break_result() since some handlers return strings, some return MenuSelection
        if result.key == "Display":
            sub_result = _handle_display_settings()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Sound":
            sub_result = _handle_sound_settings()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "AnalysisMode":
            # Toggle analysis mode
            _game_settings['analysis_mode'] = not _game_settings['analysis_mode']
            _save_game_setting('analysis_mode', _game_settings['analysis_mode'])
            log.info(f"[Settings] Analysis mode set to {_game_settings['analysis_mode']}")
            # Menu will refresh with updated checkbox
            return None
        elif result.key == "WiFi":
            sub_result = _handle_wifi_settings()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Bluetooth":
            sub_result = _handle_bluetooth_settings()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Accounts":
            sub_result = _handle_accounts_menu()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Inactivity":
            sub_result = _handle_inactivity_timeout()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "ResetSettings":
            sub_result = _handle_reset_settings()
            if is_break_result(sub_result):
                return sub_result
        elif result.key == "Shutdown":
            _shutdown("Shutdown")
            return result  # Exit after shutdown
        elif result.key == "Reboot":
            # LED cascade pattern for reboot
            try:
                for i in range(0, 8):
                    board.led(i, repeat=0)
                    time.sleep(0.2)
            except Exception:
                pass
            _shutdown("Rebooting", reboot=True)
            return result  # Exit after reboot
        return None  # Continue loop
    
    return _menu_manager.run_menu_loop(create_system_entries, handle_selection)


def _handle_inactivity_timeout():
    """Handle inactivity timeout setting submenu.

    The currently active timeout option displays a timer icon with a checkmark
    overlay to indicate selection. Other options show a plain timer icon.
    
    This is a one-shot selection menu - select a timeout and return.
    """
    # Available timeout options in minutes (0 = disabled)
    timeout_options = [
        (0, "Disabled"),
        (5, "5 min"),
        (10, "10 min"),
        (15, "15 min"),
        (30, "30 min"),
        (60, "1 hour"),
    ]

    current_timeout = board.get_inactivity_timeout()

    entries = []
    for minutes, label in timeout_options:
        seconds = minutes * 60
        is_current = seconds == current_timeout
        icon = "timer_checked" if is_current else "timer"
        entries.append(IconMenuEntry(key=str(seconds), label=label, icon_name=icon, enabled=True))

    result = _menu_manager.show_menu(entries)

    if result.is_break:
        return result
    
    if not result.is_exit():
        try:
            new_timeout = int(result.key)
            board.set_inactivity_timeout(new_timeout)
            log.info(f"[Settings] Inactivity timeout set to {new_timeout}s")
        except ValueError:
            pass
    
    return result


def _mask_token(token: str) -> str:
    """Mask a token for display, showing only first and last few characters.
    
    Args:
        token: The token to mask
        
    Returns:
        Masked token string (e.g., "lip_ab...xy" or "Not set")
    """
    if not token:
        return "Not set"
    if len(token) <= 8:
        return token[:2] + "..." + token[-2:] if len(token) > 4 else "****"
    return token[:6] + "..." + token[-4:]


def _handle_accounts_menu():
    """Handle Accounts submenu for online service credentials.
    
    Shows account settings for online services like Lichess.
    Each entry displays the current credential status (masked).
    """
    from DGTCentaurMods.board import centaur
    
    def build_entries():
        """Build accounts menu entries with current status."""
        token = centaur.get_lichess_api()
        masked = _mask_token(token)
        
        return [
            IconMenuEntry(
                key="Lichess",
                label=f"Lichess\n{masked}",
                icon_name="lichess",
                enabled=True,
                font_size=12,
                max_height=47  # ~1/6 of available screen height (280px)
            ),
        ]
    
    def handle_selection(result: MenuSelection):
        """Handle accounts menu selection."""
        if result.key == "Lichess":
            sub_result = _handle_lichess_token()
            if is_break_result(sub_result):
                return sub_result
        return None  # Continue loop
    
    return _menu_manager.run_menu_loop(build_entries, handle_selection)


def _handle_lichess_token():
    """Handle Lichess API token entry using keyboard widget.
    
    Shows the keyboard widget for entering/editing the Lichess API token.
    The token is saved immediately when confirmed (no restart required).
    
    Returns:
        MenuSelection or result indicating success/cancel
    """
    global _active_keyboard_widget
    from DGTCentaurMods.board import centaur
    
    log.info("[Accounts] Opening keyboard for Lichess token entry")
    
    # Clear display and show keyboard widget
    board.display_manager.clear_widgets(addStatusBar=False)
    
    # Create keyboard widget with current token as initial text
    current_token = centaur.get_lichess_api()
    keyboard = KeyboardWidget(title="Lichess Token", max_length=64)
    # Pre-fill with current token if exists (user can edit or clear)
    keyboard.text = current_token if current_token else ""
    
    _active_keyboard_widget = keyboard
    
    # Add widget to display
    promise = board.display_manager.add_widget(keyboard)
    if promise:
        try:
            promise.result(timeout=5.0)
        except Exception as e:
            log.warning(f"[Accounts] Keyboard display timeout: {e}")
    
    try:
        # Wait for input (blocking)
        result = keyboard.wait_for_input(timeout=300.0)
        
        if result is not None:
            # User confirmed - save the token
            centaur.set_lichess_api(result)
            log.info(f"[Accounts] Lichess token saved ({len(result)} chars)")
            board.beep(board.SOUND_GENERAL)
        else:
            log.info("[Accounts] Lichess token entry cancelled")
        
        return result
    finally:
        # Clear keyboard widget reference
        _active_keyboard_widget = None


def _shutdown(message: str, reboot: bool = False):
    """Shutdown the system with a message displayed on screen.
    
    Args:
        message: Message to display on shutdown splash
        reboot: If True, reboot instead of shutdown
    """
    board.display_manager.clear_widgets(addStatusBar=False)
    promise = board.display_manager.add_widget(SplashScreen(message=message, leave_room_for_status_bar=False))
    if promise:
        try:
            promise.result(timeout=10.0)
        except Exception:
            pass
    
    reason = f"User selected '{message}' from menu"
    board.shutdown(reboot=reboot, reason=reason)


def _run_centaur():
    """Launch the original DGT Centaur software.
    
    This hands over control to the Centaur software and exits.
    """
    # Show loading screen (full screen, no status bar)
    board.display_manager.clear_widgets(addStatusBar=False)
    promise = board.display_manager.add_widget(SplashScreen(message="Loading", leave_room_for_status_bar=False))
    if promise:
        try:
            promise.result(timeout=10.0)
        except Exception:
            pass
    
    # Pause events and cleanup
    board.pauseEvents()
    board.cleanup(leds_off=True)
    time.sleep(1)
    
    if os.path.exists(CENTAUR_SOFTWARE):
        # Ensure file is executable
        try:
            os.chmod(CENTAUR_SOFTWARE, 0o755)
        except Exception as e:
            log.warning(f"Could not set execute permissions on centaur: {e}")
        
        # Change to centaur directory and run
        os.chdir("/home/pi/centaur")
        os.system("sudo ./centaur")
    else:
        log.error(f"Centaur executable not found at {CENTAUR_SOFTWARE}")
        return False
    
    # Once Centaur starts, we cannot return - stop the service and exit
    time.sleep(3)
    os.system("sudo systemctl stop DGTCentaurMods.service")
    sys.exit()


# ============================================================================
# BLE Callbacks for BleManager
# ============================================================================

def _on_ble_data_received(data: bytes, client_type: str):
    """Handle data received from BLE client.
    
    Routes data to ConnectionManager which handles queuing if ProtocolManager is not
    yet ready (e.g., during menu -> game transition).
    
    Args:
        data: Raw bytes received from BLE client
        client_type: Type of client ('millennium', 'pegasus', 'chessnut')
    """
    _connection_manager.receive_data(data, client_type)


def _on_ble_connected(client_type: str):
    """Handle BLE client connection.
    
    Always transitions to game mode when a BLE client connects:
    - If in menu/settings mode: cancels menu and starts game
    - If between menus: starts game directly via flag
    - If in game mode: shows confirmation dialog to abandon current game or cancel
    
    Args:
        client_type: Type of client ('millennium', 'pegasus', 'chessnut')
    """
    global protocol_manager, app_state, _menu_manager, _pending_ble_client_type
    
    log.info(f"[BLE] Client connected: {client_type}")
    
    # Case 1: Already in game mode - show confirmation dialog
    if app_state == AppState.GAME and protocol_manager is not None:
        log.info("[BLE] Client connected while in game - showing confirmation dialog")
        _show_ble_connection_confirm(client_type)
        return
    
    # Case 2: In menu or settings mode with active menu widget - cancel menu to trigger game start
    if (app_state == AppState.MENU or app_state == AppState.SETTINGS) and _menu_manager.active_widget is not None:
        log.info(f"[BLE] Client connected while in {app_state.name} - cancelling menu to start game")
        _menu_manager.cancel_selection("CLIENT_CONNECTED")
        return  # ProtocolManager will be notified after game mode starts
    
    # Case 3: In menu/settings mode but between menus (no active widget) - set flag for main loop
    if app_state == AppState.MENU or app_state == AppState.SETTINGS:
        log.info(f"[BLE] Client connected between menus ({app_state.name}) - setting flag for game start")
        _pending_ble_client_type = client_type
        return
    
    # Case 4: Other states - notify game handler if available
    if protocol_manager:
        protocol_manager.on_app_connected()


def _show_ble_connection_confirm(client_type: str):
    """Show confirmation dialog when BLE client connects during active game.
    
    Presents options to abandon current game and start new one, or cancel.
    
    Args:
        client_type: Type of BLE client that connected
    """
    global display_manager
    
    def _on_confirm_result(result: str):
        """Handle confirmation dialog result."""
        global protocol_manager, app_state
        
        if result == "new_game":
            log.info("[BLE] User chose to abandon game and start new one")
            # Clean up current game and start new one
            _cleanup_game()
            _start_game_mode()
            if protocol_manager:
                protocol_manager.on_app_connected()
        else:
            # Cancel - keep current game
            log.info("[BLE] User cancelled - keeping current game")
            if protocol_manager:
                protocol_manager.on_app_connected()
    
    # Show confirmation menu using display_manager
    if display_manager is not None:
        from DGTCentaurMods.epaper.icon_menu import IconMenuEntry as _IconMenuEntry
        from DGTCentaurMods.epaper.icon_menu import IconMenuWidget as _IconMenuWidget
        
        entries = [
            _IconMenuEntry(key="new_game", label="New Game\n(abandon)", icon_name="play"),
            _IconMenuEntry(key="cancel", label="Cancel", icon_name="cancel"),
        ]
        
        confirm_menu = _IconMenuWidget(
            x=0, y=0, width=128, height=296,
            entries=entries,
            selected_index=1  # Default to Cancel
        )
        
        display_manager._menu_result_callback = _on_confirm_result
        display_manager._current_menu = confirm_menu
        display_manager._menu_active = True
        
        # Wait for selection in a background thread
        def _wait_for_selection():
            result = confirm_menu.wait_for_selection(initial_index=1)
            display_manager._menu_active = False
            display_manager._current_menu = None
            if display_manager._menu_result_callback:
                display_manager._menu_result_callback(result)
        
        import threading
        wait_thread = threading.Thread(target=_wait_for_selection, daemon=True)
        wait_thread.start()


def _on_ble_disconnected():
    """Handle BLE client disconnection.
    
    Notifies ProtocolManager that the app has disconnected.
    """
    global protocol_manager
    
    log.info("[BLE] Client disconnected")
    if protocol_manager:
        protocol_manager.on_app_disconnected()

# ============================================================================
# sendMessage callback for ProtocolManager
# ============================================================================

def sendMessage(data, message_type=None):
    """Send a message via BLE or BT classic.
    
    Routes data to the appropriate transport based on current connection state:
    - BLE: Uses BleManager.send_notification() which routes to correct protocol
    - RFCOMM: Direct socket send
    
    Args:
        data: Message data bytes (already formatted with messageType, length, payload)
        message_type: Optional message type hint (currently unused, routing is automatic)
    """
    global _last_message, relay_mode, ble_manager, client_connected, client_sock

    tosend = bytearray(data)
    _last_message = tosend
    log.info(f"[sendMessage] tosend={' '.join(f'{b:02x}' for b in tosend)}")
    
    # In relay mode, messages are forwarded to the relay target, so don't send back to client
    if relay_mode:
        log.debug(f"[sendMessage] Relay mode enabled - not sending to client")
        return
    
    # Send via BLE if connected (BleManager handles protocol routing)
    if ble_manager is not None and ble_manager.connected:
        try:
            log.info(f"[sendMessage] Sending {len(tosend)} bytes via BLE ({ble_manager.client_type})")
            ble_manager.send_notification(bytes(tosend))
        except Exception as e:
            log.error(f"[sendMessage] Error sending via BLE: {e}")
    
    # Send via BT classic if connected
    if client_connected and client_sock is not None:
        try:
            client_sock.send(bytes(tosend))
        except Exception as e:
            log.error(f"[sendMessage] Error sending via BT classic: {e}")


# ============================================================================
# RFCOMM Client Reader
# ============================================================================

def client_reader():
    """Read data from RFCOMM client.
    
    Processes data through ProtocolManager and optionally forwards to relay target.
    """
    global running, client_sock, client_connected, protocol_manager, relay_mode, relay_manager
    
    log.info("Starting Client reader thread")
    try:
        while running and not kill:
            try:
                if not client_connected or client_sock is None:
                    time.sleep(0.1)
                    continue
                
                data = client_sock.recv(1024)
                if len(data) == 0:
                    log.info("RFCOMM client disconnected")
                    client_connected = False
                    protocol_manager.on_app_disconnected()
                    break
                
                # Route through ConnectionManager (handles queuing and relay)
                _connection_manager.receive_data(bytes(data), "rfcomm")
                    
            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error: {e}")
                client_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error: {e}")
                break
    except Exception as e:
        log.error(f"Thread error: {e}")
    finally:
        log.info("Client reader thread stopped")
        client_connected = False


_cleanup_done = False  # Guard against running cleanup twice


def cleanup_and_exit(reason: str = "Normal exit"):
    """Clean up connections and resources, then exit the process.
    
    Properly stops all threads and closes all resources before exiting.
    This includes:
    - RFCOMM manager pairing thread
    - Relay manager (shadow target connection)
    - Game handler and its game manager thread
    - Display manager (analysis engine and widgets)
    - Board events and serial connection
    - Sockets and BLE mainloop
    
    Args:
        reason: Description of why the exit is happening (logged for debugging)
    """
    global kill, running, client_sock, server_sock, client_connected, mainloop
    global protocol_manager, display_manager, rfcomm_manager, ble_manager, relay_manager
    global _cleanup_done
    
    # Guard against running cleanup twice (signal handler + finally block)
    if _cleanup_done:
        log.debug(f"Cleanup already done, skipping: {reason}")
        return
    _cleanup_done = True
    
    try:
        log.info(f"Exiting: {reason}")
        kill = 1
        running = False
        
        # Skip splash screen on exit - creating widgets slows shutdown
        
        # Stop RFCOMM manager pairing thread
        if rfcomm_manager is not None:
            try:
                rfcomm_manager.stop_pairing_thread()
                log.debug("RFCOMM manager pairing thread stopped")
            except Exception as e:
                log.debug(f"Error stopping rfcomm_manager: {e}")
        
        # Stop relay manager (shadow target connection)
        if relay_manager is not None:
            try:
                relay_manager.stop()
                log.debug("Relay manager stopped")
            except Exception as e:
                log.debug(f"Error stopping relay_manager: {e}")
        
        # Clean up game handler (stops game manager thread and closes standalone engine)
        if protocol_manager is not None:
            try:
                protocol_manager.cleanup()
            except Exception as e:
                log.debug(f"Error cleaning up game handler: {e}")
        
        # Clean up display manager (analysis engine and widgets)
        # Pass for_shutdown=True to skip creating new widgets
        if display_manager is not None:
            try:
                display_manager.cleanup(for_shutdown=True)
                log.debug("Display manager cleaned up")
            except Exception as e:
                log.debug(f"Error cleaning up display manager: {e}")
        
        # Pause board events
        try:
            board.pauseEvents()
        except Exception as e:
            log.debug(f"Error pausing events: {e}")
        
        # Clean up board
        try:
            board.cleanup(leds_off=True)
        except Exception as e:
            log.debug(f"Error cleaning up board: {e}")
        
        if client_sock:
            try:
                client_sock.close()
            except:
                pass
        
        if server_sock:
            try:
                server_sock.close()
            except:
                pass
        
        # Stop BLE manager
        if ble_manager is not None:
            try:
                ble_manager.stop()
                log.debug("BLE manager stopped")
            except Exception as e:
                log.debug(f"Error stopping BLE manager: {e}")
        
        if mainloop:
            try:
                mainloop.quit()
            except:
                pass
        
        client_connected = False
        
        log.info("Cleanup completed")
    except Exception as e:
        log.error(f"Error in cleanup: {e}")
    
    # Exit the process using sys.exit() which allows cleanup handlers to run.
    # Use a background thread with timeout to force exit if sys.exit() hangs.
    log.info("Attempting graceful exit with sys.exit()")
    
    def force_exit_after_timeout():
        """Force exit if sys.exit() doesn't complete in time."""
        time.sleep(3.0)  # Give sys.exit() 3 seconds to complete
        log.warning("Graceful exit timed out, forcing exit with os._exit()")
        os._exit(0)
    
    # Start watchdog thread to force exit if needed
    watchdog = threading.Thread(target=force_exit_after_timeout, daemon=True)
    watchdog.start()
    
    # Attempt graceful exit
    sys.exit(0)


def signal_handler(signum, frame):
    """Handle termination signals"""
    cleanup_and_exit(f"Received signal {signum}")


# Counter for unhandled key events - used to detect broken state and recover
_unhandled_key_count = 0
_UNHANDLED_KEY_THRESHOLD = 5  # After this many unhandled keys, force recovery to main menu


def _reset_unhandled_key_count():
    """Reset the unhandled key counter after a successful key handling."""
    global _unhandled_key_count
    _unhandled_key_count = 0


def _handle_unhandled_key(key_id, reason: str):
    """Handle an unhandled key event - log error and potentially recover.
    
    If too many keys fall through without being handled, the app is likely in
    a broken state (e.g., menu displayed but no active widget). Force recovery
    by cleaning up and returning to the main menu.
    
    Args:
        key_id: The key that was not handled
        reason: Description of why the key was not handled
    """
    global _unhandled_key_count, app_state, protocol_manager, display_manager
    
    _unhandled_key_count += 1
    log.error(f"[App] UNHANDLED KEY: {key_id}, reason: {reason}, "
              f"app_state={app_state}, count={_unhandled_key_count}/{_UNHANDLED_KEY_THRESHOLD}")
    
    if _unhandled_key_count >= _UNHANDLED_KEY_THRESHOLD:
        log.error(f"[App] Too many unhandled keys ({_unhandled_key_count}) - forcing recovery to main menu")
        _unhandled_key_count = 0
        
        # Force cleanup and return to menu
        try:
            _cleanup_game()
        except Exception as e:
            log.error(f"[App] Error during recovery cleanup: {e}")
        
        # Force app_state to MENU so main loop will show the menu
        app_state = AppState.MENU
        
        # Beep to indicate recovery
        try:
            board.beep(board.SOUND_GENERAL, event_type='system')
        except Exception:
            pass


def key_callback(key_id):
    """Handle key press events from the board.
    
    Behavior depends on current app state:
    - MENU: Keys are routed to the active menu widget
    - GAME: GameManager handles most keys, this receives passthrough
    
    This callback receives:
    - BACK: In game mode (no game or after resign/draw), returns to menu
    - HELP: Toggle game analysis widget visibility (game mode only)
    - LONG_PLAY: Shutdown system
    
    If keys fall through without being handled, an error is logged. After
    too many unhandled keys (indicating a broken state), the app forces
    recovery by returning to the main menu.
    """
    global running, kill, display_manager, app_state, _menu_manager, _active_keyboard_widget
    
    log.info(f"[App] Key event received: {key_id}, app_state={app_state}")
    
    # Always handle LONG_PLAY for shutdown
    if key_id == board.Key.LONG_PLAY:
        log.info("[App] LONG_PLAY key event received")
        running = False
        kill = 1
        board.shutdown(reason="LONG_PLAY key event from universal.py")
        _reset_unhandled_key_count()
        return
    
    # Priority 1: Active keyboard widget gets key events
    if _active_keyboard_widget is not None:
        handled = _active_keyboard_widget.handle_key(key_id)
        if handled:
            _reset_unhandled_key_count()
            return
    
    # Route based on app state
    if app_state == AppState.MENU or app_state == AppState.SETTINGS:
        # Check if menu is loading - queue keys for replay after load completes
        if _menu_manager is not None and _menu_manager.is_loading:
            if _menu_manager.queue_key(key_id):
                _reset_unhandled_key_count()
                return
        
        # Route to active menu widget via MenuManager
        if _menu_manager is not None and _menu_manager.active_widget is not None:
            handled = _menu_manager.active_widget.handle_key(key_id)
            if handled:
                _reset_unhandled_key_count()
                return
        
        # Key not handled in MENU/SETTINGS - this should not happen
        _handle_unhandled_key(key_id, f"No active menu widget in {app_state.name}")
        return
    
    elif app_state == AppState.GAME:
        # Priority: DisplayManager menu (resign/draw, promotion) > app keys > game
        if display_manager and display_manager.is_menu_active():
            display_manager.handle_key(key_id)
            _reset_unhandled_key_count()
            return
        
        # Handle app-level keys
        if key_id == board.Key.HELP:
            # Show move hint (best move from analysis engine)
            if display_manager and protocol_manager and protocol_manager.game_manager:
                gm = protocol_manager.game_manager
                hint_move = display_manager.get_hint_move(gm.chess_board)
                if hint_move:
                    # Show hint on display widget and LEDs
                    display_manager.show_hint(hint_move)
                    log.info(f"[App] Hint: {hint_move.uci()}")
                else:
                    log.info("[App] No hint available (analysis engine not ready)")
            _reset_unhandled_key_count()
            return
        
        if key_id == board.Key.LONG_HELP:
            # Long press HELP: Show display settings menu
            _handle_display_menu()
            # Apply changes by reinitializing widgets
            if display_manager:
                display_manager._init_widgets()
            _reset_unhandled_key_count()
            return
        
        # Forward other keys to protocol_manager -> game_manager
        if protocol_manager:
            protocol_manager.receive_key(key_id)
            _reset_unhandled_key_count()
            
            # Check if GameManager wants us to exit:
            # - BACK with no game in progress (no moves made)
            # - BACK after game over (checkmate, stalemate, etc.)
            if key_id == board.Key.BACK:
                if protocol_manager.is_game_over():
                    log.info("[App] BACK after game over - returning to menu")
                    _return_to_menu("Game over - BACK pressed")
                elif not protocol_manager.is_game_in_progress():
                    log.info("[App] BACK with no game - returning to menu")
                    _return_to_menu("BACK pressed")
            return
        
        # No protocol_manager in GAME mode - should not happen
        _handle_unhandled_key(key_id, "No protocol_manager in GAME mode")
        return
    
    # Unknown app_state or fell through all handlers
    _handle_unhandled_key(key_id, f"Unknown app_state or no handler: {app_state}")


# Pending piece events for menu -> game transition
# Queue of (piece_event, field, time_in_seconds) tuples
_pending_piece_events = []

def field_callback(piece_event, field, time_in_seconds):
    """Handle field events (piece lift/place) from the board.
    
    Routes field events based on priority:
    1. Active keyboard widget (for text input like WiFi password)
    2. Menu mode with piece lift: Start game mode (piece move starts game)
    3. Game mode: Forward to protocol_manager -> game_manager for piece detection
    
    Args:
        piece_event: 0 = lift, 1 = place
        field: Board field index (0-63)
        time_in_seconds: Event timestamp
    """
    global app_state, protocol_manager, _active_keyboard_widget, _menu_manager, _pending_piece_events

    # Priority 1: Active keyboard gets field events
    if _active_keyboard_widget is not None:
        # Convert piece_event to presence: 1 = place = present, 0 = lift = not present
        piece_present = (piece_event == 1)
        _active_keyboard_widget.handle_field_event(field, piece_present)
        return
    
    # Priority 2: Menu/Settings mode - piece events trigger game start
    # Queue events if:
    # - Menu is active (first event triggers game start), OR
    # - Game start is pending (events already queued, waiting for main thread to start game)
    active_widget = _menu_manager.active_widget if _menu_manager else None
    if app_state in (AppState.MENU, AppState.SETTINGS):
        if active_widget is not None or len(_pending_piece_events) > 0:
            # Queue the piece event to forward after game mode starts
            # Multiple events may arrive before game mode is ready (e.g., LIFT then PLACE)
            _pending_piece_events.append((piece_event, field, time_in_seconds))
            log.info(f"[App] Piece event in {app_state.name} - queued for game (field={field}, event={piece_event}, queue_size={len(_pending_piece_events)}, menu_active={active_widget is not None})")
            # Only trigger game start on first event (avoid multiple cancel calls)
            if len(_pending_piece_events) == 1 and active_widget is not None:
                log.info("[App] Cancelling menu selection with PIECE_MOVED")
                _menu_manager.cancel_selection("PIECE_MOVED")
            elif active_widget is None:
                log.info("[App] Menu widget is None, events will be processed on next menu loop iteration")
            return
    
    # Priority 3: Game mode
    if app_state == AppState.GAME:
        if protocol_manager:
            protocol_manager.receive_field(piece_event, field, time_in_seconds)
        else:
            # Game handler not yet created - queue event for when it's ready
            _pending_piece_events.append((piece_event, field, time_in_seconds))
            log.info(f"[App] Game handler not ready, queuing event (field={field}, event={piece_event}, queue_size={len(_pending_piece_events)})")


def main():
    """Main entry point.
    
    Initializes the app, shows the main menu, and handles menu selections.
    BLE/RFCOMM connections can trigger auto-transition to game mode.
    """
    global server_sock, client_sock, client_connected, running, kill
    global mainloop, relay_mode, protocol_manager, relay_manager, app_state, _args
    global _pending_piece_events, _return_to_positions_menu, _switch_to_normal_game, _menu_manager
    
    parser = argparse.ArgumentParser(description="DGT Centaur Universal")
    parser.add_argument("--local-name", type=str, default="MILLENNIUM CHESS",
                       help="Local name for BLE advertisement")
    parser.add_argument("--shadow-target", type=str, default="MILLENNIUM CHESS",
                       help="Name of the target device to connect to in relay mode")
    parser.add_argument("--port", type=int, default=None,
                       help="RFCOMM port for server (default: auto-assign)")
    parser.add_argument("--device-name", type=str, default="MILLENNIUM CHESS",
                       help="Bluetooth device name")
    parser.add_argument("--relay", action="store_true",
                       help="Enable relay mode - connect to shadow_target and relay data")
    parser.add_argument("--no-ble", action="store_true",
                       help="Disable BLE (GATT) server")
    parser.add_argument("--no-rfcomm", action="store_true",
                       help="Disable RFCOMM server")
    parser.add_argument("--standalone-engine", type=str, default="stockfish_pi",
                       help="UCI engine for standalone play when no app connected (e.g., stockfish_pi, maia, ct800)")
    parser.add_argument("--engine-elo", type=str, default="Default",
                       help="ELO level from engine's .uci file (e.g., 1350, 1700, 2000, Default)")
    parser.add_argument("--player-color", type=str, default="white", choices=["white", "black", "random"],
                       help="Which color the human plays in standalone engine mode")
    
    args = parser.parse_args()
    _args = args  # Store globally for access in callbacks

    relay_mode = args.relay
    shadow_target_name = args.shadow_target
    
    # Load game settings from centaur.ini
    _load_game_settings()

    # Initialize the MenuManager singleton
    _menu_manager = MenuManager.get_instance()
    _menu_manager.set_board(board)
    _menu_manager.set_dimensions(DISPLAY_WIDTH, DISPLAY_HEIGHT, STATUS_BAR_HEIGHT)
    
    # Initialize the ConnectionManager singleton
    global _connection_manager
    _connection_manager = ConnectionManager()

    # Display is already initialized at module load time - use the early splash screen
    # The _startup_splash was created before board module was imported
    startup_splash = _startup_splash
    
    # Ensure display manager is available (was transferred from _early_display_manager)
    if board.display_manager is None:
        log.warning("Display manager not available, attempting late initialization...")
        promise = board.init_display()
        if promise:
            try:
                promise.result(timeout=10.0)
            except Exception as e:
                log.warning(f"Error initializing display: {e}")
        
        # Create splash screen if early init didn't work (full screen, no status bar)
        if startup_splash is None:
            board.display_manager.clear_widgets(addStatusBar=False)
            startup_splash = SplashScreen(message="Starting...", leave_room_for_status_bar=False)
            promise = board.display_manager.add_widget(startup_splash)
            if promise:
                try:
                    promise.result(timeout=5.0)
                except Exception:
                    pass
    
    log.info("=" * 60)
    log.info("DGT Centaur Universal Starting")
    log.info("=" * 60)
    log.info("")
    log.info("Configuration:")
    log.info(f"  Device name:       {args.device_name}")
    log.info(f"  BLE:               {'Disabled' if args.no_ble else 'Enabled'}")
    log.info(f"  RFCOMM:            {'Disabled' if args.no_rfcomm else 'Enabled'}")
    log.info(f"  Relay mode:        {'Enabled' if args.relay else 'Disabled'}")
    if args.relay:
        log.info(f"  Shadow target:     {args.shadow_target}")
    log.info("")
    log.info("=" * 60)
    
    # Subscribe to board events - universal.py is the single subscriber and routes events
    if startup_splash:
        startup_splash.set_message("Board events")
    board.subscribeEvents(key_callback, field_callback)  # Uses INACTIVITY_TIMEOUT_SECONDS default
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Setup BLE if enabled
    global ble_manager
    if not args.no_ble:
        if startup_splash:
            startup_splash.set_message("Bluetooth LE")
        log.info("Initializing BLE manager...")
        ble_manager = BleManager(
            device_name=args.device_name,
            on_data_received=_on_ble_data_received,
            on_connected=_on_ble_connected,
            on_disconnected=_on_ble_disconnected,
            relay_mode=relay_mode
        )
        
        # Initialize D-Bus mainloop for BleManager
        mainloop = GLib.MainLoop()
        
        if not ble_manager.start(mainloop):
            log.error("Failed to start BLE manager")
            sys.exit(1)
        
        log.info("BLE manager started successfully")
        
        # Start GLib mainloop in background thread
        def ble_mainloop():
            try:
                mainloop.run()
            except Exception as e:
                log.error(f"Error in BLE mainloop: {e}")
        
        ble_thread = threading.Thread(target=ble_mainloop, daemon=True)
        ble_thread.start()
        log.info("BLE mainloop thread started")
    
    # Setup RFCOMM if enabled (runs asynchronously to improve startup time)
    global rfcomm_manager
    if not args.no_rfcomm:
        def rfcomm_setup_and_accept():
            """Initialize RFCOMM and accept connections in background thread.
            
            Runs all RFCOMM setup (bluetoothctl commands, socket creation) in background
            to avoid blocking startup. Once setup is complete, accepts connections.
            """
            global rfcomm_manager, server_sock, client_sock, client_connected
            global app_state, _menu_manager, _pending_ble_client_type
            
            log.info("[RFCOMM] Starting background initialization...")
            
            # Kill any existing rfcomm processes
            os.system('sudo service rfcomm stop 2>/dev/null')
            time.sleep(0.5)
            
            for p in psutil.process_iter(attrs=['pid', 'name']):
                if str(p.info["name"]) == "rfcomm":
                    try:
                        p.kill()
                    except:
                        pass
            
            time.sleep(0.3)
            
            # Create RFCOMM manager for pairing
            rfcomm_manager = RfcommManager(device_name=args.device_name)
            rfcomm_manager.enable_bluetooth()
            rfcomm_manager.set_device_name(args.device_name)
            rfcomm_manager.start_pairing_thread()
            
            time.sleep(0.5)
            
            # Initialize server socket
            log.info("[RFCOMM] Setting up server socket...")
            server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            server_sock.bind(("", args.port if args.port else bluetooth.PORT_ANY))
            server_sock.settimeout(0.5)
            server_sock.listen(1)
            port = server_sock.getsockname()[1]
            uuid = "94f39d29-7d6d-437d-973b-fba39e49d4ee"
            
            try:
                bluetooth.advertise_service(server_sock, args.device_name, service_id=uuid,
                                          service_classes=[uuid, bluetooth.SERIAL_PORT_CLASS],
                                          profiles=[bluetooth.SERIAL_PORT_PROFILE])
                log.info(f"[RFCOMM] Service '{args.device_name}' advertised on channel {port}")
            except Exception as e:
                log.error(f"[RFCOMM] Failed to advertise service: {e}")
            
            log.info("[RFCOMM] Initialization complete, accepting connections...")
            
            # Accept connections loop
            while running and not kill:
                try:
                    sock, client_info = server_sock.accept()
                    client_sock = sock
                    client_connected = True
                    log.info("=" * 60)
                    log.info("RFCOMM CLIENT CONNECTED")
                    log.info("=" * 60)
                    log.info(f"Client address: {client_info}")
                    
                    # Handle connection - same logic as BLE
                    if app_state == AppState.GAME and protocol_manager is not None:
                        # Already in game - show confirmation dialog
                        log.info("[RFCOMM] Client connected while in game - showing confirmation dialog")
                        _show_ble_connection_confirm("rfcomm")
                    elif (app_state == AppState.MENU or app_state == AppState.SETTINGS) and _menu_manager.active_widget is not None:
                        # In menu/settings with active widget - cancel to start game
                        log.info(f"[RFCOMM] Client connected while in {app_state.name} - transitioning to game")
                        _menu_manager.cancel_selection("CLIENT_CONNECTED")
                    elif app_state == AppState.MENU or app_state == AppState.SETTINGS:
                        # Between menus - set flag for main loop
                        log.info(f"[RFCOMM] Client connected between menus ({app_state.name}) - setting flag")
                        _pending_ble_client_type = "rfcomm"
                    elif protocol_manager:
                        protocol_manager.on_app_connected()
                    
                    # Start client reader thread
                    reader_thread = threading.Thread(target=client_reader, daemon=True)
                    reader_thread.start()
                    
                    # Wait for client to disconnect before accepting new connection
                    while client_connected and running and not kill:
                        time.sleep(0.5)
                    
                except bluetooth.BluetoothError:
                    time.sleep(0.1)
                except Exception as e:
                    if running:
                        log.error(f"[RFCOMM] Error accepting connection: {e}")
                    time.sleep(0.1)
        
        # Start RFCOMM setup in background thread (doesn't block startup)
        rfcomm_thread = threading.Thread(target=rfcomm_setup_and_accept, daemon=True)
        rfcomm_thread.start()
        log.info("[RFCOMM] Background thread started")
    
    # Connect to shadow target if relay mode
    if relay_mode:
        if startup_splash:
            startup_splash.set_message("Relay mode")
        log.info("=" * 60)
        log.info(f"RELAY MODE - Connecting to {shadow_target_name}")
        log.info("=" * 60)
        
        # Callback for data received from shadow target
        def _on_shadow_data(data: bytes):
            """Handle data received from shadow target."""
            # Compare with emulator if in compare mode
            if protocol_manager is not None and protocol_manager.compare_mode:
                match, emulator_response = protocol_manager.compare_with_shadow(data)
                if match is False:
                    log.error("[Relay] MISMATCH: Emulator response differs from shadow host")
                elif match is True:
                    log.info("[Relay] MATCH: Emulator response matches shadow host")
            
            # Forward to RFCOMM client if connected
            if client_connected and client_sock is not None:
                try:
                    client_sock.send(data)
                except Exception as e:
                    log.error(f"[Relay] Error sending to RFCOMM client: {e}")
            
            # Forward to BLE client if connected
            if ble_manager is not None and ble_manager.connected:
                ble_manager.send_notification(data)
        
        def _on_shadow_disconnected():
            """Handle shadow target disconnection."""
            log.warning("[Relay] Shadow target disconnected")
        
        # Create and start relay manager
        relay_manager = RelayManager(
            target_name=shadow_target_name,
            on_data_from_target=_on_shadow_data,
            on_disconnected=_on_shadow_disconnected
        )
        
        def connect_shadow():
            time.sleep(1)
            if relay_manager.connect():
                log.info(f"[Relay] {shadow_target_name} connection established")
            else:
                log.error(f"[Relay] Failed to connect to {shadow_target_name}")
                global kill
                kill = 1
        
        shadow_thread = threading.Thread(target=connect_shadow, daemon=True)
        shadow_thread.start()
        
        # Configure ConnectionManager for relay mode
        _connection_manager.set_relay_manager(relay_manager, relay_mode)
    
    log.info("")
    log.info("Ready for connections and user input")
    log.info(f"Device name: {args.device_name}")
    if not args.no_ble:
        log.info("  BLE: Ready for GATT connections")
    if not args.no_rfcomm:
        log.info("  RFCOMM: Initializing in background...")
    log.info("")
    
    # Check for incomplete game to resume
    incomplete_game = _get_incomplete_game()
    if incomplete_game:
        if startup_splash:
            startup_splash.set_message("Resuming game...")
            time.sleep(0.5)
        
        if _resume_game(incomplete_game):
            log.info("[App] Successfully resumed incomplete game")
            app_state = AppState.GAME
        else:
            log.warning("[App] Failed to resume game, showing menu")
            if startup_splash:
                startup_splash.set_message("Ready")
                time.sleep(0.3)
            app_state = AppState.MENU
    else:
        # Show ready message before menu
        if startup_splash:
            startup_splash.set_message("Ready")
            time.sleep(0.3)
        app_state = AppState.MENU
    
    # Check if Centaur software is available
    centaur_available = os.path.exists(CENTAUR_SOFTWARE)
    main_menu_last_selected = 0  # Track last selected index for returning from submenus
    
    try:
        while running and not kill:
            if app_state == AppState.MENU:
                # Check for pending BLE client connection (set when connection happens between menus)
                global _pending_ble_client_type
                if _pending_ble_client_type is not None:
                    log.info(f"[App] Pending BLE client connection detected ({_pending_ble_client_type}) - starting game mode")
                    _pending_ble_client_type = None
                    _start_game_mode()
                    if protocol_manager:
                        protocol_manager.on_app_connected()
                    continue  # Re-check app_state (now should be GAME)
                
                # Check for pending piece events before showing menu
                # These may have been queued while in a submenu
                if _pending_piece_events:
                    log.info(f"[App] Pending piece events detected ({len(_pending_piece_events)}) - starting game mode")
                    _start_game_mode()
                    while _pending_piece_events:
                        pe, field, ts = _pending_piece_events.pop(0)
                        log.info(f"[App] Forwarding piece event: field={field}, event={pe}")
                        if protocol_manager:
                            protocol_manager.receive_field(pe, field, ts)
                    if (ble_manager and ble_manager.connected) or client_connected:
                        if protocol_manager:
                            protocol_manager.on_app_connected()
                    continue  # Re-check app_state (now should be GAME)
                
                # Show main menu
                entries = create_main_menu_entries(centaur_available=centaur_available)
                result = _show_menu(entries, initial_index=main_menu_last_selected)
                
                # Update last_selected for when we return from a submenu
                main_menu_last_selected = find_entry_index(entries, result)
                
                log.info(f"[App] Main menu selection: {result}")
                
                if result == "BACK":
                    # Show idle screen and wait for TICK
                    board.beep(board.SOUND_POWER_OFF, event_type='key_press')
                    board.display_manager.clear_widgets()
                    promise = board.display_manager.add_widget(SplashScreen(message="Press [OK]"))
                    if promise:
                        try:
                            promise.result(timeout=10.0)
                        except Exception:
                            pass
                    # Wait for TICK to return to menu
                    board.wait_for_key_up(accept=board.Key.TICK)
                    continue
                
                elif result == "SHUTDOWN":
                    _shutdown("Shutdown")
                
                elif result == "Centaur":
                    _run_centaur()
                    # Note: _run_centaur() exits the process
                
                elif result == "Universal" or result == "CLIENT_CONNECTED" or result == "PIECE_MOVED":
                    # Start game mode
                    _start_game_mode()
                    
                    # Forward all pending piece events (may have accumulated during _start_game_mode)
                    # GameManager queues events if not ready and replays them when ready
                    # Keep forwarding until queue is empty (events may arrive during forwarding)
                    while _pending_piece_events:
                        pe, field, ts = _pending_piece_events.pop(0)
                        log.info(f"[App] Forwarding piece event: field={field}, event={pe}")
                        if protocol_manager:
                            protocol_manager.receive_field(pe, field, ts)
                    
                    # Notify ProtocolManager if client is already connected
                    if (ble_manager and ble_manager.connected) or client_connected:
                        if protocol_manager:
                            protocol_manager.on_app_connected()
                
                elif result == "Settings":
                    settings_result = _handle_settings()
                    # Check if a BLE client connected during settings
                    if is_break_result(settings_result):
                        _start_game_mode()
                        if protocol_manager:
                            protocol_manager.on_app_connected()
                    # After settings, continue to main menu
                
                elif result == "HELP":
                    # Could show about/help screen here
                    pass
            
            elif app_state == AppState.GAME:
                # Check if we need to switch from position game to normal game
                if _switch_to_normal_game:
                    _switch_to_normal_game = False
                    log.info("[App] Switching from position game to normal game")
                    _cleanup_game()
                    _start_game_mode(starting_fen=None, is_position_game=False)
                else:
                    # Stay in game mode - key_callback handles exit via _return_to_menu
                    time.sleep(0.5)
            
            elif app_state == AppState.SETTINGS:
                # Check if we need to return to positions menu (from position game back)
                if _return_to_positions_menu:
                    _return_to_positions_menu = False
                    # Return directly to the last selected position in the menu
                    position_result = _handle_positions_menu(return_to_last_position=True)
                    if is_break_result(position_result):
                        # BLE client connected during positions menu
                        _start_game_mode()
                        if protocol_manager:
                            protocol_manager.on_app_connected()
                    elif not position_result:
                        # User backed out of positions menu, show settings
                        settings_result = _handle_settings()
                        if is_break_result(settings_result):
                            _start_game_mode()
                            if protocol_manager:
                                protocol_manager.on_app_connected()
                else:
                    # Settings handled by _handle_settings loop
                    time.sleep(0.1)
                
    except KeyboardInterrupt:
        log.info("[App] Interrupted by Ctrl+C")
    except Exception as e:
        log.error(f"[App] Error in main loop: {e}")
    finally:
        cleanup_and_exit("Main loop ended")


if __name__ == "__main__":
    main()
