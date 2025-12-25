"""System power operations (poweroff/reboot).

This module isolates platform/OS calls so they can be mocked in unit tests and
kept out of hardware/UI modules.
"""

from __future__ import annotations

import os
from typing import Callable


def request_poweroff(os_system: Callable[[str], int] = os.system) -> int:
    """Request a system poweroff via systemd.

    Args:
        os_system: Injectable system call function for tests.

    Returns:
        Return code from the underlying os_system call.
    """
    return os_system("sudo systemctl poweroff")


def request_reboot(os_system: Callable[[str], int] = os.system) -> int:
    """Request a system reboot via systemd.

    Args:
        os_system: Injectable system call function for tests.

    Returns:
        Return code from the underlying os_system call.
    """
    return os_system("sudo systemctl reboot")


