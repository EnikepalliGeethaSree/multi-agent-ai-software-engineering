"""Review a CODE CHANGE (pull request / diff) instead of a whole codebase.

    change = changeset_from_git("path/to/repo", base="main", head="feature")
    result = review_change(agent, change)

Pipeline:
1. impact analysis over the whole new version (removed functions still called, calls that no longer
   match a new signature, LLM check of callers the change did not update);
2. the normal review pipeline, scoped to the changed lines (static analysis + LLM + validation);
   impact findings join it before dedup, severity rubric and ranking;
3. hunk risk ranking ("look here first") and a PR-style summary.
"""

from __future__ import annotations

import time

from marl_agents.agents.code_review.agent import CodeReviewAgent
from marl_agents.agents.code_review.change_summary import build_summary
from marl_agents.agents.code_review.impact import ImpactAnalyzer
from marl_agents.agents.code_review.risk import rank_hunks
from marl_agents.core.schemas import AgentRequest, ChangedFile, ChangeReview, ReviewResult
from marl_agents.core.timing import INGESTION, OTHER, STATIC, VALIDATION, RunTimer
from marl_agents.findings import FindingValidator, validate_all
from marl_agents.ingestion.changes import ChangeSet
from marl_agents.llm.base import Usage
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.static_analysis.type_check import TypeCheckAnalyzer, mypy_available


def review_change(agent: CodeReviewAgent, change: ChangeSet) -> ReviewResult:
    t0 = time.perf_counter()
    timer = RunTimer()  # total change-review time (the ChangeSet is loaded by the caller)
    wait_start = agent.rate_limit_wait()
    cfg = agent.settings.review
    llm = agent.llm if cfg.mode != "static_only" else None
    run_usage = Usage()
    repo = change.repo
    with timer.span("ast_index", INGESTION):
        index = RepoIndex.build(repo)
    agent.progress(
        f"change: {len(change.files)} file(s) changed between {change.base} and {change.head}"
    )

    # 1. impact analysis (whole repository) --------------------------------------------------
    t = time.perf_counter()
    analyzer = ImpactAnalyzer(change, index, llm, max_llm_checks=cfg.max_impact_checks)
    with timer.span("impact_analysis", OTHER):
        impact = analyzer.run(run_usage)
    # Type errors in UNCHANGED caller files, at call sites of changed code (cross-file contracts).
    if cfg.type_check and cfg.mode != "llm_only" and mypy_available() and impact.impacted_files:
        sites = analyzer.call_sites()
        with timer.span("mypy_impacted_files", STATIC):
            typed = TypeCheckAnalyzer().analyze(repo, index, impact.impacted_files)
        impact.errors.extend(typed.errors)
        for f in typed.findings:
            if (f.file, f.start_line) in sites:
                impact.findings.append(
                    f.model_copy(update={"related": [sites[(f.file, f.start_line)]]})
                )
    # Deterministic impact findings sit OUTSIDE the diff: validate them (file/lines exist) here.
    det = [f for f in impact.findings if f.rule_id != "IMPACT-BEHAVIOR"]
    with timer.span("impact_validation", VALIDATION):
        det_valid = validate_all(FindingValidator(repo, cfg.require_llm_evidence), det)
    impact_findings = det_valid.accepted + [
        f for f in impact.findings if f.rule_id == "IMPACT-BEHAVIOR"
    ]
    agent.progress(
        f"impact analysis: {len(impact.symbols)} changed function(s), "
        f"{len(impact_findings)} caller issue(s), {len(impact.impacted_files)} impacted file(s)"
    )
    impact_s = time.perf_counter() - t

    # 2. normal review, scoped to the changed lines ------------------------------------------
    scope = change.scope()
    request = AgentRequest(
        repo_path=str(repo.root),
        options={
            "changed_lines": {k: [list(r) for r in v] for k, v in scope.items()},
            "include_tests": True,
        },
    )
    if scope:
        result = agent.review_repository(
            repo,
            index,
            request,
            extra_findings=impact_findings,
            run_usage=run_usage,
            timer=timer,
            wait_start=wait_start,
        )
    else:  # only deletions / non-code files changed: nothing to review line by line
        result = agent.review_repository(
            repo,
            index,
            request.model_copy(update={"target_files": ["__none__"]}),
            extra_findings=impact_findings,
            run_usage=run_usage,
            timer=timer,
            wait_start=wait_start,
        )

    # 3. hunk risk + summary -----------------------------------------------------------------
    tested: set[str] = (
        set().union(*index.test_identifiers.values()) if index.test_identifiers else set()
    )
    with timer.span("hunk_risk", OTHER):
        hunks = rank_hunks(change.files, result.findings, impact.symbols, tested, index.has_tests())
    with timer.span("change_summary", OTHER):
        summary, summary_errors = build_summary(
            change, index, impact.symbols, impact.impacted_files, llm, run_usage
        )
    result.change = ChangeReview(
        summary=summary,
        files=[
            ChangedFile(
                path=f.path,
                status=f.status,
                old_path=f.old_path if f.old_path != f.path else None,
                added=f.added,
                deleted=f.deleted,
                changed_ranges=f.changed_ranges,
                patch=f.patch,
            )
            for f in change.files
        ],
        hunks=hunks,
    )
    result.errors.extend(impact.errors + summary_errors)
    result.stats["change"] = {
        "base": change.base,
        "head": change.head,
        **impact.stats,
        "hunks": len(hunks),
        "high_risk_hunks": sum(1 for h in hunks if h.level == "high"),
    }
    if llm is not None:
        result.stats["llm_usage"] = run_usage.snapshot()
    result.stats.setdefault("timings_s", {})["impact_analysis"] = round(impact_s, 3)
    result.stats["timings_s"]["change_review_total"] = round(time.perf_counter() - t0, 3)
    result.stats["lines_changed"] = summary.lines_added + summary.lines_deleted
    result.stats["timing"] = agent.timing(timer, run_usage, wait_start).model_dump()
    return result
