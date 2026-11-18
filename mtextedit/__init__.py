"""mtextedit -- a modular, async-first Markdown editor for PyQt6.

This package is the reusable Markdown editing component. It is deliberately
independent of any notebook / file manager so it can be embedded in other PyQt6
applications (e.g. as the fourth panel of an e-Sword-like tool).

Public surface
--------------
* :class:`MTextEdit` -- the editor surface.
* :class:`MarkdownHighlighter` -- structural + inline highlighting.
* :class:`RenderManager` / :class:`PreviewWidget` -- the async render pipeline
  and the Chromium-free preview.
* :class:`OutlineView` / :class:`OutlineModel` -- AST-derived outline.
* :class:`FindReplaceWidget` -- in-file find & replace.
"""

from .editor import MTextEdit
from .highlighter import MarkdownHighlighter
from .outline import OutlineModel, OutlineView
from .find_replace import FindReplaceWidget
from .renderer import RenderManager, RenderWorker, PreviewWidget

__version__ = "0.1.0"

__all__ = [
    "MTextEdit",
    "MarkdownHighlighter",
    "OutlineModel",
    "OutlineView",
    "FindReplaceWidget",
    "RenderManager",
    "RenderWorker",
    "PreviewWidget",
    "__version__",
]
