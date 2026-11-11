"""Result Aggregator: merge the findings of several agents into one result (Part 5).

Two findings are the same issue when they are in the same file, their line ranges overlap and
they have the same category. Merging keeps the higher severity and the higher confidence, takes
the title, description and location of the more severe finding, keeps every evidence snippet,
source, note and the other finding's id (`related`), and records which agents raised it
(`raised_by`).

This is deliberately the simple rule asked for; the per-agent pipelines have already deduplicated
their own findings with the richer rule of `findings.dedup` (which also compares wording).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from marl_agents.core.schemas import Finding


class AggregatedFinding(BaseModel):
    finding: Finding
    raised_by: list[str] = Field(description="Agents that reported this issue, e.g. code_review.")
    merged_ids: list[str] = Field(default_factory=list, description="Original finding ids.")


class AggregationSummary(BaseModel):
    agents: list[str]
    findings_in: dict[str, int]
    unique: dict[str, int] = Field(description="Findings raised by one agent only, per agent.")
    shared: int = Field(description="Findings raised by two or more agents.")
    merged: int = Field(description="Input findings merged into another one.")
    total: int


class Aggregation(BaseModel):
    findings: list[AggregatedFinding]
    summary: AggregationSummary


def same_issue(a: Finding, b: Finding) -> bool:
    return (
        a.file == b.file
        and a.category == b.category
        and a.start_line <= b.end_line
        and b.start_line <= a.end_line
    )


def _merge(primary: AggregatedFinding, other: Finding, agent: str) -> AggregatedFinding:
    base = primary.finding
    stronger = other.severity.rank > base.severity.rank
    keep = other if stronger else base
    weaker = base if stronger else other
    merged = keep.model_copy(
        update={
            "severity": max(base.severity, other.severity, key=lambda s: s.rank),
            "confidence": max(base.confidence, other.confidence),
            "evidence": list(dict.fromkeys([*keep.evidence, *weaker.evidence])),
            "sources": list(dict.fromkeys([*keep.sources, *weaker.sources])),
            "recommendation": keep.recommendation or weaker.recommendation,
            "test_recommendation": keep.test_recommendation or weaker.test_recommendation,
            "cwe": keep.cwe or weaker.cwe,
            "related": list(dict.fromkeys([*keep.related, *weaker.related, weaker.id])),
            "notes": [
                *keep.notes,
                f"aggregator: merged {weaker.id} ({weaker.file}:{weaker.start_line}-"
                f"{weaker.end_line}) - same file, overlapping lines, same category",
            ],
        }
    )
    return AggregatedFinding(
        finding=merged,
        raised_by=list(dict.fromkeys([*primary.raised_by, agent])),
        merged_ids=[*primary.merged_ids, other.id],
    )


def aggregate(results: dict[str, list[Finding]], id_prefix: str = "AG") -> Aggregation:
    """`results`: agent name -> its findings. Order of agents is kept in the summary."""
    items = [(agent, f) for agent, fs in results.items() for f in fs]
    items.sort(key=lambda x: (x[1].file, -x[1].severity.rank, x[1].start_line))
    clusters: list[AggregatedFinding] = []
    merged = 0
    for agent, f in items:
        match = next((c for c in clusters if same_issue(c.finding, f)), None)
        if match is None:
            clusters.append(AggregatedFinding(finding=f, raised_by=[agent], merged_ids=[f.id]))
        else:
            clusters[clusters.index(match)] = _merge(match, f, agent)
            merged += 1
    clusters.sort(
        key=lambda c: (
            -c.finding.severity.rank,
            -c.finding.confidence,
            c.finding.file,
            c.finding.start_line,
        )
    )
    for i, c in enumerate(clusters, start=1):
        c.finding = c.finding.model_copy(update={"id": f"{id_prefix}-{i:03d}"})
    agents = list(results)
    return Aggregation(
        findings=clusters,
        summary=AggregationSummary(
            agents=agents,
            findings_in={a: len(fs) for a, fs in results.items()},
            unique={a: sum(1 for c in clusters if c.raised_by == [a]) for a in agents},
            shared=sum(1 for c in clusters if len(c.raised_by) > 1),
            merged=merged,
            total=len(clusters),
        ),
    )
