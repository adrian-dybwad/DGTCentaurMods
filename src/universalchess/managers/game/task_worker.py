"""Serial task worker used by GameManager.

GameManager has to execute a variety of side-effects (DB writes, callbacks, board I/O)
in strict order, even when multiple physical-board events arrive rapidly.

This worker provides:
- a single FIFO queue
- a single daemon thread that executes tasks sequentially
- a stop event shared with the owning manager for coordinated shutdown
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, Optional

from universalchess.board.logging import log


class GameTaskWorker:
    """Runs queued callables sequentially on a background thread."""

    def __init__(self, stop_event: threading.Event):
        self._stop_event = stop_event
        self._queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the worker thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return

        def worker():
            while not self._stop_event.is_set():
                try:
                    try:
                        task = self._queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    try:
                        task()
                    except Exception as e:
                        log.error(f"[GameTaskWorker] Error executing task: {e}")
                    finally:
                        self._queue.task_done()
                except Exception as e:
                    log.error(f"[GameTaskWorker] Unexpected error in worker loop: {e}")

        self._thread = threading.Thread(target=worker, daemon=True, name="GameManager-TaskWorker")
        self._thread.start()

    def submit(self, task: Callable[[], None]) -> None:
        """Submit a task to be executed in FIFO order."""
        self._queue.put(task)


__all__ = ["GameTaskWorker"]


