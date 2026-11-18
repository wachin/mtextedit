"""Document outline derived from the Markdown AST.

The outline is built from the same heading list the renderer produces
(:func:`mtextedit._markdown.extract_headings`) -- exactly VNote's approach of
deriving the outline from the parse tree rather than regex-scanning. Clicking a
heading navigates the editor via the ``headingActivated`` signal (line number).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtWidgets import QTreeView


class _OutlineNode:
    def __init__(self, level: int, text: str, line: int,
                 parent: Optional["_OutlineNode"] = None):
        self.level = level
        self.text = text
        self.line = line
        self.parent = parent
        self.children: List["_OutlineNode"] = []


class OutlineModel(QAbstractItemModel):
    LineRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = _OutlineNode(0, "", -1)
        self._headings: List[Dict[str, Any]] = []

    def set_headings(self, headings: List[Dict[str, Any]]):
        self.beginResetModel()
        self._headings = headings
        self._root = _OutlineNode(0, "", -1)
        stack = [(0, self._root)]
        for h in headings:
            level = h.get("level", 1)
            node = _OutlineNode(level, h.get("text", ""), h.get("line", 0),
                                parent=None)
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else self._root
            node.parent = parent
            parent.children.append(node)
            stack.append((level, node))
        self.endResetModel()

    # -- QAbstractItemModel --------------------------------------------------
    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = parent.internalPointer() if parent.isValid() else self._root
        if row < 0 or row >= len(parent_node.children):
            return QModelIndex()
        return self.createIndex(row, column, parent_node.children[row])

    def parent(self, index):  # noqa: A003
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        if node.parent is None or node.parent is self._root:
            return QModelIndex()
        grandparent = node.parent.parent or self._root
        try:
            row = grandparent.children.index(node.parent)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, node.parent)

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0
        node = parent.internalPointer() if parent.isValid() else self._root
        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        return 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            return node.text or f"({node.level}-level heading)"
        if role == OutlineModel.LineRole:
            return node.line
        return None

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole and section == 0:
            return "Outline"
        return None


class OutlineView(QTreeView):
    headingActivated = pyqtSignal(int)  # source line number

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = OutlineModel(self)
        self.setModel(self._model)
        self.setHeaderHidden(True)
        self.clicked.connect(self._on_clicked)

    def set_headings(self, headings: List[Dict[str, Any]]):
        self._model.set_headings(headings)
        self.expandAll()

    def _on_clicked(self, index: QModelIndex):
        line = self._model.data(index, OutlineModel.LineRole)
        if isinstance(line, int) and line >= 0:
            self.headingActivated.emit(line)
