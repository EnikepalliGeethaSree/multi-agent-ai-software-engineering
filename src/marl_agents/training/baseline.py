"""TF-IDF + logistic regression on diff text: the simple model a neural one must beat.

    python -m marl_agents.training.baseline

Trained on the same files as the neural classifier, in seconds on CPU. It also works as a leakage
detector: if something in the training data gives the label away, this model reveals it by scoring
far better on a holdout of train than on dev, whose records were collected the same way for both
classes.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any

from marl_agents.config import PROJECT_ROOT
from marl_agents.evaluation.metrics import roc_auc
from marl_agents.training.data import read_examples
from marl_agents.training.train import best_threshold

MODEL_FILE = "baseline.pkl"


def fit(data: Path, out: Path) -> dict[str, Any]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    examples = read_examples(data / "train.jsonl")
    cut = int(len(examples) * 0.9)
    fit_set, holdout = examples[:cut], examples[cut:]
    dev = read_examples(data / "dev.jsonl")
    model = make_pipeline(
        TfidfVectorizer(
            lowercase=False, ngram_range=(1, 2), max_features=200_000, min_df=2, sublinear_tf=True
        ),
        LogisticRegression(max_iter=1000, C=1.0, random_state=42),
    )
    model.fit([e.text for e in fit_set], [e.label for e in fit_set])

    def scores(items: list[Any]) -> list[float]:
        return list(model.predict_proba([e.text for e in items])[:, 1].tolist())

    dev_scores = scores(dev)
    dev_labels = [e.label for e in dev]
    threshold, balanced = best_threshold(dev_labels, dev_scores)
    holdout_auc = roc_auc([e.label for e in holdout], scores(holdout))
    dev_auc = roc_auc(dev_labels, dev_scores)
    report = {
        "model": "tfidf_logistic_regression",
        "train_examples": len(fit_set),
        "train_holdout_auc": round(holdout_auc or 0.0, 4),
        "dev_auc": round(dev_auc or 0.0, 4),
        "dev_balanced_accuracy": round(balanced, 4),
        "threshold": threshold,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / MODEL_FILE).write_bytes(pickle.dumps(model))
    (out / "baseline_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def load(out: Path) -> Any:
    return pickle.loads((out / MODEL_FILE).read_bytes())  # noqa: S301 - our own artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / "data" / "classifier" / "py")
    parser.add_argument(
        "--out", type=Path, default=PROJECT_ROOT / "data" / "models" / "change_cls_baseline"
    )
    args = parser.parse_args(argv)
    print(json.dumps(fit(args.data, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
