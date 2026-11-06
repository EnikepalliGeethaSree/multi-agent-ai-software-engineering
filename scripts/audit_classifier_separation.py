"""How separate are the classifier's train, dev and test sets? Read-only, and nothing is scored.

    python scripts/audit_classifier_separation.py experiments/results/<classifier run>

Compares project names and patch keys only. A patch key ignores whitespace and hunk positions, so it
catches copies, not similar code. Project names catch neither forks nor renamed repositories, and
train positives have no name at all. Saved next to the run as separation_audit.json.
"""

from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

from marl_agents.config import PROJECT_ROOT, load_settings
from marl_agents.evaluation.datasets import load_codereviewer
from marl_agents.evaluation.datasets.codereviewer import CLS_MEMBERS, CLS_ZIP
from marl_agents.llm.classifier import change_text
from marl_agents.training.data import Example, Pooled, patch_key, read_examples

DATA = PROJECT_ROOT / "data" / "classifier" / "py"


def shared(items: list[Example], keys: set[str]) -> int:
    return sum(patch_key(e.text) in keys for e in items)


def main(run: Path) -> None:
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    dev_projects, test_projects = set(manifest["dev_projects"]), set(manifest["test_projects"])
    train = read_examples(DATA / "train.jsonl")
    dev = read_examples(DATA / "dev.jsonl")
    with (DATA / "pool.jsonl").open(encoding="utf-8") as fh:
        pool = {p.text: p for p in (Pooled.model_validate_json(line) for line in fh)}
    settings = load_settings()
    root = PROJECT_ROOT / settings.datasets.root
    valid_other: dict[str, str | None] = {}
    with zipfile.ZipFile(root / CLS_ZIP) as zf, zf.open(CLS_MEMBERS["valid"][0]) as fh:
        for line in fh:
            raw = json.loads(line)
            if raw.get("lang") != "py":
                valid_other.setdefault(change_text(str(raw.get("patch") or "")), raw.get("proj"))
    official = load_codereviewer(
        "cls", "test", root=root, cache_dir=PROJECT_ROOT / settings.datasets.cache_dir
    )
    ids = set(json.loads((DATA / "test_sample_ids.json").read_text(encoding="utf-8")))
    held = [s for s in official if s.sample_id in ids]
    dev_keys = {patch_key(e.text) for e in dev}
    held_keys = {patch_key(s.patch) for s in held}
    official_keys = {patch_key(s.patch) for s in official}

    python_part = [e for e in train if e.text in pool]
    other_part = [e for e in train if e.text not in pool and e.text in valid_other]
    named = [e for e in python_part if pool[e.text].project]
    unnamed = [e for e in python_part if not pool[e.text].project]
    other_names = Counter(valid_other[e.text] for e in other_part)
    official_projects = {s.proj for s in official}
    in_official = [e for e in python_part if patch_key(e.text) in official_keys]

    def part(items: list[Example]) -> dict[str, int]:
        return {
            "records": len(items),
            "positive": sum(e.label for e in items),
            "shared_patches_dev": shared(items, dev_keys),
            "shared_patches_held_out_test": shared(items, held_keys),
            "shared_patches_official_test": shared(items, official_keys),
        }

    result = {
        "note": "patch key ignores whitespace and hunk positions; nothing was scored",
        "train_records": len(train),
        "unmapped_train_records": len(train) - len(python_part) - len(other_part),
        "python_named": {
            **part(named),
            "in_dev_projects": sum(pool[e.text].project in dev_projects for e in named),
            "in_test_projects": sum(pool[e.text].project in test_projects for e in named),
        },
        "python_no_project_name": part(unnamed),
        "non_python_from_valid": {
            **part(other_part),
            "projects": len(other_names),
            "without_project_name": other_names[None],
            "in_dev_projects": sum(v for k, v in other_names.items() if k in dev_projects),
            "in_test_projects": sum(v for k, v in other_names.items() if k in test_projects),
            "in_official_test_projects": sum(
                v for k, v in other_names.items() if k in official_projects
            ),
        },
        "python_records_shared_with_official_test_by_label": dict(
            Counter(str(e.label) for e in in_official)
        ),
        "dev_vs_held_out": {
            "shared_projects": len(dev_projects & test_projects),
            "shared_patches": len(dev_keys & held_keys),
        },
        "official_test": {
            "records_outside_held_out_group": sum(s.proj not in test_projects for s in official),
            "projects_outside_held_out_group": len(official_projects - test_projects),
            "of_those_in_dev_group": len((official_projects - test_projects) & dev_projects),
        },
    }
    (run / "separation_audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
