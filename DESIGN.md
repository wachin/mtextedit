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
step, not a defect.

---

## D6. One `markdown-it-py` parse feeds everything

**Decision.** A single parse produces the token stream, which is reused for the
outline headings, the editor's block-highlight regions, and the in-place preview
specs.

**Rationale.** Mirrors VNote deriving its outline from the cmark AST. One parse
avoids three divergent interpretations of the same document. `markdown-it-py`
tokens carry `map` (source line ranges), which map directly to `QTextBlock`
numbers.

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

**Decision.** Code blocks are highlighted with Pygments (HTML path) and rendered
monospace in the native preview, using `mtextedit.code_style.GitHubLightStyle`.
No C++ highlighting engine is built, bound or vendored.

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
the `QImage → QPixmap` conversion happens on the GUI thread (see D13). Painting
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

**Consequences.** The editor has exactly one highlighter (Pygments). Fenced code
in the in-place preview still paints flat text; colouring it token-by-token is a
separate, smaller change that now has a ready style to paint with. The palette
lives in a normal Python module, so no build step, submodule or C++ toolchain is
needed to keep or extend it.

---

## Non-goals

* Porting `vxcore`, `m3` or `QHotkey` C++ code. The app-level data model is
  reimplemented in Python (`core/`), with pluggable content search (the
  application's `DESIGN.md`, C9).
* Full WYSIWYG inline rendering and math preview (future work).
* Chromium as a default dependency.
