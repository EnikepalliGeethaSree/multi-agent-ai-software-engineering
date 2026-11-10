"""Bug Detection Agent (approved deck, Fig. 3).

    code -> AST / CFG -> context -> LLM -> bug findings with trigger and root cause -> report

Two jobs:
- `run(request)` finds defects in a repository, a snippet, a change, or chosen line ranges.
- `localize(...)` ranks functions by how likely they are to contain a known failure. `run` does this
  too when `options["failing_test"]` is given, and stores it in `artifacts["localization"]`.

It is a specialized Code Review Agent: ingestion, quota handling, validation, deduplication, the
severity rubric, reports and suggested fixes are shared. What differs is the prompts, the analyzers,
the extra claim checks and the budget on what the LLM reads. It never runs the code it analyzes.
"""

from __future__ import annotations

from typing import Any

from marl_agents.agents.bug_detection import localize as loc
from marl_agents.agents.bug_detection.checks import claim_problem, static_detail
from marl_agents.agents.bug_detection.llm_schema import LLMLocalization, parse_bug_items
from marl_agents.agents.bug_detection.prompts import load_prompt, prompt_versions
from marl_agents.agents.bug_detection.selection import select_units
from marl_agents.agents.code_review.agent import CodeReviewAgent, Scope
from marl_agents.agents.code_review.llm_schema import (
    LLMFinding,
    LLMReviewEnvelope,
    StaticAssessment,
)
from marl_agents.agents.code_review.units import ReviewUnit
from marl_agents.agents.prompting import PromptTemplate
from marl_agents.core.schemas import (
    AgentRequest,
    Category,
    Finding,
    LocalizationResult,
    ReviewResult,
    SuspectFunction,
)
from marl_agents.ingestion import Repository
from marl_agents.llm.base import LLMError, Message, QuotaExhaustedError, Usage
from marl_agents.parsing.python_ast import SymbolKind, parse_python
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.static_analysis import StaticAnalyzer, bug_analyzers

DEFECT_CATEGORIES = {Category.BUG, Category.ERROR_HANDLING, Category.EDGE_CASE, Category.SECURITY}
MAX_SUSPECTS = 20


class BugDetectionAgent(CodeReviewAgent):
    name = "bug_detection"
    id_prefix = "BD"
    GUIDELINE_FILES = frozenset(
        {"bug_patterns.md", "error_handling_testing.md", "security_owasp_cwe.md"}
    )

    # ---- what differs from code review ---------------------------------------------------------

    def _default_analyzers(self) -> list[StaticAnalyzer]:
        return bug_analyzers()

    def _load_prompt(self, name: str) -> PromptTemplate:
        return load_prompt(name)

    def _prompt_versions(self) -> dict[str, str]:
        return prompt_versions()

    def _parse_reply(
        self, envelope: LLMReviewEnvelope
    ) -> tuple[list[LLMFinding], list[StaticAssessment], list[str]]:
        return parse_bug_items(envelope)

    def _filter_static(self, static: list[Finding]) -> list[Finding]:
        return [f for f in static if f.category in DEFECT_CATEGORIES]

    def _scope(self, request: AgentRequest, repo: Repository) -> Scope | None:
        """`function_scope` limits the agent like `changed_lines`, but marks nothing in the prompt.

        An evaluation that shows a function must not point at the lines that were fixed.
        """
        raw = request.options.get("function_scope")
        if not raw:
            return super()._scope(request, repo)
        scope: Scope = {}
        for path, ranges in raw.items():
            resolved = repo.resolve_path(path)
            if resolved is not None:
                scope[resolved] = [(int(s), int(e)) for s, e in ranges]
        return scope

    def _build_units(
        self,
        repo: Repository,
        index: RepoIndex,
        targets: list[str],
        scope: Scope | None,
        request: AgentRequest,
    ) -> list[ReviewUnit]:
        if not request.options.get("function_scope") or scope is None:
            return super()._build_units(repo, index, targets, scope, request)
        units: list[ReviewUnit] = []
        for file in targets:
            for start, end in scope.get(file, []):
                symbols = [s for s in index.modules[file].symbols if start <= s.start_line <= end]
                units.append(ReviewUnit(file, start, end, symbols))
        return units

    def _select_units(
        self,
        units: list[ReviewUnit],
        repo: Repository,
        static: list[Finding],
        stats: dict[str, Any],
        errors: list[str],
    ) -> list[ReviewUnit]:
        budget = self.settings.bugs.max_units
        selected, coverage = select_units(units, repo, static, budget)
        stats["scan_coverage"] = coverage.model_dump()
        if not coverage.complete:
            errors.append(
                f"Scan budget: the LLM read {coverage.units_selected} of {coverage.units_total} "
                f"parts ({coverage.lines_selected} of {coverage.lines_total} lines), the riskiest "
                "first. The rest have static-analysis findings only."
            )
        return selected

    def _check_claims(
        self, findings: list[Finding], repo: Repository, unit: ReviewUnit
    ) -> tuple[list[Finding], list[str]]:
        code = "\n".join(repo.lines(unit.file)[unit.start_line - 1 : unit.end_line])
        kept: list[Finding] = []
        reasons: list[str] = []
        for finding in findings:
            problem = claim_problem(finding, code, self.settings.bugs.require_trigger)
            if problem is None:
                kept.append(finding)
            else:
                reasons.append(problem)
        return kept, reasons

    def _finish_findings(self, findings: list[Finding], repo: Repository) -> list[Finding]:
        return [
            f if f.bug is not None else f.model_copy(update={"bug": static_detail(f)})
            for f in findings
        ]

    # ---- entry point ---------------------------------------------------------------------------

    def run(self, request: AgentRequest) -> ReviewResult:
        failing_test = request.options.get("failing_test")
        if not failing_test:
            return super().run(request)
        keep = bool(request.options.get("keep_workspace"))
        repo = self.load(request, self.settings)
        try:
            index = RepoIndex.build(repo)
            test_source, test_path = resolve_test(index, str(failing_test))
            found = self.localize(
                repo, index, test_source, test_path, request.options.get("error_text")
            )
            result = super().review_repository(
                repo, index, self._after_localization(request, found)
            )
            result.artifacts["localization"] = found.model_dump()
            return result
        finally:
            if not keep:
                repo.cleanup()

    def _after_localization(self, request: AgentRequest, found: LocalizationResult) -> AgentRequest:
        """With a known failure, the LLM reads the top suspects instead of the riskiest code."""
        top = found.suspects[: self.settings.bugs.max_units]
        ranges: dict[str, list[tuple[int, int]]] = {}
        for s in top:
            ranges.setdefault(s.file, []).append((s.start_line, s.end_line))
        return request.model_copy(update={"options": {**request.options, "function_scope": ranges}})

    # ---- localization --------------------------------------------------------------------------

    def _static_rule_lines(
        self, repo: Repository, index: RepoIndex, files: list[str]
    ) -> dict[str, list[tuple[int, str]]]:
        rule_lines: dict[str, list[tuple[int, str]]] = {}
        for analyzer in self.analyzers:
            for f in self._filter_static(analyzer.analyze(repo, index, files).findings):
                if f.rule_id:
                    rule_lines.setdefault(f.file, []).append((f.start_line, f.rule_id))
        return rule_lines

    def localize(
        self,
        repo: Repository,
        index: RepoIndex,
        test_source: str,
        test_path: str | None = None,
        error_text: str | None = None,
        run_usage: Usage | None = None,
        limit: int = MAX_SUSPECTS,
    ) -> LocalizationResult:
        """Rank functions for a failing test. Raises QuotaExhaustedError so a run can stop."""
        cfg = self.settings.bugs
        mode = self.settings.review.mode
        pool = loc.structural_candidates(index, test_source, test_path, error_text)
        retriever = self._make_retriever() if mode != "static_only" else None
        if retriever is not None:
            retriever.index_repository(index)
            loc.add_retrieved(pool, index, retriever, test_source, cfg.retrieval_k)
        use_static = mode != "llm_only"
        if use_static:
            files = sorted({c.file for c in pool.values()})
            loc.apply_signals(pool.values(), self._static_rule_lines(repo, index, files))
        ordered = loc.ranked(pool)
        result = LocalizationResult(candidates_considered=len(ordered))
        if mode != "static_only" and ordered:
            ordered = self._llm_rank(index, ordered, test_source, error_text, result, run_usage)
        result.suspects = [_suspect(i, c) for i, c in enumerate(ordered[:limit], start=1)]
        return result

    def _llm_rank(
        self,
        index: RepoIndex,
        ordered: list[loc.Candidate],
        test_source: str,
        error_text: str | None,
        result: LocalizationResult,
        run_usage: Usage | None,
    ) -> list[loc.Candidate]:
        assert self.llm is not None
        cfg = self.settings.bugs
        show_signals = self.settings.review.mode == "full"
        text, refs = loc.render_candidates(
            index, ordered[: cfg.max_candidates], cfg.candidate_lines, cfg.max_prompt_chars,
            show_signals,
        )  # fmt: skip
        result.candidates_shown = len(refs)
        prompt = load_prompt("localize").render(
            failing_test=test_source,
            error_section=f"## Error output\n```text\n{error_text}\n```" if error_text else "",
            hints_note=" Static hints may be false alarms." if show_signals else "",
            candidates=text,
        )
        messages = [
            Message(role="system", content=load_prompt("system").text),
            Message(role="user", content=prompt),
        ]
        try:
            reply = self.llm.generate_structured(
                messages,
                LLMLocalization,
                config=self._llm_config(),
                usage=run_usage,
                label="localize",
            )
        except QuotaExhaustedError:
            raise
        except LLMError as exc:
            result.llm_failed = True
            result.errors.append(f"LLM ranking failed: {exc}")
            return ordered
        chosen: list[loc.Candidate] = []
        for item in reply.ranking:
            candidate = refs.get(item.ref)
            if candidate is None:
                result.errors.append(f"unknown reference dropped: {item.ref[:20]}")
                continue
            if candidate not in chosen:
                chosen.append(candidate)
                if item.reason:
                    candidate.reasons.insert(0, f"LLM: {item.reason}")
        if not chosen:
            result.llm_failed = True
            result.errors.append("LLM ranking failed: the reply ranked no listed candidate")
            return ordered
        result.hypothesis = reply.hypothesis or None
        result.ranked_by = "llm"
        return [*chosen, *(c for c in ordered if c not in chosen)]


def _suspect(rank: int, c: loc.Candidate) -> SuspectFunction:
    return SuspectFunction(
        rank=rank,
        file=c.file,
        symbol=c.symbol.qualname,
        start_line=c.symbol.start_line,
        end_line=c.symbol.end_line,
        score=round(c.score, 3),
        reasons=c.reasons[:4],
        signals=c.signals,
    )


class FailingTestError(ValueError):
    """The failing test named by the user is not in the repository."""


def resolve_test(index: RepoIndex, spec: str) -> tuple[str, str | None]:
    """`tests/test_x.py::TestA::test_b` -> (its source, its path). Other text is the test itself."""
    path, _, name = spec.partition("::")
    resolved = index.repo.resolve_path(path) if path.endswith(".py") else None
    if resolved is None:
        if path.endswith(".py") and "\n" not in spec:
            raise FailingTestError(f"{path} is not in this repository")
        return spec, None
    if not name:
        return index.repo.read_text(resolved), resolved
    wanted = name.split("::")[-1].split("[")[0]
    source = index.repo.read_text(resolved)
    module = index.modules.get(resolved) or parse_python(source, resolved)
    lines = index.repo.lines(resolved)
    for symbol in module.symbols:
        if symbol.name == wanted and symbol.kind is not SymbolKind.CLASS:
            return "\n".join(lines[symbol.start_line - 1 : symbol.end_line]), resolved
    raise FailingTestError(f"{wanted} is not defined in {resolved}")
