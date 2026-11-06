"""Split files into review units (one LLM call each) aligned to top-level definitions."""

from __future__ import annotations

from dataclasses import dataclass, field

from marl_agents.ingestion.models import Repository
from marl_agents.parsing.python_ast import ModuleInfo, SymbolInfo

MIN_CODE_LINES = 5


@dataclass
class ReviewUnit:
    file: str
    start_line: int
    end_line: int
    symbols: list[SymbolInfo] = field(default_factory=list)
    changed: list[tuple[int, int]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.file}:{self.start_line}-{self.end_line}"

    def contains(self, start: int, end: int) -> bool:
        return self.start_line <= end and start <= self.end_line

    def is_changed(self, line: int) -> bool:
        return any(s <= line <= e for s, e in self.changed)


def _segments(module: ModuleInfo, total: int) -> list[tuple[int, int, list[SymbolInfo]]]:
    """Contiguous segments: gaps between top-level defs, and the defs themselves."""
    segs: list[tuple[int, int, list[SymbolInfo]]] = []
    cursor = 1
    for sym in module.top_level_symbols():
        if sym.start_line > cursor:
            segs.append((cursor, sym.start_line - 1, []))
        inner = [s for s in module.symbols if sym.start_line <= s.start_line <= sym.end_line]
        segs.append((sym.start_line, sym.end_line, inner))
        cursor = sym.end_line + 1
    if cursor <= total:
        segs.append((cursor, total, []))
    return segs


def _split_large(
    start: int, end: int, syms: list[SymbolInfo], max_lines: int
) -> list[tuple[int, int, list[SymbolInfo]]]:
    """Split an oversized segment (e.g. a big class) at nested definition boundaries or windows."""
    if end - start + 1 <= max_lines:
        return [(start, end, syms)]
    cuts = sorted(
        {s.start_line for s in syms if s.parent is not None and start < s.start_line <= end}
    )
    pieces: list[tuple[int, int]] = []
    piece_start = start
    for cut in cuts:
        if cut - piece_start >= max_lines // 2:
            pieces.append((piece_start, cut - 1))
            piece_start = cut
    pieces.append((piece_start, end))
    out: list[tuple[int, int, list[SymbolInfo]]] = []
    for s, e in pieces:
        while e - s + 1 > max_lines:
            out.append(
                (s, s + max_lines - 1, [x for x in syms if s <= x.start_line < s + max_lines])
            )
            s += max_lines
        out.append((s, e, [x for x in syms if s <= x.start_line <= e]))
    return out


def build_units(
    repo: Repository,
    module: ModuleInfo,
    max_lines: int = 200,
    changed: list[tuple[int, int]] | None = None,
) -> list[ReviewUnit]:
    total = repo.line_count(module.path)
    if total == 0:
        return []
    code_lines = [
        ln for ln in repo.lines(module.path) if ln.strip() and not ln.strip().startswith("#")
    ]
    if not module.syntax_error and not module.symbols and len(code_lines) < MIN_CODE_LINES:
        return []  # e.g. an __init__.py with a docstring: not worth an LLM call
    if module.syntax_error or not module.symbols:
        raw: list[tuple[int, int, list[SymbolInfo]]] = [
            (s, min(s + max_lines - 1, total), []) for s in range(1, total + 1, max_lines)
        ]
    else:
        raw = []
        for s, e, syms in _segments(module, total):
            raw.extend(_split_large(s, e, syms, max_lines))

    # Greedily merge adjacent segments up to max_lines so small files are a single unit.
    units: list[ReviewUnit] = []
    for s, e, syms in raw:
        if units and e - units[-1].start_line + 1 <= max_lines:
            units[-1].end_line = e
            units[-1].symbols.extend(syms)
        else:
            units.append(ReviewUnit(module.path, s, e, list(syms)))

    lines = repo.lines(module.path)
    units = [u for u in units if any(ln.strip() for ln in lines[u.start_line - 1 : u.end_line])]
    if changed is not None:
        for u in units:
            u.changed = [(s, e) for s, e in changed if u.contains(s, e)]
        units = [u for u in units if u.changed]
    return units


def render_numbered(repo: Repository, unit: ReviewUnit) -> str:
    """Code with a line-number gutter; changed lines (diff review) are marked with '>'."""
    lines = repo.lines(unit.file)
    width = len(str(unit.end_line))
    out = []
    for n in range(unit.start_line, unit.end_line + 1):
        marker = ">" if unit.changed and unit.is_changed(n) else " "
        out.append(f"{marker}{n:>{width}} | {lines[n - 1]}")
    return "\n".join(out)
