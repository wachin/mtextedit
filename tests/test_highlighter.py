"""Tests for theme-driven Markdown highlighting (VNote Native theme).

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

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtGui import QFont, QTextCursor, QTextDocument
from PyQt6.QtWidgets import QApplication, QTextEdit

from mtextedit import mdparse
from mtextedit.highlighter import MarkdownHighlighter
from mtextedit.theme import Theme, load_default


class HighlighterThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _document(self, text: str, regions=None, theme=None):
        doc = QTextDocument()
        highlighter = MarkdownHighlighter(doc, theme=theme)
        doc.setPlainText(text)
        if regions:
            highlighter.set_regions(regions)
        highlighter.rehighlight()
        return doc, highlighter

    @staticmethod
    def _format_at(block, needle: str):
        """Char format the highlighter applied at ``needle``'s position."""
        position = block.text().index(needle)
        found = None
        for entry in block.layout().formats():
            if entry.start <= position < entry.start + entry.length:
                found = entry.format
        return found

    def test_bundled_theme_is_vnotes_native(self):
        theme = load_default()
        self.assertEqual(theme.name, "Native")
        self.assertEqual(theme.syntax_style("H1").font_size, 17)
        self.assertTrue(theme.syntax_style("STRONG").bold)

    def test_heading_uses_theme_sizes(self):
        doc, _ = self._document("# Title", regions=[
            {"start": 0, "end": 0, "kind": "heading", "level": 1}])
        fmt = self._format_at(doc.firstBlock(), "Title")
        self.assertIsNotNone(fmt)
        self.assertAlmostEqual(fmt.fontPointSize(), 17.0)
        self.assertEqual(fmt.fontWeight(), QFont.Weight.Bold)
        self.assertEqual(fmt.foreground().color().name(), "#222222")

    def test_inline_styles_come_from_the_theme(self):
        doc, _ = self._document(
            "**bold** and *it* and `code` and [link](u) and ~~gone~~ and ==mark==")
        block = doc.firstBlock()

        bold = self._format_at(block, "**bold**")
        self.assertEqual(bold.fontWeight(), QFont.Weight.Bold)

        emph = self._format_at(block, "*it*")
        self.assertTrue(emph.fontItalic())

        code = self._format_at(block, "`code`")
        self.assertEqual(code.foreground().color().name(), "#8e24aa")
        self.assertTrue(code.fontFamilies())

        link = self._format_at(block, "[link](u)")
        self.assertEqual(link.foreground().color().name(), "#005fff")

        strike = self._format_at(block, "~~gone~~")
        self.assertTrue(strike.fontStrikeOut())
        self.assertEqual(strike.foreground().color().name(), "#b71c1c")

        mark = self._format_at(block, "==mark==")
        self.assertEqual(mark.background().color().name(), "#ffff76")

    def test_custom_theme_can_replace_the_default(self):
        theme = Theme.from_dict({
            "metadata": {"name": "Custom"},
            "markdown-syntax-styles": {
                "H1": {"text-color": "#ff0000", "font-size": 30, "bold": True},
            },
        })
        doc, highlighter = self._document("# Big", regions=[
            {"start": 0, "end": 0, "kind": "heading", "level": 1}], theme=theme)
        fmt = self._format_at(doc.firstBlock(), "Big")
        self.assertAlmostEqual(fmt.fontPointSize(), 30.0)
        self.assertEqual(fmt.foreground().color().name(), "#ff0000")

        # Swapping the theme at runtime restyles existing blocks.
        highlighter.set_theme(load_default())
        fmt = self._format_at(doc.firstBlock(), "Big")
        self.assertAlmostEqual(fmt.fontPointSize(), 17.0)

    def test_code_fence_region_uses_fenced_style(self):
        doc, _ = self._document("```python\nx = 1\n```", regions=[
            {"start": 0, "end": 2, "kind": "code"}])
        fmt = self._format_at(doc.findBlockByNumber(1), "x = 1")
        self.assertIsNotNone(fmt)
        self.assertEqual(fmt.foreground().color().name(), "#673ab7")


if __name__ == "__main__":
    unittest.main()


class SpanHighlightTest(unittest.TestCase):
    """Exact cmark spans replace the regex fallback once a render arrives."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _document(self, text: str):
        doc = QTextDocument()
        highlighter = MarkdownHighlighter(doc)
        doc.setPlainText(text)
        highlighter.set_spans(mdparse.parse_document(text).spans)
        return doc, highlighter

    @staticmethod
    def _format(doc, needle: str):
        return HighlighterThemeTest._format_at(doc.firstBlock(), needle)

    def test_nested_emphasis_uses_exact_spans(self):
        doc, _ = self._document("**bold *it***")
        self.assertEqual(self._format(doc, "bold").fontWeight(), QFont.Weight.Bold)
        self.assertTrue(self._format(doc, "it").fontItalic())

    def test_escaped_markers_are_not_emphasis(self):
        # cmark reports no emphasis span; with spans ready the regex fallback
        # must not run and italicise the escaped markers.
        doc, _ = self._document(r"\*plain\*")
        self.assertIsNone(self._format(doc, "plain"))

    def test_code_span_with_inner_backtick(self):
        doc, _ = self._document("``a`b``")
        fmt = self._format(doc, "a`b")
        self.assertEqual(fmt.foreground().color().name(), "#8e24aa")

    def test_link_with_parentheses_in_destination(self):
        doc, _ = self._document("[x](https://e.test/a_(b))")
        fmt = self._format(doc, "x")
        self.assertEqual(fmt.foreground().color().name(), "#005fff")

    def test_markers_are_cropped_off_the_cursor_line(self):
        doc, highlighter = self._document("line one\n\nx **bold** y")
        block = doc.findBlockByNumber(2)
        marker = HighlighterThemeTest._format_at(block, "**")
        self.assertEqual(marker.foreground().color().alpha(), 0)
        self.assertLess(marker.fontLetterSpacing(), 0)

        highlighter.set_cursor_line(2)
        marker = HighlighterThemeTest._format_at(block, "**")
        self.assertEqual(marker.foreground().color().alpha(), 255)
        self.assertEqual(marker.fontWeight(), QFont.Weight.Bold)

        highlighter.set_cursor_line(0)
        highlighter.set_conceal_markers(False)
        marker = HighlighterThemeTest._format_at(block, "**")
        self.assertEqual(marker.foreground().color().alpha(), 255)

    def test_cropped_markers_have_zero_advance(self):
        text = "line one\n\nx **bold** y"
        editor = QTextEdit()
        editor.resize(400, 160)
        editor.setPlainText(text)
        highlighter = MarkdownHighlighter(editor.document())
        highlighter.set_spans(mdparse.parse_document(text).spans)
        highlighter.set_cursor_line(0)
        editor.show()
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()

        block = editor.document().findBlockByNumber(2)
        start = block.text().index("**")
        after = start + 2

        def x_at(position: int) -> float:
            cursor = QTextCursor(block)
            cursor.setPosition(block.position() + position)
            return editor.cursorRect(cursor).x()

        self.assertAlmostEqual(x_at(start), x_at(after), delta=1.0)

        highlighter.set_cursor_line(2)
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()
        self.assertGreater(x_at(after) - x_at(start), 4.0)


if __name__ == "__main__":
    unittest.main()
