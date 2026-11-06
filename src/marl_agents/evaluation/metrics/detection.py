"""Match findings to a ground-truth issue list (planted-issue benchmark, localization metrics)."""

from __future__ import annotations

from pydantic import BaseModel

from marl_agents.core.schemas import Category, Finding
from marl_agents.findings.dedup import categories_compatible

DEFECT_CATEGORIES = {Category.BUG, Category.SECURITY, Category.ERROR_HANDLING, Category.EDGE_CASE}


class ExpectedIssue(BaseModel):
    id: str
    file: str
    line: int
    category: Category
    detectable_by: str = "static"
    issue: str = ""
    cwe: str | None = None


class DetectionMetrics(BaseModel):
    """Planted-issue detection.

    - TP: defect findings (bug/security/error-handling/edge-case) matching a planted issue
      (same file, within `line_tolerance` lines, compatible category).
    - FP: defect findings matching no planted issue.
    - FN: planted issues no finding matched.
    - precision = TP / (TP + FP) over defect findings: style/docs findings are not in the answer
      key, so they are neither counted correct nor wrong.
    - recall = matched planted issues / all planted issues.
    - f1 = harmonic mean of precision and recall.
    """

    expected: int
    matched: int
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float = 0.0
    f1: float = 0.0
    recall: float
    recall_static: float | None
    recall_llm: float | None
    defect_findings: int
    defect_true_positives: int
    defect_precision: float
    negative_file_false_positives: int
    mean_line_error: float | None
    missed: list[str]
    false_positive_titles: list[str]


def f1_score(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def matches(finding: Finding, issue: ExpectedIssue, line_tolerance: int = 2) -> bool:
    if finding.file != issue.file:
        return False
    near = finding.start_line - line_tolerance <= issue.line <= finding.end_line + line_tolerance
    return near and categories_compatible(finding.category, issue.category)


def detection_metrics(
    findings: list[Finding],
    expected: list[ExpectedIssue],
    negative_files: list[str] | None = None,
    line_tolerance: int = 2,
) -> DetectionMetrics:
    matched_ids: set[str] = set()
    line_errors: list[int] = []
    used_findings: set[int] = set()
    for issue in expected:
        cands = [(i, f) for i, f in enumerate(findings) if matches(f, issue, line_tolerance)]
        if cands:
            i, f = min(cands, key=lambda x: abs(x[1].start_line - issue.line))
            matched_ids.add(issue.id)
            used_findings.add(i)
            line_errors.append(abs(f.start_line - issue.line))
    # Any finding matching some expected issue counts as a true positive (several findings may
    # legitimately describe one issue before dedup; dedup quality is measured separately).
    for i, f in enumerate(findings):
        if any(matches(f, issue, line_tolerance) for issue in expected):
            used_findings.add(i)

    def recall_of(kind: str) -> float | None:
        subset = [e for e in expected if e.detectable_by == kind]
        return sum(1 for e in subset if e.id in matched_ids) / len(subset) if subset else None

    defect = [(i, f) for i, f in enumerate(findings) if f.category in DEFECT_CATEGORIES]
    defect_tp = sum(1 for i, _ in defect if i in used_findings)
    negatives = set(negative_files or [])
    recall = len(matched_ids) / len(expected) if expected else 0.0
    precision = defect_tp / len(defect) if defect else 1.0
    return DetectionMetrics(
        expected=len(expected),
        matched=len(matched_ids),
        tp=defect_tp,
        fp=len(defect) - defect_tp,
        fn=len(expected) - len(matched_ids),
        precision=precision,
        f1=f1_score(precision, recall),
        recall=recall,
        recall_static=recall_of("static"),
        recall_llm=recall_of("llm"),
        defect_findings=len(defect),
        defect_true_positives=defect_tp,
        defect_precision=defect_tp / len(defect) if defect else 1.0,
        negative_file_false_positives=sum(1 for _, f in defect if f.file in negatives),
        mean_line_error=sum(line_errors) / len(line_errors) if line_errors else None,
        missed=[e.id for e in expected if e.id not in matched_ids],
        false_positive_titles=[f.title for i, f in defect if i not in used_findings],
    )
