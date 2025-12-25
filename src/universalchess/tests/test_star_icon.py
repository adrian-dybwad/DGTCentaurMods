"""Tests for the 'star' icon used by the display brightness setting.

This test must run on non-RPi environments. Importing `DGTCentaurMods.epaper`
normally triggers hardware initialization via `DGTCentaurMods.epaper.__init__`,
so the test stubs the `DGTCentaurMods.epaper` package to load `icon_button.py`
without importing the full epaper stack.
"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image, ImageDraw


def _import_icon_button_widget():
    """Import IconButtonWidget without importing DGTCentaurMods.epaper.__init__."""
    # Create a stub package for DGTCentaurMods.epaper so Python won't execute its __init__.py
    epaper_pkg = types.ModuleType("DGTCentaurMods.epaper")
    epaper_dir = Path(__file__).resolve().parents[1] / "epaper"
    epaper_pkg.__path__ = [str(epaper_dir)]  # mark as package
    sys.modules["DGTCentaurMods.epaper"] = epaper_pkg

    # Also stub DGTCentaurMods.epaper.framework to prevent its __init__.py from importing hardware.
    framework_pkg = types.ModuleType("DGTCentaurMods.epaper.framework")
    framework_dir = epaper_dir / "framework"
    framework_pkg.__path__ = [str(framework_dir)]
    sys.modules["DGTCentaurMods.epaper.framework"] = framework_pkg

    # Now import the submodule directly
    from universalchess.epaper.icon_button import IconButtonWidget  # type: ignore

    return IconButtonWidget


class TestStarIcon(unittest.TestCase):
    """Ensure the star icon can be rendered without errors.

    Expected failure message: Exception during render due to missing icon handler.
    Failure reason: icon_name 'star' not implemented in IconButtonWidget._draw_icon.
    """

    def test_star_icon_draws_polygon(self):
        """Rendering a button with icon_name='star' draws a star polygon."""
        IconButtonWidget = _import_icon_button_widget()

        # Create widget (don't render full widget, just test _draw_star_icon directly)
        mock_draw = MagicMock(spec=ImageDraw.ImageDraw)

        widget = IconButtonWidget(
            0, 0, 128, 64,
            update_callback=lambda *a, **k: None,
            key="led_brightness",
            label="LED: 5",
            icon_name="star",
            selected=False,
        )

        # Call the star icon drawing method directly
        widget._draw_star_icon(mock_draw, x=32, y=32, size=45, line_color=0)

        # Verify polygon was called (star is drawn with outline and fill)
        self.assertGreaterEqual(mock_draw.polygon.call_count, 1, 
                                 "polygon should be called at least once")
        
        # Check the first call has 10 vertices (5-pointed star has 5 outer + 5 inner)
        first_call = mock_draw.polygon.call_args_list[0]
        points = first_call[0][0]  # First positional arg is the points list
        self.assertEqual(len(points), 10, "Star should have 10 vertices")


