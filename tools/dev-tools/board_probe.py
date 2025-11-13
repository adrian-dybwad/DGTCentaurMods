#!/usr/bin/env python3
"""
Board module probe - loads and exercises board.py functions

Purpose:
  - Import and use the board.py module
  - Test board functions interactively
  - Display board state and exercise board controls

This script imports the project's board module and provides an interface
to test its functions.

Usage examples:
  python3 tools/dev-tools/board_probe.py
  python3 tools/dev-tools/board_probe.py --state
  python3 tools/dev-tools/board_probe.py --beep SOUND_GENERAL
"""

import argparse
import sys
import os
import time

# Ensure we import the repo package first (not a system-installed copy)
try:
    REPO_OPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'DGTCentaurMods', 'opt'))
    if REPO_OPT not in sys.path:
        sys.path.insert(0, REPO_OPT)
except Exception as e:
    print(f"Warning: Could not add repo path: {e}")

try:
    from DGTCentaurMods.board import board
    from DGTCentaurMods.board.sync_centaur import command
    from DGTCentaurMods.board.logging import log
except ImportError as e:
    print(f"Failed to import board module: {e}")
    print("Make sure you're running from the project root and the board module is available.")
    sys.exit(1)


def print_board_state():
    """Get and print the current board state."""
    try:
        print("\n=== Board State ===")
        state = board.getChessState()
        board.printChessState(state)
        print(f"\nRaw board data: {board.getBoardState()}")
    except Exception as e:
        print(f"Error getting board state: {e}")


def test_beep(beep_type):
    """Test beep function."""
    try:
        print(f"\n=== Testing beep: {beep_type} ===")
        if hasattr(board, beep_type):
            beep_val = getattr(board, beep_type)
            board.beep(beep_val)
            print(f"Beeped: {beep_type}")
        else:
            print(f"Unknown beep type: {beep_type}")
            print(f"Available: SOUND_GENERAL, SOUND_FACTORY, SOUND_POWER_OFF, SOUND_POWER_ON, SOUND_WRONG, SOUND_WRONG_MOVE")
    except Exception as e:
        print(f"Error testing beep: {e}")


def test_led(square, intensity=5):
    """Test LED function."""
    try:
        print(f"\n=== Testing LED: square={square}, intensity={intensity} ===")
        board.led(square, intensity)
        print(f"LED lit at square {square}")
    except Exception as e:
        print(f"Error testing LED: {e}")


def test_led_array(squares, speed=3, intensity=5):
    """Test LED array function."""
    try:
        print(f"\n=== Testing LED array: squares={squares}, speed={speed}, intensity={intensity} ===")
        board.ledArray(squares, speed, intensity)
        print(f"LED array lit")
    except Exception as e:
        print(f"Error testing LED array: {e}")


def test_led_from_to(frm, to, intensity=5):
    """Test LED from-to function."""
    try:
        print(f"\n=== Testing LED from-to: {frm} -> {to}, intensity={intensity} ===")
        board.ledFromTo(frm, to, intensity)
        print(f"LED from {frm} to {to}")
    except Exception as e:
        print(f"Error testing LED from-to: {e}")


def test_battery():
    """Get and display battery level."""
    try:
        print("\n=== Battery Info ===")
        board.getBatteryLevel()
        print(f"Battery level: {board.batterylevel}")
        print(f"Charger connected: {board.chargerconnected}")
    except Exception as e:
        print(f"Error getting battery info: {e}")


def interactive_mode():
    """Run interactive mode."""
    print("\n=== Interactive Board Probe ===")
    print("Commands:")
    print("  state          - Get and print board state")
    print("  battery        - Get battery level")
    print("  beep <type>    - Beep (SOUND_GENERAL, SOUND_FACTORY, etc.)")
    print("  led <sq> [int] - Light LED at square (0-63) with optional intensity")
    print("  leds <sqs>     - Light LED array (comma-separated squares, e.g., 0,1,2)")
    print("  fromto <f> <t> [int] - Light LED from square to square")
    print("  leds_off       - Turn all LEDs off")
    print("  controller     - Show controller info")
    print("  q              - Quit")
    print()

    while True:
        try:
            line = input("board> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ("q", "quit", "exit"):
            break
        elif cmd == "state":
            print_board_state()
        elif cmd == "battery":
            test_battery()
        elif cmd == "beep":
            if len(parts) < 2:
                print("Usage: beep <type>")
                print("Types: SOUND_GENERAL, SOUND_FACTORY, SOUND_POWER_OFF, SOUND_POWER_ON, SOUND_WRONG, SOUND_WRONG_MOVE")
            else:
                test_beep(parts[1])
        elif cmd == "led":
            if len(parts) < 2:
                print("Usage: led <square> [intensity]")
            else:
                try:
                    square = int(parts[1])
                    intensity = int(parts[2]) if len(parts) > 2 else 5
                    test_led(square, intensity)
                except ValueError:
                    print("Error: square and intensity must be integers")
        elif cmd == "leds":
            if len(parts) < 2:
                print("Usage: leds <square1,square2,...>")
            else:
                try:
                    squares = [int(s.strip()) for s in parts[1].split(",")]
                    test_led_array(squares)
                except ValueError:
                    print("Error: squares must be comma-separated integers")
        elif cmd == "fromto":
            if len(parts) < 3:
                print("Usage: fromto <from_square> <to_square> [intensity]")
            else:
                try:
                    frm = int(parts[1])
                    to = int(parts[2])
                    intensity = int(parts[3]) if len(parts) > 3 else 5
                    test_led_from_to(frm, to, intensity)
                except ValueError:
                    print("Error: squares and intensity must be integers")
        elif cmd == "leds_off":
            try:
                print("\n=== Turning LEDs off ===")
                board.ledsOff()
                print("LEDs turned off")
            except Exception as e:
                print(f"Error: {e}")
        elif cmd == "controller":
            try:
                print("\n=== Controller Info ===")
                print(f"Controller type: {type(board.controller).__name__}")
                print(f"Controller: {board.controller}")
            except Exception as e:
                print(f"Error: {e}")
        else:
            print(f"Unknown command: {cmd}")
            print("Type 'q' to quit or use 'state', 'battery', 'beep', 'led', etc.")


def main():
    ap = argparse.ArgumentParser(description="Board module probe - loads and exercises board.py")
    ap.add_argument("--state", action="store_true", help="Get and print board state, then exit")
    ap.add_argument("--battery", action="store_true", help="Get battery info, then exit")
    ap.add_argument("--beep", help="Beep type (e.g., SOUND_GENERAL), then exit")
    ap.add_argument("--led", type=int, help="Light LED at square (0-63), then exit")
    ap.add_argument("--led-intensity", type=int, default=5, help="LED intensity (default: 5)")
    ap.add_argument("--leds-off", action="store_true", help="Turn all LEDs off, then exit")
    ap.add_argument("--interactive", action="store_true", default=True, help="Run in interactive mode (default)")
    ap.add_argument("--no-interactive", dest="interactive", action="store_false", help="Don't run interactive mode")
    args = ap.parse_args()

    print("Board module probe")
    print(f"Board module loaded from: {board.__file__ if hasattr(board, '__file__') else 'unknown'}")
    print(f"Controller: {type(board.controller).__name__}")

    board.printChessState()
    resp = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    log.info(f"Discovery: RESPONSE FROM F0 - {' '.join(f'{b:02x}' for b in resp)}")
    resp = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F4)
    log.info(f"Discovery: RESPONSE FROM F4 - {' '.join(f'{b:02x}' for b in resp)}")
    resp = board.sendCommand(command.DGT_BUS_SEND_96)
    log.info(f"Discovery: RESPONSE FROM 96 - {' '.join(f'{b:02x}' for b in resp)}")
    resp = board.sendCommand(command.DGT_BUS_SEND_STATE)
    log.info(f"Discovery: RESPONSE FROM 83 - {' '.join(f'{b:02x}' for b in resp)}")

    # Handle one-shot commands
    if args.state:
        print_board_state()
        return

    if args.battery:
        test_battery()
        return

    if args.beep:
        test_beep(args.beep)
        return

    if args.led is not None:
        test_led(args.led, args.led_intensity)
        return

    if args.leds_off:
        try:
            board.ledsOff()
            print("LEDs turned off")
        except Exception as e:
            print(f"Error: {e}")
        return

    # Default: interactive mode
    if args.interactive:
        interactive_mode()
    else:
        print("No action specified. Use --state, --battery, --beep, --led, or --interactive")


if __name__ == "__main__":
    main()

