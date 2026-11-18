"""Render manager: coalescing, debouncing and priority cancellation.

This is the architectural heart of marktux's "fast by design" claim. VNote's
preview re-parsed the *entire* document and called ``setHtml`` on every
debounce -- O(N) per keystroke. Here:

* ``request`` is debounced (default 120 ms) so a burst of typing collapses into
  a single render.
* A monotonic generation token means only the *newest* request ever produces UI
  output; in-flight workers for superseded revisions abandon their work.
* Parsing and image decoding happen on ``QThreadPool``, never the GUI thread.
* Results are fanned out via separate signals: ``rendered`` (optional full
  preview), ``headingsAvailable`` (outline), ``structureAvailable`` (highlighter),
  ``tokensAvailable`` (in-place preview) and ``previewImagesAvailable`` (decoded
  images for the in-place preview).

The image cache is an LRU keyed by ``(path, mtime)`` holding ``QImage`` objects.
It is owned by the manager (GUI thread); workers receive a snapshot of its keys
so they only decode images that are not already cached (D13).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import List, Optional, Set, Tuple

from PyQt6.QtCore import pyqtSignal, QObject, QThreadPool, QTimer

from .render_worker import RenderWorker
from .._markdown import build_md

_IMAGE_CACHE_MAX = 32


def _validate_cache_size(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("image_cache_max must be an integer")
    if value < 1:
        raise ValueError("image_cache_max must be >= 1")
    return value


class RenderManager(QObject):
    rendered = pyqtSignal(int, str, list, list, list)  # rev, html, headings, tokens, regions
    headingsAvailable = pyqtSignal(list)               # headings
    structureAvailable = pyqtSignal(list)              # regions
    tokensAvailable = pyqtSignal(list)                 # parsed token stream (in-place preview)
    previewImagesAvailable = pyqtSignal(dict)          # {abs_path: QImage}

    def __init__(self, parent: QObject = None, render_delay_ms: int = 120,
                 max_threads: int = 2, image_cache_max: int = _IMAGE_CACHE_MAX):
        super().__init__(parent)
        self._md = build_md()
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max_threads)
        self._gen: List[int] = [0]
        self._pending_rev = 0
        self._latest_source = ""
        self._base_path: Optional[str] = None
        # LRU of decoded images: (path, mtime) -> QImage, bounded.
        self._image_cache_max = _validate_cache_size(image_cache_max)
        self._image_cache: "OrderedDict[Tuple[str, float], object]" = OrderedDict()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(render_delay_ms)
        self._timer.timeout.connect(self._dispatch)

    def set_base_path(self, path: Optional[str]):
        """Set the document base directory used to resolve relative images."""
        self._base_path = path

    def image_cache_max(self) -> int:
        """Current upper bound on retained decoded images."""
        return self._image_cache_max

    def set_image_cache_max(self, value: int):
        """Change the image cache bound at runtime and evict immediately."""
        self._image_cache_max = _validate_cache_size(value)
        self._evict_images()

    def _evict_images(self):
        while len(self._image_cache) > self._image_cache_max:
            self._image_cache.popitem(last=False)

    def request(self, source: str, delay_ms: int | None = None):
        """Schedule a render for ``source`` (deprecated ``delay_ms`` overrides)."""
        self._gen[0] += 1                 # invalidate any in-flight worker
        self._latest_source = source
        self._pending_rev = self._gen[0]
        if delay_ms is not None:
            self._timer.setInterval(delay_ms)
        self._timer.start()

    def _dispatch(self):
        worker = RenderWorker(
            self._pending_rev,
            self._latest_source,
            self._md,
            self._gen,
            base_path=self._base_path,
            cached_images=set(self._image_cache.keys()),
        )
        worker.signals.done.connect(self._on_done)
        self._pool.start(worker)

    def _on_done(self, rev, html, headings, tokens, regions, new_images, requests):
        if rev != self._gen[0]:           # superseded by a newer request
            return

        # Merge newly decoded images into the LRU.
        for key, image in new_images.items():
            self._image_cache[key] = image
            self._image_cache.move_to_end(key)

        # Resolve every image this render asked for BEFORE eviction, so a
        # document with more images than the cache can hold still gets all of
        # them for this render. Eviction only governs retention for next time.
        resolved = {}
        for path, mtime in requests:
            key = (path, mtime)
            image = self._image_cache.get(key)
            if image is not None:
                resolved[path] = image
                self._image_cache.move_to_end(key)  # LRU touch

        # Evict least-recently-used entries beyond the bound.
        self._evict_images()

        self.previewImagesAvailable.emit(resolved)
        self.headingsAvailable.emit(headings)
        self.structureAvailable.emit(regions)
        self.tokensAvailable.emit(tokens)
        self.rendered.emit(rev, html, headings, tokens, regions)

    def force_render(self, source: str):
        """Render immediately, bypassing the debounce (e.g. on file open)."""
        self._timer.stop()
        self.request(source, delay_ms=0)
