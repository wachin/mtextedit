# mtextedit

A **modular, async-first Markdown editor component for PyQt6**, built as the
reusable editing engine for [marktux](https://github.com/wachin/marktux) and
any other PyQt6 application (e.g. the fourth panel of an e-Sword-like tool).

mtextedit is the Python/PyQt6 answer to VNote's `vtextedit`: same goals, but
designed from scratch so performance comes from the **architecture** (async,
threaded, coalesced rendering) rather than the language.

## Architecture

```
mtextedit/
  editor.py          MTextEdit -- QTextEdit surface with in-place preview
  inplace.py         code/table/image previews drawn above their source block
  highlighter.py     MarkdownHighlighter -- block regions (async) + inline regex
  code_style.py      GitHubLightStyle -- Pygments palette for fenced code
  highlight.py       Pygments token runs for fenced code (off the GUI thread)
  renderer/
    render_worker.py RenderWorker -- parses Markdown off the GUI thread
    render_manager.py RenderManager -- debounce + coalesce + priority cancel
    preview.py       PreviewWidget -- optional full-document preview
  outline.py         OutlineModel / OutlineView -- AST-derived outline
  find_replace.py    FindReplaceWidget -- in-file find & replace
  linguistic/        optional spell-check/thesaurus via pyqt6-linguistic-tools
  _markdown.py       shared parser config, heading/region extraction, builders
```

### In-place preview (VNote-style)

Like VNote's in-place preview, there is **no separate preview pane**. For the
block types VNote previews — fenced code, tables and images — a band is reserved
above the source block and the rendered preview is painted into it, while regular
text stays as editable Markdown. `MTextEdit` implements this by setting the
block's top margin (reserving the band) and drawing into it in `paintEvent`;
this mirrors VNote's `TextDocumentLayout` intent without a custom document
layout. Toggle it from the **View → In-place Preview** menu.

The full decision record (why a single pane, why `QTextEdit`, why block margins
instead of a custom layout, preview scope and limitations) is in
[`DESIGN.md`](DESIGN.md).

### Why it is fast
* The Markdown parse (`markdown-it-py`) runs in a `QThreadPool` worker, never on
  the GUI thread.
* `RenderManager.request` is **debounced and coalesced**: a burst of keystrokes
  collapses into a single render, and only the newest request can produce UI
  output (stale in-flight workers abandon their second phase).
* In-place preview reserves a band only for code/table/image blocks and paints
  those, instead of reloading a whole `QWebEngineView` per keystroke (VNote's
  main bottleneck on large files). The heavy parse still runs on the worker.
* Images are decoded **off the GUI thread** (`QImage` in `RenderWorker`) and
  cached in a bounded LRU (32 entries by default, tunable via
  `RenderManager(image_cache_max=...)` or `set_image_cache_max(n)`); only the
  `QPixmap` conversion happens on the GUI thread (see `DESIGN.md` D13).

## Compared to VNote

| Concern        | VNote (`vtextedit`)        | mtextedit                         |
|----------------|----------------------------|-----------------------------------|
| Editor widget  | `QTextEdit`/`QPlainTextEdit` | `QTextEdit`                      |
| Parser         | cmark (C)                  | `markdown-it-py` (Python)         |
| Code highlight | KSyntaxHighlighting (C++)   | Pygments (Python)                 |
| Preview        | `QWebEngineView` (Chromium) | in-place, above the source block  |
| Render thread  | `QtConcurrent`             | `QThreadPool` + coalesced manager |
| Outline source | cmark AST                  | `markdown-it-py` AST              |
| Search         | none / ripgrep             | notebook-wide search (in marktux) |

> There is no bundled C++ highlighting engine: the KSyntaxHighlighting fork was
> removed, and code blocks are highlighted with Pygments. Its MIT-licensed
> GitHub Light palette survives as `mtextedit.code_style.GitHubLightStyle`, which
> the in-place preview paints fenced code with, token by token, using runs
> computed on the render worker (see `DESIGN.md` D12 and D14).

## Usage

```python
from mtextedit import MTextEdit, RenderManager, PreviewWidget, OutlineView

editor = MTextEdit()
manager = RenderManager()
preview = PreviewWidget()
outline = OutlineView()

editor.set_render_manager(manager)          # block highlighting
editor.renderRequested.connect(manager.request)
manager.rendered.connect(preview.on_rendered)
manager.headingsAvailable.connect(outline.set_headings)
outline.headingActivated.connect(editor.goToLine)
```

See `examples/demo.py` for a complete window.

## Spelling, thesaurus & dictionary downloads

`mtextedit.linguistic` integrates the vendored
[`pyqt6-linguistic-tools`](libs/pyqt6-linguistic-tools) submodule, which bundles
its own engines (`spylls` for spelling, `pythes` for the thesaurus). Crucially it
ships a **verified dictionary download manager** — the supported way to get
spelling/thesaurus on Windows and macOS, where the Linux-style system
Hunspell/MyThes packages are unavailable.

```python
from mtextedit.linguistic import (
    create_service, show_download_manager, toolkit_available,
)

service = create_service(namespace="marktux")      # lazily loads the toolkit
show_download_manager(window, service)             # modeless dialog, 57-entry catalog
```

The manager downloads over HTTPS, verifies size + SHA-256, rejects unsafe archive
paths, deep-validates every component, and installs into the managed provider on
a worker thread — no restart required. The wrapper also exposes a small
`Spellchecker` facade (`check`, `suggest`, `add_to_user`).

Spell-checking the editor uses the toolkit decorator:

```python
from pyqt6_linguistic_tools.qt import LinguisticTextEditDecorator
decorator = LinguisticTextEditDecorator(editor, service)
decorator.set_spellcheck_enabled(True)
```

Both `examples/demo.py` and `marktux/main.py` expose these under a **Tools** menu
(*Dictionary Download Manager…* and *Spell Check*).

## Tests

```bash
# from libs/mtextedit
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v
# or from the repository root
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s libs/mtextedit/tests -t libs/mtextedit -v
```

## Install

```bash
pip install -e .
# optional: pip install ".[webengine,linguistic]"
```
