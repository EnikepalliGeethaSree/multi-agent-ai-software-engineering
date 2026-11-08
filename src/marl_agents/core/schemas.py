"""Shared output contract used by every agent, the aggregator, reports and evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        """Higher is more severe; useful for sorting."""
        return {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}[self.value]


class Category(StrEnum):
    BUG = "bug"
    SECURITY = "security"
    QUALITY = "quality"
    MAINTAINABILITY = "maintainability"
    ERROR_HANDLING = "error_handling"
    EDGE_CASE = "edge_case"
    PERFORMANCE = "performance"
    TESTING = "testing"
    STANDARDS = "standards"
    DOCUMENTATION = "documentation"


class FindingSource(StrEnum):
    LLM = "llm"
    RUFF = "ruff"
    RADON = "radon"
    AST = "ast"
    MYPY = "mypy"


class BugType(StrEnum):
    """The defect classes of the Bug Detection Agent (approved deck, Fig. 3)."""

    LOGIC = "logic"
    NULL_EXCEPTION = "null_exception"
    BOUNDARY = "boundary"
    RESOURCE_LEAK = "resource_leak"
    CONCURRENCY = "concurrency"
    SECURITY = "security"
    OTHER = "other"


class BugDetail(BaseModel):
    """What makes a bug finding more than a comment: how it fails, and how to see it fail.

    `repro_steps` is advice for a developer. The product never runs analyzed code, so a report's
    steps are unconfirmed.
    """

    bug_type: BugType = BugType.OTHER
    trigger: str = Field(default="", description="Input or state that makes the code misbehave.")
    expected: str | None = Field(default=None, description="Correct behaviour for that trigger.")
    actual: str | None = Field(default=None, description="What the code does instead.")
    root_cause: str = Field(default="", description="Why the code misbehaves.")
    repro_steps: list[str] = Field(default_factory=list)
    involved_names: list[str] = Field(
        default_factory=list, description="Identifiers the claim depends on; checked against code."
    )


class SuggestedFix(BaseModel):
    """A concrete code change proposed for a finding. Never applied automatically."""

    file: str
    start_line: int = Field(ge=1, description="First line replaced (1-based, inclusive).")
    end_line: int = Field(ge=0, description="Last line replaced; start_line - 1 = pure insertion.")
    replacement: str = Field(description="New text for those lines (may be empty = delete).")
    diff: str = Field(description="Unified diff of the change, for display.")
    source: str = Field(description="'ruff' (tool autofix) or 'llm'.")
    verified: bool = Field(
        default=False,
        description="True when re-analysis confirmed the issue is gone and no new issue appeared.",
    )
    checks: list[str] = Field(default_factory=list, description="Verification steps performed.")


class Finding(BaseModel):
    """One located, evidenced issue. Produced by any agent or static analyzer."""

    id: str = Field(description="Stable ID within a result, e.g. 'CR-001'.")
    file: str = Field(description="Path relative to the repository root, forward slashes.")
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    category: Category
    severity: Severity
    title: str = Field(min_length=1, max_length=200)
    description: str
    evidence: list[str] = Field(
        default_factory=list, description="Code snippets / facts supporting it."
    )
    recommendation: str | None = None
    test_recommendation: str | None = None
    confidence: float = Field(
        ge=0.0, le=1.0, description="Ranking/filtering signal, NOT a probability of correctness."
    )
    sources: list[FindingSource] = Field(default_factory=list)
    rule_id: str | None = Field(default=None, description="Static-analysis rule, e.g. 'F401'.")
    cwe: str | None = Field(default=None, description="e.g. 'CWE-89' for security findings.")
    symbol: str | None = Field(default=None, description="Enclosing function/class, if any.")
    proposed_severity: Severity | None = Field(
        default=None, description="Severity suggested by the source before the rubric applied."
    )
    notes: list[str] = Field(
        default_factory=list, description="Pipeline audit trail: repairs, merges, rubric caps."
    )
    related: list[str] = Field(
        default_factory=list,
        description="Other locations involved, 'file:line description'.",
    )
    suggested_fix: SuggestedFix | None = None
    bug: BugDetail | None = Field(default=None, description="Set by the Bug Detection Agent.")

    @property
    def line_range(self) -> tuple[int, int]:
        return (self.start_line, self.end_line)

    def overlaps(self, other: Finding, slack: int = 0) -> bool:
        return (
            self.file == other.file
            and self.start_line <= other.end_line + slack
            and other.start_line <= self.end_line + slack
        )

    @model_validator(mode="after")
    def _check_line_range(self) -> Finding:
        if self.end_line < self.start_line:
            raise ValueError(f"end_line ({self.end_line}) < start_line ({self.start_line})")
        return self


class SuspectFunction(BaseModel):
    """One ranked candidate for where a failure comes from."""

    rank: int = Field(ge=1)
    file: str
    symbol: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    score: float = Field(description="Ordering signal before any LLM step; not a probability.")
    reasons: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list, description="Static rules that fired here.")


class LocalizationResult(BaseModel):
    """Fault localization: functions ranked by how likely they are to contain the failure."""

    suspects: list[SuspectFunction] = Field(default_factory=list)
    candidates_considered: int = 0
    candidates_shown: int = Field(default=0, description="How many the LLM saw; 0 without one.")
    ranked_by: str = Field(default="static", description="'static' or 'llm'.")
    hypothesis: str | None = None
    llm_failed: bool = False
    errors: list[str] = Field(default_factory=list)


class AgentRequest(BaseModel):
    """Input to any agent. Exactly one of `repo_path` or `snippet` should be set."""

    repo_path: str | None = None
    snippet: str | None = None
    snippet_filename: str = "snippet.py"
    target_files: list[str] | None = Field(
        default=None, description="Restrict analysis to these files (e.g. changed files in a PR)."
    )
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_input(self) -> AgentRequest:
        if (self.repo_path is None) == (self.snippet is None):
            raise ValueError("Provide exactly one of repo_path or snippet")
        return self


class RunMetadata(BaseModel):
    """Everything needed to reproduce a run."""

    agent: str
    provider: str
    model: str | None = None
    temperature: float | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    rag_enabled: bool = False
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


class AgentResult(BaseModel):
    """What every agent returns. Non-finding outputs (tests, docstrings) go in `artifacts`."""

    agent: str
    findings: list[Finding] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    rejected_findings: int = Field(default=0, description="Dropped by validation.")
    errors: list[str] = Field(default_factory=list)
    metadata: RunMetadata

    def by_severity(self) -> dict[Severity, int]:
        counts = {s: 0 for s in Severity}
        for f in self.findings:
            counts[f.severity] += 1
        return counts


# ---- change (pull request / diff) review ---------------------------------------------------


class ChangedFile(BaseModel):
    path: str = Field(description="Path in the new version (old path for deleted files).")
    status: str = Field(description="added | modified | deleted | renamed")
    old_path: str | None = None
    added: int = 0
    deleted: int = 0
    changed_ranges: list[tuple[int, int]] = Field(
        default_factory=list, description="Changed line ranges in the NEW file."
    )
    patch: str = Field(default="", description="Unified diff of this file.")


class ChangedSymbol(BaseModel):
    """A function/class/method added, modified or removed by the change."""

    file: str
    qualname: str
    kind: str = Field(description="added | modified | removed")
    line: int | None = Field(default=None, description="Definition line in the new version.")
    end_line: int | None = Field(default=None, description="Last line in the new version.")
    signature_changed: bool = False
    old_signature: str | None = None
    new_signature: str | None = None
    callers: int = Field(default=0, description="Call sites anywhere in the repository.")
    callers_not_updated: int = Field(
        default=0, description="Call sites in code the change did not touch."
    )


class HunkRisk(BaseModel):
    """One changed hunk, ranked by how much reviewer attention it needs."""

    file: str
    start_line: int
    end_line: int
    score: float = Field(ge=0.0, le=100.0)
    level: str = Field(description="high | medium | low")
    reasons: list[str] = Field(default_factory=list)
    patch: str = ""
    finding_ids: list[str] = Field(default_factory=list)


class ChangeSummary(BaseModel):
    base: str
    head: str
    files_changed: int
    lines_added: int
    lines_deleted: int
    symbols: list[ChangedSymbol] = Field(default_factory=list)
    salient: str | None = Field(
        default=None, description="The change that drives the others (most depended on)."
    )
    impacted_files: list[str] = Field(
        default_factory=list, description="Unchanged files that call changed code."
    )
    narrative: str | None = Field(default=None, description="LLM-written summary, if available.")


class ChangeReview(BaseModel):
    summary: ChangeSummary
    files: list[ChangedFile] = Field(default_factory=list)
    hunks: list[HunkRisk] = Field(default_factory=list)


class ReviewResult(AgentResult):
    """Code Review Agent result; files_analyzed and stats feed the dashboard/report."""

    files_analyzed: int = 0
    lines_analyzed: int = 0
    stats: dict[str, Any] = Field(
        default_factory=dict, description="Per-stage counts, timings, token usage (audit trail)."
    )
    change: ChangeReview | None = Field(
        default=None, description="Present when a code change (diff / PR) was reviewed."
    )
