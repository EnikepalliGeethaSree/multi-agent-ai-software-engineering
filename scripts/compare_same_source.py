"""Does same-source data from other languages beat the biased train split? Fast model, dev only.

    python scripts/compare_same_source.py

`valid` records of other languages were collected the same way for both classes. Records from
projects in the test group are excluded, and the test split is not read.
"""

from __future__ import annotations

import json
import zipfile

from compare_training_recipes import DATA, fit_auc

from marl_agents.config import PROJECT_ROOT, load_settings
from marl_agents.evaluation.datasets.codereviewer import CLS_MEMBERS, CLS_ZIP
from marl_agents.llm.classifier import change_text
from marl_agents.training.data import Example, patch_key, read_examples


def main() -> None:
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    test_projects = set(manifest["test_projects"])
    dev = read_examples(DATA / "dev.jsonl")
    train = read_examples(DATA / "train.jsonl")
    dev_keys = {patch_key(e.text) for e in dev}
    root = PROJECT_ROOT / load_settings().datasets.root
    other: list[Example] = []
    seen: set[str] = set()
    with zipfile.ZipFile(root / CLS_ZIP) as zf, zf.open(CLS_MEMBERS["valid"][0]) as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("lang") == "py" or r.get("proj") in test_projects:
                continue
            key = patch_key(r["patch"])
            if key in seen or key in dev_keys:
                continue
            seen.add(key)
            other.append(Example(text=change_text(r["patch"]), label=int(r["y"])))
    positives = sum(e.label for e in other)
    print(f"same-source other-language records: {len(other)}, positive {positives}", flush=True)
    results = {
        "same_source_records": len(other),
        "same_source_positive_share": round(positives / max(len(other), 1), 4),
    }
    for name, items in (
        ("other languages only", other),
        ("reweighted train + other languages", train + other),
    ):
        holdout, dev_auc = fit_auc(items, dev)
        results[name] = {
            "train": len(items),
            "holdout_auc": round(holdout, 4),
            "dev_auc": round(dev_auc, 4),
        }
        print(name, results[name], flush=True)
    (DATA / "same_source_comparison.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
