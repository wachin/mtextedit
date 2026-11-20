"""Golden-document regression test, adapted from MDHoriZon's fixture.

The original Vitest test pins a React DOM snapshot and React-only behaviour.
This one pins the parts marktux owns: the cmark token/span contract, the HTML
renderer and the editor/preview pipeline.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

from mtextedit import MTextEdit, inplace, mdparse
from mtextedit._markdown import collect_block_regions

FIXTURE = Path(__file__).with_name("fixtures") / "golden-document.md"


class GoldenDocumentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.text = FIXTURE.read_text(encoding="utf-8")
        cls.parsed = mdparse.parse_document(cls.text)
        cls.cmark = mdparse.require_cmark()
        cls.html = mdparse.render_html(
            cls.text, cls.cmark.Options.CMARK_OPT_TASKLISTS)

    def test_parser_keeps_every_section(self):
        kinds = Counter(token.type for token in self.parsed.tokens)
        self.assertEqual(kinds["heading_open"], 86)
        self.assertEqual(kinds["table_open"], 12)
        self.assertEqual(kinds["tr_open"], 43)
        self.assertEqual(kinds["fence"] + kinds["code_block"], 40)
        self.assertGreater(len(self.parsed.spans), 90)

        styles = Counter(span.style for span in self.parsed.spans)
        self.assertEqual(styles["strong"], 11)
        self.assertEqual(styles["emph"], 6)
        self.assertEqual(styles["code"], 31)
        self.assertEqual(styles["strike"], 1)
        self.assertEqual(styles["link"], 18)
        self.assertEqual(styles["image"], 14)
        self.assertEqual(styles["math"], 17)

    def test_html_renders_the_gfm_structures(self):
        self.assertEqual(self.html.count("<table"), 12)
        self.assertEqual(self.html.count("<img"), 14)
        self.assertEqual(self.html.count("<s>"), 1)
        self.assertEqual(self.html.count('type="checkbox"'), 34)
        self.assertNotIn("<script", self.html)
        self.assertNotIn("<iframe", self.html)

        tables = re.findall(r"<table.*?</table>", self.html, re.DOTALL)
        widest = max(len(re.findall(r"<th[ >]", table)) for table in tables)
        self.assertEqual(widest, 20)

        languages = set(re.findall(r'class="language-([^"]+)"', self.html))
        for language in ("typescript", "bash", "json", "mermaid",
                         "not-a-real-language"):
            self.assertIn(language, languages)

        self.assertIn('alt="This image intentionally does not exist"', self.html)
        self.assertIn('src="images/wide.png"', self.html)

    def test_preview_builds_code_table_and_image_specs(self):
        specs = inplace.build_specs(self.parsed.tokens)
        kinds = Counter(spec.kind for spec in specs)
        self.assertEqual(kinds["code"], 40)
        self.assertEqual(kinds["table"], 12)
        self.assertGreaterEqual(kinds["image"], 9)
        self.assertTrue(inplace.measure_specs(specs, 880))

    def test_editor_renders_the_whole_document(self):
        editor = MTextEdit()
        editor.setPlainText(self.text)
        editor._custom_layout.set_spans(self.parsed.spans)
        editor._custom_layout.set_regions(
            collect_block_regions(self.parsed.tokens))
        specs = inplace.measure_specs(
            inplace.build_specs(self.parsed.tokens), 880)
        editor._apply_specs(specs)
        editor.resize(900, 700)
        editor.show()
        loop = QEventLoop()
        QTimer.singleShot(100, loop.quit)
        loop.exec()

        self.assertGreater(editor._custom_layout.documentSize().height(),
                           15000)
        self.assertFalse(editor.grab().isNull())


if __name__ == "__main__":
    unittest.main()
