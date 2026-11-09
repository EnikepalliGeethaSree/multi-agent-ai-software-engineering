"""Timing instrumentation on a real review (mock LLM): complete, consistent, and side-effect free."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.config import Settings
from marl_agents.core.schemas import AgentRequest
from marl_agents.core.timing import RunTimer, TimingBreakdown
from marl_agents.llm import MockLLMProvider
from marl_agents.reports import write_reports_timed
from tests.conftest import PLANTED, llm_json


class NoopTimer(RunTimer):
    """Records nothing: lets us compare a review with and without instrumentation."""

    @contextmanager
    def span(self, name: str, category: str) -> Iterator[None]:
        yield

    def record(self, name: str, category: str, start: float, end: float) -> None:
        return None


def _review(settings: Settings) -> tuple[CodeReviewAgent, object]:
    settings.review.mode = "full"
    llm = MockLLMProvider(default=llm_json())
    agent = CodeReviewAgent(llm, settings=settings, progress=lambda _m: None)
    return agent, agent.run(AgentRequest(repo_path=str(PLANTED)))


def test_breakdown_is_complete_and_consistent(settings: Settings) -> None:
    _, result = _review(settings)
    t = TimingBreakdown.model_validate(result.stats["timing"])  # type: ignore[attr-defined]
    units = result.stats["units_total"]  # type: ignore[attr-defined]
    assert units >= 1
    assert set(t.static_tools_sec) == {"ruff", "radon", "ast", "design", "secrets", "test_gap"}
    assert t.llm_calls == units  # one review call per unit, measured by the provider
    assert t.rag_queries == 2 * units  # similar code + guidelines per unit
    assert t.rag_index_sec > 0 and t.validation_sec > 0
    accounted = t.static_analysis_sec + t.rag_sec + t.llm_inference_sec + t.validation_sec
    assert accounted <= t.total_sec + 1e-3  # concurrency 1: components fit inside the total
    assert t.other_sec == pytest.approx(t.total_sec - accounted, abs=2e-3)
    assert t.concurrency == 1 and t.report_generation_sec is None
    for s in t.spans:
        assert 0 <= s.start_s <= s.end_s <= t.total_sec + 1e-3
        assert s.duration_s == pytest.approx(s.end_s - s.start_s, abs=2e-4)
    categories = {s.category for s in t.spans}
    assert {"ingestion_parsing", "static_analysis", "rag_index", "rag_retrieval",
            "llm_inference", "validation"} <= categories  # fmt: skip


def test_instrumentation_does_not_change_the_review(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, timed = _review(settings.model_copy(deep=True))
    monkeypatch.setattr("marl_agents.agents.code_review.agent.RunTimer", NoopTimer)
    _, untimed = _review(settings.model_copy(deep=True))

    def view(r: object) -> list[tuple[str, str, int, str, str]]:
        return [
            (f.id, f.file, f.start_line, f.severity.value, f.title)
            for f in r.findings  # type: ignore[attr-defined]
        ]

    assert view(timed) == view(untimed) and view(timed)
    assert timed.stats["timing"]["static_analysis_sec"] > 0  # type: ignore[attr-defined]
    assert untimed.stats["timing"]["static_analysis_sec"] == 0  # type: ignore[attr-defined]


def test_report_generation_time_extends_the_total(settings: Settings, tmp_path: Path) -> None:
    _, result = _review(settings)
    before = TimingBreakdown.model_validate(result.stats["timing"])  # type: ignore[attr-defined]
    write_reports_timed(result, tmp_path, ("json", "md"))  # type: ignore[arg-type]
    after = TimingBreakdown.model_validate(result.stats["timing"])  # type: ignore[attr-defined]
    assert after.report_generation_sec is not None and after.report_generation_sec > 0
    assert after.total_sec == pytest.approx(
        before.total_sec + after.report_generation_sec, abs=1e-3
    )
    assert (tmp_path / "review.json").is_file()


def test_static_only_review_has_no_llm_or_rag_time(settings: Settings) -> None:
    settings.review.mode = "static_only"
    result = CodeReviewAgent(None, settings=settings).run(AgentRequest(repo_path=str(PLANTED)))
    t = TimingBreakdown.model_validate(result.stats["timing"])
    assert t.llm_calls == 0 and t.llm_inference_sec == 0 and t.rag_sec == 0
    assert t.llm_rate_limit_wait_sec is None and t.static_analysis_sec > 0
