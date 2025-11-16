"""
Centralized ePaper service entry point.

Import `service` for lifecycle management. Widgets live in
`DGTCentaurMods.display.epaper_service.widgets`.
"""

from .client import EpaperService

service = EpaperService()

__all__ = ["service", "EpaperService"]

