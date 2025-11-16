from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from PIL import Image


class DriverBase(ABC):
    """Abstract hardware/proxy driver."""

    width: int = 128
    height: int = 296

    @abstractmethod
    def init(self) -> None:
        ...

    @abstractmethod
    def reset(self) -> None:
        ...

    @abstractmethod
    def full_refresh(self, image: Image.Image) -> None:
        ...

    @abstractmethod
    def partial_refresh(self, y0: int, y1: int, image: Image.Image) -> None:
        ...

    @abstractmethod
    def sleep(self) -> None:
        ...

    @abstractmethod
    def shutdown(self) -> None:
        ...


class DriverFactory(Protocol):
    def __call__(self, name: str | None = None) -> DriverBase:
        ...

