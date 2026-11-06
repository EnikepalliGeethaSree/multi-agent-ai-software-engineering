"""One review's performance record: what the dashboard, the API and the benchmark all report.

Built only from what the run measured. A value that was not measured stays None and is shown as
"unavailable"; it is never replaced by 0 or by an estimate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from marl_agents.core.schemas import ReviewResult

RunType = Literal["cold", "warm"]
ReviewStatus = Literal["complete", "partial", "failed"]


class LLMCallTiming(BaseModel):
    label: str | None = None
    latency_s: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    ok: bool = True
    retry: bool = False
    error_kind: str | None = None


class PerformanceRecord(BaseModel):
    review_id: str
    file_name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: ReviewStatus = "complete"
    run_type: RunType = "cold"
    provider: str | None = None
    model: str | None = None

    file_size_kb: float | None = None
    lines_of_code: int | None = None
    files_reviewed: int | None = None

    input_tokens: int | None = Field(
        default=None, description="As reported by the provider; None when it reported nothing."
    )
    output_tokens: int | None = None
    thinking_tokens: int | None = None

    review_units: int | None = None
    llm_calls: int | None = None
    llm_failed_calls: int | None = None
    llm_calls_detail: list[LLMCallTiming] = Field(default_factory=list)

    file_ingestion_sec: float | None = None
    parsing_sec: float | None = None
    ast_call_graph_sec: float | None = None
    static_analysis_sec: float | None = None
    rag_retrieval_sec: float | None = None
    rag_index_sec: float | None = None
    prompt_construction_sec: float | None = None
    llm_inference_sec: float | None = None
    llm_quota_wait_sec: float | None = None
    evidence_validation_sec: float | None = None
    dedup_severity_sec: float | None = None
    validation_sec: float | None = None
    fix_generation_sec: float | None = None
    classifier_sec: float | None = None
    report_generation_sec: float | None = None
    total_sec: float | None = None
    failed_stages: list[str] = Field(default_factory=list)

    findings: int | None = None
    failed_units: int | None = None
    skipped_units: int | None = Field(
        default=None, description="Units not sent to the LLM (quota reached, or classifier gate)."
    )
    units_from_cache: int | None = None
    units_deduplicated: int | None = None
    classifier_skipped_units: int | None = None
    message: str | None = None
    resets_at: str | None = None

    @property
    def llm_durations(self) -> list[float]:
        return [c.latency_s for c in self.llm_calls_detail if c.latency_s is not None]


_STAGES = (
    "file_ingestion_sec",
    "parsing_sec",
    "ast_call_graph_sec",
    "static_analysis_sec",
    "rag_retrieval_sec",
    "rag_index_sec",
    "prompt_construction_sec",
    "llm_inference_sec",
    "evidence_validation_sec",
    "dedup_severity_sec",
    "validation_sec",
    "fix_generation_sec",
    "classifier_sec",
    "report_generation_sec",
    "total_sec",
)


def from_stats(
    stats: dict[str, Any],
    review_id: str,
    file_name: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    findings: int | None = None,
    message: str | None = None,
) -> PerformanceRecord:
    """Build the record from `ReviewResult.stats`; keys an older review lacks stay None."""
    timing = stats.get("timing")
    t: dict[str, Any] = timing if isinstance(timing, dict) else {}
    usage = stats.get("llm_usage")
    u: dict[str, Any] = usage if isinstance(usage, dict) else {}
    reported = bool(u) and int(u.get("calls", 0)) > int(u.get("calls_without_token_usage", 0))
    quota = stats.get("quota")
    q: dict[str, Any] = quota if isinstance(quota, dict) else {}
    classifier = stats.get("classifier")
    c: dict[str, Any] = classifier if isinstance(classifier, dict) else {}
    size = stats.get("bytes_reviewed")
    stages = {name: t.get(name) for name in _STAGES}
    # A stage that never ran was not measured: it is unavailable, not zero seconds.
    if stats.get("llm_enabled") is False:
        stages["llm_inference_sec"] = None
    if stats.get("rag_enabled") is False:
        stages["rag_retrieval_sec"] = stages["rag_index_sec"] = None
    return PerformanceRecord(
        review_id=review_id,
        file_name=file_name,
        status=stats.get("review_status", "complete"),
        run_type=stats.get("run_type", "cold"),
        provider=provider,
        model=model,
        file_size_kb=round(size / 1024, 2) if isinstance(size, int | float) else None,
        lines_of_code=stats.get("lines_reviewed"),
        files_reviewed=stats.get("files_reviewed"),
        input_tokens=u.get("input_tokens") if reported else None,
        output_tokens=u.get("output_tokens") if reported else None,
        thinking_tokens=u.get("thinking_tokens") if reported else None,
        review_units=stats.get("units_total"),
        llm_calls=(u.get("calls", 0) + u.get("failed_calls", 0)) if u else None,
        llm_failed_calls=u.get("failed_calls") if u else None,
        llm_calls_detail=[LLMCallTiming.model_validate(x) for x in stats.get("llm_calls", [])],
        llm_quota_wait_sec=t.get("llm_rate_limit_wait_sec"),
        failed_stages=list(t.get("failed_stages") or []),
        findings=findings if findings is not None else stats.get("final_findings"),
        failed_units=stats.get("units_failed"),
        skipped_units=stats.get("units_skipped"),
        units_from_cache=stats.get("units_from_cache"),
        units_deduplicated=stats.get("units_deduplicated"),
        classifier_skipped_units=c.get("skipped"),
        message=message or q.get("message"),
        resets_at=q.get("resets_at"),
        **stages,
    )


def from_result(result: ReviewResult, review_id: str, file_name: str) -> PerformanceRecord:
    meta = result.metadata
    llm_used = meta.provider != "none"
    return from_stats(
        result.stats,
        review_id,
        file_name,
        provider=meta.provider if llm_used else None,
        model=meta.model if llm_used else None,
        findings=len(result.findings),
    )
