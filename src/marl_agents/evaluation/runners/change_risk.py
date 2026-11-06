"""Does the hunk-risk ranking point reviewers at the hunks that humans commented on?

CodeReviewer ``cls`` labels each diff hunk 1 if a reviewer commented on it, else 0. For every
sample we run the real change-review pipeline (`review_change`: diff -> impact analysis -> static
review of the changed lines -> `rank_hunks`) on old file -> new file, and score the sample by its
highest hunk risk. Reported against two baselines that need no analysis at all:

- hunk size (changed lines): bigger diffs attract more comments;
- the finding score alone (what the plain `cls` evaluation measures).

Caveat: each sample is a single file, so cross-file signals (callers in other files) rarely fire.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any

from marl_agents.agents.code_review.agent import CodeReviewAgent
from marl_agents.agents.code_review.change_review import review_change
from marl_agents.agents.code_review.risk import rank_hunks
from marl_agents.evaluation.datasets.codereviewer import CodeReviewerSample
from marl_agents.evaluation.metrics import bootstrap_ci, roc_auc
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners import code_review as cr
from marl_agents.evaluation.runners.risk_v1 import max_score_v1
from marl_agents.ingestion import load_files
from marl_agents.ingestion.changes import changeset_from_repos
from marl_agents.ingestion.diff import PatchError, apply_patch

logger = logging.getLogger(__name__)

# Phrase in a reason produced by risk.score_hunk -> signal name (reasons start with counts).
SIGNALS = {
    "finding(s) in this hunk": "findings_in_hunk",
    "touches security-sensitive": "sensitive_api",
    "call site(s) in other code": "breaks_callers",
    "call site(s) elsewhere depend": "has_dependents",
    "changes a function signature": "signature_change",
    "removes a function": "removes_function",
    "large hunk": "size_20plus",
    "medium-sized hunk": "size_20plus",
    "changes error handling": "error_handling",
    "changed function has no test": "untested",
}
LEVELS = ("high", "medium", "low")


def signals_of(reasons: list[str]) -> set[str]:
    return {name for r in reasons for key, name in SIGNALS.items() if key in r}


def risk_for_sample(agent: CodeReviewAgent, sample: CodeReviewerSample) -> dict[str, Any]:
    try:
        new_file = apply_patch(sample.oldf, sample.patch)
    except PatchError as exc:
        return {"sample_id": sample.sample_id, "error": f"patch: {exc}"}
    ingestion = agent.settings.ingestion
    try:
        change = changeset_from_repos(
            load_files({cr.CHANGED_FILE: sample.oldf}, ingestion),
            load_files({cr.CHANGED_FILE: new_file}, ingestion),
            "before",
            "after",
        )
    except Exception as exc:
        return {"sample_id": sample.sample_id, "error": f"{type(exc).__name__}: {exc}"}
    try:
        result = review_change(agent, change)
    except Exception as exc:
        return {"sample_id": sample.sample_id, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        change.cleanup()
    assert result.change is not None
    hunks = result.change.hunks
    top = hunks[0] if hunks else None
    # Sensitivity (same pre-registered rule list as the cls evaluation): one hunk applied to the
    # old file lacks imports/definitions from the commit's other hunks, so these rules misfire.
    adjusted = [f for f in result.findings if f.rule_id not in cr.CROSS_HUNK_RULES]
    hunks_adj = rank_hunks(change.files, adjusted, result.change.summary.symbols)
    top_adj = hunks_adj[0] if hunks_adj else None
    return {
        "sample_id": sample.sample_id,
        "label": sample.label,
        "risk": top.score if top else 0.0,
        "risk_v1": max_score_v1(change.files, result.findings, result.change.summary.symbols),
        "level": top.level if top else "low",
        "reasons": top.reasons if top else [],
        "signals": sorted(set().union(*(signals_of(h.reasons) for h in hunks))),
        "risk_adj": top_adj.score if top_adj else 0.0,
        "level_adj": top_adj.level if top_adj else "low",
        "signals_adj": sorted(set().union(*(signals_of(h.reasons) for h in hunks_adj))),
        "severities_adj": dict(Counter(f.severity.value for f in adjusted)),
        "size": result.change.summary.lines_added + result.change.summary.lines_deleted,
        "finding_score": cr.finding_score(result.findings),
        "n_findings": len(result.findings),
        "n_hunks": len(hunks),
    }


def _process_one(sample: CodeReviewerSample) -> dict[str, Any]:
    assert cr._WORKER_AGENT is not None
    return risk_for_sample(cr._WORKER_AGENT, sample)


def _auc_with_ci(labels: list[int], scores: list[float]) -> dict[str, Any]:
    pairs = list(zip(labels, scores, strict=True))

    def stat(s: list[tuple[int, float]]) -> float:
        auc = roc_auc([a for a, _ in s], [b for _, b in s])
        return auc if auc is not None else 0.5

    auc = roc_auc(labels, scores)
    return {"auc": auc, "ci95": list(bootstrap_ci(pairs, stat, n_boot=500)) if auc else None}


def _precision_at_top(labels: list[int], scores: list[float], frac: float) -> float | None:
    k = max(1, int(len(labels) * frac))
    ranked = sorted(zip(scores, labels, strict=True), key=lambda x: -x[0])[:k]
    return sum(lbl for _, lbl in ranked) / k if ranked else None


def risk_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [r["label"] for r in rows]
    n = max(len(rows), 1)
    base = sum(labels) / n
    scores = {
        "hunk_risk": [r["risk"] for r in rows],
        "hunk_risk_adjusted": [r.get("risk_adj", r["risk"]) for r in rows],
        "size_baseline": [float(r["size"]) for r in rows],
        "finding_score_baseline": [r["finding_score"] for r in rows],
    }
    if rows and all("risk_v1" in r for r in rows):
        scores["risk_v1_baseline"] = [r["risk_v1"] for r in rows]
    out: dict[str, Any] = {
        "n_evaluated": len(rows),
        "base_rate": round(base, 4),
        # A random order's expected precision at any cut-off is the base rate; its AUC is 0.5.
        "random_baseline": {"precision_at_top": round(base, 4), "auc": 0.5},
        "auc": {name: _auc_with_ci(labels, s) for name, s in scores.items()},
        "precision_at_top": {
            name: {f"{int(f * 100)}%": _precision_at_top(labels, s, f) for f in (0.05, 0.1, 0.25)}
            for name, s in scores.items()
        },
    }
    for suffix, level_key, signal_key in (
        ("", "level", "signals"),
        ("_adjusted", "level_adj", "signals_adj"),
    ):
        by_level: dict[str, Any] = {}
        for level in LEVELS:
            sel = [r["label"] for r in rows if r.get(level_key, r["level"]) == level]
            by_level[level] = {
                "n": len(sel),
                "share": round(len(sel) / n, 4),
                "commented_rate": round(sum(sel) / len(sel), 4) if sel else None,
            }
        out[f"by_level{suffix}"] = by_level
        signals: dict[str, Any] = {}
        for name in sorted(set(SIGNALS.values())):
            fired = [r["label"] for r in rows if name in r.get(signal_key, r["signals"])]
            rest = [r["label"] for r in rows if name not in r.get(signal_key, r["signals"])]
            signals[name] = {
                "n_fired": len(fired),
                "commented_rate_fired": round(sum(fired) / len(fired), 4) if fired else None,
                "commented_rate_not_fired": round(sum(rest) / len(rest), 4) if rest else None,
            }
        out[f"signals{suffix}"] = signals
    return out


def run_hunk_risk(
    agent: CodeReviewAgent,
    samples: list[CodeReviewerSample],
    recorder: RunRecorder,
    workers: int = 8,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    progress = progress or (lambda m: logger.info(m))
    t0 = time.perf_counter()
    pool: ProcessPoolExecutor | ThreadPoolExecutor
    if agent.llm is None and workers > 1:
        pool = ProcessPoolExecutor(
            max_workers=workers,
            initializer=cr._init_worker,
            initargs=(agent.settings.model_dump_json(), [a.name for a in agent.analyzers]),
        )
        results = pool.map(_process_one, samples, chunksize=8)
    else:
        pool = ThreadPoolExecutor(max_workers=max(1, workers))
        results = pool.map(lambda s: risk_for_sample(agent, s), samples)
    rows: list[dict[str, Any]] = []
    with pool:
        for i, row in enumerate(results, start=1):
            rows.append(row)
            if i % 250 == 0 or i == len(samples):
                progress(f"{i}/{len(samples)} samples ({time.perf_counter() - t0:.0f}s)")
    ok = [r for r in rows if "error" not in r]
    for r in rows:
        if "error" in r:
            recorder.error(r["sample_id"], r["error"])
        else:
            recorder.prediction(r)
    metrics = risk_metrics(ok)
    metrics.update(
        n_samples=len(samples),
        n_failed=len(rows) - len(ok),
        failure_reasons=dict(Counter(r["error"].split(":")[0] for r in rows if "error" in r)),
        seconds=round(time.perf_counter() - t0, 1),
    )
    return metrics


def hunk_risk_summary_md(m: dict[str, Any], title: str) -> str:
    def f(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.3f}"

    lines = [
        f"# {title}",
        "",
        f"n = {m['n_evaluated']} evaluated ({m['n_failed']} failed: {m['failure_reasons']}); "
        f"share of hunks that received a human comment (base rate) = {m['base_rate']:.3f}; "
        f"runtime {m['seconds']} s.",
        "",
        "| Score | ROC-AUC (95% CI) | Precision top 5% | top 10% | top 25% |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, a in m["auc"].items():
        ci = f" ({a['ci95'][0]:.3f}-{a['ci95'][1]:.3f})" if a["ci95"] else ""
        p = m["precision_at_top"][name]
        lines.append(
            f"| {name} | {f(a['auc'])}{ci} | {f(p['5%'])} | {f(p['10%'])} | {f(p['25%'])} |"
        )
    lines += [
        "",
        "`hunk_risk_adjusted` ignores findings of the cross-hunk rules "
        f"({', '.join(sorted(cr.CROSS_HUNK_RULES))}): one hunk applied to the old file lacks the",
        "imports/definitions added by the commit's other hunks, so they misfire on this benchmark",
        "(but not on real changes, where the whole new version is available).",
    ]
    for suffix, label in (("", "as shipped"), ("_adjusted", "adjusted")):
        if f"by_level{suffix}" not in m:
            continue
        lines += [
            "",
            f"Risk level of the top hunk vs. how often humans commented ({label}):",
            "",
            "| Level | Samples | Share | Commented rate |",
            "|---|---:|---:|---:|",
        ]
        for level, x in m[f"by_level{suffix}"].items():
            lines.append(f"| {level} | {x['n']} | {x['share']:.3f} | {f(x['commented_rate'])} |")
        lines += [
            "",
            f"Individual signals, {label} (commented rate when the signal fires vs. not):",
            "",
            "| Signal | Fired | Rate if fired | Rate if not |",
            "|---|---:|---:|---:|",
        ]
        for name, x in m[f"signals{suffix}"].items():
            lines.append(
                f"| {name} | {x['n_fired']} | {f(x['commented_rate_fired'])} "
                f"| {f(x['commented_rate_not_fired'])} |"
            )
    lines += [
        "",
        "Each sample is one file, so cross-file signals (breaks_callers) cannot fire here; they "
        "are exercised by the git-based change tests instead.",
        "",
    ]
    return "\n".join(lines)
