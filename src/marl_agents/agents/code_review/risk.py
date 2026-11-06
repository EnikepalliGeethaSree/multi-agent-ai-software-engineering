"""Rank the hunks of a change by how much reviewer attention they need ("look here first").

Risk model v2: score = 100 * sigmoid(logit), read as "estimated chance (%) that a reviewer comments
on this hunk". Four weights were calibrated on the CodeReviewer cls *validation* split (Python,
n=4,219, run 20261005T111337Z_hunkrisk_cls_valid_n4220, scripts/calibrate_hunk_risk.py); the test
split was used once, for the reported result. Signals that do not occur in single-file benchmark
samples (broken callers in other files, untested functions) keep documented expert weights.

v1 (hand-set additive points) ranked worse than chance on CodeReviewer: static findings in a hunk
did not predict human comments. Findings therefore no longer add to the score; instead a
guardrail lifts hunks with critical (-> high) or high (-> at least medium) findings.
See docs/change-review.md and decision D17.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from marl_agents.core.schemas import ChangedSymbol, Finding, HunkRisk, Severity
from marl_agents.ingestion.changes import FileDiff

RISK_MODEL = "v2"
# Calibrated (logistic regression, L2 = 1) on the validation split; see module docstring.
INTERCEPT = -0.318
W_SENSITIVE = 0.454
W_ERROR_HANDLING = 0.648
W_SIGNATURE = 0.234
W_LOG2_SIZE = 0.055  # per doubling of changed lines
# Expert weights (logit) for signals the benchmark cannot exercise.
W_BREAKS_PER_SITE, W_BREAKS_MAX = 1.0, 2.0
W_UNTESTED = 0.3
SENSITIVE = re.compile(
    r"\b(eval|exec|pickle\.loads?|marshal\.loads?|yaml\.load|subprocess\.|os\.system|os\.popen|"
    r"shell\s*=\s*True|\.execute\(|cursor\.|hashlib\.(md5|sha1)|random\.|verify\s*=\s*False|"
    r"password|secret|token|api_key|requests\.(get|post|put|delete)|open\()",
    re.IGNORECASE,
)
ERROR_HANDLING = re.compile(r"^\s*(try:|except\b|raise\b|finally:)")
# Levels at the 90th / 65th percentile of validation-split scores.
HIGH, MEDIUM = 59.7, 47.4


@dataclass
class HunkView:
    file: str
    start: int
    end: int
    added_lines: list[str]
    deleted: int
    patch: str


def hunk_views(fd: FileDiff) -> list[HunkView]:
    views = []
    for h in fd.hunks:
        added = [ln[1:] for ln in h.lines if ln.startswith("+")]
        deleted = sum(1 for ln in h.lines if ln.startswith("-"))
        start = h.new_start if h.new_len else max(1, h.new_start)
        end = h.new_start + max(h.new_len, 1) - 1
        header = f"@@ -{h.old_start},{h.old_len} +{h.new_start},{h.new_len} @@"
        views.append(HunkView(fd.path, start, end, added, deleted, "\n".join([header, *h.lines])))
    return views


def score_hunk(
    view: HunkView,
    findings: list[Finding],
    symbols: list[ChangedSymbol],
    tested_names: set[str] | None = None,
    has_tests: bool = False,
) -> HunkRisk:
    logit = INTERCEPT
    reasons: list[str] = []
    inside = [
        f
        for f in findings
        if f.file == view.file and f.start_line <= view.end and view.start <= f.end_line
    ]
    worst = max((f.severity for f in inside), key=lambda s: s.rank, default=None)
    if inside and worst is not None:
        # Listed for the reviewer, but no score: on CodeReviewer, findings did not predict comments.
        reasons.append(f"{len(inside)} finding(s) in this hunk (worst: {worst.value})")

    sensitive = sorted(
        {m.group(0).strip().rstrip("(") for ln in view.added_lines for m in SENSITIVE.finditer(ln)}
    )
    if sensitive:
        logit += W_SENSITIVE
        reasons.append("touches security-sensitive code: " + ", ".join(sensitive[:4]))

    broken = [
        f
        for f in findings
        if (f.rule_id or "").startswith("IMPACT")
        or any(r.startswith(f"{view.file}") for r in f.related)
        if f.file != view.file and _breaks_from(f, view)
    ]
    if broken:
        logit += min(W_BREAKS_MAX, W_BREAKS_PER_SITE * len(broken))
        reasons.append(f"breaks {len(broken)} call site(s) in other code")
    dependents = sum(
        s.callers_not_updated
        for s in symbols
        if s.file == view.file and (_symbol_in(s, view) or (s.kind == "removed" and view.deleted))
    )
    if dependents:  # context for the reviewer (weight <= 0 on the validation split)
        reasons.append(f"{dependents} call site(s) elsewhere depend on the changed code")
    if any(s.signature_changed for s in symbols if s.file == view.file and _symbol_in(s, view)):
        logit += W_SIGNATURE
        reasons.append("changes a function signature")
    if any(s.kind == "removed" for s in symbols if s.file == view.file) and view.deleted:
        reasons.append("removes a function")  # context only (weight <= 0 on validation)

    size = len(view.added_lines) + view.deleted
    logit += W_LOG2_SIZE * math.log2(1 + size)
    if size > 50:
        reasons.append(f"large hunk ({size} changed lines)")
    elif size > 20:
        reasons.append(f"medium-sized hunk ({size} changed lines)")

    if any(ERROR_HANDLING.match(ln) for ln in view.added_lines):
        logit += W_ERROR_HANDLING
        reasons.append("changes error handling")

    if has_tests and tested_names is not None:
        public = [
            s
            for s in symbols
            if s.file == view.file and _symbol_in(s, view) and s.kind != "removed"
        ]
        untested = [
            s
            for s in public
            if not s.qualname.split(".")[-1].startswith("_")
            and s.qualname.split(".")[-1] not in tested_names
        ]
        if untested:
            logit += W_UNTESTED
            reasons.append("changed function has no test referencing it: " + untested[0].qualname)

    score = 100.0 / (1.0 + math.exp(-logit))
    level = "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"
    # Guardrail: severe findings are never buried, whatever the calibrated score says.
    if worst is Severity.CRITICAL:
        level = "high"
    elif worst is Severity.HIGH and level == "low":
        level = "medium"
    if not reasons:
        reasons.append("no risk signals")
    return HunkRisk(
        file=view.file,
        start_line=view.start,
        end_line=view.end,
        score=round(score, 1),
        level=level,
        reasons=reasons,
        patch=view.patch,
        finding_ids=[f.id for f in inside],
    )


def _breaks_from(f: Finding, view: HunkView) -> bool:
    """`f` (at a call site elsewhere) is caused by code changed in this hunk."""
    for rel in f.related:
        head, _, _ = rel.partition(" ")
        file, _, line = head.partition(":")
        if file != view.file:
            continue
        if not line:  # e.g. "path `fn` removed by this change"
            return view.deleted > 0
        if line.isdigit() and view.start - 1 <= int(line) <= view.end:
            return True
    return False


def _symbol_in(sym: ChangedSymbol, view: HunkView) -> bool:
    """The changed function's body overlaps this hunk."""
    if sym.line is None or sym.kind == "removed":
        return False
    return sym.line <= view.end and view.start <= (sym.end_line or sym.line)


def rank_hunks(
    files: list[FileDiff],
    findings: list[Finding],
    symbols: list[ChangedSymbol],
    tested_names: set[str] | None = None,
    has_tests: bool = False,
) -> list[HunkRisk]:
    hunks = [
        score_hunk(v, findings, symbols, tested_names, has_tests)
        for fd in files
        if fd.status != "deleted"
        for v in hunk_views(fd)
    ]
    return sorted(hunks, key=lambda h: (-h.score, h.file, h.start_line))
