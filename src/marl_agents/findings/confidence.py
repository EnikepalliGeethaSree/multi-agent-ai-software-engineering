"""Confidence calibration: a ranking/filtering signal, NOT a probability of correctness.

Inputs: the rule's prior reliability (static tools), the LLM's self-reported confidence (discounted,
LLMs are over-confident), multi-source agreement, and validation repairs.
"""

from __future__ import annotations

from marl_agents.core.schemas import Finding, FindingSource, Severity

LLM_SELF_REPORT_WEIGHT = 0.8  # LLM self-confidence is shrunk towards 0
LLM_CONFIDENCE_CEILING = 0.9  # an LLM-only finding never reaches the top of the scale
REPAIR_PENALTY = 0.85  # finding had to be relocated by the validator
LLM_DISPUTE_PENALTY = 0.5  # the LLM judged a static finding to be a false positive
LLM_CONFIRM_BOOST = 0.3  # the LLM confirmed a static finding (combined as independent vote)


def calibrate(finding: Finding) -> Finding:
    conf = finding.confidence
    notes = finding.notes
    if finding.sources == [FindingSource.LLM]:
        conf = min(conf * LLM_SELF_REPORT_WEIGHT, LLM_CONFIDENCE_CEILING)
    if any(n.startswith("lines moved") for n in notes):
        conf *= REPAIR_PENALTY
    if "llm: false positive" in notes:
        conf *= LLM_DISPUTE_PENALTY
    elif "llm: confirmed" in notes:
        conf = 1 - (1 - conf) * (1 - LLM_CONFIRM_BOOST)
    conf = round(max(0.0, min(0.99, conf)), 3)
    if conf == finding.confidence:
        return finding
    return finding.model_copy(update={"confidence": conf})


def priority(finding: Finding) -> float:
    """Ranking score: severity dominates, confidence breaks ties within a level."""
    return finding.severity.rank + finding.confidence


def rank_and_number(findings: list[Finding], prefix: str = "CR") -> list[Finding]:
    ordered = sorted(findings, key=lambda f: (-priority(f), f.file, f.start_line))
    return [
        f.model_copy(update={"id": f"{prefix}-{i:03d}"}) for i, f in enumerate(ordered, start=1)
    ]


def passes_threshold(finding: Finding, min_confidence: float) -> bool:
    """Critical findings are always kept for human review regardless of confidence."""
    return finding.severity is Severity.CRITICAL or finding.confidence >= min_confidence
