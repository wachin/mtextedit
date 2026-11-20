"""Image insertion dialog and the editor's alt/title flow."""

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
from mtextedit.image_dialog import ImageInsertDialog, image_markdown


class ImageDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_markdown_escapes_and_quotes(self):
        self.assertEqual(
            image_markdown("a b.png", "A [pic]", 'A "title"'),
            '![A \\[pic\\]](<a b.png> "A \\"title\\"")')
        self.assertEqual(image_markdown("pic.png", "Photo"),
                         "![Photo](pic.png)")

    def test_dialog_collects_alt_and_title(self):
        dialog = ImageInsertDialog(
            QImage(4, 4, QImage.Format.Format_RGB32), "photo")
        dialog._alt.setText("Photo")
        dialog._title.setText("A title")
        self.assertEqual(dialog.values(), ("Photo", "A title"))
        self.assertEqual(dialog.markdown("pic.png"),
                         '![Photo](pic.png "A title")')

    def test_editor_flow_uses_details_and_paster(self):
        editor = MTextEdit()
        editor.set_image_dialog_enabled(True)
        editor._image_details = lambda image, alt: ("Photo", "Title")
        editor.set_image_paster(lambda image: "assets/photo.png")
        mime = QMimeData()
        mime.setImageData(QImage(4, 4, QImage.Format.Format_RGB32))
        editor.insertFromMimeData(mime)
        self.assertEqual(editor.toPlainText(),
                         '![Photo](assets/photo.png "Title")')

    def test_cancelled_dialog_inserts_nothing(self):
        editor = MTextEdit()
        editor.set_image_dialog_enabled(True)
        editor._image_details = lambda image, alt: None
        editor.set_image_paster(lambda image: "unused")
        mime = QMimeData()
        mime.setImageData(QImage(4, 4, QImage.Format.Format_RGB32))
        editor.insertFromMimeData(mime)
        self.assertEqual(editor.toPlainText(), "")

    def test_dialog_exposes_accessible_names(self):
        dialog = ImageInsertDialog(QImage(4, 4, QImage.Format.Format_RGB32))
        self.assertEqual(dialog.accessibleName(), "Insert image")
        self.assertEqual(dialog._alt.accessibleName(), "Alternative text")
        self.assertEqual(dialog._title.accessibleName(), "Title")


if __name__ == "__main__":
    unittest.main()
