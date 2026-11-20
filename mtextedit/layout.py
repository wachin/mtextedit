"""A custom ``QAbstractTextDocumentLayout`` with marker concealment.

This is the layout-level counterpart of the highlighter's format trick: instead
of collapsing marker runs with negative letter spacing, the layout builds a
*display* string per block with the concealed ranges removed, keeps a
document<->display position map, and paints that. Cursor, selection and hit
testing go through the same map.

Scope of this first phase:

* plain source text with character formats from ``Theme`` spans and the block
  regions (headings, quotes, code, rules);
* concealment of the syntax markers carried by inline spans;
* painting, selection, cursor, ``hitTest`` and document geometry.

Not covered yet: inline images/preview widgets, math blocks, tables, bidi
reordering beyond what ``QTextLayout`` does, and IME pre-edit text (Qt asks the
block layout for the pre-edit area, which this layout does not populate).

Design is inspired by VNote's ``TextDocumentLayout`` (LGPL-3.0); the code below
is original and only the behaviour/architecture was studied. See
``THIRD_PARTY_NOTICES.md`` and ``themes/README.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, QSizeF, Qt
from PyQt6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFont,
    QTextBlock,
    QTextCharFormat,
    QTextFormat,
    QTextLayout,
    QTextOption,
)

from .theme import Format, Theme, load_default


def _char_format(style: Format, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
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
    if style.strike_through:
        fmt.setFontStrikeOut(True)
    if style.font_size:
        fmt.setFontPointSize(float(style.font_size))
    families = [name.strip() for name in (style.font_family or "").split(",")
                if name.strip()]
    if families:
        fmt.setFontFamilies(families)
    return fmt


def _format_range(start: int, length: int, fmt: QTextCharFormat) -> QTextLayout.FormatRange:
    """Build a QTextLayout.FormatRange (PyQt has no positional constructor)."""
    entry = QTextLayout.FormatRange()
    entry.start = start
    entry.length = length
    entry.format = fmt
    return entry


@dataclass
class _BlockLayout:
    block: QTextBlock
    top: float
    text_top: float
    top_margin: float
    bottom_margin: float
    total_height: float
    layout: QTextLayout
    display: str
    display_to_doc: list[int]
    doc_to_display: list[int]
    source: str
    preedit_text: str
    preedit_position: int
    preedit_display_pos: int
    preedit_len: int

    @property
    def height(self) -> float:
        return self.total_height

    @property
    def width(self) -> float:
        if self.layout.lineCount() == 0:
            return 0.0
        return max(self.layout.lineAt(i).naturalTextWidth()
                   for i in range(self.layout.lineCount()))


def _visible_map(text: str, hidden: list[tuple[int, int]]):
    visible = [True] * len(text)
    for start, end in hidden:
        for index in range(max(0, start), min(len(text), end)):
            visible[index] = False
    display_to_doc: list[int] = []
    doc_to_display = [0] * (len(text) + 1)
    out: list[str] = []
    display_index = 0
    for index, char in enumerate(text):
        doc_to_display[index] = display_index
        if visible[index]:
            display_to_doc.append(index)
            out.append(char)
            display_index += 1
    doc_to_display[len(text)] = display_index
    return "".join(out), display_to_doc, doc_to_display


class MarkdownDocumentLayout(QAbstractTextDocumentLayout):
    """Layout that paints source text with concealed marker ranges."""

    def __init__(self, document, theme: Theme | None = None):
        super().__init__(document)
        self._theme = theme if theme is not None else load_default()
        self._spans: list = []
        self._regions: list[dict] = []
        self._cursor_block = -1
        self._blocks: dict[int, _BlockLayout] = {}
        self._height = 0.0
        self._width = 0.0
        self._formats: dict[str, QTextCharFormat] = {}
        self._rebuild_formats()
        self._dirty = True

    # -- configuration -------------------------------------------------------
    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._rebuild_formats()
        self._invalidate()

    def set_spans(self, spans: list) -> None:
        self._spans = list(spans or [])
        self._invalidate()

    def set_regions(self, regions: list[dict]) -> None:
        self._regions = list(regions or [])
        self._invalidate()

    def set_cursor_block(self, block_number: int) -> None:
        if block_number == self._cursor_block:
            return
        previous, self._cursor_block = self._cursor_block, block_number
        self._blocks.pop(previous, None)
        self._blocks.pop(block_number, None)
        self._dirty = True
        self._refresh()

    def _rebuild_formats(self) -> None:
        theme = self._theme
        self._formats = {
            "strong": _char_format(theme.syntax_style("STRONG"), bold=True),
            "emph": _char_format(theme.syntax_style("EMPH"), italic=True),
            "code": _char_format(theme.syntax_style("CODE")),
            "link": _char_format(theme.syntax_style("LINK")),
            "image": _char_format(theme.syntax_style("IMAGE")),
            "strike": _char_format(theme.syntax_style("STRIKE")),
            "mark": _char_format(theme.syntax_style("MARK")),
            "math": _char_format(theme.syntax_style("INLINEEQUATION")),
        }
        self._heading_formats = [
            _char_format(theme.syntax_style(f"H{level}")) for level in range(1, 7)
        ]
        self._quote_format = _char_format(theme.syntax_style("BLOCKQUOTE"))
        self._code_format = _char_format(theme.syntax_style("FENCEDCODEBLOCK"))
        self._hr_format = _char_format(theme.syntax_style("HRULE"))

    def _invalidate(self) -> None:
        self._blocks.clear()
        self._dirty = True
        self._refresh()
        self.update.emit(QRectF(0, 0, max(self._width, 1.0), max(self._height, 1.0)))
        self.documentSizeChanged.emit(self.documentSize())

    # -- geometry ------------------------------------------------------------
    def _margin(self) -> float:
        return self.document().documentMargin()

    def _sync_preedit(self) -> None:
        for number, entry in list(self._blocks.items()):
            block = entry.block
            if not block.isValid():
                self._blocks.pop(number)
                self._dirty = True
                continue
            layout = block.layout()
            text = (layout.preeditAreaText() if layout else "") or ""
            position = layout.preeditAreaPosition() if layout else 0
            if text != entry.preedit_text or position != entry.preedit_position:
                self._blocks.pop(number)
                self._dirty = True

    def _refresh(self) -> None:
        self._sync_preedit()
        if not self._dirty:
            return
        self._dirty = False
        margin = self._margin()
        top = margin
        width = 0.0
        seen: set[int] = set()
        block = self.document().firstBlock()
        while block.isValid():
            if block.isVisible():
                entry = self._layout_block(block)
                entry.top = top
                entry.text_top = top + entry.top_margin
                top += entry.height
                width = max(width, entry.width)
                seen.add(block.blockNumber())
            block = block.next()
        for number in list(self._blocks):
            if number not in seen:
                self._blocks.pop(number)
        text_width = self.document().textWidth()
        if text_width > 0:
            self._width = max(width, text_width)
        else:
            self._width = width + margin * 2
        self._height = top + margin

    def _hidden_ranges(self, block: QTextBlock) -> list[tuple[int, int]]:
        if block.blockNumber() == self._cursor_block:
            return []
        start = block.position()
        end = start + len(block.text())
        ranges: list[tuple[int, int]] = []
        for span in self._spans:
            if span.end <= start or span.start >= end:
                continue
            left_start = max(span.start, start) - start
            left_end = min(span.content_start, end) - start
            right_start = max(span.content_end, start) - start
            right_end = min(span.end, end) - start
            if left_end > left_start:
                ranges.append((left_start, left_end))
            if right_end > right_start:
                ranges.append((right_start, right_end))
        return ranges

    def _layout_block(self, block: QTextBlock) -> _BlockLayout:
        number = block.blockNumber()
        text = block.text()
        block_layout = block.layout()
        preedit_text = (block_layout.preeditAreaText() if block_layout else "") or ""
        preedit_position = block_layout.preeditAreaPosition() if block_layout else 0
        block_format = block.blockFormat()
        top_margin = block_format.topMargin()
        bottom_margin = block_format.bottomMargin()

        cached = self._blocks.get(number)
        if (cached is not None and cached.block == block
                and cached.source == text
                and cached.preedit_text == preedit_text
                and cached.preedit_position == preedit_position
                and cached.top_margin == top_margin
                and cached.bottom_margin == bottom_margin):
            return cached

        display, display_to_doc, doc_to_display = _visible_map(
            text, self._hidden_ranges(block))
        preedit_display_pos = doc_to_display[min(max(preedit_position, 0), len(text))]
        if preedit_text:
            display = (display[:preedit_display_pos] + preedit_text
                       + display[preedit_display_pos:])
            display_to_doc = (display_to_doc[:preedit_display_pos]
                              + [preedit_position] * len(preedit_text)
                              + display_to_doc[preedit_display_pos:])
            for index in range(preedit_position + 1, len(text) + 1):
                doc_to_display[index] += len(preedit_text)
        layout = QTextLayout(display, self.document().defaultFont())
        option = QTextOption()
        if self.document().textWidth() <= 0:
            option.setWrapMode(QTextOption.WrapMode.NoWrap)
        layout.setTextOption(option)

        formats: list[QTextLayout.FormatRange] = []
        base = self._base_format(block)
        if base is not None and display:
            formats.append(_format_range(0, len(display), base))
        for span in self._spans:
            start = block.position()
            end = start + len(text)
            if span.end <= start or span.start >= end:
                continue
            begin = max(span.start, start) - start
            finish = min(span.end, end) - start
            display_begin = doc_to_display[begin]
            display_end = doc_to_display[finish]
            style_format = self._formats.get(span.style)
            if style_format is None or display_end <= display_begin:
                continue
            formats.append(_format_range(
                display_begin, display_end - display_begin, style_format))
        if preedit_text:
            underline = QTextCharFormat()
            underline.setFontUnderline(True)
            formats.append(_format_range(preedit_display_pos,
                                         len(preedit_text), underline))
        layout.setFormats(formats)

        text_width = self.document().textWidth()
        line_width = text_width if text_width > 0 else 1e9
        layout.beginLayout()
        y = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(line_width)
            line.setPosition(QPointF(0, y))
            y += line.height()
        layout.endLayout()

        entry = _BlockLayout(block, 0.0, 0.0, top_margin, bottom_margin,
                             top_margin + y + bottom_margin, layout, display,
                             display_to_doc, doc_to_display, text,
                             preedit_text, preedit_position,
                             preedit_display_pos, len(preedit_text))
        self._blocks[number] = entry
        return entry

    def _base_format(self, block: QTextBlock) -> QTextCharFormat | None:
        number = block.blockNumber()
        for region in self._regions:
            if region["start"] <= number <= region["end"]:
                kind = region["kind"]
                if kind == "heading":
                    level = min(max(region.get("level", 1), 1), 6)
                    return self._heading_formats[level - 1]
                if kind == "code":
                    return self._code_format
                if kind == "quote":
                    return self._quote_format
                if kind == "hr":
                    return self._hr_format
                return None
        return None

    # -- QAbstractTextDocumentLayout ----------------------------------------
    def documentSize(self) -> QSizeF:
        self._refresh()
        return QSizeF(max(self._width, 1.0), max(self._height, 1.0))

    def frameBoundingRect(self, frame) -> QRectF:
        self._refresh()
        return QRectF(0, 0, self._width, self._height)

    def blockBoundingRect(self, block: QTextBlock) -> QRectF:
        self._refresh()
        entry = self._blocks.get(block.blockNumber())
        if entry is None:
            return QRectF()
        margin = self._margin()
        return QRectF(margin, entry.top, max(entry.width, 1.0), entry.height)

    def hitTest(self, point, accuracy=Qt.HitTestAccuracy.FuzzyHit) -> int:
        self._refresh()
        margin = self._margin()
        block = self.document().firstBlock()
        while block.isValid():
            entry = self._blocks.get(block.blockNumber())
            if entry is not None and entry.top <= point.y() < entry.top + entry.height:
                return self._hit_block(entry, point.x() - margin,
                                       point.y() - entry.text_top, accuracy)
            block = block.next()
        if accuracy == Qt.HitTestAccuracy.ExactHit:
            return -1
        last = self.document().lastBlock()
        entry = self._blocks.get(last.blockNumber())
        if entry is None:
            return 0
        return last.position() + len(last.text())

    def _hit_block(self, entry: _BlockLayout, x: float, y: float,
                   accuracy) -> int:
        layout = entry.layout
        if layout.lineCount() == 0:
            return entry.block.position()
        line = layout.lineAt(layout.lineCount() - 1)
        for index in range(layout.lineCount()):
            candidate = layout.lineAt(index)
            if candidate.y() <= y < candidate.y() + candidate.height():
                line = candidate
                break
        if not line.isValid():
            return entry.block.position()
        display_cursor = line.xToCursor(max(0.0, x))
        display_cursor += line.textStart()
        display_cursor = min(max(display_cursor, 0), len(entry.display))
        if display_cursor >= len(entry.display_to_doc):
            return entry.block.position() + len(entry.block.text())
        return entry.block.position() + entry.display_to_doc[display_cursor]

    def draw(self, painter, context) -> None:
        self._refresh()
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        margin = self._margin()
        clip = context.clip if context.clip.isValid() else QRectF()
        for number, entry in sorted(self._blocks.items()):
            offset = QPointF(margin, entry.text_top)
            rect = QRectF(offset, QSizeF(entry.width, entry.height))
            if clip.isValid() and not clip.intersects(rect):
                continue

            for selection in context.selections:
                if (not selection.cursor.hasSelection()
                        and selection.cursor.blockNumber() == number
                        and selection.format.hasProperty(
                            QTextFormat.Property.FullWidthSelection)):
                    background = selection.format.background()
                    if background.style() != Qt.BrushStyle.NoBrush:
                        painter.fillRect(
                            QRectF(rect.left(), rect.top(),
                                   max(rect.width(), self._width - margin * 2),
                                   entry.height), background)

            formats: list[QTextLayout.FormatRange] = []
            block_start = entry.block.position()
            block_end = block_start + len(entry.block.text())
            for selection in context.selections:
                start = max(selection.cursor.selectionStart(), block_start)
                end = min(selection.cursor.selectionEnd(), block_end)
                if end > start:
                    display_start = entry.doc_to_display[start - block_start]
                    display_end = entry.doc_to_display[end - block_start]
                    if display_end > display_start:
                        formats.append(_format_range(
                            display_start, display_end - display_start,
                            selection.format))
            entry.layout.draw(painter, offset, formats, clip)

            cursor = context.cursorPosition
            if cursor < -1 and entry.preedit_len:
                display_cursor = entry.preedit_display_pos - (cursor + 2)
                display_cursor = min(max(display_cursor, 0), len(entry.display))
                entry.layout.drawCursor(painter, offset, display_cursor, 1)
            elif block_start <= cursor <= block_end:
                display_cursor = entry.doc_to_display[
                    min(cursor - block_start, len(entry.doc_to_display) - 1)]
                entry.layout.drawCursor(painter, offset, display_cursor, 1)
        painter.restore()

    def documentChanged(self, position: int, chars_removed: int,
                        chars_added: int) -> None:
        self._dirty = True
        self._refresh()
        self.update.emit(QRectF(0, 0, max(self._width, 1.0), max(self._height, 1.0)))
        self.documentSizeChanged.emit(self.documentSize())
