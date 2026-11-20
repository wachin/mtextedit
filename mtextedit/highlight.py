"""Pygments token runs for fenced code (computed off the GUI thread).

The in-place preview paints code into its own band, so it needs colours as plain
data: for each source line, a list of ``(text, "#rrggbb")`` runs. They are built
while the token stream is produced (``mdparse``), off the GUI thread (D12), and
are free of Qt types.

Indented ``code_block`` blocks carry no language and unknown languages are not
guessed: both return no runs, and the preview falls back to flat monospace text.
Every line's runs concatenate back to the source line, which is what makes the
painted text match what the user sees as source.
"""

from __future__ import annotations

from .code_style import CODE_TEXT, GitHubLightStyle

Run = tuple[str, str]
LineRuns = list[Run]

# A fence is a snippet, not a book. Past this size we skip highlighting so a
# pathological block cannot stretch a render worker (the block still paints).
MAX_HIGHLIGHT_CHARS = 100_000

_TAB = 4


def _lexer_for(lang: str):
    if not lang:
        return None
    try:
        from pygments.lexers import get_lexer_by_name
        return get_lexer_by_name(
            lang.strip().lower(), stripnl=False, ensurenl=False)
    except Exception:  # noqa: BLE001 - unknown alias, or Pygments missing a plugin
        return None


def _colour(token_type) -> str:
    info = GitHubLightStyle.style_for_token(token_type)
    colour = info.get("color")
    return f"#{colour}" if colour else CODE_TEXT


def _merge(runs: LineRuns) -> LineRuns:
    """Join adjacent runs of the same colour (fewer draw calls)."""
    merged: LineRuns = []
    for text, colour in runs:
        if not text:
            continue
        if merged and merged[-1][1] == colour:
            merged[-1] = (merged[-1][0] + text, colour)
        else:
            merged.append((text, colour))
    return merged


def _expand_tabs(runs: LineRuns) -> LineRuns:
    """Expand tabs to 4-column stops, tracking the column across runs."""
    out: LineRuns = []
    column = 0
    for text, colour in runs:
        if "\t" not in text:
            out.append((text, colour))
            column += len(text)
            continue
        parts = text.split("\t")
        buffer: list[str] = []
        for index, part in enumerate(parts):
            if part:
                buffer.append(part)
                column += len(part)
            if index != len(parts) - 1:
                pad = _TAB - (column % _TAB)
                buffer.append(" " * pad)
                column += pad
        out.append(("".join(buffer), colour))
    return _merge(out)


def code_runs(code: str, lang: str) -> list[LineRuns]:
    """Return per-line Pygments colour runs for ``code``, or ``[]``.

    An empty list means "no highlighting available"; callers paint the plain
    fallback. Runs never reorder or drop characters: concatenating one line's
    runs reproduces that source line, tabs already expanded.
    """
    if not code or len(code) > MAX_HIGHLIGHT_CHARS:
        return []
    lexer = _lexer_for(lang)
    if lexer is None:
        return []
    try:
        tokens = list(lexer.get_tokens(code))
    except Exception:  # noqa: BLE001 - a broken lexer must never break a render
        return []

    lines: list[LineRuns] = [[]]
    for token_type, value in tokens:
        if not value:
            continue
        colour = _colour(token_type)
        parts = value.split("\n")
        for index, part in enumerate(parts):
            if part:
                lines[-1].append((part, colour))
            if index != len(parts) - 1:
                lines.append([])

    # Pygments ends with a newline; the last empty line is not painted.
    if len(lines) > 1 and not lines[-1]:
        lines.pop()
    return [_expand_tabs(line) for line in lines]
