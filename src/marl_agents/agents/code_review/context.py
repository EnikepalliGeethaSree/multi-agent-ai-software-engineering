"""Assemble project context for a review unit.

Three sources, in priority order under a character budget:
1. structural (AST call graph): callees defined elsewhere, tests that reference the unit's symbols,
   callers - precise, cheap, and explainable;
2. dense retrieval: semantically similar chunks from the vector store;
3. guidelines: coding-standard / OWASP / error-handling guidance relevant to the code.
"""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass

from marl_agents.agents.code_review.units import ReviewUnit
from marl_agents.core.timing import PROMPT, RAG_RETRIEVAL, RunTimer
from marl_agents.ingestion.models import FileKind
from marl_agents.parsing.python_ast import SymbolKind
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.rag.retriever import Retriever

logger = logging.getLogger(__name__)

MAX_ITEM_LINES = 60
README_LINES = 40


@dataclass
class ContextItem:
    reason: str  # callee | caller | test | similar | guideline | readme
    file: str
    start_line: int
    end_line: int
    label: str
    text: str
    score: float | None = None

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.file, self.start_line, self.end_line)

    def where(self) -> str:
        if self.reason == "guideline":
            return self.file
        return f"{self.file}:{self.start_line}-{self.end_line}"

    def render(self, ref: str = "") -> str:
        lang = "python" if self.file.endswith(".py") else ""
        head = f"{ref} " if ref else ""
        return (
            f"### {head}[{self.reason}] {self.label} ({self.where()})\n```{lang}\n{self.text}\n```"
        )

    def citation(self) -> str:
        """How a cited item is recorded on a finding: what it was and where it came from."""
        return f"{self.reason}: {self.label} ({self.where()})"


class ContextBuilder:
    def __init__(
        self,
        index: RepoIndex,
        retriever: Retriever | None = None,
        structural: bool = True,
        top_k: int = 6,
        guideline_k: int = 2,
        guideline_files: frozenset[str] | None = None,
        max_chars: int = 12_000,
        timer: RunTimer | None = None,
    ) -> None:
        self.index = index
        self.retriever = retriever
        self.structural = structural
        self.top_k = top_k
        self.guideline_k = guideline_k
        self.guideline_files = guideline_files
        # Retrieval that failed (e.g. a vector-store error). The review continues without it.
        self.errors: list[str] = []
        self.max_chars = max_chars
        self.timer = timer

    def _timed(self, name: str) -> AbstractContextManager[None]:
        """RAG retrieval span (query embedding + vector search) when a run timer is attached."""
        return self.timer.span(name, RAG_RETRIEVAL) if self.timer is not None else nullcontext()

    def _prompt_stage(self, name: str) -> AbstractContextManager[None]:
        return self.timer.span(name, PROMPT) if self.timer is not None else nullcontext()

    # ---- sources ------------------------------------------------------------------------------

    def _excerpt(self, file: str, start: int, end: int) -> str:
        lines = self.index.repo.lines(file)
        end = min(end, start + MAX_ITEM_LINES - 1, len(lines))
        return "\n".join(lines[start - 1 : end])

    def structural_items(self, unit: ReviewUnit) -> list[ContextItem]:
        items: list[ContextItem] = []
        funcs = [s for s in unit.symbols if s.kind is not SymbolKind.CLASS] or unit.symbols
        for sym in funcs:
            for ref in self.index.callees(unit.file, sym):
                s = ref.symbol
                if ref.file == unit.file and unit.contains(s.start_line, s.end_line):
                    continue
                items.append(
                    ContextItem(
                        "callee",
                        ref.file,
                        s.start_line,
                        min(s.end_line, s.start_line + MAX_ITEM_LINES - 1),
                        f"called by {sym.name}: {s.qualname}",
                        self._excerpt(ref.file, s.start_line, s.end_line),
                    )
                )
        for sym in funcs:
            for test_file in self.index.tests_referencing(sym.name)[:2]:
                module = self.index.modules.get(test_file)
                tests = [
                    t
                    for t in (module.symbols if module else [])
                    if t.kind is not SymbolKind.CLASS
                    and any(c.split(".")[-1] == sym.name for c in t.calls)
                ]
                for t in tests[:2]:
                    items.append(
                        ContextItem(
                            "test",
                            test_file,
                            t.start_line,
                            t.end_line,
                            f"test of {sym.name}: {t.qualname}",
                            self._excerpt(test_file, t.start_line, t.end_line),
                        )
                    )
        for sym in funcs[:4]:
            for ref in self.index.callers(unit.file, sym)[:2]:
                s = ref.symbol
                if ref.file == unit.file and unit.contains(s.start_line, s.end_line):
                    continue
                items.append(
                    ContextItem(
                        "caller",
                        ref.file,
                        s.start_line,
                        s.end_line,
                        f"calls {sym.name}: {s.qualname}",
                        self._excerpt(ref.file, s.start_line, s.end_line),
                    )
                )
        return items

    def readme_item(self) -> ContextItem | None:
        repo = self.index.repo
        readmes = [
            f
            for f in repo.files
            if f.kind is FileKind.DOC and f.path.lower().split("/")[-1].startswith("readme")
        ]
        if not readmes:
            return None
        top = min(readmes, key=lambda f: f.path.count("/"))
        n = min(README_LINES, repo.line_count(top.path))
        if n == 0:
            return None
        return ContextItem(
            "readme", top.path, 1, n, "project README", self._excerpt(top.path, 1, n)
        )

    def similar_items(self, unit: ReviewUnit, code: str) -> list[ContextItem]:
        if self.retriever is None:
            return []
        names = " ".join(s.name for s in unit.symbols)
        query = f"{unit.file} {names}\n{code[:3000]}"
        with self._timed("similar_code"):
            try:
                hits = self.retriever.retrieve(
                    query,
                    k=self.top_k,
                    exclude_ranges={unit.file: (unit.start_line, unit.end_line)},
                )
            except Exception as exc:  # any store failure: review without similar code
                self._retrieval_failed("similar code", exc)
                return []
        return [
            ContextItem(
                "similar",
                h.chunk.file,
                h.chunk.start_line,
                h.chunk.end_line,
                h.chunk.symbol or h.chunk.kind,
                h.chunk.text[:4000],
                h.score,
            )
            for h in hits
        ]

    def _retrieval_failed(self, what: str, exc: Exception) -> None:
        message = f"retrieval of {what} failed ({type(exc).__name__}); reviewed without it"
        logger.warning(message)
        self.errors.append(message)

    def guideline_items(self, code: str, hints: list[str]) -> list[ContextItem]:
        if self.retriever is None or self.guideline_k <= 0:
            return []
        query = "\n".join(hints) + "\n" + code[:2000]
        with self._timed("guidelines"):
            try:
                hits = self.retriever.retrieve_guidelines(
                    query, k=self.guideline_k, files=self.guideline_files
                )
            except Exception as exc:  # any store failure: review without guidance
                self._retrieval_failed("guidelines", exc)
                return []
        return [
            ContextItem(
                "guideline",
                h.chunk.file,
                h.chunk.start_line,
                h.chunk.end_line,
                h.chunk.symbol or "guideline",
                h.chunk.text,
                h.score,
            )
            for h in hits
        ]

    # ---- assembly -----------------------------------------------------------------------------

    def build(
        self, unit: ReviewUnit, code: str, hints: list[str] | None = None
    ) -> list[ContextItem]:
        candidates: list[ContextItem] = []
        with self._prompt_stage("structural_context"):
            if self.structural:
                candidates.extend(self.structural_items(unit))
            readme = self.readme_item() if (self.structural or self.retriever) else None
            if readme:
                candidates.append(readme)
        candidates.extend(self.similar_items(unit, code))
        candidates.extend(self.guideline_items(code, hints or []))

        with self._prompt_stage("context_selection"):
            return self._select(candidates)

    def _select(self, candidates: list[ContextItem]) -> list[ContextItem]:
        chosen: list[ContextItem] = []
        seen: set[tuple[str, int, int]] = set()
        budget = self.max_chars
        for item in candidates:
            if item.key in seen:
                continue
            # Skip items fully contained in an already chosen one from the same file.
            if any(
                c.file == item.file
                and c.start_line <= item.start_line
                and item.end_line <= c.end_line
                for c in chosen
            ):
                continue
            size = len(item.text) + 100
            if size > budget:
                continue
            seen.add(item.key)
            chosen.append(item)
            budget -= size
        return chosen


def context_ref(i: int) -> str:
    """The id an item is shown under, and must be cited by: C1, C2, ..."""
    return f"C{i + 1}"


def render_context(items: list[ContextItem]) -> str:
    if not items:
        return "## Project context\n(none provided)"
    return (
        "## Project context (for understanding only - do not review)\n"
        "Each item has an id (C1, C2, ...). If an item supports a finding, list its id in "
        "`context_refs`.\n\n" + "\n\n".join(i.render(context_ref(n)) for n, i in enumerate(items))
    )
