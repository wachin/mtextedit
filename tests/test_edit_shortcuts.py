"""Editing shortcuts: bold, italic, link, inline code and strikethrough."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from mtextedit import MTextEdit


class EditShortcutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _editor(self, text: str = "") -> MTextEdit:
        editor = MTextEdit()
        editor.setPlainText(text)
        editor.resize(400, 200)
        editor.show()
        editor.setFocus()
        return editor

    def _select(self, editor: MTextEdit, start: int, end: int) -> None:
        cursor = QTextCursor(editor.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)

    def test_bold_from_an_empty_caret(self):
        editor = self._editor()
        QTest.keyClick(editor, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(editor, "bold")
        self.assertEqual(editor.toPlainText(), "**bold**")

    def test_bold_wraps_and_unwraps_a_selection(self):
        editor = self._editor("bold")
        self._select(editor, 0, 4)
        QTest.keyClick(editor, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.toPlainText(), "**bold**")

        QTest.keyClick(editor, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.toPlainText(), "bold")

    def test_bold_unwraps_markers_outside_the_selection(self):
        editor = self._editor("**bold**")
        self._select(editor, 2, 6)
        QTest.keyClick(editor, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.toPlainText(), "bold")

    def test_italic(self):
        editor = self._editor("ital")
        self._select(editor, 0, 4)
        QTest.keyClick(editor, Qt.Key.Key_I, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.toPlainText(), "*ital*")

    def test_link_puts_the_caret_inside_the_destination(self):
        editor = self._editor("site")
        self._select(editor, 0, 4)
        QTest.keyClick(editor, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.toPlainText(), "[site]()")
        QTest.keyClicks(editor, "https://x.test")
        self.assertEqual(editor.toPlainText(), "[site](https://x.test)")

    def test_inline_code(self):
        editor = self._editor()
        QTest.keyClick(editor, Qt.Key.Key_QuoteLeft,
                       Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(editor, "code")
        self.assertEqual(editor.toPlainText(), "`code`")

    def test_strikethrough(self):
        editor = self._editor("gone")
        self._select(editor, 0, 4)
        QTest.keyClick(editor, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier
                       | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(editor.toPlainText(), "~~gone~~")

    def test_plain_typing_is_unaffected(self):
        editor = self._editor()
        QTest.keyClicks(editor, "hello")
        self.assertEqual(editor.toPlainText(), "hello")

    def test_heading_levels_toggle(self):
        editor = self._editor("Title")
        QTest.keyClick(editor, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.toPlainText(), "# Title")
        QTest.keyClick(editor, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.toPlainText(), "## Title")
        QTest.keyClick(editor, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.toPlainText(), "Title")

    def test_unordered_list_over_a_selection(self):
        editor = self._editor("one\ntwo")
        self._select(editor, 0, len(editor.toPlainText()))
        QTest.keyClick(editor, Qt.Key.Key_8, Qt.KeyboardModifier.ControlModifier
                       | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(editor.toPlainText(), "- one\n- two")
        QTest.keyClick(editor, Qt.Key.Key_8, Qt.KeyboardModifier.ControlModifier
                       | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(editor.toPlainText(), "one\ntwo")

    def test_quote_and_task_list(self):
        editor = self._editor("note")
        QTest.keyClick(editor, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier
                       | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(editor.toPlainText(), "> note")

        editor = self._editor("todo")
        QTest.keyClick(editor, Qt.Key.Key_9, Qt.KeyboardModifier.ControlModifier
                       | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(editor.toPlainText(), "- [ ] todo")

    def test_ordered_list(self):
        editor = self._editor("first")
        QTest.keyClick(editor, Qt.Key.Key_7, Qt.KeyboardModifier.ControlModifier
                       | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(editor.toPlainText(), "1. first")


if __name__ == "__main__":
    unittest.main()
