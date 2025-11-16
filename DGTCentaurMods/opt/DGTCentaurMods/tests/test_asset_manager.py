from __future__ import annotations

from pathlib import Path

import pytest

from DGTCentaurMods.display.ui_components import AssetManager


def test_asset_manager_prefers_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure developers can point the asset loader at a local resource folder."""

    resources = tmp_path / "resources"
    resources.mkdir()
    target = resources / "Font.ttc"
    target.write_bytes(b"fake-font")

    monkeypatch.setenv("DGTCM_RESOURCES", str(resources))

    resolved = AssetManager.get_resource_path("Font.ttc")
    assert Path(resolved) == target

