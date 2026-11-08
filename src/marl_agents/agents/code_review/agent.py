"""Code Review Agent: ingestion -> AST -> static analysis -> RAG context -> LLM review ->
validation -> dedup -> severity rubric -> confidence -> ranked, evidenced findings.

Standalone and LangGraph-free: `CodeReviewAgent(llm=...).run(AgentRequest(...))`.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marl_agents.agents.base import BaseAgent
from marl_agents.agents.code_review.context import ContextBuilder, ContextItem, render_context
from marl_agents.agents.code_review.fixes import FixGenerator
from marl_agents.agents.code_review.llm_schema import (
    LLMFinding,
    LLMReviewEnvelope,
    StaticAssessment,
    parse_items,
)
from marl_agents.agents.code_review.prompts import PromptTemplate, load_prompt, prompt_versions
from marl_agents.agents.code_review.scheduling import UnitCache, UnitPlan, plan_units
from marl_agents.agents.code_review.units import ReviewUnit, build_units, render_numbered
from marl_agents.config import PROJECT_ROOT, Settings, load_settings
from marl_agents.core.schemas import AgentRequest, Finding, ReviewResult, RunMetadata, Severity
from marl_agents.core.timing import (
    CLASSIFIER,
    INGESTION,
    LLM,
    OTHER,
    PROMPT,
    RAG_INDEX,
    STATIC,
    VALIDATION,
    RunTimer,
    TimingBreakdown,
)
from marl_agents.findings import (
    FindingValidator,
    apply_rubric,
    calibrate,
    deduplicate,
    passes_threshold,
    rank_and_number,
    validate_all,
)
from marl_agents.findings.actionability import filter_actionable
from marl_agents.findings.redaction import is_secret_finding, redact_finding
from marl_agents.ingestion import Repository, load_files, load_repository, load_snippet
from marl_agents.ingestion.models import FileKind
from marl_agents.llm.base import (
    LLMError,
    LLMProvider,
    Message,
    QuotaExhaustedError,
    RequestTooLargeError,
    Usage,
)
from marl_agents.llm.classifier import ChangeClassifier
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.rag.embeddings import create_embedder
from marl_agents.rag.retriever import Retriever
from marl_agents.rag.store import create_store
from marl_agents.static_analysis import StaticAnalyzer, default_analyzers
from marl_agents.static_analysis.cache import AnalysisCache
from marl_agents.static_analysis.type_check import TypeCheckAnalyzer, mypy_available

logger = logging.getLogger(__name__)

Scope = dict[str, list[tuple[int, int]]]


@dataclass
class UnitOutcome:
    unit: ReviewUnit
    findings: list[Finding] = field(default_factory=list)
    assessments: list[StaticAssessment] = field(default_factory=list)
    static_refs: dict[str, int] = field(default_factory=dict)  # "S1" -> index into static list
    context: list[ContextItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failed: bool = False
    from_cache: bool = False
    not_attempted: bool = False  # the quota ran out before this unit's turn
    gated: bool = False  # the classifier kept this unit away from the LLM


class CodeReviewAgent(BaseAgent):
    name = "code_review"
    id_prefix = "CR"

    def __init__(
        self,
        llm: LLMProvider | None = None,
        *,
        settings: Settings | None = None,
        retriever: Retriever | None = None,
        analyzers: list[StaticAnalyzer] | None = None,
        progress: Callable[[str], None] | None = None,
        classifier: ChangeClassifier | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        mode = self.settings.review.mode
        if mode != "static_only" and llm is None:
            raise ValueError(f"review.mode={mode!r} needs an LLM provider")
        self.llm = llm  # type: ignore[assignment]
        self._retriever = retriever
        if analyzers is None:
            analyzers = self._default_analyzers()
            if self.settings.review.type_check and mypy_available():
                analyzers.append(TypeCheckAnalyzer())
        self.analyzers = analyzers
        self.progress = progress or (lambda msg: logger.info(msg))
        self.classifier = classifier
        self.last_timer: RunTimer | None = None  # survives a run that raises
        self.last_usage: Usage | None = None
        self._quota_stats: dict[str, Any] | None = None
        review = self.settings.review
        cache_root = PROJECT_ROOT / review.cache_dir
        self._unit_cache = (
            UnitCache(cache_root / "llm_units", review.cache_ttl_hours)
            if review.unit_cache and review.mode != "static_only"
            else None
        )
        self._analysis_cache = (
            AnalysisCache(cache_root / "static_analysis") if review.analysis_cache else None
        )

    # ---- what a specialized agent replaces ------------------------------------------------------

    def _default_analyzers(self) -> list[StaticAnalyzer]:
        return default_analyzers()

    def _load_prompt(self, name: str) -> PromptTemplate:
        return load_prompt(name)

    def _prompt_versions(self) -> dict[str, str]:
        return prompt_versions()

    def _parse_reply(
        self, envelope: LLMReviewEnvelope
    ) -> tuple[list[LLMFinding], list[StaticAssessment], list[str]]:
        return parse_items(envelope)

    def _filter_static(self, static: list[Finding]) -> list[Finding]:
        """Which static findings this agent reports. All of them here."""
        return static

    def _build_units(
        self,
        repo: Repository,
        index: RepoIndex,
        targets: list[str],
        scope: Scope | None,
        request: AgentRequest,
    ) -> list[ReviewUnit]:
        units: list[ReviewUnit] = []
        for f in targets:
            units.extend(
                build_units(
                    repo,
                    index.modules[f],
                    self.settings.review.max_unit_lines,
                    scope.get(f) if scope else None,
                )
            )
        return units

    def _select_units(
        self,
        units: list[ReviewUnit],
        repo: Repository,
        static: list[Finding],
        stats: dict[str, Any],
        errors: list[str],
    ) -> list[ReviewUnit]:
        """Which units get an LLM call. All of them here, up to `review.max_units`."""
        return units

    def _check_claims(
        self, findings: list[Finding], repo: Repository, unit: ReviewUnit
    ) -> tuple[list[Finding], list[str]]:
        """Checks beyond shared validation: (kept findings, one reason per rejected finding)."""
        return findings, []

    def _finish_findings(self, findings: list[Finding], repo: Repository) -> list[Finding]:
        """Last change to the ranked findings, before suggested fixes."""
        return findings

    # ---- construction helpers ------------------------------------------------------------------

    def _make_retriever(self) -> Retriever | None:
        """Injected retriever: shared (use concurrency 1 across runs); else one per run."""
        rag = self.settings.rag
        if not rag.enabled:
            return None
        if self._retriever is not None:
            return self._retriever
        persist = rag.persist_dir if rag.vector_store == "chroma" else None
        return Retriever(
            create_embedder(rag.embedding_model), create_store(rag.vector_store, persist)
        )

    @staticmethod
    def load(request: AgentRequest, settings: Settings) -> Repository:
        files = request.options.get("files")
        if isinstance(files, dict):
            return load_files(files, settings.ingestion)
        if request.snippet is not None:
            return load_snippet(request.snippet, request.snippet_filename, settings.ingestion)
        assert request.repo_path is not None
        return load_repository(request.repo_path, settings.ingestion)

    # ---- main entry point ----------------------------------------------------------------------

    def run(self, request: AgentRequest) -> ReviewResult:
        started = datetime.now(UTC)
        timer = self.last_timer = RunTimer()  # starts the total review time
        wait_start = self.rate_limit_wait()
        timings: dict[str, float] = {}
        t = time.perf_counter()
        with timer.span("load_repository", INGESTION):
            repo = self.load(request, self.settings)
        try:
            index = RepoIndex.build(repo, timer)
            timings["ingest_parse"] = time.perf_counter() - t
            return self.review_repository(
                repo, index, request, started, timings, timer=timer, wait_start=wait_start
            )
        finally:
            if not request.options.get("keep_workspace"):
                repo.cleanup()

    def review_repository(
        self,
        repo: Repository,
        index: RepoIndex,
        request: AgentRequest | None = None,
        started: datetime | None = None,
        timings: dict[str, float] | None = None,
        extra_findings: list[Finding] | None = None,
        run_usage: Usage | None = None,
        timer: RunTimer | None = None,
        wait_start: float | None = None,
    ) -> ReviewResult:
        """Review `repo`. `extra_findings` (already validated, e.g. change-impact findings outside
        the diff scope) join the pipeline before dedup, rubric and ranking."""
        request = request or AgentRequest(repo_path=str(repo.root))
        started = started or datetime.now(UTC)
        timings = timings if timings is not None else {}
        cfg = self.settings.review
        errors: list[str] = []
        # Effective flags: static-only never builds a retriever, whatever rag.enabled says.
        stats: dict[str, Any] = {
            "mode": cfg.mode,
            "static_enabled": cfg.mode != "llm_only",
            "llm_enabled": cfg.mode != "static_only",
            "rag_enabled": self.settings.rag.enabled and cfg.mode != "static_only",
        }
        # this run only (providers are shared across concurrent runs)
        run_usage = run_usage if run_usage is not None else Usage()
        if timer is None:
            timer, wait_start = RunTimer(), self.rate_limit_wait()
        self.last_timer, self.last_usage = timer, run_usage
        hits_before = self._analysis_cache.hits if self._analysis_cache else 0

        scope = self._scope(request, repo)
        targets = self._targets(request, repo, scope)
        stats["review_id"] = uuid.uuid4().hex[:12]
        stats["source_name"] = (
            request.snippet_filename
            if request.snippet is not None
            else Path(request.repo_path or str(repo.root)).name
        )
        stats["bytes_reviewed"] = sum(repo.by_path[f].size for f in targets)
        stats["files_total"] = len(repo.files)
        stats["python_files"] = len(repo.python_files)
        stats["files_reviewed"] = len(targets)
        stats["lines_reviewed"] = sum(repo.line_count(f) for f in targets)
        stats["syntax_errors"] = sum(1 for f in targets if index.modules[f].syntax_error)
        stats["has_tests"] = index.has_tests()

        # 1. static analysis ----------------------------------------------------------------------
        t = time.perf_counter()
        static: list[Finding] = []
        raw_by_analyzer: dict[str, int] = {}
        if cfg.mode != "llm_only":
            static_files = targets + [
                f.path for f in repo.files if f.language != "python" and f.kind is FileKind.CONFIG
            ]
            for analyzer in self.analyzers:
                cache = self._analysis_cache
                with timer.span(analyzer.name, STATIC):
                    cached = cache.get(repo, analyzer, static_files, scope) if cache else None
                    out = cached or analyzer.analyze(repo, index, static_files, scope)
                if cache is not None and cached is None:
                    cache.put(repo, analyzer, static_files, scope, out)
                static.extend(out.findings)
                raw_by_analyzer[analyzer.name] = len(out.findings)
                errors.extend(f"[{analyzer.name}] {e}" for e in out.errors)
            static = self._filter_static(static)
        timings["static_analysis"] = time.perf_counter() - t
        stats["static_findings_raw"] = raw_by_analyzer
        self.progress(f"static analysis: {len(static)} raw findings")

        # 2. LLM review with context -------------------------------------------------------------
        llm_findings: list[Finding] = []
        llm_rejections: Counter[str] = Counter()
        outcomes: list[UnitOutcome] = []
        if cfg.mode != "static_only":
            t = time.perf_counter()
            retriever = self._make_retriever()
            if retriever is not None:
                with timer.span("chunk_embed_store", RAG_INDEX):
                    idx_stats = retriever.index_repository(index)
                stats["rag_index"] = {
                    "chunks": idx_stats.chunks,
                    "by_source_type": idx_stats.by_source_type,
                }
            timings["rag_index"] = time.perf_counter() - t

            builder = None
            if self.settings.rag.enabled:
                builder = ContextBuilder(
                    index,
                    retriever,
                    structural=self.settings.rag.structural_context,
                    top_k=self.settings.rag.top_k,
                    guideline_k=self.settings.rag.guideline_k,
                    max_chars=self.settings.rag.max_context_chars,
                    timer=timer,
                )
            units = self._build_units(repo, index, targets, scope, request)
            units = self._select_units(units, repo, static, stats, errors)
            if len(units) > cfg.max_units:
                errors.append(
                    f"{len(units)} review units exceed max_units={cfg.max_units}; truncated"
                )
                units = units[: cfg.max_units]
            stats["units_total"] = len(units)

            with timer.span("plan_units", CLASSIFIER if self.classifier else PROMPT):
                plan = plan_units(
                    repo,
                    units,
                    static,
                    self.classifier,
                    self.settings.classifier,
                    request.options.get("patches"),
                )
            if plan.classifier:
                stats["classifier"] = plan.classifier
            t = time.perf_counter()
            outcomes = self._review_units(repo, units, plan, static, builder, run_usage, timer)
            timings["llm_review"] = time.perf_counter() - t
            self._record_unit_stats(stats, outcomes, plan, errors)
            if self._quota_stats is not None:
                stats["quota"] = self._quota_stats
                self._quota_stats = None

            for oc in outcomes:
                errors.extend(f"[{oc.unit.key}] {e}" for e in oc.errors)
                self._apply_assessments(static, oc)
                # LLM findings must lie inside their own unit (and inside the diff scope, if any).
                unit_scope = {
                    oc.unit.file: oc.unit.changed or [(oc.unit.start_line, oc.unit.end_line)]
                }
                validator = FindingValidator(
                    repo, cfg.require_llm_evidence, unit_scope, cfg.scope_slack
                )
                with timer.span("evidence_validation", VALIDATION):
                    report = validate_all(validator, oc.findings)
                    accepted, claim_rejections = self._check_claims(report.accepted, repo, oc.unit)
                llm_findings.extend(accepted)
                for rej in report.rejected:
                    llm_rejections[str(rej.reason)] += 1
                llm_rejections.update(claim_rejections)
                stats.setdefault("llm_repaired", 0)
                stats["llm_repaired"] += report.repaired
            stats["llm_findings_raw"] = sum(len(oc.findings) for oc in outcomes)
            stats["llm_findings_valid"] = len(llm_findings)
            if cfg.drop_vague:
                with timer.span("actionability", VALIDATION):
                    llm_findings, dropped, downgraded = filter_actionable(llm_findings)
                stats["vague_dropped"] = dropped
                stats["vague_downgraded"] = downgraded
            stats["llm_rejected_by_reason"] = dict(llm_rejections)
            raw = stats["llm_findings_raw"]
            stats["llm_rejection_rate"] = (
                round(sum(llm_rejections.values()) / raw, 4) if raw else 0.0
            )
            verdicts = Counter(a.verdict for oc in outcomes for a in oc.assessments)
            stats["static_assessments"] = dict(verdicts)
            ctx_counts = Counter(i.reason for oc in outcomes for i in oc.context)
            stats["context_items_by_reason"] = dict(ctx_counts)
            stats["avg_context_items_per_unit"] = (
                round(sum(ctx_counts.values()) / len(outcomes), 2) if outcomes else 0.0
            )
            if self.llm is not None:
                stats["llm_usage"] = run_usage.snapshot()

        # 3. validate static findings (file/lines exist, diff scope) ------------------------------
        static_validator = FindingValidator(repo, cfg.require_llm_evidence, scope, cfg.scope_slack)
        with timer.span("static_validation", VALIDATION):
            static_report = validate_all(static_validator, static)
        stats["static_rejected"] = len(static_report.rejected)

        # 4. dedup -> rubric -> confidence -> filter -> rank --------------------------------------
        t = time.perf_counter()
        with timer.span("dedup_severity_confidence", VALIDATION):
            combined = static_report.accepted + llm_findings + list(extra_findings or [])
            dedup = deduplicate(combined)
            ruled = [redact_finding(calibrate(apply_rubric(f))) for f in dedup.findings]
            kept = [
                f
                for f in ruled
                if passes_threshold(f, cfg.min_confidence)
                and (cfg.include_info or f.severity is not Severity.INFO)
            ]
            final = self._finish_findings(rank_and_number(kept, self.id_prefix), repo)
        stats["dedup_merged"] = dedup.merged
        stats["filtered_low_confidence"] = len(ruled) - len(kept)
        timings["postprocess"] = time.perf_counter() - t

        # 5. suggested fixes for the top findings (LLM-written, verified by re-analysis) -----------
        fixes_allowed = "quota" not in stats  # no calls that are bound to fail
        if (
            cfg.suggest_fixes
            and cfg.mode != "static_only"
            and self.llm is not None
            and final
            and fixes_allowed
        ):
            t = time.perf_counter()
            fixer = FixGenerator(
                self.llm,
                repo,
                index,
                self.settings.ingestion,
                cfg.max_llm_fixes,
                run_usage,
                progress=self.progress,
            )
            with timer.span("fix_generation", OTHER):
                final = fixer.run(final)
            stats["fixes"] = fixer.stats.as_dict()
            timings["suggested_fixes"] = time.perf_counter() - t
            stats["llm_usage"] = run_usage.snapshot()
        stats["fixes_available"] = sum(1 for f in final if f.suggested_fix is not None)
        stats["final_findings"] = len(final)
        if self._analysis_cache is not None:
            stats["static_cache_hits"] = self._analysis_cache.hits - hits_before
        stats["run_type"] = (
            "warm" if stats.get("static_cache_hits") or stats.get("units_from_cache") else "cold"
        )
        stats.setdefault("review_status", "complete")
        stats["llm_calls"] = [c.model_dump() for c in run_usage.call_log()]
        stats["timings_s"] = {k: round(v, 3) for k, v in timings.items()}
        stats["timing"] = self.timing(timer, run_usage, wait_start).model_dump()

        metadata = RunMetadata(
            agent=self.name,
            provider=self.llm.name
            if self.llm is not None and cfg.mode != "static_only"
            else "none",
            model=self.llm.model if self.llm is not None and cfg.mode != "static_only" else None,
            temperature=self.llm.config.temperature if self.llm is not None else None,
            prompt_versions=self._prompt_versions() if cfg.mode != "static_only" else {},
            rag_enabled=self.settings.rag.enabled and cfg.mode != "static_only",
            started_at=started,
            finished_at=datetime.now(UTC),
        )
        return ReviewResult(
            agent=self.name,
            findings=final,
            rejected_findings=sum(llm_rejections.values()) + len(static_report.rejected),
            errors=errors,
            metadata=metadata,
            files_analyzed=len(targets),
            lines_analyzed=stats["lines_reviewed"],
            stats=stats,
        )

    # ---- timing -------------------------------------------------------------------------------

    def rate_limit_wait(self) -> float | None:
        """Seconds this provider's rate limiter has waited so far (None without a limiter)."""
        limiter = getattr(self.llm, "limiter", None) if self.llm is not None else None
        waited = getattr(limiter, "waited_s", None)
        return float(waited) if isinstance(waited, int | float) else None

    def timing(
        self, timer: RunTimer, run_usage: Usage, wait_start: float | None
    ) -> TimingBreakdown:
        """Breakdown of this run so far: the timer's spans plus the LLM calls' own spans."""
        extra = [
            ("api_call", LLM, start, end) if kind == "inference"
            else ("json_schema", VALIDATION, start, end)
            for kind, start, end in run_usage.spans()
        ]  # fmt: skip
        wait_now = self.rate_limit_wait()
        wait = None if wait_now is None or wait_start is None else max(0.0, wait_now - wait_start)
        return TimingBreakdown.from_timer(
            timer.merged(extra),
            timer.elapsed(),
            concurrency=max(1, self.settings.review.concurrency),
            rate_limit_wait_sec=wait,
        )

    # ---- helpers ------------------------------------------------------------------------------

    def _record_unit_stats(
        self,
        stats: dict[str, Any],
        outcomes: list[UnitOutcome],
        plan: UnitPlan,
        errors: list[str],
    ) -> None:
        """What happened to every unit. Nothing that was not reviewed goes unreported."""
        failed = [oc for oc in outcomes if oc.failed]
        stats["units_failed"] = len(failed)
        stats["units_failed_list"] = [oc.unit.key for oc in failed]
        stats["units_not_attempted"] = sum(1 for oc in outcomes if oc.not_attempted)
        stats["units_from_cache"] = sum(1 for oc in outcomes if oc.from_cache)
        stats["units_deduplicated"] = len(plan.duplicates)
        gated = [oc for oc in outcomes if oc.gated]
        stats["units_skipped"] = stats["units_not_attempted"] + len(gated)
        if gated:
            errors.append(
                f"classifier: {len(gated)} low-risk unit(s) were not sent to the LLM; static "
                "analysis still covered them"
            )
        if failed:
            stats["review_status"] = "partial"

    def _scope(self, request: AgentRequest, repo: Repository) -> Scope | None:
        raw = request.options.get("changed_lines")
        if not raw:
            return None
        scope: Scope = {}
        for path, ranges in raw.items():
            resolved = repo.resolve_path(path)
            if resolved is None:
                continue
            scope[resolved] = [(int(s), int(e)) for s, e in ranges]
        return scope

    def _targets(self, request: AgentRequest, repo: Repository, scope: Scope | None) -> list[str]:
        include_tests = bool(
            request.options.get("include_tests", self.settings.review.include_tests)
        )
        if request.target_files:
            chosen = [p for p in (repo.resolve_path(t) for t in request.target_files) if p]
        elif scope is not None:
            chosen = list(scope)
        else:
            chosen = [
                f.path
                for f in repo.python_files
                if f.kind is FileKind.CODE or (include_tests and f.kind is FileKind.TEST)
            ]
        return [p for p in chosen if repo.by_path[p].language == "python"]

    def _review_units(
        self,
        repo: Repository,
        units: list[ReviewUnit],
        plan: UnitPlan,
        static: list[Finding],
        builder: ContextBuilder | None,
        run_usage: Usage,
        timer: RunTimer,
    ) -> list[UnitOutcome]:
        workers = max(1, self.settings.review.concurrency)
        total = len(plan.order)
        spent = threading.Event()  # set on the first quota stop: later calls could only fail
        stop: list[QuotaExhaustedError] = []

        def job(position: int, i: int) -> tuple[int, UnitOutcome]:
            unit = units[i]
            if spent.is_set():
                reason = "not reviewed: the LLM quota ran out first; rerun to continue"
                return i, UnitOutcome(unit=unit, failed=True, not_attempted=True, errors=[reason])
            try:
                outcome = self._review_unit(repo, unit, static, builder, run_usage, timer)
            except QuotaExhaustedError as exc:
                spent.set()
                stop.append(exc)
                outcome = UnitOutcome(unit=unit, failed=True, errors=[f"LLM review failed: {exc}"])
            self.progress(f"reviewed unit {position + 1}/{total}: {unit.key}")
            return i, outcome

        work = list(enumerate(plan.order))
        if workers == 1 or total <= 1:
            done = dict(job(p, i) for p, i in work)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                done = dict(pool.map(lambda x: job(*x), work))
        if stop:
            self._quota_stats = {
                "message": str(stop[0]),
                "resets_at": stop[0].resets_at,
                "retry_after_s": stop[0].retry_after_s,
            }
        for i in plan.skipped:
            done[i] = UnitOutcome(unit=units[i], gated=True)
        for copy, original in plan.duplicates.items():
            done[copy] = _copy_outcome(done[original], units[copy])
        return [done[i] for i in range(len(units))]

    def _review_unit(
        self,
        repo: Repository,
        unit: ReviewUnit,
        static: list[Finding],
        builder: ContextBuilder | None,
        run_usage: Usage,
        timer: RunTimer,
    ) -> UnitOutcome:
        assert self.llm is not None
        outcome = UnitOutcome(unit=unit)
        render_start = time.perf_counter()
        numbered = render_numbered(repo, unit)
        code = "\n".join(repo.lines(unit.file)[unit.start_line - 1 : unit.end_line])

        in_unit = [
            (i, f)
            for i, f in enumerate(static)
            if f.file == unit.file and unit.start_line <= f.start_line <= unit.end_line
        ]
        show_static = self.settings.review.mode == "full" and self.settings.review.llm_triage_static
        static_lines = []
        if show_static:
            for n, (i, f) in enumerate(in_unit, start=1):
                ref = f"S{n}"
                outcome.static_refs[ref] = i
                tool = f.sources[0].value if f.sources else "static"
                static_lines.append(
                    f"- {ref} [{tool} {f.rule_id or ''}] line {f.start_line}: {f.title}"
                )
        static_section = (
            "## Static analysis findings in this unit (assess each in static_assessments)\n"
            + ("\n".join(static_lines) if static_lines else "(none)")
            if show_static
            else ""
        )
        timer.record("unit_render", PROMPT, render_start, time.perf_counter())

        if builder is not None:
            hints = [f.title for _, f in in_unit]
            outcome.context = builder.build(unit, code, hints)
            context_section = render_context(outcome.context)
        else:
            context_section = ""

        def messages_with(context: str) -> list[Message]:
            review = self._load_prompt("review").render(
                file=unit.file,
                start_line=unit.start_line,
                end_line=unit.end_line,
                total_lines=repo.line_count(unit.file),
                scope_note="; this is a change review" if unit.changed else "",
                changed_legend=" Changed lines are marked with '>'; focus on them."
                if unit.changed
                else "",
                context_section=context,
                static_section=static_section,
                numbered_code=numbered,
            )
            return [
                Message(role="system", content=self._load_prompt("system").text),
                Message(role="user", content=review),
            ]

        prompt_start = time.perf_counter()
        request_messages = messages_with(context_section)
        timer.record("prompt_render", PROMPT, prompt_start, time.perf_counter())
        # Secrets stay out of the on-disk cache: such a unit is simply reviewed again.
        cache = None if any(is_secret_finding(f) for _, f in in_unit) else self._unit_cache
        key = UnitCache.key(request_messages, self.llm) if cache else ""
        cached = cache.get(key) if cache else None
        try:
            if cached is not None:
                envelope = LLMReviewEnvelope.model_validate_json(cached)
                outcome.from_cache = True
            else:
                try:
                    envelope = self.llm.generate_structured(
                        request_messages, LLMReviewEnvelope, usage=run_usage, label=unit.key
                    )
                except RequestTooLargeError:
                    if not context_section:
                        raise
                    # Small per-request quotas (e.g. free tiers): the code matters, retrieved
                    # context is optional. Retry once without it and say so.
                    outcome.errors.append(
                        "LLM request too large with project context; reviewed without it"
                    )
                    outcome.context = []
                    envelope = self.llm.generate_structured(
                        messages_with(""), LLMReviewEnvelope, usage=run_usage, label=unit.key
                    )
                if cache:
                    cache.put(key, envelope.model_dump_json())
        except QuotaExhaustedError:
            raise  # handled once, by the caller: the remaining units must not call the LLM
        except LLMError as exc:
            outcome.failed = True
            outcome.errors.append(f"LLM review failed: {exc}")
            return outcome

        items, assessments, parse_errors = self._parse_reply(envelope)
        outcome.errors.extend(parse_errors)
        outcome.assessments = assessments
        module_symbols = {s.qualname: s for s in unit.symbols}
        for item in items:
            sym = next(
                (
                    q
                    for q, s in module_symbols.items()
                    if s.start_line <= item.start_line <= s.end_line
                ),
                None,
            )
            outcome.findings.append(item.to_finding(unit.file, sym))
        return outcome

    def partial_stats(self) -> dict[str, Any]:
        """What was measured before a run raised, so a crash still leaves a timing record."""
        if self.last_timer is None:
            return {}
        usage = self.last_usage or Usage()
        wait = self.rate_limit_wait()
        timing = self.timing(self.last_timer, usage, wait)
        return {
            "timing": timing.model_dump(),
            "llm_usage": usage.snapshot(),
            "llm_calls": [c.model_dump() for c in usage.call_log()],
            "review_status": "failed",
        }

    @staticmethod
    def _apply_assessments(static: list[Finding], outcome: UnitOutcome) -> None:
        for a in outcome.assessments:
            idx = outcome.static_refs.get(a.ref.strip())
            if idx is None:
                continue
            f = static[idx]
            note = {"confirm": "llm: confirmed", "false_positive": "llm: false positive"}.get(
                a.verdict
            )
            update: dict[str, Any] = {}
            if note:
                update["notes"] = [*f.notes, note]
            if a.recommendation and a.verdict != "false_positive":
                update["recommendation"] = a.recommendation
            if a.test_recommendation and not f.test_recommendation:
                update["test_recommendation"] = a.test_recommendation
            if update:
                static[idx] = f.model_copy(update=update)


def _copy_outcome(original: UnitOutcome, unit: ReviewUnit) -> UnitOutcome:
    """The reviewed unit's result, moved onto an identical copy of its code.

    Findings then pass the same evidence validation against the copy's own file and lines. Static
    assessments are not copied: their references belong to the original unit's list.
    """
    offset = unit.start_line - original.unit.start_line
    moved = [
        f.model_copy(
            update={
                "file": unit.file,
                "start_line": f.start_line + offset,
                "end_line": f.end_line + offset,
                "notes": [*f.notes, f"reviewed as a copy of {original.unit.key}"],
            }
        )
        for f in original.findings
    ]
    return UnitOutcome(
        unit=unit,
        findings=moved,
        errors=list(original.errors),
        failed=original.failed,
        not_attempted=original.not_attempted,
    )
