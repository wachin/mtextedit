"""Tests for content-proportional table columns in the in-place preview.

Run from ``libs/mtextedit``::

    QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QFontMetricsF, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from mtextedit import mdparse
from mtextedit.inplace import (
    PreviewSpec,
    _table_font,
    build_specs,
    column_widths,
    measure_specs,
    paint_spec,
)

TABLE = """| Name | Description |
|------|-------------|
| a | a much longer description cell right here |
| b | short |
"""

WIDE = 420


def _specs(source: str = TABLE, width: int = WIDE):
    tokens = mdparse.parse_tokens(source)
    return measure_specs(build_specs(tokens), width)


class ColumnWidthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.metrics = QFontMetricsF(_table_font())

    def test_columns_fill_the_available_width(self):
        rows = [[{"text": "a", "align": "left"}, {"text": "b", "align": "left"}]]
        widths = column_widths(rows, 300.0, self.metrics)
        self.assertEqual(len(widths), 2)
        self.assertAlmostEqual(sum(widths), 300.0, delta=0.5)

    def test_wider_content_gets_a_wider_column(self):
        widths = column_widths(
            [
                [
                    {"text": "a", "align": "left"},
                    {"text": "a much longer description cell", "align": "left"},
                ]
            ],
            418.0,
            self.metrics,
        )
        self.assertGreater(widths[1], widths[0] * 1.5)

    def test_empty_columns_do_not_collapse(self):
        rows = [[
            {"text": "", "align": "left"},
            {"text": "x" * 40, "align": "left"},
        ]]
        widths = column_widths(rows, 418.0, self.metrics)
        self.assertGreater(widths[0], 0.0)
        self.assertAlmostEqual(sum(widths), 418.0, delta=0.5)

    def test_no_columns_means_no_widths(self):
        self.assertEqual(column_widths([], 100.0, self.metrics), [])


class TableSpecTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_measurement_stores_widths(self):
        spec = _specs()[0]
        widths = spec.data["col_widths"]
        self.assertEqual(len(widths), 2)
        self.assertAlmostEqual(sum(widths), WIDE - 2, delta=0.5)
        self.assertGreater(widths[1], widths[0])

    def test_narrower_band_gives_narrower_columns(self):
        wide = _specs(width=WIDE)[0].data["col_widths"]
        narrow = _specs(width=220)[0].data["col_widths"]
        self.assertAlmostEqual(sum(narrow), 218, delta=0.5)
        self.assertLess(narrow[1], wide[1])

    def test_painting_a_table_produces_pixels(self):
        spec = _specs()[0]
        image = QImage(WIDE, int(spec.height), QImage.Format.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        try:
            paint_spec(painter, spec, QRectF(0, 0, WIDE, spec.height))
        finally:
            painter.end()
        painted = sum(
            1
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).name() != "#ffffff"
        )
        self.assertGreater(painted, 200, "the table card painted nothing")

    def test_plain_spec_without_widths_still_paints(self):
        spec = PreviewSpec(block=0, kind="table", height=48.0, data={
            "rows": [[{"text": "a", "align": "left"},
                      {"text": "b", "align": "left"}]]})
        image = QImage(200, 48, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        try:
            paint_spec(painter, spec, QRectF(0, 0, 200, 48))
        finally:
            painter.end()
        painted = sum(
            1
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).name() != "#ffffff"
        )
        self.assertGreater(painted, 50, "fallback widths painted nothing")


if __name__ == "__main__":
    unittest.main()
