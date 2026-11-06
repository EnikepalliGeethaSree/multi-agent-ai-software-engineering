"""The Code Review Agent's evaluation framework: five components, one record format, two tables.

    1. Detection quality      planted-issue suite        precision, recall, F1 (TP/FP/FN)
    2. CodeReviewer benchmark cls + msg tasks          precision, AUC (cls); coverage, chrF (msg)
    3. RAG retrieval          call-graph relevance       Recall@10 (vs random baseline)
    4. Risk ranking           CodeReviewer cls hunks     Precision@top 10% (+ existing AUC)
    5. Efficiency             timing benchmark           total, static, RAG, LLM, validation, report

Records are built ONLY from saved runs in experiments/results/<run>/ (metrics.json + meta.json).
A required configuration without a run becomes status "not_run" with the command that produces
it - never an estimate.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from marl_agents.evaluation.runs import SavedRun, load_runs

Component = Literal["detection", "codereviewer", "rag", "risk_ranking", "efficiency"]

DEFINITIONS: dict[str, str] = {
    "precision (detection)": "TP / (TP + FP) over defect findings; TP = finding matching a planted "
    "issue (same file, +-2 lines, compatible category).",
    "recall (detection)": "planted issues detected / all planted issues.",
    "f1": "harmonic mean of precision and recall.",
    "precision (CodeReviewer cls)": "of the hunks the agent flags (>= 1 finding of severity >= "
    "low), the share a human reviewer commented on.",
    "auc": "ROC-AUC of the agent's per-hunk finding score against the human 'commented' label.",
    "coverage": "share of diffs for which the agent produced a review comment (the project's "
    "existing definition; a diff with no in-scope finding scores an empty comment).",
    "chrf": "character n-gram F-score (x100) between the agent's comment (title + fix) and the "
    "human reference comment.",
    "recall@10": "share of the query function's callees (from the AST call graph) found in the "
    "top 10 retrieved chunks.",
    "precision@top10%": "of the 10% of hunks ranked riskiest, the share a human commented on.",
}


class EvaluationRecord(BaseModel):
    component: Component
    benchmark: str
    configuration: str
    status: Literal["ok", "not_run"] = "ok"
    run_id: str | None = None
    n: int | None = Field(default=None, description="Samples / issues / queries evaluated.")
    quality_metrics: dict[str, float | None] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    timing: dict[str, Any] | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    how_to_run: str | None = None


CMD = "python -m marl_agents.cli eval"
REQUIRED: list[tuple[Component, str, str, str]] = [
    ("detection", "Planted issues", "static only", f"{CMD} planted --mode static_only"),
    ("detection", "Planted issues", "static + LLM", f"{CMD} planted --mode full"),
    ("codereviewer", "CodeReviewer cls (test, Python)", "static only",
     f"{CMD} codereviewer --task cls --mode static_only"),
    ("codereviewer", "CodeReviewer cls (test, Python)", "static + LLM",
     f"{CMD} codereviewer --task cls --limit 40 --seed 42 --mode full --workers 1"),
    ("codereviewer", "CodeReviewer msg (test, Python)", "static only",
     f"{CMD} codereviewer --task msg --mode static_only"),
    ("codereviewer", "CodeReviewer msg (test, Python)", "static + LLM",
     f"{CMD} codereviewer --task msg --limit 40 --seed 42 --mode full --workers 1"),
    ("rag", "Call-graph retrieval (src)", "hashing embedder", f"{CMD} retrieval --path src"),
    ("risk_ranking", "CodeReviewer cls hunks (test)", "risk v2 vs baselines",
     f"{CMD} hunkrisk --split test"),
    ("efficiency", "Timing benchmark", "static / LLM+RAG / LLM no RAG",
     f"{CMD} timing --repeats 3"),
]  # fmt: skip


def _r(x: Any) -> float | None:
    return None if x is None else round(float(x), 3)


# Labels of the five-component table, by ablation configuration (see evaluation/configurations.py).
_LABELS = {
    "static_only": "static only",
    "llm_only": "LLM only",
    "static_llm": "static + LLM",
    "static_llm_rag": "static + LLM + RAG",
    "llm_rag": "LLM only",
}


def run_label(run: SavedRun, tag: str) -> str:
    """Configuration label of a saved run: exact when config.yaml / meta records it."""
    c = run.configuration if (run.experiment or run.config) else None
    if c is None:  # only the folder tag is known: keep the historical label
        return _config(tag, run.meta.get("llm_model"))
    label = _LABELS[c.key]
    if c.llm and run.model:
        label += f" ({run.model})"
    if c.key == "static_llm":
        label += ", no RAG"
    elif c.key == "llm_rag":
        label += ", with RAG"
    return label


def _config(tag: str, model: str | None) -> str:
    base = (
        "static only"
        if tag.startswith("static_only")
        else ("LLM only" if tag.startswith("llm_only") else "static + LLM")
    )
    if base != "static only" and model:
        base += f" ({model})"
    if tag.endswith("_norag"):
        base += ", no RAG"
    return base


# ---- adapters: saved run -> record ---------------------------------------------------------------


def detection_record(
    run_id: str, tag: str, m: dict[str, Any], meta: dict[str, Any], label: str | None = None
) -> EvaluationRecord:
    d = m["detection"]
    tp = d.get("tp", d.get("defect_true_positives", 0))
    fp = d.get("fp", d.get("defect_findings", 0) - tp)
    fn = d.get("fn", d["expected"] - d["matched"])
    precision = d.get("precision", d.get("defect_precision"))
    recall = d["recall"]
    f1 = d.get("f1")
    if f1 is None and precision is not None and precision + recall:
        f1 = 2 * precision * recall / (precision + recall)
    return EvaluationRecord(
        component="detection",
        benchmark="Planted issues",
        configuration=label or _config(tag, meta.get("llm_model")),
        run_id=run_id,
        n=d["expected"],
        quality_metrics={"precision": _r(precision), "recall": _r(recall), "f1": _r(f1)},
        counts={"tp": tp, "fp": fp, "fn": fn, "expected_issues": d["expected"]},
        timing=m.get("timing") or None,
        notes=["precision over defect findings (bug, security, error handling, edge case)"],
    )


def codereviewer_record(
    run_id: str,
    task: str,
    tag: str,
    m: dict[str, Any],
    meta: dict[str, Any],
    label: str | None = None,
) -> EvaluationRecord:
    n = m.get("n_evaluated")
    notes = [] if meta.get("limit") is None else [
        f"random subset: n={meta['limit']} (seed {meta.get('seed')}), {m.get('n_failed', 0)} failed"
    ]  # fmt: skip
    if task == "cls":
        sens = m.get("sensitivity_without_cross_hunk_rules", {})
        q = {
            "precision": _r(m["default"]["precision"]),
            "auc": _r(m.get("roc_auc")),
            "precision_cross_hunk_rules_excluded": _r(sens.get("default", {}).get("precision")),
            "auc_cross_hunk_rules_excluded": _r(sens.get("roc_auc")),
        }
        bench = "CodeReviewer cls (test, Python)"
    else:
        tf = m.get("text_metrics", {}).get("title_fix", {})
        q = {"coverage": _r(m.get("comment_coverage")), "chrf": _r(tf.get("chrf"))}
        notes.append(f"BLEU-4 (approved-deck metric, still computed): {tf.get('bleu4_smoothed')}")
        bench = "CodeReviewer msg (test, Python)"
    return EvaluationRecord(
        component="codereviewer",
        benchmark=bench,
        configuration=label or _config(tag, meta.get("llm_model")),
        run_id=run_id,
        n=n,
        quality_metrics=q,
        counts={"failed": m.get("n_failed", 0)},
        timing=m.get("timing"),
        notes=notes,
    )


def rag_record(run_id: str, m: dict[str, Any]) -> EvaluationRecord:
    methods = [
        k
        for k, v in m.items()
        if isinstance(v, dict) and "recall@10" in v and k != "random_baseline"
    ]
    q: dict[str, float | None] = {f"recall@10 ({k})": _r(m[k].get("recall@10")) for k in methods}
    q["recall@10 (random baseline)"] = _r(m.get("random_baseline", {}).get("recall@10"))
    return EvaluationRecord(
        component="rag",
        benchmark=f"Call-graph retrieval ({Path(str(m.get('repo', ''))).name or 'repo'})",
        configuration=", ".join(methods) + " embedder",
        run_id=run_id,
        n=m.get("n_queries"),
        quality_metrics=q,
        counts={"chunks": m.get("n_chunks", 0)},
    )


def risk_record(run_id: str, split: str, m: dict[str, Any]) -> EvaluationRecord:
    p, auc = m["precision_at_top"], m["auc"]
    names = {
        "hunk_risk": "risk v2 (calibrated)",
        "risk_v1_baseline": "risk v1 (hand-set)",
        "size_baseline": "size only",
    }
    q: dict[str, float | None] = {}
    for key, label in names.items():
        if key in p:
            q[f"precision@top10% {label}"] = _r(p[key]["10%"])
            q[f"auc {label}"] = _r(auc[key]["auc"])
    rnd = m.get("random_baseline", {"precision_at_top": m.get("base_rate"), "auc": 0.5})
    q["precision@top10% random (expected)"] = _r(rnd["precision_at_top"])
    q["auc random (expected)"] = _r(rnd["auc"])
    notes = []
    if "risk_v1_baseline" not in p:
        notes.append("run predates the frozen v1 baseline; re-run to include it")
    if split != "test":
        notes.append("validation split (used to fit v2): not a final result")
    return EvaluationRecord(
        component="risk_ranking",
        benchmark=f"CodeReviewer cls hunks ({split})",
        configuration="risk v2 vs baselines",
        run_id=run_id,
        n=m.get("n_evaluated"),
        quality_metrics=q,
        notes=notes,
    )


def _overhead_note(sample: str, ov: dict[str, Any]) -> str:
    note = f"{sample}: RAG latency overhead {ov['overhead_pct']:+.1f}%"
    if ov.get("median_active_sec_without_rag") is not None:
        note += (
            f" ({ov['median_active_sec_without_rag']:.2f}s -> "
            f"{ov['median_active_sec_with_rag']:.2f}s, median active time)"
        )
    if ov.get("rag_direct_median_sec") is not None:
        note += (
            f"; RAG itself {ov['rag_direct_median_sec']:.2f}s ({ov['rag_direct_share_pct']}%); "
            f"median JSON retries {ov['median_llm_retries_without_rag']} without vs "
            f"{ov['median_llm_retries_with_rag']} with RAG"
        )
    return note


def efficiency_records(run_id: str, m: dict[str, Any]) -> list[EvaluationRecord]:
    out = []
    for sample, res in m["results"].items():
        for config, c in res["configs"].items():
            timing = {
                k: c[k].get("median") for k in c if isinstance(c[k], dict) and "median" in c[k]
            }
            out.append(
                EvaluationRecord(
                    component="efficiency",
                    benchmark=f"Timing: {sample}",
                    configuration=config,
                    run_id=run_id,
                    n=c["complete_runs"],
                    quality_metrics={},
                    timing={**timing, "statistic": "median over repeats"},
                    conditions={**c.get("conditions", {}), **m.get("conditions", {})},
                    notes=[_overhead_note(sample, res["rag_overhead"])]
                    if res.get("rag_overhead") and config == "llm_rag"
                    else [],
                )
            )
    return out


# ---- collection ----------------------------------------------------------------------------------


def collect_records(results_dir: Path) -> list[EvaluationRecord]:
    """Latest saved run per (component, benchmark, configuration); missing ones as not_run."""
    latest: dict[tuple[str, str, str], EvaluationRecord] = {}
    history: dict[tuple[str, str, str], list[EvaluationRecord]] = {}
    for run in load_runs(results_dir):  # chronological: later runs replace earlier ones
        m, meta, kind, rest, name = run.metrics, run.meta, run.kind, run.rest, run.name
        records: list[EvaluationRecord] = []
        try:
            if kind == "planted":
                records = [detection_record(name, rest, m, meta, run_label(run, rest))]
            elif kind == "codereviewer":
                task, _split, tag = rest.split("_", 2)
                tag = re.sub(r"_n\d+$", "", tag)
                records = [codereviewer_record(name, task, tag, m, meta, run_label(run, tag))]
            elif kind == "retrieval":
                records = [rag_record(name, m)]
            elif kind == "hunkrisk":
                split = rest.split("_")[1]
                if split == "test":
                    records = [risk_record(name, split, m)]
            elif kind == "timing":
                records = efficiency_records(name, m)
        except (KeyError, ValueError, TypeError):
            continue  # unknown/older layout: skipped rather than guessed
        for r in records:
            rkey = (r.component, r.benchmark, r.configuration)
            latest[rkey] = r
            history.setdefault(rkey, []).append(r)
    for hkey, runs in history.items():  # same configuration run more than once: show the spread
        if len(runs) > 1 and hkey[0] in ("detection", "codereviewer"):
            for old in runs[:-1]:
                values = ", ".join(f"{k} {v}" for k, v in old.quality_metrics.items())
                latest[hkey].notes.append(f"earlier run {old.run_id}: {values}")
    records = list(latest.values())
    for component, bench, config, cmd in REQUIRED:
        have = any(
            r.component == component
            and (r.benchmark == bench or component in ("rag", "efficiency", "risk_ranking"))
            and r.configuration.startswith(config.split(" (")[0])
            for r in records
        ) if component not in ("rag", "efficiency", "risk_ranking") else any(
            r.component == component for r in records
        )  # fmt: skip
        if not have:
            records.append(
                EvaluationRecord(
                    component=component,
                    benchmark=bench,
                    configuration=config,
                    status="not_run",
                    notes=["no saved run yet"],
                    how_to_run=cmd,
                )
            )
    order = ["detection", "codereviewer", "rag", "risk_ranking", "efficiency"]
    return sorted(records, key=lambda r: (order.index(r.component), r.benchmark, r.configuration))


# ---- tables --------------------------------------------------------------------------------------

LABEL = {
    "detection": "Planted issues",
    "codereviewer": "CodeReviewer",
    "rag": "RAG",
    "risk_ranking": "Risk ranking",
    "efficiency": "Efficiency",
}


def _v(x: Any, unit: str = "") -> str:
    return "-" if x is None else (f"{x:.3f}{unit}" if isinstance(x, float) else f"{x}{unit}")


def results_table_md(records: list[EvaluationRecord]) -> str:
    lines = [
        "| Evaluation | Benchmark | Configuration | n | Metric | Result |",
        "|---|---|---|---:|---|---:|",
    ]
    for r in records:
        if r.status == "not_run":
            lines.append(
                f"| {LABEL[r.component]} | {r.benchmark} | {r.configuration} | - | - | "
                f"**not run** (`{r.how_to_run}`) |"
            )
            continue
        if r.component == "efficiency":
            t = r.timing or {}
            for key, label in (
                ("total_sec", "Total review time (median)"),
                ("active_sec", "Active time, excl. LLM quota waiting (median)"),
            ):
                lines.append(
                    f"| Efficiency | {r.benchmark.removeprefix('Timing: ')} | {r.configuration} | "
                    f"{r.n} runs | {label} | {_v(t.get(key), ' s')} |"
                )
            continue
        for name, value in r.quality_metrics.items():
            lines.append(
                f"| {LABEL[r.component]} | {r.benchmark} | {r.configuration} | {r.n} | {name} | "
                f"{_v(value)} |"
            )
    return "\n".join(lines)


TIMING_ROWS = [
    ("static_analysis_sec", "Static analysis"),
    ("rag_sec", "RAG retrieval (index + queries)"),
    ("llm_inference_sec", "LLM inference"),
    ("validation_sec", "Validation"),
    ("report_generation_sec", "Report generation"),
    ("other_sec", "Other / orchestration"),
    ("llm_rate_limit_wait_sec", "of which: LLM quota waiting"),
    ("total_sec", "**Total**"),
    ("active_sec", "Active time (total - quota waiting)"),
]
CONFIG_ORDER = ["static_only", "llm_only", "llm_no_rag", "llm_rag"]


def timing_table_md(records: list[EvaluationRecord]) -> str:
    eff = [r for r in records if r.component == "efficiency" and r.status == "ok"]
    if not eff:
        return (
            "Timing breakdown: **not run** (`python -m marl_agents.cli eval timing --repeats 3`)."
        )
    out = []
    for bench in sorted({r.benchmark for r in eff}):
        rows = sorted(
            (r for r in eff if r.benchmark == bench),
            key=lambda r: (
                CONFIG_ORDER.index(r.configuration)
                if r.configuration in CONFIG_ORDER
                else len(CONFIG_ORDER)
            ),
        )
        out += [
            f"**{bench.removeprefix('Timing: ')}** (median seconds)",
            "",
            "| Component | " + " | ".join(r.configuration for r in rows) + " |",
            "|---|" + "---:|" * len(rows),
        ]
        for key, label in TIMING_ROWS:
            out.append(
                f"| {label} | " + " | ".join(_v((r.timing or {}).get(key)) for r in rows) + " |"
            )
        out.append("| Complete runs | " + " | ".join(str(r.n) for r in rows) + " |")
        out.append("")
    return "\n".join(out)


def summary_md(records: list[EvaluationRecord]) -> str:
    run_ids = sorted({r.run_id for r in records if r.run_id})
    notes = [f"- {LABEL[r.component]} / {r.configuration}: {n}" for r in records for n in r.notes]
    return "\n".join(
        [
            "# Code Review Agent: evaluation summary",
            "",
            "Generated from saved runs only (`python -m marl_agents.cli eval summary`).",
            "",
            "## Results",
            "",
            results_table_md(records),
            "",
            "## Time breakdown",
            "",
            timing_table_md(records),
            "## Notes",
            "",
            *notes,
            "",
            "## Source runs",
            "",
            *[f"- `{r}`" for r in run_ids],
            "",
        ]
    )
