"""Evaluation runners for the Code Review Agent.

1. CodeReviewer ``cls`` (diff quality estimation): does the agent flag diffs that reviewers
   commented on?
2. CodeReviewer ``msg`` (comment generation): similarity of the agent's top finding to the
   human comment.
3. Planted-issue benchmark: recall / precision / localization against a hand-labelled fixture repo.
4. RAG retrieval benchmark: can the retriever find a function's callees (call-graph relevance)?

Per-sample reconstruction for CodeReviewer: the new file is rebuilt by applying the hunk to ``oldf``
and the agent reviews only the changed lines (PR-review mode).
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from marl_agents.agents.code_review.agent import CodeReviewAgent
from marl_agents.config import Settings
from marl_agents.core.schemas import AgentRequest, Finding, ReviewResult, Severity
from marl_agents.core.timing import TimingBreakdown, describe
from marl_agents.evaluation.datasets.codereviewer import CodeReviewerSample
from marl_agents.evaluation.funnel import FUNNEL_KEYS, funnel_counts
from marl_agents.evaluation.metrics import (
    ExpectedIssue,
    binary_metrics,
    bootstrap_ci,
    chrf,
    corpus_bleu_avg,
    detection_metrics,
    hit_at_k,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    roc_auc,
    rouge_l,
    sentence_bleu,
)
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.stats import wilson
from marl_agents.findings.confidence import priority
from marl_agents.ingestion import load_repository
from marl_agents.ingestion.diff import PatchError, apply_patch, changed_new_lines
from marl_agents.llm.base import LLMProvider
from marl_agents.llm.classifier import create_classifier
from marl_agents.parsing.python_ast import SymbolKind
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.rag.chunking import Chunk, chunk_repository
from marl_agents.rag.embeddings import Embedder

logger = logging.getLogger(__name__)

CHANGED_FILE = "changed_file.py"
SEVERITY_THRESHOLDS = ["info", "low", "medium", "high", "critical"]


# ---------------------------------------------------------------------------------------------
# CodeReviewer
# ---------------------------------------------------------------------------------------------


def review_patch(
    agent: CodeReviewAgent, oldf: str, patch: str
) -> tuple[ReviewResult, list[tuple[int, int]]]:
    """Rebuild the new file from `oldf` + `patch` and review only the changed lines."""
    new_file = apply_patch(oldf, patch)
    ranges = changed_new_lines(patch)
    if not ranges:
        raise PatchError("patch has no changed lines")
    request = AgentRequest(
        snippet=new_file,
        snippet_filename=CHANGED_FILE,
        options={
            "changed_lines": {CHANGED_FILE: ranges},
            "include_tests": True,
            "patches": {CHANGED_FILE: patch},
        },
    )
    return agent.run(request), ranges


def finding_score(findings: list[Finding]) -> float:
    """Sample-level 'needs review' score in [0, 1): the best finding's priority / 5."""
    return max((priority(f) for f in findings), default=0.0) / 5.0


def predict_needs_review(findings: list[Finding], min_severity: str = "low") -> int:
    rank = Severity(min_severity).rank
    return int(any(f.severity.rank >= rank for f in findings))


def compose_comment(findings: list[Finding], variant: str) -> str:
    """Turn the top finding into a single review comment (variants are compared in the report)."""
    ranked = sorted(findings, key=priority, reverse=True)
    if not ranked:
        return ""
    top = ranked[0]
    title = top.title.split(": ", 1)[1] if top.rule_id and ": " in top.title else top.title
    if variant == "title":
        return title
    if variant == "title_fix":
        return f"{title}. {top.recommendation or ''}".strip()
    if variant == "description":
        return top.description.split("\nRelated:")[0]
    if variant == "full":  # what a developer sees: used by the usefulness judge, not by BLEU
        description = top.description.split("\nRelated:")[0]
        # tool findings often repeat the title as the description: say it once
        parts = [title] + ([description] if description.strip() != title.strip() else [])
        if top.recommendation:
            parts.append(f"Suggestion: {top.recommendation}")
        return "\n".join(p for p in parts if p)
    raise ValueError(variant)


# Rules whose verdict depends on code outside a single hunk (see run_codereviewer).
CROSS_HUNK_RULES = frozenset({"F821", "F401", "F811", "F403", "F405"})


def _cls_metrics(y_true: list[int], findings_lists: list[list[Finding]]) -> dict[str, Any]:
    scores = [finding_score(fs) for fs in findings_lists]
    sweep = {}
    for thr in SEVERITY_THRESHOLDS:
        preds = [predict_needs_review(fs, thr) for fs in findings_lists]
        sweep[thr] = binary_metrics(y_true, preds).model_dump()
    default = [predict_needs_review(fs, "low") for fs in findings_lists]
    pairs = list(zip(y_true, default, strict=True))

    def stat(name: str) -> Callable[[list[tuple[int, int]]], float]:
        return lambda s: float(getattr(binary_metrics([a for a, _ in s], [b for _, b in s]), name))

    n = max(len(y_true), 1)
    return {
        "label_balance": {"positive": sum(y_true), "negative": len(y_true) - sum(y_true)},
        "threshold_sweep": sweep,
        "default_threshold": "low",
        "default": sweep["low"],
        "f1_ci95": bootstrap_ci(pairs, stat("f1")),
        "accuracy_ci95": bootstrap_ci(pairs, stat("accuracy")),
        "precision_ci95": bootstrap_ci(pairs, stat("precision")),
        "roc_auc": roc_auc(y_true, scores),
        "baselines": {
            "majority_class_accuracy": max(sum(y_true), len(y_true) - sum(y_true)) / n,
            "always_positive": binary_metrics(y_true, [1] * len(y_true)).model_dump(),
        },
    }


def _msg_metrics(refs: list[str], findings_lists: list[list[Finding]]) -> dict[str, Any]:
    """Comment-generation metrics over the evaluated samples.

    Coverage (the same definition in every configuration and table): the number of samples for
    which the configuration produced a comment, i.e. its top-ranked in-scope finding exists, so
    the composed comment is not empty, divided by the number of evaluated samples. It is
    reported as a count (x/n) and a fraction. Empty comments score 0 on BLEU-4, ROUGE-L, chrF.
    """
    n = max(len(refs), 1)
    variants = ("title", "title_fix", "description")
    comments = {v: [compose_comment(fs, v) for fs in findings_lists] for v in variants}

    def mean100(fn: Callable[[str, str], float], hyps: list[str]) -> float:
        return round(100 * sum(fn(a, b) for a, b in zip(refs, hyps, strict=True)) / n, 3)

    text_metrics = {
        variant: {
            "bleu4_smoothed": round(corpus_bleu_avg(refs, hyps), 3),
            "rouge_l": mean100(rouge_l, hyps),
            "chrf": mean100(chrf, hyps),
        }
        for variant, hyps in comments.items()
    }
    hyps = comments["title_fix"]
    return {
        "comment_coverage": sum(1 for h in hyps if h) / n,
        "text_metrics": text_metrics,
        "bleu4_ci95_title_fix": bootstrap_ci(
            list(zip(refs, hyps, strict=True)),
            lambda s: 100 * sum(sentence_bleu(a, b) for a, b in s) / len(s),
        ),
        "hit_rate_non_info": sum(predict_needs_review(fs, "low") for fs in findings_lists) / n,
    }


def _compact(findings: list[Finding]) -> list[dict[str, Any]]:
    return [
        {
            "severity": f.severity.value,
            "category": f.category.value,
            "confidence": f.confidence,
            "rule": f.rule_id,
            "sources": [s.value for s in f.sources],
            "lines": [f.start_line, f.end_line],
            "title": f.title,
        }
        for f in findings
    ]


def _review_sample(agent: CodeReviewAgent, sample: CodeReviewerSample) -> dict[str, Any]:
    try:
        result, ranges = review_patch(agent, sample.oldf, sample.patch)
    except PatchError as exc:
        return {"sample_id": sample.sample_id, "error": f"patch: {exc}"}
    except Exception as exc:
        return {"sample_id": sample.sample_id, "error": f"{type(exc).__name__}: {exc}"}
    failed_units = int(result.stats.get("units_failed", 0) or 0)
    if failed_units and agent.llm is not None and agent.settings.review.mode != "static_only":
        # The LLM did not review this sample (quota, timeout, unparseable reply): scoring it on
        # static findings alone would silently mix configurations. Count it as a failure instead.
        first = next((e for e in result.errors if e), "")
        return {
            "sample_id": sample.sample_id,
            "error": f"llm: {failed_units} review unit(s) failed: {first[:200]}",
        }
    return {
        "sample_id": sample.sample_id,
        "label": sample.label,
        "reference": sample.msg,
        "changed": ranges,
        "findings": result.findings,
        "llm_rejected": result.stats.get("llm_rejected_by_reason", {}),
        "funnel": {
            k: result.stats[k]
            for k in (*FUNNEL_KEYS, "llm_rejected_by_reason")
            if k in result.stats
        },
        "errors": result.errors,
        "timing": timing_summary(result),
        "llm_usage": result.stats.get("llm_usage"),
    }


TIMING_FIELDS = (
    "total_sec",
    "static_analysis_sec",
    "rag_sec",
    "llm_inference_sec",
    "validation_sec",
    "other_sec",
    "llm_rate_limit_wait_sec",
)


def timing_summary(result: ReviewResult) -> dict[str, Any]:
    """Per-sample timing without spans (kept small for predictions.jsonl)."""
    raw = result.stats.get("timing")
    return TimingBreakdown.model_validate(raw).summary() if isinstance(raw, dict) else {}


def timing_distribution(rows: list[dict[str, Any]], workers: int) -> dict[str, Any]:
    """Mean / median / min / max of each timing component over benchmark samples."""
    timings = [r["timing"] for r in rows if r.get("timing")]
    out: dict[str, Any] = {
        f: describe(t.get(f) for t in timings).model_dump() for f in TIMING_FIELDS
    }
    out["conditions"] = {
        "samples": len(timings),
        "workers": workers,
        "note": "per-sample review time; samples ran concurrently on `workers` workers",
    }
    return out


# Process-pool workers: static analysis is CPU-bound Python, so threads are limited by the GIL.
_WORKER_AGENT: CodeReviewAgent | None = None


def _init_worker(settings_json: str, analyzer_names: list[str]) -> None:
    global _WORKER_AGENT
    from marl_agents.config import Settings
    from marl_agents.static_analysis import (
        AstChecksAnalyzer,
        RadonAnalyzer,
        RuffAnalyzer,
        SecretsAnalyzer,
        TestGapAnalyzer,
    )

    classes = (RuffAnalyzer, RadonAnalyzer, AstChecksAnalyzer, SecretsAnalyzer, TestGapAnalyzer)
    registry = {cls.name: cls for cls in classes}
    _WORKER_AGENT = CodeReviewAgent(
        None,
        settings=Settings.model_validate_json(settings_json),
        analyzers=[registry[n]() for n in analyzer_names],
        progress=lambda _m: None,
    )


def _process_one(sample: CodeReviewerSample) -> dict[str, Any]:
    assert _WORKER_AGENT is not None
    return _review_sample(_WORKER_AGENT, sample)


def llm_work(rows: list[dict[str, Any]]) -> dict[str, float] | None:
    """Mean LLM calls, tokens and total time per sample; None for a run without an LLM."""
    usage = [r["llm_usage"] for r in rows if r.get("llm_usage")]
    if not usage:
        return None
    n = len(usage)
    totals = [r["timing"]["total_sec"] for r in rows if r.get("timing", {}).get("total_sec")]
    return {
        "mean_calls": round(sum(u["calls"] for u in usage) / n, 3),
        "mean_input_tokens": round(sum(u["input_tokens"] for u in usage) / n, 1),
        "mean_output_tokens": round(sum(u["output_tokens"] for u in usage) / n, 1),
        "mean_total_sec": round(sum(totals) / len(totals), 3) if totals else 0.0,
    }


def run_codereviewer(
    agent: CodeReviewAgent,
    samples: list[CodeReviewerSample],
    recorder: RunRecorder,
    workers: int = 8,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the agent over CodeReviewer samples and compute task metrics.

    Static-only runs use a process pool (CPU-bound); runs with an LLM use threads (I/O-bound).
    """
    progress = progress or (lambda m: logger.info(m))
    task = samples[0].task if samples else "cls"
    t0 = time.perf_counter()
    use_processes = agent.settings.review.mode == "static_only" and workers > 1

    rows: list[dict[str, Any]] = []
    pool: ProcessPoolExecutor | ThreadPoolExecutor
    if use_processes:
        pool = ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(agent.settings.model_dump_json(), [a.name for a in agent.analyzers]),
        )
        results = pool.map(_process_one, samples, chunksize=8)
    else:
        pool = ThreadPoolExecutor(max_workers=max(1, workers))
        results = pool.map(lambda s: _review_sample(agent, s), samples)
    with pool:
        for i, row in enumerate(results, start=1):
            rows.append(row)
            if i % 250 == 0 or i == len(samples):
                progress(f"{i}/{len(samples)} samples ({time.perf_counter() - t0:.0f}s)")

    ok = [r for r in rows if "error" not in r]
    for r in rows:
        if "error" in r:
            recorder.error(r["sample_id"], r["error"])
    y_true = [r["label"] for r in ok]
    scores = [finding_score(r["findings"]) for r in ok]
    comments = {
        v: [compose_comment(r["findings"], v) for r in ok]
        for v in ("title", "title_fix", "description")
    }
    for idx, r in enumerate(ok):
        recorder.prediction(
            {
                "sample_id": r["sample_id"],
                "label": r["label"],
                "score": scores[idx],
                "pred_low": predict_needs_review(r["findings"], "low"),
                "changed": r["changed"],
                "findings": _compact(r["findings"]),
                "comment": comments["title_fix"][idx],
                "comment_full": compose_comment(r["findings"], "full"),
                "reference": r["reference"],
                "timing": r.get("timing", {}),
            }
        )

    metrics: dict[str, Any] = {
        "task": task,
        "n_samples": len(samples),
        "n_evaluated": len(ok),
        "n_failed": len(rows) - len(ok),
        "failure_reasons": dict(Counter(r["error"].split(":")[0] for r in rows if "error" in r)),
        "seconds": round(time.perf_counter() - t0, 1),
        "findings_per_sample": round(sum(len(r["findings"]) for r in ok) / max(len(ok), 1), 3),
        "timing": timing_distribution(ok, workers),
        "finding_categories": dict(Counter(f.category.value for r in ok for f in r["findings"])),
        "finding_rules_top20": dict(
            Counter(f.rule_id or "llm" for r in ok for f in r["findings"]).most_common(20)
        ),
    }

    metrics["llm_work"] = llm_work(ok)
    if any(r.get("funnel") for r in ok):
        metrics["llm_funnel"] = funnel_counts(r.get("funnel") or {} for r in ok)
    findings_lists = [r["findings"] for r in ok]
    if task == "cls":
        metrics.update(_cls_metrics(y_true, findings_lists))
    else:
        metrics.update(_msg_metrics([r["reference"] for r in ok], findings_lists))
    # Sensitivity analysis: CodeReviewer samples are ONE hunk of a larger commit, so rules that
    # need the rest of the change (imports added in another hunk, names defined elsewhere) fire
    # spuriously. Recompute with those rules removed; both numbers are always reported.
    filtered = [[f for f in fs if f.rule_id not in CROSS_HUNK_RULES] for fs in findings_lists]
    sensitivity: dict[str, Any] = {"excluded_rules": sorted(CROSS_HUNK_RULES)}
    if task == "cls":
        sensitivity.update(_cls_metrics(y_true, filtered))
    else:
        sensitivity.update(_msg_metrics([r["reference"] for r in ok], filtered))
    metrics["sensitivity_without_cross_hunk_rules"] = sensitivity
    return metrics


def _cls_block(m: dict[str, Any]) -> list[str]:
    d = m["default"]
    auc = m["roc_auc"]
    lines = [
        "| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for thr, s in m["threshold_sweep"].items():
        lines.append(
            f"| {thr} | {s['accuracy']:.3f} | {s['precision']:.3f} | {s['recall']:.3f} "
            f"| {s['f1']:.3f} | {s['positive_rate']:.3f} |"
        )
    lines += [
        "",
        f"- Threshold `low`: accuracy {d['accuracy']:.3f} "
        f"(95% CI {m['accuracy_ci95'][0]:.3f}-{m['accuracy_ci95'][1]:.3f}), precision "
        f"{d['precision']:.3f} (95% CI {m['precision_ci95'][0]:.3f}-{m['precision_ci95'][1]:.3f}), "
        f"F1 {d['f1']:.3f} (95% CI {m['f1_ci95'][0]:.3f}-{m['f1_ci95'][1]:.3f})",
        f"- ROC-AUC of the finding score: {auc:.3f}" if auc is not None else "- ROC-AUC: n/a",
        f"- Baselines: majority-class accuracy {m['baselines']['majority_class_accuracy']:.3f}; "
        f"always-positive F1 {m['baselines']['always_positive']['f1']:.3f}",
    ]
    return lines


def cls_summary_md(metrics: dict[str, Any], title: str) -> str:
    sens = metrics["sensitivity_without_cross_hunk_rules"]
    lines = [
        f"# {title}",
        "",
        f"n = {metrics['n_evaluated']} evaluated ({metrics['n_failed']} failed: "
        f"{metrics['failure_reasons']}), labels = {metrics['label_balance']}. "
        f"Findings per sample: {metrics['findings_per_sample']}; runtime {metrics['seconds']} s.",
        "",
        "## All rules",
        "",
        *_cls_block(metrics),
        "",
        "## Sensitivity: without cross-hunk rules " + ", ".join(sens["excluded_rules"]),
        "",
        "Each sample is one hunk of a larger commit, so these rules fire on imports/names that",
        "live in other hunks. Both analyses are reported; neither replaces the other.",
        "",
        *_cls_block(sens),
        "",
    ]
    return "\n".join(lines)


def _msg_block(m: dict[str, Any]) -> list[str]:
    lines = [
        f"Comment coverage (a comment was produced): {m['comment_coverage']:.3f}",
        "",
        "| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |",
        "|---|---:|---:|---:|",
    ]
    for variant, s in m["text_metrics"].items():
        lines.append(
            f"| {variant} | {s['bleu4_smoothed']:.2f} | {s['rouge_l']:.2f} | {s['chrf']:.2f} |"
        )
    lo, hi = m["bleu4_ci95_title_fix"]
    lines += ["", f"- BLEU-4 (title_fix) 95% CI: {lo:.2f}-{hi:.2f}"]
    return lines


def msg_summary_md(metrics: dict[str, Any], title: str) -> str:
    sens = metrics["sensitivity_without_cross_hunk_rules"]
    return "\n".join(
        [
            f"# {title}",
            "",
            f"n = {metrics['n_evaluated']} evaluated ({metrics['n_failed']} failed: "
            f"{metrics['failure_reasons']}). Runtime {metrics['seconds']} s.",
            "",
            "## All rules",
            "",
            *_msg_block(metrics),
            "",
            "## Sensitivity: without cross-hunk rules " + ", ".join(sens["excluded_rules"]),
            "",
            *_msg_block(sens),
            "",
        ]
    )


# ---------------------------------------------------------------------------------------------
# Planted-issue benchmark
# ---------------------------------------------------------------------------------------------


def run_planted(
    agent: CodeReviewAgent, repo_path: Path, expected_path: Path
) -> tuple[ReviewResult, dict[str, Any]]:
    spec = json.loads(expected_path.read_text(encoding="utf-8"))
    expected = [ExpectedIssue.model_validate(x) for x in spec["issues"]]
    result = agent.run(AgentRequest(repo_path=str(repo_path)))
    det = detection_metrics(result.findings, expected, spec.get("negative_files"))
    timing = result.stats.get("timing") or {}
    metrics = {
        "detection": det.model_dump(),
        "pipeline": {k: v for k, v in result.stats.items() if k != "timing"},
        "timing": {k: v for k, v in timing.items() if k != "spans"},
        "final_findings": len(result.findings),
    }
    return result, metrics


def planted_summary_md(metrics: dict[str, Any], title: str) -> str:
    d = metrics["detection"]

    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.3f}"

    return "\n".join(
        [
            f"# {title}",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Expected issues | {d['expected']} |",
            f"| Matched | {d['matched']} |",
            f"| TP / FP / FN | {d.get('tp')} / {d.get('fp')} / {d.get('fn')} |",
            f"| Precision (defect findings) | {pct(d.get('precision'))} |",
            f"| Recall | {pct(d['recall'])} |",
            f"| F1 | {pct(d.get('f1'))} |",
            f"| Recall (static-detectable) | {pct(d['recall_static'])} |",
            f"| Recall (LLM-only issues) | {pct(d['recall_llm'])} |",
            f"| False positives in negative-control files | {d['negative_file_false_positives']} |",
            f"| Mean line error of matches | {pct(d['mean_line_error'])} |",
            "",
            f"Missed: {', '.join(d['missed']) or 'none'}",
            "",
        ]
    )


# ---------------------------------------------------------------------------------------------
# RAG retrieval benchmark (self-supervised from the call graph)
# ---------------------------------------------------------------------------------------------


def _containing_chunk(chunks: list[Chunk], file: str, line: int) -> Chunk | None:
    cands = [
        c
        for c in chunks
        if c.file == file and c.start_line <= line <= c.end_line and c.kind != "module"
    ]
    return min(cands, key=lambda c: c.end_line - c.start_line) if cands else None


def callgraph_queries(index: RepoIndex, chunks: list[Chunk]) -> list[tuple[Chunk, set[str]]]:
    """(query chunk, ids of chunks containing its repo-defined callees) per function."""
    queries: list[tuple[Chunk, set[str]]] = []
    for file, module in index.modules.items():
        for sym in module.symbols:
            if sym.kind is SymbolKind.CLASS:
                continue
            q = _containing_chunk(chunks, file, sym.def_line)
            if q is None:
                continue
            relevant: set[str] = set()
            for ref in index.callees(file, sym):
                c = _containing_chunk(chunks, ref.file, ref.symbol.def_line)
                if c is not None and c.id != q.id:
                    relevant.add(c.id)
            if relevant:
                queries.append((q, relevant))
    return queries


_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def code_tokens(text: str) -> list[str]:
    """BM25 tokens for code: identifiers split on '_' and camelCase, lower-cased, plus the whole
    identifier (so `load_user` matches both `load_user` and `load` / `user`)."""
    out: list[str] = []
    for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        parts = [p.lower() for piece in word.split("_") for p in _CAMEL.findall(piece)]
        out.extend(parts)
        if len(parts) > 1:
            out.append(word.lower())
    return out


def bm25_ranker(chunks: list[Chunk]) -> Callable[[Chunk], list[str]] | None:
    """Okapi BM25 (rank_bm25, k1=1.5, b=0.75) over code tokens; None if rank_bm25 is missing."""
    try:
        from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]
    except ImportError:
        return None
    ids = [c.id for c in chunks]
    bm25 = BM25Okapi([code_tokens(c.text) for c in chunks])

    def rank(q: Chunk) -> list[str]:
        scores = bm25.get_scores(code_tokens(q.text))
        order = sorted(range(len(ids)), key=lambda i: (-scores[i], ids[i]))
        return [ids[i] for i in order if ids[i] != q.id]

    return rank


def run_retrieval(
    repo_path: Path,
    embedders: dict[str, Embedder],
    ks: tuple[int, ...] = (1, 3, 5, 10),
    seed: int = 42,
) -> dict[str, Any]:
    repo = load_repository(repo_path)
    index = RepoIndex.build(repo)
    chunks = [c for c in chunk_repository(index) if c.source_type.value in {"code", "test"}]
    queries = callgraph_queries(index, chunks)
    results: dict[str, Any] = {
        "repo": str(repo_path),
        "n_chunks": len(chunks),
        "n_queries": len(queries),
        "relevance": "chunks containing the query function's repo-defined callees (AST call graph)",
        "relevance_labelling": (
            "automatic, no human labels: for every function with at least one callee defined in "
            "the repository, the query is the function's own chunk and the relevant set is the "
            "chunks that contain those callees (the query chunk itself is excluded); classes are "
            "skipped"
        ),
        "ks": list(ks),
        "seed": seed,
        "embedders": list(embedders),
    }

    def evaluate(rank_fn: Callable[[Chunk], list[str]]) -> dict[str, float]:
        agg: dict[str, float] = {f"recall@{k}": 0.0 for k in ks}
        agg.update({f"hit@{k}": 0.0 for k in ks})
        agg.update({"mrr": 0.0, "ndcg@10": 0.0})
        for q, rel in queries:
            ranked = rank_fn(q)
            for k in ks:
                agg[f"recall@{k}"] += recall_at_k(ranked, rel, k)
                agg[f"hit@{k}"] += hit_at_k(ranked, rel, k)
            agg["mrr"] += reciprocal_rank(ranked, rel)
            agg["ndcg@10"] += ndcg_at_k(ranked, rel, 10)
        n = max(len(queries), 1)
        return {k: round(v / n, 4) for k, v in agg.items()}

    rng = random.Random(seed)

    def random_rank(q: Chunk) -> list[str]:
        ids = [c.id for c in chunks if c.id != q.id]
        rng.shuffle(ids)
        return ids

    results["random_baseline"] = evaluate(random_rank)
    bm25 = bm25_ranker(chunks)
    if bm25 is not None:
        t = time.perf_counter()
        results["bm25"] = evaluate(bm25)
        results["bm25"]["seconds"] = round(time.perf_counter() - t, 2)
    else:
        results["bm25_skipped"] = "rank_bm25 is not installed (pip install -e '.[eval]')"
    for name, emb in embedders.items():
        t = time.perf_counter()
        vectors = dict(
            zip([c.id for c in chunks], emb.embed([c.text for c in chunks]), strict=True)
        )

        def dense_rank(q: Chunk, vectors: dict[str, list[float]] = vectors) -> list[str]:
            qv = vectors[q.id]
            scored = [
                (sum(a * b for a, b in zip(qv, v, strict=True)), cid)
                for cid, v in vectors.items()
                if cid != q.id
            ]
            scored.sort(reverse=True)
            return [cid for _, cid in scored]

        results[name] = evaluate(dense_rank)
        results[name]["seconds"] = round(time.perf_counter() - t, 2)
    return results


def retrieval_methods(metrics: dict[str, Any]) -> list[str]:
    """Ranking methods in a retrieval run (random baseline + embedders), not metadata blocks."""
    return [k for k, v in metrics.items() if isinstance(v, dict) and "recall@10" in v]


def retrieval_summary_md(metrics: dict[str, Any], title: str) -> str:
    methods = retrieval_methods(metrics)
    cols = [c for c in next(iter(metrics[m] for m in methods)) if c != "seconds"]
    lines = [
        f"# {title}",
        "",
        f"Repository `{metrics['repo']}`: {metrics['n_chunks']} code chunks, "
        f"{metrics['n_queries']} queries. "
        f"Relevance = {metrics['relevance']}.",
        "",
        "| Method | " + " | ".join(cols) + " |",
        "|---|" + "---:|" * len(cols),
    ]
    for m in methods:
        lines.append(f"| {m} | " + " | ".join(f"{metrics[m][c]:.3f}" for c in cols) + " |")
    n = int(metrics.get("n_queries") or 0)
    if n:
        lines += ["", f"Hit@10 with Wilson 95% intervals (share of the {n} queries):"]
        for m in methods:
            lines.append(f"- {m}: {wilson(round(metrics[m]['hit@10'] * n), n).text()}")
    if metrics.get("relevance_labelling"):
        lines += ["", f"Relevance labelling: {metrics['relevance_labelling']}."]
    return "\n".join(lines) + "\n"


def make_agent(settings: Settings, llm: LLMProvider | None) -> CodeReviewAgent:
    classifier = create_classifier(settings.classifier) if llm is not None else None
    return CodeReviewAgent(llm, settings=settings, progress=lambda _m: None, classifier=classifier)
