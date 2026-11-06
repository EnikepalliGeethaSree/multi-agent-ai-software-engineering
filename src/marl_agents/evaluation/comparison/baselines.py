"""Method-baseline tables: RAG vs random retrieval, risk vs size/random, efficiency, usefulness."""

from __future__ import annotations

import csv
from typing import Any

from marl_agents.evaluation.comparison.common import (
    CMD,
    LLM_CONFIG,
    compare,
    config_row,
    fmt,
    not_run_row,
    provider_badge,
)
from marl_agents.evaluation.comparison.detection import planted_chosen
from marl_agents.evaluation.comparison.models import Column, ComparisonTable, FairnessCheck, Row
from marl_agents.evaluation.configurations import ORDER
from marl_agents.evaluation.metrics.efficiency import mean_sd, overhead_pct
from marl_agents.evaluation.runs import SavedRun

# ---- RAG retrieval -------------------------------------------------------------------------------

RETRIEVAL_COLUMNS = [
    Column(key="recall_at_1", label="Recall@1"),
    Column(key="recall_at_5", label="Recall@5"),
    Column(key="recall_at_10", label="Recall@10", metric="recall_at_10"),
    Column(key="hit_at_10", label="Hit@10"),
    Column(key="mrr", label="MRR", metric="mrr"),
    Column(key="ndcg_at_10", label="nDCG@10"),
]


def retrieval_table(runs: list[SavedRun]) -> ComparisonTable:
    rr = [r for r in runs if r.kind == "retrieval"]
    base = ComparisonTable(
        id="retrieval",
        section="4. RAG retrieval",
        title="RAG retrieval vs random retrieval",
        about="Self-supervised from the AST call graph: for each function, the relevant chunks "
        "are those containing the functions it calls; the query is the function's own chunk.",
        columns=RETRIEVAL_COLUMNS,
        rows=[],
    )
    if not rr:
        base.rows = [
            Row(
                label="Random baseline", status="not_run", how_to_run=f"{CMD} retrieval --path src"
            ),
            Row(label="RAG", status="not_run", how_to_run=f"{CMD} retrieval --path src"),
        ]
        return base
    run = rr[-1]
    m = run.metrics
    methods = [k for k, v in m.items() if isinstance(v, dict) and "recall@10" in v]
    order = ["random_baseline"] + [k for k in methods if k != "random_baseline"]
    for name in order:
        if name not in m:
            continue
        label = "Random baseline" if name == "random_baseline" else f"RAG ({name} embedder)"
        base.rows.append(
            Row(
                label=label,
                values={
                    "recall_at_1": m[name].get("recall@1"),
                    "recall_at_5": m[name].get("recall@5"),
                    "recall_at_10": m[name].get("recall@10"),
                    "hit_at_10": m[name].get("hit@10"),
                    "mrr": m[name].get("mrr"),
                    "ndcg_at_10": m[name].get("ndcg@10"),
                },
                n=m.get("n_queries"),
                n_runs=1,
                run_ids=[run.name],
            )
        )
    embedders = [k for k in order if k != "random_baseline"]
    base.conditions = {
        "repository": m.get("repo"),
        "queries": m.get("n_queries"),
        "chunks": m.get("n_chunks"),
        "cut-offs evaluated (k)": m.get("ks", [1, 3, 5, 10]),
        "embedding model": ", ".join(embedders) or None,
        "review-time retrieval": f"top_k = {run.setting('rag', 'top_k')} similar chunks + "
        f"guideline_k = {run.setting('rag', 'guideline_k')} guideline chunks per review unit",
        "random seed": m.get("seed", 42),
    }
    rnd = m.get("random_baseline", {})
    for name in embedders:
        s = compare("Recall@10", f"RAG ({name})", m[name].get("recall@10"), "random",
                    rnd.get("recall@10"))  # fmt: skip
        if s:
            base.observations.append(s)
    base.badges = ["Complete", f"Embedder: {', '.join(embedders)}", "Retrieval quality only"]
    query_counts = ", ".join(str(r.metrics.get("n_queries")) for r in rr)
    base.notes = [
        "This measures whether retrieval finds a function's call-graph neighbours. It does not "
        "measure final review accuracy, and its effect on reviews needs Static + LLM vs "
        "Static + LLM + RAG on identical samples.",
        f"{len(rr)} retrieval runs are saved, on {query_counts} queries. The repository grew "
        "between them, so they are not comparable. This table shows the latest.",
        f"Recall@3 and the other Hit@k cut-offs are in run {run.name}.",
    ]
    return base


# ---- risk ranking --------------------------------------------------------------------------------

RISK_COLUMNS = [
    Column(key="roc_auc", label="ROC-AUC", metric="roc_auc"),
    Column(key="precision_at_top5", label="Precision@Top5%"),
    Column(key="precision_at_top10", label="Precision@Top10%", metric="precision_at_top10"),
    Column(key="precision_at_top25", label="Precision@Top25%"),
]
RISK_METHODS = [
    ("size_baseline", "Size only (changed lines)"),
    ("finding_score_baseline", "Finding score only (static findings)"),
    ("risk_v1_baseline", "Risk v1 (hand-set points)"),
    ("hunk_risk", "Risk model v2 (calibrated, shipped)"),
]


def risk_table(runs: list[SavedRun]) -> ComparisonTable:
    hr = [r for r in runs if r.kind == "hunkrisk" and r.split == "test"]
    table = ComparisonTable(
        id="risk",
        section="5. Risk ranking",
        title="Risk-based hunk ranking vs baselines",
        about="CodeReviewer cls hunks (test split, Python): does ranking by risk put the hunks a "
        "human commented on first?",
        columns=RISK_COLUMNS,
        rows=[],
    )
    if not hr:
        table.rows = [Row(label="Risk model", status="not_run",
                          how_to_run=f"{CMD} hunkrisk --split test")]  # fmt: skip
        return table
    run = hr[-1]
    m = run.metrics
    n = m.get("n_evaluated")
    rnd = m.get("random_baseline", {"precision_at_top": m.get("base_rate"), "auc": 0.5})
    table.rows.append(
        Row(
            label="Random (expected value)",
            values={"roc_auc": rnd.get("auc"), "precision_at_top10": rnd.get("precision_at_top")},
            n=n,
            notes=["exact expectation of a random order: precision = base rate, AUC = 0.5"],
            n_runs=1,
            run_ids=[run.name],
        )
    )
    for key, label in RISK_METHODS:
        if key not in m.get("auc", {}):
            continue
        table.rows.append(
            Row(
                label=label,
                values={
                    "roc_auc": m["auc"][key].get("auc"),
                    **{
                        f"precision_at_top{cut}": (
                            m.get("precision_at_top", {}).get(key) or {}
                        ).get(f"{cut}%")
                        for cut in (5, 10, 25)
                    },
                },
                n=n,
                n_runs=1,
                run_ids=[run.name],
            )
        )
    levels = m.get("by_level", {})
    table.conditions = {
        "hunks": n,
        "failed": m.get("n_failed"),
        "commented base rate": m.get("base_rate"),
        "commented if level high": (levels.get("high") or {}).get("commented_rate"),
        "commented if level low": (levels.get("low") or {}).get("commented_rate"),
        "configuration": "static analysis only (the ranking must be cheap enough for every change)",
    }
    by = {r.label: r.values for r in table.rows}
    risk, size = by.get("Risk model v2 (calibrated, shipped)"), by.get("Size only (changed lines)")
    if risk and size:
        for metric, label in (("roc_auc", "ROC-AUC"), ("precision_at_top10", "Precision@Top10%")):
            s = compare(label, "Risk model v2", risk.get(metric), "size only", size.get(metric))
            if s:
                table.observations.append(s)
    table.badges = ["Complete"]
    if risk and size and (size.get("roc_auc") or 0) > (risk.get("roc_auc") or 0):
        table.badges.append("Baseline not beaten")
        table.warning = (
            "Size-only ranking outperforms Risk model v2 on the current test set, on ROC-AUC and "
            "on precision at every cut-off. Do not describe risk ranking as beating the baseline."
        )
    table.notes = [
        f"v2 weights were fitted on the validation split. The test split appears in {len(hr)} "
        "saved runs, and the weights were not changed after seeing test results.",
        "That validation fit predates the line-ending fix, so it used inflated sizes for some "
        "samples. Re-fitting on a corrected validation run has not been done.",
    ]
    return table


# ---- efficiency ----------------------------------------------------------------------------------

TIME_COLUMNS = [
    Column(key="total_sec", label="Total", metric="seconds", digits=2),
    Column(key="static_analysis_sec", label="Static", metric="seconds", digits=2),
    Column(key="rag_sec", label="RAG", metric="seconds", digits=2),
    Column(key="llm_inference_sec", label="LLM", metric="seconds", digits=2),
    Column(key="validation_sec", label="Validation", metric="seconds", digits=3),
    Column(key="report_generation_sec", label="Reports", metric="seconds", digits=2),
    Column(key="other_sec", label="Other", metric="seconds", digits=2),
    Column(key="active_sec", label="Active (total - quota wait)", metric="seconds", digits=2),
]
TIMING_KEYS = {"static_only": "static_only", "llm_only": "llm_only", "static_llm": "llm_no_rag",
               "static_llm_rag": "llm_rag"}  # fmt: skip


RUNTIME_GEMINI = "6a. Efficiency: Gemini"
RUNTIME_STATIC = "6b. Efficiency: static analysis only"
HISTORICAL_TIMING = "6c. Efficiency: historical timing (not Gemini)"
RUNTIME_LLM = [
    Column(key="llm_inference_sec", label="LLM", metric="seconds", digits=2),
    Column(key="llm_quota_wait_sec", label="Quota wait", metric="seconds", digits=2),
    Column(key="input_tokens", label="Tokens in", digits=0),
    Column(key="output_tokens", label="Tokens out", digits=0),
    Column(key="thinking_tokens", label="Reasoning tokens", digits=0),
    Column(key="cache_hit_rate", label="Cache hit rate", digits=2),
]
RUNTIME_BASE = [
    Column(key="complete", label="Complete", digits=0, group="Runs"),
    Column(key="partial", label="Partial", digits=0, group="Runs"),
    Column(key="failed", label="Failed", digits=0, group="Runs"),
    Column(key="skipped", label="Skipped", digits=0, group="Runs"),
    Column(key="total_sec", label="Total", metric="seconds", digits=2),
    Column(key="static_analysis_sec", label="Static", metric="seconds", digits=2),
    Column(key="rag_retrieval_sec", label="RAG", metric="seconds", digits=3),
]
RUN_STATES = ("complete", "partial", "failed", "skipped")


def _csv_rows(run: SavedRun) -> list[dict[str, str]]:
    """The benchmark's raw rows. Completion is judged from these, never from its summary."""
    path = run.path / "results.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def runtime_counts(run: SavedRun) -> dict[str, Any] | None:
    """What actually happened in a file-size benchmark, counted from results.csv."""
    rows = _csv_rows(run)
    if not rows:
        return None
    repeats = int(run.metrics.get("repeats") or 0)
    files = len(run.metrics.get("inputs") or [])
    planned = repeats * files * 2  # one cold and one warm run per file, per round
    done = [r for r in rows if r.get("status") == "complete"]
    rounds = sorted({r["repeat"] for r in rows})
    finished = [k for k in rounds if sum(1 for r in done if r["repeat"] == k) == files * 2]
    counts = {s: sum(1 for r in rows if r.get("status") == s) for s in RUN_STATES}
    return {
        **counts,
        "planned": planned,
        "recorded": len(rows),
        "repeats": repeats,
        "files": files,
        "files_measured": len({r["file_name"] for r in rows if r.get("status") != "skipped"}),
        "files_complete": len({r["file_name"] for r in done}),
        "rounds_reached": len({r["repeat"] for r in rows if r.get("status") != "skipped"}),
        "rounds_complete": len(finished),
        "is_complete": planned > 0 and counts["complete"] == planned,
    }


def _mean(rows: list[dict[str, str]], key: str) -> float | None:
    values = [float(r[key]) for r in rows if r.get(key) not in (None, "")]
    return sum(values) / len(values) if values else None


def _runtime_row(
    group: list[dict[str, str]], label: str, columns: list[Column], run: SavedRun, uses_llm: bool
) -> Row:
    done = [r for r in group if r.get("status") == "complete"]
    row = Row(label=label, n=len(done), n_runs=len(group), run_ids=[run.name])
    for state in RUN_STATES:
        row.values[state] = sum(1 for r in group if r.get("status") == state)
    for col in columns:
        if col.key in RUN_STATES:
            continue
        row.values[col.key] = _mean(done, col.key)
        if row.values[col.key] is None:
            warm = label.endswith("warm")
            row.na[col.key] = (
                "no complete run"
                if not done
                else "no LLM call: answered from the cache"
                if uses_llm and warm
                else "not recorded for this run"
            )
    return row


def runtime_tables(runs: list[SavedRun]) -> list[ComparisonTable]:
    """One table per file-size benchmark, separating measured runs from skipped ones."""
    tables = []
    for run in (r for r in runs if r.kind == "runtime"):
        if run.metrics.get("pipeline_check_only"):
            continue
        counts = runtime_counts(run)
        rows = _csv_rows(run)
        if counts is None:
            continue
        uses_llm = run.metrics.get("mode") != "static_only"
        columns = RUNTIME_BASE + (RUNTIME_LLM if uses_llm else [])
        body = []
        for category in ("small", "medium", "large"):
            for run_type in ("cold", "warm"):
                group = [r for r in rows if r["category"] == category and r["run_type"] == run_type]
                body.append(
                    _runtime_row(group, f"{category.title()}, {run_type}", columns, run, uses_llm)
                )
        unmeasured = [
            c
            for c in ("small", "medium", "large")
            if not any(r["category"] == c and r["status"] == "complete" for r in rows)
        ]
        c = counts
        state = "Complete" if c["is_complete"] else "Incomplete"
        title = f"File-size benchmark: {run.model}" if uses_llm else "File-size benchmark: no LLM"
        table = ComparisonTable(
            id=f"runtime_{run.stamp}",
            section=RUNTIME_GEMINI if uses_llm else RUNTIME_STATIC,
            title=title,
            about="Times are means over complete runs only. Partial, failed and skipped runs are "
            "counted and never enter a time. Status comes from results.csv.",
            badges=[state, (provider_badge([run]) if uses_llm else None) or "No LLM"],
            columns=columns,
            rows=body,
            show_counts=False,
            conditions={
                "run": run.name,
                "planned": f"{c['files']} files x {c['repeats']} rounds x cold and warm = "
                f"{c['planned']} runs",
                "run status": f"{c['complete']} complete, {c['partial']} partial, {c['failed']} "
                f"failed, {c['skipped']} skipped",
                "files measured": f"{c['files_measured']} of {c['files']} "
                f"({c['files_complete']} with a complete run)",
                "rounds": f"{c['rounds_reached']} reached, {c['rounds_complete']} of "
                f"{c['repeats']} finished",
                "llm.max_tokens": run.setting("llm", "max_tokens") if uses_llm else None,
            },
        )
        if not c["is_complete"]:
            sizes = ", ".join(unmeasured) or "none"
            table.warning = (
                f"Incomplete: {c['complete']} of {c['planned']} planned runs finished, and "
                f"{c['rounds_complete']} of {c['repeats']} rounds. No complete run for: {sizes}. "
                "This is not the file-size benchmark result."
            )
            table.notes.append(
                "These runs used llm.max_tokens = 4096, since raised to 16,384 after replies were "
                "cut off on larger units. Rerun before quoting any time."
            )
        tables.append(table)
    return sorted(tables, key=lambda t: t.section)


def timing_tables(runs: list[SavedRun]) -> list[ComparisonTable]:
    tr = [r for r in runs if r.kind == "timing" and isinstance(r.metrics.get("results"), dict)]
    if not tr:
        return [
            ComparisonTable(
                id="timing", section=HISTORICAL_TIMING, title="Timing benchmark",
                columns=TIME_COLUMNS,
                rows=[not_run_row(k, f"{CMD} timing --repeats 3 {LLM_CONFIG}") for k in ORDER],
            )
        ]  # fmt: skip
    run = tr[-1]
    m = run.metrics
    cond = m.get("conditions", {})
    tables = []
    for sample, res in m["results"].items():
        rows = []
        for key in ORDER:
            cfg = res["configs"].get(TIMING_KEYS[key])
            if not cfg or not cfg.get("complete_runs"):
                why = "not included in the latest timing run" if not cfg else "no complete run"
                rows.append(not_run_row(key, f"{CMD} timing --repeats 3 {LLM_CONFIG}", why))
                continue
            row = config_row(key)
            for col in TIME_COLUMNS:
                d = cfg.get(col.key) or {}
                row.values[col.key] = d.get("median")
                row.spread[col.key] = [d.get("min"), d.get("max")]
            row.n = cfg["complete_runs"]
            row.n_runs = cfg["complete_runs"]
            row.n_failed = cfg["runs"] - cfg["complete_runs"]
            row.model = cond.get("model") if key != "static_only" else None
            row.run_ids = [run.name]
            rows.append(row)
        conds = [c.get("conditions") or {} for c in res["configs"].values()]
        c0 = max(conds, key=lambda c: c.get("review_units") or 0, default={})
        table = ComparisonTable(
            id=f"timing_{sample}",
            section=HISTORICAL_TIMING,
            title=f"Time per review: {sample} (median of {m.get('repeats')} runs, seconds)",
            about="Fixed input, interleaved repeats, concurrency 1, fresh vector store per run, "
            "one untimed warm-up; incomplete runs excluded.",
            badges=[f"Historical: {str(cond.get('provider')).title()} ({cond.get('model')})"],
            columns=TIME_COLUMNS,
            rows=rows,
            conditions={
                "input": sample,
                "files": c0.get("files"),
                "lines reviewed": c0.get("lines_reviewed"),
                "LLM review units": c0.get("review_units"),
                "provider / model": f"{cond.get('provider')} / {cond.get('model')}",
                "repeats": m.get("repeats"),
                "hardware": (cond.get("hardware") or {}).get("processor"),
            },
        )
        ov = res.get("rag_overhead")
        if ov:
            table.observations.append(
                f"RAG overhead {ov['overhead_pct']:+.1f}% (median active time "
                f"{ov['median_active_sec_without_rag']:.2f}s without -> "
                f"{ov['median_active_sec_with_rag']:.2f}s with RAG); RAG's own cost "
                f"{fmt(ov.get('rag_direct_median_sec'), 2)}s."
            )
            r_without = ov.get("median_llm_retries_without_rag")
            r_with = ov.get("median_llm_retries_with_rag")
            if r_without is not None and r_with is not None and r_without != r_with:
                table.observations.append(
                    f"Median LLM JSON retries differ ({r_without:g} without vs {r_with:g} with "
                    "RAG): a retry repeats the whole LLM call, so retries, not retrieval, explain "
                    "most of this overhead."
                )
        else:
            table.notes.append("RAG overhead: N/A (needs complete Static + LLM and Static + LLM + "
                               "RAG runs in the same timing run).")  # fmt: skip
        table.notes.append(
            "Timing statistics (mean, median, min, max) per component are in "
            f"run {run.name}; the table shows the median, ranges on hover."
        )
        tables.append(table)
    return tables


ACTIVE_NA = (
    "quota waiting is summed over concurrent LLM workers, so total - waiting is only defined "
    "for runs at concurrency 1"
)


def _active(m: dict[str, Any]) -> float | None:
    """Total minus LLM quota waiting; None unless the run used one LLM worker (see ACTIVE_NA)."""
    t = m.get("timing") or {}
    total = t.get("total_sec")
    if total is None or int(t.get("concurrency") or 1) > 1:
        return None
    return float(total) - float(t.get("llm_rate_limit_wait_sec") or 0.0)


def planted_timing_table(runs: list[SavedRun]) -> ComparisonTable:
    """Timing of the planted-benchmark runs themselves: every configuration, same repository."""
    chosen = planted_chosen(runs)
    rows = []
    for key in ORDER:
        sel = chosen[key]
        if not sel:
            rows.append(not_run_row(key, f"{CMD} planted --configuration {key}"))
            continue
        row = config_row(key)
        for col in TIME_COLUMNS:
            if col.key == "active_sec":
                values = [_active(r.metrics) for r in sel]
            elif col.key == "rag_sec":
                values = [
                    (r.metrics.get("timing") or {}).get("rag_index_sec", 0.0)
                    + (r.metrics.get("timing") or {}).get("rag_retrieval_sec", 0.0)
                    if r.metrics.get("timing")
                    else None
                    for r in sel
                ]
            else:
                values = [(r.metrics.get("timing") or {}).get(col.key) for r in sel]
            mean, sd, n = mean_sd(values)
            row.values[col.key] = mean
            if n > 1:
                row.sd[col.key] = sd
        row.n_runs = len(sel)
        row.model = sel[0].model
        row.run_ids = [r.name for r in sel]
        if row.values.get("report_generation_sec") is None:
            row.na["report_generation_sec"] = "benchmark runs do not write reports"
        if row.values.get("active_sec") is None:
            row.na["active_sec"] = ACTIVE_NA
        rows.append(row)
    table = ComparisonTable(
        id="timing_planted_runs",
        section=HISTORICAL_TIMING,
        badges=[b for b in [provider_badge(r for rs in chosen.values() for r in rs)] if b],
        title="Time per review in the planted-benchmark runs (seconds)",
        about="The same repository reviewed under each configuration (the runs in section 1). "
        "One measurement per run; repeated runs show the mean.",
        columns=TIME_COLUMNS,
        rows=rows,
        conditions={"input": "planted fixture repository (8 files, 6 Python)"},
    )
    by = {r.configuration.key: r for r in rows if r.configuration and r.status == "ok"}
    c, d = by.get("static_llm"), by.get("static_llm_rag")
    together = bool(c and d) and _same_group(chosen["static_llm"], chosen["static_llm_rag"])
    if c and d and together:
        t_with, t_without = d.values.get("active_sec"), c.values.get("active_sec")
        pct = overhead_pct(
            float(t_with) if t_with is not None else None,
            float(t_without) if t_without is not None else None,
        )
        if pct is not None:
            table.observations.append(
                f"RAG overhead {pct:+.1f}% on active time (n = {d.n_runs} run(s) per "
                "configuration; a single run is noisy, the timing benchmark is the fair measure)."
            )
            rag_own, llm_d, llm_c = (
                d.values.get("rag_sec"),
                d.values.get("llm_inference_sec"),
                c.values.get("llm_inference_sec"),
            )
            if rag_own is not None and llm_d is not None and llm_c is not None:
                table.observations.append(
                    f"Of that difference, retrieval itself took {rag_own:.2f}s; LLM inference took "
                    f"{llm_d - llm_c:+.2f}s more with RAG (longer prompts carrying the context)."
                )
    elif c and d:
        table.notes.append(
            "RAG overhead: N/A (Static + LLM and Static + LLM + RAG were not run in the same "
            "ablation group, so their times are not comparable)."
        )
    table.fairness = [
        FairnessCheck(name="Same input", ok=True, detail="planted fixture repository for every row")
    ]
    return table


def _same_group(a: list[SavedRun], b: list[SavedRun]) -> bool:
    ga, gb = {r.group_id for r in a}, {r.group_id for r in b}
    return len(ga) == 1 and ga == gb and None not in ga


# ---- supplementary: usefulness (LLM judge) -------------------------------------------------------

USEFULNESS_COLUMNS = [
    Column(key="relevance", label="Relevance (1-5)", metric="rating", digits=2),
    Column(key="informativeness", label="Informativeness (1-5)", metric="rating", digits=2),
]


def usefulness_table(runs: list[SavedRun]) -> ComparisonTable | None:
    ur = [r for r in runs if r.kind == "usefulness"]
    if not ur:
        return None
    run = ur[-1]
    m = run.metrics
    rows = []
    for key, label in (("agent", "Agent comment"), ("human", "Human reviewer comment")):
        part = m.get(key) or {}
        rows.append(
            Row(
                label=label,
                values={
                    "relevance": (part.get("relevance") or {}).get("mean"),
                    "informativeness": (part.get("informativeness") or {}).get("mean"),
                },
                n=(part.get("relevance") or {}).get("n"),
                n_runs=1,
                run_ids=[run.name],
            )
        )
    return ComparisonTable(
        id="usefulness",
        section="Supplementary",
        title="Supplementary comment usefulness evaluation (LLM judge)",
        about="Blind, reference-free 1-5 ratings of the agent's and the human's comment on the "
        "same diff. Supplementary only: not a primary result.",
        columns=USEFULNESS_COLUMNS,
        rows=rows,
        conditions={
            "judge model": run.model,
            "reviewer model": run.meta.get("reviewer_model"),
            "source run": run.meta.get("source_run"),
            "comments judged": m.get("n_judged"),
            "diffs where the agent wrote no comment": m.get("agent_no_comment"),
        },
        badges=["Preliminary", "Historical: Groq (reviewer and judge)"],
        notes=[
            "Limitations: a single LLM judge (possible self-preference and verbosity bias); small "
            "sample; the agent's comments are longer than human ones, which judges tend to reward; "
            "judge-human agreement must be measured with the human rating kit before citing.",
        ],
        supplementary=True,
    )
