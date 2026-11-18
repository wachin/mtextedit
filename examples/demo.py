"""Stand-alone demo for the mtextedit component.

Run with:
    cd libs/mtextedit
    python examples/demo.py [optional_markdown_file.md]

Use ``QT_QPA_PLATFORM=offscreen python examples/demo.py`` for headless testing.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from mtextedit import (
    MTextEdit,
    OutlineView,
    RenderManager,
    FindReplaceWidget,
)
from mtextedit.linguistic import (
    create_service,
    show_download_manager,
    toolkit_available,
    toolkit_error,
)


SAMPLE = """# mtextedit demo

A **lightweight**, async-first Markdown editor built with PyQt6.

## Features

- Single-pane editor with **in-place preview**
- *Asynchronous* rendering: parsing runs on a worker thread
- Outline derived from the parse tree
- Find / Replace
- Code blocks and tables rendered above their source

### Code

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

### A table

| Feature | VNote | marktux |
|---------|-------|---------|
| Preview | WebEngine | native |
| Parse   | cmark  | markdown-it-py |
| Search  | none   | FTS5 |

> Note: headings, code blocks, lists, quotes and tables all come from the
> single token stream produced by the render worker.
"""


class DemoWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("mtextedit demo")
        self.resize(1100, 750)

        self.manager = RenderManager(self)
        self._service = None
        self._dict_dialog = None
        self._spell_decorator = None

        # Center: a single editor pane with in-place preview.
        self.editor = MTextEdit(self)
        self.editor.set_render_manager(self.manager)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        self.find_replace = FindReplaceWidget(self.editor)
        self.find_replace.hide()
        cl.addWidget(self.find_replace)
        cl.addWidget(self.editor)
        self.setCentralWidget(center)

        # Right dock: outline.
        self.outline = OutlineView(self)
        dock = QDockWidget("Outline", self)
        dock.setWidget(self.outline)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        # Wiring.
        self.editor.renderRequested.connect(self.manager.request)
        self.manager.headingsAvailable.connect(self.outline.set_headings)
        self.manager.previewImagesAvailable.connect(self.editor.set_preview_images)
        self.manager.tokensAvailable.connect(self.editor.set_preview_tokens)
        self.outline.headingActivated.connect(self.editor.goToLine)

        self._build_menu()

        self.editor.setPlainText(SAMPLE)
        self.manager.force_render(SAMPLE)

    def _build_menu(self):
        menu = self.menuBar().addMenu("File")
        open_act = menu.addAction("Open...")
        open_act.triggered.connect(self._open)
        menu.addAction("Quit").triggered.connect(self.close)

        edit = self.menuBar().addMenu("Edit")
        find_act = edit.addAction("Find / Replace")
        find_act.setShortcut("Ctrl+F")
        find_act.triggered.connect(self._toggle_find)

        view = self.menuBar().addMenu("View")
        inplace_act = view.addAction("In-place Preview")
        inplace_act.setCheckable(True)
        inplace_act.setChecked(True)
        inplace_act.triggered.connect(self.editor.set_inplace_preview_enabled)

        tools = self.menuBar().addMenu("Tools")
        tools.addAction("Dictionary Download Manager…").triggered.connect(
            self._open_dict_manager
        )
        self.spell_act = tools.addAction("Spell Check")
        self.spell_act.setCheckable(True)
        self.spell_act.triggered.connect(self._toggle_spellcheck)

    # -- linguistic tools ---------------------------------------------------
    def _ensure_service(self):
        if self._service is None:
            self._service = create_service(namespace="marktux")
        return self._service

    def _open_dict_manager(self):
        if not toolkit_available():
            QMessageBox.information(
                self, "Dictionary Manager",
                f"The linguistic toolkit is unavailable:\n{toolkit_error()}",
            )
            return
        try:
            service = self._ensure_service()
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "Dictionary Manager", str(error))
            return
        if self._dict_dialog is None:
            self._dict_dialog = show_download_manager(
                self, service, namespace="marktux"
            )
        if self._dict_dialog is None:
            QMessageBox.information(
                self, "Dictionary Manager",
                "Could not open the dictionary download manager.",
            )
        else:
            self._dict_dialog.show()
            self._dict_dialog.raise_()

    def _toggle_spellcheck(self, checked: bool):
        if not toolkit_available():
            self.spell_act.setChecked(False)
            QMessageBox.information(
                self, "Spell Check",
                f"The linguistic toolkit is unavailable:\n{toolkit_error()}",
            )
            return
        try:
            from pyqt6_linguistic_tools.qt import LinguisticTextEditDecorator  # type: ignore
            service = self._ensure_service()
        except Exception as error:  # noqa: BLE001
            self.spell_act.setChecked(False)
            QMessageBox.warning(self, "Spell Check", str(error))
            return
        if checked:
            if self._spell_decorator is None:
                self._spell_decorator = LinguisticTextEditDecorator(
                    self.editor, service
                )
            self._spell_decorator.set_spellcheck_enabled(True)
        elif self._spell_decorator is not None:
            self._spell_decorator.set_spellcheck_enabled(False)

    def closeEvent(self, event):
        if self._spell_decorator is not None:
            try:
                self._spell_decorator.set_spellcheck_enabled(False)
                self._spell_decorator.detach()
            except Exception:
                pass
            self._spell_decorator = None
        if self._service is not None:
            try:
                self._service.close()
            except Exception:
                pass
            self._service = None
        super().closeEvent(event)

    def _toggle_find(self):
        self.find_replace.setVisible(not self.find_replace.isVisible())
        if self.find_replace.isVisible():
            self.find_replace.find_edit.setFocus()

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Markdown", "", "Markdown (*.md *.markdown);;All (*)"
        )
        if path:
            self.editor.load_file(path)
            self.manager.force_render(self.editor.toPlainText())


def main():
    app = QApplication(sys.argv)
    win = DemoWindow()
    win.show()
    if len(sys.argv) > 1:
        win.editor.load_file(sys.argv[1])
        win.manager.force_render(win.editor.toPlainText())
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
