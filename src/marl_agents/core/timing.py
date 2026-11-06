"""Lightweight timing instrumentation for a review run (efficiency analysis).

Every measurement is a `Span` with a start, an end and a duration in seconds, measured with the
monotonic `time.perf_counter()` and stored relative to the run's origin. Spans are kept in memory
(a list append under a lock); nothing is logged or written in the critical path.

`TimingBreakdown` turns the spans of one run into the six reported components:

    total, static analysis, RAG (index + retrieval), LLM inference, validation, report generation

plus `other_sec` = total - sum(components) (ingestion/parsing, context assembly, waiting for the
LLM rate limiter, scheduling). It also carries finer stages for execution-time analysis (ingestion,
parsing, call graph, prompt construction, evidence validation, dedup, fix generation). These
break the six components and "other" down further and do not add to them. Components are sums of
spans: with concurrency > 1 the LLM and RAG
sums can exceed their share of the wall-clock total, so `other_sec` is floored at 0 and the
breakdown records the concurrency used. Timing benchmarks run with concurrency 1.
"""

from __future__ import annotations

import statistics
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

from pydantic import BaseModel, Field

# Span categories (the breakdown components). Names inside a category are free-form.
INGESTION = "ingestion_parsing"
PARSING = "parsing"
CALL_GRAPH = "ast_call_graph"
PROMPT = "prompt_construction"
CLASSIFIER = "classifier"
STATIC = "static_analysis"
RAG_INDEX = "rag_index"
RAG_RETRIEVAL = "rag_retrieval"
LLM = "llm_inference"
VALIDATION = "validation"
REPORT = "report_generation"
OTHER = "other"


class Span(BaseModel):
    name: str
    category: str
    start_s: float = Field(description="Seconds since the run's origin.")
    end_s: float
    duration_s: float
    failed: bool = False


class RunTimer:
    """Collects spans for one run. Thread-safe; overhead is one perf_counter pair per span."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self.origin = clock()
        self._spans: list[Span] = []
        self._lock = threading.Lock()

    def now(self) -> float:
        return self._clock()

    def elapsed(self) -> float:
        return self._clock() - self.origin

    def record(
        self, name: str, category: str, start: float, end: float, failed: bool = False
    ) -> None:
        """Add a span measured elsewhere with the same clock (absolute perf_counter values)."""
        span = Span(
            name=name,
            category=category,
            start_s=start - self.origin,
            end_s=end - self.origin,
            duration_s=max(0.0, end - start),
            failed=failed,
        )
        with self._lock:
            self._spans.append(span)

    @contextmanager
    def span(self, name: str, category: str) -> Iterator[None]:
        start = self._clock()
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:  # a stage that raises is still timed, and marked
            self.record(name, category, start, self._clock(), failed)

    def merged(self, extra: Iterable[tuple[str, str, float, float]]) -> RunTimer:
        """A copy with extra (name, category, start, end) spans added; this timer is unchanged."""
        out = RunTimer(self._clock)
        out.origin = self.origin
        out._spans = self.spans
        for name, category, start, end in extra:
            out.record(name, category, start, end)
        return out

    @property
    def spans(self) -> list[Span]:
        with self._lock:
            return list(self._spans)

    def total(self, category: str) -> float:
        return sum(s.duration_s for s in self.spans if s.category == category)

    def count(self, category: str) -> int:
        return sum(1 for s in self.spans if s.category == category)

    def by_name(self, category: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for s in self.spans:
            if s.category == category:
                out[s.name] = out.get(s.name, 0.0) + s.duration_s
        return out


class TimingBreakdown(BaseModel):
    """Where one review spent its time. Seconds; components need not sum to the total."""

    total_sec: float = Field(description="Request start -> final result (and reports, if written).")
    static_analysis_sec: float
    static_tools_sec: dict[str, float] = Field(default_factory=dict)
    rag_index_sec: float = Field(description="Chunking + embedding + vector-store insert.")
    rag_retrieval_sec: float = Field(description="Query embedding + vector search, all queries.")
    rag_queries: int = 0
    llm_inference_sec: float = Field(description="Sum of request->response time of LLM calls.")
    llm_calls: int = 0
    llm_rate_limit_wait_sec: float | None = Field(
        default=None,
        description="Time spent waiting for the provider's quota, summed over concurrent callers "
        "(can exceed the elapsed time when concurrency > 1). Part of 'other'.",
    )
    validation_sec: float = Field(
        description="JSON schema parsing, evidence validation, actionability, dedup, severity."
    )
    report_generation_sec: float | None = Field(
        default=None, description="None when the run did not write reports."
    )
    ingestion_parsing_sec: float = 0.0
    other_sec: float = Field(description="total - sum(components), floored at 0.")
    concurrency: int = 1
    # Finer stages (all default so reviews saved earlier still load). None = stage did not run.
    file_ingestion_sec: float | None = None
    parsing_sec: float | None = None
    ast_call_graph_sec: float | None = None
    prompt_construction_sec: float | None = Field(
        default=None, description="Context assembly and prompt rendering, excluding RAG queries."
    )
    evidence_validation_sec: float | None = None
    dedup_severity_sec: float | None = None
    fix_generation_sec: float | None = Field(
        default=None, description="Includes the LLM calls that wrote the fixes."
    )
    classifier_sec: float | None = None
    failed_stages: list[str] = Field(default_factory=list)
    spans: list[Span] = Field(default_factory=list)

    @property
    def rag_sec(self) -> float:
        return self.rag_index_sec + self.rag_retrieval_sec

    def components(self) -> dict[str, float | None]:
        return {
            "static_analysis_sec": self.static_analysis_sec,
            "rag_sec": round(self.rag_sec, 4),
            "llm_inference_sec": self.llm_inference_sec,
            "validation_sec": self.validation_sec,
            "report_generation_sec": self.report_generation_sec,
        }

    def summary(self) -> dict[str, float | int | None]:
        """Compact form without spans (benchmark predictions, dashboard)."""
        data = self.model_dump(exclude={"spans", "static_tools_sec"})
        data["rag_sec"] = round(self.rag_sec, 4)
        return data

    @classmethod
    def from_timer(
        cls,
        timer: RunTimer,
        total_sec: float,
        concurrency: int = 1,
        rate_limit_wait_sec: float | None = None,
        report_sec: float | None = None,
    ) -> TimingBreakdown:
        def r(x: float) -> float:
            return round(x, 4)

        static = timer.total(STATIC)
        rag_index = timer.total(RAG_INDEX)
        rag_retrieval = timer.total(RAG_RETRIEVAL)
        llm = timer.total(LLM)
        validation = timer.total(VALIDATION)
        report = report_sec if report_sec is not None else (timer.total(REPORT) or None)
        accounted = static + rag_index + rag_retrieval + llm + validation + (report or 0.0)
        by_validation = timer.by_name(VALIDATION)
        evidence = sum(
            by_validation.get(n, 0.0)
            for n in ("evidence_validation", "static_validation", "impact_validation")
        )
        fixes = timer.by_name(OTHER).get("fix_generation")

        def stage(category: str) -> float | None:
            return r(timer.total(category)) if timer.count(category) else None

        return cls(
            total_sec=r(total_sec),
            static_analysis_sec=r(static),
            static_tools_sec={k: r(v) for k, v in timer.by_name(STATIC).items()},
            rag_index_sec=r(rag_index),
            rag_retrieval_sec=r(rag_retrieval),
            rag_queries=timer.count(RAG_RETRIEVAL),
            llm_inference_sec=r(llm),
            llm_calls=timer.count(LLM),
            llm_rate_limit_wait_sec=None if rate_limit_wait_sec is None else r(rate_limit_wait_sec),
            validation_sec=r(validation),
            report_generation_sec=None if report is None else r(report),
            ingestion_parsing_sec=r(
                timer.total(INGESTION) + timer.total(PARSING) + timer.total(CALL_GRAPH)
            ),
            other_sec=r(max(0.0, total_sec - accounted)),
            concurrency=concurrency,
            file_ingestion_sec=stage(INGESTION),
            parsing_sec=stage(PARSING),
            ast_call_graph_sec=stage(CALL_GRAPH),
            prompt_construction_sec=stage(PROMPT),
            evidence_validation_sec=r(evidence) if evidence else None,
            dedup_severity_sec=(
                r(by_validation["dedup_severity_confidence"])
                if "dedup_severity_confidence" in by_validation
                else None
            ),
            fix_generation_sec=r(fixes) if fixes is not None else None,
            classifier_sec=stage(CLASSIFIER),
            failed_stages=sorted({s.name for s in timer.spans if s.failed}),
            spans=[
                s.model_copy(
                    update={
                        "start_s": r(s.start_s),
                        "end_s": r(s.end_s),
                        "duration_s": r(s.duration_s),
                    }
                )
                for s in timer.spans
            ],
        )

    def with_report(self, report_sec: float) -> TimingBreakdown:
        """Add the report-generation step that followed the review (it extends the total)."""
        total = self.total_sec + report_sec
        accounted = (
            self.static_analysis_sec
            + self.rag_sec
            + self.llm_inference_sec
            + self.validation_sec
            + report_sec
        )
        return self.model_copy(
            update={
                "total_sec": round(total, 4),
                "report_generation_sec": round(report_sec, 4),
                "other_sec": round(max(0.0, total - accounted), 4),
            }
        )


class Distribution(BaseModel):
    n: int
    mean: float | None
    median: float | None
    min: float | None
    max: float | None


def percentile(values: Iterable[float], q: float) -> float | None:
    """Linear-interpolation percentile (the numpy default); `q` in 0-100. None if no values."""
    xs = sorted(float(v) for v in values)
    if not xs:
        return None
    position = (len(xs) - 1) * q / 100
    low = int(position)
    high = min(low + 1, len(xs) - 1)
    return xs[low] + (xs[high] - xs[low]) * (position - low)


def describe(values: Iterable[float | None]) -> Distribution:
    """Mean / median / min / max over repeated measurements (None values are skipped)."""
    xs = [float(v) for v in values if v is not None]
    if not xs:
        return Distribution(n=0, mean=None, median=None, min=None, max=None)
    return Distribution(
        n=len(xs),
        mean=round(statistics.fmean(xs), 4),
        median=round(statistics.median(xs), 4),
        min=round(min(xs), 4),
        max=round(max(xs), 4),
    )
