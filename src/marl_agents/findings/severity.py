"""Apply the documented severity rubric (docs/severity-rubric.md).

Tool findings already carry the severity from the rule table. LLM findings carry a *proposed*
severity; this module enforces floors/caps so severity is rule-based, not arbitrary.
"""

from __future__ import annotations

from marl_agents.core.schemas import Category, Finding, FindingSource, Severity

# Category ceilings: these kinds of issues cannot be more than this severe on their own.
CATEGORY_CAP: dict[Category, Severity] = {
    Category.STANDARDS: Severity.LOW,
    Category.DOCUMENTATION: Severity.LOW,
    Category.QUALITY: Severity.MEDIUM,
    Category.MAINTAINABILITY: Severity.MEDIUM,
    Category.TESTING: Severity.MEDIUM,
    Category.PERFORMANCE: Severity.HIGH,
}
# Category floors for LLM findings (static rules set their own severity explicitly).
LLM_CATEGORY_FLOOR: dict[Category, Severity] = {
    Category.SECURITY: Severity.MEDIUM,
}
# An LLM-only claim with low confidence cannot be critical/high.
LLM_LOW_CONFIDENCE = 0.5
LLM_LOW_CONFIDENCE_CAP = Severity.MEDIUM

_BY_RANK = {s.rank: s for s in Severity}


def _cap(sev: Severity, cap: Severity) -> Severity:
    return _BY_RANK[min(sev.rank, cap.rank)]


def _floor(sev: Severity, floor: Severity) -> Severity:
    return _BY_RANK[max(sev.rank, floor.rank)]


def apply_rubric(finding: Finding) -> Finding:
    proposed = finding.proposed_severity or finding.severity
    sev = finding.severity
    notes = list(finding.notes)
    llm_only = finding.sources == [FindingSource.LLM]

    if llm_only:
        floor = LLM_CATEGORY_FLOOR.get(finding.category)
        if floor and sev.rank < floor.rank:
            sev = _floor(sev, floor)
            notes.append(f"raised to {sev} (category floor)")
        if finding.confidence < LLM_LOW_CONFIDENCE and sev.rank > LLM_LOW_CONFIDENCE_CAP.rank:
            sev = LLM_LOW_CONFIDENCE_CAP
            notes.append(f"capped at {sev}: low-confidence LLM-only finding")

    cap = CATEGORY_CAP.get(finding.category)
    if cap and sev.rank > cap.rank:
        sev = _cap(sev, cap)
        notes.append(f"capped at {sev} (category ceiling)")

    if not finding.evidence and sev.rank > Severity.LOW.rank:
        sev = Severity.LOW
        notes.append("capped at low: no evidence")

    if sev == finding.severity and proposed == finding.proposed_severity:
        return finding
    return finding.model_copy(
        update={"severity": sev, "proposed_severity": proposed, "notes": notes}
    )
