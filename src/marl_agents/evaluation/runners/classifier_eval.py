"""Independent evaluation of the fine-tuned change classifier.

Primary result: the repository-disjoint test set, whose projects the model and its tuning never
saw. The official Python test split is reported too, flagged, because it shares projects and some
patches with the validation split. Scores are computed once from the saved threshold; the test set
takes no part in training or in choosing that threshold.

Baselines on the same samples: the original system's static analysis (from its saved predictions,
so nothing is rerun), majority class, change size, and TF-IDF + logistic regression.

Each distinct change is scored once, so the two sets use identical scores, and every score is saved
to predictions.jsonl with the SHA-256 of the weights that produced it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from marl_agents.config import PROJECT_ROOT, Settings
from marl_agents.core.schemas import Severity
from marl_agents.evaluation.datasets import load_codereviewer
from marl_agents.evaluation.datasets.codereviewer import CodeReviewerSample
from marl_agents.evaluation.metrics import binary_metrics, bootstrap_ci, roc_auc
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners.code_review import CROSS_HUNK_RULES
from marl_agents.llm.classifier import TransformersChangeClassifier, change_text
from marl_agents.training.data import patch_key


def score_report(labels: list[int], scores: list[float], threshold: float) -> dict[str, Any]:
    """Every metric of the brief for one scorer on one sample set."""
    predicted = [int(s >= threshold) for s in scores]
    m = binary_metrics(labels, predicted)
    pairs = list(zip(labels, scores, strict=True))

    def auc_of(items: list[tuple[int, float]]) -> float:
        value = roc_auc([t for t, _ in items], [s for _, s in items])
        return value if value is not None else 0.5

    low, high = bootstrap_ci(pairs, auc_of, n_boot=300)
    tn, fp, fn, tp = m.tn, m.fp, m.fn, m.tp
    negatives = tn + fp
    positives = tp + fn
    auc = roc_auc(labels, scores)
    return {
        "n": m.n,
        "threshold": threshold,
        "accuracy": round(m.accuracy, 4),
        "precision": round(m.precision, 4),
        "recall": round(m.recall, 4),
        "f1": round(m.f1, 4),
        "roc_auc": None if auc is None else round(auc, 4),
        "roc_auc_ci95": [round(low, 4), round(high, 4)],
        "false_positive_rate": round(fp / negatives, 4) if negatives else None,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "class_wise": {
            "needs_review": {
                "precision": round(m.precision, 4),
                "recall": round(m.recall, 4),
                "support": positives,
            },
            "no_comment": {
                "precision": round(tn / (tn + fn), 4) if tn + fn else None,
                "recall": round(tn / negatives, 4) if negatives else None,
                "support": negatives,
            },
        },
    }


def _changed_lines(sample: CodeReviewerSample) -> float:
    return float(
        sum(
            1
            for ln in sample.patch.splitlines()
            if ln[:1] in {"+", "-"} and not ln.startswith(("+++", "---"))
        )
    )


def majority_report(labels: list[int]) -> dict[str, Any]:
    positive = sum(labels) >= len(labels) / 2
    return {
        "n": len(labels),
        "accuracy": round(max(sum(labels), len(labels) - sum(labels)) / len(labels), 4),
        "predicts": "needs_review" if positive else "no_comment",
    }


def latest_static_run(results_dir: Path) -> Path | None:
    """The newest full static-only classification run with its raw predictions."""
    runs = sorted(results_dir.glob("*_codereviewer_cls_test_static_only_n4196"))
    runs = [r for r in runs if (r / "predictions.jsonl").is_file()]
    return runs[-1] if runs else None


def static_report(run_dir: Path, sample_ids: set[str]) -> dict[str, Any] | None:
    """The original system on exactly these samples, from its saved predictions.

    Uses the adjusted rule set (cross-hunk rules removed), the form most favourable to static
    analysis, and the project's own definitions: flagged = a finding of severity >= low; score =
    highest finding priority / 5. Scores are compared with threshold 0.5 only through AUC.
    """
    low = Severity("low").rank
    labels: list[int] = []
    scores: list[float] = []
    flags: list[int] = []
    with (run_dir / "predictions.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("sample_id") not in sample_ids or "label" not in row:
                continue
            kept = [f for f in row.get("findings", []) if f.get("rule") not in CROSS_HUNK_RULES]
            ranks = [Severity(f["severity"]).rank for f in kept]
            priorities = [
                Severity(f["severity"]).rank + float(f.get("confidence", 0.0)) for f in kept
            ]
            labels.append(int(row["label"]))
            flags.append(int(any(r >= low for r in ranks)))
            scores.append(max(priorities, default=0.0) / 5.0)
    if not labels:
        return None
    report = score_report(labels, [float(f) for f in flags], 0.5)
    auc = roc_auc(labels, scores)
    report["roc_auc"] = None if auc is None else round(auc, 4)
    report["roc_auc_ci95"] = None
    report["source_run"] = run_dir.name
    report["rule_set"] = "adjusted (cross-hunk rules removed)"
    return report


def _deduplicated(samples: list[CodeReviewerSample]) -> list[CodeReviewerSample]:
    seen: set[str] = set()
    out = []
    for s in samples:
        key = patch_key(s.patch)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _evaluate(
    samples: list[CodeReviewerSample],
    threshold: float,
    scored: dict[str, float],
    baseline: Any | None,
    baseline_threshold: float,
    static_run: Path | None,
) -> dict[str, Any]:
    labels = [s.label for s in samples]
    texts = [change_text(s.patch) for s in samples]
    report = score_report(labels, [scored[t] for t in texts], threshold)
    size = [_changed_lines(s) for s in samples]
    size_auc = roc_auc(labels, size)
    report["baselines"] = {
        "majority_class": majority_report(labels),
        "size_only_roc_auc": None if size_auc is None else round(size_auc, 4),
    }
    if static_run is not None:
        report["baselines"]["static_analysis"] = static_report(
            static_run, {s.sample_id for s in samples}
        )
    if baseline is not None:
        scores = baseline.predict_proba(texts)[:, 1].tolist()
        report["baselines"]["tfidf_logistic"] = score_report(labels, scores, baseline_threshold)
    return report


def summary_md(m: dict[str, Any]) -> str:
    def row(name: str, r: dict[str, Any]) -> str:
        ci = r.get("roc_auc_ci95") or ["-", "-"]
        return (
            f"| {name} | {r.get('n')} | {r.get('accuracy')} | {r.get('precision', '-')} | "
            f"{r.get('recall', '-')} | {r.get('f1', '-')} | {r.get('false_positive_rate', '-')} | "
            f"{r.get('roc_auc', '-')} ({ci[0]}-{ci[1]}) |"
        )

    a, b = m["repo_disjoint"], m["official_test"]
    lines = [
        "# Change classifier: independent test",
        "",
        f"Model {m['model']}, trained on {m['train_examples']} examples "
        f"({m['epochs_completed']} epochs of {m['epochs_requested']}). Threshold "
        f"{m['threshold']} from the dev split. The label is 'a human commented on this change', "
        "a proxy for 'needs review', not a defect label.",
        "",
        "| Scorer and set | n | Accuracy | Precision | Recall | F1 | FPR | ROC-AUC (95% CI) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        row("Classifier, repository-disjoint (primary)", a),
    ]
    static = a["baselines"].get("static_analysis")
    if static:
        lines.append(row("Original static analysis, same set", static))
    tfidf = a["baselines"].get("tfidf_logistic")
    if tfidf:
        lines.append(row("TF-IDF + logistic regression, same set", tfidf))
    lines += [
        f"| Majority class, same set | {a['n']} | {a['baselines']['majority_class']['accuracy']} "
        "| - | - | - | - | - |",
        f"| Change size only, same set | {a['n']} | - | - | - | - | - | "
        f"{a['baselines']['size_only_roc_auc']} |",
        row("Classifier, official test (shares projects with valid)", b),
        "",
        f"Confusion matrix (primary): {a['confusion_matrix']}.",
        f"Class-wise (primary): {a['class_wise']}.",
        "",
        "Python only. No claim is made about other languages.",
        "",
    ]
    return "\n".join(lines)


def _weights_sha256(model_dir: Path) -> str | None:
    weights = model_dir / "model.safetensors"
    if not weights.is_file():
        return None
    digest = hashlib.sha256()
    with weights.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _score_once(model: Any, samples: list[CodeReviewerSample]) -> dict[str, float]:
    """Model score per distinct change text."""
    texts = list(dict.fromkeys(change_text(s.patch) for s in samples))
    return dict(zip(texts, model.score(texts), strict=True))


def run_classifier_evaluation(
    settings: Settings, model_dir: Path, data_dir: Path, results_dir: Path | None = None
) -> Path:
    results_dir = results_dir or PROJECT_ROOT / "experiments" / "results"
    root = PROJECT_ROOT / settings.datasets.root
    cache = PROJECT_ROOT / settings.datasets.cache_dir
    test = load_codereviewer("cls", "test", root=root, cache_dir=cache)
    ids = set(json.loads((data_dir / "test_sample_ids.json").read_text(encoding="utf-8")))
    held_out = [s for s in test if s.sample_id in ids]
    official = _deduplicated(test)
    model = TransformersChangeClassifier(model_dir)
    report_file = model_dir / "training_report.json"
    training = json.loads(report_file.read_text(encoding="utf-8")) if report_file.is_file() else {}

    baseline, baseline_threshold = None, 0.5
    baseline_dir = model_dir.parent / "change_cls_baseline"
    if (baseline_dir / "baseline.pkl").is_file():
        from marl_agents.training.baseline import load

        baseline = load(baseline_dir)
        saved = json.loads((baseline_dir / "baseline_report.json").read_text(encoding="utf-8"))
        baseline_threshold = float(saved["threshold"])

    threshold = model.metadata.threshold
    static_run = latest_static_run(results_dir)
    recorder = RunRecorder(f"classifier_cls_test_n{len(held_out)}", settings, base_dir=results_dir)
    scored = _score_once(model, held_out + official)
    official_ids = {s.sample_id for s in official}
    for s in test:
        if s.sample_id in ids or s.sample_id in official_ids:
            recorder.prediction(
                {
                    "sample_id": s.sample_id,
                    "label": s.label,
                    "score": scored[change_text(s.patch)],
                    "repo_disjoint": s.sample_id in ids,
                    "official_test": s.sample_id in official_ids,
                }
            )
    metrics = {
        "benchmark": "classifier",
        "model": model.model_id,
        "weights_sha256": _weights_sha256(model_dir),
        "threshold": threshold,
        "train_examples": training.get("train_examples"),
        "epochs_completed": training.get("epochs_completed"),
        "epochs_requested": training.get("epochs_requested"),
        "stopped_by_time_budget": training.get("stopped_by_time_budget"),
        "repo_disjoint": _evaluate(
            held_out, threshold, scored, baseline, baseline_threshold, static_run
        ),
        "official_test": _evaluate(
            official, threshold, scored, baseline, baseline_threshold, static_run
        ),
    }
    return recorder.finish(
        metrics,
        summary_md(metrics),
        benchmark="classifier",
        dataset="CodeReviewer",
        task="cls",
        split="test",
        languages=["py"],
        sample_ids=sorted(ids),
    )
