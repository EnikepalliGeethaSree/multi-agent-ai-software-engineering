"""Common interface for static analyzers. Output is normalized into `core.schemas.Finding`."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from marl_agents.core.schemas import Category, Finding, FindingSource, Severity
from marl_agents.ingestion.models import Repository
from marl_agents.parsing.repo_index import RepoIndex

Scope = dict[str, list[tuple[int, int]]]
# Must be >= review.scope_slack so pre-filtering never drops a finding that validation keeps.
SCOPE_SLACK = 3


@dataclass
class AnalyzerOutput:
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: bool = False


def overlaps_scope(scope: Scope | None, file: str, start: int, end: int) -> bool:
    """True when [start, end] touches a changed range (with slack), or when there is no scope."""
    if scope is None:
        return True
    return any(start <= e + SCOPE_SLACK and s - SCOPE_SLACK <= end for s, e in scope.get(file, []))


class StaticAnalyzer(ABC):
    name: str = "base"

    @abstractmethod
    def analyze(
        self, repo: Repository, index: RepoIndex, files: list[str], scope: Scope | None = None
    ) -> AnalyzerOutput:
        """Analyze the given repo-relative files. Must never execute repository code.

        `scope` (diff review) lets an analyzer skip work far from the changed lines; it is an
        optimisation only - the validator applies the authoritative scope filter afterwards.
        """


def make_finding(
    *,
    source: FindingSource,
    file: str,
    start_line: int,
    end_line: int | None,
    category: Category,
    severity: Severity,
    title: str,
    description: str,
    confidence: float,
    evidence: list[str] | None = None,
    recommendation: str | None = None,
    test_recommendation: str | None = None,
    rule_id: str | None = None,
    cwe: str | None = None,
    symbol: str | None = None,
) -> Finding:
    """Build a Finding with a temporary id; ids are assigned after dedup and ranking."""
    start = max(1, start_line)
    end = max(start, end_line or start)
    return Finding(
        id="TMP",
        file=file,
        start_line=start,
        end_line=end,
        category=category,
        severity=severity,
        proposed_severity=severity,
        title=title[:200],
        description=description,
        evidence=evidence or [],
        recommendation=recommendation,
        test_recommendation=test_recommendation,
        confidence=max(0.0, min(1.0, confidence)),
        sources=[source],
        rule_id=rule_id,
        cwe=cwe,
        symbol=symbol,
    )


def line_evidence(repo: Repository, file: str, start: int, end: int, max_lines: int = 3) -> str:
    """The cited source lines, trimmed, used as evidence for tool findings."""
    lines = repo.lines(file)
    chosen = lines[start - 1 : min(end, start - 1 + max_lines)]
    return "\n".join(chosen).strip()
