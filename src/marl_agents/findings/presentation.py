"""Last touches shared by every agent: what supports a finding, and the code it points at.

Runs after deduplication, because merging can widen a finding's line range.

Evidence basis:
- `static_confirmed`: a static rule produced or agreed with the finding.
- `llm_with_context`: the LLM produced it and cited retrieved project context that it was shown.
- `llm_inferred`: the LLM produced it from the code alone.

The basis says where a finding came from. It is not a probability that the finding is right.
"""

from __future__ import annotations

from marl_agents.core.schemas import EvidenceBasis, Finding, FindingSource
from marl_agents.findings.redaction import is_secret_finding, mask_literals
from marl_agents.ingestion import Repository

MAX_SNIPPET_LINES = 12


def evidence_basis(finding: Finding) -> EvidenceBasis:
    if any(s is not FindingSource.LLM for s in finding.sources):
        return EvidenceBasis.STATIC_CONFIRMED
    if finding.context_refs:
        return EvidenceBasis.LLM_WITH_CONTEXT
    return EvidenceBasis.LLM_INFERRED


def snippet_of(finding: Finding, repo: Repository) -> str | None:
    """The finding's own lines, read from the file (at most MAX_SNIPPET_LINES); secrets masked."""
    if not repo.has(finding.file):
        return None
    lines = repo.lines(finding.file)
    end = min(finding.end_line, finding.start_line + MAX_SNIPPET_LINES - 1, len(lines))
    picked = lines[finding.start_line - 1 : end]
    if not picked:
        return None
    text = "\n".join(picked)
    return mask_literals(text) if is_secret_finding(finding) else text


def finalize(findings: list[Finding], repo: Repository) -> list[Finding]:
    return [
        f.model_copy(update={"evidence_basis": evidence_basis(f), "snippet": snippet_of(f, repo)})
        for f in findings
    ]
