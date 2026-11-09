"""What the LLM returns for bug detection and localization, parsed leniently."""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError, field_validator

from marl_agents.agents.code_review.llm_schema import (
    LLMFinding,
    LLMReviewEnvelope,
    StaticAssessment,
)
from marl_agents.core.schemas import BugDetail, BugType, Finding

BUG_TYPE_ALIASES: dict[str, BugType] = {
    "wrong_result": BugType.LOGIC,
    "null": BugType.NULL_EXCEPTION,
    "none": BugType.NULL_EXCEPTION,
    "exception": BugType.NULL_EXCEPTION,
    "null_or_exception": BugType.NULL_EXCEPTION,
    "off_by_one": BugType.BOUNDARY,
    "edge_case": BugType.BOUNDARY,
    "resource": BugType.RESOURCE_LEAK,
    "leak": BugType.RESOURCE_LEAK,
    "race": BugType.CONCURRENCY,
    "race_condition": BugType.CONCURRENCY,
    "vulnerability": BugType.SECURITY,
}


def parse_bug_type(value: object) -> BugType:
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_").replace("/", "_")
    try:
        return BugType(text)
    except ValueError:
        return BUG_TYPE_ALIASES.get(text, BugType.OTHER)


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


class LLMBugFinding(LLMFinding):
    """A review finding, plus what is needed to believe it and to see it fail."""

    bug_type: BugType = BugType.OTHER
    root_cause: str = ""
    trigger: str = ""
    expected: str | None = None
    actual: str | None = None
    involved_names: list[str] = Field(default_factory=list)
    repro_steps: list[str] = Field(default_factory=list)
    fix_explanation: str = ""

    @field_validator("bug_type", mode="before")
    @classmethod
    def _bug_type(cls, v: object) -> BugType:
        return parse_bug_type(v)

    @field_validator("root_cause", "trigger", "fix_explanation", mode="before")
    @classmethod
    def _plain(cls, v: object) -> str:
        return _text(v)

    @field_validator("involved_names", "repro_steps", mode="before")
    @classmethod
    def _strings(cls, v: object) -> list[str]:
        if v is None:
            return []
        items = v if isinstance(v, list) else [v]
        return [_text(x) for x in items if _text(x)]

    def to_finding(self, default_file: str, symbol: str | None = None) -> Finding:
        finding = super().to_finding(default_file, symbol)
        detail = BugDetail(
            bug_type=self.bug_type,
            trigger=self.trigger,
            expected=self.expected,
            actual=self.actual,
            root_cause=self.root_cause,
            repro_steps=self.repro_steps,
            involved_names=self.involved_names,
            fix_explanation=self.fix_explanation,
        )
        description = self.root_cause or finding.description
        return finding.model_copy(update={"bug": detail, "description": description})


def parse_bug_items(
    envelope: LLMReviewEnvelope,
) -> tuple[list[LLMFinding], list[StaticAssessment], list[str]]:
    findings: list[LLMFinding] = []
    assessments: list[StaticAssessment] = []
    errors: list[str] = []
    for raw in envelope.findings:
        try:
            findings.append(LLMBugFinding.model_validate(raw))
        except ValidationError as exc:
            errors.append(f"malformed finding dropped: {exc.errors()[0].get('msg', exc)}")
    for raw in envelope.static_assessments:
        try:
            assessments.append(StaticAssessment.model_validate(raw))
        except ValidationError:
            errors.append("malformed static assessment dropped")
    return findings, assessments, errors


class RankedSuspect(BaseModel):
    ref: str
    reason: str = ""

    @field_validator("ref", mode="before")
    @classmethod
    def _ref(cls, v: object) -> str:
        return _text(v).strip("[]`")

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, v: object) -> str:
        return _text(v)


class LLMLocalization(BaseModel):
    hypothesis: str = ""
    ranking: list[RankedSuspect] = Field(default_factory=list)

    @field_validator("hypothesis", mode="before")
    @classmethod
    def _hypothesis(cls, v: object) -> str:
        return _text(v)

    @field_validator("ranking", mode="before")
    @classmethod
    def _ranking(cls, v: object) -> list[object]:
        if v is None:
            return []
        items = v if isinstance(v, list) else [v]
        # A bare reference ("F3") is enough to rank; a malformed item must not lose the others.
        return [{"ref": x} if isinstance(x, str) else x for x in items if isinstance(x, str | dict)]
