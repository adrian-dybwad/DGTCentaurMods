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

# Initialize display immediately
_early_display_manager: Optional[Manager] = None
_startup_splash: Optional[SplashScreen] = None

def _init_display_early():
    """Initialize display and show splash screen before board initialization."""
    global _early_display_manager, _startup_splash
    try:
        _early_display_manager = Manager()
        promise = _early_display_manager.initialize()
        if promise:
            promise.result(timeout=10.0)
        
        # Show splash screen immediately
        _early_display_manager.clear_widgets(addStatusBar=False)
        _startup_splash = SplashScreen(message="Starting...")
        promise = _early_display_manager.add_widget(_startup_splash)
        if promise:
            promise.result(timeout=5.0)
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
import bluetooth
from gi.repository import GLib
import chess
import chess.engine
import pathlib
from PIL import Image, ImageDraw, ImageFont

from DGTCentaurMods.rfcomm_manager import RfcommManager
from DGTCentaurMods.ble_manager import BleManager
from DGTCentaurMods.relay_manager import RelayManager
from DGTCentaurMods.game_handler import GameHandler
from DGTCentaurMods.display_manager import DisplayManager

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
game_handler = None  # GameHandler instance
display_manager = None  # DisplayManager for game UI widgets
_last_message = None  # Last message sent via sendMessage
relay_mode = False  # Whether relay mode is enabled (connects to relay target)
mainloop = None  # GLib mainloop for BLE
rfcomm_manager = None  # RfcommManager for RFCOMM pairing
ble_manager = None  # BleManager for BLE GATT services
relay_manager = None  # RelayManager for shadow target connections

# Menu state
_active_menu_widget: Optional[IconMenuWidget] = None
_menu_selection_event = None  # Threading event for menu selection

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
}

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
        
        log.info(f"[Settings] Loaded: engine={_game_settings['engine']}, "
                 f"elo={_game_settings['elo']}, color={_game_settings['player_color']}")
    except Exception as e:
        log.warning(f"[Settings] Error loading game settings: {e}, using defaults")


def _save_game_setting(key: str, value: str):
    """Save a single game setting to centaur.ini.
    
    Args:
        key: Setting key (engine, elo, player_color)
        value: Setting value
    """
    global _game_settings
    
    try:
        from DGTCentaurMods.board.settings import Settings
        
        _game_settings[key] = value
        Settings.write(SETTINGS_SECTION, key, value)
        log.debug(f"[Settings] Saved {key}={value}")
    except Exception as e:
        log.warning(f"[Settings] Error saving {key}={value}: {e}")


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
        label="Universal",
        icon_name="universal",
        enabled=True,
        height_ratio=2.0,
        icon_size=72,
        layout="vertical",
        font_size=20  # Larger text for prominent button
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
    
    Uses current values from _game_settings for engine, elo, and color labels.
    Multi-line labels are used to show the setting name and current value.

    Returns:
        List of IconMenuEntry for settings menu
    """
    engine_label = f"Engine\n{_game_settings['engine']}"
    elo_label = f"ELO: {_game_settings['elo']}"
    color_label = f"Color: {_game_settings['player_color'].capitalize()}"
    
    return [
        IconMenuEntry(key="Engine", label=engine_label, icon_name="engine", enabled=True, font_size=14),
        IconMenuEntry(key="ELO", label=elo_label, icon_name="elo", enabled=True, font_size=14),
        IconMenuEntry(key="Color", label=color_label, icon_name="color", enabled=True, font_size=14),
        IconMenuEntry(key="Sound", label="Sound", icon_name="sound", enabled=True, font_size=14),
        IconMenuEntry(key="WiFi", label="WiFi", icon_name="wifi", enabled=True, font_size=14),
        IconMenuEntry(key="System", label="System", icon_name="system", enabled=True, font_size=14),
    ]


def create_system_entries() -> List[IconMenuEntry]:
    """Create entries for the system submenu (shutdown, reboot, inactivity timeout).

    Returns:
        List of IconMenuEntry for system menu
    """
    # Get current inactivity timeout for display
    timeout = board.get_inactivity_timeout()
    if timeout == 0:
        timeout_label = "Sleep Timer\nDisabled"
    else:
        timeout_label = f"Sleep Timer\n{timeout // 60} min"
    
    return [
        IconMenuEntry(key="Inactivity", label=timeout_label, icon_name="timer", enabled=True),
        IconMenuEntry(key="Shutdown", label="Shutdown", icon_name="shutdown", enabled=True),
        IconMenuEntry(key="Reboot", label="Reboot", icon_name="reboot", enabled=True),
    ]


def _show_menu(entries: List[IconMenuEntry]) -> str:
    """Display a menu and wait for selection.

    Args:
        entries: List of menu entry configurations to display

    Returns:
        Selected entry key, "BACK", "HELP", or "SHUTDOWN"
    """
    global _active_menu_widget

    # Clear existing widgets and add status bar
    board.display_manager.clear_widgets()

    # Create menu widget
    menu_widget = IconMenuWidget(
        x=0,
        y=STATUS_BAR_HEIGHT,
        width=DISPLAY_WIDTH,
        height=DISPLAY_HEIGHT - STATUS_BAR_HEIGHT,
        entries=entries,
        selected_index=0
    )

    # Register as active menu for key routing
    _active_menu_widget = menu_widget
    menu_widget.activate()

    # Add widget to display and wait for render
    promise = board.display_manager.add_widget(menu_widget)
    if promise:
        try:
            promise.result(timeout=5.0)
        except Exception as e:
            log.warning(f"[Menu] Error waiting for menu render: {e}")

    try:
        # Wait for selection using the widget's blocking method
        result = menu_widget.wait_for_selection(initial_index=0)
        return result
    finally:
        _active_menu_widget = None


def _start_game_mode():
    """Transition from menu to game mode.

    Initializes game handler and display manager, shows chess widgets.
    Uses settings from _game_settings (configurable via Settings menu).
    """
    global app_state, game_handler, display_manager, _game_settings

    log.info("[App] Transitioning to GAME mode")
    app_state = AppState.GAME
    
    # Get current game settings
    engine_name = _game_settings['engine']
    engine_elo = _game_settings['elo']
    player_color_setting = _game_settings['player_color']

    # Determine player color for standalone engine
    if player_color_setting == "random":
        player_color = chess.WHITE if random.randint(0, 1) == 0 else chess.BLACK
        log.info(f"[App] Random color selected: {'white' if player_color == chess.WHITE else 'black'}")
    else:
        player_color = chess.WHITE if player_color_setting == "white" else chess.BLACK

    # Get analysis engine path
    base_path = pathlib.Path(__file__).parent
    analysis_engine_path = str((base_path / "engines/ct800").resolve())

    # Create DisplayManager - handles all game widgets (chess board, analysis)
    display_manager = DisplayManager(
        flip_board=False,
        show_analysis=True,
        analysis_engine_path=analysis_engine_path,
        on_exit=lambda: _return_to_menu("Menu exit")
    )
    log.info("[App] DisplayManager initialized")

    # Display update callback for GameHandler
    def update_display(fen):
        """Update display manager with new position."""
        if display_manager:
            display_manager.update_position(fen)
            # Trigger analysis
            try:
                board_obj = chess.Board(fen)
                current_turn = "white" if board_obj.turn == chess.WHITE else "black"
                display_manager.analyze_position(board_obj, current_turn)
            except Exception as e:
                log.debug(f"Error triggering analysis: {e}")

    # Back menu result handler
    def _on_back_menu_result(result: str):
        """Handle result from back menu (resign/draw/cancel/exit)."""
        if result == "resign":
            game_handler.game_manager.handle_resign()
            _return_to_menu("Resigned")
        elif result == "draw":
            game_handler.game_manager.handle_draw()
            _return_to_menu("Draw")
        elif result == "exit":
            board.shutdown(reason="User selected 'exit' from game menu")
        # cancel is handled by DisplayManager (restores display)

    # Create GameHandler with user-configured settings
    # Note: Key and field events are routed through universal.py's callbacks
    game_handler = GameHandler(
        sendMessage_callback=sendMessage,
        client_type=None,
        compare_mode=relay_mode,
        standalone_engine_name=engine_name,
        player_color=player_color,
        engine_elo=engine_elo,
        display_update_callback=update_display
    )
    log.info(f"[App] GameHandler created: engine={engine_name}, elo={engine_elo}, color={player_color_setting}")
    
    # Wire up GameManager callbacks to DisplayManager
    game_handler.game_manager.on_promotion_needed = display_manager.show_promotion_menu
    game_handler.game_manager.on_back_pressed = lambda: display_manager.show_back_menu(_on_back_menu_result)
    
    # Wire up event callback to reset analysis on new game
    from DGTCentaurMods.game_manager import EVENT_NEW_GAME
    def _on_game_event(event):
        if event == EVENT_NEW_GAME:
            display_manager.reset_analysis()
    game_handler._external_event_callback = _on_game_event


def _return_to_menu(reason: str):
    """Return from game mode to menu mode.
    
    Cleans up game handler and display manager, shows main menu.
    
    Args:
        reason: Reason for returning to menu (for logging)
    """
    global app_state, game_handler, display_manager, _pending_piece_events
    
    log.info(f"[App] Returning to MENU: {reason}")
    
    # Clear any stale pending piece events from previous game
    _pending_piece_events.clear()
    
    # Clean up game handler
    if game_handler is not None:
        try:
            game_handler.cleanup()
        except Exception as e:
            log.debug(f"Error cleaning up game handler: {e}")
        game_handler = None
    
    # Clean up display manager
    if display_manager is not None:
        try:
            display_manager.cleanup()
        except Exception as e:
            log.debug(f"Error cleaning up display manager: {e}")
        display_manager = None
    
    app_state = AppState.MENU


def _handle_settings():
    """Handle the Settings submenu.
    
    Displays settings options and handles their selection.
    Includes game settings (Engine, ELO, Color) and system settings (Sound, Shutdown, Reboot).
    """
    global app_state, _game_settings
    from DGTCentaurMods.board import centaur
    
    app_state = AppState.SETTINGS
    
    while app_state == AppState.SETTINGS:
        entries = create_settings_entries()
        result = _show_menu(entries)
        
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
            if engine_result not in ["BACK", "SHUTDOWN", "HELP"]:
                old_engine = _game_settings['engine']
                _save_game_setting('engine', engine_result)
                log.info(f"[Settings] Engine changed: {old_engine} -> {engine_result}")
                # Reset ELO to Default when engine changes
                _save_game_setting('elo', 'Default')
                board.beep(board.SOUND_GENERAL)
        
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
            if elo_result not in ["BACK", "SHUTDOWN", "HELP"]:
                old_elo = _game_settings['elo']
                _save_game_setting('elo', elo_result)
                log.info(f"[Settings] ELO changed: {old_elo} -> {elo_result}")
                board.beep(board.SOUND_GENERAL)
        
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
            ]
            
            color_result = _show_menu(color_entries)
            if color_result in ["white", "black", "random"]:
                old_color = _game_settings['player_color']
                _save_game_setting('player_color', color_result)
                log.info(f"[Settings] Player color changed: {old_color} -> {color_result}")
                board.beep(board.SOUND_GENERAL)
        
        elif result == "Sound":
            # Sound toggle submenu
            sound_entries = [
                IconMenuEntry(key="On", label="On", icon_name="sound", enabled=True),
                IconMenuEntry(key="Off", label="Off", icon_name="cancel", enabled=True),
            ]
            sound_result = _show_menu(sound_entries)
            if sound_result == "On":
                centaur.set_sound("on")
                board.beep(board.SOUND_GENERAL)
            elif sound_result == "Off":
                centaur.set_sound("off")
        
        elif result == "WiFi":
            _handle_wifi_settings()
        
        elif result == "System":
            _handle_system_menu()


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
        # Show scanning message
        board.display_manager.clear_widgets(addStatusBar=False)
        promise = board.display_manager.add_widget(SplashScreen(message="Scanning..."))
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
        # Show connecting message
        board.display_manager.clear_widgets(addStatusBar=False)
        promise = board.display_manager.add_widget(SplashScreen(message="Connecting..."))
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
            board.beep(board.SOUND_GENERAL)
            return True
        else:
            log.error(f"[WiFi] Failed to connect: {result.stderr}")
            board.beep(board.SOUND_WRONG)
            return False
            
    except subprocess.TimeoutExpired:
        log.error("[WiFi] Connection timed out")
        board.beep(board.SOUND_WRONG)
        return False
    except Exception as e:
        log.error(f"[WiFi] Error connecting: {e}")
        board.beep(board.SOUND_WRONG)
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
    
    Shows WiFi status, allows scanning for networks, and connecting.
    """
    while True:
        # Get current status
        current_ssid, ip_address = _get_current_wifi_status()
        
        if current_ssid:
            status_label = f"Status\n{current_ssid}"
            if ip_address:
                status_label = f"Connected\n{ip_address}"
        else:
            status_label = "Status\nNot connected"
        
        wifi_entries = [
            IconMenuEntry(
                key="Scan", 
                label="Scan", 
                icon_name="wifi", 
                enabled=True,
                height_ratio=2.0,
                icon_size=48,
                layout="vertical",
                font_size=24
            ),
            IconMenuEntry(
                key="Enable", 
                label="Enable", 
                icon_name="wifi", 
                enabled=True,
                height_ratio=0.67,
                layout="horizontal",
                font_size=14
            ),
            IconMenuEntry(
                key="Disable", 
                label="Disable", 
                icon_name="cancel", 
                enabled=True,
                height_ratio=0.67,
                layout="horizontal",
                font_size=14
            ),
        ]
        
        wifi_result = _show_menu(wifi_entries)
        
        if wifi_result in ["BACK", "SHUTDOWN", "HELP"]:
            return
        
        if wifi_result == "Scan":
            _handle_wifi_scan()
        elif wifi_result == "Enable":
            try:
                import subprocess
                subprocess.run(['sudo', 'rfkill', 'unblock', 'wifi'], timeout=5)
                board.beep(board.SOUND_GENERAL)
                log.info("[Settings] WiFi enabled")
            except Exception as e:
                log.error(f"[Settings] Failed to enable WiFi: {e}")
        elif wifi_result == "Disable":
            try:
                import subprocess
                subprocess.run(['sudo', 'rfkill', 'block', 'wifi'], timeout=5)
                log.info("[Settings] WiFi disabled")
            except Exception as e:
                log.error(f"[Settings] Failed to disable WiFi: {e}")


def _handle_wifi_scan():
    """Handle WiFi network scanning and selection."""
    log.info("[WiFi] Starting network scan...")
    networks = _scan_wifi_networks()
    log.info(f"[WiFi] Scan complete, found {len(networks)} networks")

    if not networks:
        # Show no networks found message
        board.display_manager.clear_widgets(addStatusBar=False)
        promise = board.display_manager.add_widget(SplashScreen(message="No networks found"))
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
        # Signal strength determines icon
        signal = net['signal']
        if signal >= 70:
            icon_name = "wifi_strong"
        elif signal >= 40:
            icon_name = "wifi_medium"
        else:
            icon_name = "wifi_weak"

        # Truncate SSID if too long
        ssid_display = net['ssid'][:14] if len(net['ssid']) > 14 else net['ssid']
        label = f"{ssid_display}\n{signal}%"

        network_entries.append(
            IconMenuEntry(key=net['ssid'], label=label, icon_name=icon_name, enabled=True, font_size=14)
        )
        log.debug(f"[WiFi] Added network entry: {net['ssid']} ({signal}%)")

    log.info(f"[WiFi] Showing menu with {len(network_entries)} entries")
    network_result = _show_menu(network_entries)
    log.info(f"[WiFi] Menu result: {network_result}")
    
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


def _handle_system_menu():
    """Handle system submenu (shutdown, reboot, inactivity timeout)."""
    while True:
        system_entries = create_system_entries()
        system_result = _show_menu(system_entries)
        
        if system_result == "Inactivity":
            _handle_inactivity_timeout()
            # Loop back to system menu after changing timeout
        elif system_result == "Shutdown":
            _shutdown("Shutdown")
            return
        elif system_result == "Reboot":
            # LED cascade pattern for reboot
            try:
                for i in range(0, 8):
                    board.led(i, repeat=0)
                    time.sleep(0.2)
            except Exception:
                pass
            _shutdown("Rebooting", reboot=True)
            return
        else:
            # BACK or other - exit system menu
            return


def _handle_inactivity_timeout():
    """Handle inactivity timeout setting submenu."""
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
        # Mark current selection
        if seconds == current_timeout:
            display_label = f"[{label}]"
        else:
            display_label = label
        entries.append(IconMenuEntry(key=str(seconds), label=display_label, icon_name="timer", enabled=True))
    
    result = _show_menu(entries)
    
    if result not in ("BACK", "HELP", "SHUTDOWN"):
        try:
            new_timeout = int(result)
            board.set_inactivity_timeout(new_timeout)
            log.info(f"[Settings] Inactivity timeout set to {new_timeout}s")
        except ValueError:
            pass


def _shutdown(message: str, reboot: bool = False):
    """Shutdown the system with a message displayed on screen.
    
    Args:
        message: Message to display on shutdown splash
        reboot: If True, reboot instead of shutdown
    """
    board.display_manager.clear_widgets(addStatusBar=False)
    promise = board.display_manager.add_widget(SplashScreen(message=message))
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
    # Show loading screen
    board.display_manager.clear_widgets(addStatusBar=False)
    promise = board.display_manager.add_widget(SplashScreen(message="Loading"))
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
    
    Routes data to GameHandler for protocol processing.
    
    Args:
        data: Raw bytes received from BLE client
        client_type: Type of client ('millennium', 'pegasus', 'chessnut')
    """
    global game_handler, relay_mode, relay_manager
    
    hex_str = ' '.join(f'{b:02x}' for b in data)
    log.info(f"[BLE RX] {client_type}: {len(data)} bytes - {hex_str}")
    
    # Process through GameHandler
    if game_handler:
        for byte_val in data:
            game_handler.receive_data(byte_val)
    
    # Forward to shadow target if in relay mode
    if relay_mode and relay_manager is not None and relay_manager.connected:
        relay_manager.send_to_target(data)


def _on_ble_connected(client_type: str):
    """Handle BLE client connection.
    
    If in menu mode, auto-transitions to game mode by cancelling the menu.
    Notifies GameHandler that an app has connected.
    
    Args:
        client_type: Type of client ('millennium', 'pegasus', 'chessnut')
    """
    global game_handler, app_state, _active_menu_widget
    
    log.info(f"[BLE] Client connected: {client_type}")
    
    # Auto-transition to game mode if currently in menu
    if app_state == AppState.MENU and _active_menu_widget is not None:
        log.info("[BLE] Client connected while in menu - cancelling menu to start game")
        # Cancel the menu selection with a special result that triggers game mode
        _active_menu_widget.cancel_selection("CLIENT_CONNECTED")
        return  # GameHandler will be notified after game mode starts
    
    if game_handler:
        game_handler.on_app_connected()


def _on_ble_disconnected():
    """Handle BLE client disconnection.
    
    Notifies GameHandler that the app has disconnected.
    """
    global game_handler
    
    log.info("[BLE] Client disconnected")
    if game_handler:
        game_handler.on_app_disconnected()

# ============================================================================
# sendMessage callback for GameHandler
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
    
    Processes data through GameHandler and optionally forwards to relay target.
    """
    global running, client_sock, client_connected, game_handler, relay_mode, relay_manager
    
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
                    game_handler.on_app_disconnected()
                    break
                
                data_bytes = bytearray(data)
                log.info(f"[RFCOMM RX] {' '.join(f'{b:02x}' for b in data_bytes)}")
                
                # Process through GameHandler
                for byte_val in data_bytes:
                    game_handler.receive_data(byte_val)
                
                # Forward to shadow target if in relay mode
                if relay_mode and relay_manager is not None and relay_manager.connected:
                    relay_manager.send_to_target(bytes(data_bytes))
                    
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
    global game_handler, display_manager, rfcomm_manager, ble_manager, relay_manager
    
    try:
        log.info(f"Exiting: {reason}")
        kill = 1
        running = False
        
        # Show exiting splash screen
        try:
            board.display_manager.clear_widgets(addStatusBar=False)
            exit_splash = SplashScreen(message="Exiting...")
            board.display_manager.add_widget(exit_splash)
        except Exception as e:
            log.debug(f"Error showing exit splash: {e}")
        
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
        if game_handler is not None:
            try:
                game_handler.cleanup()
            except Exception as e:
                log.debug(f"Error cleaning up game handler: {e}")
        
        # Clear splash screen message before cleanup
        try:
            exit_splash.set_message("")
        except Exception:
            pass
        
        # Clean up display manager (analysis engine and widgets)
        if display_manager is not None:
            try:
                display_manager.cleanup()
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


def key_callback(key_id):
    """Handle key press events from the board.
    
    Behavior depends on current app state:
    - MENU: Keys are routed to the active menu widget
    - GAME: GameManager handles most keys, this receives passthrough
    
    This callback receives:
    - BACK: In game mode (no game or after resign/draw), returns to menu
    - HELP: Toggle game analysis widget visibility (game mode only)
    - LONG_PLAY: Shutdown system
    """
    global running, kill, display_manager, app_state, _active_menu_widget, _active_keyboard_widget
    
    log.info(f"[App] Key event received: {key_id}, app_state={app_state}")
    
    # Always handle LONG_PLAY for shutdown
    if key_id == board.Key.LONG_PLAY:
        log.info("[App] LONG_PLAY key event received")
        running = False
        kill = 1
        board.shutdown(reason="LONG_PLAY key event from universal.py")
        return
    
    # Priority 1: Active keyboard widget gets key events
    if _active_keyboard_widget is not None:
        handled = _active_keyboard_widget.handle_key(key_id)
        if handled:
            return
    
    # Route based on app state
    if app_state == AppState.MENU or app_state == AppState.SETTINGS:
        # Route to active menu widget
        if _active_menu_widget is not None:
            handled = _active_menu_widget.handle_key(key_id)
            if handled:
                return
    
    elif app_state == AppState.GAME:
        # Priority: DisplayManager menu (resign/draw, promotion) > app keys > game
        if display_manager and display_manager.is_menu_active():
            display_manager.handle_key(key_id)
            return
        
        # Handle app-level keys
        if key_id == board.Key.HELP:
            # Toggle game analysis widget visibility
            if display_manager:
                display_manager.toggle_analysis()
            return
        
        # Forward other keys to game_handler -> game_manager
        if game_handler:
            game_handler.receive_key(key_id)
            
            # Check if GameManager wants us to exit (BACK with no game in progress)
            if key_id == board.Key.BACK and not game_handler.game_manager.is_game_in_progress():
                log.info("[App] BACK with no game - returning to menu")
                _return_to_menu("BACK pressed")


# Pending piece events for menu -> game transition
# Queue of (piece_event, field, time_in_seconds) tuples
_pending_piece_events = []

def field_callback(piece_event, field, time_in_seconds):
    """Handle field events (piece lift/place) from the board.
    
    Routes field events based on priority:
    1. Active keyboard widget (for text input like WiFi password)
    2. Menu mode with piece lift: Start game mode (piece move starts game)
    3. Game mode: Forward to game_handler -> game_manager for piece detection
    
    Args:
        piece_event: 0 = lift, 1 = place
        field: Board field index (0-63)
        time_in_seconds: Event timestamp
    """
    global app_state, game_handler, _active_keyboard_widget, _active_menu_widget, _pending_piece_events

    # Priority 1: Active keyboard gets field events
    if _active_keyboard_widget is not None:
        # Convert piece_event to presence: 1 = place = present, 0 = lift = not present
        piece_present = (piece_event == 1)
        _active_keyboard_widget.handle_field_event(field, piece_present)
        return
    
    # Priority 2: Menu mode - piece events queued for game mode
    # Queue events if:
    # - Menu is active (first event triggers game start), OR
    # - Game start is pending (events already queued, waiting for main thread to start game)
    if app_state == AppState.MENU:
        if _active_menu_widget is not None or len(_pending_piece_events) > 0:
            # Queue the piece event to forward after game mode starts
            # Multiple events may arrive before game mode is ready (e.g., LIFT then PLACE)
            _pending_piece_events.append((piece_event, field, time_in_seconds))
            log.info(f"[App] Piece event in menu - queued for game (field={field}, event={piece_event}, queue_size={len(_pending_piece_events)})")
            # Only trigger game start on first event (avoid multiple cancel calls)
            if len(_pending_piece_events) == 1 and _active_menu_widget is not None:
                _active_menu_widget.cancel_selection("PIECE_MOVED")
            return
    
    # Priority 3: Game mode
    if app_state == AppState.GAME:
        if game_handler:
            game_handler.receive_field(piece_event, field, time_in_seconds)
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
    global mainloop, relay_mode, game_handler, relay_manager, app_state, _args
    global _pending_piece_events
    
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
        
        # Create splash screen if early init didn't work
        if startup_splash is None:
            board.display_manager.clear_widgets(addStatusBar=False)
            startup_splash = SplashScreen(message="Starting...")
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
            global app_state, _active_menu_widget
            
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
                    
                    # Auto-transition to game mode if in menu
                    if app_state == AppState.MENU and _active_menu_widget is not None:
                        log.info("[RFCOMM] Client connected while in menu - transitioning to game")
                        _active_menu_widget.cancel_selection("CLIENT_CONNECTED")
                    elif game_handler:
                        game_handler.on_app_connected()
                    
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
            if game_handler is not None and game_handler.compare_mode:
                match, emulator_response = game_handler.compare_with_shadow(data)
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
    
    log.info("")
    log.info("Ready for connections and user input")
    log.info(f"Device name: {args.device_name}")
    if not args.no_ble:
        log.info("  BLE: Ready for GATT connections")
    if not args.no_rfcomm:
        log.info("  RFCOMM: Initializing in background...")
    log.info("")
    
    # Show ready message before menu
    if startup_splash:
        startup_splash.set_message("Ready")
        time.sleep(0.3)
    
    # Check if Centaur software is available
    centaur_available = os.path.exists(CENTAUR_SOFTWARE)
    
    # Main application loop - menu based
    app_state = AppState.MENU
    try:
        while running and not kill:
            if app_state == AppState.MENU:
                # Show main menu
                entries = create_main_menu_entries(centaur_available=centaur_available)
                result = _show_menu(entries)
                
                log.info(f"[App] Main menu selection: {result}")
                
                if result == "BACK":
                    # Show idle screen and wait for TICK
                    board.beep(board.SOUND_POWER_OFF)
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
                        if game_handler:
                            game_handler.receive_field(pe, field, ts)
                    
                    # Notify GameHandler if client is already connected
                    if (ble_manager and ble_manager.connected) or client_connected:
                        if game_handler:
                            game_handler.on_app_connected()
                
                elif result == "Settings":
                    _handle_settings()
                    # After settings, continue to main menu
                
                elif result == "HELP":
                    # Could show about/help screen here
                    pass
            
            elif app_state == AppState.GAME:
                # Stay in game mode - key_callback handles exit via _return_to_menu
                time.sleep(0.5)
            
            elif app_state == AppState.SETTINGS:
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
