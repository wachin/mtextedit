"""The single parser: VNote's cmark, exposed as an IR (Intermediate
Representation — representación intermedia) and as a small token stream.

There is no alternative parser. ``cmarkgfm`` (the ``libs/cmarkgfm`` fork bound
to ``vnotex/cmark``) is required; if it is missing, :func:`parse` and
:func:`parse_tokens` raise a clear ``RuntimeError`` instead of silently using a
different engine.

Two views of the same document are produced:

* :func:`parse` returns :class:`MarkdownIR` -- block ranges plus inline spans
  with exact delimiter positions. This is what the highlighter will consume.
* :func:`parse_tokens` returns a compact token list with the shape the editor
  already understands (``heading_open``, ``inline``, ``fence``, ``table_open``,
  ``strong_open``...). It exists so the preview, outline and table builders keep
  one implementation while the parser underneath is cmark.

cmark positions are 1-based and columns are UTF-8 byte offsets, so
:class:`SourceMap` converts them to character offsets once per line.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------------------
# IR
# ---------------------------------------------------------------------------

INLINE_STYLES = {
    "strong": "strong",
    "emph": "emph",
    "code": "code",
    "link": "link",
    "image": "image",
    "strikethrough": "strike",
    "mark": "mark",
    "formula_inline": "math",
    "footnote_reference": "footnote",
    "wikilink": "link",
}

BLOCK_KINDS = {
    "paragraph": "paragraph",
    "heading": "heading",
    "code_block": "code_block",
    "block_quote": "quote",
    "list": "list",
    "item": "item",
    "table": "table",
    "thematic_break": "hr",
    "frontmatter": "frontmatter",
    "html_block": "html",
    "formula_block": "math_block",
}


@dataclass(frozen=True)
class Span:
    """One styled source range, in absolute character offsets."""

    style: str
    start: int
    end: int
    content_start: int
    content_end: int


@dataclass(frozen=True)
class Block:
    """A block range in 0-based, inclusive source lines."""

    kind: str
    start_line: int
    end_line: int
    level: int = 0


@dataclass
class MarkdownIR:
    source: str
    blocks: list[Block] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    backend: str = "cmark"

    def spans_for_line(self, line: int) -> list[Span]:
        """Spans that intersect 0-based ``line``."""
        return [span for span in self.spans
                if self._lines(span)[0] <= line <= self._lines(span)[1]]

    def _lines(self, span: Span) -> tuple[int, int]:
        start = self.source.count("\n", 0, span.start)
        end = self.source.count("\n", 0, max(span.start, span.end - 1))
        return start, end


# ---------------------------------------------------------------------------
# Token stream (the shape the editor consumes)
# ---------------------------------------------------------------------------

@dataclass
class Token:
    type: str
    tag: str = ""
    content: str = ""
    info: str = ""
    map: tuple[int, int] | None = None
    attrs: list[tuple[str, str]] = field(default_factory=list)
    children: list[Token] | None = None
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Position conversion
# ---------------------------------------------------------------------------

class SourceMap:
    """Maps cmark's (1-based line, UTF-8 byte column) to character offsets."""

    def __init__(self, text: str):
        self.text = text
        self.line_starts = [0]
        for index, char in enumerate(text):
            if char == "\n":
                self.line_starts.append(index + 1)
        self._byte_map: dict[int, list[int]] = {}

    def offset(self, line: int, column: int) -> int:
        line_index = max(0, line - 1)
        if line_index >= len(self.line_starts):
            return len(self.text)
        start = self.line_starts[line_index]
        end = (self.line_starts[line_index + 1]
               if line_index + 1 < len(self.line_starts) else len(self.text))
        mapping = self._byte_map.get(line_index)
        if mapping is None:
            mapping = _byte_to_char(self.text[start:end])
            self._byte_map[line_index] = mapping
        byte_index = max(0, column - 1)
        char_index = mapping[min(byte_index, len(mapping) - 1)]
        return min(end, start + char_index)


def _byte_to_char(line: str) -> list[int]:
    """``mapping[byte_offset] = char_index`` for one line."""
    mapping = [0]
    for index, char in enumerate(line, start=1):
        mapping.extend([index] * len(char.encode("utf-8")))
    return mapping


# ---------------------------------------------------------------------------
# Backend discovery
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def cmark_backend():
    """Return the cmark module if VNote's fork is importable, else ``None``.

    A source checkout prefers the built binding under ``libs/cmarkgfm/src`` so
    the fork is used even when an older ``cmarkgfm`` exists system-wide.
    """
    fork_src = Path(__file__).resolve().parents[1] / "libs" / "cmarkgfm" / "src"
    if (fork_src / "cmarkgfm").is_dir() and str(fork_src) not in sys.path:
        sys.path.insert(0, str(fork_src))
    try:
        from cmarkgfm import cmark  # noqa: WPS433 - required dependency
    except Exception:  # noqa: BLE001 - reported by require_cmark()
        return None
    if not hasattr(cmark, "Node") or not hasattr(cmark.Node, "syntax_extent"):
        return None
    return cmark


def require_cmark():
    cmark = cmark_backend()
    if cmark is None:
        raise RuntimeError(
            "VNote's cmark binding is required. Build it with:\n"
            "    cd libs/mtextedit/libs/cmarkgfm/src && "
            "python3 cmarkgfm/build_cmark.py\n"
            "or install the package from libs/mtextedit/libs/cmarkgfm."
        )
    return cmark


def backend_name() -> str:
    return "cmark" if cmark_backend() is not None else "unavailable"


# ---------------------------------------------------------------------------
# IR construction
# ---------------------------------------------------------------------------

def _span_from_node(node, source_map: SourceMap, style: str) -> Span | None:
    extent = node.syntax_extent
    if extent is not None:
        start_line, start_column, end_line, end_column = extent
        start = source_map.offset(start_line, start_column)
        end = source_map.offset(end_line, end_column)
    else:
        if not node.start_line or not node.end_line:
            return None
        start = source_map.offset(node.start_line, node.start_column)
        end = source_map.offset(node.end_line, node.end_column + 1)

    content_start, content_end = start, end
    delimiters = node.syntax_spans()
    if delimiters:
        first, last = delimiters[0], delimiters[-1]
        content_start = (source_map.offset(first["line"], first["column"])
                         + len(first["text"]))
        content_end = source_map.offset(last["line"], last["column"])

    start = max(0, min(start, len(source_map.text)))
    end = max(start, min(end, len(source_map.text)))
    content_start = max(start, min(content_start, end))
    content_end = max(content_start, min(content_end, end))
    return Span(style, start, end, content_start, content_end)


def parse(text: str) -> MarkdownIR:
    """Parse ``text`` into block ranges plus exact inline spans."""
    cmark = require_cmark()
    source_map = SourceMap(text)
    ir = MarkdownIR(source=text, backend="cmark")
    document = cmark.parse_document(text, cmark.Options.CMARK_OPT_HIGHLIGHT)
    try:
        stack = [document]
        while stack:
            node = stack.pop()
            name = node.type_name
            if name in BLOCK_KINDS:
                start_line = max(0, node.start_line - 1)
                end_line = max(start_line, node.end_line - 1)
                if node.end_column == 0 and end_line > start_line:
                    end_line -= 1
                level = node.heading_level if name == "heading" else 0
                ir.blocks.append(Block(BLOCK_KINDS[name], start_line, end_line, level))
            style = INLINE_STYLES.get(name)
            if style is not None:
                span = _span_from_node(node, source_map, style)
                if span is not None:
                    ir.spans.append(span)
            stack.extend(reversed(list(node.children())))
    finally:
        document.close()
    ir.spans.sort(key=lambda span: (span.start, -span.end))
    return ir


# ---------------------------------------------------------------------------
# Token stream construction
# ---------------------------------------------------------------------------

def _line_map(node) -> tuple[int, int]:
    """Half-open ``(start, end)`` line range, in 0-based lines."""
    start = max(0, node.start_line - 1)
    end = max(start, node.end_line - 1)
    if node.end_column == 0 and end > start:
        end -= 1
    return (start, end + 1)


def _plain_text(node) -> str:
    parts: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type_name in ("text", "code", "formula_inline"):
            parts.append(current.literal)
        else:
            stack.extend(reversed(list(current.children())))
    return "".join(parts)


@dataclass
class ParsedDocument:
    """Tokens for the editor plus the exact spans for the highlighter."""

    tokens: list[Token]
    spans: list[Span]


def _collect_span(node, source_map: SourceMap, spans: list[Span]) -> None:
    style = INLINE_STYLES.get(node.type_name)
    if style is None:
        return
    span = _span_from_node(node, source_map, style)
    if span is not None:
        spans.append(span)


def _inline_tokens(container, source_map: SourceMap,
                   spans: list[Span]) -> list[Token]:
    tokens: list[Token] = []
    for node in container.children():
        name = node.type_name
        if name == "text":
            tokens.append(Token("text", content=node.literal))
        elif name == "softbreak":
            tokens.append(Token("softbreak"))
        elif name == "linebreak":
            tokens.append(Token("hardbreak"))
        elif name == "code":
            _collect_span(node, source_map, spans)
            tokens.append(Token("code_inline", content=node.literal))
        elif name in ("strong", "emph", "strikethrough", "mark"):
            _collect_span(node, source_map, spans)
            open_type = {"strong": "strong_open", "emph": "em_open",
                         "strikethrough": "s_open", "mark": "mark_open"}[name]
            close_type = {"strong": "strong_close", "emph": "em_close",
                          "strikethrough": "s_close", "mark": "mark_close"}[name]
            tokens.append(Token(open_type))
            tokens.extend(_inline_tokens(node, source_map, spans))
            tokens.append(Token(close_type))
        elif name in ("link", "wikilink"):
            _collect_span(node, source_map, spans)
            tokens.append(Token("link_open", attrs=[
                ("href", node.url or node.literal),
                ("title", node.title),
            ]))
            tokens.extend(_inline_tokens(node, source_map, spans))
            tokens.append(Token("link_close"))
        elif name == "image":
            _collect_span(node, source_map, spans)
            alt = _plain_text(node)
            tokens.append(Token("image", content=alt, attrs=[
                ("src", node.url), ("alt", alt), ("title", node.title),
            ]))
        elif name == "html_inline":
            tokens.append(Token("html_inline", content=node.literal))
        elif name == "formula_inline":
            _collect_span(node, source_map, spans)
            tokens.append(Token("math_inline", content=node.literal))
        elif name == "footnote_reference":
            tokens.append(Token("footnote_ref", content=node.literal))
        else:
            tokens.extend(_inline_tokens(node, source_map, spans))
    return tokens


def _inline(container, source_map: SourceMap, spans: list[Span]) -> Token:
    return Token("inline", content=_plain_text(container),
                 children=_inline_tokens(container, source_map, spans),
                 map=_line_map(container))


def _table_aligns(source_lines: list[str], table_line: int, ncols: int) -> list[str]:
    """Infer column alignment from the delimiter row of a GFM table."""
    aligns = ["left"] * ncols
    index = table_line  # table_line is 1-based; delimiter is the next line
    if index >= len(source_lines):
        return aligns
    cells = [cell.strip() for cell in source_lines[index].strip().strip("|").split("|")]
    for column, cell in enumerate(cells[:ncols]):
        left, right = cell.startswith(":"), cell.endswith(":")
        aligns[column] = "center" if left and right else "right" if right else "left"
    return aligns


def _table_tokens(node, source_lines: list[str], source_map: SourceMap,
                  spans: list[Span]) -> list[Token]:
    tokens: list[Token] = [Token("table_open", map=_line_map(node))]
    rows = list(node.children())
    ncols = max((len(list(row.children())) for row in rows), default=0)
    aligns = _table_aligns(source_lines, node.start_line, ncols)
    body_index = 0
    for row in rows:
        if row.start_line == node.start_line + 1:
            continue  # the |---| delimiter row is not a rendered row
        is_header = body_index == 0
        tokens.append(Token("tr_open", map=_line_map(row)))
        for column, cell in enumerate(row.children()):
            align = aligns[column] if column < len(aligns) else "left"
            cell_type = "th_open" if is_header else "td_open"
            tokens.append(Token(cell_type, attrs=[("style", f"text-align:{align}")]))
            tokens.append(_inline(cell, source_map, spans))
            tokens.append(Token("th_close" if is_header else "td_close"))
        tokens.append(Token("tr_close"))
        body_index += 1
    tokens.append(Token("table_close"))
    return tokens


def _code_token(node) -> Token:
    content = node.literal
    info = node.fence_info or ""
    token = Token("fence" if info else "code_block",
                  content=content, info=info, map=_line_map(node))
    lang = info.strip().split()[0] if info.strip() else ""
    if lang:
        from .highlight import code_runs

        runs = code_runs(content, lang)
        if runs:
            token.meta["highlight"] = runs
    return token


def _block_tokens(node, source_lines: list[str], source_map: SourceMap,
                  spans: list[Span]) -> list[Token]:
    name = node.type_name
    if name == "paragraph":
        return [Token("paragraph_open", map=_line_map(node)),
                _inline(node, source_map, spans), Token("paragraph_close")]
    if name == "heading":
        level = node.heading_level
        return [Token("heading_open", tag=f"h{level}", map=_line_map(node)),
                _inline(node, source_map, spans), Token("heading_close")]
    if name == "code_block":
        return [_code_token(node)]
    if name == "block_quote":
        tokens = [Token("blockquote_open", map=_line_map(node))]
        for child in node.children():
            tokens.extend(_block_tokens(child, source_lines, source_map, spans))
        tokens.append(Token("blockquote_close"))
        return tokens
    if name == "list":
        ordered = node.list_type == 2
        open_type = "ordered_list_open" if ordered else "bullet_list_open"
        close_type = "ordered_list_close" if ordered else "bullet_list_close"
        tokens = [Token(open_type, map=_line_map(node))]
        for child in node.children():
            tokens.extend(_block_tokens(child, source_lines, source_map, spans))
        tokens.append(Token(close_type))
        return tokens
    if name == "item":
        tokens = [Token("list_item_open", map=_line_map(node))]
        for child in node.children():
            tokens.extend(_block_tokens(child, source_lines, source_map, spans))
        tokens.append(Token("list_item_close"))
        return tokens
    if name == "table":
        return _table_tokens(node, source_lines, source_map, spans)
    if name == "thematic_break":
        return [Token("hr", map=_line_map(node))]
    if name == "html_block":
        return [Token("html_block", content=node.literal, map=_line_map(node))]
    if name == "frontmatter":
        return [Token("frontmatter", content=node.literal, map=_line_map(node))]
    if name == "formula_block":
        return [Token("formula_block", content=node.literal, map=_line_map(node))]
    return []


def parse_document(text: str) -> ParsedDocument:
    """Parse once into the editor token stream and the highlighter spans."""
    cmark = require_cmark()
    document = cmark.parse_document(text, cmark.Options.CMARK_OPT_HIGHLIGHT)
    source_lines = text.split("\n")
    source_map = SourceMap(text)
    tokens: list[Token] = []
    spans: list[Span] = []
    try:
        for child in document.children():
            tokens.extend(_block_tokens(child, source_lines, source_map, spans))
    finally:
        document.close()
    spans.sort(key=lambda span: (span.start, -span.end))
    return ParsedDocument(tokens, spans)


def parse_tokens(text: str) -> list[Token]:
    """Tokens only (kept for callers that do not need the spans)."""
    return parse_document(text).tokens


def render_html(text: str, options: int | None = None) -> str:
    """Render ``text`` to HTML with cmark itself.

    GFM task lists are enabled by default; pass an explicit options mask to
    override that (``0`` means cmark's plain default).
    """
    cmark = require_cmark()
    if options is None:
        options = cmark.Options.CMARK_OPT_TASKLISTS
    document = cmark.parse_document(text, options)
    try:
        return cmark.render_html(document, options)
    finally:
        document.close()
