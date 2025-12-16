#!/usr/bin/env python3
"""
DGT Centaur Controller Sleep Hook (Fallback)

This script is called by DGTStopController.service during system shutdown
when the main DGTCentaurMods service is not running. It ensures the
controller powers down properly before the Raspberry Pi completes shutdown.

The main DGTCentaurMods service disables this fallback on startup and handles
shutdown itself. If the main service crashes or is stopped, this fallback
re-enables to catch system shutdowns.

The sleep command uses blocking request_response with retries to confirm
the controller received the command. Without confirmation, the controller
may remain powered after the Pi shuts down, draining the battery.

Installed by: DGTCentaurMods package
Service: /etc/systemd/system/DGTStopController.service
"""

import sys
from DGTCentaurMods.board.logging import log

try:
    from DGTCentaurMods.board import board
    success = board.sleep_controller()
    if success:
        log.info("[shutdown.py] Controller sleep acknowledged")
        sys.exit(0)
    else:
        log.error("[shutdown.py] Controller did not acknowledge sleep command - battery may drain")
        sys.exit(1)
except Exception as e:
    log.error(f"[shutdown.py] Failed to sleep DGT Centaur controller: {e}")
    sys.exit(1)
