"""Stage-wise timing, multi-chunk aggregation, and "unavailable is not zero"."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.config import Settings
from marl_agents.core.performance import from_result, from_stats
from marl_agents.core.schemas import AgentRequest
from marl_agents.core.timing import (
    CALL_GRAPH,
    PARSING,
    PROMPT,
    RunTimer,
    TimingBreakdown,
    percentile,
)
from marl_agents.llm import LLMResponse, MockLLMProvider
from marl_agents.llm.base import CallAttempt, Usage
from marl_agents.reports import write_reports_timed

CODE = "\n\n".join(
    f"def f{i}(x):\n" + "\n".join(f"    a{n} = x + {n}" for n in range(120)) + "\n    return a0"
    for i in range(3)
)


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_percentile_matches_hand_computed_values() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(xs, 50) == 3.0
    assert percentile(xs, 95) == pytest.approx(4.8)  # 4 + 0.8 x (5 - 4)
    assert percentile([7.0], 95) == 7.0
    assert percentile([], 95) is None


def test_failed_stage_is_timed_and_marked() -> None:
    clock = Clock()
    timer = RunTimer(clock)
    with pytest.raises(ValueError), timer.span("mypy", "static_analysis"):
        clock.t += 2
        raise ValueError("tool crashed")
    b = TimingBreakdown.from_timer(timer, total_sec=2.0)
    assert b.static_analysis_sec == 2.0 and b.failed_stages == ["mypy"]


def test_new_stages_split_ingestion_and_are_none_when_they_did_not_run() -> None:
    timer = RunTimer(Clock())
    timer.record("parse_python", PARSING, 100, 101)
    timer.record("symbol_tables", CALL_GRAPH, 101, 103)
    timer.record("prompt_render", PROMPT, 103, 103.5)
    b = TimingBreakdown.from_timer(timer, total_sec=4.0)
    assert (b.parsing_sec, b.ast_call_graph_sec, b.prompt_construction_sec) == (1.0, 2.0, 0.5)
    assert b.ingestion_parsing_sec == 3.0
    assert b.fix_generation_sec is None and b.classifier_sec is None


def test_reviews_saved_before_the_new_stages_still_load() -> None:
    old = {
        "total_sec": 1.0,
        "static_analysis_sec": 0.1,
        "rag_index_sec": 0.0,
        "rag_retrieval_sec": 0.0,
        "llm_inference_sec": 0.0,
        "validation_sec": 0.0,
        "other_sec": 0.9,
    }
    assert TimingBreakdown.model_validate(old).parsing_sec is None
    record = from_stats({"timing": old}, "id", "x.py")
    assert record.total_sec == 1.0 and record.parsing_sec is None and record.input_tokens is None


def test_multi_chunk_review_aggregates_every_call(settings: Settings) -> None:
    settings.rag.enabled = False
    llm = MockLLMProvider()
    result = CodeReviewAgent(llm, settings=settings, analyzers=[]).run(AgentRequest(snippet=CODE))
    record = from_result(result, "r1", "snippet.py")
    assert record.review_units == 3 == record.llm_calls == len(record.llm_calls_detail)
    assert record.llm_inference_sec == pytest.approx(sum(record.llm_durations), abs=1e-3)
    assert {c.label for c in record.llm_calls_detail} == {
        c["label"] for c in result.stats["llm_calls"]
    }


def test_all_requested_stages_are_measured(settings: Settings) -> None:
    settings.review.suggest_fixes = False
    agent = CodeReviewAgent(MockLLMProvider(), settings=settings)
    t = agent.run(AgentRequest(snippet=CODE)).stats["timing"]
    for stage in (
        "file_ingestion_sec",
        "parsing_sec",
        "ast_call_graph_sec",
        "static_analysis_sec",
        "rag_retrieval_sec",
        "prompt_construction_sec",
        "llm_inference_sec",
        "evidence_validation_sec",
        "dedup_severity_sec",
        "total_sec",
    ):
        assert t[stage] is not None, stage


def test_record_describes_the_file(settings: Settings, tmp_path: Path) -> None:
    settings.rag.enabled = False
    agent = CodeReviewAgent(MockLLMProvider(), settings=settings, analyzers=[])
    result = agent.run(AgentRequest(snippet=CODE, snippet_filename="big.py"))
    written = write_reports_timed(result, tmp_path, ("json",))
    assert written
    saved = json.loads((tmp_path / "performance.json").read_text(encoding="utf-8"))
    assert saved["file_name"] == "big.py"
    assert saved["lines_of_code"] == result.lines_analyzed
    assert saved["file_size_kb"] == pytest.approx(len(CODE.encode()) / 1024, abs=0.02)
    assert saved["report_generation_sec"] is not None
    assert saved["provider"] == "mock" and saved["status"] == "complete"
    assert saved["run_type"] == "cold"


def test_unavailable_values_stay_unavailable(settings: Settings) -> None:
    settings.review.mode = "static_only"
    settings.rag.enabled = False
    result = CodeReviewAgent(None, settings=settings, analyzers=[]).run(AgentRequest(snippet=CODE))
    r = from_result(result, "r", "x.py")
    assert r.llm_inference_sec is None and r.rag_retrieval_sec is None
    assert r.input_tokens is None and r.provider is None


def test_tokens_stay_unavailable_when_the_provider_reports_none(settings: Settings) -> None:
    settings.rag.enabled = False
    result = CodeReviewAgent(MockLLMProvider(), settings=settings, analyzers=[]).run(
        AgentRequest(snippet=CODE)
    )
    assert from_result(result, "r", "x.py").input_tokens is None


def test_reported_tokens_are_summed_over_chunks() -> None:
    usage = Usage()
    for tokens in (10, 20):
        usage.record(LLMResponse(text="", model="m", input_tokens=tokens, output_tokens=1))
    record = from_stats({"llm_usage": usage.snapshot()}, "r", "x.py")
    assert (record.input_tokens, record.output_tokens, record.llm_calls) == (30, 2, 2)


def test_failed_calls_are_counted_in_llm_calls() -> None:
    usage = Usage()
    usage.record(LLMResponse(text="", model="m", input_tokens=1, output_tokens=1))
    usage.record_failures([CallAttempt(started_at=0, latency_s=2.5, error_kind="quota")])
    record = from_stats({"llm_usage": usage.snapshot()}, "r", "x.py")
    assert record.llm_calls == 2 and record.llm_failed_calls == 1


def test_timing_survives_a_run_that_crashes(settings: Settings) -> None:
    from marl_agents.static_analysis.base import StaticAnalyzer

    class Broken(StaticAnalyzer):
        name = "broken"

        def analyze(self, repo, index, files, scope=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    agent = CodeReviewAgent(MockLLMProvider(), settings=settings, analyzers=[Broken()])
    with pytest.raises(RuntimeError):
        agent.run(AgentRequest(snippet=CODE))
    stats = agent.partial_stats()
    record = from_stats(stats, "r", "x.py", message="boom")
    assert record.status == "failed" and record.failed_stages == ["broken"]
    assert record.parsing_sec is not None
