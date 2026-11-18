"""Tests for the host-supplied pasted-image hook on ``MTextEdit``.

Run from ``libs/mtextedit``::

    QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PyQt6.QtCore import QMimeData
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from mtextedit import MTextEdit


class ImagePasteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pasted_image_inserts_markdown_link(self):
        editor = MTextEdit()
        seen: list[QImage] = []
        editor.set_image_paster(
            lambda image: seen.append(image) or "vx_assets/x/pic.png")
        mime = QMimeData()
        mime.setImageData(QImage(4, 4, QImage.Format.Format_RGB32))
        editor.insertFromMimeData(mime)
        self.assertEqual(editor.toPlainText(), "![](vx_assets/x/pic.png)")
        self.assertEqual(len(seen), 1)

    def test_plain_text_paste_unchanged(self):
        editor = MTextEdit()
        editor.set_image_paster(lambda image: "unused")
        mime = QMimeData()
        mime.setText("hello")
        editor.insertFromMimeData(mime)
        self.assertEqual(editor.toPlainText(), "hello")

    def test_declining_paster_does_not_insert_markdown(self):
        editor = MTextEdit()
        editor.set_image_paster(lambda image: None)
        mime = QMimeData()
        mime.setImageData(QImage(4, 4, QImage.Format.Format_RGB32))
        editor.insertFromMimeData(mime)
        self.assertNotIn("![](", editor.toPlainText())


if __name__ == "__main__":
    unittest.main()
