import json
import zipfile
from pathlib import Path

import pytest

from marl_agents.evaluation.datasets import load_codereviewer, reservoir_sample, stream_codereviewer
from marl_agents.evaluation.datasets.codereviewer import CLS_ZIP, MSG_DIR

FIXTURE = Path(__file__).parents[2] / "fixtures" / "datasets" / "codereviewer" / "records.jsonl"


@pytest.fixture
def dataset_root(tmp_path: Path) -> Path:
    """Lay out the fixture records exactly like the real dataset (msg JSONL + cls zip)."""
    records = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    msg_dir = tmp_path / MSG_DIR
    msg_dir.mkdir(parents=True)
    with (msg_dir / "msg-test.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            # In the real comment-generation split every diff has a comment and y == 1.
            fh.write(json.dumps({**r, "y": 1, "msg": r["msg"] or "looks good"}) + "\n")
    zpath = tmp_path / CLS_ZIP
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(
            "Diff_Quality_Estimation/cls-test.jsonl",
            "".join(json.dumps(r) + "\n" for r in records),
        )
    return tmp_path


def test_msg_stream_filters_language_and_parses(dataset_root: Path) -> None:
    samples = list(stream_codereviewer("msg", "test", dataset_root, {"py"}))
    assert [s.lang for s in samples] == ["py"] * 4
    assert all(s.label == 1 and s.msg and s.patch.startswith("@@") for s in samples)
    assert len({s.sample_id for s in samples}) == 4


def test_cls_stream_reads_from_zip_with_string_labels(dataset_root: Path) -> None:
    samples = list(stream_codereviewer("cls", "test", dataset_root, {"py"}))
    assert sorted(s.label for s in samples) == [0, 0, 1, 1]
    assert len(list(stream_codereviewer("cls", "test", dataset_root, None))) == 5


def test_reservoir_sampling_is_deterministic_and_ordered(dataset_root: Path) -> None:
    a = load_codereviewer("cls", limit=2, seed=1, root=dataset_root, cache_dir=None)
    b = load_codereviewer("cls", limit=2, seed=1, root=dataset_root, cache_dir=None)
    assert [s.sample_id for s in a] == [s.sample_id for s in b] and len(a) == 2
    items = list(range(100))
    picked = reservoir_sample(items, 10, seed=3)  # type: ignore[arg-type]
    assert picked == sorted(picked) and len(set(picked)) == 10
    assert reservoir_sample(items, 10, seed=3) == picked  # type: ignore[arg-type]


def test_sample_ids_reproduce_a_previous_run(dataset_root: Path) -> None:
    first = load_codereviewer("msg", limit=2, seed=7, root=dataset_root, cache_dir=None)
    again = load_codereviewer(
        "msg", root=dataset_root, cache_dir=None, sample_ids={s.sample_id for s in first}
    )
    assert [s.sample_id for s in again] == [s.sample_id for s in first]


def test_cache_is_written_once_and_reused(dataset_root: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    first = load_codereviewer("cls", root=dataset_root, cache_dir=cache)
    files = list(cache.glob("*.jsonl"))
    assert len(files) == 1 and not list(cache.glob("*.tmp"))
    (dataset_root / CLS_ZIP).unlink()  # the cache must now be sufficient
    second = load_codereviewer("cls", root=dataset_root, cache_dir=cache)
    assert [s.model_dump() for s in first] == [s.model_dump() for s in second]


@pytest.mark.dataset
def test_real_codereviewer_python_test_split_counts() -> None:
    root = Path(__file__).parents[3] / "capstone-datasets"
    n = sum(1 for _ in stream_codereviewer("msg", "test", root, {"py"}))
    assert n == 1403
