"""Turn a directory, ZIP archive or code snippet into a filtered `Repository`. Never runs code."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid
from collections import Counter
from pathlib import Path, PurePosixPath

from marl_agents.config import IngestionSettings
from marl_agents.ingestion.models import Repository, SourceFile, classify, language_for
from marl_agents.ingestion.safe_zip import safe_extract_zip

logger = logging.getLogger(__name__)

_BINARY_SNIFF_BYTES = 8192


class IngestionError(ValueError):
    """The input could not be turned into a repository."""


def _looks_binary(path: Path) -> bool:
    with path.open("rb") as fh:
        return b"\x00" in fh.read(_BINARY_SNIFF_BYTES)


def load_directory(root: Path, settings: IngestionSettings | None = None) -> Repository:
    """Keep reviewable text files; skip ignored dirs, symlinks, binaries and huge files."""
    settings = settings or IngestionSettings()
    root = root.resolve()
    if not root.is_dir():
        raise IngestionError(f"{root} is not a directory")

    include = {e.lower() for e in settings.include_extensions}
    ignore = set(settings.ignore_dirs)
    files: list[SourceFile] = []
    skipped: Counter[str] = Counter()

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Prune in place so os.walk never descends into ignored or hidden-tool directories.
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in ignore
            and not d.endswith(".egg-info")
            and not (Path(dirpath) / d).is_symlink()
        )
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = PurePosixPath(full.relative_to(root).as_posix())
            if full.is_symlink():
                skipped["symlink"] += 1
                continue
            if full.suffix.lower() not in include:
                skipped["extension"] += 1
                continue
            size = full.stat().st_size
            if size > settings.max_file_bytes:
                skipped["too_large"] += 1
                continue
            if _looks_binary(full):
                skipped["binary"] += 1
                continue
            path = str(rel)
            files.append(
                SourceFile(path=path, size=size, language=language_for(path), kind=classify(path))
            )
            if len(files) > settings.max_files:
                raise IngestionError(f"More than {settings.max_files} reviewable files")

    logger.info("Loaded %d files from %s (skipped: %s)", len(files), root, dict(skipped))
    return Repository(root=root, files=files, skipped=dict(skipped))


def new_workspace(settings: IngestionSettings) -> Path:
    base = Path(settings.workspace_dir)
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="job_", dir=base))


def load_zip(zip_path: Path, settings: IngestionSettings | None = None) -> Repository:
    """Safely extract an uploaded ZIP into a fresh workspace and load it."""
    settings = settings or IngestionSettings()
    workspace = new_workspace(settings)
    try:
        repo_root = safe_extract_zip(zip_path, workspace / "src", settings)
        repo = load_directory(repo_root, settings)
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
    repo.workspace = workspace
    return repo


def load_snippet(
    code: str, filename: str = "snippet.py", settings: IngestionSettings | None = None
) -> Repository:
    """Materialise a snippet as a one-file repository so every stage works unchanged."""
    settings = settings or IngestionSettings()
    safe_name = PurePosixPath(filename.replace("\\", "/")).name or "snippet.py"
    if not safe_name.endswith(".py"):
        safe_name += ".py"
    job = new_workspace(settings)
    workspace = job / f"snippet_{uuid.uuid4().hex[:8]}"
    workspace.mkdir(parents=True)
    # newline="\n": no CRLF translation on Windows (keeps line numbers exact on re-analysis)
    (workspace / safe_name).write_text(code, encoding="utf-8", newline="\n")
    repo = load_directory(workspace, settings)
    repo.workspace = job
    return repo


def load_files(files: dict[str, str], settings: IngestionSettings | None = None) -> Repository:
    """Materialise several in-memory files (path -> content) as a repository."""
    settings = settings or IngestionSettings()
    for rel in files:
        parts = PurePosixPath(rel.replace("\\", "/")).parts
        if (
            not parts
            or any(p in ("..", "") for p in parts)
            or rel.startswith(("/", "\\"))
            or ":" in rel
        ):
            raise IngestionError(f"Unsafe file path: {rel!r}")
    job = new_workspace(settings)
    workspace = job / f"files_{uuid.uuid4().hex[:8]}"
    for rel, content in files.items():
        target = workspace.joinpath(*PurePosixPath(rel.replace("\\", "/")).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")  # see load_snippet
    repo = load_directory(workspace, settings)
    repo.workspace = job
    return repo


def load_repository(source: str | Path, settings: IngestionSettings | None = None) -> Repository:
    """Dispatch on the input: a .zip file or a directory."""
    path = Path(source)
    if path.is_file() and path.suffix.lower() == ".zip":
        return load_zip(path, settings)
    if path.is_dir():
        return load_directory(path, settings)
    raise IngestionError(f"Unsupported input {source!s}: expected a directory or a .zip file")
