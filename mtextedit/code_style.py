"""Code-block colour palette for the in-place preview (Pygments style).

Pygments is the highlighting engine (``DESIGN.md`` D8). What it does *not* ship
is a GitHub Light style -- only ``github-dark`` -- so the palette here was
extracted from the ``github-light.theme`` file that lived in the vendored C++
KSyntaxHighlighting fork. That fork has been removed (D14); this module is the
only thing kept from it, because the colours are still useful:

* ``GitHubLightStyle`` is a ready Pygments style for fenced code blocks.
* The ``CODE_*`` constants are the chrome and text colour the in-place preview
  paints, so the preview and any future token colouring share one palette
  instead of two sets of hex literals.

Provenance: ``github-light.theme``, ``SPDX-FileCopyrightText: 2020 GitHub Inc.``,
``SPDX-License-Identifier: MIT``. The colour *values* are GitHub's; the mapping
onto Pygments token types and the constants below are ours.
"""

from __future__ import annotations

from pygments.style import Style
from pygments.token import (
    Comment,
    Error,
    Generic,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
)

# Code-card chrome used by ``inplace.py``. It predates the extraction and is kept
# unchanged so existing notes render exactly as before.
CODE_BG = "#f6f8fa"
CODE_BORDER = "#d0d7de"

# ``Normal`` in the theme.
CODE_TEXT = "#24292e"

# Theme ``text-styles``: Keyword/ControlFlow/DataType/BuiltIn/Attribute/
# Preprocessor, Function/Others, String/Char/SpecialString/Import,
# VerbatimString, Constant/BaseN/DecVal/Float/SpecialChar, Variable, Comment/
# Documentation/Annotation/Information, Error/Alert/Warning.
KEYWORD = "#d73a49"
FUNCTION = "#6f42c1"
STRING = "#032f62"
STRING_VERBATIM = "#034c95"
CONSTANT = "#005cc5"
VARIABLE = "#e36209"
COMMENT = "#6a737d"
ERROR = "#ff5555"

# Theme ``custom-styles``: XML "Element" is green; Rust "Macro" / Python
# "Special Variable" are the constant blue.
TAG = "#22863a"


class GitHubLightStyle(Style):
    """GitHub Light colours for Pygments token types."""

    name = "github-light"
    aliases = ["github_light"]

    background_color = CODE_BG
    default_style = CODE_TEXT

    styles = {
        Text: CODE_TEXT,
        Error: f"underline {ERROR}",
        Comment: f"italic {COMMENT}",
        Comment.Preproc: KEYWORD,
        Keyword: f"bold {KEYWORD}",
        Keyword.Type: KEYWORD,
        Keyword.Constant: CONSTANT,
        # ``import`` / ``from``: theme's Python "Import" override.
        Keyword.Namespace: KEYWORD,
        Operator: CODE_TEXT,
        Operator.Word: KEYWORD,
        Punctuation: CODE_TEXT,
        Name: CODE_TEXT,
        Name.Attribute: KEYWORD,
        Name.Builtin: KEYWORD,
        Name.Builtin.Pseudo: CONSTANT,
        Name.Class: FUNCTION,
        Name.Constant: CONSTANT,
        Name.Decorator: KEYWORD,
        Name.Exception: FUNCTION,
        Name.Function: FUNCTION,
        Name.Namespace: CODE_TEXT,
        Name.Tag: TAG,
        Name.Variable: VARIABLE,
        Name.Variable.Magic: CONSTANT,
        Number: CONSTANT,
        String: STRING,
        String.Doc: STRING,
        String.Escape: CONSTANT,
        String.Interpol: CONSTANT,
        String.Regex: STRING,
        String.Symbol: STRING_VERBATIM,
        Generic.Heading: f"bold {CODE_TEXT}",
        Generic.Subheading: f"bold {CODE_TEXT}",
        Generic.Emph: "italic",
        Generic.Strong: "bold",
        Generic.Error: ERROR,
        Generic.Deleted: KEYWORD,
        Generic.Inserted: TAG,
    }
