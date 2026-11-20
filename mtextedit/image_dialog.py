"""Small image-insertion dialog: alternative text and title.

The dialog is host-agnostic: the host still stores the image and returns the
note-relative path. The editor only uses it to collect Markdown metadata before
inserting ``![alt](path "title")``.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


def _escape_alt(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def _escape_title(text: str) -> str:
    return text.replace('"', '\\"')


def image_markdown(path: str, alt: str = "", title: str = "") -> str:
    target = path if " " not in path else f"<{path}>"
    suffix = f' "{_escape_title(title)}"' if title else ""
    return f"![{_escape_alt(alt)}]({target}{suffix})"


class ImageInsertDialog(QDialog):
    def __init__(self, image: QImage, suggested_alt: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Image")
        self.setAccessibleName("Insert image")
        self._alt = QLineEdit(suggested_alt)
        self._alt.setAccessibleName("Alternative text")
        self._title = QLineEdit()
        self._title.setAccessibleName("Title")

        preview = QLabel()
        preview.setAccessibleName("Image preview")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap.fromImage(image)
        if not pixmap.isNull():
            preview.setPixmap(pixmap.scaled(
                320, 200, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

        form = QFormLayout()
        form.addRow("Preview", preview)
        form.addRow("Alternative text", self._alt)
        form.addRow("Title", self._title)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self._alt.text(), self._title.text()

    def markdown(self, path: str) -> str:
        alt, title = self.values()
        return image_markdown(path, alt, title)
