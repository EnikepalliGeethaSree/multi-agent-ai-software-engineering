"""Code-aware chunking: one chunk per function/method/class (from the AST), docs by heading."""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum

from pydantic import BaseModel

from marl_agents.ingestion.models import FileKind, Repository
from marl_agents.parsing.python_ast import ModuleInfo, SymbolKind
from marl_agents.parsing.repo_index import RepoIndex

MAX_CHUNK_LINES = 120
WINDOW_OVERLAP = 10
DOC_MAX_LINES = 60


class SourceType(StrEnum):
    CODE = "code"
    TEST = "test"
    DOC = "doc"
    CONFIG = "config"
    GUIDELINE = "guideline"


class Chunk(BaseModel):
    id: str
    repo_id: str
    file: str
    symbol: str | None = None
    kind: str
    start_line: int
    end_line: int
    language: str
    source_type: SourceType
    text: str

    def metadata(self) -> dict[str, str | int]:
        return {
            "repo_id": self.repo_id,
            "file": self.file,
            "symbol": self.symbol or "",
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "language": self.language,
            "source_type": str(self.source_type),
        }

    def header(self) -> str:
        where = f"{self.file}:{self.start_line}-{self.end_line}"
        return f"{where} ({self.kind}{' ' + self.symbol if self.symbol else ''})"


def _chunk_id(repo_id: str, file: str, start: int, end: int, symbol: str | None) -> str:
    raw = f"{repo_id}|{file}|{start}|{end}|{symbol or ''}"
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]


def _windows(start: int, end: int, size: int, overlap: int) -> list[tuple[int, int]]:
    if end - start + 1 <= size:
        return [(start, end)]
    out: list[tuple[int, int]] = []
    s = start
    while s <= end:
        e = min(end, s + size - 1)
        out.append((s, e))
        if e == end:
            break
        s = e - overlap + 1
    return out


def _source_type(kind: FileKind) -> SourceType:
    return {
        FileKind.CODE: SourceType.CODE,
        FileKind.TEST: SourceType.TEST,
        FileKind.DOC: SourceType.DOC,
        FileKind.CONFIG: SourceType.CONFIG,
    }[kind]


def chunk_python(repo: Repository, module: ModuleInfo, repo_id: str) -> list[Chunk]:
    lines = repo.lines(module.path)
    src_type = _source_type(repo.by_path[module.path].kind)
    chunks: list[Chunk] = []

    def add(start: int, end: int, kind: str, symbol: str | None, prefix: str = "") -> None:
        for s, e in _windows(start, end, MAX_CHUNK_LINES, WINDOW_OVERLAP):
            text = prefix + "\n".join(lines[s - 1 : e])
            if not text.strip():
                continue
            chunks.append(
                Chunk(
                    id=_chunk_id(repo_id, module.path, s, e, symbol),
                    repo_id=repo_id,
                    file=module.path,
                    symbol=symbol,
                    kind=kind,
                    start_line=s,
                    end_line=e,
                    language="python",
                    source_type=src_type,
                    text=text,
                )
            )

    if module.syntax_error:
        add(1, max(len(lines), 1), "module", None)
        return chunks

    top_level = module.top_level_symbols()
    # Module-level chunk: everything outside top-level defs (imports, constants, main block).
    covered = {ln for s in top_level for ln in range(s.start_line, s.end_line + 1)}
    outside = [i for i in range(1, len(lines) + 1) if i not in covered and lines[i - 1].strip()]
    if outside:
        body = "\n".join(lines[i - 1] for i in outside)
        if body.strip():
            chunks.append(
                Chunk(
                    id=_chunk_id(repo_id, module.path, 0, 0, "<module>"),
                    repo_id=repo_id,
                    file=module.path,
                    symbol="<module>",
                    kind="module",
                    start_line=outside[0],
                    end_line=outside[-1],
                    language="python",
                    source_type=src_type,
                    text=body[: 200 * 80],
                )
            )

    for sym in module.symbols:
        if sym.kind is SymbolKind.CLASS:
            methods = [s for s in module.symbols if s.parent == sym.qualname]
            if sym.line_span <= MAX_CHUNK_LINES or not methods:
                add(sym.start_line, sym.end_line, "class", sym.qualname)
            else:
                # Large class: header + attributes, methods get their own chunks.
                header_end = min(m.start_line for m in methods) - 1
                add(sym.start_line, max(sym.start_line, header_end), "class", sym.qualname)
        elif sym.parent is None or sym.kind is SymbolKind.METHOD:
            parent_class = next(
                (
                    s
                    for s in module.symbols
                    if s.qualname == sym.parent and s.kind is SymbolKind.CLASS
                ),
                None,
            )
            if parent_class is not None and parent_class.line_span <= MAX_CHUNK_LINES:
                continue  # already inside its class chunk
            prefix = f"# in class {sym.parent}\n" if sym.parent else ""
            add(sym.start_line, sym.end_line, str(sym.kind), sym.qualname, prefix)
    return chunks


_HEADING = re.compile(r"^(#{1,6}\s|\S.*\n[=-]{3,}$)")


def chunk_text(repo: Repository, path: str, repo_id: str) -> list[Chunk]:
    """Markdown/RST split at headings; other text/config files in fixed windows."""
    lines = repo.lines(path)
    if not lines:
        return []
    f = repo.by_path[path]
    sections: list[tuple[int, int]] = []
    if f.language in {"markdown", "rst"}:
        starts = [1] + [i + 1 for i, ln in enumerate(lines) if i > 0 and ln.startswith("#")]
        starts = sorted(set(starts))
        for i, s in enumerate(starts):
            e = (starts[i + 1] - 1) if i + 1 < len(starts) else len(lines)
            sections.extend(_windows(s, e, DOC_MAX_LINES, 5))
    else:
        sections = _windows(1, len(lines), DOC_MAX_LINES, 5)

    chunks = []
    for s, e in sections:
        text = "\n".join(lines[s - 1 : e])
        if not text.strip():
            continue
        title = next(
            (ln.lstrip("# ").strip() for ln in lines[s - 1 : e] if ln.startswith("#")), None
        )
        chunks.append(
            Chunk(
                id=_chunk_id(repo_id, path, s, e, title),
                repo_id=repo_id,
                file=path,
                symbol=title,
                kind="section" if f.language in {"markdown", "rst"} else "text",
                start_line=s,
                end_line=e,
                language=f.language,
                source_type=_source_type(f.kind),
                text=text,
            )
        )
    return chunks


def chunk_repository(index: RepoIndex) -> list[Chunk]:
    repo = index.repo
    repo_id = repo.repo_id
    chunks: list[Chunk] = []
    for f in repo.files:
        if f.language == "python":
            module = index.modules.get(f.path)
            if module is not None:
                chunks.extend(chunk_python(repo, module, repo_id))
        else:
            chunks.extend(chunk_text(repo, f.path, repo_id))
    return chunks
