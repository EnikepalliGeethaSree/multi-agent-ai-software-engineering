"""Evaluation status: what is complete, preliminary, incomplete and pending, from saved runs only.

Every status comes from a rule applied to the saved runs, so it changes by itself when a new run
arrives. Nothing here writes to a run. A run counts as complete only by its own rows: the file-size
benchmark, for example, is judged from results.csv, never from its summary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from marl_agents.evaluation.comparison.baselines import runtime_counts
from marl_agents.evaluation.comparison.common import ALL_CONFIGS, CMD, LLM_CONFIG, MIN_PAIRED_N
from marl_agents.evaluation.comparison.models import (
    ComparisonTable,
    EvaluationStatus,
    Row,
    StatusItem,
)
from marl_agents.evaluation.runs import SavedRun

SET_MODEL = "set GEMINI_MODEL=gemini-3.6-flash first"
LIMITATIONS = [
    "Planted benchmark: 17 issues written by the project team, and only one needs semantic "
    "reasoning. It is a regression check, not evidence of real-world accuracy.",
    "CodeReviewer labels record whether a human commented, which is a proxy for 'needs attention', "
    "not a defect label.",
    "Every LLM comparison so far uses Groq-hosted models. No Gemini result exists for detection or "
    "comment quality, and results from different models must not be combined.",
    "The Gemini free tier allows 20 requests per day per model, so larger comparisons run over "
    "several days with --reuse-llm-cache. Their quality metrics compare; their times do not.",
    "All runs come from an uncommitted working tree, so none can be traced to a commit.",
    "This evaluates the Code Review Agent alone, not the five-agent platform.",
]


def _rows(table: ComparisonTable | None) -> list[Row]:
    return [] if table is None else table.rows


def _ok(table: ComparisonTable | None) -> list[Row]:
    return [r for r in _rows(table) if r.status == "ok"]


def _ids(table: ComparisonTable | None) -> list[str]:
    return sorted({rid for r in _rows(table) for rid in r.run_ids})


def _value(table: ComparisonTable | None, label: str, key: str) -> Any:
    return next((r.values.get(key) for r in _rows(table) if r.label.startswith(label)), None)


def _gemini(runs: list[SavedRun], kind: str) -> list[SavedRun]:
    return [r for r in runs if r.kind == kind and r.provider == "gemini"]


def unfinished_runs(results_dir: Path) -> list[str]:
    """Folders with no metrics.json or marked aborted. The run tables cannot show these."""
    if not results_dir.is_dir():
        return []
    out = []
    for path in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        if (path / "ABORTED.txt").exists():
            out.append(f"{path.name}: aborted (see ABORTED.txt)")
        elif not (path / "metrics.json").is_file():
            out.append(f"{path.name}: stopped before metrics were saved")
    return out


def _detection_items(tables: dict[str, ComparisonTable]) -> list[StatusItem]:
    items: list[StatusItem] = []
    planted = tables.get("planted")
    done = _ok(planted)
    if planted is not None and done:
        full = len(done) == 4
        items.append(
            StatusItem(
                name="Planted-issue benchmark",
                status="complete" if full else "incomplete",
                detail=f"{len(done)} of 4 configurations on 17 issues, run with "
                f"{done[-1].model or 'no LLM'}. Small benchmark.",
                run_ids=_ids(planted),
            )
        )
    for tid, name in (("codereviewer_cls", "CodeReviewer classification, paired"),
                      ("codereviewer_msg", "Review comment generation, paired")):  # fmt: skip
        table = tables.get(tid)
        done = _ok(table)
        if table is None or not done:
            continue
        paired = done[0].n or 0
        missing = [r.label for r in _rows(table) if r.status != "ok"]
        state = "preliminary" if paired < MIN_PAIRED_N else "incomplete" if missing else "complete"
        gap = f"; no scored samples for {', '.join(missing)}" if missing else ""
        requested = table.conditions.get("requested samples")
        items.append(
            StatusItem(
                name=name,
                status=state,
                detail=f"{paired} of {requested} requested samples paired{gap}.",
                run_ids=_ids(table),
            )
        )
    for tid, name in (("codereviewer_cls_full", "CodeReviewer classification, static only"),
                      ("codereviewer_msg_full", "Comment generation, static only")):  # fmt: skip
        table = tables.get(tid)
        if table is not None and table.rows:
            detail = f"Full Python test split, n = {table.rows[0].n}. Not paired with the LLM runs."
            items.append(
                StatusItem(name=name, status="complete", detail=detail, run_ids=_ids(table))
            )
    return items


def _method_items(tables: dict[str, ComparisonTable], runs: list[SavedRun]) -> list[StatusItem]:
    items: list[StatusItem] = []
    retrieval = tables.get("retrieval")
    if _ok(retrieval):
        items.append(
            StatusItem(
                name="RAG retrieval",
                status="complete",
                detail="Retrieval quality on this repository, hashing embedder. It does not "
                "measure final review accuracy.",
                run_ids=_ids(retrieval),
            )
        )
    risk = tables.get("risk")
    if _ok(risk):
        items.append(
            StatusItem(
                name="Risk ranking",
                status="complete",
                detail=f"{risk.conditions.get('hunks')} hunks. Size-only is the better ranker."  # type: ignore[union-attr]
                if _size_beats_risk(risk)
                else f"{risk.conditions.get('hunks')} hunks.",  # type: ignore[union-attr]
                run_ids=_ids(risk),
            )
        )
    historic = [t for t in tables.values() if t.id.startswith("timing_") and _ok(t)]
    if historic:
        ids = sorted({rid for t in historic for rid in _ids(t)})
        items.append(
            StatusItem(
                name="Timing, historical Groq",
                status="complete",
                detail="Separate provider. Not an estimate for Gemini.",
                run_ids=ids,
            )
        )
    for run in (r for r in runs if r.kind == "runtime"):
        if run.metrics.get("pipeline_check_only"):
            continue
        c = runtime_counts(run)
        done = bool(c and c["is_complete"])
        gemini = run.metrics.get("mode") != "static_only"
        name = f"File-size benchmark, {run.model}" if gemini else "File-size benchmark, static only"
        status = "complete" if done else "incomplete"
        detail = "Could not read results.csv."
        if c:
            detail = (
                f"{c['complete']} of {c['planned']} planned runs complete ({c['partial']} partial, "
                f"{c['failed']} failed, {c['skipped']} skipped); {c['rounds_complete']} of "
                f"{c['repeats']} rounds finished."
            )
        command = None
        if gemini and not done:
            command = (
                "python -m marl_agents.evaluation.benchmark_runtime --config configs/gemini.yaml "
                "--repeats 5 --per-category 1 --max-llm-calls 65"
            )
        items.append(
            StatusItem(name=name, status=status, detail=detail, run_ids=[run.name], command=command)
        )
    return items


def _size_beats_risk(risk: ComparisonTable | None) -> bool:
    size = _value(risk, "Size only", "roc_auc")
    model = _value(risk, "Risk model v2", "roc_auc")
    return size is not None and model is not None and size > model


def _other_items(tables: dict[str, ComparisonTable], runs: list[SavedRun]) -> list[StatusItem]:
    items: list[StatusItem] = []
    classifier = [r for r in runs if r.kind == "classifier" and r.rest.startswith("cls")]
    if classifier:
        run = classifier[-1]
        primary = run.metrics.get("repo_disjoint") or {}
        items.append(
            StatusItem(
                name="Fine-tuned change classifier",
                status="complete",
                detail=f"Held-out test, n = {primary.get('n')}, used once. Predicts human "
                "comments, not review quality.",
                run_ids=[run.name],
            )
        )
    smoke = [r for r in runs if r.kind == "gemini" and r.rest.startswith("smoke")]
    if smoke:
        passed = [r for r in smoke if not r.metrics.get("failed")]
        failed = [r for r in smoke if r.metrics.get("failed")]
        latest = passed[-1] if passed else failed[-1]
        note = ""
        if failed:
            note = " Failed on: " + ", ".join(sorted({str(r.metrics.get("model")) for r in failed}))
        items.append(
            StatusItem(
                name="Gemini smoke test",
                status="complete" if passed else "incomplete",
                detail=f"Live checks on {latest.metrics.get('model')}.{note}",
                run_ids=[r.name for r in smoke],
            )
        )
    usefulness = tables.get("usefulness")
    if _ok(usefulness):
        items.append(
            StatusItem(
                name="Comment usefulness (LLM judge)",
                status="preliminary",
                detail="Supplementary. One judge model, not yet checked against human ratings.",
                run_ids=_ids(usefulness),
            )
        )
    return items


def _pending(runs: list[SavedRun]) -> list[StatusItem]:
    items: list[StatusItem] = []
    if not _gemini(runs, "planted"):
        items.append(
            StatusItem(
                name="Planted issues on Gemini",
                status="pending",
                detail=f"All four configurations in one group; {SET_MODEL}.",
                command=f"{CMD} ablation --benchmark planted --configurations {ALL_CONFIGS} "
                f"{LLM_CONFIG}",
            )
        )
    if not [r for r in _gemini(runs, "codereviewer") if r.task == "msg"]:
        items.append(
            StatusItem(
                name="Comment generation on Gemini",
                status="pending",
                detail="All four configurations on identical samples. About 120 requests, so "
                "repeat the command each day: cached replies carry the run forward.",
                command=f"{CMD} ablation --benchmark codereviewer --task msg --limit 40 --seed 42 "
                f"--configurations {ALL_CONFIGS} --reuse-llm-cache {LLM_CONFIG}",
            )
        )
    if not [r for r in runs if r.kind == "classifier" and r.rest.startswith("ablation")]:
        items.append(
            StatusItem(
                name="Classifier off, prioritize and gate",
                status="pending",
                detail="Development samples only. The classifier test split is not read.",
                command=f"{CMD} classifier-ablation --model-dir data/models/change_cls --limit 15 "
                f"--max-llm-calls 45 {LLM_CONFIG}",
            )
        )
    return items


def _findings(tables: dict[str, ComparisonTable], runs: list[SavedRun]) -> list[str]:
    """Findings with enough data behind them. Each is written only if its numbers exist."""
    out: list[str] = []
    full = tables.get("codereviewer_cls_full")
    if full is not None and full.rows:
        v = full.rows[0].values
        raw, adj = v.get("roc_auc"), v.get("adj_roc_auc")
        if raw is not None and adj is not None:
            out.append(
                f"Static analysis alone barely predicts where humans comment: ROC-AUC {adj:.3f} "
                f"with cross-hunk rules removed, {raw:.3f} raw (n = {full.rows[0].n})."
            )
    classifier = [r for r in runs if r.kind == "classifier" and r.rest.startswith("cls")]
    if classifier:
        p = classifier[-1].metrics.get("repo_disjoint") or {}
        base = p.get("baselines") or {}
        tfidf = (base.get("tfidf_logistic") or {}).get("roc_auc")
        size = base.get("size_only_roc_auc")
        ci = p.get("roc_auc_ci95") or [None, None]
        if p.get("roc_auc") is not None and tfidf is not None and size is not None:
            out.append(
                f"The fine-tuned classifier ranks human-commented changes better than its "
                f"baselines: ROC-AUC {p['roc_auc']:.3f} (95% CI {ci[0]:.3f}-{ci[1]:.3f}), against "
                f"TF-IDF {tfidf:.3f} and size {size:.3f} (n = {p.get('n')}). This is a proxy "
                "label, and review quality was not measured."
            )
    risk = tables.get("risk")
    if _size_beats_risk(risk):
        out.append(
            f"Risk model v2 does not beat the size baseline: ROC-AUC "
            f"{_value(risk, 'Risk model v2', 'roc_auc'):.3f} against "
            f"{_value(risk, 'Size only', 'roc_auc'):.3f}."
        )
    retrieval = tables.get("retrieval")
    rag = next((r for r in _ok(retrieval) if r.label.startswith("RAG")), None)
    rnd = _value(retrieval, "Random", "recall_at_10")
    if rag is not None and rnd is not None and rag.values.get("recall_at_10") is not None:
        out.append(
            f"Retrieval finds call-graph neighbours far better than random: Recall@10 "
            f"{rag.values['recall_at_10']:.3f} against {rnd:.3f}. That is retrieval quality, not "
            "review accuracy."
        )
    return out


def build_status(
    runs: list[SavedRun], results_dir: Path, tables: list[ComparisonTable]
) -> EvaluationStatus:
    by_id = {t.id: t for t in tables}
    items = _detection_items(by_id) + _method_items(by_id, runs) + _other_items(by_id, runs)
    return EvaluationStatus(
        items=items + _pending(runs),
        limitations=LIMITATIONS,
        findings=_findings(by_id, runs),
        unfinished_runs=unfinished_runs(results_dir),
    )
