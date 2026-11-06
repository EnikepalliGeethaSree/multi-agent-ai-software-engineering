"""Prepare CodeReviewer "needs review?" data for fine-tuning, without leaking the label.

What inspecting the raw files showed, and what this module does about it (decision D28):

- In the train chunks all 132,918 positives have only `id, msg, oldf, patch, y`, and all 132,918
  negatives also have `lang, proj, idx`. So `lang == "py"` selects negatives only, and the mere
  presence of a field gives the label away. Python is therefore recognised from the code itself,
  by the same rule for both classes, and only the diff text ever reaches the model.
- valid and test share 28 projects and 664 identical Python patches, so a model tuned on valid has
  seen part of test. `project_holdout` tunes on some projects and tests on the others.
- Train positives have no project name, so a project-level split cannot be proved for them.
  Exact and near-duplicate patches are removed across splits instead, and the limit is documented.
- Train positives are far larger than real ones (mean 1,684 characters against 721 in dev), and
  train negatives lean on a few projects, so a model can score well by size and project name alone.
  A TF-IDF model showed this: AUC 0.82 on held-out train, 0.62 on dev. `reweight` therefore caps
  negatives per project and matches each class's size distribution to the dev split.
- Where data comes from matters more than how much there is. `other_language_examples` adds valid
  records of other languages, collected the same way for both classes, from projects outside the
  test group. Added to the reweighted train set, they gave the best dev AUC of the recipes tried
  (`scripts/compare_same_source.py`).

Parsing uses `ast.parse` only: dataset code is never executed.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import random
import re
import warnings
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel, Field

from marl_agents.evaluation.datasets.codereviewer import (
    CLS_MEMBERS,
    CLS_ZIP,
    CodeReviewerSample,
    load_codereviewer,
)
from marl_agents.llm.classifier import change_text

logger = logging.getLogger(__name__)

SEED = 42
MIN_CHANGED_LINES = 1
_NON_PYTHON_LINE = re.compile(r"[;{}]\s*$")
_LOW_INFO = re.compile(
    r"^\W*(lgtm|nit|nits?:?|\+1|ditto|same|same here|thanks|thank you|ok|okay|done|fixed|why\??|"
    r"typo|nice|good|great|ping|bump|see above|as above)\W*$",
    re.IGNORECASE,
)


class Example(BaseModel):
    """What the model may see (`text`) and its label. No metadata, so nothing can leak."""

    text: str
    label: int


class Pooled(Example):
    """A filtered training record. `project` only guides sampling and never reaches the model."""

    project: str | None = None


class SplitReport(BaseModel):
    name: str
    records: int = 0
    kept: int = 0
    positives: int = 0
    negatives: int = 0
    dropped: dict[str, int] = Field(default_factory=dict)


class Manifest(BaseModel):
    seed: int
    dataset: str = "CodeReviewer Diff_Quality_Estimation"
    language: str = "python (content-based for train; lang tag for valid and test)"
    input_format: str = "unified diff text only (no metadata)"
    max_train: int | None
    max_per_project: int | None = None
    size_matched_to_dev: bool = False
    other_language_records: int = 0
    dev_projects: list[str]
    test_projects: list[str]
    splits: list[SplitReport]
    python_filter_check: dict[str, float | int] = Field(default_factory=dict)
    train_hash: str = ""


def added_lines(patch: str) -> list[str]:
    return [ln[1:] for ln in patch.splitlines() if ln.startswith("+") and not ln.startswith("+++")]


def _changed_count(patch: str) -> int:
    return sum(
        1
        for ln in patch.splitlines()
        if ln[:1] in {"+", "-"} and not ln.startswith(("+++", "---")) and ln[1:].strip()
    )


def _parses(code: str) -> bool:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # invalid escapes in dataset code are not our concern
        try:
            ast.parse(code)
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            return False
    return True


def looks_like_python(oldf: str, patch: str) -> bool:
    """Content-only language check, the same for positives and negatives. Parses, never runs.

    A file written in another language rarely parses as Python, and the cheap test first rejects
    most of them. New files have no `oldf`, so their added lines are parsed instead, which is
    stricter and only loses examples.
    """
    code = oldf if oldf.strip() else "\n".join(added_lines(patch))
    if not code.strip():
        return False
    lines = [ln for ln in code.splitlines() if ln.strip()]
    if not lines:
        return False
    semicolons = sum(1 for ln in lines if _NON_PYTHON_LINE.search(ln))
    if semicolons / len(lines) > 0.2:
        return False
    return _parses(code)


def patch_key(patch: str) -> str:
    """Identity of a change, ignoring whitespace and hunk positions (catches near-duplicates)."""
    changed = [
        re.sub(r"\s+", "", ln)
        for ln in patch.splitlines()
        if ln[:1] in {"+", "-"} and not ln.startswith(("+++", "---"))
    ]
    return hashlib.sha1("\n".join(changed).encode("utf-8")).hexdigest()  # noqa: S324 - not security


def is_low_information(comment: str) -> bool:
    """A review comment too short to mean the change really needed attention."""
    text = comment.strip()
    return not text or len(text.split()) < 2 or bool(_LOW_INFO.match(text))


def project_holdout(
    projects: Iterable[str], dev_share: float = 0.5, seed: int = SEED
) -> tuple[set[str], set[str]]:
    """Divide projects into tuning and testing sets: no repository appears on both sides."""
    ordered = sorted(set(projects))
    random.Random(seed).shuffle(ordered)
    cut = round(len(ordered) * dev_share)
    return set(ordered[:cut]), set(ordered[cut:])


def iter_train_records(root: Path) -> Iterator[dict[str, object]]:
    with zipfile.ZipFile(root / CLS_ZIP) as zf:
        for member in CLS_MEMBERS["train"]:
            with zf.open(member) as fh:
                for line in fh:
                    yield json.loads(line)


def other_language_examples(
    root: Path, test_projects: set[str], exclude: set[str]
) -> list[Example]:
    """Non-Python records of `valid`, unique and outside the test projects. Test is never read."""
    seen = set(exclude)
    out: list[Example] = []
    with zipfile.ZipFile(root / CLS_ZIP) as zf, zf.open(CLS_MEMBERS["valid"][0]) as fh:
        for line in fh:
            raw = json.loads(line)
            if raw.get("lang") == "py" or raw.get("proj") in test_projects:
                continue
            key = patch_key(str(raw.get("patch") or ""))
            if key not in seen and _changed_count(str(raw.get("patch") or "")):
                seen.add(key)
                out.append(Example(text=change_text(str(raw["patch"])), label=int(raw["y"])))
    return out


def select_train(
    records: Iterable[dict[str, object]],
    excluded: set[str],
    keep_low_information: bool = False,
) -> tuple[list[Pooled], SplitReport, dict[str, int]]:
    """Filter raw train records into unique examples.

    `check` compares the content filter with `lang` tags, which exist on negatives only: that
    measures the filter, and the tags take no part in selecting anything.
    """
    report = SplitReport(name="train")
    dropped: Counter[str] = Counter()
    check: Counter[str] = Counter()
    by_key: dict[str, Pooled] = {}
    conflicts: set[str] = set()
    for raw in records:
        report.records += 1
        patch = str(raw.get("patch") or "")
        oldf = str(raw.get("oldf") or "")
        label = int(str(raw.get("y", 0)))
        if not patch.strip() or "@@" not in patch:
            dropped["empty_or_malformed_patch"] += 1
            continue
        if _changed_count(patch) < MIN_CHANGED_LINES:
            dropped["no_changed_lines"] += 1
            continue
        python = looks_like_python(oldf, patch)
        tag = raw.get("lang")
        if tag is not None:
            check[f"{'py' if tag == 'py' else 'other'}_tag_{'kept' if python else 'dropped'}"] += 1
        if not python:
            dropped["not_python"] += 1
            continue
        if (
            label == 1
            and not keep_low_information
            and is_low_information(str(raw.get("msg") or ""))
        ):
            dropped["low_information_comment"] += 1
            continue
        key = patch_key(patch)
        if key in excluded:
            dropped["duplicate_of_valid_or_test"] += 1
            continue
        if key in conflicts:
            dropped["conflicting_labels"] += 1
            continue
        seen = by_key.get(key)
        if seen is not None:
            if seen.label != label:
                del by_key[key]
                conflicts.add(key)
                dropped["conflicting_labels"] += 2
            else:
                dropped["duplicate"] += 1
            continue
        proj = raw.get("proj")
        by_key[key] = Pooled(
            text=change_text(patch), label=label, project=str(proj) if proj else None
        )
    kept = list(by_key.values())
    report.dropped = dict(dropped)
    return kept, report, dict(check)


SIZE_EDGES = (2, 5, 10, 20, 50)


def size_bin(text: str) -> int:
    """Which size bucket a diff falls in, by changed lines."""
    changed = sum(
        1 for ln in text.splitlines() if ln[:1] in {"+", "-"} and not ln.startswith(("+++", "---"))
    )
    return next((i for i, edge in enumerate(SIZE_EDGES) if changed <= edge), len(SIZE_EDGES))


def cap_projects(pool: list[Pooled], limit: int | None, seed: int = SEED) -> list[Pooled]:
    """At most `limit` records per named project, so no project's vocabulary can stand for a class.

    Only negatives have project names, which is where the concentration is.
    """
    if limit is None:
        return list(pool)
    rng = random.Random(seed)
    groups: dict[str | None, list[Pooled]] = {}
    for p in pool:
        groups.setdefault(p.project, []).append(p)
    kept: list[Pooled] = list(groups.pop(None, []))
    for _project, items in sorted(groups.items(), key=lambda x: str(x[0])):
        kept.extend(rng.sample(items, limit) if len(items) > limit else items)
    return kept


def match_sizes(pool: list[Pooled], reference: list[Example], seed: int = SEED) -> list[Pooled]:
    """Downsample each class until its size mix equals that class's mix in `reference`.

    `reference` is the dev split, which was collected the same way for both classes. The test split
    plays no part.
    """
    rng = random.Random(seed)
    bins = len(SIZE_EDGES) + 1
    kept: list[Pooled] = []
    for label in (0, 1):
        ref = Counter(size_bin(e.text) for e in reference if e.label == label)
        total = sum(ref.values())
        if not total:  # the reference says nothing about this class
            kept.extend(p for p in pool if p.label == label)
            continue
        by_bin: dict[int, list[Pooled]] = {b: [] for b in range(bins)}
        for p in pool:
            if p.label == label:
                by_bin[size_bin(p.text)].append(p)
        scale = min(len(by_bin[b]) / (ref[b] / total) for b in range(bins) if ref[b])
        for b in range(bins):
            target = round(scale * ref[b] / total)
            items = by_bin[b]
            kept.extend(rng.sample(items, min(target, len(items))))
    return kept


def reweight(
    pool: list[Pooled],
    reference: list[Example],
    max_per_project: int | None,
    max_total: int | None,
    seed: int = SEED,
) -> list[Example]:
    """The training set: project cap, size match, balanced classes. Text and label only."""
    capped = cap_projects(pool, max_per_project, seed)
    matched = match_sizes(capped, reference, seed)
    return [Example(text=e.text, label=e.label) for e in balance(matched, max_total, seed)]


def balance(
    examples: list[Pooled] | list[Example], max_total: int | None, seed: int = SEED
) -> list[Pooled] | list[Example]:
    """Equal classes (largest possible, or `max_total`), shuffled reproducibly."""
    rng = random.Random(seed)
    pos = [e for e in examples if e.label == 1]
    neg = [e for e in examples if e.label == 0]
    per_class = min(len(pos), len(neg))
    if max_total is not None:
        per_class = min(per_class, max_total // 2)
    chosen = rng.sample(pos, per_class) + rng.sample(neg, per_class)
    rng.shuffle(chosen)
    return chosen


def clean_eval_split(
    samples: Iterable[CodeReviewerSample], name: str, exclude: set[str]
) -> tuple[list[CodeReviewerSample], SplitReport]:
    report = SplitReport(name=name)
    dropped: Counter[str] = Counter()
    seen: set[str] = set()
    kept: list[CodeReviewerSample] = []
    for s in samples:
        report.records += 1
        key = patch_key(s.patch)
        if not s.patch.strip() or _changed_count(s.patch) < MIN_CHANGED_LINES:
            dropped["no_changed_lines"] += 1
        elif key in exclude:
            dropped["duplicate_across_splits"] += 1
        elif key in seen:
            dropped["duplicate"] += 1
        else:
            seen.add(key)
            kept.append(s)
    report.dropped = dict(dropped)
    return kept, report


def _count(report: SplitReport, labels: Iterable[int]) -> SplitReport:
    tally = Counter(labels)
    report.kept = sum(tally.values())
    report.positives, report.negatives = tally[1], tally[0]
    return report


def _write(path: Path, examples: Iterable[Example]) -> str:
    digest = hashlib.sha256()
    with path.open("w", encoding="utf-8") as out:
        for e in examples:
            line = e.model_dump_json() + "\n"
            out.write(line)
            digest.update(line.encode("utf-8"))
    return digest.hexdigest()[:16]


def read_examples(path: Path) -> list[Example]:
    with path.open(encoding="utf-8") as fh:
        return [Example.model_validate_json(line) for line in fh]


def prepare(
    root: Path,
    out_dir: Path,
    cache_dir: Path,
    max_train: int | None = None,
    seed: int = SEED,
    keep_low_information: bool = False,
    max_per_project: int | None = 1500,
    add_other_languages: bool = True,
) -> Manifest:
    """Build train / dev / test files. Test keeps its sample ids so runs can be compared on them.

    The filtered pool is saved, so changing the sampling does not repeat the slow pass over the
    archive. It holds the project names used for sampling; train.jsonl does not.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    valid = load_codereviewer("cls", "valid", root=root, cache_dir=cache_dir)
    test = load_codereviewer("cls", "test", root=root, cache_dir=cache_dir)
    dev_projects, test_projects = project_holdout(
        (s.proj for s in [*valid, *test] if s.proj), seed=seed
    )
    # A patch in both project groups would cross the boundary: it stays out of dev.
    test_keys = {patch_key(s.patch) for s in test if s.proj in test_projects}
    dev, dev_report = clean_eval_split(
        (s for s in valid if s.proj in dev_projects), "dev", test_keys
    )
    held, test_report = clean_eval_split(
        (s for s in test if s.proj in test_projects), "test_repo_disjoint", set()
    )
    excluded = test_keys | {patch_key(s.patch) for s in dev}
    pool_path = out_dir / "pool.jsonl"
    report_path = out_dir / "pool_report.json"
    if pool_path.is_file() and report_path.is_file():
        with pool_path.open(encoding="utf-8") as fh:
            pooled = [Pooled.model_validate_json(line) for line in fh]
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        train_report = SplitReport.model_validate(saved["report"])
        check = saved["check"]
    else:
        pooled, train_report, check = select_train(
            iter_train_records(root), excluded, keep_low_information
        )
        with pool_path.open("w", encoding="utf-8") as out:
            for p in pooled:
                out.write(p.model_dump_json() + "\n")
        report_path.write_text(
            json.dumps({"report": train_report.model_dump(), "check": check}), encoding="utf-8"
        )
    dev_examples = [Example(text=change_text(s.patch), label=s.label) for s in dev]
    python_part = reweight(pooled, dev_examples, max_per_project, None, seed)
    others = other_language_examples(root, test_projects, excluded) if add_other_languages else []
    chosen = [
        Example(text=e.text, label=e.label)
        for e in balance([*python_part, *others], max_train, seed)
    ]
    _count(train_report, (e.label for e in chosen))
    train_report.dropped["project_cap_size_match_or_balance"] = len(pooled) - len(chosen)
    _count(dev_report, (s.label for s in dev))
    _count(test_report, (s.label for s in held))
    train_hash = _write(out_dir / "train.jsonl", chosen)
    _write(out_dir / "dev.jsonl", dev_examples)
    (out_dir / "test_sample_ids.json").write_text(
        json.dumps([s.sample_id for s in held]), encoding="utf-8"
    )
    tagged_py = check.get("py_tag_kept", 0) + check.get("py_tag_dropped", 0)
    tagged_other = check.get("other_tag_kept", 0) + check.get("other_tag_dropped", 0)
    kept_any = check.get("py_tag_kept", 0) + check.get("other_tag_kept", 0)
    manifest = Manifest(
        seed=seed,
        max_train=max_train,
        max_per_project=max_per_project,
        size_matched_to_dev=True,
        other_language_records=len(others),
        dev_projects=sorted(dev_projects),
        test_projects=sorted(test_projects),
        splits=[train_report, dev_report, test_report],
        python_filter_check={
            **check,
            "recall_on_tagged_python": round(check.get("py_tag_kept", 0) / max(tagged_py, 1), 4),
            "precision_on_tagged": round(check.get("py_tag_kept", 0) / max(kept_any, 1), 4),
            "tagged_non_python": tagged_other,
        },
        train_hash=train_hash,
    )
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest
