import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from raggg.desktop.main_window import AILoaderOverlay


class LoaderThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def render_corner_lightness(self, theme: str) -> int:
        overlay = AILoaderOverlay(text="生成中")
        overlay.resize(480, 320)
        image = QImage(overlay.size(), QImage.Format_ARGB32)
        image.fill(0)
        with patch("raggg.desktop.widgets.get_theme", return_value=theme):
            overlay.render(image)
        overlay.close()
        return image.pixelColor(12, 12).lightness()

    def test_loader_background_follows_current_theme(self) -> None:
        light_lightness = self.render_corner_lightness("light")
        dark_lightness = self.render_corner_lightness("dark")

        self.assertGreater(light_lightness, 180)
        self.assertLess(dark_lightness, 80)
        self.assertGreater(light_lightness - dark_lightness, 120)


if __name__ == "__main__":
    unittest.main()
