"""Tests for the VNote-style theme loader (format only, no copied data).

Run from ``libs/mtextedit``::

    QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mtextedit.theme import Theme, ThemeError

FIXTURE = {
    "metadata": {"name": "Fixture", "type": "vtextedit"},
    "markdown-syntax-styles": {
        "H1": {"text-color": "#222222", "bold": True, "font-size": 17},
        "H2": {"text-color": "#222222", "bold": True, "font-size": 16},
        "STRONG": {"bold": True},
        "EMPH": {"italic": True},
        "CODE": {"text-color": "#8e24aa", "font-family": "monospace"},
        "TABLEBORDER": {"text-color": "#d33682", "background-color": "#e0e0e0"},
        "//comment": "not a style",
    },
    "markdown-editor-styles": {
        "Text": {"text-color": "#000000"},
        "ConcealedText": {"text-color": "#999999"},
    },
}


class ThemeTest(unittest.TestCase):
    def _write(self, payload) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "fixture.theme"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_parses_syntax_styles(self):
        theme = Theme.from_dict(FIXTURE)
        self.assertEqual(theme.name, "Fixture")
        h1 = theme.syntax_style("H1")
        self.assertTrue(h1.bold)
        self.assertEqual(h1.font_size, 17)
        self.assertEqual(h1.color, "#222222")
        self.assertTrue(theme.syntax_style("EMPH").italic)
        self.assertEqual(theme.syntax_style("CODE").font_family, "monospace")
        border = theme.syntax_style("TABLEBORDER")
        self.assertEqual(border.color, "#d33682")
        self.assertEqual(border.background, "#e0e0e0")

    def test_parses_editor_styles(self):
        theme = Theme.from_dict(FIXTURE)
        self.assertEqual(theme.editor_style("ConcealedText").color, "#999999")
        self.assertIn("Text", theme.editor_names)

    def test_unknown_style_is_inherit(self):
        theme = Theme.from_dict(FIXTURE)
        unknown = theme.syntax_style("NOPE")
        self.assertIsNone(unknown.color)
        self.assertFalse(unknown.bold)
        self.assertIsNone(unknown.font_size)

    def test_comment_keys_are_skipped(self):
        theme = Theme.from_dict(FIXTURE)
        self.assertNotIn("//comment", theme.syntax_names)

    def test_loads_from_disk(self):
        theme = Theme.load(self._write(FIXTURE))
        self.assertEqual(theme.syntax_style("H2").font_size, 16)

    def test_rejects_invalid_themes(self):
        with self.assertRaises(ThemeError):
            Theme.from_dict({"metadata": {"name": "empty"}})
        with self.assertRaises(ThemeError):
            Theme.from_dict({"markdown-syntax-styles": []})
        with self.assertRaises(ThemeError):
            Theme.load(self._write({"unrelated": True}))

    def test_missing_file(self):
        with self.assertRaises(ThemeError):
            Theme.load("/nonexistent/theme.theme")


if __name__ == "__main__":
    unittest.main()
