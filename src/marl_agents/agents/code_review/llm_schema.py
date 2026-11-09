"""What the LLM returns, parsed leniently: one malformed finding must not discard the others."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from marl_agents.core.schemas import Category, Finding, FindingSource, Severity

logger = logging.getLogger(__name__)

CATEGORY_ALIASES: dict[str, Category] = {
    "logic": Category.BUG,
    "correctness": Category.BUG,
    "defect": Category.BUG,
    "vulnerability": Category.SECURITY,
    "error handling": Category.ERROR_HANDLING,
    "exception handling": Category.ERROR_HANDLING,
    "exceptions": Category.ERROR_HANDLING,
    "edge case": Category.EDGE_CASE,
    "edge cases": Category.EDGE_CASE,
    "robustness": Category.EDGE_CASE,
    "concurrency": Category.EDGE_CASE,
    "complexity": Category.MAINTAINABILITY,
    "design": Category.MAINTAINABILITY,
    "readability": Category.QUALITY,
    "code quality": Category.QUALITY,
    "code smell": Category.QUALITY,
    "style": Category.STANDARDS,
    "convention": Category.STANDARDS,
    "coding standards": Category.STANDARDS,
    "test": Category.TESTING,
    "tests": Category.TESTING,
    "docs": Category.DOCUMENTATION,
    "docstring": Category.DOCUMENTATION,
    "efficiency": Category.PERFORMANCE,
}
SEVERITY_ALIASES: dict[str, Severity] = {
    "blocker": Severity.CRITICAL,
    "major": Severity.HIGH,
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "moderate": Severity.MEDIUM,
    "minor": Severity.LOW,
    "trivial": Severity.LOW,
    "suggestion": Severity.INFO,
    "note": Severity.INFO,
}


def parse_category(value: object) -> Category:
    text = str(value).strip().lower().replace("-", "_")
    try:
        return Category(text)
    except ValueError:
        spaced = text.replace("_", " ")
        if spaced in CATEGORY_ALIASES:
            return CATEGORY_ALIASES[spaced]
        raise ValueError(f"unknown category {value!r}") from None


def parse_severity(value: object) -> Severity:
    text = str(value).strip().lower()
    try:
        return Severity(text)
    except ValueError:
        if text in SEVERITY_ALIASES:
            return SEVERITY_ALIASES[text]
        raise ValueError(f"unknown severity {value!r}") from None


class LLMFinding(BaseModel):
    file: str | None = None
    start_line: int = Field(ge=1)
    end_line: int | None = None
    category: Category
    severity: Severity
    title: str = Field(min_length=1)
    description: str = ""
    evidence: list[str] = Field(default_factory=list)
    recommendation: str | None = None
    test_recommendation: str | None = None
    confidence: float = 0.5
    cwe: str | None = None
    # Ids ("C2") of the project-context items the model says support the finding. The agent keeps
    # only ids it really showed, so a cited source is never invented.
    context_refs: list[str] = Field(default_factory=list)

    @field_validator("context_refs", mode="before")
    @classmethod
    def _refs(cls, v: object) -> list[str]:
        if v is None:
            return []
        items = v if isinstance(v, list) else [v]
        return [str(x).strip().strip("[]").upper() for x in items if str(x).strip()]

    @field_validator("category", mode="before")
    @classmethod
    def _category(cls, v: object) -> Category:
        return parse_category(v)

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, v: object) -> Severity:
        return parse_severity(v)

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [str(x) for x in v] if isinstance(v, list) else [str(v)]

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v: object) -> float:
        try:
            x = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.5
        if x > 1.0:
            x = x / 100.0 if x <= 100 else 1.0
        return max(0.0, min(1.0, x))

    @field_validator("cwe", mode="before")
    @classmethod
    def _cwe(cls, v: object) -> str | None:
        if v in (None, "", "null", "None", "N/A"):
            return None
        text = str(v).strip().upper()
        if text.isdigit():
            text = f"CWE-{text}"
        return text if text.startswith("CWE-") else None

    def to_finding(self, default_file: str, symbol: str | None = None) -> Finding:
        end = (
            self.end_line if self.end_line and self.end_line >= self.start_line else self.start_line
        )
        return Finding(
            id="TMP",
            file=self.file or default_file,
            start_line=self.start_line,
            end_line=end,
            category=self.category,
            severity=self.severity,
            proposed_severity=self.severity,
            title=self.title.strip()[:200],
            description=self.description.strip() or self.title.strip(),
            evidence=[e for e in self.evidence if e.strip()],
            recommendation=self.recommendation,
            test_recommendation=self.test_recommendation,
            confidence=self.confidence,
            sources=[FindingSource.LLM],
            cwe=self.cwe,
            symbol=symbol,
        )


class StaticAssessment(BaseModel):
    ref: str
    verdict: str = "uncertain"
    recommendation: str | None = None
    test_recommendation: str | None = None

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, v: object) -> str:
        text = str(v).strip().lower().replace(" ", "_").replace("-", "_")
        if text in {"confirm", "confirmed", "true_positive", "valid", "agree"}:
            return "confirm"
        if text in {"false_positive", "fp", "reject", "rejected", "invalid", "disagree"}:
            return "false_positive"
        return "uncertain"


class LLMReviewEnvelope(BaseModel):
    """Outer shape only; items are validated one by one in `parse_items`."""

    findings: list[dict[str, Any]] = Field(default_factory=list)
    static_assessments: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("findings", "static_assessments", mode="before")
    @classmethod
    def _listify(cls, v: object) -> list[Any]:
        if v is None:
            return []
        if isinstance(v, dict):
            return [v]
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def parse_items(
    envelope: LLMReviewEnvelope,
) -> tuple[list[LLMFinding], list[StaticAssessment], list[str]]:
    findings: list[LLMFinding] = []
    assessments: list[StaticAssessment] = []
    errors: list[str] = []
    for raw in envelope.findings:
        try:
            findings.append(LLMFinding.model_validate(raw))
        except ValidationError as exc:
            errors.append(f"malformed finding dropped: {exc.errors()[0].get('msg', exc)}")
    for raw in envelope.static_assessments:
        try:
            assessments.append(StaticAssessment.model_validate(raw))
        except ValidationError:
            errors.append("malformed static assessment dropped")
    return findings, assessments, errors
