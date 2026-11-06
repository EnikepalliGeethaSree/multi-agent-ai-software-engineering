"""Configuration comparison tables for the detection benchmarks: planted issues and CodeReviewer.

CodeReviewer comparisons are *paired*: every configuration is scored on the same samples. The
reference sample set is the one of the latest ablation group (else the latest LLM run, else the
latest run). A run whose sample set contains the reference set is restricted to it (each sample is
reviewed independently, and static analysis is deterministic). Samples a configuration failed on
(D22) are removed from every configuration, so all rows share one denominator. Metrics are then
recomputed from the saved predictions with the same functions the runner uses.
"""

from __future__ import annotations

from typing import Any

from marl_agents.core.schemas import Severity
from marl_agents.evaluation.comparison.common import (
    ALL_CONFIGS,
    CMD,
    LLM_CONFIG,
    compare,
    config_row,
    fairness_checks,
    fill_mean,
    is_mock,
    not_run_row,
    pick,
    prf,
)
from marl_agents.evaluation.comparison.models import Column, ComparisonTable, FairnessCheck, Row
from marl_agents.evaluation.configurations import ORDER
from marl_agents.evaluation.metrics import binary_metrics, corpus_bleu_avg, roc_auc
from marl_agents.evaluation.metrics.text import chrf, rouge_l
from marl_agents.evaluation.runners.code_review import CROSS_HUNK_RULES
from marl_agents.evaluation.runs import SavedRun

# ---- planted issues ------------------------------------------------------------------------------

PLANTED_COLUMNS = [
    Column(key="precision", label="Precision", metric="precision"),
    Column(key="recall", label="Recall", metric="recall"),
    Column(key="f1", label="F1", metric="f1"),
    Column(key="roc_auc", label="ROC-AUC", metric="roc_auc"),
    Column(key="tp", label="TP", digits=0),
    Column(key="fp", label="FP", digits=0),
    Column(key="fn", label="FN", digits=0),
    Column(key="recall_static", label="Recall (static-detectable)", metric="recall"),
    Column(key="recall_llm", label="Recall (semantic / LLM-only)", metric="recall"),
    Column(key="clean_fp", label="FP in clean file", digits=0),
    Column(key="line_error", label="Mean line error", digits=2),
]
PLANTED_AUC_NA = (
    "not applicable: the planted suite labels positives only (no scored negative cases), so a "
    "ROC curve is undefined"
)


def planted_complete(run: SavedRun) -> bool:
    if "complete" in run.metrics:
        return bool(run.metrics["complete"])
    return not int((run.metrics.get("pipeline") or {}).get("units_failed", 0) or 0)


def planted_values(m: dict[str, Any]) -> dict[str, float | int | None]:
    d = m["detection"]
    tp = int(d.get("tp", d.get("defect_true_positives", 0)))
    fp = int(d.get("fp", d.get("defect_findings", 0) - tp))
    fn = int(d.get("fn", d["expected"] - d["matched"]))
    precision, _, _ = prf(tp, fp, fn)
    recall = d["matched"] / d["expected"] if d["expected"] else None
    f1 = None
    if precision is not None and recall is not None:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "roc_auc": None,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall_static": d.get("recall_static"),
        "recall_llm": d.get("recall_llm"),
        "clean_fp": d.get("negative_file_false_positives"),
        "line_error": d.get("mean_line_error"),
    }


def planted_chosen(runs: list[SavedRun]) -> dict[str, list[SavedRun]]:
    planted = [r for r in runs if r.kind == "planted" and r.configuration and not is_mock(r)]
    return {
        key: pick(planted, key, lambda r: planted_complete(r) and "detection" in r.metrics)
        for key in ORDER
    }


def planted_table(runs: list[SavedRun]) -> ComparisonTable:
    planted = [r for r in runs if r.kind == "planted" and r.configuration and not is_mock(r)]
    chosen = planted_chosen(runs)
    rows: list[Row] = []
    for key in ORDER:
        sel = chosen[key]
        if not sel:
            partial = [r.name for r in planted if r.configuration.key == key]  # type: ignore[union-attr]
            cmd = f"{CMD} planted --configuration {key}" + (
                f" {LLM_CONFIG}" if key != "static_only" else ""
            )
            row = not_run_row(key, cmd)
            if partial:
                row.status = "incomplete"
                row.na = {"*": "only incomplete runs (an LLM review unit failed)"}
                row.run_ids = partial
            rows.append(row)
            continue
        row = config_row(key)
        fill_mean(row, [planted_values(r.metrics) for r in sel], PLANTED_COLUMNS)
        row.na["roc_auc"] = PLANTED_AUC_NA
        row.n = sel[0].metrics["detection"]["expected"]
        row.n_failed = 0
        row.n_runs = len(sel)
        row.model = sel[0].model
        row.run_ids = [r.name for r in sel]
        newer = [r.name for r in planted if r.configuration.key == key and r.stamp > sel[-1].stamp]  # type: ignore[union-attr]
        if newer:
            row.notes.append(f"newer incomplete run(s) ignored: {', '.join(newer)}")
        rows.append(row)
    fingerprints = {r.fingerprint for rs in chosen.values() for r in rs if r.fingerprint}
    same = FairnessCheck(
        name="Same samples (answer key)",
        ok=len(fingerprints) <= 1,
        detail="one fixture repository and answer key for every configuration"
        if len(fingerprints) <= 1
        else "answer key changed between runs",
    )
    return ComparisonTable(
        id="planted",
        section="1. Planted issues",
        title="Planted-issue benchmark: detection by configuration",
        about="17 hand-labelled issues in a fixture repository (16 detectable by a rule, 1 "
        "needing semantic reasoning) plus a clean negative-control file.",
        columns=PLANTED_COLUMNS,
        rows=rows,
        conditions={
            "answer key": "tests/fixtures/repos/planted_expected.json (17 issues)",
            "negative control": "shop/utils.py",
            "matching": "same file, start within +-2 lines, compatible category",
            "precision counts": "defect findings only (bug, security, error handling, edge case)",
        },
        fairness=fairness_checks(chosen, same),
        observations=_planted_observations(rows),
        notes=[
            "Precision TP = defect findings that match a planted issue; recall TP = planted "
            "issues detected (the project's existing definitions).",
            "Precision is N/A, not 1.0, when a configuration reports no defect findings at all.",
            f"Run all four together: {CMD} ablation --benchmark planted --configurations "
            f"{ALL_CONFIGS} {LLM_CONFIG}",
        ],
    )


def _planted_observations(rows: list[Row]) -> list[str]:
    by = {r.configuration.key: r for r in rows if r.configuration and r.status == "ok"}
    out: list[str] = []
    for metric in ("recall", "precision"):
        for a, b in (("static_only", "static_llm"), ("static_llm", "static_llm_rag"),
                     ("static_only", "llm_only")):  # fmt: skip
            if a in by and b in by:
                s = compare(
                    metric, by[a].label, by[a].values.get(metric), by[b].label,
                    by[b].values.get(metric),
                )  # fmt: skip
                if s:
                    out.append(s)
    for row in by.values():
        r_llm = row.values.get("recall_llm")
        if r_llm is not None:
            out.append(
                f"{row.label}: semantic (LLM-only) issue recall {r_llm:.3f} "
                "(the suite has a single such issue, so this is 0 or 1 per run)."
            )
    return out


# ---- CodeReviewer --------------------------------------------------------------------------------

CLS_COLUMNS = [
    Column(key="precision", label="Precision", metric="precision", group="RAW"),
    Column(key="recall", label="Recall", metric="recall", group="RAW"),
    Column(key="f1", label="F1", metric="f1", group="RAW"),
    Column(key="roc_auc", label="ROC-AUC", metric="roc_auc", group="RAW"),
    Column(key="adj_precision", label="Precision", metric="precision", group="ADJUSTED"),
    Column(key="adj_recall", label="Recall", metric="recall", group="ADJUSTED"),
    Column(key="adj_f1", label="F1", metric="f1", group="ADJUSTED"),
    Column(key="adj_roc_auc", label="ROC-AUC", metric="roc_auc", group="ADJUSTED"),
]
MSG_COLUMNS = [
    Column(key="bleu4", label="BLEU-4", metric="bleu4", digits=2),
    Column(key="rouge_l", label="ROUGE-L", metric="rouge_l", digits=2),
    Column(key="chrf", label="chrF", metric="chrf", digits=2),
    Column(key="coverage", label="Coverage", metric="coverage"),
]
LOW = Severity.LOW.rank


def _cls_scores(findings: list[dict[str, Any]]) -> tuple[int, float]:
    """(flag, score) exactly as the runner computes them, from the compact saved findings."""
    flag = int(any(Severity(f["severity"]).rank >= LOW for f in findings))
    score = max(
        (Severity(f["severity"]).rank + float(f["confidence"]) for f in findings), default=0.0
    )
    return flag, score / 5.0


def cls_metrics(preds: list[dict[str, Any]]) -> dict[str, float | int | None]:
    y = [int(p["label"]) for p in preds]
    raw = [_cls_scores(p.get("findings", [])) for p in preds]
    adj = [
        _cls_scores([f for f in p.get("findings", []) if f.get("rule") not in CROSS_HUNK_RULES])
        for p in preds
    ]
    out: dict[str, float | int | None] = {}
    for prefix, scored in (("", raw), ("adj_", adj)):
        bm = binary_metrics(y, [f for f, _ in scored])
        p, r, f1 = prf(bm.tp, bm.fp, bm.fn)
        out.update({f"{prefix}precision": p, f"{prefix}recall": r, f"{prefix}f1": f1})
        out[f"{prefix}roc_auc"] = roc_auc(y, [s for _, s in scored])
    return out


def msg_metrics(preds: list[dict[str, Any]]) -> dict[str, float | int | None]:
    refs = [str(p.get("reference") or "") for p in preds]
    hyps = [str(p.get("comment") or "") for p in preds]
    n = len(preds)
    if not n:
        return {"bleu4": None, "rouge_l": None, "chrf": None, "coverage": None}
    return {
        "bleu4": corpus_bleu_avg(refs, hyps),
        "rouge_l": 100 * sum(rouge_l(a, b) for a, b in zip(refs, hyps, strict=True)) / n,
        "chrf": 100 * sum(chrf(a, b) for a, b in zip(refs, hyps, strict=True)) / n,
        "coverage": sum(1 for h in hyps if h) / n,
    }


def _cr_command(task: str, key: str, limit: int | None = 40, seed: int | None = 42) -> str:
    """Command for a missing row; reuses the reference sample set (same limit and seed)."""
    if key == "static_only" and limit is None:
        return f"{CMD} codereviewer --task {task} --configuration static_only"
    lim = f" --limit {limit}" if limit else ""
    return (
        f"{CMD} codereviewer --task {task}{lim} --seed {seed if seed is not None else 42} "
        f"--configuration {key}" + (f" --workers 1 {LLM_CONFIG}" if key != "static_only" else "")
    )


def codereviewer_tables(runs: list[SavedRun], task: str) -> list[ComparisonTable]:
    cand = [
        r for r in runs
        if r.kind == "codereviewer" and r.task == task and r.split == "test"
        and r.configuration and not is_mock(r) and r.metrics.get("n_evaluated")
    ]  # fmt: skip
    # Runs in which every sample failed (e.g. the LLM quota ran out): shown, never scored.
    all_failed = [
        r for r in runs
        if r.kind == "codereviewer" and r.task == task and r.split == "test"
        and r.configuration and not is_mock(r) and r.metrics.get("n_evaluated") == 0
    ]  # fmt: skip
    columns = CLS_COLUMNS if task == "cls" else MSG_COLUMNS
    compute = cls_metrics if task == "cls" else msg_metrics
    title = (
        "CodeReviewer: does this change need a review comment? (classification)"
        if task == "cls"
        else "CodeReviewer: review comment generation"
    )
    section = "2. CodeReviewer classification" if task == "cls" else "3. Review comment generation"
    tid = f"codereviewer_{task}"
    if not cand:
        empty = [
            not_run_row(k, _cr_command(task, k, None if k == "static_only" else 40)) for k in ORDER
        ]
        return [ComparisonTable(id=tid, section=section, title=title, columns=columns, rows=empty)]
    grouped = [r for r in cand if r.group_id]
    with_llm = [r for r in cand if r.configuration is not None and r.configuration.llm]
    ref_run = (grouped or with_llm or cand)[-1]
    ref_ids = set(ref_run.sample_ids)
    ref_limit = ref_run.experiment.get("limit", ref_run.meta.get("limit"))
    ref_seed = ref_run.experiment.get("sampling_seed", ref_run.meta.get("seed"))

    def choose(key: str) -> list[SavedRun]:
        """The reference group's own run(s) of `key`; else the latest run covering its samples."""
        if ref_run.group_id:
            same = [r for r in cand if r.group_id == ref_run.group_id and r.configuration
                    and r.configuration.key == key]  # fmt: skip
            if same:
                return same
        return pick(cand, key, lambda r: bool(ref_ids) and set(r.sample_ids) >= ref_ids)

    chosen = {key: choose(key) for key in ORDER}
    preds: dict[str, dict[str, dict[str, Any]]] = {}
    for rs in chosen.values():
        for r in rs:
            preds[r.name] = {
                p["sample_id"]: p for p in r.predictions() if p["sample_id"] in ref_ids
            }
    common = set(ref_ids)
    for p in preds.values():
        common &= set(p)
    rows: list[Row] = []
    for key in ORDER:
        sel = chosen[key]
        if not sel:
            rows.append(
                _failed_or_not_run(_cr_command(task, key, ref_limit, ref_seed), key, all_failed)
            )
            continue
        row = config_row(key)
        ordered = sorted(common)
        fill_mean(row, [compute([preds[r.name][i] for i in ordered]) for r in sel], columns)
        row.n = len(common)
        row.n_failed = sum(len(ref_ids) - len(preds[r.name]) for r in sel)
        row.n_runs = len(sel)
        row.model = sel[0].model
        row.run_ids = [r.name for r in sel]
        for col in columns:
            if row.values.get(col.key) is None:
                row.na[col.key] = "undefined on these samples (zero denominator or one class only)"
        covers = len(set(sel[0].sample_ids))
        if covers > len(ref_ids):
            row.notes.append(
                f"restricted to the {len(ref_ids)} reference samples (the run covers {covers})"
            )
        rows.append(row)
    same = FairnessCheck(
        name="Same samples",
        ok=True,
        detail=f"{len(common)} samples evaluated by every configuration "
        f"({len(ref_ids)} requested; reference run {ref_run.name})",
    )
    exp = ref_run.experiment
    conditions = {
        "dataset": "CodeReviewer, test split, Python only",
        "requested samples": len(ref_ids),
        "samples in every row": len(common),
        "sampling seed": exp.get("sampling_seed", ref_run.meta.get("seed")),
        "limit": exp.get("limit", ref_run.meta.get("limit")),
    }
    if task == "cls":
        conditions["flagged"] = "at least one finding of severity >= low"
        conditions["score (ROC-AUC)"] = "highest finding priority / 5"
        conditions["ADJUSTED"] = "excludes " + ", ".join(sorted(CROSS_HUNK_RULES))
    else:
        conditions["comment"] = "top finding's title + recommendation"
        conditions["scale"] = "BLEU-4, ROUGE-L, chrF: 0-100; coverage: 0-1"
    notes = [
        f"Run all four on one sample set: {CMD} ablation --benchmark codereviewer --task {task} "
        f"--limit {ref_limit or 40} --seed {ref_seed if ref_seed is not None else 42} "
        f"--configurations {ALL_CONFIGS} {LLM_CONFIG}",
    ]
    if task == "cls":
        notes.insert(0, "RAW counts every finding. ADJUSTED drops the rules that cannot be judged "
                     "from one hunk (imports/names defined in the commit's other hunks); both are "
                     "always reported, neither replaces the other.")  # fmt: skip
    if len(common) < 30:
        notes.append(f"n = {len(common)}: far too few samples for any conclusion; this table only "
                     "shows that the pipeline runs end to end.")  # fmt: skip
    elif len(common) < 100:
        notes.append(f"n = {len(common)}: differences of a few points are within sampling noise "
                     "(see the bootstrap CIs in each run's summary).")  # fmt: skip
    tables = [
        ComparisonTable(
            id=tid,
            section=section,
            title=title,
            about="Paired comparison: every row is scored on the same samples.",
            columns=columns,
            rows=rows,
            conditions=conditions,
            fairness=fairness_checks(chosen, same),
            observations=_cr_observations(rows, task),
            notes=notes,
        )
    ]
    full = _full_static_table(cand, task, len(ref_ids), columns, section)
    if full is not None:
        tables.append(full)
    return tables


def _failed_or_not_run(command: str, key: str, all_failed: list[SavedRun]) -> Row:
    row = not_run_row(key, command)
    failed = [r for r in all_failed if r.configuration and r.configuration.key == key]
    if failed:
        run = failed[-1]
        reasons = run.metrics.get("failure_reasons") or {}
        why = ", ".join(f"{k}: {v}" for k, v in reasons.items()) or "see errors.jsonl"
        row.status = "incomplete"
        row.na = {"*": f"every sample failed in run {run.name} ({why}); nothing to score"}
        row.n, row.n_failed, row.run_ids = 0, run.metrics.get("n_failed"), [run.name]
        row.model = run.model
    return row


def _cr_observations(rows: list[Row], task: str) -> list[str]:
    by = {r.configuration.key: r for r in rows if r.configuration and r.status == "ok"}
    if any((r.n or 0) < 30 for r in by.values()):
        return []  # comparisons on a handful of samples would read as findings; see notes
    metrics = ("f1", "roc_auc") if task == "cls" else ("chrf", "coverage")
    names = {"f1": "F1 (raw)", "roc_auc": "ROC-AUC (raw)", "chrf": "chrF", "coverage": "coverage"}
    out: list[str] = []
    for metric in metrics:
        for a, b in (("static_only", "static_llm"), ("static_llm", "static_llm_rag"),
                     ("static_only", "llm_only")):  # fmt: skip
            if a in by and b in by:
                s = compare(names[metric], by[a].label, by[a].values.get(metric), by[b].label,
                            by[b].values.get(metric), 2 if metric == "chrf" else 3)  # fmt: skip
                if s:
                    out.append(s)
    if task == "cls":
        for row in by.values():
            auc = row.values.get("roc_auc")
            if isinstance(auc, float):
                side = "above" if auc > 0.5 else ("below" if auc < 0.5 else "at")
                out.append(f"{row.label}: raw ROC-AUC {auc:.3f} is {side} chance (0.5).")
    return out


def _full_static_table(
    cand: list[SavedRun], task: str, n_ref: int, columns: list[Column], section: str
) -> ComparisonTable | None:
    static = [r for r in cand if r.configuration.key == "static_only" and len(r.sample_ids) > n_ref]  # type: ignore[union-attr]
    if not static:
        return None
    run = static[-1]
    compute = cls_metrics if task == "cls" else msg_metrics
    row = config_row("static_only")
    row.values = compute(run.predictions())
    row.n, row.n_failed, row.n_runs = run.metrics.get("n_evaluated"), run.metrics.get("n_failed"), 1
    row.run_ids = [run.name]
    return ComparisonTable(
        id=f"codereviewer_{task}_full",
        section=section,
        title=f"Static Only on the full Python test split (n = {row.n})",
        about="Static analysis is cheap enough to run on every sample; LLM configurations are "
        "limited by API quota, so they are compared on the subset above.",
        columns=columns,
        rows=[row],
        conditions={"dataset": "CodeReviewer, test split, Python only (all samples)"},
    )
