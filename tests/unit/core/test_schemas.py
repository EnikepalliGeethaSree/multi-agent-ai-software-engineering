import pytest
from pydantic import ValidationError

from marl_agents.core.schemas import (
    AgentRequest,
    AgentResult,
    Category,
    Finding,
    RunMetadata,
    Severity,
)


def make_finding(**overrides: object) -> Finding:
    data: dict[str, object] = {
        "id": "CR-001",
        "file": "app/auth.py",
        "start_line": 42,
        "end_line": 47,
        "category": "security",
        "severity": "high",
        "title": "Missing authorization check",
        "description": "delete_user does not verify the caller is an admin.",
        "evidence": ["def delete_user(user_id):"],
        "confidence": 0.8,
    }
    data.update(overrides)
    return Finding.model_validate(data)


def test_finding_parses_enums() -> None:
    f = make_finding()
    assert f.category is Category.SECURITY
    assert f.severity is Severity.HIGH


def test_finding_rejects_inverted_line_range() -> None:
    with pytest.raises(ValidationError):
        make_finding(start_line=50, end_line=40)


@pytest.mark.parametrize("bad", [{"confidence": 1.5}, {"severity": "urgent"}, {"start_line": 0}])
def test_finding_rejects_invalid_values(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_finding(**bad)


def test_severity_rank_orders_levels() -> None:
    ordered = sorted(Severity, key=lambda s: s.rank, reverse=True)
    assert ordered == [
        Severity.CRITICAL,
        Severity.HIGH,
        Severity.MEDIUM,
        Severity.LOW,
        Severity.INFO,
    ]


def test_agent_request_requires_exactly_one_input() -> None:
    AgentRequest(snippet="x = 1")
    AgentRequest(repo_path="some/repo")
    with pytest.raises(ValidationError):
        AgentRequest()
    with pytest.raises(ValidationError):
        AgentRequest(snippet="x = 1", repo_path="some/repo")


def test_agent_result_counts_by_severity() -> None:
    result = AgentResult(
        agent="code_review",
        findings=[make_finding(), make_finding(id="CR-002", severity="low")],
        metadata=RunMetadata(agent="code_review", provider="mock"),
    )
    counts = result.by_severity()
    assert counts[Severity.HIGH] == 1
    assert counts[Severity.LOW] == 1
    assert counts[Severity.CRITICAL] == 0
