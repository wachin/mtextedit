"""In-place Markdown preview.

Mirrors VNote's ``TextDocumentLayout`` idea in a tractable way: for the block
types VNote previews (fenced code, tables, images), we reserve a vertical band
above the source block and paint a rendered preview into it. Regular text stays
as editable Markdown source -- exactly VNote's in-place preview, but implemented
with block top-margins instead of a custom ``QAbstractTextDocumentLayout``.

The editor (``MTextEdit``) owns the reservation and painting; this module only
knows how to turn a token stream into specs, measure them and draw
them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPen,
    QPixmap,
)

from .code_style import CODE_BG, CODE_BORDER, CODE_TEXT

_PAD = 8
_TITLE_H = 16
_ROW_H = 24
_MAX_H = 420
# Table columns: never narrower than this, and never squeezed below the cell's
# own text plus its horizontal padding when measuring.
_MIN_COL_W = 48.0
_CELL_PAD = 4
_CODE_BG = QColor(CODE_BG)
_CODE_BORDER = QColor(CODE_BORDER)
_CODE_FG = QColor(CODE_TEXT)
_HEAD_BG = QColor("#eaeef2")
_GRID = QColor("#d0d7de")
_TEXT = QColor("#24292f")


@dataclass
class PreviewSpec:
    block: int                 # 0-based source line / QTextBlock number
    kind: str                  # "code" | "table" | "image"
    height: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Build specs from the token stream
# ---------------------------------------------------------------------------

def build_specs(tokens: List[Any], base_path: Optional[str] = None) -> List[PreviewSpec]:
    specs: List[PreviewSpec] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        ty = tok.type
        if ty in ("fence", "code_block"):
            line = tok.map[0] if tok.map else 0
            lang = ""
            if ty == "fence" and tok.info:
                lang = tok.info.strip().split()[0]
            specs.append(PreviewSpec(block=line, kind="code",
                                     data={"lang": lang, "code": tok.content,
                                           "highlight": tok.meta.get("highlight")}))
            i += 1
        elif ty == "table_open":
            line = tok.map[0] if tok.map else 0
            rows, end = _parse_table(tokens, i)
            if rows:
                specs.append(PreviewSpec(block=line, kind="table",
                                         data={"rows": rows}))
            i = end + 1
        elif ty == "paragraph_open":
            inline = tokens[i + 1] if i + 1 < n else None
            imgs = _paragraph_images(inline)
            if imgs:
                line = tok.map[0] if tok.map else 0
                for src, alt in imgs:
                    specs.append(PreviewSpec(
                        block=line, kind="image",
                        data={"src": src, "alt": alt, "base": base_path,
                              "abs_path": _resolve_image_path(src, base_path)}))
            i += 3
        else:
            i += 1
    return specs


def image_requests(tokens: List[Any], base_path: Optional[str] = None) -> List[tuple]:
    """Return ``(absolute_path, mtime)`` for local images the preview needs.

    Called from the render worker so the decode can happen off the GUI thread
    (D13). Remote/``data:`` images and missing files are skipped.
    """
    out: List[tuple] = []
    for spec in build_specs(tokens, base_path):
        if spec.kind != "image":
            continue
        path = spec.data.get("abs_path")
        if not path:
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        out.append((path, mtime))
    return out


def _paragraph_images(inline) -> List[tuple]:
    if inline is None or not inline.children:
        return []
    images = []
    others = False
    for child in inline.children:
        if child.type == "image":
            attrs = dict(child.attrs or [])
            images.append((attrs.get("src", ""), attrs.get("alt", "")))
        elif child.type not in ("softbreak", "hardbreak"):
            if child.type == "text" and not child.content.strip():
                continue
            others = True
    if images and not others:
        return images
    return []


def _parse_table(tokens: List[Any], start: int):
    rows: List[List[Dict[str, str]]] = []
    cur_row: Optional[List[Dict[str, str]]] = None
    cur_cell: Optional[Dict[str, str]] = None
    j = start + 1
    while j < len(tokens):
        tok = tokens[j]
        ty = tok.type
        if ty == "table_close":
            return rows, j
        if ty == "tr_open":
            cur_row = []
        elif ty == "tr_close":
            if cur_row is not None:
                rows.append(cur_row)
                cur_row = None
        elif ty in ("th_open", "td_open"):
            cur_cell = {"text": "", "align": "left"}
            for key, value in (tok.attrs or []):
                if key == "style" and "text-align" in value:
                    cur_cell["align"] = value.split(":")[-1].strip().rstrip(";")
        elif ty == "inline" and cur_cell is not None:
            cur_cell["text"] = tok.content
        elif ty in ("th_close", "td_close") and cur_row is not None and cur_cell is not None:
            cur_row.append(cur_cell)
            cur_cell = None
        j += 1
    return rows, j


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def _code_font() -> QFont:
    f = QFont("monospace")
    f.setPointSize(9)
    return f


def _table_font() -> QFont:
    f = QFont()
    f.setPointSize(9)
    return f


def column_widths(rows: list[list[dict[str, str]]], available: float,
                  metrics: QFontMetricsF) -> list[float]:
    """Content-proportional column widths that still fill ``available``.

    Equal widths used to clip every cell of a table whose columns carry very
    different amounts of text. Weighting each column by its widest cell gives
    the text room; cells that still do not fit are elided when painted. A floor
    keeps an empty or one-character column from collapsing.
    """
    ncols = max((len(row) for row in rows), default=0)
    if not ncols:
        return []
    natural: list[float] = []
    for c_index in range(ncols):
        widest = 0.0
        for row in rows:
            text = row[c_index]["text"] if c_index < len(row) else ""
            widest = max(widest, metrics.horizontalAdvance(text))
        natural.append(max(_MIN_COL_W, widest + _CELL_PAD * 2))
    total = sum(natural) or 1.0
    return [available * width / total for width in natural]


def measure_specs(
    specs: List[PreviewSpec],
    available_width: int,
    image_provider: Optional[Callable[[str], Any]] = None,
) -> List[PreviewSpec]:
    """Fill ``height`` on each spec; drop those that cannot be shown.

    ``image_provider(abs_path)`` returns a decoded ``QImage`` (produced off the
    GUI thread by the render worker). The ``QPixmap`` conversion happens here,
    on the GUI thread, as Qt requires.
    """
    out: List[PreviewSpec] = []
    fm = QFontMetricsF(_code_font())
    for spec in specs:
        if spec.kind == "code":
            lines = spec.data.get("code", "").rstrip("\n").split("\n") or [""]
            title = _TITLE_H if spec.data.get("lang") else 0
            spec.height = min(_PAD * 2 + title + len(lines) * fm.height(), _MAX_H)
            spec.data["lines"] = lines
            spec.data["fm_height"] = fm.height()
            spec.data["fm_ascent"] = fm.ascent()
        elif spec.kind == "table":
            rows = spec.data.get("rows", [])
            spec.height = min(_PAD * 2 + len(rows) * _ROW_H, _MAX_H)
            spec.data["col_widths"] = column_widths(
                rows, max(1.0, available_width - 2),
                QFontMetricsF(_table_font()))
        elif spec.kind == "image":
            pix = _image_pixmap(spec, image_provider)
            if pix is None or pix.isNull():
                continue
            width = max(40, min(pix.width(), available_width))
            spec.height = min(pix.height() * width / max(1, pix.width()), _MAX_H)
            spec.data["pixmap"] = pix
            spec.data["draw_w"] = width
        if spec.height > 0:
            out.append(spec)
    return out


def _resolve_image_path(src: str, base: Optional[str]) -> Optional[str]:
    if not src:
        return None
    if src.startswith(("http://", "https://", "data:")):
        return None  # no network / inline data in the in-place preview
    path = src
    if base and not os.path.isabs(path):
        path = os.path.join(base, src)
    path = os.path.abspath(path)
    return path if os.path.isfile(path) else None


def _image_pixmap(spec: PreviewSpec, provider) -> Optional[QPixmap]:
    abs_path = spec.data.get("abs_path")
    if not abs_path:
        return None
    if provider is not None:
        image = provider(abs_path)  # decoded off-thread by the render worker
        if image is not None and not image.isNull():
            return QPixmap.fromImage(image)
    # Fallback: decode on the GUI thread if the worker has not produced it
    # (e.g. a cache miss before the image signal arrives).
    pix = QPixmap(abs_path)
    return pix if not pix.isNull() else None


# ---------------------------------------------------------------------------
# Painting
# ---------------------------------------------------------------------------

def paint_spec(painter: QPainter, spec: PreviewSpec, rect: QRectF) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if spec.kind == "code":
        _paint_code(painter, spec, rect)
    elif spec.kind == "table":
        _paint_table(painter, spec, rect)
    elif spec.kind == "image":
        _paint_image(painter, spec, rect)
    painter.restore()


def _paint_code(painter: QPainter, spec: PreviewSpec, rect: QRectF) -> None:
    painter.setBrush(_CODE_BG)
    painter.setPen(QPen(_CODE_BORDER, 1))
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

    lang = spec.data.get("lang", "")
    y = rect.top() + _PAD
    if lang:
        f = QFont("monospace"); f.setPointSize(8); f.setItalic(True)
        painter.setFont(f)
        painter.setPen(QColor("#57606a"))
        painter.drawText(QRectF(rect.left() + _PAD, y, rect.width() - 2 * _PAD, _TITLE_H),
                         int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                         lang)
        y += _TITLE_H

    f = _code_font()
    painter.setFont(f)
    painter.setPen(_CODE_FG)
    fm_h = spec.data.get("fm_height", 14.0)
    ascent = spec.data.get("fm_ascent", 11.0)
    left = rect.left() + _PAD
    text_width = rect.width() - 2 * _PAD
    # ``highlight`` holds Pygments runs produced by the render worker (D12).
    # Without them — unknown language, indented block, oversized fence — the
    # line paints flat, exactly as before.
    runs = spec.data.get("highlight") or []
    metrics = QFontMetricsF(f)
    painter.save()
    painter.setClipRect(QRectF(left, rect.top(), text_width, rect.height()))
    for index, line in enumerate(spec.data.get("lines", [])):
        if y + fm_h > rect.bottom():
            break
        line_runs = runs[index] if index < len(runs) else None
        if line_runs:
            x = left
            baseline = y + ascent
            for text, colour in line_runs:
                painter.setPen(QColor(colour))
                painter.drawText(QPointF(x, baseline), text)
                x += metrics.horizontalAdvance(text)
        else:
            painter.setPen(_CODE_FG)
            painter.drawText(QRectF(left, y, text_width, fm_h),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                             line.expandtabs(4))
        y += fm_h
    painter.restore()


def _paint_table(painter: QPainter, spec: PreviewSpec, rect: QRectF) -> None:
    rows = spec.data.get("rows", [])
    if not rows:
        return
    ncols = max(len(r) for r in rows)
    widths = spec.data.get("col_widths") or []
    if len(widths) != ncols:  # spec built without measurement
        widths = [(rect.width() - 2) / max(1, ncols)] * ncols
    painter.setPen(QPen(_GRID, 1))
    f = _table_font()
    header_f = QFont(f)
    header_f.setBold(True)
    metrics = QFontMetricsF(f)

    y = rect.top() + _PAD / 2
    for r_index, row in enumerate(rows):
        row_h = _ROW_H
        if r_index == 0:
            painter.setBrush(_HEAD_BG)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(rect.left(), y, rect.width(), row_h))
            painter.setPen(QPen(_GRID, 1))
        painter.setFont(header_f if r_index == 0 else f)
        x = rect.left()
        for c_index in range(ncols):
            width = widths[c_index]
            painter.drawRect(QRectF(x, y, width, row_h))
            text = row[c_index]["text"] if c_index < len(row) else ""
            painter.setPen(_TEXT)
            align = Qt.AlignmentFlag.AlignLeft
            if c_index < len(row) and row[c_index]["align"] == "center":
                align = Qt.AlignmentFlag.AlignHCenter
            elif c_index < len(row) and row[c_index]["align"] == "right":
                align = Qt.AlignmentFlag.AlignRight
            inner = max(0.0, width - _CELL_PAD * 2)
            shown = metrics.elidedText(
                text, Qt.TextElideMode.ElideRight, int(inner))
            painter.drawText(
                QRectF(x + _CELL_PAD, y, inner, row_h),
                int(align | Qt.AlignmentFlag.AlignVCenter),
                shown,
            )
            painter.setPen(QPen(_GRID, 1))
            x += width
        y += row_h
        if y > rect.bottom():
            break


def _paint_image(painter: QPainter, spec: PreviewSpec, rect: QRectF) -> None:
    pix = spec.data.get("pixmap")
    if pix is None:
        return
    width = spec.data.get("draw_w", rect.width())
    height = spec.height
    target = QRectF(rect.left(), rect.top(), min(width, rect.width()), height)
    painter.drawPixmap(target, pix, QRectF(pix.rect()))
