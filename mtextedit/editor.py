"""The Markdown editor surface with VNote-style in-place preview.

``MTextEdit`` is a ``QTextEdit`` specialised for Markdown. Unlike a side-by-side
editor/preview layout, it renders previews *inside* the editing surface: for the
block types VNote previews (fenced code, tables, images) a band is reserved above
the source block and the rendered preview is painted into it, while regular text
stays as editable Markdown source.

This mirrors VNote's ``TextDocumentLayout`` intent with a simpler mechanism --
block top-margins reserve the band, and ``paintEvent`` draws into it -- so the
component stays small and portable while giving the same single-pane experience.

The editor knows nothing about notebooks or the application shell, so it can be
embedded in any PyQt6 project (e.g. the fourth panel of an e-Sword-like tool).
"""

from __future__ import annotations

import os
from typing import List, Optional

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QTextCursor
from PyQt6.QtWidgets import QTextEdit

from . import inplace
from .highlighter import MarkdownHighlighter


class MTextEdit(QTextEdit):
    # Emitted (debounced) with the full document source whenever the user edits.
    renderRequested = pyqtSignal(str)

    def __init__(self, parent=None, render_delay_ms: int = 120,
                 use_custom_layout: bool = True):
        super().__init__(parent)
        self._highlighter = MarkdownHighlighter(self.document())
        self._custom_layout = None
        if use_custom_layout:
            from .layout import MarkdownDocumentLayout

            self._custom_layout = MarkdownDocumentLayout(self.document())
            self.document().setDocumentLayout(self._custom_layout)
            self._highlighter.setDocument(None)
        self.cursorPositionChanged.connect(self._sync_cursor_line)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(render_delay_ms)
        self._timer.timeout.connect(self._emit_render)
        self.textChanged.connect(self._on_text_changed)

        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setAcceptRichText(False)
        self.setAccessibleName("Markdown editor")
        self.setAccessibleDescription(
            "Markdown source editor. Syntax markers are concealed on lines "
            "without the cursor.")

        self._base_path: Optional[str] = None
        self._inplace_enabled = True
        self._specs: List[inplace.PreviewSpec] = []
        self._spec_blocks: set = set()
        self._applying = False  # guards the textChanged fired by block formats
        self._last_emitted_text = ""  # text-compare guard (block formats fire textChanged)
        self._manager = None
        self._images: dict = {}  # abs_path -> QImage decoded off-thread (D13)
        self._image_paster = None  # host hook: (QImage) -> markdown path | None

    # -- render wiring -------------------------------------------------------
    def _on_text_changed(self):
        if self._applying:
            return
        # Block top-margin changes fire textChanged but do not alter the text;
        # comparing against the last rendered text prevents a render loop.
        if self.toPlainText() == self._last_emitted_text:
            return
        self._timer.start()

    def _emit_render(self):
        text = self.toPlainText()
        if text == self._last_emitted_text:
            return
        self._last_emitted_text = text
        self.renderRequested.emit(text)

    # -- editing shortcuts ---------------------------------------------------
    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        key = event.key()
        if control and not shift and key == Qt.Key.Key_B:
            self._toggle_inline("**")
            return
        if control and not shift and key == Qt.Key.Key_I:
            self._toggle_inline("*")
            return
        if control and key == Qt.Key.Key_K:
            self._insert_link()
            return
        if control and key == Qt.Key.Key_QuoteLeft:
            self._toggle_inline("`")
            return
        if control and shift and key == Qt.Key.Key_X:
            self._toggle_inline("~~")
            return
        super().keyPressEvent(event)

    def _select(self, start: int, end: int) -> None:
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _toggle_inline(self, marker: str) -> None:
        """Wrap or unwrap the selection (or the caret) with a marker pair."""
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        text = self.document().toPlainText()
        size = len(marker)

        if start == end:
            if text[max(0, start - size):start] == marker and \
                    text[start:start + size] == marker:
                cursor.beginEditBlock()
                cursor.setPosition(start - size)
                cursor.setPosition(start + size, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                cursor.endEditBlock()
                self.setTextCursor(cursor)
                return
            cursor.insertText(marker + marker)
            cursor.setPosition(start + size)
            self.setTextCursor(cursor)
            return

        selected = text[start:end]
        if (len(selected) >= 2 * size and selected.startswith(marker)
                and selected.endswith(marker)):
            inner = selected[size:-size]
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(inner)
            cursor.endEditBlock()
            self._select(start, start + len(inner))
            return
        if text[max(0, start - size):start] == marker and \
                text[end:end + size] == marker:
            cursor.beginEditBlock()
            cursor.setPosition(start - size)
            cursor.setPosition(end + size, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(selected)
            cursor.endEditBlock()
            self._select(start - size, end - size)
            return

        cursor.beginEditBlock()
        cursor.setPosition(end)
        cursor.insertText(marker)
        cursor.setPosition(start)
        cursor.insertText(marker)
        cursor.endEditBlock()
        self._select(start + size, end + size)

    def _insert_link(self) -> None:
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        if start == end:
            cursor.insertText("[]()")
            cursor.setPosition(cursor.position() - 3)
        else:
            selected = self.document().toPlainText()[start:end]
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(f"[{selected}]()")
            cursor.endEditBlock()
            cursor.setPosition(start + len(selected) + 3)
        self.setTextCursor(cursor)

    def set_render_manager(self, manager):
        """Attach the editor to a RenderManager (highlight regions + images)."""
        self._manager = manager
        if self._custom_layout is not None:
            if manager is not None:
                manager.spansAvailable.connect(self._custom_layout.set_spans)
                manager.structureAvailable.connect(self._custom_layout.set_regions)
        else:
            self._highlighter.set_manager(manager)
        if manager is not None:
            manager.set_base_path(self._base_path)

    # -- document helpers ----------------------------------------------------
    def load_file(self, path: str):
        self.set_base_path(os.path.dirname(os.path.abspath(path)))
        with open(path, "r", encoding="utf-8") as fh:
            self.setPlainText(fh.read())

    def set_base_path(self, path: Optional[str]):
        self._base_path = path
        if self._manager is not None:
            self._manager.set_base_path(path)

    # -- paste ---------------------------------------------------------------

    def set_image_paster(self, callback):
        """Install a host hook for pasted images.

        ``callback(image: QImage) -> str | None`` stores the image and returns
        the path to embed (relative to the note), or ``None`` to decline. The
        editor stays notebook-agnostic; the host owns asset storage.
        """
        self._image_paster = callback

    def insertFromMimeData(self, source):
        if self._image_paster is not None and source.hasImage():
            image = source.imageData()
            path = self._image_paster(image) if image is not None else None
            if path:
                self.textCursor().insertText(f"![]({path})")
                return
        super().insertFromMimeData(source)

    def goToLine(self, line: int):
        """Move the cursor to the start of ``line`` (0-based) and reveal it."""
        block = self.document().findBlockByNumber(line)
        if not block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        self.centerCursor()

    def current_line(self) -> int:
        return self.textCursor().blockNumber()

    def _sync_cursor_line(self):
        line = self.textCursor().blockNumber()
        if self._custom_layout is not None:
            self._custom_layout.set_cursor_block(line)
        else:
            self._highlighter.set_cursor_line(line)

    # -- in-place preview ----------------------------------------------------
    def set_inplace_preview_enabled(self, enabled: bool):
        self._inplace_enabled = bool(enabled)
        if not self._inplace_enabled:
            self._apply_specs([])
        self.viewport().update()

    def inplace_preview_enabled(self) -> bool:
        return self._inplace_enabled

    def set_preview_images(self, images: dict):
        """Receive images decoded off-thread (QImage) from the render pipeline."""
        self._images = dict(images)

    def _image_lookup(self, abs_path: str):
        return self._images.get(abs_path)

    def set_preview_tokens(self, tokens):
        """Build and apply preview specs from a parsed token stream."""
        if not self._inplace_enabled:
            return
        specs = inplace.build_specs(tokens, self._base_path)
        available = max(200, self.viewport().width() - 16)
        specs = inplace.measure_specs(specs, available, self._image_lookup)
        self._apply_specs(specs)

    def _apply_specs(self, specs: List[inplace.PreviewSpec]):
        # Setting a block format fires textChanged; suppress the render loop.
        self._applying = True
        try:
            doc = self.document()
            for bnum in self._spec_blocks:
                block = doc.findBlockByNumber(bnum)
                if not block.isValid():
                    continue
                fmt = block.blockFormat()
                if fmt.topMargin() != 0:
                    fmt.setTopMargin(0)
                    QTextCursor(block).setBlockFormat(fmt)
            self._spec_blocks = set()

            for spec in specs:
                block = doc.findBlockByNumber(spec.block)
                if not block.isValid():
                    continue
                fmt = block.blockFormat()
                fmt.setTopMargin(float(spec.height))
                QTextCursor(block).setBlockFormat(fmt)
                self._spec_blocks.add(spec.block)
        finally:
            self._applying = False
        self._specs = specs
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Width changed: re-measure image previews against the new width.
        if self._inplace_enabled and self._specs:
            available = max(200, self.viewport().width() - 16)
            self._specs = inplace.measure_specs(
                self._specs, available, self._image_lookup
            )

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._inplace_enabled or not self._specs:
            return
        painter = QPainter(self.viewport())
        painter.setClipRect(event.rect())
        doc = self.document()
        width = self.viewport().width()
        event_rect = QRectF(event.rect())
        for spec in self._specs:
            block = doc.findBlockByNumber(spec.block)
            if not block.isValid():
                continue
            block_rect = doc.documentLayout().blockBoundingRect(block)
            margin = int(spec.height)
            # Document coordinates must be translated by the scroll offset;
            # the band is exactly the block's reserved top margin.
            left = block_rect.left() - self.horizontalScrollBar().value()
            top = block_rect.top() - self.verticalScrollBar().value()
            band = QRectF(left, top, width - left - 6, margin)
            if not band.intersects(event_rect):
                continue
            inplace.paint_spec(painter, spec, band)
        painter.end()
