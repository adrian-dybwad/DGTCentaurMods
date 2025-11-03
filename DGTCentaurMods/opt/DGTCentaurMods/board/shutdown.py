#!/usr/bin/env python3
"""
DGT Centaur Controller Sleep Hook

This script is called by DGTStopController.service during system shutdown
to send a sleep command to the DGT Centaur controller. This ensures the
controller powers down properly before the Raspberry Pi completes shutdown.

Installed by: DGTCentaurMods package
Service: /etc/systemd/system/DGTStopController.service

Can be tested independently: python3 board/shutdown.py
"""

import sys
from DGTCentaurMods.board.logging import log

try:
    from DGTCentaurMods.board import board
    board.sleep_controller()
    sys.exit(0)
except Exception as e:
    log.error(f"Failed to sleep DGT Centaur controller: {e}")
    sys.exit(1)  # Non-zero exit signals failure to systemd

