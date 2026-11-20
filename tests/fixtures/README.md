# Golden document fixture

`golden-document.md` is adapted from MDHoriZon's ([https://github.com/wachin/MDHoriZon](https://github.com/wachin/MDHoriZon))
`tests/fixtures/Golden-Test-Document.md` (same author). It is a rendering
regression document, not application content.

The original Vitest/React test checks a DOM snapshot, heading anchors,
sanitization, KaTeX and Mermaid. Those are React-specific contracts and do not
apply to marktux; `test_golden_document.py` instead pins the parser, the
cmark HTML output and the editor/preview pipeline.
