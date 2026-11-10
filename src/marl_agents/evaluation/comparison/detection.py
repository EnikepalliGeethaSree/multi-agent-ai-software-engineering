"""Configuration comparison tables for the detection benchmarks: planted issues and CodeReviewer.

CodeReviewer comparisons are *paired*: every configuration is scored on the same samples. The
reference sample set is the one of the latest ablation group (else the latest LLM run, else the
latest run). A run whose sample set contains the reference set is restricted to it (each sample is
reviewed independently, and static analysis is deterministic). Samples a configuration failed on
(D22) are removed from every configuration, so all rows share one denominator. Metrics are then
recomputed from the saved predictions with the same functions the runner uses.
"""

from __future__ import annotations

import json
from typing import Any

from marl_agents.config import PROJECT_ROOT
from marl_agents.core.schemas import Severity
from marl_agents.evaluation.comparison.common import (
    ALL_CONFIGS,
    CMD,
    LLM_CONFIG,
    MIN_PAIRED_N,
    compare,
    config_row,
    fairness_checks,
    fill_mean,
    is_mock,
    not_run_row,
    pick,
    prf,
    provider_badge,
)
from marl_agents.evaluation.comparison.models import Column, ComparisonTable, FairnessCheck, Row
from marl_agents.evaluation.comparison.statistics import (
    codereviewer_statistics,
    planted_statistics,
)
from marl_agents.evaluation.configurations import ORDER
from marl_agents.evaluation.metrics import binary_metrics, corpus_bleu_avg, roc_auc
from marl_agents.evaluation.metrics.detection import DEFECT_CATEGORIES
from marl_agents.evaluation.metrics.text import chrf, rouge_l
from marl_agents.evaluation.runners.code_review import CROSS_HUNK_RULES
from marl_agents.evaluation.runs import SavedRun

# ---- planted issues ------------------------------------------------------------------------------

ISSUES = "Labelled issues"
FINDINGS = "Defect findings"
PLANTED_COLUMNS = [
    Column(key="recall", label="Issue recall", metric="issue_recall", group=ISSUES),
    Column(key="issues_found", label="Found", digits=0, group=ISSUES),
    Column(key="fn", label="Missed", digits=0, group=ISSUES),
    Column(key="recall_static", label="Rule-detectable recall", metric="issue_recall",
           group=ISSUES),
    Column(key="recall_llm", label="Semantic recall", metric="issue_recall", group=ISSUES),
    Column(key="precision", label="Precision", metric="defect_precision", group=FINDINGS),
    Column(key="tp", label="Correct", digits=0, group=FINDINGS),
    Column(key="fp", label="False positives", digits=0, group=FINDINGS),
    Column(key="clean_fp", label="FP in clean file", digits=0, group=FINDINGS),
    Column(key="f1", label="F1 (mixed basis)", metric="mixed_f1", group="Other"),
    Column(key="roc_auc", label="ROC-AUC", metric="roc_auc", group="Other"),
    Column(key="line_error", label="Mean line error", digits=2, group="Other"),
]  # fmt: skip
PLANTED_AUC_NA = (
    "not applicable: the planted suite labels positives only (no scored negative cases), so a "
    "ROC curve is undefined"
)


def answer_key_counts() -> dict[str, int] | None:
    """Counts from the answer key itself, so the explanation cannot drift from the benchmark."""
    path = PROJECT_ROOT / "tests" / "fixtures" / "repos" / "planted_expected.json"
    try:
        issues = json.loads(path.read_text(encoding="utf-8"))["issues"]
    except (OSError, ValueError, KeyError):
        return None
    defect = {str(getattr(c, "value", c)) for c in DEFECT_CATEGORIES}
    return {
        "total": len(issues),
        "defect": sum(1 for i in issues if i.get("category") in defect),
        "other": sum(1 for i in issues if i.get("category") not in defect),
        "static": sum(1 for i in issues if i.get("detectable_by") == "static"),
        "semantic": sum(1 for i in issues if i.get("detectable_by") == "llm"),
    }


def _stability(planted: list[SavedRun], chosen: dict[str, list[SavedRun]]) -> list[str]:
    """Complete repeats of the same configuration and model. The table shows only the latest."""
    out = []
    for key in ORDER:
        sel = chosen[key]
        if not sel or not sel[0].model:
            continue
        same = [
            r
            for r in planted
            if r.configuration is not None and r.configuration.key == key
            and r.model == sel[0].model and planted_complete(r) and "detection" in r.metrics
        ]  # fmt: skip
        if len(same) < 2:
            continue
        scores = [
            f"{r.metrics['detection']['matched']}/{r.metrics['detection']['expected']}"
            for r in same
        ]
        label = sel[0].configuration.label  # type: ignore[union-attr]
        detail = ", ".join(f"{r.stamp[:8]}: {s}" for r, s in zip(same, scores, strict=True))
        if len(set(scores)) > 1:
            out.append(
                f"{label} on {sel[0].model} varies between complete runs ({detail}). The table "
                "shows the latest, so 1.000 is not a stable result."
            )
        else:
            out.append(f"{label} on {sel[0].model} gave the same recall in {len(same)} runs.")
    return out


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
        "issues_found": int(d["matched"]),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall_static": d.get("recall_static"),
        "recall_llm": d.get("recall_llm"),
        "clean_fp": d.get("negative_file_false_positives"),
        "line_error": d.get("mean_line_error"),
    }


def planted_chosen(runs: list[SavedRun]) -> dict[str, list[SavedRun]]:
    """Latest valid run per configuration, then aligned on one ablation group: every configuration
    that the newest LLM run's group covers is taken from that group, so a later stand-alone
    static run (or another model's ablation) cannot replace one row of a group."""
    planted = [r for r in runs if r.kind == "planted" and r.configuration and not is_mock(r)]

    def valid(r: SavedRun) -> bool:
        return planted_complete(r) and "detection" in r.metrics

    chosen = {key: pick(planted, key, valid) for key in ORDER}
    llm_runs = [rs[-1] for rs in chosen.values() if rs and rs[-1].configuration.llm]  # type: ignore[union-attr]
    newest = max(llm_runs, key=lambda r: r.stamp, default=None)
    if newest is not None and newest.group_id:
        for key in ORDER:
            same = [r for r in planted if r.configuration.key == key  # type: ignore[union-attr]
                    and r.group_id == newest.group_id and valid(r)]  # fmt: skip
            if same:
                chosen[key] = same
    return chosen


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
    key_counts = answer_key_counts() or {}
    selected = [r for rs in chosen.values() for r in rs]
    badge = provider_badge(selected)
    n_issues = key_counts.get("total", 17)
    gap = (
        f"Why 14 correct findings can sit beside 17 issues found: the answer key has "
        f"{key_counts.get('defect')} defect-class issues and {key_counts.get('other')} others "
        "(quality, maintainability, standards). Found counts issues of every category. Correct "
        "counts findings of the defect classes only. They are separate counts, so Correct + "
        "Missed need not equal the number of issues."
        if key_counts
        else "Found counts issues of every category. Correct counts defect-class findings only."
    )
    return ComparisonTable(
        id="planted",
        section="1. Planted issues",
        title="Planted-issue benchmark: detection by configuration",
        about="17 hand-labelled issues in a fixture repository (16 detectable by a rule, 1 "
        "needing semantic reasoning) plus a clean negative-control file.",
        badges=["Complete", f"Small benchmark (n = {n_issues})", *([badge] if badge else [])],
        warning=f"Small benchmark: {n_issues} issues written by the project team. It is a "
        "regression check, and a score of 1.000 is not evidence of 100% bug detection in real "
        "code.",
        columns=PLANTED_COLUMNS,
        rows=rows,
        conditions={
            "answer key": "tests/fixtures/repos/planted_expected.json (17 issues)",
            "negative control": "shop/utils.py",
            "matching": "same file, start within +-2 lines, compatible category",
            "precision counts": "defect findings only (bug, security, error handling, edge case)",
        },
        fairness=fairness_checks(chosen, same),
        observations=[*_planted_observations(rows), *_stability(planted, chosen)],
        statistics=planted_statistics(rows, chosen),
        notes=[
            gap,
            f"Rule-detectable recall covers {key_counts.get('static', 16)} issues. Semantic recall "
            f"covers {key_counts.get('semantic', 1)}, so it can only be 0 or 1 in a run.",
            "F1 here mixes defect precision and issue recall, which have different denominators. "
            "Treat it as a summary of this benchmark, not a standard F1.",
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
    if len(common) < MIN_PAIRED_N:
        for row in rows:
            for metric in ("roc_auc", "adj_roc_auc"):
                if metric in row.values:
                    row.values[metric] = None
                    row.na[metric] = (
                        f"not reported: {len(common)} paired samples are too few for ROC-AUC "
                        f"(minimum {MIN_PAIRED_N})"
                    )
    scored = [r for r in rows if r.status == "ok"]
    missing = [r for r in rows if r.status != "ok"]
    evaluated = []
    for row in rows:
        letter = row.configuration.letter if row.configuration else "?"
        if row.status == "ok":
            evaluated.append(f"{letter} {len(preds[row.run_ids[0]])}/{len(ref_ids)}")
        else:
            evaluated.append(f"{letter} {'not run' if row.status == 'not_run' else 0}")
    same = FairnessCheck(
        name="Same samples",
        ok=not missing,
        detail=(
            f"{len(common)} of {len(ref_ids)} requested samples evaluated by "
            f"{_names(scored)}; no scored samples for {_names(missing)} "
            f"(reference run {ref_run.name})"
            if missing
            else f"{len(common)} samples evaluated by every configuration "
            f"({len(ref_ids)} requested; reference run {ref_run.name})"
        ),
    )
    exp = ref_run.experiment
    conditions = {
        "dataset": "CodeReviewer, test split, Python only",
        "paired samples": f"{len(common)} of {len(ref_ids)} requested",
        "evaluated per configuration": ", ".join(evaluated),
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
    if len(common) < MIN_PAIRED_N:
        notes.append(f"n = {len(common)}: far too few samples for any conclusion; this table only "
                     "shows that the pipeline runs end to end. ROC-AUC is not reported. Each run's "
                     "saved scores are unchanged in its predictions.jsonl.")  # fmt: skip
    elif len(common) < 100:
        notes.append(f"n = {len(common)}: differences of a few points are within sampling noise "
                     "(see the bootstrap CIs in each run's summary).")  # fmt: skip
    for row in rows:
        if row.n_failed and row.run_ids:
            run = next((r for r in [*cand, *all_failed] if r.name == row.run_ids[0]), None)
            reasons = (run.metrics.get("failure_reasons") or {}) if run else {}
            why = ", ".join(f"{k}: {v}" for k, v in reasons.items()) or "see errors.jsonl"
            notes.append(f"{row.label}: {row.n_failed} of {len(ref_ids)} samples failed ({why}).")
    checks = fairness_checks(chosen, same)
    badge = provider_badge(r for rs in chosen.values() for r in rs)
    warning, badges = _cr_warning(rows, checks, len(common), len(ref_ids), task)
    if task == "msg" and not (_scored(rows, "static_llm") and _scored(rows, "static_llm_rag")):
        notes.append("The effect of RAG on comment quality cannot be judged here: it needs "
                     "Static + LLM and Static + LLM + RAG on the same samples. Static Only vs "
                     "Static + LLM + RAG changes two things at once.")  # fmt: skip
    limit = ref_limit or len(ref_ids)
    notes.append(f"Gemini: set GEMINI_MODEL=gemini-3.6-flash first. Three LLM configurations on "
                 f"{limit} samples need at least {3 * limit} requests, and the free tier allows 20 "
                 "per day per model. Add --reuse-llm-cache and repeat the command each day: cached "
                 "replies carry it forward, and the run that finishes is complete.")  # fmt: skip
    if task == "cls":
        notes.append("That command reads the CodeReviewer cls test split, which contains the "
                     "CodeBERT classifier's held-out samples. It does not run the classifier, but "
                     "use --split valid for new work so that test set is not reused.")  # fmt: skip
    tables = [
        ComparisonTable(
            id=tid,
            section=section,
            title=title,
            about="Paired comparison: every row is scored on the same samples.",
            badges=[*badges, *([badge] if badge else [])],
            warning=warning,
            columns=columns,
            rows=rows,
            conditions=conditions,
            fairness=checks,
            observations=_cr_observations(rows, task),
            statistics=codereviewer_statistics(task, rows, preds, sorted(common)),
            notes=notes,
        )
    ]
    full = _full_static_table(cand, task, len(ref_ids), columns, section)
    if full is not None:
        tables.append(full)
    return tables


def _names(rows: list[Row]) -> str:
    return ", ".join(r.label for r in rows) or "none"


def _scored(rows: list[Row], key: str) -> bool:
    return any(r.configuration and r.configuration.key == key and r.status == "ok" for r in rows)


def _cr_warning(
    rows: list[Row], checks: list[FairnessCheck], n: int, requested: int, task: str
) -> tuple[str | None, list[str]]:
    missing = [r for r in rows if r.status != "ok"]
    if n < MIN_PAIRED_N:
        return (
            f"Preliminary: only {n} of {requested} requested samples are paired. No conclusion "
            "about any configuration can be drawn from this table, and ROC-AUC is not reported.",
            ["Preliminary"],
        )
    separate = any(c.name.startswith("Run together") and not c.ok for c in checks)
    prompts = any(c.name == "Same prompt versions" and c.ok is None for c in checks)
    reasons = []
    if missing:
        reasons.append(f"{_names(missing)} have no results")
    if separate:
        reasons.append("the rows were run separately")
    if prompts:
        reasons.append("prompt versions were not fully recorded")
    if not reasons:
        return None, ["Complete"]
    claim = " This table does not show that RAG improves comment quality." if task == "msg" else ""
    return f"Incomplete comparison: {'; '.join(reasons)}.{claim}", ["Incomplete"]


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
        "limited by API quota, so they are compared on the subset above. These samples are not "
        "paired with that subset, so do not compare this row with the table above.",
        badges=["Complete", "Static only, full test split", "Not paired"],
        columns=columns,
        rows=[row],
        conditions={"dataset": "CodeReviewer, test split, Python only (all samples)"},
    )
