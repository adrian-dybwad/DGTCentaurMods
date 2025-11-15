"""
Centralized ePaper service entry point.

Import `service` for lifecycle management, `widgets` for common drawing helpers.
"""

from .client import EpaperService
from . import widgets

service = EpaperService()

__all__ = ["service", "widgets", "EpaperService"]

