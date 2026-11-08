"""Source of BugsInPy projects, one commit at a time. Fetches and reads; never runs project code.

Each project is one bare repository under `data/cache/bugsinpy/repos/`, created with no hooks.
Commits are fetched shallowly by id, so the disk holds a few snapshots rather than a project's
history. That also means no retrieval can reach a later commit: nothing later is there.

`resolve_bug` turns a dataset entry into what an experiment needs, or says why it cannot be used.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import textwrap
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import IO, cast

from pydantic import BaseModel, Field

from marl_agents.config import IngestionSettings
from marl_agents.evaluation.datasets.bugsinpy import BugsInPySample, patch_for_file
from marl_agents.ingestion.diff import parse_hunks
from marl_agents.parsing.python_ast import ModuleInfo, SymbolInfo, SymbolKind, parse_python

logger = logging.getLogger(__name__)

GIT_TIMEOUT_S = 900
MIN_FREE_BYTES = 3 * 1024**3  # this machine's disk is nearly full: stop before it is
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_ANY_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_GITHUB = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+$")
_WINDOWS_BAD = re.compile(r'[<>:"|?*\x00-\x1f]')


class RepoCacheError(RuntimeError):
    """A commit could not be fetched or read."""


class DiskSpaceError(RuntimeError):
    """Stopped before filling the disk. Not a problem with any one bug."""


class IneligibleBug(ValueError):
    """This bug cannot be used; `reason` is reported in the eligibility audit."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class GoldFunction(BaseModel):
    """A function the gold patch changes."""

    file: str
    qualname: str
    buggy_start: int
    buggy_end: int
    fixed_start: int | None = None
    fixed_end: int | None = None
    changed_lines: list[int] = Field(default_factory=list, description="In the buggy file.")


class ResolvedBug(BaseModel):
    """A bug with source located: everything an experiment needs except the code itself."""

    sample: BugsInPySample
    buggy_commit: str = Field(description="Full id.")
    fixed_commit: str
    file: str
    gold: list[GoldFunction]
    failing_test: str = Field(description="Source of the failing test(s), from the fixed commit.")
    test_path: str

    @property
    def sample_id(self) -> str:
        return self.sample.sample_id


def _github_full_sha(url: str, short: str) -> str | None:
    """Ask GitHub for a commit's full id (pandas lists short ids). None if it does not know."""
    owner_repo = url.removeprefix("https://github.com/")
    api = f"https://api.github.com/repos/{owner_repo}/commits/{short}"
    request = urllib.request.Request(
        api, headers={"User-Agent": "marl-agents-evaluation", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("Could not resolve %s from GitHub: %s", short, exc)
        return None
    sha = data.get("sha")
    return sha if isinstance(sha, str) and _FULL_SHA.match(sha) else None


class BugRepoCache:
    def __init__(self, cache_dir: Path) -> None:
        self.dir = cache_dir / "bugsinpy" / "repos"
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---- git -----------------------------------------------------------------------------------

    def _repo(self, project: str) -> Path:
        if not re.fullmatch(r"[\w.-]+", project):
            raise RepoCacheError(f"unsafe project name: {project!r}")
        return self.dir / f"{project}.git"

    @staticmethod
    def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
        command = ["git", "-c", "protocol.ext.allow=never", "-C", str(repo), *args]
        try:
            done = subprocess.run(  # noqa: S603 - fixed program, arguments validated by callers
                command, capture_output=True, timeout=GIT_TIMEOUT_S, env=env, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RepoCacheError(f"git {args[0]}: {exc}") from exc
        if check and done.returncode != 0:
            message = done.stderr.decode("utf-8", errors="replace")[:300]
            raise RepoCacheError(f"git {args[0]}: {message}")
        return done

    def _ensure_repo(self, project: str, url: str) -> Path:
        if not _GITHUB.match(url):
            raise RepoCacheError(f"unexpected repository url: {url!r}")
        repo = self._repo(project)
        if not repo.exists():
            repo.mkdir(parents=True)
            self._git(repo, "init", "-q", "--bare", "--template=")
            self._git(repo, "remote", "add", "origin", url)
        return repo

    def _has_commit(self, repo: Path, sha: str) -> bool:
        return self._git(repo, "cat-file", "-e", f"{sha}^{{tree}}", check=False).returncode == 0

    def _fetch(self, repo: Path, sha: str, depth: int) -> None:
        free = shutil.disk_usage(self.dir).free
        if free < MIN_FREE_BYTES:
            raise DiskSpaceError(f"only {free / 1024**3:.1f} GB free; stopping before fetching")
        self._git(
            repo, "fetch", "-q", f"--depth={depth}", "--no-tags", "--no-recurse-submodules",
            "origin", sha,
        )  # fmt: skip

    def ensure_commits(self, sample: BugsInPySample) -> tuple[str, str]:
        """(buggy, fixed) as full ids, both present locally."""
        for sha in (sample.buggy_commit, sample.fixed_commit):
            if not _ANY_SHA.match(sha):
                raise RepoCacheError(f"not a commit id: {sha!r}")
        repo = self._ensure_repo(sample.project, sample.github_url)
        fixed = sample.fixed_commit
        if not _FULL_SHA.match(fixed):
            resolved = _github_full_sha(sample.github_url, fixed)
            if resolved is None:
                raise RepoCacheError(f"cannot resolve {fixed}")
            fixed = resolved
        if not self._has_commit(repo, fixed):
            self._fetch(repo, fixed, 2)  # depth 2 also brings the parent, usually the buggy commit
        buggy = sample.buggy_commit
        if not _FULL_SHA.match(buggy):
            found = self._git(
                repo, "rev-parse", "--verify", "-q", f"{buggy}^{{commit}}", check=False
            )
            text = found.stdout.decode("ascii", errors="replace").strip()
            buggy = text if found.returncode == 0 else (
                _github_full_sha(sample.github_url, buggy) or ""
            )  # fmt: skip
            if not buggy:
                raise RepoCacheError(f"cannot resolve {sample.buggy_commit}")
        if not self._has_commit(repo, buggy):
            self._fetch(repo, buggy, 1)
        return buggy, fixed

    def show(self, project: str, sha: str, path: str) -> str | None:
        """A file's text at a commit, or None if it is not there."""
        done = self._git(self._repo(project), "show", f"{sha}:{path}", check=False)
        if done.returncode != 0:
            return None
        return done.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")

    # ---- snapshots -----------------------------------------------------------------------------

    def snapshot(
        self, project: str, sha: str, dest: Path, settings: IngestionSettings | None = None
    ) -> int:
        """Write the reviewable files of a commit to `dest`. Returns how many.

        `git archive` output is untrusted: only plain files inside `dest` are written, nothing is
        extracted by a tool, and names Windows cannot store are skipped.
        """
        settings = settings or IngestionSettings()
        include = {e.lower() for e in settings.include_extensions}
        ignore = set(settings.ignore_dirs)
        repo = self._repo(project)
        command = ["git", "-C", str(repo), "archive", "--format=tar", sha]
        process = subprocess.Popen(  # noqa: S603 - fixed program, validated commit id
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        written = 0
        try:
            with tarfile.open(fileobj=cast(IO[bytes], process.stdout), mode="r|") as archive:
                for member in archive:
                    if not self._wanted(member, include, ignore, settings.max_file_bytes):
                        continue
                    data = archive.extractfile(member)
                    if data is None:
                        continue
                    target = dest.joinpath(*PurePosixPath(member.name).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data.read())
                    written += 1
        finally:
            if process.stdout is not None:
                process.stdout.close()
            process.wait(timeout=60)
        if written == 0:
            raise RepoCacheError(f"no files in snapshot of {project}@{sha[:8]}")
        return written

    @staticmethod
    def _wanted(member: tarfile.TarInfo, include: set[str], ignore: set[str], limit: int) -> bool:
        if not member.isfile() or member.size > limit:
            return False
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or path.suffix.lower() not in include:
            return False
        if any(_WINDOWS_BAD.search(p) or p.endswith((".", " ")) for p in path.parts):
            return False
        return not (set(path.parts[:-1]) & ignore)


# ---- gold locations ------------------------------------------------------------------------------


def gold_lines(patch: str, buggy_text: str) -> list[int]:
    """Lines of the buggy file the patch touches; an insertion counts as the line before it.

    Raises IneligibleBug if the patch does not describe this file, which would make every score
    meaningless.
    """
    lines = buggy_text.splitlines()
    touched: list[int] = []
    for hunk in parse_hunks(patch):
        old = hunk.old_start
        for raw in hunk.lines:
            tag, text = raw[0], raw[1:]
            if tag == "+":
                touched.append(max(old - 1, 1))
                continue
            if old > len(lines) or lines[old - 1].rstrip() != text.rstrip():
                raise IneligibleBug("patch_does_not_match_buggy_commit", f"line {old}")
            if tag == "-":
                touched.append(old)
            old += 1
    return sorted(set(touched))


def _innermost_function(module: ModuleInfo, line: int) -> SymbolInfo | None:
    around = [
        s
        for s in module.symbols
        if s.kind is not SymbolKind.CLASS and s.start_line <= line <= s.end_line
    ]
    return min(around, key=lambda s: s.line_span, default=None)


def locate_gold(sample: BugsInPySample, buggy_text: str, fixed_text: str) -> list[GoldFunction]:
    path = sample.source_files[0]
    lines = gold_lines(patch_for_file(sample.patch, path), buggy_text)
    buggy, fixed = parse_python(buggy_text, path), parse_python(fixed_text, path)
    if buggy.syntax_error or fixed.syntax_error:
        raise IneligibleBug("not_parseable_by_python_3")
    if not lines:
        raise IneligibleBug("patch_changes_no_lines")
    functions: dict[str, GoldFunction] = {}
    for line in lines:
        symbol = _innermost_function(buggy, line)
        if symbol is None:
            raise IneligibleBug("change_outside_a_function", f"line {line}")
        gold = functions.setdefault(
            symbol.qualname,
            GoldFunction(
                file=path,
                qualname=symbol.qualname,
                buggy_start=symbol.start_line,
                buggy_end=symbol.end_line,
            ),
        )
        gold.changed_lines.append(line)
    after = {s.qualname: s for s in fixed.symbols if s.kind is not SymbolKind.CLASS}
    for gold in functions.values():
        match = after.get(gold.qualname)
        if match is None:
            raise IneligibleBug("function_gone_after_fix", gold.qualname)
        gold.fixed_start, gold.fixed_end = match.start_line, match.end_line
    return list(functions.values())


def _nodes(source: str, path: str) -> list[ast.AST]:
    try:
        return list(ast.walk(ast.parse(source, filename=path)))
    except (SyntaxError, ValueError):
        return []


def extract_tests(source: str, path: str, names: list[str]) -> str:
    """The source of the named test functions, or '' if none is found."""
    lines = source.splitlines()
    wanted = set(names)
    parts = [
        textwrap.dedent("\n".join(lines[n.lineno - 1 : n.end_lineno]))
        for n in _nodes(source, path)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name in wanted
    ]
    return "\n\n".join(dict.fromkeys(parts))


def resolve_bug(sample: BugsInPySample, cache: BugRepoCache) -> ResolvedBug:
    """Locate a bug's gold functions and failing test. Raises IneligibleBug if it cannot be used."""
    try:
        buggy, fixed = cache.ensure_commits(sample)
    except RepoCacheError as exc:
        raise IneligibleBug("commit_unavailable", str(exc)[:120]) from exc
    path = sample.source_files[0]
    buggy_text = cache.show(sample.project, buggy, path)
    fixed_text = cache.show(sample.project, fixed, path)
    if buggy_text is None or fixed_text is None:
        raise IneligibleBug("patched_file_missing", path)
    gold = locate_gold(sample, buggy_text, fixed_text)
    if not sample.test_names:
        raise IneligibleBug("failing_test_not_named")
    for test_path in sample.test_files:
        source = cache.show(sample.project, fixed, test_path)
        if source is None:
            continue
        code = extract_tests(source, test_path, sample.test_names)
        if code:
            return ResolvedBug(
                sample=sample,
                buggy_commit=buggy,
                fixed_commit=fixed,
                file=path,
                gold=gold,
                failing_test=code,
                test_path=test_path,
            )
    raise IneligibleBug("failing_test_not_found")
