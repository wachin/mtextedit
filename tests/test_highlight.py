"""Tests for Pygments token runs and their painting (D12/D14).

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

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QTextDocument
from PyQt6.QtWidgets import QApplication

from mtextedit import mdparse
from mtextedit._markdown import build_document
from mtextedit.code_style import CODE_TEXT, CONSTANT, KEYWORD, STRING
from mtextedit.highlight import (
    MAX_HIGHLIGHT_CHARS,
    _expand_tabs,
    _merge,
    code_runs,
)
from mtextedit.inplace import PreviewSpec, _paint_code, build_specs, measure_specs
from mtextedit.renderer.render_worker import RenderWorker

SOURCE = "def f(x):\n    return 'v' + 1  # note\n"


def _text_of(runs) -> list[str]:
    return ["".join(text for text, _colour in line) for line in runs]


class CodeRunsTest(unittest.TestCase):
    def test_runs_reproduce_the_source_lines(self):
        runs = code_runs(SOURCE, "python")
        self.assertEqual(len(runs), 2)
        self.assertEqual(_text_of(runs), SOURCE.rstrip("\n").split("\n"))

    def test_runs_use_the_shared_palette(self):
        runs = code_runs(SOURCE, "python")
        colours = {colour for line in runs for _text, colour in line}
        self.assertIn(KEYWORD, colours)   # def / return
        self.assertIn(STRING, colours)    # 'v'
        self.assertIn(CODE_TEXT, colours)  # punctuation, spaces

    def test_unknown_language_has_no_runs(self):
        self.assertEqual(code_runs(SOURCE, "no-such-language"), [])

    def test_empty_language_has_no_runs(self):
        self.assertEqual(code_runs(SOURCE, ""), [])

    def test_oversized_fence_is_not_highlighted(self):
        big = "x = 1\n" * (MAX_HIGHLIGHT_CHARS // 4)
        self.assertGreater(len(big), MAX_HIGHLIGHT_CHARS)
        self.assertEqual(code_runs(big, "python"), [])

    def test_tabs_expand_to_four_column_stops(self):
        self.assertEqual(
            _expand_tabs([("\tpass", "#111111")]),
            [("    pass", "#111111")],
        )
        # Column tracking continues across runs: col 5 -> next stop is 8.
        self.assertEqual(
            _expand_tabs([("\ta", "#111111"), ("\tb", "#222222")]),
            [("    a", "#111111"), ("   b", "#222222")],
        )

    def test_adjacent_runs_of_one_colour_merge(self):
        self.assertEqual(
            _merge([("a", "#111111"), ("b", "#111111"), ("c", "#222222")]),
            [("ab", "#111111"), ("c", "#222222")],
        )


class AnnotationTest(unittest.TestCase):
    def test_build_specs_carries_the_runs(self):
        tokens = mdparse.parse_tokens("```python\nx = 1\n```\n")
        specs = build_specs(tokens)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].kind, "code")
        self.assertEqual(specs[0].data["highlight"], code_runs("x = 1\n", "python"))

    def test_indented_block_is_not_annotated(self):
        tokens = mdparse.parse_tokens("    x = 1\n")
        self.assertFalse(any(tok.meta.get("highlight") for tok in tokens))


class WorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_annotates_tokens_before_emitting(self):
        captured = []
        worker = RenderWorker(1, "```python\nx = 1\n```\n", [1])
        worker.signals.done.connect(lambda *args: captured.append(args))
        worker.run()

        self.assertEqual(len(captured), 1)
        tokens = captured[0][3]
        fence = next(tok for tok in tokens if tok.type == "fence")
        self.assertTrue(fence.meta.get("highlight"))


class PaintingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _paint(spec: PreviewSpec, width: int = 420) -> QImage:
        measured = measure_specs([spec], width)
        assert measured, "spec was dropped during measurement"
        spec = measured[0]
        image = QImage(
            width, max(1, int(spec.height)), QImage.Format.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        try:
            _paint_code(painter, spec, QRectF(0, 0, width, spec.height))
        finally:
            painter.end()
        return image

    @staticmethod
    def _near(image: QImage, target: str, tolerance: int = 40) -> bool:
        want = QColor(target)
        for y in range(image.height()):
            for x in range(image.width()):
                got = image.pixelColor(x, y)
                if (abs(got.red() - want.red()) <= tolerance
                        and abs(got.green() - want.green()) <= tolerance
                        and abs(got.blue() - want.blue()) <= tolerance):
                    return True
        return False

    def _spec(self, highlight) -> PreviewSpec:
        return PreviewSpec(
            block=0, kind="code",
            data={"lang": "python", "code": SOURCE, "highlight": highlight})

    def test_painted_card_contains_token_colours(self):
        image = self._paint(self._spec(code_runs(SOURCE, "python")))
        self.assertTrue(self._near(image, KEYWORD), "keyword colour not painted")

    def test_card_without_runs_stays_monochrome(self):
        image = self._paint(self._spec(None))
        self.assertFalse(
            self._near(image, KEYWORD), "flat fallback should not use keywords")


class DocumentBuilderTest(unittest.TestCase):
    """The full-document preview shares the in-place preview's code colours."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _document(source: str, annotate: bool = True) -> QTextDocument:
        tokens = mdparse.parse_tokens(source)
        if not annotate:
            for token in tokens:
                token.meta.clear()
        doc = QTextDocument()
        build_document(tokens, doc)
        return doc

    @staticmethod
    def _block(doc: QTextDocument, text: str):
        block = doc.firstBlock()
        while block.isValid():
            if block.text() == text:
                return block
            block = block.next()
        return None

    @staticmethod
    def _fragment(block, text: str):
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid() and fragment.text() == text:
                return fragment
            it += 1
        return None

    def test_fenced_code_is_coloured(self):
        doc = self._document("```python\ndef f():\n    return 1\n```\n")
        keyword = self._fragment(self._block(doc, "def f():"), "def")
        self.assertIsNotNone(keyword)
        fmt = keyword.charFormat()
        self.assertEqual(fmt.foreground().color().name(), KEYWORD)
        self.assertEqual(fmt.fontFamily(), "monospace")

    def test_number_and_keyword_keep_distinct_colours(self):
        doc = self._document("```python\ndef f():\n    return 1\n```\n")
        block = self._block(doc, "    return 1")
        self.assertIsNotNone(block)
        self.assertEqual(
            self._fragment(block, "return").charFormat().foreground().color().name(),
            KEYWORD)
        self.assertEqual(
            self._fragment(block, "1").charFormat().foreground().color().name(),
            CONSTANT)

    def test_text_is_not_altered_by_colouring(self):
        doc = self._document("```python\ndef f():\n    return 1\n```\n")
        self.assertEqual(doc.toPlainText(), "def f():\n    return 1")

    def test_unannotated_tokens_stay_flat(self):
        doc = self._document("```python\ndef f():\n    return 1\n```\n",
                             annotate=False)
        block = self._block(doc, "def f():")
        self.assertIsNotNone(block)
        fmt = self._fragment(block, "def f():").charFormat()
        self.assertNotEqual(fmt.foreground().color().name(), KEYWORD)

    def test_heading_keeps_its_size_and_weight(self):
        doc = self._document("# Title\n", annotate=False)
        block = self._block(doc, "Title")
        self.assertIsNotNone(block)
        fmt = self._fragment(block, "Title").charFormat()
        self.assertEqual(fmt.fontWeight(), QFont.Weight.Bold)
        self.assertAlmostEqual(fmt.fontPointSize(), 18.0)

    def test_unstyled_pygments_token_falls_back(self):
        from pygments.token import Token

        from mtextedit.highlight import _colour

        # Mermaid's lexer emits Literal.Scalar.Plain, which our style omits.
        self.assertIsInstance(_colour(Token.Literal.Scalar.Plain), str)


if __name__ == "__main__":
    unittest.main()
