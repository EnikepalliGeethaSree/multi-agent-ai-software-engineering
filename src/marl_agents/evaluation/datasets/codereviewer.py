"""CodeReviewer (Li et al., ESEC/FSE 2022) loaders.

Tasks:
- ``msg``: review comment generation, ``Comment_Generation/msg-{train,valid,test}.jsonl``
  (every diff has a human comment, ``y`` is always 1).
- ``cls``: diff quality estimation, ``Diff_Quality_Estimation.zip`` -> ``cls-*.jsonl``
  (``y`` = 1 if the diff received a review comment, else 0; stored as a string).

Both stream line by line. Seeded reservoir sampling makes subsets reproducible; the chosen
``sample_id`` list is saved with every run so A/B/C configurations use identical samples.
The ``train`` split of ``msg`` has no ``lang`` field, so language filtering yields nothing there.
"""

from __future__ import annotations

import json
import logging
import random
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)

Task = Literal["msg", "cls"]
MSG_DIR = "codereview/CodeBERT/CodeReviewer/dataset/Comment_Generation"
CLS_ZIP = "codereview/CodeBERT/CodeReviewer/dataset/Diff_Quality_Estimation.zip"
CLS_MEMBERS = {
    "test": ["Diff_Quality_Estimation/cls-test.jsonl"],
    "valid": ["Diff_Quality_Estimation/cls-valid.jsonl"],
    "train": [f"Diff_Quality_Estimation/cls-train-chunk-{i}.jsonl" for i in range(4)],
}


class CodeReviewerSample(BaseModel):
    sample_id: str
    task: Task
    split: str
    lang: str | None = None
    proj: str | None = None
    patch: str
    oldf: str
    msg: str = ""
    label: int


def _record_to_sample(
    raw: dict[str, object], task: Task, split: str, line_no: int
) -> CodeReviewerSample:
    rid = raw.get("id", raw.get("idx", line_no))
    return CodeReviewerSample(
        sample_id=f"{task}-{split}-{rid}-{line_no}",
        task=task,
        split=split,
        lang=str(raw["lang"]) if raw.get("lang") is not None else None,
        proj=str(raw["proj"]) if raw.get("proj") is not None else None,
        patch=str(raw.get("patch", "")),
        oldf=str(raw.get("oldf", "")),
        msg=str(raw.get("msg") or ""),
        label=int(str(raw.get("y", 1))),
    )


def _iter_lines(task: Task, split: str, root: Path) -> Iterator[bytes]:
    if task == "msg":
        path = root / MSG_DIR / f"msg-{split}.jsonl"
        with path.open("rb") as fh:
            yield from fh
    else:
        with zipfile.ZipFile(root / CLS_ZIP) as zf:
            for member in CLS_MEMBERS[split]:
                with zf.open(member) as fh:
                    yield from fh


def _cache_path(cache_dir: Path, task: Task, split: str, languages: set[str] | None) -> Path:
    langs = "-".join(sorted(languages)) if languages else "all"
    return cache_dir / f"codereviewer_{task}_{split}_{langs}.jsonl"


def stream_codereviewer(
    task: Task,
    split: str,
    root: Path,
    languages: set[str] | None = None,
    cache_dir: Path | None = None,
) -> Iterator[CodeReviewerSample]:
    """All samples of a split (filtered by language), in file order.

    With `cache_dir`, the filtered subset is written once to a small JSONL cache (the cls test file
    alone is 1.4 GB inside the zip; its Python subset is a few hundred MB).
    """
    if cache_dir is not None:
        cache = _cache_path(cache_dir, task, split, languages)
        if cache.exists():
            with cache.open(encoding="utf-8") as fh:
                for line in fh:
                    yield CodeReviewerSample.model_validate_json(line)
            return
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as out:
            for sample in stream_codereviewer(task, split, root, languages, None):
                out.write(sample.model_dump_json() + "\n")
                yield sample
        tmp.replace(cache)
        return

    for line_no, raw_line in enumerate(_iter_lines(task, split, root)):
        # Cheap pre-filter before JSON parsing: the lang field is near the end of each record.
        if languages is not None and not any(
            f'"lang": "{lang}"'.encode() in raw_line or f'"lang":"{lang}"'.encode() in raw_line
            for lang in languages
        ):
            continue
        raw = json.loads(raw_line)
        if languages is not None and raw.get("lang") not in languages:
            continue
        yield _record_to_sample(raw, task, split, line_no)


def reservoir_sample(
    items: Iterable[CodeReviewerSample], k: int, seed: int
) -> list[CodeReviewerSample]:
    """Uniform sample of k items from a stream (Vitter's algorithm R), returned in stream order."""
    rng = random.Random(seed)
    reservoir: list[tuple[int, CodeReviewerSample]] = []
    for i, item in enumerate(items):
        if i < k:
            reservoir.append((i, item))
        else:
            j = rng.randint(0, i)
            if j < k:
                reservoir[j] = (i, item)
    return [item for _, item in sorted(reservoir, key=lambda x: x[0])]


def load_codereviewer(
    task: Task,
    split: str = "test",
    limit: int | None = None,
    seed: int = 42,
    languages: set[str] | None = frozenset({"py"}),  # type: ignore[assignment]
    root: str | Path = "capstone-datasets",
    cache_dir: str | Path | None = "data/cache",
    sample_ids: set[str] | None = None,
) -> list[CodeReviewerSample]:
    """Load a (sub)set. `sample_ids` reproduces a previous run's exact sample set."""
    stream = stream_codereviewer(
        task,
        split,
        Path(root),
        set(languages) if languages else None,
        Path(cache_dir) if cache_dir else None,
    )
    if sample_ids is not None:
        return [s for s in stream if s.sample_id in sample_ids]
    if limit is None:
        return list(stream)
    return reservoir_sample(stream, limit, seed)
