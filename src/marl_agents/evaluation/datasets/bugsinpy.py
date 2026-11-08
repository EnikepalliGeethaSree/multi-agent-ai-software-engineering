"""BugsInPy (Widyasari et al., ESEC/FSE 2020): real bugs from 17 Python projects.

A bug's folder holds metadata only: commits, the gold patch and the failing test. Source comes from
`bugsinpy_repo.py`. Nothing here runs a project's code.

Split. Dev and test share no project, so a prompt tuned on dev has never seen a test project.
BugsInPy has no split of its own, so this one is ours; it is fixed in `DEV_PROJECTS`.

Pool. `is_small_fix` keeps bugs fixed in one source file with at most `MAX_CHANGED_LINES` changed
lines. Results apply to such bugs, not to bugs in general.

Sampling is round-robin over projects, so pandas (170 of 501 bugs) cannot dominate a sample.
"""

from __future__ import annotations

import logging
import random
import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, Field

from marl_agents.ingestion.diff import parse_hunks
from marl_agents.ingestion.models import FileKind, classify

logger = logging.getLogger(__name__)

PROJECTS_DIR = "bugsinpy/projects"
MAX_CHANGED_LINES = 10
DEV_PROJECTS = frozenset(
    {"black", "cookiecutter", "httpie", "PySnooper", "sanic", "tornado", "tqdm"}
)
SPLITS = ("dev", "test")

# `key="value"`, found anywhere: some files have two pairs on one line, or `cause="N.A."` before
# the URL with no newline between them, and youtube-dl writes `fixed_commit_id ="..."`.
_PAIR = re.compile(r'([A-Za-z_]+)\s*=\s*"([^"]*)"')
_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/\S+$", re.MULTILINE)
_PYTEST_ID = re.compile(r"(\S+\.py)((?:::[^\s\"';]+)+)")
_UNITTEST = re.compile(r"unittest\s+(?:-\S+\s+)*([\w.]+)")


class BugsInPySample(BaseModel):
    """One bug as the dataset describes it, before its source is fetched."""

    sample_id: str
    project: str
    bug_id: int
    github_url: str
    python_version: str = ""
    buggy_commit: str
    fixed_commit: str
    test_files: list[str] = Field(default_factory=list)
    test_names: list[str] = Field(default_factory=list, description="Failing tests, unqualified.")
    patch: str = Field(repr=False)
    source_files: list[str] = Field(default_factory=list, description="Non-test files patched.")
    changed_lines: int = 0

    @property
    def split(self) -> str:
        return "dev" if self.project in DEV_PROJECTS else "test"


def parse_pairs(text: str) -> dict[str, str]:
    return dict(_PAIR.findall(text))


def parse_test_names(run_test: str) -> list[str]:
    """Failing test names from run_test.sh: pytest ids or dotted unittest paths."""
    names: list[str] = []
    for line in run_test.splitlines():
        for _path, nodes in _PYTEST_ID.findall(line):
            names.append(nodes.split("::")[-1].split("[")[0])
        if "unittest" in line and "::" not in line:
            names.extend(m.split(".")[-1] for m in _UNITTEST.findall(line))
    return list(dict.fromkeys(n for n in names if n))


def patch_for_file(patch: str, path: str) -> str:
    """The part of a multi-file diff that changes `path`."""
    parts = re.split(r"(?m)^(?=diff --git )", patch)
    return next((p for p in parts if p.startswith(f"diff --git a/{path} ")), "")


def changed_line_count(patch: str) -> int:
    return sum(1 for hunk in parse_hunks(patch) for line in hunk.lines if line[0] in "+-")


def read_bug(bug_dir: Path, github_url: str) -> BugsInPySample | None:
    """None when a folder is not a complete bug (for example a stray file)."""
    info_path, patch_path = bug_dir / "bug.info", bug_dir / "bug_patch.txt"
    if not (info_path.is_file() and patch_path.is_file()):
        return None
    info = parse_pairs(info_path.read_text(encoding="utf-8", errors="replace"))
    patch = patch_path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    run_test = bug_dir / "run_test.sh"
    project, bug_id = bug_dir.parent.parent.name, int(bug_dir.name)
    files = _DIFF_FILE.findall(patch)
    return BugsInPySample(
        sample_id=f"{project}-{bug_id}",
        project=project,
        bug_id=bug_id,
        github_url=github_url.rstrip("/"),
        python_version=info.get("python_version", ""),
        buggy_commit=info["buggy_commit_id"],
        fixed_commit=info["fixed_commit_id"],
        test_files=[t for t in re.split(r"[;\s]+", info.get("test_file", "")) if t],
        test_names=parse_test_names(
            run_test.read_text(encoding="utf-8", errors="replace") if run_test.is_file() else ""
        ),
        patch=patch,
        source_files=[f for f in files if classify(f) is FileKind.CODE and f.endswith(".py")],
        changed_lines=changed_line_count(patch),
    )


def iter_bugs(root: Path) -> Iterator[BugsInPySample]:
    """Every bug, in a stable order."""
    projects = root / PROJECTS_DIR
    if not projects.is_dir():
        raise FileNotFoundError(f"BugsInPy not found at {projects}")
    # Sorted by name: Path order ignores case on Windows, which would change the sample.
    for project in sorted((p for p in projects.iterdir() if p.is_dir()), key=lambda p: p.name):
        info = project / "project.info"
        url = parse_pairs(info.read_text(encoding="utf-8", errors="replace")).get("github_url", "")
        bugs = sorted(
            (d for d in (project / "bugs").iterdir() if d.is_dir() and d.name.isdigit()),
            key=lambda d: int(d.name),
        )
        for bug_dir in bugs:
            sample = read_bug(bug_dir, url)
            if sample is not None:
                yield sample


def is_small_fix(sample: BugsInPySample) -> bool:
    return len(sample.source_files) == 1 and sample.changed_lines <= MAX_CHANGED_LINES


def ordered_candidates(
    bugs: list[BugsInPySample], split: str, seed: int = 42
) -> list[BugsInPySample]:
    """The split's pool in sampling order: shuffled per project, then round-robin over projects.

    The first n are the sample; a caller replaces an unusable bug with the next one, and the same
    seed always gives the same order.
    """
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; choose from {SPLITS}")
    by_project: dict[str, list[BugsInPySample]] = defaultdict(list)
    for bug in bugs:
        if bug.split == split and is_small_fix(bug):
            by_project[bug.project].append(bug)
    rng = random.Random(seed)
    queues = []
    for project in sorted(by_project):
        queue = sorted(by_project[project], key=lambda b: b.bug_id)
        rng.shuffle(queue)
        queues.append(queue)
    ordered: list[BugsInPySample] = []
    while any(queues):
        for queue in queues:
            if queue:
                ordered.append(queue.pop(0))
    return ordered


def load_bugsinpy(
    split: str, limit: int | None = None, seed: int = 42, root: Path | None = None
) -> list[BugsInPySample]:
    """Small-fix bugs of a split in sampling order. Needs no source checkout."""
    ordered = ordered_candidates(list(iter_bugs(root or Path("capstone-datasets"))), split, seed)
    return ordered if limit is None else ordered[:limit]
