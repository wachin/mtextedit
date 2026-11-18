"""Find / Replace widget for the editor.

Operates on any ``QPlainTextEdit`` (or ``QTextEdit``). Supports case-sensitive,
whole-word and regular-expression matching, incremental highlighting of all
matches, and replace / replace-all. This is the in-file equivalent of VNote's
``FindAndReplaceWidget2``; notebook-wide search lives in ``marktux.core``.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import (
    QColor,
    QTextCursor,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class FindReplaceWidget(QWidget):
    def __init__(self, target: QWidget, parent=None):
        # ``target`` is the editor (QPlainTextEdit / QTextEdit).
        super().__init__(parent)
        self.editor = target
        self._last_cursor: Optional[QTextCursor] = None
        self._setup_ui()

    # -- UI -----------------------------------------------------------------
    def _setup_ui(self):
        root = QVBoxLayout(self)
        row1 = QHBoxLayout()
        self.find_edit = QLineEdit(); self.find_edit.setPlaceholderText("Find")
        self.replace_edit = QLineEdit(); self.replace_edit.setPlaceholderText("Replace")
        self.status = QLabel("")
        row1.addWidget(QLabel("Find:"))
        row1.addWidget(self.find_edit)
        row1.addWidget(QLabel("Replace:"))
        row1.addWidget(self.replace_edit)
        row1.addWidget(self.status)

        row2 = QHBoxLayout()
        self.case_cb = QCheckBox("Case")
        self.word_cb = QCheckBox("Whole word")
        self.regex_cb = QCheckBox("Regex")
        self.inc_cb = QCheckBox("Incremental")
        self.inc_cb.setChecked(True)
        btn_next = QPushButton("Next"); btn_prev = QPushButton("Prev")
        btn_rep = QPushButton("Replace"); btn_repa = QPushButton("Replace All")
        btn_close = QPushButton("Close")
        for b, slot in (
            (btn_next, self.find_next),
            (btn_prev, self.find_prev),
            (btn_rep, self.replace),
            (btn_repa, self.replace_all),
            (btn_close, self.hide),
        ):
            b.clicked.connect(slot)
        row2.addWidget(self.case_cb); row2.addWidget(self.word_cb)
        row2.addWidget(self.regex_cb); row2.addWidget(self.inc_cb)
        row2.addStretch(1)
        row2.addWidget(btn_prev); row2.addWidget(btn_next)
        row2.addWidget(btn_rep); row2.addWidget(btn_repa)
        row2.addWidget(btn_close)

        root.addLayout(row1); root.addLayout(row2)

        self.find_edit.textChanged.connect(self._on_find_text_changed)
        self.find_edit.returnPressed.connect(self.find_next)
        self.replace_edit.returnPressed.connect(self.replace)

    # -- match helpers ------------------------------------------------------
    def _build_regex(self) -> Optional[QRegularExpression]:
        text = self.find_edit.text()
        if not text:
            return None
        if self.regex_cb.isChecked():
            rx = QRegularExpression(text)
            if self.case_cb.isChecked():
                rx.setPatternOptions(rx.patternOptions()
                                     | QRegularExpression.PatternOption.CaseInsensitiveOption)
        else:
            pat = QRegularExpression.escape(text)
            if self.word_cb.isChecked():
                pat = r"\b" + pat + r"\b"
            rx = QRegularExpression(pat)
            if not self.case_cb.isChecked():
                rx.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
        return rx

    def _find_flags(self):
        flags = QTextDocument.FindFlag(0)
        if self.case_cb.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def _search_from(self, cursor: QTextCursor, forward: bool,
                    rx: QRegularExpression) -> QTextCursor:
        doc = self.editor.document()
        flags = self._find_flags()
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward
        found = doc.find(rx, cursor, flags)
        if found.isNull():
            # Wrap around.
            if forward:
                found = doc.find(rx, QTextCursor(doc), flags)
            else:
                end = QTextCursor(doc); end.movePosition(QTextCursor.MoveOperation.End)
                found = doc.find(rx, end, flags)
        return found

    # -- public actions -----------------------------------------------------
    def find_next(self):
        rx = self._build_regex()
        if rx is None:
            return
        cur = self.editor.textCursor()
        if cur.hasSelection():
            cur.setPosition(cur.position())
        found = self._search_from(cur, True, rx)
        if found.isNull():
            self.status.setText("No match")
            return
        self.editor.setTextCursor(found)
        self._last_cursor = found
        self._highlight_all(rx)
        self.status.setText("")

    def find_prev(self):
        rx = self._build_regex()
        if rx is None:
            return
        cur = self.editor.textCursor()
        found = self._search_from(cur, False, rx)
        if found.isNull():
            self.status.setText("No match")
            return
        self.editor.setTextCursor(found)
        self._last_cursor = found
        self._highlight_all(rx)

    def replace(self):
        rx = self._build_regex()
        if rx is None:
            return
        cur = self.editor.textCursor()
        if not cur.hasSelection():
            self.find_next()
            cur = self.editor.textCursor()
        if cur.hasSelection():
            cur.insertText(self.replace_edit.text())
            self.find_next()

    def replace_all(self):
        rx = self._build_regex()
        if rx is None:
            return
        doc = self.editor.document()
        count = 0
        # Iterate from the start, replacing without disturbing later matches.
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        while True:
            found = doc.find(rx, edit, self._find_flags())
            if found.isNull():
                break
            found.insertText(self.replace_edit.text())
            count += 1
        edit.endEditBlock()
        self.status.setText(f"Replaced {count}")

    # -- highlighting -------------------------------------------------------
    def _highlight_all(self, rx: QRegularExpression):
        doc = self.editor.document()
        color = QColor(255, 235, 120, 90)
        extras = []
        cur = QTextCursor(doc)
        while True:
            found = doc.find(rx, cur, self._find_flags())
            if found.isNull():
                break
            es = QTextEdit.ExtraSelection()
            es.cursor = found
            es.format.setBackground(color)
            extras.append(es)
            cur = found
            if cur.atEnd():
                break
        self.editor.setExtraSelections(extras)

    def _on_find_text_changed(self, _text):
        if self.inc_cb.isChecked():
            self.find_next()
        else:
            self._highlight_all(self._build_regex())
