"""Unified-diff utilities: changed line ranges (PR review) and applying a hunk to an old file."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(ValueError):
    """The patch does not apply to the given file content."""


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list[str] = field(default_factory=list)  # with ' ', '-', '+' prefixes


def parse_hunks(patch: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    current: Hunk | None = None
    for line in patch.splitlines():
        m = _HUNK.match(line)
        if m:
            current = Hunk(
                old_start=int(m.group(1)),
                old_len=int(m.group(2)) if m.group(2) is not None else 1,
                new_start=int(m.group(3)),
                new_len=int(m.group(4)) if m.group(4) is not None else 1,
            )
            hunks.append(current)
            continue
        if current is None or line.startswith(("---", "+++", "diff ", "index ")):
            continue
        if line.startswith("\\"):
            continue  # "\ No newline at end of file"
        if line == "":
            line = " "  # some tools strip the space from empty context lines
        if line[0] in " +-":
            current.lines.append(line)
    return hunks


def changed_new_lines(patch: str) -> list[tuple[int, int]]:
    """1-based line ranges in the NEW file that were added/modified.

    A pure deletion is attributed to the new line where the deletion happened.
    """
    ranges: list[tuple[int, int]] = []
    for hunk in parse_hunks(patch):
        new_line = hunk.new_start
        run_start: int | None = None
        pending_delete = False
        for line in hunk.lines:
            tag = line[0]
            if tag == "+":
                run_start = new_line if run_start is None else run_start
                new_line += 1
            elif tag == "-":
                pending_delete = True
            else:
                if run_start is not None:
                    ranges.append((run_start, new_line - 1))
                    run_start = None
                elif pending_delete:
                    ranges.append((max(1, new_line - 1), max(1, new_line)))
                pending_delete = False
                new_line += 1
        if run_start is not None:
            ranges.append((run_start, new_line - 1))
        elif pending_delete:
            ranges.append((max(1, new_line - 1), max(1, new_line - 1)))
    return _merge(ranges)


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def apply_patch(old: str, patch: str, fuzz: int = 3) -> str:
    """Apply the hunks of `patch` to `old` (context lines are verified).

    `fuzz` allows the hunk to be found a few lines away from its declared position.
    """
    old_lines = old.splitlines()
    result: list[str] = []
    cursor = 0  # index into old_lines
    for hunk in parse_hunks(patch):
        expected_old = [ln[1:] for ln in hunk.lines if ln[0] in " -"]
        declared = max(hunk.old_start - 1, 0) if hunk.old_len else hunk.old_start
        position = None
        for delta in sorted(range(-fuzz, fuzz + 1), key=abs):
            pos = declared + delta
            if pos < cursor or pos < 0:
                continue
            window = old_lines[pos : pos + len(expected_old)]
            if [w.rstrip() for w in window] == [e.rstrip() for e in expected_old]:
                position = pos
                break
        if position is None:
            raise PatchError(f"hunk at -{hunk.old_start} does not match the old file")
        result.extend(old_lines[cursor:position])
        result.extend(ln[1:] for ln in hunk.lines if ln[0] in " +")
        cursor = position + len(expected_old)
    result.extend(old_lines[cursor:])
    trailing = "\n" if old.endswith("\n") or not old else ""
    return "\n".join(result) + trailing
