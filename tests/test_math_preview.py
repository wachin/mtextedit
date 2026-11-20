"""Optional block-math previews (matplotlib extra)."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication

from mtextedit import MTextEdit, inplace, mdparse
from mtextedit._markdown import collect_block_regions

HAS_MATPLOTLIB = importlib.util.find_spec("matplotlib") is not None


@unittest.skipUnless(HAS_MATPLOTLIB, "matplotlib is an optional extra")
class MathPreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_block_formula_becomes_a_pixmap_spec(self):
        text = "$$\n\\int_0^1 x\\,dx = \\frac{1}{2}\n$$\n"
        parsed = mdparse.parse_document(text)
        specs = inplace.measure_specs(inplace.build_specs(parsed.tokens), 600)
        self.assertTrue(specs)
        spec = specs[0]
        self.assertEqual(spec.kind, "math")
        self.assertGreater(spec.height, 0)
        self.assertIsNotNone(spec.data.get("pixmap"))
        self.assertFalse(spec.data["pixmap"].isNull())

    def test_editor_embeds_the_formula_off_the_cursor_line(self):
        text = "before\n\n$$\nx^2\n$$\n\nafter\n"
        editor = MTextEdit()
        editor.setPlainText(text)
        parsed = mdparse.parse_document(text)
        layout = editor._custom_layout
        layout.set_spans(parsed.spans)
        layout.set_regions(collect_block_regions(parsed.tokens))
        specs = inplace.measure_specs(inplace.build_specs(parsed.tokens), 860)
        editor._apply_specs(specs)
        layout._refresh()

        start = specs[0].block
        self.assertEqual(layout._blocks[start].display, "")
        self.assertGreater(layout._blocks[start].height, 0)

        editor.setTextCursor(
            QTextCursor(editor.document().findBlockByNumber(start + 1)))
        layout._refresh()
        self.assertIn("x^2", layout._blocks[start + 1].display)


if __name__ == "__main__":
    unittest.main()
