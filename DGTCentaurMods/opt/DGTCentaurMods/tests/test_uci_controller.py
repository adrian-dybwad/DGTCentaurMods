from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import chess

from DGTCentaurMods.uci.controller import ControllerConfig, UciGameController


class DummyEngines:
    def __init__(self):
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.configure_play_engine = AsyncMock()
        self.play = AsyncMock(return_value=chess.Move.from_uci("e2e4"))
        self.analyse = AsyncMock(return_value={"score": None})


async def test_controller_start_stop(monkeypatch):
    engines = DummyEngines()
    cfg = ControllerConfig(color="white", engine_name="sf")
    c = UciGameController(engines, cfg)

    # Patch epaper and gamemanager side-effects
    monkeypatch.setattr("DGTCentaurMods.display.epaper_service.service.init", lambda *a, **k: None)
    monkeypatch.setattr("DGTCentaurMods.game.gamemanager.subscribeGame", lambda *a, **k: None)
    monkeypatch.setattr("DGTCentaurMods.game.gamemanager.getBoard", lambda: chess.Board())

    await c.start()
    await c.stop()


