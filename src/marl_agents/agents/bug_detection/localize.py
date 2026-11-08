"""Fault localization: from a failing test to a ranked list of suspect functions.

1. Candidates come from reading the test, not running it: the project functions it names, what
   those call a few levels down, the rest of the files that reaches, and (configuration D) what
   retrieval finds. Traceback frames join if one is given.
2. Static signals order the candidates. That ranking is configuration A.
3. An LLM re-ranks them. Its reply is only a reordering: a reference that is not in the list is
   dropped, so it cannot point at a function that does not exist.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Iterable
from dataclasses import dataclass, field

from marl_agents.ingestion.models import FileKind
from marl_agents.parsing.python_ast import SymbolInfo, SymbolKind, parse_python
from marl_agents.parsing.repo_index import RepoIndex, SymbolRef
from marl_agents.rag.retriever import Retriever

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FRAME = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?')
_TEST_STEM = re.compile(r"^test_|_test$")
# Too common to say anything about which function a test exercises.
_GENERIC_NAMES = {
    "get", "set", "add", "run", "main", "copy", "read", "write", "close", "open", "update",
    "init", "name", "value", "values", "keys", "items", "data", "index", "test", "setup",
}  # fmt: skip
NAMED_IN_TEST = 1.0
# Score by call depth below the test: closer code is more likely, deeper code is still reachable.
HOP_SCORES = (0.4, 0.2, 0.1)
MAX_FRONTIER = 300  # functions expanded per level, so a wide test stays fast in a large project
IDENTIFIER_ONLY = 0.5
FILES_TO_EXPAND = 3  # a test reaching a file often fails in another function of that file
SAME_FILE = 0.05
TRACEBACK_FRAME = 2.0
SAME_MODULE_AS_TEST = 0.5
RETRIEVED = 0.5
SIGNAL = 0.3
MAX_SIGNAL_POINTS = 0.9


@dataclass
class Candidate:
    file: str
    symbol: SymbolInfo
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.file, self.symbol.qualname)


class _Pool:
    """Candidates by function; a function reached several ways keeps every reason."""

    def __init__(self, index: RepoIndex) -> None:
        self.index = index
        self.by_key: dict[tuple[str, str], Candidate] = {}

    def add(self, ref: SymbolRef, score: float, reason: str) -> None:
        if self.index.repo.by_path[ref.file].kind is not FileKind.CODE:
            return
        for symbol in self.functions_of(ref):
            key = (ref.file, symbol.qualname)
            item = self.by_key.setdefault(key, Candidate(ref.file, symbol))
            item.score += score
            if reason not in item.reasons:
                item.reasons.append(reason)

    def functions_of(self, ref: SymbolRef) -> list[SymbolInfo]:
        if ref.symbol.kind is not SymbolKind.CLASS:
            return [ref.symbol]
        module = self.index.modules[ref.file]
        init = f"{ref.symbol.qualname}.__init__"
        return [s for s in module.symbols if s.qualname == init]


def identifiers_in_test(test_source: str) -> tuple[set[str], set[str]]:
    """(names the test calls, every other identifier in it)."""
    code = textwrap.dedent(test_source)
    module = parse_python(code, "failing_test.py")
    called: set[str] = {c.split(".")[-1] for c in module.module_calls}
    for symbol in module.symbols:
        called |= {c.split(".")[-1] for c in symbol.calls}
    return called, set(_IDENT.findall(code)) - called


def traceback_frames(error_text: str) -> list[tuple[str, int, str | None]]:
    return [
        (m["file"].replace("\\", "/"), int(m["line"]), m["func"])
        for m in _FRAME.finditer(error_text)
    ]


def _module_stem(path: str) -> str:
    return path.rsplit("/", 1)[-1].removesuffix(".py")


def structural_candidates(
    index: RepoIndex, test_source: str, test_path: str | None = None, error_text: str | None = None
) -> dict[tuple[str, str], Candidate]:
    pool = _Pool(index)
    called, mentioned = identifiers_in_test(test_source)
    named: list[SymbolRef] = []
    for name in sorted(called):
        refs = index.by_name.get(name, [])
        if name in _GENERIC_NAMES or not refs:
            continue
        share = NAMED_IN_TEST / len(refs)  # a name defined in many places says less about each
        for ref in refs:
            pool.add(ref, share, f"called by the test: {name}")
            named.append(ref)
    for name in sorted(mentioned):
        refs = index.by_name.get(name, [])
        if name in _GENERIC_NAMES or len(name) < 4 or not refs:
            continue
        share = IDENTIFIER_ONLY / len(refs)
        for ref in refs:
            pool.add(ref, share, f"named in the test: {name}")
    _follow_calls(pool, index, named)
    if error_text:
        _add_frames(pool, index, error_text)
    stem = _TEST_STEM.sub("", _module_stem(test_path)) if test_path else None
    _add_whole_files(pool, index, stem)
    if stem:
        for item in pool.by_key.values():
            if _module_stem(item.file) == stem:
                item.score += SAME_MODULE_AS_TEST
                item.reasons.append("in the module the test file is named after")
    return pool.by_key


def _follow_calls(pool: _Pool, index: RepoIndex, named: list[SymbolRef]) -> None:
    """Walk the call graph down from what the test names, helpers in test files included."""
    frontier = named
    seen: set[tuple[str, str]] = set()
    for depth, score in enumerate(HOP_SCORES, start=1):
        following: list[SymbolRef] = []
        for ref in frontier[:MAX_FRONTIER]:
            for function in pool.functions_of(ref):
                key = (ref.file, function.qualname)
                if key in seen:
                    continue
                seen.add(key)
                for callee in index.callees(ref.file, function):
                    pool.add(callee, score, f"{depth} call(s) below the test")
                    following.append(callee)
        frontier = following


def _add_whole_files(pool: _Pool, index: RepoIndex, stem: str | None) -> None:
    totals: dict[str, float] = {}
    for item in pool.by_key.values():
        totals[item.file] = totals.get(item.file, 0.0) + item.score
    top = sorted(totals, key=lambda f: (-totals[f], f))[:FILES_TO_EXPAND]
    named_after_test = [p for p in index.modules if stem and _module_stem(p) == stem]
    for path in dict.fromkeys([*top, *named_after_test]):
        for symbol in index.modules[path].symbols:
            if symbol.kind is not SymbolKind.CLASS:
                pool.add(SymbolRef(path, symbol), SAME_FILE, "in a file the test reaches")


def _add_frames(pool: _Pool, index: RepoIndex, error_text: str) -> None:
    for file, line, _func in traceback_frames(error_text):
        path = index.repo.resolve_path(file)
        module = index.modules.get(path) if path else None
        symbol = module.symbol_at(line) if module else None
        if path and symbol and symbol.kind is not SymbolKind.CLASS:
            pool.add(SymbolRef(path, symbol), TRACEBACK_FRAME, f"in the traceback at line {line}")


def add_retrieved(
    pool: dict[tuple[str, str], Candidate],
    index: RepoIndex,
    retriever: Retriever,
    test_source: str,
    k: int,
) -> int:
    """Add retrieved functions (similarity to the test). Returns how many were new."""
    added = 0
    for hit in retriever.retrieve(test_source[:3000], k=k * 4):
        chunk = hit.chunk
        module = index.modules.get(chunk.file)
        if module is None or index.repo.by_path[chunk.file].kind is not FileKind.CODE:
            continue
        symbol = next((s for s in module.symbols if s.qualname == chunk.symbol), None)
        if symbol is None or symbol.kind is SymbolKind.CLASS:
            continue
        key = (chunk.file, symbol.qualname)
        if key not in pool:
            pool[key] = Candidate(chunk.file, symbol)
            added += 1
        pool[key].score += RETRIEVED * max(hit.score, 0.0)
        pool[key].reasons.append("similar to the test (retrieval)")
        if added >= k:
            break
    return added


def apply_signals(
    candidates: Iterable[Candidate], rule_lines: dict[str, list[tuple[int, str]]]
) -> None:
    """Static rules that fired inside a candidate raise it, and are shown to the LLM."""
    for item in candidates:
        hits = [
            rule
            for line, rule in rule_lines.get(item.file, [])
            if item.symbol.start_line <= line <= item.symbol.end_line
        ]
        if hits:
            item.signals = sorted(set(hits))
            item.score += min(SIGNAL * len(hits), MAX_SIGNAL_POINTS)


def ranked(pool: dict[tuple[str, str], Candidate]) -> list[Candidate]:
    return sorted(pool.values(), key=lambda c: (-c.score, c.file, c.symbol.start_line))


def render_candidates(
    index: RepoIndex,
    candidates: list[Candidate],
    max_lines: int,
    max_chars: int,
    show_signals: bool,
) -> tuple[str, dict[str, Candidate]]:
    """Prompt text and the references it used. Candidates that do not fit are left out."""
    parts: list[str] = []
    refs: dict[str, Candidate] = {}
    used = 0
    for n, item in enumerate(candidates, start=1):
        ref = f"F{n}"
        lines = index.repo.lines(item.file)
        start, end = item.symbol.start_line, item.symbol.end_line
        shown = lines[start - 1 : min(end, start + max_lines - 1)]
        cut = " (truncated)" if end - start + 1 > max_lines else ""
        hints = (
            f"\nstatic hints: {', '.join(item.signals)}" if show_signals and item.signals else ""
        )
        body = "\n".join(shown)
        text = (
            f"### {ref} {item.file}::{item.symbol.qualname} lines {start}-{end}{cut}{hints}\n"
            f"```python\n{body}\n```"
        )
        if used + len(text) > max_chars:
            break
        parts.append(text)
        refs[ref] = item
        used += len(text)
    return "\n\n".join(parts), refs
