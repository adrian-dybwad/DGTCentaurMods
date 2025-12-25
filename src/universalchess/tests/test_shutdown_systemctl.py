from __future__ import annotations

from unittest.mock import patch


def test_shutdown_uses_systemctl_poweroff():
    # Import lazily to allow patching os.system
    with patch("os.system") as os_system:
        # Arrange return code success
        os_system.return_value = 0

        from universalchess.platform.system_power import request_poweroff
        request_poweroff(os_system=os_system)

        # Assert that systemctl poweroff was requested
        calls = [str(args[0]) for args, _ in os_system.call_args_list]
        assert any("systemctl poweroff" in c for c in calls), calls


