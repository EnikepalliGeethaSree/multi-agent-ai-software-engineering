"""Build SuggestedFix objects: apply text edits, compute the replaced line range and a display diff.

A suggested fix is never applied to the analyzed repository; it is shown to the developer.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from dataclasses import dataclass

from marl_agents.core.schemas import SuggestedFix


@dataclass(frozen=True)
class TextEdit:
    """Replace text between (row, col) positions; rows and columns are 1-based, end exclusive."""

    start_row: int
    start_col: int
    end_row: int
    end_col: int
    content: str


def _offset(lines: list[str], row: int, col: int) -> int:
    if row > len(lines):
        return sum(len(ln) for ln in lines)
    return sum(len(ln) for ln in lines[: row - 1]) + (col - 1)


def apply_edits(text: str, edits: Iterable[TextEdit]) -> str:
    """Apply non-overlapping edits (any order) to `text`."""
    lines = text.splitlines(keepends=True)
    spans = sorted(
        (
            (
                _offset(lines, e.start_row, e.start_col),
                _offset(lines, e.end_row, e.end_col),
                e.content,
            )
            for e in edits
        ),
        reverse=True,
    )
    out = text
    for start, end, content in spans:
        out = out[:start] + content + out[end:]
    return out


def replace_lines(text: str, start_line: int, end_line: int, replacement: str) -> str:
    """Replace lines start..end (1-based, inclusive); end = start - 1 means insert."""
    lines = text.splitlines(keepends=True)
    new_lines = replacement.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n") and end_line < len(lines):
        new_lines[-1] += "\n"
    return "".join(lines[: start_line - 1] + new_lines + lines[end_line:])


def make_fix(
    file: str,
    old_text: str,
    new_text: str,
    source: str,
    verified: bool = False,
    checks: list[str] | None = None,
) -> SuggestedFix | None:
    """The minimal line range that differs, as a SuggestedFix; None if nothing changed."""
    old = old_text.splitlines()
    new = new_text.splitlines()
    if old == new:
        return None
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(old), len(new)) - prefix
        and old[len(old) - 1 - suffix] == new[len(new) - 1 - suffix]
    ):
        suffix += 1
    start = prefix + 1
    end = len(old) - suffix  # may be start - 1 for a pure insertion
    replacement = "\n".join(new[prefix : len(new) - suffix])
    diff = "\n".join(
        difflib.unified_diff(old, new, fromfile=f"a/{file}", tofile=f"b/{file}", n=2, lineterm="")
    )
    return SuggestedFix(
        file=file,
        start_line=start,
        end_line=end,
        replacement=replacement,
        diff=diff,
        source=source,
        verified=verified,
        checks=checks or [],
    )
