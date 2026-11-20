# mtextedit — design decisions

This document records the architectural decisions behind `mtextedit` and the
reasoning behind them, so they are not re-litigated from scratch. It is the
component-level companion to the repository `README.md`.

VNote (`external/vnote`, `libs/vtextedit`) is the reference implementation. We
reuse its *ideas*, not its C++ code.

---

## D1. Single-pane, in-place preview (no side-by-side panel)

**Decision.** The editor is one pane. There is no separate preview panel. For
the block types VNote previews, a rendered preview is drawn *inside* the editor
above its Markdown source; regular text stays as editable source.

**Context.** The first implementation used a `QSplitter` with an editor and a
`PreviewWidget` side by side. VNote and Obsidian do not present Markdown editing
as two panels; they integrate the rendered result into the editing surface.

**VNote reference.** `TextDocumentLayout`
(`libs/vtextedit/src/markdowneditor/textdocumentlayout.cpp`) reserves a vertical
band per block and paints previews for code blocks, images, math and tables.
`PreviewPlacement` (`src/include/vtextedit/preview.h`) defines
`BlockAfterSource` and `InlineAboveLine`.

**Consequences.** One central widget; the outline and notebook tree remain docks.
The optional full-document `PreviewWidget` still exists but is **not** used by
default.

---

## D2. Preview is drawn *above* the source block

**Decision.** The reserved band sits above the source block (VNote's
`InlineAboveLine` spirit), not below it.

**Rationale.** The explicit product request was "preview right above the editor."
VNote's *default* block placement is `BlockAfterSource`; we deliberately deviate
so the rendered result appears above the source being edited.

---

## D3. Editor widget is `QTextEdit` (not `QPlainTextEdit`)

**Decision.** `MTextEdit` subclasses `QTextEdit`.

**Rationale.**
* Block top-margins (`QTextBlockFormat.setTopMargin`) create the preview band;
  this needs the rich-text layout that `QTextEdit` provides. `QPlainTextEdit`
  uses `QPlainTextDocumentLayout`, which does not support block margins.
* VNote's own editor (`VTextEdit`) is a `QTextEdit` subclass.
* The markdown parse is already off-thread, so the editor's layout is not the
  performance-critical path.

**Trade-off.** `QPlainTextEdit` is lighter for very large plain-text documents.
We accept `QTextEdit` for the in-place-preview capability and VNote parity.

---

## D4. Reserve the band with block top-margins + `paintEvent`

**Decision.** Instead of reimplementing `QAbstractTextDocumentLayout`, reserve
the band by setting the block's top margin to the preview height, then draw the
preview into that band in `MTextEdit.paintEvent`.

**Rationale.** A custom `QAbstractTextDocumentLayout` (VNote's route) is
thousands of lines and high-risk to reimplement in Python. Block margins produce
the same visual result (a blank band above the block) with a fraction of the
code. Coordinates are derived from `cursorRect(block)`: the band is
`[caret.top() - margin, caret.top()]`.

**Consequences / limits.** The band is measured once per render; image previews
are re-measured on resize. Very large previews are capped (`_MAX_H`). This is a
deliberate simplification of VNote's full layout engine.

---

## D5. Preview scope: code, tables, local images

**Decision.** In-place preview covers **fenced code blocks**, **tables** and
**local images**. Math and remote/`data:` images are skipped. Inline text
(emphasis, links, headings) remains source with syntax highlighting.

**Rationale.** These are the block types where a rendered preview adds the most
value and can be drawn without extra runtimes. Math needs KaTeX; remote images
need networking. VNote's in-place preview likewise keeps regular text as source
(it is not full WYSIWYG).

**Consequences.** This is not Obsidian-style Live Preview. Inline markers such as
`**` and `*` stay visible. Extending to inline rendering is a documented future
step, not a defect. Within that scope, fenced code is token-coloured (D8) and
table columns are sized from their content — proportional widths, a floor for
narrow columns, bold headers — with ellipsis for cells that still overflow.

---

## D6. One cmark parse feeds everything

**Decision.** A single parse with VNote's cmark (`libs/cmarkgfm`) produces the
intermediate representation and a compact token stream, and both feed the outline
headings, the editor's block regions, the in-place preview specs and the
full-document preview. There is no second parser and no fallback:
`markdown-it-py` was removed.

**Rationale.** Mirrors VNote deriving its outline from the cmark AST, and keeps a
single interpretation of the document. cmark reports source lines and, with
`CMARK_OPT_SOURCE_SYNTAX`, the exact delimiter spans; its line ranges map
directly to `QTextBlock` numbers. On a 3,000-line fixture the cmark path is about
2.6 times faster than the previous pure-Python parser.

---

## D7. Async renderer: worker + debounced, coalescing manager

**Decision.** Parsing runs on a `QThreadPool` worker. `RenderManager` debounces
edits, coalesces bursts into one render, and uses a monotonic generation token so
only the newest revision produces UI output; stale workers abandon their second
phase.

**Signals.** `rendered` (full document, optional preview), `headingsAvailable`
(outline), `structureAvailable` (highlighter regions), `tokensAvailable`
(in-place preview).

**Rationale.** This is the core of the "fast by design" claim and the direct
answer to VNote's per-keystroke full re-render.

---

## D8. Pygments for code; no C++ highlighting engine

**Decision.** Code blocks are highlighted with Pygments in both native previews
(the in-place card and the optional full-document `PreviewWidget`) and in the
HTML path, all using `mtextedit.code_style.GitHubLightStyle`. No C++ highlighting
engine is built, bound or vendored.

**Rationale.** KSyntaxHighlighting is C++/Qt and not importable from Python.
Pygments is pure Python and already a dependency, and it covers more languages
(589 lexers versus 429 Kate definitions). The KSyntaxHighlighting fork that used
to be vendored has been removed; only its MIT-licensed GitHub Light palette
survived (D14).

---

## D9. Render-loop guard by text comparison

**Decision.** `MTextEdit` suppresses `renderRequested` when the document text is
unchanged since the last render, and ignores `textChanged` while applying block
formats.

**Rationale.** `QTextEdit` emits `textChanged` when a block format changes (the
top-margin reservation), asynchronously. A simple "applying" flag alone is not
enough because the signal can arrive after the flag clears; comparing text is
robust. Verified: applying previews produces zero renders; typing produces one.

---

## D10. Optional full-document preview retained

**Decision.** `PreviewWidget` (native `QTextDocument` builder, optional
`QWebEngineView`) remains available for hosts that want a whole-document view,
but the default experience is in-place preview.

**Rationale.** Keeps a non-in-place option for read-only/full-page use without
forcing Chromium into the default path. `QWebEngineView` is optional and was not
installed in the development environment.

**Consequences.** Its native builder consumes the same worker-computed colour
runs as the in-place card, so both native surfaces show identical token colours.

---

## D11. Linguistic tools are lazily bootstrapped

**Decision.** `mtextedit.linguistic` registers the vendored
`pyqt6-linguistic-tools` paths at import (cheap) but imports the heavy engines
(`spylls`, `pythes`) only when a service or the dictionary manager is requested.
The dictionary download manager and spell-check decorator are exposed through
this wrapper; shutdown detaches the decorator and closes the service.

**Rationale.** Importing `mtextedit` must stay light and must not fail when the
toolkit is absent. The download manager is the supported path for
spelling/thesaurus on Windows/macOS, where system Hunspell/MyThes do not exist.

---

## D12. Asynchronous preview pipeline

**Decision.** Preview is driven by the async render pipeline. The expensive
Markdown parse runs on a `QThreadPool` worker (`RenderWorker`); the resulting
token stream is delivered to the editor through
`RenderManager.tokensAvailable`. Preview *derivation* — building specs,
measuring, loading local images — plus block-margin reservation and painting run
on the GUI thread.

**Rationale.** Qt GUI types (`QPixmap`, `QPainter`, `QTextDocument` block-format
edits) are not thread-safe, so only the parse is offloaded. This keeps typing
responsive without cross-thread painting or layout hazards. The manager debounces
and coalesces requests and uses a generation token, so a stale parse is discarded
and never reaches the preview.

**Consequences.** Image decoding now happens off-thread in `RenderWorker`; only
the `QImage → QPixmap` conversion happens on the GUI thread (see D13). Code
fences get their Pygments colour runs on the worker too (`highlight.
annotate_code_runs`) and travel on the token stream, so the GUI thread only
draws strings it receives. Painting
is synchronous per `paintEvent`, which is the correct Qt model.
`tokensAvailable` carries plain Python token objects (no GUI types), so it is
safe to emit across threads.

---

## D13. Decode images off the GUI thread

**Decision.** Local image decoding moves off the GUI thread. The render worker
decodes image files into a `QImage` (thread-safe, no GUI dependency); the GUI
thread only converts the decoded `QImage` to a `QPixmap` and scales it for
painting. Decoded images are cached by `(path, mtime)` and the cache is bounded.

**Rationale.** `QPixmap` must be created on the GUI thread, but `QImage`
decoding does not. Today `inplace.measure_specs` calls `_load_pixmap` (which
constructs a `QPixmap` directly) inside `set_preview_tokens`, so a large local
image stalls the GUI thread while it is decoded (see D12). Moving decode into
the existing `RenderWorker` keeps the GUI-side preview derivation cheap and
reuses the manager's debounce/coalesce/cancel machinery.

**Consequences.**
- The worker's payload must carry decoded images (or raw bytes plus source
  identity) alongside the token stream; `measure_specs` then builds the
  `QPixmap` from the already-decoded `QImage` on the GUI thread.
- Cache entries are keyed by `(path, mtime)`; memory is bounded and entries are
  evicted LRU-style. Stale decodes are dropped by the same generation token the
  renderer already uses.
- Decode failures degrade to "no preview" exactly as today.
- **Status:** implemented. `RenderWorker` decodes `QImage` off-thread and returns
  the new images plus the requested `(path, mtime)` list; `RenderManager` keeps
  an LRU cache keyed by `(path, mtime)` and emits `previewImagesAvailable`;
  `MTextEdit` converts to `QPixmap` on the GUI thread in
  `inplace.measure_specs`. Workers skip decoding images already in the cache
  and abandon stale decodes via the generation token.
- **Cache size.** The bound defaults to 32 entries and is configurable at
  construction (`RenderManager(image_cache_max=...)`) or at runtime
  (`set_image_cache_max(n)`, which evicts immediately). Values must be integers
  `>= 1`; `bool` is rejected rather than accepted as `0`/`1`. All images a
  single render asked for are resolved *before* eviction, so a document with
  more images than the cache holds still paints completely on that render; the
  bound only governs retention for subsequent renders.

---

## D14. The C++ fork was removed; its GitHub Light palette was kept

**Decision.** `libs/mtextedit/libs/syntax-highlighting` — a 10k-line C++
KSyntaxHighlighting fork with a 53 MB checkout — was deleted. The one artefact
kept is the palette of its MIT-licensed `github-light.theme`, re-expressed as
`mtextedit.code_style.GitHubLightStyle` plus the `CODE_*` constants that
`inplace.py` paints the code card with.

**Rationale.** Porting or binding the engine would duplicate Pygments (D8) and
add a C++/Qt build dependency; it could not even configure on the development
machine, because it requires Qt 6.9 while the platform ships 6.8.2. The palette,
by contrast, has no Python equivalent: Pygments ships `github-dark` but no
GitHub Light style, and the preview already drew its code card in GitHub's light
colours (`#f6f8fa` on `#d0d7de`). Colour values are GitHub Inc.'s (MIT); the
mapping onto Pygments token types is ours.

**Consequences.** The editor has exactly one highlighter (Pygments), and the
in-place preview paints fenced code token by token using this style, with flat
monospace as the fallback for unknown languages, indented blocks and oversized
fences. The palette lives in a normal Python module, so no build step, submodule
or C++ toolchain is needed to keep or extend it.

---

## D15. VNote's cmark is the parser; parsing yields a small IR

**Decision.** `mtextedit.mdparse` parses the document with VNote's cmark fork
(`libs/cmarkgfm`, whose `libs/cmark` is our fork of `vnotex/cmark`
0.31.2, `wachin/cmark`) into a Qt-free IR: block
ranges plus inline spans in absolute character offsets. Inline spans come from
the parser's own source metadata (`CMARK_OPT_SOURCE_SYNTAX`), including the
exact delimiter positions. The binding is required: if it is missing or the build is broken,
`parse`/`parse_tokens` raise a clear `RuntimeError` instead of silently
switching parsers.

**Why.** It is the same parser VNote uses, so node extents match; the previous
pure-Python parser carried positions only on blocks, which is why inline styling
fell back to regexes. Measured on a 3,000-line fixture: **54 ms** for the cmark
IR versus **141 ms** for that parser. The IR contains no Qt types, so it is safe
to build on the render worker. The same parse also produces the compact token
stream `_markdown`/`inplace` consume, so removing markdown-it needed no rewrite
of those consumers.

**Consequences.** cmark columns are 1-based UTF-8 byte offsets, converted to
character offsets once per line by `SourceMap`; tests cover accented and emoji
text. A source checkout prefers the built fork under `libs/cmarkgfm/src`, while
an installed package uses its declared dependency (the pinned `cmarkgfm` fork).
There is no fallback path. The
highlighter (exact spans instead of regexes) and cursor-aware marker
concealment are the next consumers; until they are wired, the existing
region/regex highlighting stays in place.

---

## D16. VNote's theme format and its Native theme are the editor's look

**Decision.** `mtextedit.theme` parses VNote's `.theme` JSON
(`markdown-syntax-styles`, `markdown-editor-styles`). The bundled
`themes/native.theme` -- VNote's **Native** theme, copied unmodified -- is the
default, and the highlighter builds its formats from it. A host can load any
other VNote theme with `Theme.load(path)`.

**Why.** The format plus the Native theme is what makes a VNote-like look
possible without rewriting VNote's C++ highlighter: headings get VNote's sizes,
strong/emphasis/code/link/strike/mark get its colours. VNote is LGPL-3.0 and
`mtextedit` is MIT; the theme file stays LGPL-3.0 with its attribution (see
`themes/README.md` and `THIRD_PARTY_NOTICES.md`), while the loader is our code.

**Consequences.** The editor now looks like VNote for the constructs the
highlighter styles. Inline styling uses exact cmark spans and markers are cropped off
the cursor line (D17); a host that does not want the VNote look can pass its
own `Theme` to `MarkdownHighlighter` or call `set_theme()` at runtime.

## D17. Exact cmark spans drive inline styling; markers dim off the cursor line

**Decision.** The render worker gets tokens *and* exact inline spans from one
cmark parse (`mdparse.parse_document`). `MarkdownHighlighter.set_spans()`
replaces the regex inline styling: strong, emphasis, inline code, links, images,
strikethrough, mark and inline math are applied at the parser's own offsets.
Regexes remain only as a fallback until the first render arrives. This is the
path used when `use_custom_layout=False`; the editor default is the layout in
D18. Markers are styled normally on the cursor's line and cropped elsewhere: the highlighter
applies a transparent copy of the span format with negative absolute letter
spacing equal to the run's average glyph advance, so the run keeps its characters
but occupies zero width.

**Why.** Regexes mis-style nested emphasis, escaped markers, code with inner
backticks and destinations containing parentheses; cmark already computes exact
extents and delimiter spans. Qt's `QSyntaxHighlighter` cannot delete a run's
advance directly, but letter spacing is a font property the layout honours, so
the source text stays intact, caret positions land at the run's start and the
line reflows to the VNote-like "no markers" look. A custom
`QAbstractTextDocumentLayout` would mean reimplementing line layout, caret,
selection and IME for the same visual result.

**Consequences.** Markers expand again on the cursor's line, and
`set_conceal_markers(False)` disables cropping. A very small font size (0.1 pt)
triggered a Qt layout loop with `NoWrap`; the letter-spacing mechanism avoids
that. Only spans that carry markers are cropped -- heading `#` markers are not
covered yet. Cursor movement rehighlights only the previous and current blocks.

---

## D18. A custom layout prototype owns concealment (opt-in)

**Decision.** `mtextedit.layout.MarkdownDocumentLayout` is a
`QAbstractTextDocumentLayout` that paints each block from a *display* string with
the concealed marker ranges removed, keeping a document<->display position map
for cursor, selection and hit testing. It is the editor default
(`MTextEdit(use_custom_layout=True)`); `use_custom_layout=False` keeps the
`QSyntaxHighlighter` fallback (D17).

**Why.** Format-level cropping works, but constructs that need layout control
(heading markers, embedded previews, folding) cannot be expressed through
character formats. VNote's approach -- a custom layout on top of
`QTextDocument` -- is the proven middle ground between fighting Qt's layout and
writing a text engine; this module is our implementation, and only the
architecture was studied (VNote is LGPL-3.0; no code copied).

**Consequences.** Phase 1 covers plain blocks, span/region formats,
concealment, cursor, selection (including full-width selection) and hit
testing. IME (Input Method Editor) pre-edit text is read from the block's
layout and painted underlined; the commit reachable from it updates the
document normally. Unaffected block layouts are reused across edits, so typing
rebuilds only the edited block; the block walk is still O(blocks).

Not covered yet: inline images/math/tables, code-block backgrounds, list
guides, and accessibility verification.

---

## Non-goals

* Porting `vxcore`, `m3` or `QHotkey` C++ code. The app-level data model is
  reimplemented in Python (`core/`), with pluggable content search (the
  application's `DESIGN.md`, C9).
* Full WYSIWYG inline rendering and math preview (future work).
* Chromium as a default dependency.
