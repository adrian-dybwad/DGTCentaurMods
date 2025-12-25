from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


def _build_update_system():
    # Prevent module import side-effects from trying to read real /opt config in unit tests.
    sys.modules.pop("universalchess.board.centaur", None)
    with patch("universalchess.board.settings.Settings.get_config", return_value=None), patch(
        "universalchess.board.settings.Settings.read", side_effect=lambda _section, _key, default=None: default
    ):
        from universalchess.board.centaur import UpdateSystem

        return UpdateSystem()


def test_update_install_invokes_python_runner_without_copytree():
    updater = _build_update_system()

    with patch("universalchess.board.centaur.subprocess.Popen") as popen, patch(
        "universalchess.board.centaur.sys.exit", side_effect=SystemExit
    ):

        popen.return_value = MagicMock()

        with pytest.raises(SystemExit):
            updater.updateInstall()

    (cmd,), kwargs = popen.call_args
    assert isinstance(cmd, (list, tuple)), cmd
    assert kwargs.get("shell", False) is False
    assert cmd[0] == sys.executable
    assert any("universalchess" in str(segment) and "update.py" in str(segment) for segment in cmd), cmd


