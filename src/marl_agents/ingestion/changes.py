"""Load a code CHANGE (before/after) for change review: from git refs, the working tree, the index,
or two ZIP archives.

Safety: git is never asked to run anything configured inside the repository. File contents are read
raw from the object database (`ls-tree` + `cat-file --batch`), which applies no filters, hooks or
fsmonitor; every call also disables hooks and fsmonitor explicitly. The diff is computed here with
difflib, so one code path serves git, ZIPs and directories alike.
"""

from __future__ import annotations

import difflib
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from marl_agents.config import IngestionSettings
from marl_agents.ingestion.diff import Hunk, changed_new_lines, parse_hunks
from marl_agents.ingestion.loader import IngestionError, load_directory, load_zip, new_workspace
from marl_agents.ingestion.models import Repository

logger = logging.getLogger(__name__)

GIT_TIMEOUT_S = 60
_SAFE_REF = re.compile(r"^[A-Za-z0-9._/@~^{}:+-]{1,200}$")
_GIT_SAFETY = ["-c", "core.hooksPath=", "-c", "core.fsmonitor=false", "-c", "core.quotepath=off"]
RENAME_SIMILARITY = 0.85


@dataclass
class FileDiff:
    path: str
    status: str  # added | modified | deleted | renamed
    old_path: str | None
    patch: str
    hunks: list[Hunk]
    added: int
    deleted: int
    changed_ranges: list[tuple[int, int]]


@dataclass
class ChangeSet:
    """A reviewable change: the full NEW version as a Repository + the old text of changed files."""

    base: str
    head: str
    repo: Repository
    old_sources: dict[str, str]
    files: list[FileDiff] = field(default_factory=list)
    _cleanup: list[Repository] = field(default_factory=list, repr=False)

    def scope(self) -> dict[str, list[tuple[int, int]]]:
        """Changed line ranges per file that exists in the new version (diff-review scope)."""
        return {
            f.path: f.changed_ranges
            for f in self.files
            if f.status != "deleted" and f.changed_ranges and self.repo.has(f.path)
        }

    @property
    def python_files(self) -> list[FileDiff]:
        return [f for f in self.files if f.path.endswith(".py")]

    def cleanup(self) -> None:
        for repo in [self.repo, *self._cleanup]:
            repo.cleanup()


class ChangeError(IngestionError):
    """The change could not be loaded (bad ref, not a git repo, no differences...)."""


def normalize_newlines(text: str) -> str:
    """CRLF/CR -> LF. Windows checkouts (core.autocrlf) differ from the stored blobs only in line
    endings; without this every line of every file would look changed."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ---------------------------------------------------------------------------------------------
# Diffing two versions
# ---------------------------------------------------------------------------------------------


def _unified(old: str, new: str, old_path: str, new_path: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile=f"a/{old_path}" if old else "/dev/null",
        tofile=f"b/{new_path}" if new else "/dev/null",
        n=3,
        lineterm="",
    )
    return "\n".join(lines)


def _file_diff(path: str, old: str, new: str, status: str, old_path: str | None) -> FileDiff | None:
    patch = _unified(old, new, old_path or path, path)
    if not patch:
        return None
    hunks = parse_hunks(patch)
    added = sum(1 for h in hunks for ln in h.lines if ln.startswith("+"))
    deleted = sum(1 for h in hunks for ln in h.lines if ln.startswith("-"))
    ranges = changed_new_lines(patch) if status != "deleted" else []
    return FileDiff(path, status, old_path, patch, hunks, added, deleted, ranges)


def diff_versions(old: dict[str, str], new: dict[str, str]) -> list[FileDiff]:
    """Compare two {path: text} maps; detects added, deleted, modified and renamed files."""
    added = sorted(set(new) - set(old))
    deleted = sorted(set(old) - set(new))
    renames: dict[str, str] = {}  # new path -> old path
    for new_path in added:
        best, best_ratio = None, 0.0
        for old_path in deleted:
            if (
                old_path in renames.values()
                or PurePosixPath(old_path).suffix != PurePosixPath(new_path).suffix
            ):
                continue
            ratio = difflib.SequenceMatcher(
                None, old[old_path], new[new_path], autojunk=False
            ).quick_ratio()
            if ratio >= RENAME_SIMILARITY and ratio > best_ratio:
                best, best_ratio = old_path, ratio
        if best is not None:
            renames[new_path] = best

    out: list[FileDiff] = []
    for path in sorted(set(old) | set(new)):
        if path in renames.values():
            continue
        if path in renames:
            d = _file_diff(path, old[renames[path]], new[path], "renamed", renames[path])
            if d is None:  # pure rename, no content change: still report it
                d = FileDiff(path, "renamed", renames[path], "", [], 0, 0, [])
        elif path not in old:
            d = _file_diff(path, "", new[path], "added", None)
        elif path not in new:
            d = _file_diff(path, old[path], "", "deleted", path)
        elif old[path] == new[path]:
            continue
        else:
            d = _file_diff(path, old[path], new[path], "modified", path)
        if d is not None:
            out.append(d)
    return out


def _texts(repo: Repository) -> dict[str, str]:
    return {f.path: normalize_newlines(repo.read_text(f.path)) for f in repo.files}


def changeset_from_repos(
    old_repo: Repository, new_repo: Repository, base: str, head: str
) -> ChangeSet:
    old = _texts(old_repo)
    files = diff_versions(old, _texts(new_repo))
    if not files:
        raise ChangeError(f"No differences between {base} and {head}")
    old_sources = {f.old_path: old[f.old_path] for f in files if f.old_path and f.old_path in old}
    return ChangeSet(base, head, new_repo, old_sources, files, _cleanup=[old_repo])


def changeset_from_zips(
    before_zip: Path, after_zip: Path, settings: IngestionSettings | None = None
) -> ChangeSet:
    settings = settings or IngestionSettings()
    old_repo = load_zip(before_zip, settings)
    try:
        new_repo = load_zip(after_zip, settings)
    except Exception:
        old_repo.cleanup()
        raise
    try:
        return changeset_from_repos(old_repo, new_repo, before_zip.name, after_zip.name)
    except Exception:
        old_repo.cleanup()
        new_repo.cleanup()
        raise


# ---------------------------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------------------------


def _git_binary() -> str:
    git = shutil.which("git")
    if git is None:
        raise ChangeError("git is not installed or not on PATH")
    return git


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    cmd = [_git_binary(), *_GIT_SAFETY, "-C", str(repo), *args]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed binary, argument list, no shell
            cmd, input=input_bytes, capture_output=True, timeout=GIT_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise ChangeError(f"git {args[0]} timed out") from exc
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ChangeError(f"git {args[0]} failed: {msg[-1] if msg else proc.returncode}")
    return proc.stdout


def _check_ref(ref: str) -> str:
    if ref.startswith("-") or not _SAFE_REF.match(ref):
        raise ChangeError(f"Invalid git reference: {ref!r}")
    return ref


def resolve_commit(repo: Path, ref: str) -> str:
    return (
        _git(repo, "rev-parse", "--verify", "--quiet", f"{_check_ref(ref)}^{{commit}}")
        .decode()
        .strip()
    )


def _wanted(path: str, settings: IngestionSettings) -> bool:
    p = PurePosixPath(path)
    if any(part in settings.ignore_dirs or part.endswith(".egg-info") for part in p.parts[:-1]):
        return False
    return p.suffix.lower() in {e.lower() for e in settings.include_extensions}


def _read_blobs(
    repo: Path, entries: list[tuple[str, str]], settings: IngestionSettings
) -> dict[str, str]:
    """entries = [(sha, path)] -> {path: text} via one `git cat-file --batch` (raw, no filters)."""
    if len(entries) > settings.max_files:
        raise ChangeError(f"More than {settings.max_files} reviewable files in the revision")
    if not entries:
        return {}
    out = _git(
        repo, "cat-file", "--batch", input_bytes="".join(f"{sha}\n" for sha, _ in entries).encode()
    )
    texts: dict[str, str] = {}
    pos = 0
    for sha, path in entries:
        header_end = out.index(b"\n", pos)
        header = out[pos:header_end].decode().split()
        if len(header) < 3 or header[1] != "blob":
            raise ChangeError(f"Unexpected object for {path}: {header}")
        size = int(header[2])
        data = out[header_end + 1 : header_end + 1 + size]
        pos = header_end + 1 + size + 1  # trailing newline
        if size > settings.max_file_bytes or b"\x00" in data[:8192]:
            continue  # too large or binary: skipped like in directory loading
        texts[path] = normalize_newlines(data.decode("utf-8", errors="replace"))
        del sha
    return texts


def _tree_texts(repo: Path, commit: str, settings: IngestionSettings) -> dict[str, str]:
    listing = _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit)
    entries = []
    for rec in listing.split(b"\x00"):
        if not rec:
            continue
        meta, _, path_b = rec.partition(b"\t")
        mode, otype, sha = meta.decode().split()
        path = path_b.decode("utf-8", "replace")
        if otype == "blob" and mode in ("100644", "100755") and _wanted(path, settings):
            entries.append((sha, path))
    return _read_blobs(repo, entries, settings)


def _index_texts(repo: Path, settings: IngestionSettings) -> dict[str, str]:
    listing = _git(repo, "ls-files", "-s", "-z")
    entries = []
    for rec in listing.split(b"\x00"):
        if not rec:
            continue
        meta, _, path_b = rec.partition(b"\t")
        mode, sha, stage = meta.decode().split()
        path = path_b.decode("utf-8", "replace")
        if stage == "0" and mode in ("100644", "100755") and _wanted(path, settings):
            entries.append((sha, path))
    return _read_blobs(repo, entries, settings)


def _materialise(texts: dict[str, str], settings: IngestionSettings, label: str) -> Repository:
    """Write a version to a fresh workspace so every stage can read it from disk."""
    job = new_workspace(settings)
    root = job / label
    for rel, content in texts.items():
        target = root.joinpath(*PurePosixPath(rel).parts)
        if not target.resolve().is_relative_to(root.resolve()):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as fh:  # keep LF on Windows
            fh.write(content)
    root.mkdir(parents=True, exist_ok=True)
    repo = load_directory(root, settings)
    repo.workspace = job
    return repo


def check_git_target(repo_path: str | Path, base: str, head: str | None = None) -> Path:
    """Fail fast (ChangeError) unless `repo_path` is a git repository and the refs exist.

    Returns the repository's top-level directory. Cheap: a few `git rev-parse` calls.
    """
    repo = Path(repo_path).expanduser().resolve()
    if not repo.is_dir():
        raise ChangeError(f"{repo} is not a directory")
    try:
        top = Path(_git(repo, "rev-parse", "--show-toplevel").decode().strip())
    except ChangeError as exc:
        raise ChangeError(f"{repo} is not a git repository") from exc
    for ref in (base, head):
        if ref is not None:
            try:
                resolve_commit(top, ref)
            except ChangeError as exc:
                raise ChangeError(f"Unknown or invalid git reference: {ref!r}") from exc
    return top


def changeset_from_git(
    repo_path: str | Path,
    base: str,
    head: str | None = None,
    staged: bool = False,
    settings: IngestionSettings | None = None,
) -> ChangeSet:
    """Review `base..head`. head=None -> the working tree; staged=True -> the index (pre-commit)."""
    settings = settings or IngestionSettings()
    repo = check_git_target(repo_path, base, head)
    base_sha = resolve_commit(repo, base)
    old_repo = _materialise(_tree_texts(repo, base_sha, settings), settings, "base")
    try:
        if staged:
            new_texts, head_label = _index_texts(repo, settings), "staged changes"
        elif head is not None:
            head_sha = resolve_commit(repo, head)
            new_texts, head_label = (
                _tree_texts(repo, head_sha, settings),
                f"{head} ({head_sha[:8]})",
            )
        else:
            disk = load_directory(repo, settings)
            new_texts, head_label = _texts(disk), "working tree"
        new_repo = _materialise(new_texts, settings, "head")
    except Exception:
        old_repo.cleanup()
        raise
    try:
        return changeset_from_repos(old_repo, new_repo, f"{base} ({base_sha[:8]})", head_label)
    except Exception:
        old_repo.cleanup()
        new_repo.cleanup()
        raise
