"""Markdown preview widget.

The default preview is a Chromium-free ``QTextEdit`` whose content is built
from the parsed token stream by :func:`mtextedit._markdown.build_document`.
This is the key divergence from VNote, which reloaded the whole document into a
``QWebEngineView`` on every keystroke. Because the expensive parse already ran
on a worker thread, rebuilding the ``QTextDocument`` here is cheap and scales
with visible structure rather than forcing a full Chromium re-layout.

If ``PyQt6.QtWebEngineWidgets`` is importable, a faithful HTML preview with
Pygments-highlighted code is available via :meth:`set_webengine_enabled`.
"""

from __future__ import annotations

from typing import Any, List, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTextEdit

try:  # Optional, heavier path.
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # type: ignore
    _HAS_WEBENGINE = True
except Exception:  # pragma: no cover - depends on install
    _HAS_WEBENGINE = False


class PreviewWidget(QTextEdit):
    # Forwarded navigation requests (e.g. outline click inside a future web UI).
    linkClicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._web: Optional["QWebEngineView"] = None
        self._use_webengine = False
        self._html = ""

    # -- preview backend selection ------------------------------------------
    def set_webengine_enabled(self, enabled: bool) -> bool:
        """Enable the QWebEngineView HTML preview if available. Returns success."""
        if enabled and not _HAS_WEBENGINE:
            return False
        self._use_webengine = bool(enabled) and _HAS_WEBENGINE
        if self._use_webengine and self._web is None:
            self._web = QWebEngineView(self)
            self.setViewportMargins(0, 0, 0, 0)
        return self._use_webengine

    @property
    def using_webengine(self) -> bool:
        return self._use_webengine

    # -- update from the render pipeline ------------------------------------
    def on_rendered(self, rev: int, html: str, headings: List[Any],
                    tokens: List[Any], regions: List[Any]):
        self._html = html
        if self._use_webengine and self._web is not None:
            self._web.setHtml(html)
            return
        # Native path: rebuild the QTextDocument from tokens (GUI thread).
        from .._markdown import build_document
        build_document(tokens, self.document())
