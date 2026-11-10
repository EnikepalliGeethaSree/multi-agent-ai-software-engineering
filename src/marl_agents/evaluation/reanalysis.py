"""Extra metrics computed from saved predictions: no model is run and no decision is changed.

- `classifier_report`: PR-AUC (chance = positive base rate), MCC, balanced accuracy, precision at
  the top 10%, Brier score, and the always-positive and majority baselines, for the fine-tuned
  change classifier's single test run. The threshold is the one saved with that run, chosen on dev.
  The scores were produced once, when the test set was used; reading them again re-scores nothing.
- `static_baseline_report`: majority-class baseline, balanced accuracy and MCC for the static
  baseline on the full CodeReviewer test set, with all rules and without the rules that cannot be
  judged from one hunk (D-sensitivity, both always reported).

Each report names its source run so every number can be traced.
"""

from __future__ import annotations

from typing import Any

from marl_agents.core.schemas import Severity
from marl_agents.evaluation.metrics.classification import (
    always_positive,
    average_precision,
    balanced_accuracy,
    binary_metrics,
    brier_score,
    mcc,
    precision_at_fraction,
    roc_auc,
)
from marl_agents.evaluation.runners.code_review import CROSS_HUNK_RULES
from marl_agents.evaluation.runs import SavedRun
from marl_agents.evaluation.stats import wilson

LOW = Severity.LOW.rank


def _block(y: list[int], pred: list[int], scores: list[float] | None) -> dict[str, Any]:
    bm = binary_metrics(y, pred)
    base = sum(y) / len(y) if y else 0.0
    out: dict[str, Any] = {
        "n": len(y),
        "positives": sum(y),
        "positive_base_rate": base,
        "confusion": {"tp": bm.tp, "fp": bm.fp, "tn": bm.tn, "fn": bm.fn},
        "accuracy": bm.accuracy,
        "precision": bm.precision,
        "recall": bm.recall,
        "f1": bm.f1,
        "balanced_accuracy": balanced_accuracy(bm),
        "mcc": mcc(bm),
        "majority_baseline_accuracy": max(base, 1 - base),
        "always_positive": always_positive(y),
        "wilson_precision": wilson(bm.tp, bm.tp + bm.fp).model_dump(),
        "wilson_recall": wilson(bm.tp, bm.tp + bm.fn).model_dump(),
    }
    if scores is not None:
        top = precision_at_fraction(y, scores, 0.10)
        out.update(
            roc_auc=roc_auc(y, scores),
            pr_auc=average_precision(y, scores),
            pr_auc_chance=base,
            brier=brier_score(y, scores),
            precision_at_10pct=top[0] if top else None,
            top_10pct_items=top[1] if top else None,
        )
    return out


def classifier_report(run: SavedRun) -> dict[str, Any]:
    threshold = float(run.metrics["threshold"])
    preds = run.predictions()
    subsets = {
        "repo_disjoint": [p for p in preds if p.get("repo_disjoint")],
        "official_test": [p for p in preds if p.get("official_test")],
    }
    out: dict[str, Any] = {"source_run": run.name, "threshold": threshold,
                           "threshold_source": "chosen on dev before the test run"}  # fmt: skip
    for name, rows in subsets.items():
        if not rows:
            continue
        y = [int(p["label"]) for p in rows]
        scores = [float(p["score"]) for p in rows]
        out[name] = _block(y, [int(s >= threshold) for s in scores], scores)
    return out


def _flag(findings: list[dict[str, Any]], drop: frozenset[str] | set[str] = frozenset()) -> int:
    return int(
        any(Severity(f["severity"]).rank >= LOW for f in findings if f.get("rule") not in drop)
    )


def static_baseline_report(run: SavedRun) -> dict[str, Any]:
    preds = run.predictions()
    y = [int(p["label"]) for p in preds]
    return {
        "source_run": run.name,
        "flagged": "at least one finding of severity >= low",
        "all_rules": _block(y, [_flag(p.get("findings", [])) for p in preds], None),
        "without_single_hunk_rules": _block(
            y, [_flag(p.get("findings", []), set(CROSS_HUNK_RULES)) for p in preds], None
        ),
        "excluded_rules": sorted(CROSS_HUNK_RULES),
    }


def _f(x: float | None, digits: int = 3) -> str:
    return "N/A" if x is None else f"{x:.{digits}f}"


def _ci(d: dict[str, Any]) -> str:
    return "" if d.get("low") is None else f" ({d['low']:.3f}-{d['high']:.3f})"


def classifier_md(r: dict[str, Any]) -> str:
    lines = [
        "# Fine-tuned change classifier: extended test metrics",
        "",
        f"Source run `{r['source_run']}`. Threshold {r['threshold']} "
        f"({r['threshold_source']}). Computed from the saved scores of the single test run; "
        "nothing was re-scored.",
        "",
    ]
    for name, label in (("repo_disjoint", "Repository-disjoint test (primary)"),
                        ("official_test", "Official Python test (secondary)")):  # fmt: skip
        b = r.get(name)
        if not b:
            continue
        ap = b["always_positive"]
        c = b["confusion"]
        lines += [
            f"## {label}: n = {b['n']} ({b['positives']} positive, base rate "
            f"{b['positive_base_rate']:.3f})", "",
            "| Metric | Classifier | Baseline |", "|---|---:|---:|",
            f"| ROC-AUC | {_f(b['roc_auc'])} | 0.500 (random) |",
            f"| PR-AUC (average precision) | {_f(b['pr_auc'])} | {_f(b['pr_auc_chance'])} "
            "(positive base rate) |",
            f"| Precision | {_f(b['precision'])}{_ci(b['wilson_precision'])} | "
            f"{_f(ap['precision'])} (always positive) |",
            f"| Recall | {_f(b['recall'])}{_ci(b['wilson_recall'])} | 1.000 (always positive) |",
            f"| F1 | {_f(b['f1'])} | {_f(ap['f1'])} (always positive) |",
            f"| Accuracy | {_f(b['accuracy'])} | {_f(ap['accuracy'])} (always positive); "
            f"{_f(b['majority_baseline_accuracy'])} (majority class) |",
            f"| Balanced accuracy | {_f(b['balanced_accuracy'])} | 0.500 |",
            f"| MCC | {_f(b['mcc'])} | 0.000 |",
            f"| Precision at top 10% ({b['top_10pct_items']} changes) | "
            f"{_f(b['precision_at_10pct'])} | {_f(b['positive_base_rate'])} (base rate) |",
            f"| Brier score (lower is better) | {_f(b['brier'])} | "
            f"{_f(b['positive_base_rate'] * (1 - b['positive_base_rate']))} (constant base rate) |",
            "",
            f"Confusion matrix at the threshold: TP {c['tp']}, FP {c['fp']}, TN {c['tn']}, "
            f"FN {c['fn']}. Intervals in brackets are Wilson 95% intervals.", "",
        ]  # fmt: skip
    return "\n".join(lines)


def static_baseline_md(r: dict[str, Any]) -> str:
    lines = ["# Static baseline on the full CodeReviewer test set: extended metrics", "",
             f"Source run `{r['source_run']}`. Flagged = {r['flagged']}. Python only. "
             f"\"Without single-hunk rules\" excludes {', '.join(r['excluded_rules'])}.", "",
             "| Rule set | n | Accuracy | Balanced accuracy | MCC | Precision | Recall | F1 | "
             "Majority-class accuracy | Always-positive F1 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]  # fmt: skip
    for key, label in (("all_rules", "All rules"),
                       ("without_single_hunk_rules", "Without single-hunk rules")):  # fmt: skip
        b = r[key]
        lines.append(
            f"| {label} | {b['n']} | {_f(b['accuracy'])} | {_f(b['balanced_accuracy'])} | "
            f"{_f(b['mcc'])} | {_f(b['precision'])}{_ci(b['wilson_precision'])} | "
            f"{_f(b['recall'])}{_ci(b['wilson_recall'])} | {_f(b['f1'])} | "
            f"{_f(b['majority_baseline_accuracy'])} | {_f(b['always_positive']['f1'])} |"
        )
    return "\n".join(lines) + "\n"
