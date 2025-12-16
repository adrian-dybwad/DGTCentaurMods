from __future__ import annotations

import builtins
from unittest.mock import patch


def test_shutdown_uses_systemctl_poweroff():
    # Import lazily to allow patching os.system
    with patch("os.system") as os_system:
        # Arrange return code success
        os_system.return_value = 0

        from DGTCentaurMods.board import board

        # Patch out side-effects in shutdown sequence
        with patch.object(board, "beep", lambda *a, **k: None), \
             patch("DGTCentaurMods.display.epaper_service.widgets.clear_screen", lambda *a, **k: None), \
             patch("DGTCentaurMods.display.epaper_service.widgets.write_text", lambda *a, **k: None), \
             patch.object(board, "led", lambda *a, **k: None), \
             patch.object(board, "ledsOff", lambda *a, **k: None), \
             patch("DGTCentaurMods.display.epaper_service.service.shutdown", lambda *a, **k: None), \
             patch.object(board, "sleep_controller", lambda *a, **k: None):
            board.shutdown()

        # Assert that systemctl poweroff was requested
        calls = [str(args[0]) for args, _ in os_system.call_args_list]
        assert any("systemctl poweroff" in c for c in calls), calls


