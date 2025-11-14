#!/usr/bin/env python3
"""
Simple Centaur probe - loads and exercises simple_centaur.py directly

Purpose:
  - Import and use SimpleCentaur directly
  - Test board commands with minimal implementation
  - Display raw responses from serial port

This script uses the simple_centaur module which provides:
  - Board discovery
  - Packet construction
  - Command sending with raw byte output

Usage examples:
  python3 tools/dev-tools/simple_centaur_probe.py
  python3 tools/dev-tools/simple_centaur_probe.py --command DGT_BUS_SEND_STATE
  python3 tools/dev-tools/simple_centaur_probe.py --command LED_OFF_CMD
  python3 tools/dev-tools/simple_centaur_probe.py --list-commands
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
    from DGTCentaurMods.board.simple_centaur import SimpleCentaur, command
    from DGTCentaurMods.board.logging import log
except ImportError as e:
    print(f"Failed to import simple_centaur module: {e}")
    print("Make sure you're running from the project root and the simple_centaur module is available.")
    sys.exit(1)


def list_commands():
    """List all available commands."""
    print("\n=== Available Commands ===")
    from DGTCentaurMods.board.simple_centaur import COMMANDS
    for name, spec in sorted(COMMANDS.items()):
        resp_type = f"0x{spec.expected_resp_type:02x}" if spec.expected_resp_type else "None"
        data_str = f"data={spec.default_data.hex()}" if spec.default_data else "no data"
        print(f"  {name:30s} cmd=0x{spec.cmd:02x}  resp={resp_type:6s}  {data_str}")
    print()


def send_command(centaur, cmd_name, data=None):
    """Send a command and display the response."""
    try:
        print(f"\n=== Sending command: {cmd_name} ===")
        if data:
            print(f"Data: {data.hex()}")
        
        response = centaur.sendCommand(cmd_name, data)
        
        if response:
            print(f"Response ({len(response)} bytes):")
            print(f"  Hex: {' '.join(f'{b:02x}' for b in response)}")
            print(f"  Raw: {response}")
        else:
            print("No response received")
        
        return response
    except Exception as e:
        print(f"Error sending command: {e}")
        import traceback
        traceback.print_exc()
        return None


def send_custom_command(centaur, cmd_hex, data_hex=None):
    """Send a custom command with hex values."""
    try:
        cmd_byte = int(cmd_hex, 16)
        data_bytes = bytes.fromhex(data_hex) if data_hex else None
        
        print(f"\n=== Sending custom command: 0x{cmd_byte:02x} ===")
        if data_bytes:
            print(f"Data: {data_bytes.hex()}")
        
        # Build packet manually
        packet = centaur.buildPacket(cmd_byte, data_bytes)
        print(f"Packet: {' '.join(f'{b:02x}' for b in packet)}")
        centaur.ser.write(packet)
        
        time.sleep(0.1)
        response = centaur.ser.read(1000)
        
        if response:
            print(f"Response ({len(response)} bytes):")
            print(f"  Hex: {' '.join(f'{b:02x}' for b in response)}")
            print(f"  Raw: {response}")
        else:
            print("No response received")
        
        return response
    except Exception as e:
        print(f"Error sending custom command: {e}")
        import traceback
        traceback.print_exc()
        return None


def interactive_mode(centaur):
    """Run interactive mode."""
    print("\n=== Interactive Simple Centaur Probe ===")
    print("Commands:")
    print("  <command_name>        - Send a command (e.g., DGT_BUS_SEND_STATE)")
    print("  send <cmd> [data_hex] - Send command with optional hex data")
    print("  custom <hex> [data]  - Send custom command byte with optional hex data")
    print("  discover              - Re-discover the board")
    print("  info                  - Show controller info")
    print("  list                  - List all available commands")
    print("  q                     - Quit")
    print()


    while True:
        try:
            line = input("simple_centaur> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].upper()

        if cmd in ("Q", "QUIT", "EXIT"):
            break
        elif cmd == "DISCOVER":
            try:
                print("\n=== Re-discovering board ===")
                centaur.discover_board()
            except Exception as e:
                print(f"Error: {e}")
        elif cmd == "INFO":
            try:
                print("\n=== Controller Info ===")
                print(f"Type: {type(centaur).__name__}")
                print(f"Ready: {centaur.ready}")
                print(f"Address: addr1={hex(centaur.addr1)}, addr2={hex(centaur.addr2)}")
                print(f"Developer mode: {centaur.developer_mode}")

                resp = centaur.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
                #log.info(f"Discovery: RESPONSE FROM F0 - {' '.join(f'{b:02x}' for b in resp)}")
                centaur.sendPacket(command.DGT_NOTIFY_EVENTS_58)
                resp = centaur.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F4)
                #log.info(f"Discovery: RESPONSE FROM F4 - {' '.join(f'{b:02x}' for b in resp)}")
                centaur.sendPacket(command.DGT_NOTIFY_EVENTS_58)
                resp = centaur.sendCommand(command.DGT_BUS_SEND_96)
                #log.info(f"Discovery: RESPONSE FROM 96 - {' '.join(f'{b:02x}' for b in resp)}")
                centaur.sendPacket(command.DGT_NOTIFY_EVENTS_58)
                resp = centaur.sendCommand(command.DGT_BUS_SEND_STATE)
                #log.info(f"Discovery: RESPONSE FROM 83 - {' '.join(f'{b:02x}' for b in resp)}")
                centaur.sendPacket(command.DGT_NOTIFY_EVENTS_58)

            except Exception as e:
                print(f"Error: {e}")
        elif cmd == "LIST":
            list_commands()
        elif cmd == "SEND":
            if len(parts) < 2:
                print("Usage: send <command_name> [data_hex]")
            else:
                cmd_name = parts[1]
                data = bytes.fromhex(parts[2]) if len(parts) > 2 else None
                send_command(centaur, cmd_name, data)
        elif cmd == "CUSTOM":
            if len(parts) < 2:
                print("Usage: custom <cmd_hex> [data_hex]")
            else:
                cmd_hex = parts[1]
                data_hex = parts[2] if len(parts) > 2 else None
                send_custom_command(centaur, cmd_hex, data_hex)
        else:
            # Try as a command name
            send_command(centaur, cmd)


def main():
    ap = argparse.ArgumentParser(description="Simple Centaur probe - loads and exercises simple_centaur.py")
    ap.add_argument("--command", "-c", help="Send a command and exit (e.g., DGT_BUS_SEND_STATE)")
    ap.add_argument("--data", help="Hex data for command (e.g., 4c08)")
    ap.add_argument("--custom", help="Send custom command byte in hex (e.g., 82)")
    ap.add_argument("--custom-data", help="Hex data for custom command")
    ap.add_argument("--list-commands", action="store_true", help="List all available commands and exit")
    ap.add_argument("--developer-mode", action="store_true", help="Use developer mode (virtual serial ports)")
    ap.add_argument("--interactive", action="store_true", default=True, help="Run in interactive mode (default)")
    ap.add_argument("--no-interactive", dest="interactive", action="store_false", help="Don't run interactive mode")
    args = ap.parse_args()

    print("Simple Centaur probe")
    print("=" * 50)

    # Initialize SimpleCentaur
    try:
        centaur = SimpleCentaur(developer_mode=args.developer_mode)
        print(f"SimpleCentaur initialized (developer_mode={args.developer_mode})")
    except Exception as e:
        print(f"Failed to initialize SimpleCentaur: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Discover board
    try:
        print("\nDiscovering board...")
        centaur.discover_board()
        if centaur.ready:
            print(f"Board discovered successfully - addr1={hex(centaur.addr1)}, addr2={hex(centaur.addr2)}")
        else:
            print("Warning: Board discovery may have failed")
    except Exception as e:
        print(f"Error during board discovery: {e}")
        import traceback
        traceback.print_exc()
        if not args.interactive:
            sys.exit(1)

    # Handle one-shot commands
    if args.list_commands:
        list_commands()
        centaur.cleanup()
        return

    if args.command:
        data = bytes.fromhex(args.data) if args.data else None
        send_command(centaur, args.command, data)
        centaur.cleanup()
        return

    if args.custom:
        send_custom_command(centaur, args.custom, args.custom_data)
        centaur.cleanup()
        return

    # Default: interactive mode
    if args.interactive:
        try:
            interactive_mode(centaur)
        finally:
            centaur.cleanup()
    else:
        print("No action specified. Use --command, --custom, --list-commands, or --interactive")
        centaur.cleanup()


if __name__ == "__main__":
    main()

