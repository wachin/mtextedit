"""Shared Markdown processing for mtextedit.

This module owns the single Markdown parser configuration used across the
editor, the async renderer, the highlighter and the outline. It deliberately
keeps *no* Qt dependencies in the pure-parsing helpers (``build_md``,
``extract_headings``, ``collect_block_regions``) so they can run on a worker
thread without a GUI context. The Qt-dependent builder (``build_document``)
is only ever called on the GUI thread.

Design notes
------------
* Parser: ``markdown-it-py`` (pure Python, GFM flavour). It both renders HTML
  and exposes a token stream we reuse for the outline and for editor
  highlighting -- mirroring how VNote derived its outline from the cmark AST
  rather than regex-scanning the source.
* Code blocks: highlighted with Pygments when rendering to HTML. The native
  ``QTextDocument`` preview renders code blocks in a monospace face (per-token
  colouring is left as a documented extension point).
* The native preview (``build_document``) replaces VNote's full-document
  ``QWebEngineView.setHtml`` reload. We build a ``QTextDocument`` directly
  from the token stream, which keeps the heavy parse on a worker thread and
  avoids spinning up Chromium for every keystroke.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from markdown_it import MarkdownIt

# ---------------------------------------------------------------------------
# Parser configuration
# ---------------------------------------------------------------------------

_MD: Optional[MarkdownIt] = None


def build_md() -> MarkdownIt:
    """Return the shared, fully-configured Markdown parser.

    The parser is created lazily and reused. It is *not* thread-safe to mutate
    its configuration after creation, so callers must treat the returned object
    as read-only (use it only to parse/render).
    """
    global _MD
    if _MD is None:
        _MD = MarkdownIt("gfm-like").enable("table")
        # Render fenced code blocks through Pygments for the HTML path.
        _MD.add_render_rule("fence", _render_fence_pygments)
    return _MD


def _render_fence_pygments(self, tokens, idx, options, env):
    token = tokens[idx]
    lang = (token.info or "").strip().split()[0] if token.info else ""
    text = token.content or ""
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name, guess_lexer

        try:
            lexer = get_lexer_by_name(lang, stripall=False)
        except Exception:
            lexer = guess_lexer(text)
        highlighted = highlight(text, lexer, HtmlFormatter(nowrap=True))
        classes = f"language-{lang}" if lang else ""
        return (
            f'<pre class="code-block {classes}"><code>{highlighted}</code></pre>\n'
        )
    except Exception:
        esc = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return f'<pre class="code-block"><code>{esc}</code></pre>\n'


# ---------------------------------------------------------------------------
# Heading extraction (outline source of truth)
# ---------------------------------------------------------------------------

Heading = Dict[str, Any]  # {"level": int, "text": str, "line": int}


def extract_headings(tokens: List[Any]) -> List[Heading]:
    """Build the outline heading list from a parsed token stream.

    Mirrors VNote's ``OutlineProvider`` -- the headings come from the parse
    tree, never from a regex scan of the source.
    """
    headings: List[Heading] = []
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            level = int(tok.tag[1])
            text = ""
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                text = (tokens[i + 1].content or "").strip()
            line = tok.map[0] if tok.map else 0
            headings.append({"level": level, "text": text, "line": line})
    return headings


# ---------------------------------------------------------------------------
# Block regions for the editor highlighter
# ---------------------------------------------------------------------------

Region = Dict[str, Any]  # {"start": int, "end": int, "kind": str, "level": int}


def collect_block_regions(tokens: List[Any]) -> List[Region]:
    """Return line-range regions so the highlighter can style whole blocks.

    ``start``/``end`` are inclusive 0-based source line numbers. ``kind`` is one
    of ``heading``, ``code``, ``quote``, ``list`` or ``hr``.
    """
    regions: List[Region] = []
    for tok in tokens:
        if not tok.map:
            continue
        start, end = tok.map[0], tok.map[1] - 1
        if tok.type == "heading_open":
            regions.append(
                {"start": start, "end": end, "kind": "heading",
                 "level": int(tok.tag[1])}
            )
        elif tok.type in ("fence", "code_block"):
            regions.append({"start": start, "end": end, "kind": "code"})
        elif tok.type == "blockquote_open":
            regions.append({"start": start, "end": end, "kind": "quote"})
        elif tok.type in ("bullet_list_open", "ordered_list_open"):
            regions.append({"start": start, "end": end, "kind": "list"})
        elif tok.type == "hr":
            regions.append({"start": start, "end": end, "kind": "hr"})
    return regions


# ---------------------------------------------------------------------------
# HTML rendering (used by the optional QWebEngineView preview)
# ---------------------------------------------------------------------------

def render_html(md: MarkdownIt, tokens: List[Any]) -> str:
    """Render previously-parsed tokens to a full HTML string."""
    # Reuse markdown-it's renderer on the token stream.
    return md.renderer.render(tokens, md.options, {})


# ---------------------------------------------------------------------------
# Native QTextDocument builder (default, Chromium-free preview)
# ---------------------------------------------------------------------------

def build_document(tokens: List[Any], doc: "Any") -> None:
    """Populate a ``QTextDocument`` from the token stream.

    Called only on the GUI thread. The expensive *parse* already happened on a
    worker thread; this step is a cheap linear walk that assembles formatted
    blocks. Incremental/diff updates are a documented future optimisation.
    """
    from PyQt6.QtGui import (
        QTextBlockFormat,
        QTextCharFormat,
        QTextCursor,
        QTextDocument,
        QFont,
    )
    from PyQt6.QtCore import Qt

    doc.clear()
    builder = _DocBuilder(doc, QTextCursor, QTextBlockFormat, QTextCharFormat,
                         QFont, Qt)
    builder.run(tokens)


class _DocBuilder:
    def __init__(self, doc, QTextCursor, QTextBlockFormat, QTextCharFormat,
                 QFont, Qt):
        self.doc = doc
        self.cursor = QTextCursor(doc)
        self.QTextBlockFormat = QTextBlockFormat
        self.QTextCharFormat = QTextCharFormat
        self.QFont = QFont
        self.Qt = Qt
        self.list_stack: List[Dict[str, Any]] = []
        self.quote_depth = 0
        self.list_item_marker: Optional[str] = None
        self.first = True
        self.cf_stack: List[QTextCharFormat] = [QTextCharFormat()]

    # -- format helpers ------------------------------------------------------
    def _base_cf(self) -> QTextCharFormat:
        return self.QTextCharFormat(self.cf_stack[-1])

    def _block_format(self) -> QTextBlockFormat:
        bf = self.QTextBlockFormat()
        indent = 20 * self.quote_depth + 20 * len(self.list_stack)
        if indent:
            bf.setLeftMargin(indent)
        bf.setTopMargin(2)
        bf.setBottomMargin(2)
        return bf

    def _new_block(self, bf=None, cf=None):
        if bf is None:
            bf = self._block_format()
        if cf is None:
            cf = self._base_cf()
        if self.first:
            self.cursor.setBlockFormat(bf)
            self.cursor.setCharFormat(cf)
            self.first = False
        else:
            self.cursor.insertBlock(bf, cf)

    def _consume_marker(self) -> str:
        m = self.list_item_marker or ""
        self.list_item_marker = None
        return m

    # -- block builders ------------------------------------------------------
    def _heading_block(self, level: int, inline):
        cf = self._base_cf()
        sizes = {1: 18, 2: 15, 3: 13, 4: 12, 5: 11, 6: 10}
        cf.setFontPointSize(sizes.get(level, 11))
        cf.setFontWeight(self.QFont.Weight.Bold)
        self._new_block(cf=cf)
        marker = self._consume_marker()
        if marker:
            self.cursor.insertText(marker)
        self._render_inline(inline)

    def _para_block(self, inline):
        self._new_block()
        marker = self._consume_marker()
        if marker:
            self.cursor.insertText(marker)
        self._render_inline(inline)

    def _code_block(self, tok):
        cf = self._base_cf()
        cf.setFontFamily("monospace")
        bf = self._block_format()
        bf.setTopMargin(4)
        bf.setBottomMargin(4)
        self._new_block(bf=bf, cf=cf)
        self.cursor.insertText(tok.content.rstrip("\n"))

    def _hr(self):
        cf = self._base_cf()
        cf.setForeground(self.Qt.GlobalColor.gray)
        self._new_block(cf=cf)
        self.cursor.insertText("─" * 24)

    # -- inline rendering ----------------------------------------------------
    def _render_inline(self, inline):
        if not inline:
            return
        for t in inline:
            ty = t.type
            if ty == "text":
                self.cursor.insertText(t.content, self._base_cf())
            elif ty == "strong_open":
                cf = self._base_cf(); cf.setFontWeight(self.QFont.Weight.Bold)
                self.cf_stack.append(cf)
            elif ty == "strong_close":
                if len(self.cf_stack) > 1:
                    self.cf_stack.pop()
            elif ty == "em_open":
                cf = self._base_cf(); cf.setFontItalic(True)
                self.cf_stack.append(cf)
            elif ty == "em_close":
                if len(self.cf_stack) > 1:
                    self.cf_stack.pop()
            elif ty == "s_open":
                cf = self._base_cf(); cf.setFontStrikeOut(True)
                self.cf_stack.append(cf)
            elif ty == "s_close":
                if len(self.cf_stack) > 1:
                    self.cf_stack.pop()
            elif ty == "code_inline":
                cf = self._base_cf(); cf.setFontFamily("monospace")
                self.cursor.insertText(t.content, cf)
            elif ty == "link_open":
                cf = self._base_cf()
                cf.setForeground(self.Qt.GlobalColor.blue)
                cf.setUnderlineStyle(
                    self.QTextCharFormat.UnderlineStyle.SingleUnderline)
                href = ""
                for k, v in (t.attrs or []):
                    if k == "href":
                        href = v
                if href:
                    cf.setAnchor(True)
                    cf.setAnchorHref(href)
                self.cf_stack.append(cf)
            elif ty == "link_close":
                if len(self.cf_stack) > 1:
                    self.cf_stack.pop()
            elif ty == "softbreak":
                self.cursor.insertText(" ")
            elif ty in ("hardbreak", "br"):
                self.cursor.insertText("\n")
            elif ty == "html_inline":
                self.cursor.insertText(t.content, self._base_cf())
            # image / html_inline etc. are skipped for the preview.

    # -- token walk ----------------------------------------------------------
    def run(self, tokens: List[Any]):
        i = 0
        n = len(tokens)
        while i < n:
            t = tokens[i]
            ty = t.type
            if ty == "heading_open":
                lvl = int(t.tag[1])
                inline = tokens[i + 1].children if i + 1 < n else None
                self._heading_block(lvl, inline)
                i += 3
            elif ty == "paragraph_open":
                inline = tokens[i + 1].children if i + 1 < n else None
                self._para_block(inline)
                i += 3
            elif ty == "bullet_list_open":
                self.list_stack.append({"ordered": False, "count": 0})
                i += 1
            elif ty == "ordered_list_open":
                self.list_stack.append({"ordered": True, "count": 0})
                i += 1
            elif ty in ("bullet_list_close", "ordered_list_close"):
                if self.list_stack:
                    self.list_stack.pop()
                i += 1
            elif ty == "list_item_open":
                entry = self.list_stack[-1] if self.list_stack else None
                if entry is not None:
                    entry["count"] += 1
                    self.list_item_marker = (
                        f"{entry['count']}. "
                        if entry["ordered"]
                        else "• "
                    )
                i += 1
            elif ty == "list_item_close":
                i += 1
            elif ty == "blockquote_open":
                self.quote_depth += 1
                i += 1
            elif ty == "blockquote_close":
                self.quote_depth = max(0, self.quote_depth - 1)
                i += 1
            elif ty in ("fence", "code_block"):
                self._code_block(t)
                i += 1
            elif ty == "hr":
                self._hr()
                i += 1
            elif ty == "html_block":
                self._para_block_text(t.content)
                i += 1
            else:
                i += 1

    def _para_block_text(self, text: str):
        self._new_block()
        marker = self._consume_marker()
        if marker:
            self.cursor.insertText(marker)
        self.cursor.insertText(text.rstrip("\n"))
