"""Which training set generalises? Compares recipes with the fast TF-IDF model, on dev only.

    python scripts/compare_training_recipes.py

The test split is not read. `dev_cv` is 5-fold cross-validation inside dev, whose two classes were
collected the same way, so it estimates how much signal the label holds without any train artifact.
"""

from __future__ import annotations

import json

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline

from marl_agents.config import PROJECT_ROOT
from marl_agents.evaluation.metrics import roc_auc
from marl_agents.training.data import (
    Example,
    Pooled,
    balance,
    cap_projects,
    match_sizes,
    read_examples,
)

DATA = PROJECT_ROOT / "data" / "classifier" / "py"


def pipeline():  # type: ignore[no-untyped-def]
    return make_pipeline(
        TfidfVectorizer(
            lowercase=False, ngram_range=(1, 2), max_features=200_000, min_df=2, sublinear_tf=True
        ),
        LogisticRegression(max_iter=1000, C=1.0, random_state=42),
    )


def changed(text: str) -> float:
    return float(
        sum(
            1
            for ln in text.splitlines()
            if ln[:1] in {"+", "-"} and not ln.startswith(("+++", "---"))
        )
    )


def fit_auc(train: list[Example], dev: list[Example]) -> tuple[float, float]:
    cut = int(len(train) * 0.9)
    model = pipeline()
    model.fit([e.text for e in train[:cut]], [e.label for e in train[:cut]])

    def auc(items: list[Example]) -> float:
        scores = model.predict_proba([e.text for e in items])[:, 1].tolist()
        return roc_auc([e.label for e in items], scores) or 0.0

    return auc(train[cut:]), auc(dev)


def main() -> None:
    with (DATA / "pool.jsonl").open(encoding="utf-8") as fh:
        pool = [Pooled.model_validate_json(line) for line in fh]
    dev = read_examples(DATA / "dev.jsonl")
    labels = [e.label for e in dev]
    capped = cap_projects(pool, 1500)
    recipes: dict[str, list[Pooled]] = {
        "balanced only": pool,
        "project cap only": capped,
        "size match only": match_sizes(pool, dev),
        "project cap + size match": match_sizes(capped, dev),
    }
    results = {
        "pool": len(pool),
        "dev": len(dev),
        "size_only_dev_auc": round(roc_auc(labels, [changed(e.text) for e in dev]) or 0.0, 4),
    }
    for name, items in recipes.items():
        chosen = balance(items, None)
        holdout, dev_auc = fit_auc(chosen, dev)  # type: ignore[arg-type]
        results[name] = {
            "train": len(chosen),
            "train_holdout_auc": round(holdout, 4),
            "dev_auc": round(dev_auc, 4),
        }
        print(name, results[name], flush=True)
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    aucs = []
    texts = [e.text for e in dev]
    for fit_idx, test_idx in folds.split(texts, labels):
        model = pipeline()
        model.fit([texts[i] for i in fit_idx], [labels[i] for i in fit_idx])
        scores = model.predict_proba([texts[i] for i in test_idx])[:, 1].tolist()
        aucs.append(roc_auc([labels[i] for i in test_idx], scores) or 0.0)
    results["dev_cv_auc"] = round(sum(aucs) / len(aucs), 4)
    print(json.dumps(results, indent=2))
    (DATA / "recipe_comparison.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
