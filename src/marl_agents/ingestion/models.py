"""In-memory view of an ingested repository. Files are read lazily and cached."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict


class FileKind(StrEnum):
    CODE = "code"
    TEST = "test"
    DOC = "doc"
    CONFIG = "config"


_LANGUAGES = {
    ".py": "python",
    ".md": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".cfg": "ini",
    ".ini": "ini",
}


def language_for(path: str) -> str:
    return _LANGUAGES.get(PurePosixPath(path).suffix.lower(), "unknown")


def classify(path: str) -> FileKind:
    """Classify a repo-relative POSIX path."""
    p = PurePosixPath(path)
    lang = language_for(path)
    if lang == "python":
        parts = {part.lower() for part in p.parts[:-1]}
        name = p.name.lower()
        if (
            "tests" in parts
            or "test" in parts
            or name.startswith("test_")
            or name.endswith("_test.py")
            or name == "conftest.py"
        ):
            return FileKind.TEST
        return FileKind.CODE
    if lang in {"markdown", "rst", "text"}:
        return FileKind.DOC
    return FileKind.CONFIG


class SourceFile(BaseModel):
    """One file of the repository. `path` is repo-relative with forward slashes."""

    model_config = ConfigDict(frozen=True)

    path: str
    size: int
    language: str
    kind: FileKind


@dataclass(eq=False)
class Repository:
    """A filtered, read-only view of a repository on disk."""

    root: Path
    files: list[SourceFile]
    skipped: dict[str, int] = field(default_factory=dict)
    workspace: Path | None = None  # temp dir we created (ZIP/snippet); removed by cleanup()
    _text_cache: dict[str, str] = field(default_factory=dict, repr=False)

    def cleanup(self) -> None:
        """Delete the temporary workspace this repository was extracted into, if any."""
        if self.workspace is not None and self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)
            self.workspace = None

    @cached_property
    def by_path(self) -> dict[str, SourceFile]:
        return {f.path: f for f in self.files}

    @property
    def python_files(self) -> list[SourceFile]:
        return [f for f in self.files if f.language == "python"]

    @property
    def code_files(self) -> list[SourceFile]:
        return [f for f in self.files if f.kind is FileKind.CODE]

    @property
    def test_files(self) -> list[SourceFile]:
        return [f for f in self.files if f.kind is FileKind.TEST]

    @cached_property
    def repo_id(self) -> str:
        """Content hash: identical code gets the same id (stable vector-store collection name)."""
        digest = hashlib.sha256()
        for f in sorted(self.files, key=lambda x: x.path):
            digest.update(f.path.encode("utf-8"))
            digest.update(self.read_text(f.path).encode("utf-8", errors="replace"))
        return "repo_" + digest.hexdigest()[:16]

    def has(self, path: str) -> bool:
        return path in self.by_path

    def read_text(self, path: str) -> str:
        if path not in self._text_cache:
            if path not in self.by_path:
                raise KeyError(f"{path} is not part of the repository")
            raw = (self.root / path).read_bytes()
            self._text_cache[path] = raw.decode("utf-8", errors="replace")
        return self._text_cache[path]

    def lines(self, path: str) -> list[str]:
        """File lines without line endings; index 0 is line 1."""
        return self.read_text(path).splitlines()

    def line_count(self, path: str) -> int:
        return len(self.lines(path))

    def total_python_lines(self) -> int:
        return sum(self.line_count(f.path) for f in self.python_files)

    def resolve_path(self, candidate: str) -> str | None:
        """Map an LLM-cited path (backslashes, './', absolute, unique suffix) to a repo path."""
        cleaned = candidate.strip().strip("`'\"").replace("\\", "/")
        while cleaned.startswith("./"):
            cleaned = cleaned[2:]
        if cleaned in self.by_path:
            return cleaned
        root_posix = self.root.as_posix().rstrip("/") + "/"
        if cleaned.startswith(root_posix):
            rel = cleaned[len(root_posix) :]
            return rel if rel in self.by_path else None
        cleaned = cleaned.lstrip("/")
        matches = [p for p in self.by_path if p == cleaned or p.endswith("/" + cleaned)]
        if len(matches) == 1:
            return matches[0]
        return None
