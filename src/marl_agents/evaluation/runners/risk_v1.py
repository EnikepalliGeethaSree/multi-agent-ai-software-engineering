"""Frozen baseline: hunk-risk model v1 (hand-set additive points), as shipped before v2.

Kept only so every risk-ranking evaluation compares v2 against v1, size and random on the same
samples. Not used by the product. Weights are exactly those of v1 (see docs/results.md, section 6):
findings in the hunk (critical 30, high 20, medium 10, low 3, capped at 40), security-sensitive
code +15, broken call sites +15 each (max 30), callers not updated +5 each (max 20), signature
change +10, removed function +10, size >50 lines +10 / >20 lines +5, error handling +5,
untested public function +5; capped at 100.
"""

from __future__ import annotations

from marl_agents.agents.code_review.risk import (
    ERROR_HANDLING,
    SENSITIVE,
    HunkView,
    _breaks_from,
    _symbol_in,
    hunk_views,
)
from marl_agents.core.schemas import ChangedSymbol, Finding, Severity
from marl_agents.ingestion.changes import FileDiff

FINDING_POINTS = {
    Severity.CRITICAL: 30,
    Severity.HIGH: 20,
    Severity.MEDIUM: 10,
    Severity.LOW: 3,
    Severity.INFO: 0,
}
FINDING_CAP = 40


def score_v1(
    view: HunkView,
    findings: list[Finding],
    symbols: list[ChangedSymbol],
    tested_names: set[str] | None = None,
    has_tests: bool = False,
) -> float:
    score = 0.0
    inside = [
        f
        for f in findings
        if f.file == view.file and f.start_line <= view.end and view.start <= f.end_line
    ]
    score += min(FINDING_CAP, sum(FINDING_POINTS[f.severity] for f in inside))
    if any(SENSITIVE.search(ln) for ln in view.added_lines):
        score += 15
    broken = [
        f
        for f in findings
        if (f.rule_id or "").startswith("IMPACT") or any(r.startswith(view.file) for r in f.related)
        if f.file != view.file and _breaks_from(f, view)
    ]
    score += min(30, 15 * len(broken))
    dependents = sum(
        s.callers_not_updated
        for s in symbols
        if s.file == view.file and (_symbol_in(s, view) or (s.kind == "removed" and view.deleted))
    )
    score += min(20, 5 * dependents)
    if any(s.signature_changed for s in symbols if s.file == view.file and _symbol_in(s, view)):
        score += 10
    if any(s.kind == "removed" for s in symbols if s.file == view.file) and view.deleted:
        score += 10
    size = len(view.added_lines) + view.deleted
    score += 10 if size > 50 else 5 if size > 20 else 0
    if any(ERROR_HANDLING.match(ln) for ln in view.added_lines):
        score += 5
    if has_tests and tested_names is not None:
        untested = [
            s
            for s in symbols
            if s.file == view.file
            and _symbol_in(s, view)
            and s.kind != "removed"
            and not s.qualname.split(".")[-1].startswith("_")
            and s.qualname.split(".")[-1] not in tested_names
        ]
        if untested:
            score += 5
    return min(100.0, score)


def max_score_v1(
    files: list[FileDiff],
    findings: list[Finding],
    symbols: list[ChangedSymbol],
    tested_names: set[str] | None = None,
    has_tests: bool = False,
) -> float:
    """Highest v1 hunk score of a change (0 when there is no reviewable hunk)."""
    return max(
        (
            score_v1(v, findings, symbols, tested_names, has_tests)
            for fd in files
            if fd.status != "deleted"
            for v in hunk_views(fd)
        ),
        default=0.0,
    )
