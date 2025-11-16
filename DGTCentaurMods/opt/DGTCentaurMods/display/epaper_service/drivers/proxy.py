from __future__ import annotations

import os
import socket
import struct

from PIL import Image

from ..driver_base import DriverBase


class ProxyDriver(DriverBase):
    """Sends display frames to the VM proxy server."""

    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        self._host = host or os.environ.get("EPAPER_PROXY_HOST", "127.0.0.1")
        self._port = port or int(os.environ.get("EPAPER_PROXY_PORT", "8889"))
        self._sock: socket.socket | None = None
        self._connect()

    def _connect(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self._host, self._port))
        self._sock = sock

    def _send_image(self, image: Image.Image) -> None:
        if not self._sock:
            self._connect()
        mode_bytes = image.mode.encode("utf-8")
        payload = struct.pack("!II", image.width, image.height)
        payload += struct.pack("!I", len(mode_bytes))
        payload += mode_bytes
        payload += image.tobytes()
        size = struct.pack("!I", len(payload))
        assert self._sock is not None
        self._sock.sendall(size + payload)

    def init(self) -> None:  # pragma: no cover - proxy is state-less
        return

    def reset(self) -> None:
        return

    def full_refresh(self, image: Image.Image) -> None:
        self._send_image(image)

    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        self._send_image(image)

    def sleep(self) -> None:
        return

    def shutdown(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None

