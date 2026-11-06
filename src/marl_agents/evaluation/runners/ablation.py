"""Baseline comparison: run the Code Review Agent under configurations A-D on identical inputs.

    A Static Only | B LLM Only | C Static + LLM | D Static + LLM + RAG

Fairness (each rule is recorded in the runs' ``experiment`` metadata):
- one sample set for every configuration (CodeReviewer samples are loaded once, then shared);
- every other setting is identical: `apply_configuration` changes only review.mode and rag.enabled;
- the same LLM provider object (model, temperature, seed) serves every LLM configuration;
- repeats are interleaved (repeat -> configuration) so API or machine drift hits all alike;
- each configuration of each repeat is saved as its own ordinary run (so `eval summary`, the API and
  the dashboard read it like any other run), tagged with a shared ``group_id``;
- failures are counted, never scored: a CodeReviewer sample whose LLM review failed is excluded
  from that configuration (D22) and the comparison then uses the samples every configuration
  evaluated; a planted run with a failed LLM unit is marked incomplete.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marl_agents.agents.code_review.agent import CodeReviewAgent
from marl_agents.config import PROJECT_ROOT, Settings
from marl_agents.evaluation.configurations import (
    CONFIGURATIONS,
    apply_configuration,
    classify_settings,
    experiment_metadata,
)
from marl_agents.evaluation.datasets.codereviewer import CodeReviewerSample
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners import code_review as runner
from marl_agents.evaluation.runs import load_run
from marl_agents.llm.base import LLMProvider
from marl_agents.llm.classifier import create_classifier

logger = logging.getLogger(__name__)

PLANTED_REPO = PROJECT_ROOT / "tests" / "fixtures" / "repos" / "planted"
PLANTED_EXPECTED = PLANTED_REPO.parent / "planted_expected.json"
PLANTED_RULES = {
    "line_tolerance": 2,
    "match": "same file, start within +-2 lines, compatible category",
    "precision_over": "defect findings (bug, security, error_handling, edge_case)",
}
CLS_RULES = {
    "flag_threshold": "at least one finding of severity >= low",
    "score": "highest finding priority (severity rank + confidence) / 5",
    "adjusted_excludes_rules": sorted(runner.CROSS_HUNK_RULES),
}
MSG_RULES = {
    "comment": "top-ranked finding: title + recommendation (variant title_fix)",
    "text_metric_scale": "BLEU-4, ROUGE-L, chrF in 0-100; coverage in 0-1",
}


def planted_issue_ids(expected_path: Path = PLANTED_EXPECTED) -> list[str]:
    """Answer-key entries as ids that change whenever a label changes (fingerprinted)."""
    spec = json.loads(expected_path.read_text(encoding="utf-8"))
    return [f"{i['id']}:{i['file']}:{i['line']}:{i['category']}" for i in spec["issues"]]


def planted_once(
    settings: Settings,
    llm: LLMProvider | None,
    *,
    results_dir: Path | None = None,
    group_id: str | None = None,
    repeat: int | None = None,
    repeats: int | None = None,
    repo: Path = PLANTED_REPO,
    expected: Path = PLANTED_EXPECTED,
) -> Path:
    """One planted-issue run under `settings`' configuration. Returns the run folder."""
    config = classify_settings(settings)
    use_llm = llm if config.llm else None
    agent = runner.make_agent(settings, use_llm)
    rec = RunRecorder(f"planted_{config.key}", settings, base_dir=results_dir)
    result, metrics = runner.run_planted(agent, repo, expected)
    for f in result.findings:
        rec.prediction(json.loads(f.model_dump_json()))
    units_failed = int(result.stats.get("units_failed", 0) or 0)
    for e in result.errors:
        if "LLM review failed" in e:
            rec.error("planted", e)
    metrics["complete"] = units_failed == 0
    metrics["llm_units_failed"] = units_failed
    md = runner.planted_summary_md(metrics, f"Planted-issue benchmark ({config.label})")
    if units_failed:
        md += f"\n**Incomplete:** {units_failed} LLM review unit(s) failed (see errors.jsonl).\n"
    ids = planted_issue_ids(expected)
    exp = experiment_metadata(
        settings,
        benchmark="planted",
        llm_used=use_llm is not None,
        sample_ids=ids,
        n_evaluated=len(ids),
        n_failed=units_failed,
        dataset="planted-issue fixture (tests/fixtures/repos/planted)",
        evaluation_rules=PLANTED_RULES,
        analyzers=[a.name for a in agent.analyzers],
        group_id=group_id,
        repeat=repeat,
        repeats=repeats,
    )
    return rec.finish(
        metrics,
        md,
        experiment=exp,
        llm_provider=settings.llm.provider if use_llm else None,
        llm_model=settings.llm.model if use_llm else None,
    )


def codereviewer_once(
    settings: Settings,
    llm: LLMProvider | None,
    samples: list[CodeReviewerSample],
    *,
    task: str,
    split: str,
    seed: int,
    limit: int | None,
    workers: int = 8,
    results_dir: Path | None = None,
    group_id: str | None = None,
    repeat: int | None = None,
    repeats: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """One CodeReviewer cls/msg run under `settings`' configuration. Returns the run folder."""
    from marl_agents.static_analysis import (
        AstChecksAnalyzer,
        RadonAnalyzer,
        RuffAnalyzer,
        SecretsAnalyzer,
    )

    s = settings.model_copy(deep=True)
    config = classify_settings(s)
    use_llm = llm if config.llm else None
    # No test-gap analyzer: a single patched file has no test context, it would bias predictions.
    analyzers = [RuffAnalyzer(), RadonAnalyzer(), AstChecksAnalyzer(), SecretsAnalyzer()]
    s.review.concurrency = 1  # parallelism is across samples
    s.rag.vector_store = "memory"
    classifier = create_classifier(s.classifier) if use_llm is not None else None
    agent = CodeReviewAgent(
        use_llm, settings=s, analyzers=analyzers, progress=lambda _m: None, classifier=classifier
    )
    rec = RunRecorder(f"codereviewer_{task}_{split}_{config.key}_n{len(samples)}", s, results_dir)
    metrics = runner.run_codereviewer(agent, samples, rec, workers=workers, progress=progress)
    title = f"CodeReviewer {task} ({split}, Python, n={len(samples)}, seed={seed}, {config.label})"
    md = (
        runner.cls_summary_md(metrics, title)
        if task == "cls"
        else runner.msg_summary_md(metrics, title)
    )
    ids = [x.sample_id for x in samples]
    exp = experiment_metadata(
        s,
        benchmark=f"codereviewer_{task}",
        llm_used=use_llm is not None,
        sample_ids=ids,
        n_evaluated=metrics["n_evaluated"],
        n_failed=metrics["n_failed"],
        dataset="CodeReviewer (Python)",
        split=split,
        seed=seed,
        limit=limit,
        evaluation_rules=CLS_RULES if task == "cls" else MSG_RULES,
        analyzers=[a.name for a in analyzers],
        group_id=group_id,
        repeat=repeat,
        repeats=repeats,
    )
    return rec.finish(
        metrics,
        md,
        experiment=exp,
        dataset="CodeReviewer",
        task=task,
        split=split,
        seed=seed,
        limit=limit,
        languages=["py"],
        sample_ids=ids,
        llm_provider=s.llm.provider if use_llm else None,
        llm_model=s.llm.model if use_llm else None,
    )


def new_group_id() -> str:
    return "abl-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_ablation(
    benchmark: str,
    base: Settings,
    llm: LLMProvider | None,
    configurations: list[str],
    repeats: int = 1,
    *,
    samples: list[CodeReviewerSample] | None = None,
    task: str = "cls",
    split: str = "test",
    seed: int = 42,
    limit: int | None = None,
    workers: int = 8,
    llm_workers: int = 1,
    fixes: bool = False,
    results_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Run every configuration `repeats` times, then save a comparison record for the group.

    LLM fix suggestions are off unless `fixes`: they are extra LLM calls made after detection
    (they never change the findings), so they would only add time and quota use (as in `timing`).

    Returns (comparison run folder, comparison metrics).
    """
    from marl_agents.evaluation.comparison import build_group_tables, tables_md

    progress = progress or (lambda m: logger.info(m))
    unknown = [k for k in configurations if k not in CONFIGURATIONS]
    if unknown:
        raise ValueError(f"unknown configuration(s) {unknown}")
    if any(CONFIGURATIONS[k].llm for k in configurations) and llm is None:
        raise ValueError("LLM configurations need an LLM provider")
    if benchmark == "codereviewer" and not samples:
        raise ValueError("the CodeReviewer ablation needs samples")
    group_id = new_group_id()
    children: dict[str, list[str]] = {k: [] for k in configurations}
    for rep in range(1, repeats + 1):
        for key in configurations:
            s = apply_configuration(base, key)
            s.review.suggest_fixes = fixes
            if benchmark == "planted":
                # One LLM worker: findings do not depend on it (tested), but per-component times
                # (and "active" = total - quota waiting) are then comparable across configurations.
                s.review.concurrency = 1
            progress(f"[{group_id}] repeat {rep}/{repeats}: {CONFIGURATIONS[key].label}")
            if benchmark == "planted":
                out = planted_once(
                    s, llm, results_dir=results_dir, group_id=group_id, repeat=rep, repeats=repeats
                )
            else:
                assert samples is not None
                out = codereviewer_once(
                    s,
                    llm,
                    samples,
                    task=task,
                    split=split,
                    seed=seed,
                    limit=limit,
                    workers=llm_workers if CONFIGURATIONS[key].llm else workers,
                    results_dir=results_dir,
                    group_id=group_id,
                    repeat=rep,
                    repeats=repeats,
                    progress=progress,
                )
            children[key].append(out.name)
    runs = [load_run(out.parent / name) for names in children.values() for name in names]
    loaded = [r for r in runs if r is not None]
    tables = build_group_tables(loaded)
    metrics = {
        "group_id": group_id,
        "benchmark": benchmark if benchmark == "planted" else f"codereviewer_{task}",
        "configurations": configurations,
        "repeats": repeats,
        "suggested_fixes": fixes,
        "runs": children,
        "tables": [t.model_dump() for t in tables],
    }
    name = "ablation_planted" if benchmark == "planted" else f"ablation_codereviewer_{task}"
    rec = RunRecorder(name, base, base_dir=results_dir)
    md = tables_md(tables, f"Baseline comparison ({metrics['benchmark']}, group {group_id})")
    folder = rec.finish(metrics, md, group_id=group_id, configurations=configurations)
    return folder, metrics
