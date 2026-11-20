# Bundled themes

`native.theme` is VNote's **Native** editor theme, copied unmodified from
VNote's repository (`src/data/extra/themes/native/text-editor.theme`).

* Upstream: <https://github.com/vnotex/vnote>
* License: **LGPL-3.0** (the VNote project license). Copyright the VNote
  authors. The file remains LGPL-3.0; `mtextedit` itself is MIT.
* Attribution: see [`../../THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).

`mtextedit.theme` reads this format (`markdown-syntax-styles` and
`markdown-editor-styles`). `Theme.load_default()` loads this file, and a host can
load any other VNote `.theme` with `Theme.load(path)`.
