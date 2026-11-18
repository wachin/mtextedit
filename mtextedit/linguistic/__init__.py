"""Integration with ``pyqt6-linguistic-tools`` (spell-check + dictionary downloads).

The toolkit is vendored at ``libs/mtextedit/libs/pyqt6-linguistic-tools`` and
brings its own engines (``spylls`` for spelling, ``pythes`` for the thesaurus).
It also ships a **verified dictionary download manager** -- the feature that
makes spelling/thesaurus work on Windows and macOS, where the Linux-style
system Hunspell/MyThes packages are not available.

This module is intentionally *lazy*: importing ``mtextedit`` must not pull in the
heavy engines. Paths are registered at import time (cheap); the toolkit itself
is imported only when a service or the download manager is actually requested.
If the toolkit is absent, every call degrades gracefully.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Locate and bootstrap the vendored toolkit
# ---------------------------------------------------------------------------

_TOOLKIT_ROOT: Optional[Path] = None
_TOOLKIT_LOADED = False
_TOOLKIT_ERROR: Optional[Exception] = None
_create_service = None
_load_catalog = None


def _find_toolkit_root() -> Optional[Path]:
    env = os.environ.get("MARKTUX_LINGUISTIC_TOOLKIT")
    candidates = []
    if env:
        candidates.append(Path(env))
    # .../libs/mtextedit/mtextedit/linguistic/__init__.py
    # parents[2] == .../libs/mtextedit ; the toolkit is under its libs/.
    here = Path(__file__).resolve()
    if len(here.parents) > 2:
        candidates.append(here.parents[2] / "libs" / "pyqt6-linguistic-tools")
    for candidate in candidates:
        if (candidate / "src" / "pyqt6_linguistic_tools").is_dir():
            return candidate
    return None


def _register_paths(root: Path) -> None:
    """Make the toolkit package and its vendored engines importable."""
    for relative in ("src", "libs/spylls", "libs/pythes"):
        path = str(root / relative)
        if path not in sys.path:
            sys.path.insert(0, path)


_TOOLKIT_ROOT = _find_toolkit_root()
if _TOOLKIT_ROOT is not None:
    _register_paths(_TOOLKIT_ROOT)


def _load_toolkit() -> bool:
    """Import the toolkit on first use. Returns True when available."""
    global _TOOLKIT_LOADED, _TOOLKIT_ERROR, _create_service, _load_catalog
    if _TOOLKIT_LOADED:
        return True
    if _TOOLKIT_ERROR is not None:
        return False
    if _TOOLKIT_ROOT is None:
        _TOOLKIT_ERROR = RuntimeError(
            "pyqt6-linguistic-tools was not found; set MARKTUX_LINGUISTIC_TOOLKIT"
        )
        return False
    try:
        from pyqt6_linguistic_tools import (  # type: ignore
            create_service as _cs,
            load_bundled_dictionary_catalog as _lc,
        )
    except Exception as error:  # pragma: no cover - depends on install
        _TOOLKIT_ERROR = error
        return False
    _create_service = _cs
    _load_catalog = _lc
    _TOOLKIT_LOADED = True
    return True


def toolkit_available() -> bool:
    return _load_toolkit()


def toolkit_error() -> Optional[Exception]:
    _load_toolkit()
    return _TOOLKIT_ERROR


# ---------------------------------------------------------------------------
# Service / catalog factories
# ---------------------------------------------------------------------------

def create_service(
    namespace: str = "marktux",
    *,
    language: Optional[str] = None,
    dictionary_root: Optional[str] = None,
) -> Any:
    """Create a ``LinguisticService`` with managed/user providers.

    ``namespace`` isolates marktux's dictionaries from other applications that
    also use the toolkit. Pass ``dictionary_root`` to share one suite-wide
    managed/user/personal directory instead.
    """
    if not _load_toolkit():
        raise RuntimeError(f"linguistic toolkit unavailable: {_TOOLKIT_ERROR}")
    return _create_service(
        namespace=namespace,
        language=language,
        dictionary_root=dictionary_root,
    )


def load_catalog() -> Any:
    """Load the bundled 57-entry verified dictionary catalog (or None)."""
    if not _load_toolkit():
        return None
    return _load_catalog()


def open_download_manager(
    parent: Any = None,
    service: Any = None,
    *,
    namespace: str = "marktux",
) -> Any:
    """Create (but do not show) a ``DictionaryDownloadManagerDialog``.

    The dialog downloads, verifies (size + SHA-256), validates and installs
    spelling/thesaurus bundles into the managed provider off the GUI thread.
    Returns ``None`` when the toolkit is unavailable.
    """
    if not _load_toolkit():
        return None
    from pyqt6_linguistic_tools.qt import (  # type: ignore
        DictionaryDownloadManagerDialog,
    )

    if service is None:
        service = create_service(namespace=namespace)
    return DictionaryDownloadManagerDialog(
        service, catalog=load_catalog(), parent=parent
    )


def show_download_manager(
    parent: Any = None,
    service: Any = None,
    *,
    namespace: str = "marktux",
) -> Any:
    """Create and show a modeless download-manager dialog; returns it."""
    dialog = open_download_manager(parent, service, namespace=namespace)
    if dialog is not None:
        dialog.show()
    return dialog


# ---------------------------------------------------------------------------
# Spell-check facade
# ---------------------------------------------------------------------------

class Spellchecker:
    """Minimal spell-check facade backed by a ``LinguisticService``."""

    def __init__(self, service: Any = None, language: str = "en_US"):
        self.language = language
        self._service = service
        if self._service is None and _load_toolkit():
            try:
                self._service = create_service(language=language)
            except Exception:
                self._service = None

    @property
    def available(self) -> bool:
        return self._service is not None

    def check(self, word: str) -> bool:
        if self._service is None:
            return True
        try:
            return bool(self._service.check_word(word))
        except Exception:
            return True

    def suggest(self, word: str) -> list[str]:
        if self._service is None:
            return []
        try:
            return list(self._service.suggestions(word))
        except Exception:
            return []

    def add_to_user(self, word: str) -> None:
        if self._service is None:
            return
        try:
            self._service.add_to_personal_dictionary(word)
        except Exception:
            pass


__all__ = [
    "Spellchecker",
    "create_service",
    "load_catalog",
    "open_download_manager",
    "show_download_manager",
    "toolkit_available",
    "toolkit_error",
]
