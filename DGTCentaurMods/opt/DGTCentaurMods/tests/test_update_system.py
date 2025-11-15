from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


def _build_update_system():
    from DGTCentaurMods.board.centaur import UpdateSystem

    return UpdateSystem()


def test_update_install_invokes_python_runner_without_copytree():
    updater = _build_update_system()

    with patch("DGTCentaurMods.board.centaur.widgets.write_text"), \
         patch("DGTCentaurMods.board.centaur.time.sleep"), \
         patch("DGTCentaurMods.board.centaur.subprocess.Popen") as popen, \
         patch("DGTCentaurMods.board.centaur.shutil.copy") as copy_file, \
         patch("DGTCentaurMods.board.centaur.shutil.copytree") as copytree, \
         patch("DGTCentaurMods.board.centaur.sys.exit", side_effect=SystemExit):

        popen.return_value = MagicMock()

        with pytest.raises(SystemExit):
            updater.updateInstall()

    copy_file.assert_not_called()
    copytree.assert_not_called()

    (cmd,), kwargs = popen.call_args
    assert isinstance(cmd, (list, tuple)), cmd
    assert kwargs.get("shell", False) is False
    assert cmd[0] == sys.executable
    assert any("DGTCentaurMods" in str(segment) and "update.py" in str(segment) for segment in cmd), cmd


