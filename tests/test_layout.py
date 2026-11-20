"""Tests for the custom layout: concealment, mapping, hit test, editing.

Run from ``libs/mtextedit``::

    QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -t .
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

from PyQt6.QtCore import QEventLoop, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QTextEdit

from mtextedit import MTextEdit, mdparse
from mtextedit.layout import MarkdownDocumentLayout


class LayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _pump(self, ms: int = 30) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def _editor(self, text: str, cursor_block: int = -1):
        editor = QTextEdit()
        layout = MarkdownDocumentLayout(editor.document())
        editor.document().setDocumentLayout(layout)
        editor.setPlainText(text)
        layout.set_spans(mdparse.parse_document(text).spans)
        layout.set_cursor_block(cursor_block)
        editor.resize(500, 200)
        editor.show()
        self._pump()
        return editor, layout

    def test_markers_are_removed_from_the_display_text(self):
        text = "x **bold** and `code` y"
        _, layout = self._editor(text, cursor_block=-1)
        entry = layout._blocks[0]
        self.assertEqual(entry.display, "x bold and code y")
        self.assertNotIn("**", entry.display)
        self.assertNotIn("`", entry.display)

    def test_cursor_line_shows_the_markers_again(self):
        text = "x **bold** y"
        _, off = self._editor(text, cursor_block=-1)
        width_off = off.blockBoundingRect(off.document().firstBlock()).width()

        _editor, on = self._editor(text, cursor_block=0)
        width_on = on.blockBoundingRect(on.document().firstBlock()).width()
        self.assertLess(width_off, width_on)
        self.assertIn("**", on._blocks[0].display)

    def test_hit_test_maps_display_to_document_positions(self):
        text = "x **bold** y"
        _, layout = self._editor(text, cursor_block=-1)
        entry = layout._blocks[0]
        margin = layout._margin()
        line = entry.layout.lineAt(0)
        x_bold = margin + line.cursorToX(2)[0]  # 'b' in "x bold y"
        y = layout.blockBoundingRect(entry.block).center().y()
        position = layout.hitTest(QPointF(x_bold, y))
        self.assertEqual(text[position:position + 4], "bold")

    def test_typing_and_clicking_work(self):
        editor, layout = self._editor("x **bold** y", cursor_block=0)
        editor.setFocus()
        QTest.keyClicks(editor, "Z")
        self.assertTrue(editor.toPlainText().startswith("Zx **bold**"))
        layout.set_cursor_block(0)
        QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(60, 8))
        self.assertGreater(editor.textCursor().position(), 0)

    def test_selection_range_stays_in_document_coordinates(self):
        editor, _layout = self._editor("x **bold** y", cursor_block=0)
        cursor = QTextCursor(editor.document())
        cursor.setPosition(0)
        cursor.setPosition(9, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        self.assertEqual(editor.textCursor().selectionStart(), 0)
        self.assertEqual(editor.textCursor().selectionEnd(), 9)
        self._pump()
        self.assertTrue(editor.grab().width() > 0)

    def test_document_size_grows_with_new_lines(self):
        editor, layout = self._editor("one\ntwo\nthree", cursor_block=-1)
        height = layout.documentSize().height()
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("\nfour")
        self._pump()
        self.assertGreater(layout.documentSize().height(), height)

    def test_mtextedit_can_run_on_the_custom_layout(self):
        editor = MTextEdit(use_custom_layout=True)
        editor.resize(500, 160)
        editor.setPlainText("x **bold** y")
        editor.show()
        self._pump()
        self.assertIsNotNone(editor._custom_layout)
        self.assertIsNone(editor._highlighter.document())

        editor._custom_layout.set_spans(mdparse.parse_document("x **bold** y").spans)
        editor._custom_layout.set_cursor_block(-1)
        self._pump()
        self.assertEqual(editor._custom_layout._blocks[0].display, "x bold y")

        editor.setFocus()
        QTest.keyClicks(editor, "Z")
        self.assertTrue(editor.toPlainText().startswith("Zx **bold**"))

    def test_hit_test_second_line(self):
        editor, layout = self._editor("one\ntwo\nthree", cursor_block=-1)
        second = editor.document().findBlockByNumber(1)
        rect = layout.blockBoundingRect(second)
        position = layout.hitTest(QPointF(rect.left() + 2, rect.center().y()))
        self.assertGreaterEqual(position, second.position())
        self.assertLessEqual(position, second.position() + len(second.text()))

    def test_preview_margin_is_reserved(self):
        editor, layout = self._editor("```\ncode\n```", cursor_block=-1)
        block = editor.document().findBlockByNumber(0)
        block_format = block.blockFormat()
        block_format.setTopMargin(40)
        QTextCursor(block).setBlockFormat(block_format)
        layout.documentChanged(0, 0, 0)
        rect = layout.blockBoundingRect(block)
        entry = layout._blocks[0]
        self.assertGreaterEqual(rect.height(), 40)
        self.assertAlmostEqual(entry.text_top, rect.top() + 40)

    def test_mtextedit_defaults_to_the_custom_layout(self):
        editor = MTextEdit()
        self.assertIsNotNone(editor._custom_layout)
        self.assertIsNone(editor._highlighter.document())


if __name__ == "__main__":
    unittest.main()
