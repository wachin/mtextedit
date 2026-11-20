"""Tests for the parse IR (blocks + exact spans) and its backends.

Run from ``libs/mtextedit``::

    QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from hypothesis import given, settings
from hypothesis import strategies as st

from mtextedit import mdparse

HAS_CMARK = mdparse.backend_name() == "cmark"


def _span(ir, style):
    spans = [s for s in ir.spans if s.style == style]
    return spans[0] if spans else None


@unittest.skipUnless(HAS_CMARK, "VNote's cmark binding is not built")
class CmarkIRTest(unittest.TestCase):
    def test_strong_span_covers_the_delimiters(self):
        ir = mdparse.parse("a **bold** b\n")
        span = _span(ir, "strong")
        self.assertIsNotNone(span)
        self.assertEqual(ir.source[span.start:span.end], "**bold**")
        self.assertEqual(ir.source[span.content_start:span.content_end], "bold")

    def test_unicode_columns_are_byte_offsets_in_cmark(self):
        # "é" is one character but two UTF-8 bytes; the span must still start
        # at the character offset of the first "*".
        ir = mdparse.parse("é **x**\n")
        span = _span(ir, "strong")
        self.assertIsNotNone(span)
        self.assertEqual(ir.source[span.start:span.end], "**x**")
        self.assertEqual(ir.source[span.content_start:span.content_end], "x")

    def test_code_span_and_content(self):
        ir = mdparse.parse("`x` and ``y``\n")
        spans = [s for s in ir.spans if s.style == "code"]
        self.assertEqual([ir.source[s.start:s.end] for s in spans], ["`x`", "``y``"])
        self.assertEqual([ir.source[s.content_start:s.content_end] for s in spans],
                         ["x", "y"])

    def test_link_span(self):
        ir = mdparse.parse("see [text](https://x.test) now\n")
        span = _span(ir, "link")
        self.assertIsNotNone(span)
        self.assertEqual(ir.source[span.start:span.end], "[text](https://x.test)")
        self.assertEqual(ir.source[span.content_start:span.content_end], "text")

    def test_emphasis_and_strike(self):
        ir = mdparse.parse("*a* ~~b~~ ==c==\n")
        self.assertEqual(ir.source[_span(ir, "emph").start:_span(ir, "emph").end], "*a*")
        self.assertEqual(ir.source[_span(ir, "strike").start:_span(ir, "strike").end],
                         "~~b~~")
        self.assertEqual(ir.source[_span(ir, "mark").start:_span(ir, "mark").end],
                         "==c==")

    def test_block_ranges(self):
        ir = mdparse.parse("# Title\n\nparagraph\n")
        headings = [b for b in ir.blocks if b.kind == "heading"]
        self.assertEqual(len(headings), 1)
        self.assertEqual((headings[0].start_line, headings[0].end_line), (0, 0))
        self.assertEqual(headings[0].level, 1)
        paragraphs = [b for b in ir.blocks if b.kind == "paragraph"]
        self.assertTrue(any((b.start_line, b.end_line) == (2, 2) for b in paragraphs))

    def test_spans_for_line(self):
        ir = mdparse.parse("plain\n\n**bold**\n")
        self.assertEqual(ir.spans_for_line(0), [])
        self.assertEqual([s.style for s in ir.spans_for_line(2)], ["strong"])

    @settings(max_examples=40, deadline=None)
    @given(prefix=st.text(alphabet=st.sampled_from("ab éñ😀 "), max_size=12),
           suffix=st.text(alphabet=st.sampled_from("ab éñ😀 "), max_size=12))
    def test_strong_span_is_always_exact(self, prefix, suffix):
        source = f"{prefix}**x**{suffix}"
        ir = mdparse.parse(source)
        spans = [s for s in ir.spans if s.style == "strong"]
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(source[span.start:span.end], "**x**")
        self.assertEqual(source[span.content_start:span.content_end], "x")
        self.assertLessEqual(0, span.start)
        self.assertLessEqual(span.end, len(source))
        self.assertLess(span.start, span.end)


class ParsedDocumentTest(unittest.TestCase):
    def test_tokens_and_spans_come_from_one_parse(self):
        source = "a **b** and `c` and ~~d~~\n"
        parsed = mdparse.parse_document(source)
        self.assertTrue(parsed.tokens)
        styles = {span.style for span in parsed.spans}
        self.assertTrue({"strong", "code", "strike"} <= styles)

        ir = mdparse.parse(source)
        self.assertEqual(
            [(span.style, span.start, span.end) for span in parsed.spans],
            [(span.style, span.start, span.end) for span in ir.spans],
        )


class RequiredBackendTest(unittest.TestCase):
    def test_parse_requires_vnotes_cmark(self):
        with mock.patch.object(mdparse, "cmark_backend", lambda: None):
            with self.assertRaises(RuntimeError):
                mdparse.parse("x")
            with self.assertRaises(RuntimeError):
                mdparse.parse_tokens("x")

    def test_parse_never_raises_on_odd_input(self):
        for source in ("", "\n\n", "**", "```\nunclosed", "[x](", "\x00",
                       "# \u2029 emoji \U0001F600"):
            ir = mdparse.parse(source)
            self.assertIsInstance(ir.blocks, list)
            self.assertIsInstance(ir.spans, list)


@unittest.skipUnless(HAS_CMARK, "VNote's cmark binding is not built")
class TokenStreamTest(unittest.TestCase):
    def test_heading_and_inline_tokens(self):
        tokens = mdparse.parse_tokens("# Title\n\n**bold** and `code`\n")
        types = [token.type for token in tokens]
        self.assertEqual(types[:3], ["heading_open", "inline", "heading_close"])
        self.assertEqual(tokens[0].tag, "h1")
        self.assertEqual(tokens[0].map, (0, 1))
        self.assertEqual(tokens[1].content, "Title")
        inline = tokens[4]
        child_types = [child.type for child in inline.children]
        self.assertIn("strong_open", child_types)
        self.assertIn("code_inline", child_types)

    def test_fenced_code_carries_language_and_runs(self):
        tokens = mdparse.parse_tokens("```python\nx = 1\n```\n")
        self.assertEqual(len(tokens), 1)
        fence = tokens[0]
        self.assertEqual(fence.type, "fence")
        self.assertEqual(fence.info, "python")
        self.assertEqual(fence.content, "x = 1\n")
        self.assertTrue(fence.meta.get("highlight"))

    def test_indented_code_has_no_language_or_runs(self):
        tokens = mdparse.parse_tokens("    x = 1\n")
        self.assertEqual(tokens[0].type, "code_block")
        self.assertEqual(tokens[0].info, "")
        self.assertFalse(tokens[0].meta.get("highlight"))

    def test_table_skips_delimiter_row_and_keeps_alignment(self):
        tokens = mdparse.parse_tokens("| a | b |\n|:--|--:|\n| 1 | 2 |\n")
        self.assertEqual(tokens[0].type, "table_open")
        rows = [token for token in tokens if token.type == "tr_open"]
        self.assertEqual(len(rows), 2)  # header + body, delimiter skipped
        headers = [token for token in tokens if token.type == "th_open"]
        self.assertEqual([dict(token.attrs)["style"] for token in headers],
                         ["text-align:left", "text-align:right"])

    def test_image_token_carries_source_and_alt(self):
        tokens = mdparse.parse_tokens('![alt](img.png "t")\n')
        inline = tokens[1]
        image = inline.children[0]
        self.assertEqual(image.type, "image")
        attrs = dict(image.attrs)
        self.assertEqual(attrs["src"], "img.png")
        self.assertEqual(attrs["alt"], "alt")
        self.assertEqual(attrs["title"], "t")

    def test_list_kinds(self):
        bullet = mdparse.parse_tokens("- a\n")
        ordered = mdparse.parse_tokens("1. a\n")
        self.assertIn("bullet_list_open", [token.type for token in bullet])
        self.assertIn("ordered_list_open", [token.type for token in ordered])

    def test_render_html(self):
        html = mdparse.render_html("**x**")
        self.assertIn("<strong>x</strong>", html)


if __name__ == "__main__":
    unittest.main()
