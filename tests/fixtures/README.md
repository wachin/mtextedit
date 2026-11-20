# Golden document fixture

`golden-document.md` is adapted from MDHoriZon's ([https://github.com/wachin/MDHoriZon](https://github.com/wachin/MDHoriZon))
`tests/fixtures/Golden-Test-Document.md` (same author). It is a rendering
regression document, not application content.

The original Vitest/React test checks a DOM snapshot, heading anchors,
sanitization, KaTeX and Mermaid. Those are React-specific contracts and do not
apply to marktux; `test_golden_document.py` instead pins the parser, the
cmark HTML output and the editor/preview pipeline.

`golden-document.html` is the exact `render_html()` output (task lists
enabled). Regenerate it deliberately when the HTML contract changes:

```bash
cd libs/mtextedit
python3 -c "import sys; sys.path.insert(0, '.'); from mtextedit import mdparse; print(mdparse.render_html(open('tests/fixtures/golden-document.md', encoding='utf-8').read()), end='')" > tests/fixtures/golden-document.html
```
