"""Loader for VNote-style ``.theme`` files.

VNote's editor theme is a JSON document with ``markdown-syntax-styles``
(``H1``..``H6``, ``STRONG``, ``EMPH``, ``CODE``, ``LINK``, ``TABLE``,
``TABLEBORDER``, ...) and ``markdown-editor-styles`` (``Text``, ``Preview``,
``ConcealedText``, ...). This module parses that *format* so a user can point
the editor at a theme they already have.

Only the format is implemented; no VNote code or theme data is copied. See
``DESIGN.md`` D16 and the repository notices for attribution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class ThemeError(ValueError):
    """Raised when a theme file cannot be read or has no usable styles."""


@dataclass(frozen=True)
class Format:
    """One resolved style. ``None`` means 'inherit / not specified'."""

    color: str | None = None
    background: str | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike_through: bool = False
    font_size: int | None = None
    font_family: str | None = None


def _format(value) -> Format:
    if not isinstance(value, dict):
        return Format()
    size = value.get("font-size")
    try:
        size = int(size) if size is not None else None
    except (TypeError, ValueError):
        size = None
    return Format(
        color=value.get("text-color"),
        background=value.get("background-color"),
        bold=bool(value.get("bold", False)),
        italic=bool(value.get("italic", False)),
        underline=bool(value.get("underline", False)),
        strike_through=bool(value.get("strike-through", False)),
        font_size=size,
        font_family=value.get("font-family"),
    )


class Theme:
    """A parsed theme: named syntax and editor styles."""

    def __init__(self, name: str, syntax: dict[str, Format],
                 editor: dict[str, Format]):
        self.name = name
        self._syntax = syntax
        self._editor = editor

    def __repr__(self) -> str:
        return f"<Theme {self.name} ({len(self._syntax)} syntax, {len(self._editor)} editor)>"

    @property
    def syntax_names(self) -> list[str]:
        return sorted(self._syntax)

    @property
    def editor_names(self) -> list[str]:
        return sorted(self._editor)

    def syntax_style(self, name: str) -> Format:
        """Style for a VNote syntax key; ``Format()`` when not defined."""
        return self._syntax.get(name, Format())

    def editor_style(self, name: str) -> Format:
        return self._editor.get(name, Format())

    @classmethod
    def from_dict(cls, payload: dict) -> Theme:
        if not isinstance(payload, dict):
            raise ThemeError("theme must be a JSON object")
        metadata = payload.get("metadata") or {}
        name = metadata.get("name") or "unnamed"
        syntax_payload = payload.get("markdown-syntax-styles") or {}
        editor_payload = payload.get("markdown-editor-styles") or {}
        if not isinstance(syntax_payload, dict) or not isinstance(editor_payload, dict):
            raise ThemeError("theme style sections must be JSON objects")
        if not syntax_payload and not editor_payload:
            raise ThemeError("theme has no markdown styles")
        syntax = {key: _format(value) for key, value in syntax_payload.items()
                  if not key.startswith("//")}
        editor = {key: _format(value) for key, value in editor_payload.items()
                  if not key.startswith("//")}
        return cls(str(name), syntax, editor)

    @classmethod
    def load(cls, path: str | Path) -> Theme:
        """Load a VNote ``.theme`` file from disk."""
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except OSError as error:
            raise ThemeError(f"cannot read theme: {error}") from error
        except ValueError as error:
            raise ThemeError(f"invalid theme JSON: {error}") from error
        return cls.from_dict(payload)


_THEMES_DIR = Path(__file__).with_name("themes")


def default_theme_path() -> Path:
    """Path of the bundled VNote ``Native`` theme."""
    return _THEMES_DIR / "native.theme"


@lru_cache(maxsize=1)
def load_default() -> Theme:
    """Load (once) and return the bundled theme."""
    return Theme.load(default_theme_path())
