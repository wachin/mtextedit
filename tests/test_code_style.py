"""Tests for the code-block palette salvaged from the removed C++ fork (D14).

Run from ``libs/mtextedit``::

    python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer
from pygments.style import Style
from pygments.token import Keyword, Name, Token

from mtextedit import inplace
from mtextedit.code_style import (
    CODE_BG,
    CODE_BORDER,
    CODE_TEXT,
    COMMENT,
    CONSTANT,
    FUNCTION,
    KEYWORD,
    STRING,
    GitHubLightStyle,
)


class GitHubLightStyleTest(unittest.TestCase):
    def test_is_a_pygments_style(self):
        self.assertTrue(issubclass(GitHubLightStyle, Style))
        self.assertEqual(GitHubLightStyle.background_color, CODE_BG)

    def test_token_colors_match_the_extracted_theme(self):
        # Values taken verbatim from github-light.theme (MIT, GitHub Inc.).
        self.assertEqual(CODE_BG, "#f6f8fa")
        self.assertEqual(CODE_BORDER, "#d0d7de")
        self.assertEqual(CODE_TEXT, "#24292e")
        self.assertEqual(
            {KEYWORD, FUNCTION, STRING, CONSTANT, COMMENT},
            {"#d73a49", "#6f42c1", "#032f62", "#005cc5", "#6a737d"},
        )

    def test_subtokens_inherit_their_parent(self):
        style = GitHubLightStyle
        # Pygments reports colours without the leading '#'.
        self.assertEqual(
            style.style_for_token(Name.Function)["color"], FUNCTION.lstrip("#"))
        self.assertEqual(
            style.style_for_token(Name.Function.Magic)["color"],
            FUNCTION.lstrip("#"))
        self.assertEqual(
            style.style_for_token(Token.Text)["color"], CODE_TEXT.lstrip("#"))

    def test_python_snippet_uses_the_palette(self):
        code = (
            "import os\n"
            "\n"
            "def greet(name):\n"
            "    # a comment\n"
            "    return f'hello {name}' + str(1)\n"
        )
        html = highlight(
            code, PythonLexer(),
            HtmlFormatter(style=GitHubLightStyle, noclasses=True),
        )
        for color in (KEYWORD, COMMENT, STRING, CONSTANT, CODE_BG):
            self.assertIn(color, html)

    def test_preview_shares_the_palette(self):
        # One source of truth: the in-place code card must not re-declare hexes.
        self.assertEqual(inplace._CODE_BG.name(), CODE_BG)
        self.assertEqual(inplace._CODE_BORDER.name(), CODE_BORDER)
        self.assertEqual(inplace._CODE_FG.name(), CODE_TEXT)


if __name__ == "__main__":
    unittest.main()
