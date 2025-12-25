"""Tests for Hand+Brain mode menu entries using checkbox icons."""

import sys
import types
import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock

# Stub PIL so epaper imports succeed without external dependency.
pil_module = types.ModuleType("PIL")
pil_image_module = types.ModuleType("PIL.Image")
pil_image_module.Image = MagicMock()
pil_module.Image = pil_image_module.Image
sys.modules.setdefault("PIL", pil_module)
sys.modules.setdefault("PIL.Image", pil_image_module)
pil_image_draw_module = types.ModuleType("PIL.ImageDraw")
pil_image_draw_module.ImageDraw = MagicMock()
pil_image_font_module = types.ModuleType("PIL.ImageFont")
pil_image_font_module.ImageFont = MagicMock()
pil_module.ImageDraw = pil_image_draw_module.ImageDraw
pil_module.ImageFont = pil_image_font_module.ImageFont
sys.modules.setdefault("PIL.ImageDraw", pil_image_draw_module)
sys.modules.setdefault("PIL.ImageFont", pil_image_font_module)
# Stub hardware-specific modules used by epaper to allow imports on non-RPi.
for module_name in [
    "spidev",
    "RPi",
    "RPi.GPIO",
    "gpiozero",
    "lgpio",
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
]:
    sys.modules.setdefault(module_name, MagicMock())

# Stub IconMenuEntry to avoid importing full epaper stack in unit tests.
@dataclass
class _StubIconMenuEntry:
    key: str
    label: str
    icon_name: str
    enabled: bool = True
    selectable: bool = True
    height_ratio: float = 1.0
    max_height: int = None
    icon_size: int = None
    layout: str = "horizontal"
    font_size: int = 16
    bold: bool = False
    border_width: int = 2
    description: str = None
    description_font_size: int = 11

epaper_module = types.ModuleType("DGTCentaurMods.epaper")
icon_menu_module = types.ModuleType("DGTCentaurMods.epaper.icon_menu")
icon_menu_module.IconMenuEntry = _StubIconMenuEntry

class _StubIconMenuWidget:
    pass

icon_menu_module.IconMenuWidget = _StubIconMenuWidget
epaper_module.icon_menu = icon_menu_module
sys.modules.setdefault("DGTCentaurMods.epaper", epaper_module)
sys.modules.setdefault("DGTCentaurMods.epaper.icon_menu", icon_menu_module)

# Stub SplashScreen for Chromecast menu import chain
epaper_module.SplashScreen = MagicMock()
sys.modules["DGTCentaurMods.epaper"] = epaper_module

# Stub managers.menu to avoid pulling full stack (numpy, etc.).
managers_menu_module = types.ModuleType("DGTCentaurMods.managers.menu")
class _StubMenuSelection:
    def __init__(self, key: str):
        self.key = key
        self.result_type = None
        self.is_break = False
managers_menu_module.MenuSelection = _StubMenuSelection
def _stub_is_break_result(result):
    return False
managers_menu_module.is_break_result = _stub_is_break_result
sys.modules.setdefault("DGTCentaurMods.managers.menu", managers_menu_module)
sys.modules.setdefault("DGTCentaurMods.managers", types.ModuleType("DGTCentaurMods.managers"))

from DGTCentaurMods.menus.hand_brain_menu import build_hand_brain_mode_entries
from DGTCentaurMods.menus.hand_brain_menu import (
    build_hand_brain_mode_toggle_entry,
    toggle_hand_brain_mode,
)


class TestHandBrainMenuIcons(unittest.TestCase):
    """Tests ensuring Hand+Brain mode menu entries use checkbox icons."""

    def test_reverse_mode_entry_uses_checkbox_icon(self):
        """Reverse mode entry uses checkbox icon.

        Expected failure message: AssertionError because icon_name was 'engine'.
        Failure reason: reverse mode menu entry currently uses the engine icon instead of a checkbox.
        """
        entries = build_hand_brain_mode_entries("reverse")
        reverse_entry = next(entry for entry in entries if entry.key == "reverse")
        normal_entry = next(entry for entry in entries if entry.key == "normal")

        self.assertEqual(reverse_entry.icon_name, "checkbox_checked")
        self.assertEqual(normal_entry.icon_name, "checkbox_empty")

    def test_normal_mode_entry_uses_checkbox_icon(self):
        """Normal mode entry uses checkbox icon.

        Expected failure message: AssertionError because icon_name was 'engine'.
        Failure reason: normal mode menu entry currently uses the engine icon instead of a checkbox.
        """
        entries = build_hand_brain_mode_entries("normal")
        normal_entry = next(entry for entry in entries if entry.key == "normal")
        reverse_entry = next(entry for entry in entries if entry.key == "reverse")

        self.assertEqual(normal_entry.icon_name, "checkbox_checked")
        self.assertEqual(reverse_entry.icon_name, "checkbox_empty")

    def test_toggle_entry_uses_checkbox(self):
        """Toggle entry uses checkbox to show reverse state."""
        reverse_entry = build_hand_brain_mode_toggle_entry("reverse")
        normal_entry = build_hand_brain_mode_toggle_entry("normal")
        self.assertEqual(reverse_entry.icon_name, "checkbox_checked")
        self.assertEqual(normal_entry.icon_name, "checkbox_empty")

    def test_toggle_function_flips_modes(self):
        """Toggle helper flips between normal and reverse."""
        self.assertEqual(toggle_hand_brain_mode("normal"), "reverse")
        self.assertEqual(toggle_hand_brain_mode("reverse"), "normal")

