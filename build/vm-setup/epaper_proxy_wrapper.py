#!/usr/bin/env python3
"""
Launch a command with the ePaper proxy backend enabled.

Usage:
  ./epaper_proxy_wrapper.py --server-ip 192.168.0.10 -- <command> [args...]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

DEFAULT_PROXY_PORT = 8889


def _build_env(server_ip: str, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env["EPAPER_DRIVER"] = "proxy"
    env["EPAPER_PROXY_HOST"] = server_ip
    env["EPAPER_PROXY_PORT"] = str(port)
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a command using the ePaper proxy backend")
    parser.add_argument("--server-ip", required=True, help="IP address of the Raspberry Pi proxy server")
    parser.add_argument("--server-port", type=int, default=DEFAULT_PROXY_PORT, help="Proxy TCP port")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run (prefix with -- to stop parsing)")
    args = parser.parse_args()

    if not args.command:
        parser.error("command to run is required (hint: use '-- <cmd> ...')")

    env = _build_env(args.server_ip, args.server_port)
    print(f"EPAPER_DRIVER=proxy (target={args.server_ip}:{args.server_port})")
    print(f"Running command: {' '.join(args.command)}")

    try:
        result = subprocess.run(args.command, env=env, check=False)
        return result.returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

