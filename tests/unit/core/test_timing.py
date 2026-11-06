"""Timing utilities: spans, aggregation, breakdown arithmetic, serialization (hand-computed)."""

from __future__ import annotations

import threading

import pytest

from marl_agents.core.timing import (
    LLM,
    RAG_INDEX,
    RAG_RETRIEVAL,
    REPORT,
    STATIC,
    VALIDATION,
    RunTimer,
    TimingBreakdown,
    describe,
)


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


def test_span_records_start_end_duration_relative_to_origin() -> None:
    clock = FakeClock()
    timer = RunTimer(clock)
    clock.advance(1.0)
    with timer.span("ruff", STATIC):
        clock.advance(0.25)
    [s] = timer.spans
    assert (s.name, s.category, s.start_s, s.end_s, s.duration_s) == (
        "ruff",
        STATIC,
        1.0,
        1.25,
        0.25,
    )
    assert timer.elapsed() == pytest.approx(1.25)


def test_span_is_recorded_even_when_the_block_raises() -> None:
    clock = FakeClock()
    timer = RunTimer(clock)
    with pytest.raises(ValueError), timer.span("mypy", STATIC):
        clock.advance(2.0)
        raise ValueError
    assert timer.total(STATIC) == pytest.approx(2.0)


def test_totals_counts_and_by_name() -> None:
    clock = FakeClock()
    timer = RunTimer(clock)
    for name, d in (("ruff", 0.5), ("mypy", 3.0), ("ruff", 0.25)):
        with timer.span(name, STATIC):
            clock.advance(d)
    assert timer.total(STATIC) == pytest.approx(3.75)
    assert timer.count(STATIC) == 3
    assert timer.by_name(STATIC) == {"ruff": pytest.approx(0.75), "mypy": pytest.approx(3.0)}


def test_recording_is_thread_safe() -> None:
    timer = RunTimer()

    def work() -> None:
        for _ in range(200):
            timer.record("q", RAG_RETRIEVAL, timer.origin, timer.origin + 0.001)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert timer.count(RAG_RETRIEVAL) == 1600


def test_merged_adds_external_spans_without_changing_the_timer() -> None:
    clock = FakeClock()
    timer = RunTimer(clock)
    merged = timer.merged([("api_call", LLM, 100.5, 102.0)])
    assert timer.count(LLM) == 0 and merged.count(LLM) == 1
    assert merged.spans[0].start_s == pytest.approx(0.5) and merged.total(LLM) == pytest.approx(1.5)


def _timer_with(durations: dict[str, float]) -> RunTimer:
    clock = FakeClock()
    timer = RunTimer(clock)
    for category, d in durations.items():
        with timer.span(category, category):
            clock.advance(d)
    return timer


def test_breakdown_components_and_other_hand_computed() -> None:
    # static 2, index 0.25, retrieval 0.5, llm 5, validation 0.75 = 8.5 of a 10 s total -> other 1.5
    timer = _timer_with(
        {STATIC: 2.0, RAG_INDEX: 0.25, RAG_RETRIEVAL: 0.5, LLM: 5.0, VALIDATION: 0.75}
    )
    b = TimingBreakdown.from_timer(timer, total_sec=10.0, rate_limit_wait_sec=0.4)
    assert (b.static_analysis_sec, b.rag_sec, b.llm_inference_sec, b.validation_sec) == (
        2.0, 0.75, 5.0, 0.75,
    )  # fmt: skip
    assert b.other_sec == pytest.approx(1.5) and b.report_generation_sec is None
    assert b.llm_calls == 1 and b.rag_queries == 1 and b.llm_rate_limit_wait_sec == 0.4
    # reports written afterwards extend the total; other stays 1.5
    r = b.with_report(0.5)
    assert (r.total_sec, r.report_generation_sec, r.other_sec) == (10.5, 0.5, 1.5)


def test_other_is_floored_at_zero_for_concurrent_runs() -> None:
    timer = _timer_with({LLM: 9.0})  # e.g. 3 units x 3 s on 3 workers inside a 4 s total
    b = TimingBreakdown.from_timer(timer, total_sec=4.0, concurrency=3)
    assert b.other_sec == 0.0 and b.concurrency == 3


def test_report_category_is_used_when_no_explicit_report_time() -> None:
    b = TimingBreakdown.from_timer(_timer_with({REPORT: 0.2}), total_sec=1.0)
    assert b.report_generation_sec == pytest.approx(0.2)


def test_breakdown_serialization_round_trip() -> None:
    b = TimingBreakdown.from_timer(_timer_with({STATIC: 1.0, LLM: 2.0}), total_sec=3.5)
    again = TimingBreakdown.model_validate_json(b.model_dump_json())
    assert again == b and len(again.spans) == 2
    summary = b.summary()
    assert "spans" not in summary and summary["rag_sec"] == 0.0 and summary["total_sec"] == 3.5


def test_describe_hand_computed() -> None:
    d = describe([1.0, 2.0, 3.0, 10.0, None])
    assert (d.n, d.mean, d.median, d.min, d.max) == (4, 4.0, 2.5, 1.0, 10.0)
    assert describe([]).mean is None and describe([None]).n == 0
