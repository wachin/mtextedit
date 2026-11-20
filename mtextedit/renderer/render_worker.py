"""Worker that parses Markdown off the GUI thread.

A ``RenderWorker`` is a ``QRunnable`` so it runs on ``QThreadPool``. It parses
the source into a token stream and derives everything the UI needs in *one*
pass: the HTML string, the outline headings, the editor block regions, the token
stream for the in-place preview, and the **decoded images** for that preview.

Images are decoded here into ``QImage`` (thread-safe, no GUI dependency); the
GUI thread only converts them to ``QPixmap``. This keeps large local images from
stalling typing (design decision D13).

Cancellation is cooperative but *prioritised*: the manager bumps a generation
token before starting a newer worker. This worker checks the token between its
phases and abandons the remaining work if it has been superseded -- so a slow
parse or image decode of a stale revision never reaches the GUI.
"""

from __future__ import annotations

from typing import Any, List, Optional, Set, Tuple

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable
from PyQt6.QtGui import QImage


class _RenderSignals(QObject):
    # rev, html, headings, tokens, regions, new_images, image_requests
    done = pyqtSignal(int, str, list, list, list, dict, list)


class RenderWorker(QRunnable):
    def __init__(
        self,
        revision: int,
        source: str,
        md,
        gen_token: List[int],
        base_path: Optional[str] = None,
        cached_images: Optional[Set[Tuple[str, float]]] = None,
    ):
        super().__init__()
        self.revision = revision
        self.source = source
        self.md = md
        self.gen_token = gen_token  # mutable one-element list owned by the manager
        self.base_path = base_path
        self.cached_images = cached_images or set()
        self.signals = _RenderSignals()

    def _stale(self) -> bool:
        return self.gen_token[0] != self.revision

    def run(self):
        # Cheap first phase: parse + headings/regions (outline shows immediately).
        tokens = self.md.parse(self.source)

        from .._markdown import extract_headings, collect_block_regions
        from ..highlight import annotate_code_runs
        headings = extract_headings(tokens)
        regions = collect_block_regions(tokens)
        # Pygments runs for fenced code stay on this thread; the token stream
        # carries them to the GUI as plain strings (D12).
        annotate_code_runs(tokens)

        # Priority-cancel point: a newer keystroke may have arrived.
        if self._stale():
            return

        from .._markdown import render_html
        html = render_html(self.md, tokens)

        if self._stale():
            return

        # Decode the preview images off the GUI thread (D13). Images already in
        # the manager's cache are skipped; the GUI thread resolves those.
        from ..inplace import image_requests
        requests = image_requests(tokens, self.base_path)
        new_images = {}
        for path, mtime in requests:
            if (path, mtime) in self.cached_images:
                continue
            if self._stale():
                return
            image = QImage(path)
            if not image.isNull():
                new_images[(path, mtime)] = image

        if self._stale():
            return

        # tokens/images are plain Python/Qt value objects; safe to pass by
        # reference across the queued signal.
        self.signals.done.emit(
            self.revision, html, headings, tokens, regions, new_images, requests
        )
