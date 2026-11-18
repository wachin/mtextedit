"""Regression tests for the configurable image cache (DESIGN.md D13).

Run from ``libs/mtextedit``::

    QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v

or with pytest::

    QT_QPA_PLATFORM=offscreen pytest tests -v
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from mtextedit.renderer.render_manager import RenderManager, _validate_cache_size

_IMAGE_COUNT = 8


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_image(path: Path, width: int) -> None:
    image = QImage(width, 30, QImage.Format.Format_RGB32)
    image.fill(QColor("#3366cc"))
    painter = QPainter(image)
    painter.fillRect(0, 0, 10, 10, QColor("#ff0000"))
    painter.end()
    assert image.save(str(path)), f"could not write {path}"


def _render_and_wait(manager: RenderManager, source: str) -> dict:
    """Force a render and return the ``{abs_path: QImage}`` payload."""
    loop = QEventLoop()
    result: dict = {}

    def on_images(images: dict) -> None:
        result["images"] = images
        QTimer.singleShot(0, loop.quit)

    manager.previewImagesAvailable.connect(on_images)
    manager.force_render(source)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    manager.previewImagesAvailable.disconnect(on_images)
    return result.get("images", {})


class ImageCacheConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _app()
        cls.tmp = Path(tempfile.mkdtemp(prefix="marktux_cache_"))
        for i in range(_IMAGE_COUNT):
            _make_image(cls.tmp / f"img{i}.png", 40 + i)
        cls.source = "\n\n".join(
            f"![alt{i}](img{i}.png)" for i in range(_IMAGE_COUNT)
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_default_bound(self) -> None:
        manager = RenderManager()
        self.assertEqual(manager.image_cache_max(), 32)

    def test_all_requested_images_resolve_beyond_bound(self) -> None:
        """A document larger than the cache still paints completely."""
        manager = RenderManager(image_cache_max=5)
        manager.set_base_path(str(self.tmp))

        images = _render_and_wait(manager, self.source)

        self.assertEqual(len(images), _IMAGE_COUNT)
        self.assertEqual(len(manager._image_cache), 5)

    def test_runtime_resize_evicts_immediately(self) -> None:
        manager = RenderManager(image_cache_max=5)
        manager.set_base_path(str(self.tmp))
        _render_and_wait(manager, self.source)
        self.assertEqual(len(manager._image_cache), 5)

        manager.set_image_cache_max(2)

        self.assertEqual(manager.image_cache_max(), 2)
        self.assertEqual(len(manager._image_cache), 2)

    def test_growing_bound_does_not_add_entries(self) -> None:
        manager = RenderManager(image_cache_max=2)
        manager.set_base_path(str(self.tmp))
        _render_and_wait(manager, self.source)
        self.assertEqual(len(manager._image_cache), 2)

        manager.set_image_cache_max(64)

        self.assertEqual(manager.image_cache_max(), 64)
        self.assertEqual(len(manager._image_cache), 2)

    def test_setter_rejects_bad_values_and_keeps_bound(self) -> None:
        manager = RenderManager(image_cache_max=4)
        for bad, exc in (
            (0, ValueError),
            (-1, ValueError),
            (True, TypeError),
            (2.5, TypeError),
            ("8", TypeError),
            (None, TypeError),
        ):
            with self.subTest(value=bad):
                with self.assertRaises(exc):
                    manager.set_image_cache_max(bad)
                self.assertEqual(manager.image_cache_max(), 4)

    def test_constructor_rejects_bad_values(self) -> None:
        for bad, exc in (
            (0, ValueError),
            (-1, ValueError),
            (True, TypeError),
            (2.5, TypeError),
            ("8", TypeError),
        ):
            with self.subTest(value=bad):
                with self.assertRaises(exc):
                    RenderManager(image_cache_max=bad)

    def test_validator_accepts_positive_ints(self) -> None:
        self.assertEqual(_validate_cache_size(1), 1)
        self.assertEqual(_validate_cache_size(128), 128)


if __name__ == "__main__":
    unittest.main()
