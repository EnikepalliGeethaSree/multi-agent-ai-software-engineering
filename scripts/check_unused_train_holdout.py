"""Part 3.9 feasibility check: is there a verifiable, never-used held-out set in the train split?

    python scripts/check_unused_train_holdout.py

Reads only the saved classifier data (data/classifier/py/) and its manifest. Nothing is trained,
scored or sampled. Writes experiments/evaluation_summary/unused-train-holdout-check.json.
"""

from __future__ import annotations

import json
from collections import Counter

from marl_agents.config import PROJECT_ROOT

DATA = PROJECT_ROOT / "data" / "classifier" / "py"
OUT = PROJECT_ROOT / "experiments" / "evaluation_summary" / "unused-train-holdout-check.json"


def main() -> None:
    labels: Counter[int] = Counter()
    named: Counter[int] = Counter()
    with (DATA / "pool.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            labels[int(r["label"])] += 1
            named[int(r["label"])] += r.get("project") is not None
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    recipes = json.loads((DATA / "recipe_comparison.json").read_text(encoding="utf-8"))
    minority = min(labels[0], labels[1])
    minority_label = 0 if labels[0] <= labels[1] else 1
    report = {
        "python_train_pool": dict(labels),
        "with_project_name": dict(named),
        "balanced_only_recipe_train": recipes["balanced only"]["train"],
        "balanced_only_uses_every_record_of_label": minority_label,
        "minority_class_size": minority,
        "finding_1": (
            f"balance() keeps min(class sizes) per class, so the 'balanced only' recipe of the "
            f"recipe comparison used all {minority} label-{minority_label} records "
            f"(it trained on {recipes['balanced only']['train']} = 2 x {minority}): none is unused."
        ),
        "finding_2": (
            f"Unused records can only have label {1 - minority_label}; "
            f"{named[1 - minority_label]} of {labels[1 - minority_label]} have a project name, so "
            "their repository identity cannot be checked against the test projects."
        ),
        "finding_3": (
            f"The other Python-tagged train records ({manifest['python_filter_check']['py_tag_dropped']}"
            ") are negatives that failed the content filter; adding them would tie the label to "
            "'parses as Python' and bias the gate evaluation."
        ),
        "decision": "Part 3.9 not run: no verifiable never-used held-out set with both classes "
        "exists. Test and dev samples are not substituted (D41).",
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
