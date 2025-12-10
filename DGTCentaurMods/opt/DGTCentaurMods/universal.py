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
import subprocess
import socket
import random
import psutil
import bluetooth
from gi.repository import GLib
import chess
import chess.engine
import pathlib

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board import board
from DGTCentaurMods.epaper import SplashScreen
from DGTCentaurMods.rfcomm_manager import RfcommManager
from DGTCentaurMods.ble_manager import BleManager
from DGTCentaurMods.game_handler import GameHandler
from DGTCentaurMods.display_manager import DisplayManager

# Global state
running = True
kill = 0
shadow_target_connected = False
client_connected = False
game_handler = None  # GameHandler instance
display_manager = None  # DisplayManager for game UI widgets
_last_message = None  # Last message sent via sendMessage
relay_mode = False  # Whether relay mode is enabled (connects to relay target)
shadow_target = "MILLENNIUM CHESS"  # Default target device name (can be overridden via --shadow-target)
mainloop = None  # GLib mainloop for BLE
rfcomm_manager = None  # RfcommManager for RFCOMM pairing
ble_manager = None  # BleManager for BLE GATT services

# Socket references
shadow_target_sock = None
server_sock = None
client_sock = None

# Thread references
shadow_target_to_client_thread = None
shadow_target_to_client_thread_started = False

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
    global game_handler, relay_mode, shadow_target_sock, shadow_target_connected
    
    hex_str = ' '.join(f'{b:02x}' for b in data)
    log.info(f"[BLE RX] {client_type}: {len(data)} bytes - {hex_str}")
    
    # Process through GameHandler
    if game_handler:
        for byte_val in data:
            game_handler.receive_data(byte_val)
    
    # Forward to shadow target if in relay mode
    if relay_mode and shadow_target_connected and shadow_target_sock is not None:
        try:
            log.info(f"[BLE -> Shadow] Forwarding {len(data)} bytes")
            shadow_target_sock.send(bytes(data))
        except Exception as e:
            log.error(f"[BLE -> Shadow] Error: {e}")
            shadow_target_connected = False


def _on_ble_connected(client_type: str):
    """Handle BLE client connection.
    
    Notifies GameHandler that an app has connected.
    
    Args:
        client_type: Type of client ('millennium', 'pegasus', 'chessnut')
    """
    global game_handler
    
    log.info(f"[BLE] Client connected: {client_type}")
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
# Bluetooth Classic SPP Functions
# ============================================================================

def find_shadow_target_device(shadow_target="MILLENNIUM CHESS"):
    """Find the device by name."""
    log.info(f"Looking for {shadow_target} device...")
    
    # First, try to find in known devices using RfcommManager
    controller = RfcommManager()
    addr = controller.find_device_by_name(shadow_target)
    if addr:
        return addr
    
    # If not found in known devices, do a discovery scan
    log.info(f"Scanning for {shadow_target} device...")
    devices = bluetooth.discover_devices(duration=8, lookup_names=True, flush_cache=True)
    
    for addr, name in devices:
        log.info(f"Found device: {name} ({addr})")
        if name and shadow_target.upper() in name.upper():
            log.info(f"Found {shadow_target} at address: {addr}")
            return addr
    
    log.warning(f"{shadow_target} device not found in scan")
    return None


def find_shadow_target_service(device_addr):
    """Find the RFCOMM service on the SHADOW TARGET device"""
    log.info(f"Discovering services on {device_addr}...")
    
    services = bluetooth.find_service(address=device_addr)
    
    for service in services:
        log.info(f"Service: {service.get('name', 'Unknown')} - "
                 f"Protocol: {service.get('protocol', 'Unknown')} - "
                 f"Port: {service.get('port', 'Unknown')}")
        
        if service.get('protocol') == 'RFCOMM':
            port = service.get('port')
            if port is not None:
                log.info(f"Found RFCOMM service on port {port}")
                return port
    
    log.warning(f"No RFCOMM service found on {device_addr}")
    return None


def connect_to_shadow_target(shadow_target="MILLENNIUM CHESS"):
    """Connect to the target device."""
    global shadow_target_sock, shadow_target_connected
    global shadow_target_to_client_thread, shadow_target_to_client_thread_started
    
    try:
        device_addr = find_shadow_target_device(shadow_target=shadow_target)
        if not device_addr:
            log.error(f"Could not find SHADOW TARGET '{shadow_target}'")
            return False
        
        port = find_shadow_target_service(device_addr)
        if port is None:
            log.info("Trying common RFCOMM ports...")
            for common_port in [1, 2, 3, 4, 5]:
                try:
                    log.info(f"Attempting connection on port {common_port}...")
                    sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
                    sock.connect((device_addr, common_port))
                    shadow_target_sock = sock
                    shadow_target_connected = True
                    log.info(f"Connected to {device_addr} on port {common_port}")
                    if not shadow_target_to_client_thread_started:
                        shadow_target_to_client_thread = threading.Thread(target=shadow_target_to_client, daemon=True)
                        shadow_target_to_client_thread.start()
                        shadow_target_to_client_thread_started = True
                    return True
                except Exception as e:
                    log.debug(f"Failed on port {common_port}: {e}")
                    try:
                        sock.close()
                    except:
                        pass
            log.error(f"Could not connect to {device_addr} on any common port")
            return False
        
        log.info(f"Connecting to {device_addr}:{port}...")
        shadow_target_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        shadow_target_sock.connect((device_addr, port))
        shadow_target_connected = True
        log.info(f"Connected to SHADOW TARGET successfully")
        if not shadow_target_to_client_thread_started:
            shadow_target_to_client_thread = threading.Thread(target=shadow_target_to_client, daemon=True)
            shadow_target_to_client_thread.start()
            shadow_target_to_client_thread_started = True
        return True
        
    except Exception as e:
        log.error(f"Error connecting to SHADOW TARGET: {e}")
        import traceback
        log.error(traceback.format_exc())
        return False


def shadow_target_to_client():
    """Relay data from SHADOW TARGET to client."""
    global running, shadow_target_sock, client_sock, shadow_target_connected, client_connected
    global _last_message, shadow_target, game_handler
    
    log.info(f"Starting SHADOW TARGET -> Client relay thread")
    try:
        while running and not kill:
            try:
                if not shadow_target_connected or shadow_target_sock is None:
                    time.sleep(0.1)
                    continue
                
                data = shadow_target_sock.recv(1024)
                if len(data) > 0:
                    data_bytes = bytearray(data)
                    log.info(f"SHADOW TARGET -> Client: {' '.join(f'{b:02x}' for b in data_bytes)}")
                    
                    if game_handler is not None and game_handler.compare_mode:
                        match, emulator_response = game_handler.compare_with_shadow(bytes(data_bytes))
                        if match is False:
                            log.error("[Relay] MISMATCH: Emulator response differs from shadow host")
                        elif match is True:
                            log.info("[Relay] MATCH: Emulator response matches shadow host")
                    
                    if client_connected and client_sock is not None:
                        client_sock.send(data)
                    
                    # Send via BLE if connected
                    if ble_manager is not None and ble_manager.connected:
                        ble_manager.send_notification(bytes(data_bytes))

            except bluetooth.BluetoothError as e:
                if running:
                    log.error(f"Bluetooth error in relay: {e}")
                shadow_target_connected = False
                break
            except Exception as e:
                if running:
                    log.error(f"Error in relay: {e}")
                break
    except Exception as e:
        log.error(f"Relay thread error: {e}")
    finally:
        log.info("SHADOW TARGET -> Client relay thread stopped")
        shadow_target_connected = False


def client_to_shadow_target():
    """Relay data from client to SHADOW TARGET"""
    global running, shadow_target_sock, client_sock, shadow_target_connected, client_connected, game_handler
    
    log.info("Starting Client -> SHADOW TARGET relay thread")
    try:
        while running and not kill:
            try:
                if not client_connected or client_sock is None:
                    time.sleep(0.1)
                    continue
                
                if not shadow_target_connected or shadow_target_sock is None:
                    time.sleep(0.1)
                    continue
                
                data = client_sock.recv(1024)
                if len(data) == 0:
                    log.info("RFCOMM client disconnected")
                    client_connected = False
                    game_handler.on_app_disconnected()
                    break
                
                data_bytes = bytearray(data)
                log.info(f"Client -> SHADOW TARGET: {' '.join(f'{b:02x}' for b in data_bytes)}")
                
                for byte_val in data_bytes:
                    game_handler.receive_data(byte_val)
                
                if shadow_target_sock is not None: 
                    shadow_target_sock.send(data)
                    
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
        log.info("Client -> SHADOW TARGET relay thread stopped")
        client_connected = False


def client_reader():
    """Read data from RFCOMM client in server-only mode."""
    global running, client_sock, client_connected, game_handler
    
    log.info("Starting Client reader thread (server-only mode)")
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
                log.info(f"Client -> Server: {' '.join(f'{b:02x}' for b in data_bytes)}")
                
                for byte_val in data_bytes:
                    game_handler.receive_data(byte_val)
                    
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
    - Bluetooth controller pairing thread
    - Game handler and its game manager thread
    - Analysis engine
    - Board events and serial connection
    - Sockets and BLE mainloop
    
    Args:
        reason: Description of why the exit is happening (logged for debugging)
    """
    global kill, running, shadow_target_sock, client_sock, server_sock
    global shadow_target_connected, client_connected, mainloop
    global game_handler, display_manager, rfcomm_manager, ble_manager
    
    try:
        log.info(f"Exiting: {reason}")
        kill = 1
        running = False
        
        # Stop bluetooth controller pairing thread
        if rfcomm_manager is not None:
            try:
                rfcomm_manager.stop_pairing_thread()
                log.debug("Bluetooth controller pairing thread stopped")
            except Exception as e:
                log.debug(f"Error stopping rfcomm_manager: {e}")
        
        # Clean up game handler (stops game manager thread and closes standalone engine)
        if game_handler is not None:
            try:
                game_handler.cleanup()
            except Exception as e:
                log.debug(f"Error cleaning up game handler: {e}")
        
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
        
        if shadow_target_sock:
            try:
                shadow_target_sock.close()
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
        
        shadow_target_connected = False
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


def _exit_universal(reason: str):
    """Exit universal mode with cleanup.
    
    Args:
        reason: Reason for exiting (for logging)
    """
    global running, kill, display_manager
    
    running = False
    kill = 1
    
    # Show exiting splash screen
    if display_manager:
        display_manager.show_splash("    Exiting...")


def key_callback(key_id):
    """Handle key press events from the board.
    
    GameManager handles BACK key when game is in progress (notifies display controller).
    This callback receives:
    - BACK: When no game in progress, or after resign/draw (signals exit)
    - HELP: Toggle game analysis widget visibility
    - LONG_PLAY: Shutdown system (also sent by GameManager for 'exit' menu choice)
    """
    global running, kill, display_manager
    
    log.info(f"Key event received: {key_id}")
    
    if key_id == board.Key.BACK:
        # BACK passed through means exit (no game or after resign/draw)
        log.info("BACK - exiting Universal mode")
        _exit_universal("BACK pressed")
    
    elif key_id == board.Key.HELP:
        # Toggle game analysis widget visibility
        if display_manager:
            display_manager.toggle_analysis()
    
    elif key_id == board.Key.LONG_PLAY:
        log.info("LONG_PLAY pressed - shutting down")
        running = False
        kill = 1
        board.shutdown()


def main():
    """Main entry point"""
    global server_sock, client_sock, shadow_target_sock
    global shadow_target_connected, client_connected, running, kill
    global mainloop, shadow_target_to_client_thread, shadow_target_to_client_thread_started
    global relay_mode, shadow_target, game_handler
    
    parser = argparse.ArgumentParser(description="Bluetooth Classic SPP Relay with BLE")
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
    
    global display_manager, game_handler
    
    # Initialize display and show splash screen
    log.info("Initializing display...")
    promise = board.init_display()
    if promise:
        try:
            promise.result(timeout=10.0)
        except Exception as e:
            log.warning(f"Error initializing display: {e}")
    
    log.info("=" * 60)
    log.info("Universal Starting")
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
    log.info("Standalone Engine:")
    log.info(f"  Engine:            {args.standalone_engine}")
    log.info(f"  ELO:               {args.engine_elo}")
    log.info(f"  Player color:      {args.player_color}")
    log.info("")
    log.info("Controls:")
    log.info("  BACK:              Exit to menu")
    log.info("  HELP (?):          Toggle evaluation")
    log.info("")
    log.info("=" * 60)
    
    relay_mode = args.relay
    shadow_target = args.shadow_target
    
    # Determine player color for standalone engine
    if args.player_color == "random":
        fallback_player_color = chess.WHITE if random.randint(0, 1) == 0 else chess.BLACK
    else:
        fallback_player_color = chess.WHITE if args.player_color == "white" else chess.BLACK
    
    # Get analysis engine path
    base_path = pathlib.Path(__file__).parent
    analysis_engine_path = str((base_path / "engines/ct800").resolve())
    
    # Create DisplayManager - handles all game widgets (chess board, analysis)
    display_manager = DisplayManager(
        flip_board=False,
        show_analysis=True,
        analysis_engine_path=analysis_engine_path,
        on_exit=lambda: _exit_universal("Menu exit")
    )
    log.info("DisplayManager initialized")
    
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
            game_handler.manager.handle_resign()
            _exit_universal("Resigned")
        elif result == "draw":
            game_handler.manager.handle_draw()
            _exit_universal("Draw")
        elif result == "exit":
            board.shutdown()
        # cancel is handled by DisplayManager (restores display)
    
    # Create GameHandler at startup (with standalone engine if configured)
    game_handler = GameHandler(
        sendMessage_callback=sendMessage,
        client_type=None,
        compare_mode=relay_mode,
        standalone_engine_name=args.standalone_engine,
        player_color=fallback_player_color,
        engine_elo=args.engine_elo,
        display_update_callback=update_display,
        key_callback=key_callback
    )
    log.info(f"[GameHandler] Created with standalone engine: {args.standalone_engine} @ {args.engine_elo}")
    
    # Wire up GameManager callbacks to DisplayManager
    game_handler.manager.on_promotion_needed = display_manager.show_promotion_menu
    game_handler.manager.on_back_pressed = lambda: display_manager.show_back_menu(_on_back_menu_result)
    
    # Wire up event callback to reset analysis on new game
    from DGTCentaurMods.game_manager import EVENT_NEW_GAME
    def _on_game_event(event):
        if event == EVENT_NEW_GAME:
            display_manager.reset_analysis()
    game_handler._external_event_callback = _on_game_event
    
    # Check for early exit (BACK pressed during setup)
    if kill:
        cleanup_and_exit("BACK pressed during setup")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Setup BLE if enabled using BleManager
    global ble_manager
    if not args.no_ble:
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
    
    # Check for early exit (BACK pressed during BLE setup)
    if kill:
        cleanup_and_exit("BACK pressed during BLE setup")
    
    # Setup RFCOMM if enabled
    global rfcomm_manager
    if not args.no_rfcomm:
        # Check for early exit before starting RFCOMM setup
        if kill:
            cleanup_and_exit("BACK pressed before RFCOMM setup")
        
        # Kill any existing rfcomm processes
        os.system('sudo service rfcomm stop 2>/dev/null')
        time.sleep(1)
        
        for p in psutil.process_iter(attrs=['pid', 'name']):
            if str(p.info["name"]) == "rfcomm":
                try:
                    p.kill()
                except:
                    pass
        
        time.sleep(0.5)
        
        # Check again before creating RfcommManager
        if kill:
            cleanup_and_exit("BACK pressed before RfcommManager creation")
        
        # Create RFCOMM manager for pairing
        rfcomm_manager = RfcommManager(device_name=args.device_name)
        rfcomm_manager.enable_bluetooth()
        rfcomm_manager.set_device_name(args.device_name)
        rfcomm_manager.start_pairing_thread()
        
        time.sleep(1)
        
        # Check again before socket setup
        if kill:
            cleanup_and_exit("BACK pressed before RFCOMM socket setup")
        
        # Initialize server socket
        log.info("Setting up RFCOMM server socket...")
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
            log.info(f"RFCOMM service '{args.device_name}' advertised on channel {port}")
        except Exception as e:
            log.error(f"Failed to advertise RFCOMM service: {e}")
    
    # Start GLib mainloop in a thread for BLE
    def ble_mainloop():
        try:
            mainloop.run()
        except Exception as e:
            log.error(f"Error in BLE mainloop: {e}")
    
    if not args.no_ble:
        ble_thread = threading.Thread(target=ble_mainloop, daemon=True)
        ble_thread.start()
        log.info("BLE mainloop thread started")
    
    # Check for early exit (BACK pressed during RFCOMM setup)
    if kill:
        cleanup_and_exit("BACK pressed during RFCOMM setup")
    
    # Connect to shadow target if relay mode
    if relay_mode:
        log.info("=" * 60)
        log.info(f"RELAY MODE - Connecting to {shadow_target}")
        log.info("=" * 60)
        
        def connect_shadow():
            time.sleep(1)
            if connect_to_shadow_target(shadow_target=shadow_target):
                log.info(f"{shadow_target} connection established")
            else:
                log.error(f"Failed to connect to {shadow_target}")
                global kill
                kill = 1
        
        shadow_thread = threading.Thread(target=connect_shadow, daemon=True)
        shadow_thread.start()
    
    log.info("")
    log.info("Waiting for connections...")
    log.info(f"Device name: {args.device_name}")
    if not args.no_ble:
        log.info("  BLE: Ready for GATT connections")
    if not args.no_rfcomm:
        log.info(f"  RFCOMM: Listening on channel {port}")
    log.info("")
    
    # Wait for RFCOMM client connection (BLE is handled via callbacks)
    connected = False
    ble_is_connected = ble_manager.connected if ble_manager else False
    if not args.no_rfcomm:
        while not connected and not ble_is_connected and not kill:
            ble_is_connected = ble_manager.connected if ble_manager else False
            try:
                client_sock, client_info = server_sock.accept()
                connected = True
                client_connected = True
                log.info("=" * 60)
                log.info("RFCOMM CLIENT CONNECTED")
                log.info("=" * 60)
                log.info(f"Client address: {client_info}")
                
                # Notify GameHandler that an app connected
                game_handler.on_app_connected()
                log.info("[GameHandler] RFCOMM app connected")
                
            except bluetooth.BluetoothError:
                time.sleep(0.1)
            except Exception as e:
                if running:
                    log.error(f"Error accepting connection: {e}")
                time.sleep(0.1)
    
    # Wait for shadow target connection if relay mode
    if relay_mode:
        max_wait = 30
        wait_time = 0
        while not shadow_target_connected and wait_time < max_wait and not kill:
            time.sleep(0.5)
            wait_time += 0.5
        
        if not shadow_target_connected:
            cleanup_and_exit("Shadow target connection timeout")
    
    # Start appropriate relay/reader threads
    if relay_mode:
        if connected and client_sock is not None:
            client_to_shadow_target_thread = threading.Thread(target=client_to_shadow_target, daemon=True)
            client_to_shadow_target_thread.start()
    else:
        if connected and client_sock is not None:
            client_reader_thread = threading.Thread(target=client_reader, daemon=True)
            client_reader_thread.start()
    
    # Main loop
    exit_reason = "BACK pressed"
    try:
        while running and not kill:
            time.sleep(1)
    except KeyboardInterrupt:
        exit_reason = "Keyboard interrupt"
    except Exception as e:
        exit_reason = f"Error in main loop: {e}"
    
    cleanup_and_exit(exit_reason)


if __name__ == "__main__":
    main()
