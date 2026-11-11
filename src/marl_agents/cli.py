"""Command line: review a repository / ZIP / file, or run Code Review Agent evaluations.

python -m marl_agents.cli review <dir|zip|file.py> [--mode static_only] [--out data/reports/x]
python -m marl_agents.cli eval codereviewer --task cls --limit 500 --mode static_only
python -m marl_agents.cli eval planted --configuration static_llm_rag --config configs/gemini.yaml
python -m marl_agents.cli eval ablation --benchmark planted --config configs/gemini.yaml  # A-D
python -m marl_agents.cli eval retrieval --path src
python -m marl_agents.cli eval classifier --model-dir data/models/change_cls   # test once
python -m marl_agents.cli eval summary          # baseline comparison + five-component tables
python -m marl_agents.cli bugs <dir|zip|file.py> [--failing-test tests/t.py::test_x]
python -m marl_agents.cli eval-bugs {audit|localization|detection|labels} --split dev --limit 10
python -m marl_agents.cli models                # models for the key in .env, with a recommendation
python -m marl_agents.cli check --model <id>    # one tiny request to verify key + model
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from marl_agents.config import PROJECT_ROOT, Settings, apply_groq_env, load_settings, model_for
from marl_agents.core.schemas import ReviewResult
from marl_agents.llm.base import LLMError, LLMProvider
from marl_agents.llm.classifier import ChangeClassifier, create_classifier
from marl_agents.llm.factory import create_provider

GEMINI_DATA_NOTICE = (
    "note: your code is sent to Google. On the free tier Google may use it to improve its "
    "products, so do not review confidential code this way (docs/llm-gemini.md)."
)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--config", type=Path, default=None, help="YAML config (default configs/default.yaml)"
    )
    p.add_argument("--mode", choices=["full", "static_only", "llm_only"])
    p.add_argument("--provider", choices=["mock", "openai", "groq", "gemini", "local", "ollama"])
    p.add_argument("--model")
    p.add_argument("--base-url")
    p.add_argument("--rpm", type=int, help="LLM requests per minute limit (your project's quota)")
    p.add_argument("--tpm", type=int, help="LLM tokens per minute limit (your project's quota)")
    p.add_argument("--classifier", help="fine-tuned change classifier folder (change reviews)")
    p.add_argument("--classifier-mode", choices=["prioritize", "gate"])
    p.add_argument(
        "--no-cache", action="store_true", help="repeat all work; ignore saved results and replies"
    )
    p.add_argument("--no-rag", action="store_true", help="disable retrieval (experiment config B)")
    p.add_argument("--no-structural", action="store_true", help="disable call-graph context")
    p.add_argument("--store", choices=["chroma", "memory"])
    p.add_argument("--embedder", help="'hashing' or a sentence-transformers model name")
    p.add_argument("--min-confidence", type=float)
    p.add_argument("--concurrency", type=int)
    p.add_argument("-v", "--verbose", action="store_true")


def build_settings(args: argparse.Namespace) -> Settings:
    s = load_settings(args.config)
    if args.mode:
        s.review.mode = args.mode
    if args.provider:
        s.llm.provider = args.provider
        s.llm.model = model_for(args.provider, s.llm.model)
    if s.llm.provider == "groq":
        apply_groq_env(s.llm)  # GROQ_* in .env win over the config file (D39)
    if args.model:
        s.llm.model = args.model
    if args.base_url:
        s.llm.base_url = args.base_url
    if getattr(args, "rpm", None):
        s.llm.requests_per_minute = args.rpm
    if getattr(args, "tpm", None):
        s.llm.tokens_per_minute = args.tpm
    if getattr(args, "no_rag", False):
        s.rag.enabled = False
    if args.no_structural:
        s.rag.structural_context = False
    if args.store:
        s.rag.vector_store = args.store
    if args.embedder:
        s.rag.embedding_model = args.embedder
    if args.min_confidence is not None:
        s.review.min_confidence = args.min_confidence
    if args.concurrency:
        s.review.concurrency = args.concurrency
    if getattr(args, "classifier", None):
        s.classifier.enabled = True
        s.classifier.model_dir = args.classifier
    if getattr(args, "classifier_mode", None):
        s.classifier.mode = args.classifier_mode
    if getattr(args, "no_cache", False):
        s.review.unit_cache = s.review.analysis_cache = False
        s.llm.response_cache = False
    return s


def build_llm(s: Settings) -> LLMProvider | None:
    return None if s.review.mode == "static_only" else create_provider(s.llm)


def build_classifier(s: Settings) -> ChangeClassifier | None:
    return create_classifier(s.classifier) if s.review.mode != "static_only" else None


def _print_data_notice(llm: LLMProvider | None) -> None:
    if llm is not None and llm.name == "gemini":
        print(GEMINI_DATA_NOTICE, file=sys.stderr)


def _print_partial(result: ReviewResult) -> None:
    """A partial review must never look like a complete one."""
    if result.stats.get("review_status") != "partial":
        return
    failed, skipped = (
        result.stats.get("units_failed", 0),
        result.stats.get("units_not_attempted", 0),
    )
    print(f"PARTIAL REVIEW: {failed} review unit(s) not reviewed ({skipped} never attempted).")
    quota = result.stats.get("quota")
    if isinstance(quota, dict):
        print(quota.get("message"))
    print("Run the same command again to continue; finished units are reused, not repeated.")


def cmd_review(args: argparse.Namespace) -> int:
    from marl_agents.agents.code_review import CodeReviewAgent
    from marl_agents.core.schemas import AgentRequest
    from marl_agents.reports import summarize, write_reports_timed

    s = build_settings(args)
    target = Path(args.target)
    if target.is_file() and target.suffix == ".py":
        request = AgentRequest(
            snippet=target.read_text(encoding="utf-8"), snippet_filename=target.name
        )
    else:
        request = AgentRequest(repo_path=str(target))
    llm = build_llm(s)
    _print_data_notice(llm)
    agent = CodeReviewAgent(
        llm,
        settings=s,
        progress=lambda m: print(f"  {m}", file=sys.stderr),
        classifier=build_classifier(s),
    )
    if getattr(args, "orchestrated", False):
        from marl_agents.agents.bug_detection import BugDetectionAgent
        from marl_agents.orchestration.graph import run_orchestrated

        bugs = BugDetectionAgent(
            llm, settings=s, progress=lambda m: print(f"  {m}", file=sys.stderr)
        )
        result = run_orchestrated(agent, bugs, request)
        agg = result.stats["aggregation"]
        print(
            f"orchestrated: code review {agg['findings_in']['code_review']} + bug detection "
            f"{agg['findings_in']['bug_detection']} findings -> {agg['total']} after aggregation "
            f"(only code review {agg['unique']['code_review']}, only bug detection "
            f"{agg['unique']['bug_detection']}, shared {agg['shared']})"
        )
    else:
        result = agent.run(request)
    _print_llm_usage(llm, result)
    out = (
        Path(args.out)
        if args.out
        else PROJECT_ROOT / "data" / "reports" / (target.stem or "review")
    )
    written = write_reports_timed(result, out, tuple(args.formats.split(",")))
    summary = summarize(result)
    print(
        f"{summary.total_findings} findings in {summary.files_analyzed} files "
        f"({summary.by_severity})"
    )
    for fmt, path in written.items():
        print(f"{fmt}: {path}")
    _print_timing(result)
    _print_partial(result)
    return _exit_code(result, args.fail_on)


def _print_timing(result: ReviewResult) -> None:
    t = result.stats.get("timing")
    if not isinstance(t, dict):
        return
    rag = (t.get("rag_index_sec") or 0.0) + (t.get("rag_retrieval_sec") or 0.0)
    wait = t.get("llm_rate_limit_wait_sec")
    print(
        f"time: total {t['total_sec']:.2f}s | static {t['static_analysis_sec']:.2f}s | "
        f"RAG {rag:.2f}s | LLM {t['llm_inference_sec']:.2f}s ({t['llm_calls']} calls) | "
        f"validation {t['validation_sec']:.2f}s | "
        f"reports {t.get('report_generation_sec') or 0:.2f}s"
        f" | other {t['other_sec']:.2f}s" + (f" (quota wait {wait:.2f}s)" if wait else "")
    )


SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]


def _exit_code(result: ReviewResult, fail_on: str) -> int:
    """CI / pre-commit gate: 1 when a finding at or above `fail_on` exists, else 0."""
    if fail_on == "none":
        return 0
    threshold = SEVERITY_ORDER.index(fail_on)
    blocking = [f for f in result.findings if SEVERITY_ORDER.index(f.severity.value) >= threshold]
    if blocking:
        sys.stdout.flush()
        print(f"FAIL: {len(blocking)} finding(s) at or above '{fail_on}'", file=sys.stderr)
        return 1
    return 0


def _print_llm_usage(llm: LLMProvider | None, result: ReviewResult) -> None:
    if llm is not None:
        usage = llm.usage
        line = (
            f"LLM {llm.name}/{llm.model}: {usage.calls} calls, {usage.input_tokens} input + "
            f"{usage.output_tokens} output tokens"
        )
        limiter = getattr(llm, "limiter", None)
        if limiter is not None and limiter.waited_s:
            line += f", throttled {limiter.waited_s:.0f}s to stay within the rate limit"
        rate_limited = getattr(llm, "rate_limited", 0)
        if rate_limited:
            line += f", {rate_limited} HTTP 429 response(s)"
        print(line)
        if result.stats.get("units_failed"):
            print(f"warning: {result.stats['units_failed']} review unit(s) failed; see report")


def cmd_review_change(args: argparse.Namespace) -> int:
    """Review a code change: git refs, uncommitted work, staged changes, or two ZIP archives."""
    from datetime import UTC, datetime

    from marl_agents.agents.bug_detection import BugDetectionAgent
    from marl_agents.agents.code_review import CodeReviewAgent
    from marl_agents.agents.code_review.change_review import review_change
    from marl_agents.ingestion.changes import ChangeError, changeset_from_git, changeset_from_zips
    from marl_agents.reports import write_reports_timed

    s = build_settings(args)
    try:
        if args.before or args.after:
            if not (args.before and args.after):
                print("error: --before and --after must be given together", file=sys.stderr)
                return 2
            change = changeset_from_zips(Path(args.before), Path(args.after), s.ingestion)
        else:
            base = args.base or ("main" if args.head else "HEAD")
            change = changeset_from_git(args.repo, base, args.head, args.staged, s.ingestion)
    except ChangeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    llm = build_llm(s)
    _print_data_notice(llm)
    agent_class = BugDetectionAgent if args.agent == "bug_detection" else CodeReviewAgent
    agent = agent_class(
        llm,
        settings=s,
        progress=lambda m: print(f"  {m}", file=sys.stderr),
        classifier=build_classifier(s),
    )
    try:
        result = review_change(agent, change)
    finally:
        change.cleanup()
    _print_llm_usage(llm, result)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else PROJECT_ROOT / "data" / "reports" / f"change-{stamp}"
    written = write_reports_timed(result, out, tuple(args.formats.split(",")))

    assert result.change is not None
    sm = result.change.summary
    print()
    print(
        f"Change {sm.base} -> {sm.head}: {sm.files_changed} file(s), "
        f"+{sm.lines_added}/-{sm.lines_deleted}"
    )
    if sm.narrative:
        print(f"  {sm.narrative}")
    if sm.impacted_files:
        print(f"  Unchanged files that call changed code: {', '.join(sm.impacted_files)}")
    print()
    print("Review these first:")
    for h in result.change.hunks[:5]:
        where = f"{h.file}:{h.start_line}-{h.end_line}"
        print(f"  [{h.level.upper():6} {h.score:5.1f}] {where}  {'; '.join(h.reasons)}")
    print()
    print(f"{len(result.findings)} finding(s):")
    for f in result.findings[:15]:
        fix = " [fix available]" if f.suggested_fix else ""
        print(f"  {f.id} {f.severity.value:8} {f.file}:{f.start_line}  {f.title}{fix}")
    for fmt, path in written.items():
        print(f"{fmt}: {path}")
    _print_timing(result)
    _print_partial(result)
    return _exit_code(result, args.fail_on)


def _apply_configuration(args: argparse.Namespace, s: Settings) -> Settings | None:
    """`--configuration A-D` sets review.mode and rag.enabled together (None on conflict)."""
    from marl_agents.evaluation.configurations import CONFIGURATIONS, apply_configuration

    key = getattr(args, "configuration", None)
    if not key:
        return s
    c = CONFIGURATIONS[key]
    if (args.mode and args.mode != c.mode) or (args.no_rag and c.rag):
        print(f"error: --configuration {key} conflicts with --mode/--no-rag", file=sys.stderr)
        return None
    return apply_configuration(s, key)


def _warn_mock(s: Settings, needs_llm: bool) -> None:
    if needs_llm and s.llm.provider == "mock":
        print(
            "note: LLM configurations use the offline mock provider: the run tests the pipeline "
            "only and is excluded from the comparison tables (use --config configs/gemini.yaml)",
            file=sys.stderr,
        )


def cmd_eval(args: argparse.Namespace) -> int:
    from marl_agents.evaluation.configurations import classify_settings
    from marl_agents.evaluation.recorder import RunRecorder
    from marl_agents.evaluation.runners import ablation
    from marl_agents.evaluation.runners import code_review as runner

    settings = _apply_configuration(args, build_settings(args))
    if settings is None:
        return 2
    s = settings
    # A benchmark measures real work: nothing is reused from an earlier run.
    s.review.unit_cache = s.review.analysis_cache = False
    apply_cache_choice(s, getattr(args, "reuse_llm_cache", False))
    if args.repeats is None:
        args.repeats = 1 if args.suite == "ablation" else 3
    if args.suite == "ablation":
        return _eval_ablation(args, s)
    if args.suite == "retrieval":
        from marl_agents.rag.embeddings import create_embedder

        embedders = {name: create_embedder(name) for name in args.embedders.split(",")}
        rec = RunRecorder(f"retrieval_{Path(args.path).name}", s)
        metrics = runner.run_retrieval(Path(args.path), embedders, seed=args.seed)
        out = rec.finish(
            metrics, runner.retrieval_summary_md(metrics, "RAG retrieval (call-graph relevance)")
        )
        print(runner.retrieval_summary_md(metrics, "RAG retrieval"))
        print(f"saved: {out}")
        return 0

    if args.suite == "summary":
        return _eval_summary()
    if args.suite == "clean-repos":
        return _eval_clean_repos(s)
    if args.suite in ("funnel", "classifier-metrics", "static-baseline", "ranker-saved-scores"):
        return _eval_report(args.suite)
    if args.suite == "classifier":
        return _eval_classifier(args, s)
    if args.suite == "classifier-ablation":
        return _eval_classifier_ablation(args, s)
    if args.suite == "before-after":
        return _eval_before_after()
    if args.suite == "timing":
        return _eval_timing(args, s)
    if args.suite == "agreement":
        return _eval_agreement(args)
    if args.suite == "usefulness":
        return _eval_usefulness(args, s)

    llm = build_llm(s)
    config = classify_settings(s)
    _warn_mock(s, config.llm)
    if args.suite == "planted":
        out = ablation.planted_once(s, llm)
        print((out / "summary.md").read_text(encoding="utf-8"))
        print(f"configuration: {config.label} (static {config.static}, LLM {config.llm}, "
              f"RAG {config.rag})")  # fmt: skip
        print(f"saved: {out}")
        return 0

    # CodeReviewer
    from marl_agents.evaluation.datasets import load_codereviewer

    samples = load_codereviewer(
        "cls" if args.suite == "hunkrisk" else args.task,
        args.split,
        limit=args.limit,
        seed=args.seed,
        languages={"py"},
        root=PROJECT_ROOT / s.datasets.root,
        cache_dir=PROJECT_ROOT / s.datasets.cache_dir,
    )
    print(
        f"loaded {len(samples)} samples (task={args.task}, split={args.split}, "
        f"python, seed={args.seed})"
    )
    if args.suite == "hunkrisk":
        return _eval_hunk_risk(args, s, samples)
    out = ablation.codereviewer_once(
        s,
        llm,
        samples,
        task=args.task,
        split=args.split,
        seed=args.seed,
        limit=args.limit,
        workers=args.workers,
        progress=print,
    )
    print((out / "summary.md").read_text(encoding="utf-8"))
    print(f"configuration: {config.label}")
    print(f"saved: {out}")
    return 0


def _eval_classifier(args: argparse.Namespace, s: Settings) -> int:
    from marl_agents.evaluation.runners.classifier_eval import run_classifier_evaluation

    if not args.model_dir:
        print("error: --model-dir <trained classifier folder> is required", file=sys.stderr)
        return 2
    out = run_classifier_evaluation(s, Path(args.model_dir), Path(args.data_dir))
    print((out / "summary.md").read_text(encoding="utf-8"))
    print(f"saved: {out}")
    return 0


def _eval_classifier_ablation(args: argparse.Namespace, s: Settings) -> int:
    """Classifier off, prioritizing and gating on identical dev samples. Never reads test."""
    import tempfile

    from marl_agents.evaluation.recorder import RunRecorder
    from marl_agents.evaluation.runners import classifier_ablation as ablation
    from marl_agents.llm.factory import create_provider

    if not args.model_dir:
        print("error: --model-dir <trained classifier folder> is required", file=sys.stderr)
        return 2
    limit = args.limit or ablation.DEFAULT_LIMIT
    data_dir = Path(args.data_dir)
    samples = ablation.dev_samples(s, data_dir, limit, args.seed)
    print(f"loaded {len(samples)} development samples (seed {args.seed})")
    done = ablation.load_previous(Path(args.resume)) if args.resume else None
    llm = create_provider(s.llm)
    _warn_mock(s, True)
    recorder = RunRecorder(f"classifier_ablation_valid_n{len(samples)}", s)
    with tempfile.TemporaryDirectory(prefix="marl_ablation_", ignore_cleanup_errors=True) as store:
        agents = ablation.build_agents(s, llm, Path(args.model_dir), Path(store))
        rows = ablation.run_ablation(agents, samples, recorder, done, args.max_llm_calls)
    metrics = {
        "benchmark": "classifier_ablation",
        "provider": llm.name,
        "model": llm.model,
        "seed": args.seed,
        "split": "dev (cls valid, dev projects only)",
        **ablation.compare(rows),
    }
    summary = ablation.summary_md(metrics)
    out = recorder.finish(
        metrics,
        summary,
        benchmark="classifier_ablation",
        dataset="CodeReviewer",
        task="cls",
        split="dev",
        languages=["py"],
        llm_provider=llm.name,
        llm_model=llm.model,
        sample_ids=[x.sample_id for x in samples],
    )
    ablation.write_outputs(out, rows)
    print(summary)
    print(f"saved: {out}")
    return 0


def _eval_clean_repos(s: Settings) -> int:
    """Part 3.10: configuration D on the three clean repositories, then the labelling sheet."""
    import json as _json

    from marl_agents.evaluation.runners import clean_repos as cr
    from marl_agents.llm.base import QuotaExhaustedError

    settings = cr.settings_for(s)
    llm = create_provider(settings.llm)
    rows: list[dict[str, object]] = []
    for repo in cr.REPOS:
        print(f"reviewing {repo.name} ({repo.package}) ...", flush=True)
        try:
            out = cr.review_repo(repo, settings, llm)
        except QuotaExhaustedError as exc:
            print(f"stopped: {exc}")
            return 1
        metrics = _json.loads((out / "metrics.json").read_text(encoding="utf-8"))
        print(f"  {metrics['findings']} findings, {metrics['per_kloc']} per 1,000 lines, "
              f"status {metrics['review_status']} -> {out.name}", flush=True)  # fmt: skip
        if not metrics["complete"]:
            print("stopped: the review is partial; repeat the command after fixing the cause")
            return 1
        with (out / "predictions.jsonl").open(encoding="utf-8") as fh:
            rows.extend({**_json.loads(line), "run": out.name} for line in fh)
    n = cr.export_sheet(rows)
    print(f"labelling sheet: {n} of {len(rows)} findings -> {cr.SHEET}")
    return 0


# The hunk-risk run cited in docs/results.md section 6a (line-ending fix applied).
HUNK_RISK_REFERENCE_RUN = "20261012T085812Z_hunkrisk_cls_test_n4196"


def _eval_report(kind: str) -> int:
    """Reports from saved runs only (no model call): funnel, classifier, static baseline."""
    import json as _json

    from marl_agents.evaluation import reanalysis
    from marl_agents.evaluation.funnel import funnel_report
    from marl_agents.evaluation.runs import load_runs

    runs = load_runs(PROJECT_ROOT / "experiments" / "results")
    data: object
    if kind == "funnel":
        md, data = funnel_report(runs)
    elif kind == "classifier-metrics":
        cls = [r for r in runs if r.name.split("_", 1)[-1].startswith("classifier_cls_test")]
        if not cls:
            print("error: no saved classifier test run", file=sys.stderr)
            return 1
        data = reanalysis.classifier_report(cls[-1])
        md = reanalysis.classifier_md(data)
    elif kind == "ranker-saved-scores":
        from marl_agents.evaluation.saved_score_ranking import compare_md, compare_saved_rankers

        by_name = {r.name: r for r in runs}
        hunk = by_name.get(HUNK_RISK_REFERENCE_RUN)
        cls = [r for r in runs if r.name.split("_", 1)[-1].startswith("classifier_cls_test")]
        if hunk is None or not cls:
            print("error: saved hunk-risk or classifier test run missing; nothing is re-run "
                  "(report TBD)", file=sys.stderr)  # fmt: skip
            return 1
        data = compare_saved_rankers(hunk, cls[-1])
        md = compare_md(data)
    else:
        full = [r for r in runs if r.kind == "codereviewer" and r.task == "cls"
                and r.split == "test" and r.configuration is not None
                and r.configuration.key == "static_only"
                and int(r.metrics.get("n_evaluated") or 0) >= 4000]  # fmt: skip
        if not full:
            print("error: no saved full static run on the CodeReviewer cls test split",
                  file=sys.stderr)  # fmt: skip
            return 1
        data = reanalysis.static_baseline_report(full[-1])
        md = reanalysis.static_baseline_md(data)
    out = PROJECT_ROOT / "experiments" / "evaluation_summary"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{kind}.md").write_text(md, encoding="utf-8")
    (out / f"{kind}.json").write_text(_json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(md)
    print(f"saved: {out / (kind + '.md')}")
    return 0


def _eval_before_after() -> int:
    from marl_agents.evaluation.comparison.before_after import before_after, before_after_md

    table = before_after(PROJECT_ROOT / "experiments" / "results")
    out = PROJECT_ROOT / "experiments" / "evaluation_summary"
    out.mkdir(parents=True, exist_ok=True)
    md = before_after_md(table)
    (out / "before_after.md").write_text(md, encoding="utf-8")
    (out / "before_after.json").write_text(table.model_dump_json(indent=2), encoding="utf-8")
    print(md)
    print(f"saved: {out}")
    return 0


CACHE_TTL_FOR_RESUME_HOURS = 720


def apply_cache_choice(s: Settings, reuse: bool) -> None:
    """Let a quota-stopped evaluation continue on a later day from cached LLM replies.

    Off by default, because a benchmark normally measures real work. When on, the run records it,
    its quality metrics stay comparable, and its times do not. Replies are kept for 30 days, longer
    than a free-tier comparison takes to finish.
    """
    if reuse:
        s.review.unit_cache = True
        s.review.cache_ttl_hours = max(s.review.cache_ttl_hours, CACHE_TTL_FOR_RESUME_HOURS)


def _eval_ablation(args: argparse.Namespace, s: Settings) -> int:
    """Configurations A-D on identical inputs; each run saved, plus one comparison record."""
    from marl_agents.evaluation.configurations import CONFIGURATIONS
    from marl_agents.evaluation.runners import ablation
    from marl_agents.llm.factory import create_provider

    keys = [k.strip() for k in args.configurations.split(",") if k.strip()]
    unknown = [k for k in keys if k not in CONFIGURATIONS]
    if unknown or not keys:
        print(f"error: unknown configuration(s) {unknown}; use {list(CONFIGURATIONS)}",
              file=sys.stderr)  # fmt: skip
        return 2
    needs_llm = any(CONFIGURATIONS[k].llm for k in keys)
    _warn_mock(s, needs_llm)
    llm = create_provider(s.llm) if needs_llm else None
    samples = None
    if args.benchmark == "codereviewer":
        from marl_agents.evaluation.datasets import load_codereviewer

        samples = load_codereviewer(
            args.task,
            args.split,
            limit=args.limit,
            seed=args.seed,
            languages={"py"},
            root=PROJECT_ROOT / s.datasets.root,
            cache_dir=PROJECT_ROOT / s.datasets.cache_dir,
        )
        print(f"loaded {len(samples)} samples (task={args.task}, split={args.split}, "
              f"python, seed={args.seed}); every configuration reviews exactly these")  # fmt: skip
    folder, _metrics = ablation.run_ablation(
        args.benchmark,
        s,
        llm,
        keys,
        repeats=args.repeats,
        samples=samples,
        task=args.task,
        split=args.split,
        seed=args.seed,
        limit=args.limit,
        workers=args.workers,
        llm_workers=args.llm_workers,
        fixes=args.with_fixes,
        progress=print,
    )
    print((folder / "summary.md").read_text(encoding="utf-8"))
    print(f"saved: {folder}")
    return 0


def _eval_summary() -> int:
    from marl_agents.evaluation.comparison import build_summary
    from marl_agents.evaluation.comparison import summary_md as comparison_md
    from marl_agents.evaluation.framework import collect_records, summary_md

    results = PROJECT_ROOT / "experiments" / "results"
    records = collect_records(results)
    comparison = build_summary(results)
    out = PROJECT_ROOT / "experiments" / "evaluation_summary"
    out.mkdir(parents=True, exist_ok=True)
    cmp_md = comparison_md(comparison)
    md = cmp_md + "\n---\n\n" + summary_md(records).replace("# ", "## Appendix: ", 1)
    (out / "summary.md").write_text(md, encoding="utf-8")
    (out / "comparison.md").write_text(cmp_md, encoding="utf-8")
    (out / "comparison.json").write_text(comparison.model_dump_json(indent=2), encoding="utf-8")
    (out / "records.json").write_text(
        json.dumps([r.model_dump() for r in records], indent=2), encoding="utf-8"
    )
    print(md)
    print(f"saved: {out}")
    return 0


def _eval_timing(args: argparse.Namespace, s: Settings) -> int:
    from marl_agents.evaluation.recorder import RunRecorder
    from marl_agents.evaluation.runners import timing as tm

    configs = [c.strip() for c in args.timing_configs.split(",") if c.strip()]
    unknown = [c for c in configs if c not in tm.CONFIGS]
    if unknown:
        print(f"error: unknown timing configuration(s): {unknown}", file=sys.stderr)
        return 2
    if args.timing_inputs:
        inputs = [
            tm.TimingInput(Path(p).stem or Path(p).name, Path(p).resolve())
            for p in args.timing_inputs.split(",")
        ]
    else:
        inputs = tm.default_inputs(PROJECT_ROOT)
    needs_llm = any(tm.CONFIGS[c]["mode"] != "static_only" for c in configs)
    llm = None
    if needs_llm:
        s.review.mode = "full"
        llm = build_llm(s)
        if llm is None or s.llm.provider == "mock":
            print(
                "note: LLM configurations use the mock provider (no network): the LLM column "
                "then measures pipeline overhead only, not real inference",
                file=sys.stderr,
            )
    rec = RunRecorder(f"timing_r{args.repeats}", s)
    metrics = tm.run_timing(
        s, llm, rec, inputs, configs, repeats=args.repeats, fixes=args.with_fixes, progress=print
    )
    md = tm.timing_summary_md(metrics, "Efficiency: time per review and per component")
    out = rec.finish(
        metrics,
        md,
        benchmark="timing",
        repeats=args.repeats,
        configs=configs,
        llm_provider=s.llm.provider if llm else None,
        llm_model=s.llm.model if llm else None,
    )
    print(md)
    print(f"saved: {out}")
    return 0


def _eval_hunk_risk(args: argparse.Namespace, s: Settings, samples: list[Any]) -> int:
    from marl_agents.agents.code_review import CodeReviewAgent
    from marl_agents.evaluation.recorder import RunRecorder
    from marl_agents.evaluation.runners import change_risk
    from marl_agents.static_analysis import (
        AstChecksAnalyzer,
        RadonAnalyzer,
        RuffAnalyzer,
        SecretsAnalyzer,
    )

    # Static only: the ranking must be cheap enough to run on every change (and free here).
    s.review.mode = "static_only"
    s.review.type_check = False
    s.review.suggest_fixes = False
    s.review.concurrency = 1
    s.rag.vector_store = "memory"
    analyzers = [RuffAnalyzer(), RadonAnalyzer(), AstChecksAnalyzer(), SecretsAnalyzer()]
    agent = CodeReviewAgent(None, settings=s, analyzers=analyzers, progress=lambda _m: None)
    rec = RunRecorder(f"hunkrisk_cls_{args.split}_n{len(samples)}", s)
    metrics = change_risk.run_hunk_risk(agent, samples, rec, workers=args.workers, progress=print)
    title = (
        f"Hunk-risk ranking vs. human review comments (CodeReviewer cls {args.split}, Python, "
        f"n={len(samples)}, seed={args.seed})"
    )
    md = change_risk.hunk_risk_summary_md(metrics, title)
    out = rec.finish(
        metrics,
        md,
        dataset="CodeReviewer",
        task="cls",
        split=args.split,
        seed=args.seed,
        limit=args.limit,
        languages=["py"],
        sample_ids=[x.sample_id for x in samples],
    )
    print(md)
    print(f"saved: {out}")
    return 0


def _eval_usefulness(args: argparse.Namespace, s: Settings) -> int:
    from marl_agents.evaluation.datasets import load_codereviewer
    from marl_agents.evaluation.recorder import RunRecorder
    from marl_agents.evaluation.runners import usefulness as uf
    from marl_agents.llm.base import Usage

    if not args.from_run:
        print("error: --from-run <experiments/results/...msg run> is required", file=sys.stderr)
        return 2
    run_dir = Path(args.from_run)
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    if meta.get("task") != "msg" or not meta.get("llm_model"):
        print("error: --from-run must be a CodeReviewer msg run made with an LLM", file=sys.stderr)
        return 2
    reviewer = meta["llm_model"]
    if args.judge_model:
        s.llm.model = args.judge_model
    if s.llm.model == reviewer:
        print(
            f"warning: the judge ({s.llm.model}) is the reviewer model; LLM judges favour their "
            "own outputs. Prefer --judge-model <another model>.",
            file=sys.stderr,
        )
    samples = load_codereviewer(
        "msg",
        meta["split"],
        languages={"py"},
        root=PROJECT_ROOT / s.datasets.root,
        cache_dir=PROJECT_ROOT / s.datasets.cache_dir,
        sample_ids=set(meta["sample_ids"]),
    )
    patches = {x.sample_id: x.patch for x in samples}
    items, no_comment = uf.items_from_run(run_dir, patches)
    if args.limit:
        keep = sorted({i.sample_id for i in items})[: args.limit]
        items = [i for i in items if i.sample_id in set(keep)]
    llm = build_llm(s)
    if llm is None or s.llm.provider == "mock":
        print("error: the usefulness judge needs a real LLM (set provider/model)", file=sys.stderr)
        return 2
    print(f"judging {len(items)} comments with {s.llm.provider}/{s.llm.model} ...")
    rec = RunRecorder(f"usefulness_{run_dir.name.split('_', 1)[-1]}", s)
    usage = Usage()
    scored, metrics = uf.run_usefulness(llm, items, rec, workers=args.workers, usage=usage)
    metrics["agent_no_comment"] = no_comment
    metrics["judge_usage"] = usage.snapshot()
    kit = uf.export_human_kit(scored, rec.dir / "human_kit", size=args.kit_size, seed=args.seed)
    title = f"Comment usefulness (LLM judge) for {run_dir.name}"
    md = uf.usefulness_summary_md(metrics, title, s.llm.model or "?", reviewer)
    out = rec.finish(
        metrics,
        md,
        source_run=run_dir.name,
        reviewer_model=reviewer,
        llm_provider=s.llm.provider,
        llm_model=s.llm.model,
        sample_ids=sorted({i.sample_id for i in items}),
    )
    print(md)
    print(f"human rating kit: {kit['sheet'].parent}")
    print(f"saved: {out}")
    return 0


def _eval_agreement(args: argparse.Namespace) -> int:
    from marl_agents.evaluation.runners import usefulness as uf

    if not (args.key and args.sheets):
        print("error: --key key.csv and --sheets a.csv[,b.csv] are required", file=sys.stderr)
        return 2
    sheets = [Path(p) for p in args.sheets.split(",")]
    metrics = uf.agreement_from_sheets(Path(args.key), sheets)
    md = uf.agreement_summary_md(metrics)
    out = Path(args.key).parent / "agreement.md"
    out.write_text(md, encoding="utf-8")
    (out.with_suffix(".json")).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(md)
    print(f"saved: {out}")
    return 0


def cmd_bugs(args: argparse.Namespace) -> int:
    """Find bugs in a repository, or locate a known failure from its test. Runs nothing."""
    from datetime import UTC, datetime

    from marl_agents.agents.bug_detection import BugDetectionAgent, FailingTestError
    from marl_agents.core.schemas import AgentRequest
    from marl_agents.ingestion import IngestionError
    from marl_agents.reports import write_reports_timed

    s = build_settings(args)
    if args.max_units:
        s.bugs.max_units = args.max_units
    llm = build_llm(s)
    _print_data_notice(llm)
    agent = BugDetectionAgent(llm, settings=s, progress=lambda m: print(f"  {m}", file=sys.stderr))
    target = Path(args.path)
    options: dict[str, Any] = {}
    if args.failing_test:
        options["failing_test"] = args.failing_test
    if args.traceback:
        options["error_text"] = Path(args.traceback).read_text(encoding="utf-8", errors="replace")
    if target.is_file() and target.suffix == ".py":
        code = target.read_text(encoding="utf-8", errors="replace")
        request = AgentRequest(snippet=code, snippet_filename=target.name, options=options)
    else:
        request = AgentRequest(repo_path=str(target), options=options)
    try:
        result = agent.run(request)
    except (FailingTestError, IngestionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print_llm_usage(llm, result)
    found = result.artifacts.get("localization")
    if found:
        print("Most likely locations:")
        if found.get("hypothesis"):
            print(f"  {found['hypothesis']}")
        for suspect in found["suspects"][:5]:
            print(
                f"  {suspect['rank']}. {suspect['file']}:{suspect['start_line']} "
                f"{suspect['symbol']}"
            )
        print()
    print(f"{len(result.findings)} finding(s):")
    for f in result.findings[:20]:
        kind = f.bug.bug_type.value if f.bug else f.category.value
        print(f"  {f.id} {f.severity.value:8} {kind:15} {f.file}:{f.start_line}  {f.title}")
    coverage = result.stats.get("scan_coverage")
    if coverage and coverage["units_selected"] < coverage["units_total"]:
        print(
            f"\nThe LLM read {coverage['units_selected']} of {coverage['units_total']} parts; "
            "raise --max-units to read more."
        )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else PROJECT_ROOT / "data" / "reports" / f"bugs-{stamp}"
    for fmt, path in write_reports_timed(result, out, tuple(args.formats.split(","))).items():
        print(f"{fmt}: {path}")
    _print_timing(result)
    _print_partial(result)
    return _exit_code(result, args.fail_on)


def cmd_eval_bugs(args: argparse.Namespace) -> int:
    """Bug Detection Agent on BugsInPy. The test split needs --final."""
    from marl_agents.evaluation.runners import bug_detection as runner

    s = build_settings(args)
    if args.split == "test" and not args.final:
        print(
            "error: the test split is for final numbers. Freeze prompts on dev, then pass --final.",
            file=sys.stderr,
        )
        return 2
    if args.task == "audit":
        out = runner.run_audit(s, args.split, args.seed, args.limit, progress=print)
        print((out / "summary.md").read_text(encoding="utf-8"))
        print(f"saved: {out}")
        return 0
    if args.task == "labels":
        default = PROJECT_ROOT / "experiments" / "bug_type_labels" / f"sheet_{args.split}.csv"
        sheet = Path(args.out) if args.out else default
        written = runner.write_label_sheet(s, args.split, args.seed, args.limit or 10, sheet)
        print(f"saved: {written}")
        return 0
    configurations = args.configurations.split(",")
    unknown = [c for c in configurations if c not in runner.DEFAULT_CONFIGURATIONS]
    if unknown:
        print(f"error: unknown configuration(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    options = runner.BugEvalOptions(
        task=args.task,
        split=args.split,
        limit=args.limit or 10,
        seed=args.seed,
        configurations=configurations,
        max_llm_calls=args.max_llm_calls,
        bug_type_files=[Path(p) for p in args.bug_types.split(",")] if args.bug_types else [],
    )
    needs_llm = configurations != ["static_only"]
    _warn_mock(s, needs_llm)
    llm = build_llm(s) if needs_llm else None
    _print_data_notice(llm)
    for path in runner.run_bug_evaluation(options, s, llm, progress=print):
        print((path / "summary.md").read_text(encoding="utf-8"))
        print(f"saved: {path}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    """List models available to the configured key, and recommend a free Gemini model."""
    s = build_settings(args)
    if s.llm.provider not in {"openai", "groq", "gemini", "local", "ollama"}:
        print(
            f"'models' works with gemini/ollama/openai/groq/local providers, not {s.llm.provider!r}"
        )
        return 2
    s.llm.model = s.llm.model or "unused"
    provider = create_provider(s.llm)
    models = provider.list_models()  # type: ignore[attr-defined]
    for model_id in models:
        print(model_id)
    if s.llm.provider == "gemini":
        from marl_agents.llm.gemini import recommend_model

        best = recommend_model(models)
        print(f"recommended free-tier model for this key: {best or 'none of the known ones'}")
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    """Calls, tokens and cost of the pending Groq experiments. Makes no API call."""
    from marl_agents.evaluation.estimate import estimate, estimate_md, pending_plan

    s = build_settings(args)
    report = estimate(s.llm, pending_plan(bugs=args.bugs, runs=args.runs))
    md = estimate_md(report)
    out = PROJECT_ROOT / "experiments" / "evaluation_summary"
    out.mkdir(parents=True, exist_ok=True)
    (out / "groq-estimate.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """One tiny JSON request: verifies key, model, JSON mode and parsing end to end."""
    from pydantic import BaseModel

    from marl_agents.llm.base import Message

    class Ping(BaseModel):
        status: str

    s = build_settings(args)
    s.llm.response_cache = False  # a cached reply would not prove the key works
    try:
        llm = create_provider(s.llm)
        if s.llm.provider == "gemini":
            from marl_agents.llm.gemini import recommend_model

            models = llm.list_models()  # type: ignore[attr-defined]
            if s.llm.model not in models:
                best = recommend_model(models)
                hint = f"Set GEMINI_MODEL={best} in .env." if best else "See `cli models`."
                print(f"FAILED: model {s.llm.model} is not available to this key. {hint}")
                return 1
        if s.llm.provider == "ollama":
            llm.ensure_model()  # type: ignore[attr-defined]
        reply = llm.generate_structured(
            [
                Message(role="system", content="Reply with a JSON object only."),
                Message(role="user", content='Return exactly this JSON: {"status": "ok"}'),
            ],
            Ping,
        )
    except LLMError as exc:
        print(f"FAILED: {exc}")
        return 1
    print(
        f"OK: provider={llm.name} model={llm.model} reply={reply.status!r} "
        f"tokens={llm.usage.input_tokens}+{llm.usage.output_tokens}"
    )
    budget = getattr(llm, "budget", None)
    if budget is not None:  # cumulative usage and caps; never the key itself
        print("usage so far: " + ", ".join(f"{k}={v}" for k, v in budget.status().items()))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the API and the dashboard (frontend/dist) with uvicorn."""
    try:
        import uvicorn
    except ImportError:
        print("Install the api extra first: pip install -e '.[api]'")
        return 2
    from marl_agents.api import create_app

    s = build_settings(args)
    app = create_app(settings=s)
    dist = PROJECT_ROOT / "frontend" / "dist" / "index.html"
    print(
        f"Dashboard: http://{args.host}:{args.port}   API docs: http://{args.host}:{args.port}/docs"
    )
    if not dist.is_file():
        print("note: dashboard not built yet -> cd frontend && npm install && npm run build")
    llm = (
        "static analysis only (no LLM)"
        if s.llm.provider == "mock"
        else f"{s.llm.provider} / {s.llm.model}"
    )
    print(f"LLM: {llm}")
    if s.llm.provider == "gemini":
        print(GEMINI_DATA_NOTICE)
    uvicorn.run(
        app, host=args.host, port=args.port, log_level="info" if args.verbose else "warning"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252; LLM output often contains Unicode (e.g. non-breaking
    # hyphens), which would crash print(). Never fail on output encoding.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="marl_agents", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_review = sub.add_parser("review", help="review a directory, ZIP or .py file")
    p_review.add_argument("target")
    p_review.add_argument("--out")
    p_review.add_argument("--formats", default="json,md,pdf")
    p_review.add_argument(
        "--orchestrated",
        action="store_true",
        help="run Code Review and Bug Detection in parallel (LangGraph) and aggregate the results",
    )
    _add_common(p_review)
    p_review.add_argument(
        "--fail-on",
        choices=["none", *SEVERITY_ORDER],
        default="none",
        help="exit with code 1 if a finding at or above this severity exists",
    )
    p_review.set_defaults(func=cmd_review)

    p_change = sub.add_parser(
        "review-change",
        help="review a code change: git branches/commits, uncommitted or staged work, or two ZIPs",
    )
    p_change.add_argument("repo", nargs="?", default=".", help="git repository (default: .)")
    p_change.add_argument("--base", help="base branch/commit (default: HEAD, or main with --head)")
    p_change.add_argument("--head", help="head branch/commit (default: the working tree)")
    p_change.add_argument(
        "--staged", action="store_true", help="review staged changes (pre-commit)"
    )
    p_change.add_argument("--before", help="ZIP of the old version (instead of git)")
    p_change.add_argument("--after", help="ZIP of the new version (instead of git)")
    p_change.add_argument("--out")
    p_change.add_argument(
        "--formats", default="json,md,pdf", help="any of json,md,pdf,sarif (comma separated)"
    )
    p_change.add_argument(
        "--fail-on",
        choices=["none", *SEVERITY_ORDER],
        default="none",
        help="exit with code 1 if a finding at or above this severity exists",
    )
    _add_common(p_change)
    p_change.set_defaults(func=cmd_review_change)

    p_eval = sub.add_parser("eval", help="run an evaluation suite")
    p_eval.add_argument(
        "suite",
        choices=[
            "codereviewer",
            "planted",
            "retrieval",
            "hunkrisk",
            "timing",
            "summary",
            "usefulness",
            "agreement",
            "ablation",
            "classifier",
            "classifier-ablation",
            "before-after",
            "funnel",
            "classifier-metrics",
            "static-baseline",
            "ranker-saved-scores",
            "clean-repos",
        ],
        help="hunkrisk: risk ranking vs CodeReviewer cls labels; timing: efficiency benchmark "
        "(time per review and per component); summary: baseline comparison + five-component "
        "tables from saved runs; usefulness / agreement: LLM-judge and human ratings of comments; "
        "ablation: configurations A-D on identical inputs (--benchmark planted|codereviewer)",
    )
    p_eval.add_argument(
        "--configuration",
        choices=["static_only", "llm_only", "static_llm", "static_llm_rag"],
        help="experiment configuration: A static_only | B llm_only (no static, no RAG) | "
        "C static_llm (no RAG) | D static_llm_rag (the full agent); sets mode and RAG together",
    )
    p_eval.add_argument(
        "--configurations",
        default="static_only,llm_only,static_llm,static_llm_rag",
        help="ablation: configurations to run, comma separated",
    )
    p_eval.add_argument(
        "--benchmark",
        choices=["planted", "codereviewer"],
        default="planted",
        help="ablation: which benchmark (codereviewer uses --task/--limit/--seed)",
    )
    p_eval.add_argument(
        "--llm-workers",
        type=int,
        default=1,
        help="ablation: parallel samples for LLM configurations (static ones use --workers)",
    )
    p_eval.add_argument("--task", choices=["cls", "msg"], default="cls")
    p_eval.add_argument("--split", default="test")
    p_eval.add_argument("--limit", type=int)
    p_eval.add_argument("--seed", type=int, default=42)
    p_eval.add_argument("--workers", type=int, default=8)
    p_eval.add_argument("--path", default="src", help="repository for the retrieval benchmark")
    p_eval.add_argument("--embedders", default="hashing")
    p_eval.add_argument("--from-run", help="usefulness: the CodeReviewer msg run to judge")
    p_eval.add_argument("--judge-model", help="usefulness: judge model (use a different model)")
    p_eval.add_argument(
        "--repeats",
        type=int,
        default=None,
        help="timing: runs per configuration (default 3); ablation: repeats (default 1)",
    )
    p_eval.add_argument(
        "--timing-configs",
        default="static_only,llm_only,llm_no_rag,llm_rag",
        help="timing: any of static_only (A), llm_only (B), llm_no_rag (C), llm_rag (D)",
    )
    p_eval.add_argument(
        "--timing-inputs", help="timing: comma-separated paths (default: planted repo + example)"
    )
    p_eval.add_argument(
        "--with-fixes", action="store_true", help="timing / ablation: keep LLM fix suggestions"
    )
    p_eval.add_argument(
        "--reuse-llm-cache",
        action="store_true",
        help="codereviewer / ablation: reuse LLM replies cached by earlier runs, so a run stopped "
        "by the quota can continue on a later day. Quality metrics stay comparable; times do not",
    )
    p_eval.add_argument("--kit-size", type=int, default=40, help="usefulness: diffs in the kit")
    p_eval.add_argument("--model-dir", help="classifier: the trained model folder")
    p_eval.add_argument(
        "--max-llm-calls", type=int, help="classifier-ablation: stop between samples at this many"
    )
    p_eval.add_argument("--resume", help="classifier-ablation: earlier run folder to continue")
    p_eval.add_argument(
        "--data-dir",
        default=str(PROJECT_ROOT / "data" / "classifier" / "py"),
        help="classifier: folder written by marl_agents.training.prepare",
    )
    p_eval.add_argument("--key", help="agreement: key.csv from the human rating kit")
    p_eval.add_argument("--sheets", help="agreement: rated sheet(s), comma separated")
    _add_common(p_eval)
    p_eval.set_defaults(func=cmd_eval)

    p_change.add_argument(
        "--agent", choices=["code_review", "bug_detection"], default="code_review"
    )

    p_bugs = sub.add_parser("bugs", help="find bugs, or locate a known failure from its test")
    p_bugs.add_argument("path", help="directory, ZIP or .py file")
    p_bugs.add_argument("--failing-test", help="e.g. tests/test_x.py::test_y")
    p_bugs.add_argument("--traceback", help="file holding the error output of that test")
    p_bugs.add_argument("--max-units", type=int, help="most LLM requests for a scan")
    p_bugs.add_argument("--out", help="report folder")
    p_bugs.add_argument("--formats", default="json,md,pdf,sarif")
    p_bugs.add_argument("--fail-on", choices=["none", *SEVERITY_ORDER], default="none")
    _add_common(p_bugs)
    p_bugs.set_defaults(func=cmd_bugs)

    p_eval_bugs = sub.add_parser("eval-bugs", help="Bug Detection Agent on BugsInPy")
    p_eval_bugs.add_argument(
        "task",
        choices=["audit", "localization", "detection", "labels"],
        help="audit: which bugs are usable (no LLM); localization / detection: the two tracks; "
        "labels: write a blank bug-type sheet",
    )
    p_eval_bugs.add_argument("--split", choices=["dev", "test"], default="dev")
    p_eval_bugs.add_argument("--limit", type=int, help="bugs (default 10; audit: all)")
    p_eval_bugs.add_argument("--seed", type=int, default=42)
    p_eval_bugs.add_argument(
        "--configurations", default="static_only,llm_only,static_llm,static_llm_rag"
    )
    p_eval_bugs.add_argument("--max-llm-calls", type=int, help="stop between bugs at this many")
    p_eval_bugs.add_argument("--final", action="store_true", help="allow the test split")
    p_eval_bugs.add_argument("--bug-types", help="two filled label sheets, comma separated")
    p_eval_bugs.add_argument("--out", help="labels: where to write the sheet")
    _add_common(p_eval_bugs)
    p_eval_bugs.set_defaults(func=cmd_eval_bugs)

    p_models = sub.add_parser("models", help="list LLM models available to your API key")
    _add_common(p_models)
    p_models.set_defaults(func=cmd_models)

    p_est = sub.add_parser("estimate", help="calls, tokens and cost of the pending Groq runs")
    _add_common(p_est)
    p_est.add_argument("--bugs", type=int, default=40, help="BugsInPy bugs (dev + test)")
    p_est.add_argument("--runs", type=int, default=3, help="runs per LLM configuration")
    p_est.set_defaults(func=cmd_estimate)
    p_check = sub.add_parser("check", help="verify the LLM key/model with one tiny request")
    _add_common(p_check)
    p_check.set_defaults(func=cmd_check)

    p_serve = sub.add_parser("serve", help="start the dashboard + API (http://127.0.0.1:8000)")
    p_serve.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow other machines")
    p_serve.add_argument("--port", type=int, default=8000)
    _add_common(p_serve)
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(args.func(args))
    except LLMError as exc:
        print(f"LLM error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
