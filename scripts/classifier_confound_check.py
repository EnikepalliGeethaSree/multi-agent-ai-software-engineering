"""Does the saved classifier beat change size within size bands and projects? Reads saved scores.

    python scripts/classifier_confound_check.py experiments/results/<classifier run>

Nothing is rescored or retrained, and the model and threshold were frozen before this ran. The
result is descriptive and is saved next to the run as confound_check.json.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from marl_agents.config import PROJECT_ROOT, load_settings
from marl_agents.evaluation.datasets import load_codereviewer
from marl_agents.evaluation.metrics import roc_auc
from marl_agents.training.data import SIZE_EDGES, size_bin


def top_share(rows: list[dict], key: str, share: float) -> float:
    ranked = sorted(rows, key=lambda r: -r[key])
    top = ranked[: round(len(ranked) * share)]
    return sum(r["label"] for r in top) / len(top)


def main(run: Path) -> None:
    s = load_settings()
    test = load_codereviewer(
        "cls",
        "test",
        root=PROJECT_ROOT / s.datasets.root,
        cache_dir=PROJECT_ROOT / s.datasets.cache_dir,
    )
    by_id = {x.sample_id: x for x in test}
    rows = []
    with (run / "predictions.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["repo_disjoint"]:
                x = by_id[r["sample_id"]]
                changed = sum(
                    1
                    for ln in x.patch.splitlines()
                    if ln[:1] in {"+", "-"} and not ln.startswith(("+++", "---"))
                )
                r.update(size=float(changed), band=size_bin(x.patch), project=x.proj)
                rows.append(r)
    edges = ["1-2", "3-5", "6-10", "11-20", "21-50", "51+"]
    assert len(edges) == len(SIZE_EDGES) + 1
    bands = []
    for b, name in enumerate(edges):
        part = [r for r in rows if r["band"] == b]
        labels = [r["label"] for r in part]
        bands.append(
            {
                "changed_lines": name,
                "n": len(part),
                "positive_share": round(sum(labels) / len(part), 4) if part else None,
                "classifier_auc": roc_auc(labels, [r["score"] for r in part]),
                "size_auc": roc_auc(labels, [r["size"] for r in part]),
            }
        )
    weighted = [(b["n"], b["classifier_auc"]) for b in bands if b["classifier_auc"] is not None]
    projects: dict[str, list[dict]] = {}
    for r in rows:
        projects.setdefault(str(r["project"]), []).append(r)
    per_project = []
    for name, part in sorted(projects.items()):
        labels = [r["label"] for r in part]
        if len(part) >= 30 and 0 < sum(labels) < len(labels):
            per_project.append(
                {
                    "project": name,
                    "n": len(part),
                    "classifier_auc": roc_auc(labels, [r["score"] for r in part]),
                    "size_auc": roc_auc(labels, [r["size"] for r in part]),
                }
            )
    rng = random.Random(42)  # noqa: S311 - reproducible tie-breaking
    jitter = [{**r, "tie": r["size"] + rng.random() / 2} for r in rows]
    result = {
        "n": len(rows),
        "note": "descriptive; computed after the model and threshold were frozen; largest_changes "
        "breaks size ties at random (seed 42)",
        "size_bands": bands,
        "within_band_auc_weighted": round(
            sum(n * a for n, a in weighted) / sum(n for n, _ in weighted), 4
        ),
        "projects": per_project,
        "projects_where_classifier_beats_size": sum(
            p["classifier_auc"] > p["size_auc"] for p in per_project
        ),
        "precision_at_top_share": {
            str(f): {
                "classifier": round(top_share(rows, "score", f), 4),
                "largest_changes": round(top_share(jitter, "tie", f), 4),
            }
            for f in (0.1, 0.2, 0.3, 0.5)
        },
    }
    (run / "confound_check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
