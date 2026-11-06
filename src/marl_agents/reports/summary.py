"""Dashboard numbers computed from a ReviewResult. Nothing here is invented or hard-coded."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from marl_agents.core.schemas import Category, ReviewResult, Severity

# Severity weights for the issue density and the most-affected-files ranking.
SEVERITY_WEIGHT = {
    Severity.CRITICAL: 10.0,
    Severity.HIGH: 5.0,
    Severity.MEDIUM: 2.0,
    Severity.LOW: 0.5,
    Severity.INFO: 0.0,
}


class ReviewSummary(BaseModel):
    files_analyzed: int
    lines_analyzed: int
    total_findings: int
    by_severity: dict[str, int]
    by_category: dict[str, int]
    by_source: dict[str, int]
    potential_bugs: int = Field(description="bug + edge_case findings")
    security_issues: int
    error_handling_issues: int
    maintainability_issues: int
    testing_gaps: int
    documentation_issues: int
    weighted_density_per_kloc: float = Field(
        description="(10*critical + 5*high + 2*medium + 0.5*low) per 1000 reviewed lines"
    )
    top_files: list[tuple[str, float]]
    llm_rejection_rate: float | None = None


def summarize(result: ReviewResult) -> ReviewSummary:
    findings = result.findings
    sev = Counter(f.severity.value for f in findings)
    cat = Counter(f.category.value for f in findings)
    src = Counter(s.value for f in findings for s in f.sources)
    weighted = sum(SEVERITY_WEIGHT[f.severity] for f in findings)
    kloc = max(result.lines_analyzed, 1) / 1000.0
    density = weighted / kloc
    per_file: dict[str, float] = {}
    for f in findings:
        per_file[f.file] = per_file.get(f.file, 0.0) + SEVERITY_WEIGHT[f.severity]
    return ReviewSummary(
        files_analyzed=result.files_analyzed,
        lines_analyzed=result.lines_analyzed,
        total_findings=len(findings),
        by_severity={s.value: sev.get(s.value, 0) for s in Severity},
        by_category={c.value: cat.get(c.value, 0) for c in Category if cat.get(c.value)},
        by_source=dict(src),
        potential_bugs=cat.get(Category.BUG.value, 0) + cat.get(Category.EDGE_CASE.value, 0),
        security_issues=cat.get(Category.SECURITY.value, 0),
        error_handling_issues=cat.get(Category.ERROR_HANDLING.value, 0),
        maintainability_issues=cat.get(Category.MAINTAINABILITY.value, 0)
        + cat.get(Category.QUALITY.value, 0),
        testing_gaps=cat.get(Category.TESTING.value, 0),
        documentation_issues=cat.get(Category.DOCUMENTATION.value, 0),
        weighted_density_per_kloc=round(density, 2),
        top_files=[(f, w) for f, w in sorted(per_file.items(), key=lambda x: -x[1])[:5] if w > 0],
        llm_rejection_rate=result.stats.get("llm_rejection_rate"),
    )
