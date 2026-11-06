"""Repository-wide structural index: symbol table, call graph and test references.

This is what makes context *structural* (callees, callers, tests of a function) rather than purely
embedding-based.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from marl_agents.core.timing import CALL_GRAPH, PARSING, RunTimer
from marl_agents.ingestion.models import FileKind, Repository
from marl_agents.parsing.python_ast import ModuleInfo, SymbolInfo, SymbolKind, parse_python

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def module_name_for(path: str) -> str:
    """'pkg/sub/mod.py' -> 'pkg.sub.mod'; 'pkg/__init__.py' -> 'pkg'. Strips a leading 'src/'."""
    p = PurePosixPath(path)
    parts = list(p.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


@dataclass(frozen=True)
class SymbolRef:
    file: str
    symbol: SymbolInfo


@dataclass
class RepoIndex:
    repo: Repository
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    by_name: dict[str, list[SymbolRef]] = field(default_factory=lambda: defaultdict(list))
    module_to_file: dict[str, str] = field(default_factory=dict)
    test_identifiers: dict[str, set[str]] = field(default_factory=dict)
    _reverse_calls: dict[tuple[str, str], list[SymbolRef]] | None = field(default=None, repr=False)

    @classmethod
    def build(cls, repo: Repository, timer: RunTimer | None = None) -> RepoIndex:
        """Parse every module, then build the symbol and call-graph tables (timed separately)."""
        index = cls(repo=repo)
        start = time.perf_counter()
        parsed = [(f, parse_python(repo.read_text(f.path), f.path)) for f in repo.python_files]
        mid = time.perf_counter()
        for f, info in parsed:
            index.modules[f.path] = info
            index.module_to_file[module_name_for(f.path)] = f.path
            for sym in info.symbols:
                index.by_name[sym.name].append(SymbolRef(f.path, sym))
            if f.kind is FileKind.TEST:
                index.test_identifiers[f.path] = set(_IDENT.findall(repo.read_text(f.path)))
        if timer is not None:
            timer.record("parse_python", PARSING, start, mid)
            timer.record("symbol_tables", CALL_GRAPH, mid, time.perf_counter())
        logger.info(
            "Indexed %d python modules, %d symbols",
            len(index.modules),
            sum(len(m.symbols) for m in index.modules.values()),
        )
        return index

    # ---- lookups -------------------------------------------------------------------------

    def resolve_call(self, file: str, call: str) -> list[SymbolRef]:
        """Best-effort resolution of a called name to repo-defined symbols."""
        info = self.modules.get(file)
        last = call.split(".")[-1]
        candidates = [
            ref for ref in self.by_name.get(last, []) if ref.symbol.kind is not SymbolKind.CLASS
        ] or list(self.by_name.get(last, []))
        if not candidates:
            return []
        if info is not None:
            # Prefer symbols in the same file, then symbols from modules this file imports.
            same_file = [c for c in candidates if c.file == file]
            if same_file:
                return same_file
            imported_files = self.imported_files(file)
            from_imports = [c for c in candidates if c.file in imported_files]
            if from_imports:
                return from_imports
        return candidates if len(candidates) <= 3 else []

    def imported_files(self, file: str) -> set[str]:
        info = self.modules.get(file)
        if info is None:
            return set()
        own_pkg = module_name_for(file).rsplit(".", 1)[0] if "." in module_name_for(file) else ""
        found: set[str] = set()
        for imp in info.imports:
            targets: list[str] = []
            if imp.is_from:
                base = imp.module or ""
                if imp.level:
                    pkg_parts = own_pkg.split(".") if own_pkg else []
                    keep = len(pkg_parts) - (imp.level - 1)
                    prefix = ".".join(pkg_parts[: max(keep, 0)])
                    base = ".".join(x for x in (prefix, base) if x)
                targets.append(base)
                targets.extend(f"{base}.{n}" if base else n for n in imp.names)
            else:
                targets.extend(imp.names)
            for t in targets:
                if t in self.module_to_file:
                    found.add(self.module_to_file[t])
        found.discard(file)
        return found

    def callees(self, file: str, symbol: SymbolInfo) -> list[SymbolRef]:
        seen: set[tuple[str, str]] = set()
        result: list[SymbolRef] = []
        for call in symbol.calls:
            for ref in self.resolve_call(file, call):
                key = (ref.file, ref.symbol.qualname)
                if key not in seen and not (ref.file == file and ref.symbol == symbol):
                    seen.add(key)
                    result.append(ref)
        return result

    def callers(self, file: str, symbol: SymbolInfo) -> list[SymbolRef]:
        if self._reverse_calls is None:
            reverse: dict[tuple[str, str], list[SymbolRef]] = defaultdict(list)
            for mod_file, info in self.modules.items():
                for sym in info.symbols:
                    for ref in self.callees(mod_file, sym):
                        reverse[(ref.file, ref.symbol.qualname)].append(SymbolRef(mod_file, sym))
            self._reverse_calls = reverse
        return list(self._reverse_calls.get((file, symbol.qualname), []))

    def tests_referencing(self, name: str) -> list[str]:
        return sorted(f for f, idents in self.test_identifiers.items() if name in idents)

    def has_tests(self) -> bool:
        return bool(self.test_identifiers)
