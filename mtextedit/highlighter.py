"""Markdown syntax highlighter for the editor.

The highlighter styles two layers:

1. *Block structure* (headings, code fences, blockquotes, lists, rules) comes
   from the async render pipeline. The render manager emits ``structureAvailable``
   with line-range regions produced by
   :func:`mtextedit._markdown.collect_block_regions`; the highlighter caches
   them and re-highlights. The Markdown parse stays off the GUI thread.
2. *Inline* emphasis (``**bold**``, ``*italic*``, `` `code` ``, ``[link](u)``,
   ``~~strike~~``, ``==mark==``) uses the exact cmark spans delivered with the
   render. Regexes remain only as a fallback until the first render arrives.

Markers are cropped to zero width on lines without the cursor by applying a
transparent copy of the span format with negative absolute letter spacing;
the cursor's line expands them again.

Formats come from a :class:`mtextedit.theme.Theme`, i.e. VNote's ``.theme``
format. The bundled ``Native`` theme is the default, so the look follows VNote;
attribution and licensing are in ``THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)

from .theme import Format, Theme, load_default


def _char_format(style: Format, *, bold: bool = False, italic: bool = False,
                 strike: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    if style.color:
        fmt.setForeground(QColor(style.color))
    if style.background:
        fmt.setBackground(QColor(style.background))
    if style.bold or bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    if style.italic or italic:
        fmt.setFontItalic(True)
    if style.underline:
        fmt.setFontUnderline(True)
    if style.strike_through or strike:
        fmt.setFontStrikeOut(True)
    if style.font_size:
        fmt.setFontPointSize(float(style.font_size))
    if style.font_family:
        families = [name.strip() for name in style.font_family.split(",")
                    if name.strip()]
        if families:
            fmt.setFontFamilies(families)
    return fmt


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument,
                 manager: object | None = None,
                 theme: Theme | None = None):
        super().__init__(document)
        self._regions: list[dict] = []
        self._spans: list = []
        self._spans_ready = False
        self._cursor_line = -1
        self._conceal_markers = True
        self._concealed_cache: dict[tuple, QTextCharFormat] = {}
        self._theme = theme if theme is not None else load_default()
        self._setup_formats()
        self._setup_inline_patterns()
        if manager is not None:
            self.set_manager(manager)

    # -- configuration -------------------------------------------------------
    def theme(self) -> Theme:
        return self._theme

    def set_theme(self, theme: Theme) -> None:
        """Swap the theme and restyle every block."""
        self._theme = theme
        self._concealed_cache.clear()
        self._setup_formats()
        self._setup_inline_patterns()
        self.rehighlight()

    def _setup_formats(self) -> None:
        theme = self._theme
        self.f_heading = [
            _char_format(theme.syntax_style(f"H{level}"))
            for level in range(1, 7)
        ]
        for fmt in self.f_heading:
            fmt.setFontWeight(QFont.Weight.Bold)

        self.f_code = _char_format(theme.syntax_style("FENCEDCODEBLOCK"))
        if not self.f_code.fontFamilies():
            self.f_code.setFontFamily("monospace")
        self.f_inline_code = _char_format(theme.syntax_style("CODE"))
        if not self.f_inline_code.fontFamilies():
            self.f_inline_code.setFontFamily("monospace")
        self.f_quote = _char_format(theme.syntax_style("BLOCKQUOTE"))
        self.f_list = _char_format(theme.syntax_style("LIST_BULLET"))
        self.f_hr = _char_format(theme.syntax_style("HRULE"))
        self.f_strong = _char_format(theme.syntax_style("STRONG"), bold=True)
        self.f_emph = _char_format(theme.syntax_style("EMPH"), italic=True)
        self.f_link = _char_format(theme.syntax_style("LINK"))
        self.f_image = _char_format(theme.syntax_style("IMAGE"))
        self.f_strike = _char_format(theme.syntax_style("STRIKE"), strike=True)
        self.f_mark = _char_format(theme.syntax_style("MARK"))
        self.f_math = _char_format(theme.syntax_style("INLINEEQUATION"))


    def _setup_inline_patterns(self) -> None:
        self._inline_patterns = [
            (QRegularExpression(r"`[^`\n]+`"), self.f_inline_code),
            (QRegularExpression(r"\*\*[^*\n]+\*\*"), self.f_strong),
            (QRegularExpression(r"__[^_\n]+__"), self.f_strong),
            (QRegularExpression(r"(?<!\*)\*[^*\n]+\*(?!\*)"), self.f_emph),
            (QRegularExpression(r"(?<!_)_[^_\n]+_(?!_)"), self.f_emph),
            (QRegularExpression(r"~~[^~\n]+~~"), self.f_strike),
            (QRegularExpression(r"==[^=\n]+=="), self.f_mark),
            (QRegularExpression(r"\[[^\]\n]+\]\([^)\n]+\)"), self.f_link),
            (QRegularExpression(r"!\[[^\]\n]*\]\([^)\n]+\)"), self.f_image),
        ]

    # -- manager wiring ------------------------------------------------------
    def set_manager(self, manager):
        """Connect to a RenderManager to receive regions and exact spans."""
        manager.structureAvailable.connect(self.set_regions)
        if hasattr(manager, "spansAvailable"):
            manager.spansAvailable.connect(self.set_spans)

    def set_regions(self, regions: list[dict]):
        self._regions = regions or []
        self.rehighlight()

    # -- highlighting --------------------------------------------------------
    def set_spans(self, spans: list) -> None:
        """Receive exact inline spans (absolute character offsets)."""
        self._spans = list(spans or [])
        self._spans_ready = True
        self.rehighlight()

    def set_conceal_markers(self, enabled: bool) -> None:
        """Crop markers on non-cursor lines (default) or show them."""
        self._conceal_markers = bool(enabled)
        self.rehighlight()

    def set_cursor_line(self, line: int) -> None:
        """Markers stay visible on the cursor's line and dim elsewhere."""
        if line == self._cursor_line:
            return
        previous, self._cursor_line = self._cursor_line, line
        document = self.document()
        for number in {previous, line}:
            if 0 <= number < document.blockCount():
                self.rehighlightBlock(document.findBlockByNumber(number))

    def _concealed_format(self, marker: str,
                          style_fmt: QTextCharFormat) -> QTextCharFormat:
        """A transparent, zero-advance format for ``marker``.

        Negative absolute letter spacing equal to the run's average glyph
        advance makes the run occupy zero width, so Qt's own layout crops it
        without a custom document layout.
        """
        families = style_fmt.fontFamilies() or []
        key = (marker, style_fmt.fontWeight(), style_fmt.fontItalic(),
               tuple(families), style_fmt.fontPointSize())
        cached = self._concealed_cache.get(key)
        if cached is not None:
            return cached
        font = QFont(self.document().defaultFont())
        if families:
            font.setFamilies(families)
        if style_fmt.fontPointSize() > 0:
            font.setPointSizeF(style_fmt.fontPointSize())
        font.setBold(style_fmt.fontWeight() >= QFont.Weight.Bold)
        font.setItalic(style_fmt.fontItalic())
        advance = QFontMetricsF(font).horizontalAdvance(marker)
        spacing = -(advance / len(marker)) if marker else 0.0

        fmt = QTextCharFormat(style_fmt)
        fmt.setForeground(QColor(0, 0, 0, 0))
        fmt.clearBackground()
        fmt.setFontUnderline(False)
        fmt.setFontStrikeOut(False)
        fmt.setFontLetterSpacingType(QFont.SpacingType.AbsoluteSpacing)
        fmt.setFontLetterSpacing(spacing)
        self._concealed_cache[key] = fmt
        return fmt

    def _format_for(self, style: str):
        return {
            "strong": self.f_strong,
            "emph": self.f_emph,
            "code": self.f_inline_code,
            "link": self.f_link,
            "image": self.f_image,
            "strike": self.f_strike,
            "mark": self.f_mark,
            "math": self.f_math,
        }.get(style)

    def _highlight_spans(self, text: str, line: int, block_start: int,
                         block_end: int) -> None:
        for span in self._spans:
            if span.end <= block_start or span.start >= block_end:
                continue
            start = max(span.start, block_start) - block_start
            end = min(span.end, block_end) - block_start
            fmt = self._format_for(span.style)
            if fmt is not None and end > start:
                self.setFormat(start, end - start, fmt)
            if line == self._cursor_line or not self._conceal_markers:
                continue
            content_start = max(start, min(span.content_start, block_end)
                                - block_start)
            content_end = max(start, min(span.content_end, block_end)
                              - block_start)
            style_fmt = fmt if fmt is not None else QTextCharFormat()
            if content_start > start:
                self.setFormat(start, content_start - start,
                               self._concealed_format(text[start:content_start],
                                                      style_fmt))
            if end > content_end:
                self.setFormat(content_end, end - content_end,
                               self._concealed_format(text[content_end:end],
                                                      style_fmt))

    def highlightBlock(self, text: str) -> None:
        block = self.currentBlock()
        line = block.blockNumber()
        block_start = block.position()
        block_end = block_start + len(text)

        if self._spans_ready:
            self._highlight_spans(text, line, block_start, block_end)
        else:
            # Fallback until the first render delivers spans.
            for pattern, fmt in self._inline_patterns:
                it = pattern.globalMatch(text)
                while it.hasNext():
                    match = it.next()
                    self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

        # Block structure from the async pipeline.
        for region in self._regions:
            if region["start"] <= line <= region["end"]:
                kind = region["kind"]
                if kind == "heading":
                    level = region.get("level", 1)
                    fmt = self.f_heading[min(max(level, 1), 6) - 1]
                    self.setFormat(0, len(text), fmt)
                elif kind == "code":
                    self.setFormat(0, len(text), self.f_code)
                elif kind == "quote":
                    self.setFormat(0, len(text), self.f_quote)
                elif kind == "list":
                    self.setFormat(0, len(text), self.f_list)
                elif kind == "hr":
                    self.setFormat(0, len(text), self.f_hr)
                break
