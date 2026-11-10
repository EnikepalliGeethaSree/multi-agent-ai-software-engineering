"""Part 3.8: the fine-tuned classifier as a hunk-risk ranker. SAVED-SCORE SECONDARY ANALYSIS.

The hunk-risk samples are the CodeReviewer cls test split, which also holds the classifier's
held-out test set. That test set must not be used for new scoring, training, threshold tuning or
model selection. So this analysis only *reads* scores that already exist:

- risk v2 and change size from the saved hunk-risk run (`hunkrisk_cls_test`), and
- the classifier score from its single saved test run (`classifier_cls_test`),

and compares them on the changes both runs scored that are in the repository-disjoint subset.
Nothing is re-run. The result is reported, never used to pick a default: risk v2 stays the
default ranker (decision recorded in docs/decisions.md, D40).
"""

from __future__ import annotations

from typing import Any

from marl_agents.evaluation.metrics.classification import bootstrap_ci, roc_auc
from marl_agents.evaluation.runners.change_risk import _precision_at_top
from marl_agents.evaluation.runs import SavedRun

FRACTIONS = (0.05, 0.10, 0.25)
RANKERS = {"risk_v2": "risk", "change_size": "size"}


def _auc_ci(labels: list[int], scores: list[float]) -> list[float] | None:
    pairs = list(zip(labels, scores, strict=True))

    def stat(sample: list[tuple[int, float]]) -> float:
        auc = roc_auc([a for a, _ in sample], [b for _, b in sample])
        return auc if auc is not None else 0.5

    lo, hi = bootstrap_ci(pairs, stat, n_boot=300, seed=42)
    return [round(lo, 4), round(hi, 4)]


def compare_saved_rankers(hunk_run: SavedRun, classifier_run: SavedRun) -> dict[str, Any]:
    risk = {p["sample_id"]: p for p in hunk_run.predictions()}
    cls = {p["sample_id"]: p for p in classifier_run.predictions() if p.get("repo_disjoint")}
    common = sorted(set(risk) & set(cls))
    mismatched = [i for i in common if int(risk[i]["label"]) != int(cls[i]["label"])]
    usable = [i for i in common if i not in mismatched]
    labels = [int(cls[i]["label"]) for i in usable]
    scores: dict[str, list[float]] = {
        name: [float(risk[i][field]) for i in usable] for name, field in RANKERS.items()
    }
    scores["classifier_saved_score"] = [float(cls[i]["score"]) for i in usable]
    rows = {}
    for name, s in scores.items():
        rows[name] = {
            "auc": roc_auc(labels, s),
            "auc_ci95": _auc_ci(labels, s),
            "precision_at_top": {
                f"{int(f * 100)}%": _precision_at_top(labels, s, f) for f in FRACTIONS
            },
        }
    return {
        "label": "saved-score secondary analysis (test changes already used to evaluate the "
        "classifier; nothing re-scored; not used to choose a default)",
        "hunk_risk_run": hunk_run.name,
        "classifier_run": classifier_run.name,
        "classifier_repo_disjoint_changes": len(cls),
        "scored_by_both": len(common),
        "label_mismatches": len(mismatched),
        "n": len(usable),
        "positives": sum(labels),
        "base_rate": sum(labels) / len(labels) if labels else None,
        "rankers": rows,
        "default_ranker": "risk_v2 (unchanged)",
    }


def compare_md(r: dict[str, Any]) -> str:
    def f(x: float | None) -> str:
        return "N/A" if x is None else f"{x:.3f}"

    lines = [
        "# Classifier as a hunk-risk ranker (saved-score secondary analysis)",
        "",
        f"**{r['label']}.**",
        "",
        f"- Sources: hunk-risk run `{r['hunk_risk_run']}` (risk v2, change size) and classifier "
        f"test run `{r['classifier_run']}` (saved scores).",
        f"- Repository-disjoint classifier test changes: {r['classifier_repo_disjoint_changes']}; "
        f"scored by both runs: {r['scored_by_both']}; label mismatches excluded: "
        f"{r['label_mismatches']}; compared: n = {r['n']} ({r['positives']} commented, base rate "
        f"{f(r['base_rate'])}).",
        f"- Default ranker: {r['default_ranker']}. This comparison does not change it.",
        "",
        "| Ranker | ROC-AUC (95% CI) | Precision top 5% | top 10% | top 25% |",
        "|---|---:|---:|---:|---:|",
    ]
    names = {"risk_v2": "Risk v2 (shipped)", "change_size": "Change size",
             "classifier_saved_score": "Fine-tuned classifier (saved scores)"}  # fmt: skip
    for key, row in r["rankers"].items():
        ci = row["auc_ci95"]
        p = row["precision_at_top"]
        lines.append(
            f"| {names[key]} | {f(row['auc'])} ({ci[0]:.3f}-{ci[1]:.3f}) | {f(p['5%'])} | "
            f"{f(p['10%'])} | {f(p['25%'])} |"
        )
    lines += [
        "",
        f"Random ranking: AUC 0.500, precision at any cut = base rate {f(r['base_rate'])}. "
        "AUC intervals: percentile bootstrap, 300 resamples, seed 42.",
    ]
    return "\n".join(lines) + "\n"
