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

from PyQt6.QtGui import QFont, QTextDocument
from PyQt6.QtWidgets import QApplication

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
        for entry in block.layout().formats():
            if entry.start <= position < entry.start + entry.length:
                return entry.format
        return None

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
