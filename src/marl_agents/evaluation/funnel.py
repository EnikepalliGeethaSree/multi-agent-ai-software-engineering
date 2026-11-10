"""Hallucination and pipeline funnel: what happens to the LLM's findings on their way to a report.

Stages, per model and configuration:

1. produced           finding items in the LLM's replies (after the reply itself parsed as JSON)
2. passed schema      items that validate against the finding schema (`LLMFinding`)
3. quote verified     the cited file exists, the lines exist, and the quoted code is found at those
                      lines (`unknown_file`, `line_out_of_range`, `no_evidence` and
                      `evidence_not_found` fail this check; `outside_scope` and claim checks are
                      counted apart, because they reject real code that is out of the unit)
4. actionable         after the actionability filter dropped vague findings
5. after dedupe       LLM findings that remain after merging duplicates (with static findings too)

Hallucination rate = findings that failed the quote check / findings that passed the schema.

The counters come from the agent's `stats` (saved per run in `metrics.pipeline` for the planted
benchmark and summed into `metrics.llm_funnel` for CodeReviewer runs). Runs made before a counter
existed show it as None, never as zero.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

QUOTE_FAILURES = ("unknown_file", "line_out_of_range", "no_evidence", "evidence_not_found")
FUNNEL_KEYS = (
    "llm_items_schema_invalid",
    "llm_findings_raw",
    "llm_findings_valid",
    "llm_findings_actionable",
    "vague_dropped",
    "llm_findings_after_dedupe",
)


class Funnel(BaseModel):
    produced: int | None
    passed_schema: int
    quote_failed: int
    quote_verified: int
    other_rejected: int  # outside the unit's scope, or failed an agent's claim check
    actionable: int | None
    after_dedupe: int | None
    hallucination_rate: float | None
    rejected_by_reason: dict[str, int]


def funnel_counts(stats_list: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Sum the funnel counters of several reviews (e.g. one per CodeReviewer sample)."""
    out: dict[str, Any] = {}
    reasons: dict[str, int] = {}
    for stats in stats_list:
        for key in FUNNEL_KEYS:
            value = stats.get(key)
            if value is None:
                continue
            out[key] = int(out.get(key, 0)) + int(value)
        for reason, n in (stats.get("llm_rejected_by_reason") or {}).items():
            reasons[reason] = reasons.get(reason, 0) + int(n)
    out["llm_rejected_by_reason"] = reasons
    return out


def funnel(stats: dict[str, Any]) -> Funnel | None:
    """The five stages from one review's (or a summed) counters; None without LLM findings data."""
    if stats.get("llm_findings_raw") is None:
        return None
    reasons = {k: int(v) for k, v in (stats.get("llm_rejected_by_reason") or {}).items()}
    passed = int(stats["llm_findings_raw"])
    invalid = stats.get("llm_items_schema_invalid")
    quote_failed = sum(reasons.get(r, 0) for r in QUOTE_FAILURES)
    other = sum(n for r, n in reasons.items() if r not in QUOTE_FAILURES)
    valid = int(stats.get("llm_findings_valid", passed - quote_failed - other))
    actionable = stats.get("llm_findings_actionable")
    if actionable is None and stats.get("vague_dropped") is not None:
        actionable = valid - int(stats["vague_dropped"])
    return Funnel(
        produced=None if invalid is None else passed + int(invalid),
        passed_schema=passed,
        quote_failed=quote_failed,
        quote_verified=passed - quote_failed,
        other_rejected=other,
        actionable=None if actionable is None else int(actionable),
        after_dedupe=stats.get("llm_findings_after_dedupe"),
        hallucination_rate=round(quote_failed / passed, 4) if passed else None,
        rejected_by_reason=reasons,
    )


def _run_counts(run: Any) -> dict[str, Any] | None:
    """Funnel counters of a saved run (planted: metrics.pipeline; CodeReviewer: llm_funnel)."""
    key = "pipeline" if run.kind == "planted" else "llm_funnel"
    counts = run.metrics.get(key)
    return dict(counts) if isinstance(counts, dict) else None


def funnel_report(runs: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    """Markdown with one table per provider + model (never mixed), and the rows as data.

    Every saved LLM run of the planted benchmark or CodeReviewer that recorded the counters becomes
    one row, labelled with its run folder. Mock runs are left out (they test the pipeline only).
    """
    rows: list[dict[str, Any]] = []
    for run in runs:
        cfg = run.configuration
        if cfg is None or not cfg.llm or run.provider in (None, "mock"):
            continue
        counts = _run_counts(run)
        f = funnel(counts) if counts else None
        if f is None:
            continue
        rows.append({"run": run.name, "benchmark": run.kind, "configuration": cfg.letter,
                     "provider": run.provider, "model": run.model, **f.model_dump()})  # fmt: skip
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((str(r["provider"]), str(r["model"])), []).append(r)

    def cell(v: Any) -> str:
        return "N/A" if v is None else str(v)

    lines = ["# Hallucination and pipeline funnel", "",
             "Stages: produced -> passed schema -> quote verified at the cited lines -> actionable "
             "-> after dedupe. Hallucination rate = failed quote check / passed schema. N/A: the "
             "run was made before that counter was recorded.", ""]  # fmt: skip
    for (provider, model), group in sorted(groups.items()):
        lines += [f"## {provider} / {model}", "",
                  "| Run | Benchmark | Config | Produced | Passed schema | Quote verified | "
                  "Other rejected | Actionable | After dedupe | Hallucination rate |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]  # fmt: skip
        for r in group:
            rate = "N/A" if r["hallucination_rate"] is None else f"{r['hallucination_rate']:.3f}"
            lines.append(
                f"| `{r['run']}` | {r['benchmark']} | {r['configuration']} | {cell(r['produced'])} "
                f"| {r['passed_schema']} | {r['quote_verified']} ({r['quote_failed']} failed) | "
                f"{r['other_rejected']} | {cell(r['actionable'])} | {cell(r['after_dedupe'])} | "
                f"{rate} |"
            )
        lines.append("")
    if not rows:
        lines.append("No saved LLM run recorded the funnel counters yet.")
    return "\n".join(lines) + "\n", rows
