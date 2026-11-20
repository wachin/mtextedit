"""Markdown syntax highlighter for the editor.

The highlighter styles two layers:

1. *Block structure* (headings, code fences, blockquotes, lists, rules) comes
   from the async render pipeline. The render manager emits ``structureAvailable``
   with line-range regions produced by
   :func:`mtextedit._markdown.collect_block_regions`; the highlighter caches
   them and re-highlights. This keeps the Markdown parse *off* the GUI thread
   (VNote did the same parse on a worker for highlighting).
2. *Inline* emphasis (``**bold**``, ``*italic*``, `` `code` ``, ``[link](u)``)
   is computed per-block with lightweight regex on the GUI thread -- cheap
   because it only touches the visible block.
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QRegularExpression, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument,
                 manager: Optional["object"] = None):
        super().__init__(document)
        self._regions: List[dict] = []
        self._setup_formats()
        self._setup_inline_patterns()
        if manager is not None:
            self.set_manager(manager)

    # -- configuration -------------------------------------------------------
    def _setup_formats(self):
        self.f_heading = []
        colors = ["#1a5fb4", "#1a5fb4", "#613583", "#613583",
                  "#e01b24", "#e01b24"]
        for lvl, color in enumerate(colors, start=1):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            f.setFontWeight(QFont.Weight.Bold)
            if lvl <= 2:
                f.setFontPointSize(11 + (3 - lvl))
            self.f_heading.append(f)

        self.f_code = QTextCharFormat()
        self.f_code.setForeground(QColor("#8a4b00"))
        self.f_code.setFontFamily("monospace")

        self.f_quote = QTextCharFormat()
        self.f_quote.setForeground(QColor("#5f6368"))
        self.f_quote.setFontItalic(True)

        self.f_list = QTextCharFormat()
        self.f_list.setForeground(QColor("#0a8043"))

        self.f_hr = QTextCharFormat()
        self.f_hr.setForeground(QColor("#b0b3b8"))

    def _setup_inline_patterns(self):
        self._inline_patterns = [
            (QRegularExpression(r"`[^`\n]+`"), self.f_code),
            (QRegularExpression(r"\*\*[^*\n]+\*\*"), self.f_heading[0]),
            (QRegularExpression(r"__[^_\n]+__"), self.f_heading[0]),
            (QRegularExpression(r"(?<!\*)\*[^*\n]+\*(?!\*)"), self.f_quote),
            (QRegularExpression(r"(?<!_)_[^_\n]+_(?!_)"), self.f_quote),
            (QRegularExpression(r"\[[^\]\n]+\]\([^)\n]+\)"), self.f_list),
        ]

    # -- manager wiring ------------------------------------------------------
    def set_manager(self, manager):
        """Connect to a RenderManager to receive block regions."""
        manager.structureAvailable.connect(self.set_regions)

    def set_regions(self, regions: List[dict]):
        self._regions = regions or []
        self.rehighlight()

    # -- highlighting --------------------------------------------------------
    def highlightBlock(self, text: str) -> None:
        line = self.currentBlock().blockNumber()

        # Inline emphasis (cheap, per visible block).
        for pattern, fmt in self._inline_patterns:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        # Block structure from the async pipeline.
        for r in self._regions:
            if r["start"] <= line <= r["end"]:
                kind = r["kind"]
                if kind == "heading":
                    lvl = r.get("level", 1)
                    fmt = self.f_heading[min(max(lvl, 1), 6) - 1]
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
