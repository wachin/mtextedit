# Third-party notices (mtextedit)

`mtextedit` is licensed under **MIT** (see `pyproject.toml`). This file records
the third-party work it builds on or depends on.

## Compiled and runtime dependencies

* **cmark** — `libs/cmarkgfm/libs/cmark`: our fork (`wachin/cmark`) of
  VNote's cmark fork. BSD-2-Clause, Copyright (c) 2014 John MacFarlane. The
  `COPYING` file ships inside that submodule; `MAINTENANCE.md` in cmarkgfm
  documents how upstream changes are reviewed.
* **cmarkgfm** — `libs/cmarkgfm`, MIT, Copyright (c) theacodes. The fork is
  `github.com/wachin/cmarkgfm`; `LICENSE.txt` ships inside it.
* **Pygments** — BSD-2-Clause.
* **matplotlib** (optional `[math]` extra) — Matplotlib License (PSF-based,
  BSD-compatible). Only imported when block formulas are rendered.
* **PyQt6 / Qt 6** — GPL-3.0 or LGPL-3.0 (Riverbank Computing / The Qt Company).

## Data

* **GitHub Light palette** — `mtextedit/code_style.py` uses colour values from
  `github-light.theme` (`SPDX-FileCopyrightText: 2020 GitHub Inc.`,
  `SPDX-License-Identifier: MIT`), taken from the removed KSyntaxHighlighting
  fork. Only the colour values were kept; the token mapping is ours.

## Format compatibility

* **VNote Native theme** — `mtextedit/themes/native.theme`, copied unmodified
  from VNote's `src/data/extra/themes/native/text-editor.theme`. LGPL-3.0,
  copyright the VNote authors; the file keeps its own license and the rest of
  `mtextedit` remains MIT. See `mtextedit/themes/README.md`.
* **VNote layout architecture** -- VNote's `TextDocumentLayout`
  (`QAbstractTextDocumentLayout`, LGPL-3.0) was studied for the design of
  `mtextedit/layout.py`. No VNote code is copied; the implementation is
  original.
* **VNote `.theme` format** — `mtextedit/theme.py` parses the JSON layout used
  by VNote: `markdown-syntax-styles` and `markdown-editor-styles`. The loader
  is independent code.
