"""Minimal LangGraph orchestrator: Code Review and Bug Detection in parallel, then the aggregator.

    START --> code_review   --+
          \\-> bug_detection --+--> aggregate --> END

The nodes are the agents' existing wrappers (`make_code_review_node`, `make_bug_detection_node`), so
the agents stay plain Python and runnable on their own; LangGraph only schedules them. Each node
writes its own state key, so the parallel branches never conflict. LangGraph is imported lazily
(`llm` extra).

The result is an ordinary `ReviewResult` (agent "orchestrator"), so every report renderer works on
it; `stats["aggregation"]` holds the per-agent counts and `stats["agents"]` each agent's own stats.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

from marl_agents.agents.bug_detection import BugDetectionAgent, make_bug_detection_node
from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.agents.code_review.node import make_code_review_node
from marl_agents.core.schemas import AgentRequest, ReviewResult, RunMetadata
from marl_agents.orchestration.aggregator import aggregate


class OrchestratorState(TypedDict, total=False):
    request: AgentRequest
    code_review_result: ReviewResult
    bug_detection_result: ReviewResult
    result: ReviewResult


def _aggregate_node(state: OrchestratorState) -> dict[str, Any]:
    cr, bd = state["code_review_result"], state["bug_detection_result"]
    agg = aggregate({"code_review": cr.findings, "bug_detection": bd.findings})
    findings = []
    for item in agg.findings:
        note = f"raised by: {', '.join(item.raised_by)}"
        findings.append(item.finding.model_copy(update={"notes": [*item.finding.notes, note]}))
    meta = cr.metadata
    result = ReviewResult(
        agent="orchestrator",
        findings=findings,
        rejected_findings=cr.rejected_findings + bd.rejected_findings,
        errors=[
            *(f"[code_review] {e}" for e in cr.errors),
            *(f"[bug_detection] {e}" for e in bd.errors),
        ],
        metadata=RunMetadata(
            agent="orchestrator",
            provider=meta.provider,
            model=meta.model,
            temperature=meta.temperature,
            prompt_versions={
                **{f"code_review.{k}": v for k, v in meta.prompt_versions.items()},
                **{f"bug_detection.{k}": v for k, v in bd.metadata.prompt_versions.items()},
            },
            rag_enabled=meta.rag_enabled,
            started_at=min(meta.started_at, bd.metadata.started_at),
            finished_at=datetime.now(UTC),
        ),
        files_analyzed=max(cr.files_analyzed, bd.files_analyzed),
        lines_analyzed=max(cr.lines_analyzed, bd.lines_analyzed),
        stats={
            "aggregation": agg.summary.model_dump(),
            "raised_by": {
                f.id: item.raised_by for f, item in zip(findings, agg.findings, strict=True)
            },
            "agents": {"code_review": cr.stats, "bug_detection": bd.stats},
            # A partial agent makes the whole result partial; it never looks complete.
            "review_status": (
                "partial"
                if "partial" in (cr.stats.get("review_status"), bd.stats.get("review_status"))
                else "complete"
            ),
            "units_failed": int(cr.stats.get("units_failed", 0) or 0)
            + int(bd.stats.get("units_failed", 0) or 0),
            "units_not_attempted": int(cr.stats.get("units_not_attempted", 0) or 0)
            + int(bd.stats.get("units_not_attempted", 0) or 0),
            **({"quota": q} if (q := cr.stats.get("quota") or bd.stats.get("quota")) else {}),
        },
    )
    return {"result": result}


def build_graph(code_review: CodeReviewAgent, bug_detection: BugDetectionAgent) -> Any:
    """Compiled LangGraph graph; `graph.invoke({"request": request})["result"]`."""
    from langgraph.graph import END, START, StateGraph

    graph: Any = StateGraph(OrchestratorState)  # node functions take plain dict states
    graph.add_node("code_review", make_code_review_node(code_review))
    graph.add_node("bug_detection", make_bug_detection_node(bug_detection))
    graph.add_node("aggregate", _aggregate_node)
    graph.add_edge(START, "code_review")
    graph.add_edge(START, "bug_detection")
    graph.add_edge(["code_review", "bug_detection"], "aggregate")  # waits for both
    graph.add_edge("aggregate", END)
    return graph.compile()


def run_orchestrated(
    code_review: CodeReviewAgent, bug_detection: BugDetectionAgent, request: AgentRequest
) -> ReviewResult:
    result: ReviewResult = build_graph(code_review, bug_detection).invoke({"request": request})[
        "result"
    ]
    return result
