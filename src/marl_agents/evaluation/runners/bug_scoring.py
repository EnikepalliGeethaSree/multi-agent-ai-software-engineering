"""Turn saved per-sample rows of the Bug Detection evaluation into metrics and summaries.

A row's `status` is "complete" or "failed". A failed sample is never dropped (D22): in localization
it is a miss, and in detection it counts as a wrong answer on that version of the function.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from typing import Any

from marl_agents.evaluation.metrics import binary_metrics, bootstrap_ci, roc_auc
from marl_agents.evaluation.metrics.classification import BinaryMetrics
from marl_agents.evaluation.metrics.localization import (
    TOP_KS,
    cohen_kappa,
    localization_metrics,
    mcnemar_exact,
    pair_outcomes,
    random_top_k,
)
from marl_agents.evaluation.stats import wilson

Row = dict[str, Any]
BOOT_DIGITS = 3


def _rounded_ci(values: list[Any], stat: Any) -> list[float] | None:
    if not values:
        return None
    lo, hi = bootstrap_ci(values, stat)
    return [round(lo, BOOT_DIGITS), round(hi, BOOT_DIGITS)]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def gold_rank(row: Row) -> int | None:
    rank = row.get("gold_rank")
    return int(rank) if row["status"] == "complete" and rank is not None else None


def _hit(row: Row, k: int) -> float:
    rank = gold_rank(row)
    return 1.0 if rank is not None and rank <= k else 0.0


def score_localization(rows: list[Row]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    done = [r for r in rows if r["status"] == "complete"]
    base = localization_metrics(
        [r.get("ranked_functions", []) if r["status"] == "complete" else [] for r in rows],
        [set(r["gold_functions"]) for r in rows],
        [r.get("ranked_files", []) if r["status"] == "complete" else [] for r in rows],
        [{r["gold_file"]} for r in rows],
    )
    random_rates = {
        f"top_{k}": round(
            _mean(
                [
                    random_top_k(int(r.get("functions_in_repo", 0)), len(r["gold_functions"]), k)
                    for r in rows
                ]
            ),
            4,
        )
        for k in TOP_KS
    }

    def reciprocal(row: Row) -> float:
        rank = gold_rank(row)
        return 1 / rank if rank else 0.0

    return {
        **base.model_dump(),
        "n_failed": len(rows) - len(done),
        "gold_in_candidates": round(_mean([1.0 if gold_rank(r) else 0.0 for r in rows]), 4),
        "gold_shown_to_llm": _shown_rate(rows),
        "mean_candidates": round(_mean([float(r.get("candidates", 0)) for r in done]), 1),
        "random_expected": random_rates,
        "ci_top_1": _rounded_ci(rows, lambda s: _mean([_hit(r, 1) for r in s])),
        "ci_top_5": _rounded_ci(rows, lambda s: _mean([_hit(r, 5) for r in s])),
        "ci_mrr": _rounded_ci(rows, lambda s: _mean([reciprocal(r) for r in s])),
        "wilson": {
            f"top_{k}": wilson(int(sum(_hit(r, k) for r in rows)), len(rows)).model_dump()
            for k in TOP_KS
        },
        "llm_calls": sum(int(r.get("llm_calls", 0) or 0) for r in rows),
        "by_project": _by_project(rows),
    }


def _shown_rate(rows: list[Row]) -> float | None:
    """How often the LLM saw the gold function at all: the ceiling on what it could rank."""
    shown = [r for r in rows if int(r.get("candidates_shown", 0) or 0) > 0]
    if not shown:
        return None
    return round(_mean([_hit(r, int(r["candidates_shown"])) for r in shown]), 4)


def _by_project(rows: list[Row]) -> dict[str, dict[str, float]]:
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        groups[r["project"]].append(r)
    return {
        p: {
            "n": len(g),
            "top_1": round(_mean([_hit(r, 1) for r in g]), 3),
            "top_5": round(_mean([_hit(r, 5) for r in g]), 3),
        }
        for p, g in sorted(groups.items())
    }


def _predictions(rows: list[Row], key: str) -> tuple[list[int], list[int]]:
    """(labels, predictions); a failed version is scored as the wrong answer."""
    y_true: list[int] = []
    y_pred: list[int] = []
    for r in rows:
        label = 1 if r["version"] == "buggy" else 0
        y_true.append(label)
        y_pred.append(int(r.get(key, False)) if r["status"] == "complete" else 1 - label)
    return y_true, y_pred


def score_detection(rows: list[Row]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    y_true, loose = _predictions(rows, "flagged")
    _, strict = _predictions(rows, "flagged_at_gold")
    versions: dict[str, dict[str, Row]] = defaultdict(dict)
    for r in rows:
        versions[r["sample_id"]][r["version"]] = r
    pairs = [v for v in versions.values() if len(v) == 2]
    complete = [p for p in pairs if all(x["status"] == "complete" for x in p.values())]
    outcome = pair_outcomes(
        [bool(p["buggy"].get("flagged")) for p in complete],
        [bool(p["fixed"].get("flagged")) for p in complete],
    )

    def f1(sample: list[tuple[int, int]]) -> float:
        return binary_metrics([a for a, _ in sample], [b for _, b in sample]).f1

    scores = [float(r.get("top_priority", 0.0)) / 5 for r in rows]
    return {
        "n_functions": len(rows),
        "n_bugs": len(pairs),
        "n_failed": sum(1 for r in rows if r["status"] != "complete"),
        "function_level": binary_metrics(y_true, loose).model_dump(),
        "at_gold_lines": binary_metrics(y_true, strict).model_dump(),
        "ci_f1": _rounded_ci(list(zip(y_true, loose, strict=True)), f1),
        "auc": roc_auc(y_true, scores),
        "pairs": {**outcome.model_dump(), "discrimination": round(outcome.discrimination, 4)},
        "wilson": _detection_wilson(binary_metrics(y_true, loose), outcome.only_buggy, outcome.n),
        "llm_calls": sum(int(r.get("llm_calls", 0) or 0) for r in rows),
        "llm_rejected": sum(int(r.get("llm_rejected", 0) or 0) for r in rows),
    }


def _detection_wilson(bm: BinaryMetrics, told_apart: int, n_pairs: int) -> dict[str, Any]:
    """Wilson intervals: per-finding precision, per-bug recall, and bugs told apart from the fix."""
    return {
        "precision": wilson(bm.tp, bm.tp + bm.fp).model_dump(),
        "recall": wilson(bm.tp, bm.tp + bm.fn).model_dump(),
        "detection_rate": wilson(told_apart, n_pairs).model_dump(),
    }


def _wilson_text(d: dict[str, Any] | None) -> str:
    if not d or d.get("value") is None:
        return "N/A"
    return f"{d['value']:.3f} ({d['k']}/{d['n']}; 95% CI {d['low']:.3f}-{d['high']:.3f})"


def _correct_localization(rows: list[Row], k: int) -> dict[str, bool]:
    return {r["sample_id"]: _hit(r, k) > 0 for r in rows}


def _correct_detection(rows: list[Row]) -> dict[str, bool]:
    y_true, y_pred = _predictions(rows, "flagged")
    return {
        f"{r['sample_id']}/{r['version']}": t == p
        for r, t, p in zip(rows, y_true, y_pred, strict=True)
    }


def compare(by_config: dict[str, dict[str, bool]]) -> list[dict[str, Any]]:
    """Exact McNemar tests between configurations, on the samples both have."""
    table = []
    for a, b in itertools.combinations(by_config, 2):
        common = sorted(set(by_config[a]) & set(by_config[b]))
        only_a = sum(1 for s in common if by_config[a][s] and not by_config[b][s])
        only_b = sum(1 for s in common if by_config[b][s] and not by_config[a][s])
        table.append(
            {
                "a": a,
                "b": b,
                "n": len(common),
                "only_a_correct": only_a,
                "only_b_correct": only_b,
                "p_value": round(mcnemar_exact(only_a, only_b), 4),
            }
        )
    return table


def compare_localization(rows_by_config: dict[str, list[Row]]) -> dict[str, Any]:
    return {
        f"top_{k}": compare(
            {c: _correct_localization(rows, k) for c, rows in rows_by_config.items()}
        )
        for k in (1, 5)
    }


def compare_detection(rows_by_config: dict[str, list[Row]]) -> dict[str, Any]:
    return {"correct": compare({c: _correct_detection(r) for c, r in rows_by_config.items()})}


# ---- bug types (labelled by people, independently, before results are looked at) -----------------


def type_agreement(raters: list[dict[str, str]]) -> dict[str, Any]:
    """Agreement of two raters, and the labels they agree on."""
    if len(raters) != 2:
        raise ValueError("bug-type labels need exactly two raters")
    common = sorted(set(raters[0]) & set(raters[1]))
    a = [raters[0][s] for s in common]
    b = [raters[1][s] for s in common]
    return {
        "n": len(common),
        "kappa": cohen_kappa(a, b),
        "agreed": {s: x for s, x, y in zip(common, a, b, strict=True) if x == y},
    }


def localization_by_type(rows: list[Row], labels: dict[str, str]) -> dict[str, dict[str, float]]:
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        if r["sample_id"] in labels:
            groups[labels[r["sample_id"]]].append(r)
    return {
        t: {"n": len(g), "top_1": round(_mean([_hit(r, 1) for r in g]), 3)}
        for t, g in sorted(groups.items())
    }


# ---- text --------------------------------------------------------------------------------------


def _pct(x: float) -> str:
    return f"{x:.3f}"


def _ci(ci: list[float] | None) -> str:
    return f" ({ci[0]:.3f}-{ci[1]:.3f})" if ci else ""


def _subset_line(meta: dict[str, Any]) -> str:
    return (
        f"BugsInPy {meta['split']} split, n={meta['n_samples']} bugs (of {meta['n_requested']} "
        f"requested), seed {meta['seed']}. Pool: one source file, at most 10 changed lines, "
        "change inside a function."
    )


def _status_lines(meta: dict[str, Any]) -> list[str]:
    lines = [f"- {_subset_line(meta)}"]
    if meta.get("pending"):
        lines.append(
            f"- **Incomplete:** {meta['pending']} sample(s) not run yet. Run the same command "
            "again to continue; these numbers cover finished samples only."
        )
    if meta.get("provider") == "mock" and meta.get("uses_llm", True):
        lines.append("- **Mock LLM:** this run tests the pipeline. Its numbers mean nothing.")
    return lines


def localization_summary(config: str, m: dict[str, Any], meta: dict[str, Any]) -> str:
    if not m.get("n"):
        return f"# Fault localization: {config}\n\nNo finished samples.\n"
    tf, tfile = m["top_function"], m["top_file"]
    rnd = m["random_expected"]
    lines = [
        f"# Fault localization: {config}",
        "",
        *_status_lines(meta),
        f"- Failed samples, counted as misses: {m['n_failed']}",
        "",
        "| Metric | Function | File | Random function |",
        "|---|---:|---:|---:|",
        f"| Top-1 | {_pct(tf['top_1'])}{_ci(m['ci_top_1'])} | {_pct(tfile['top_1'])} | "
        f"{rnd['top_1']:.4f} |",
        f"| Top-3 | {_pct(tf['top_3'])} | {_pct(tfile['top_3'])} | {rnd['top_3']:.4f} |",
        f"| Top-5 | {_pct(tf['top_5'])}{_ci(m['ci_top_5'])} | {_pct(tfile['top_5'])} | "
        f"{rnd['top_5']:.4f} |",
        f"| MRR | {_pct(m['mrr_function'])}{_ci(m['ci_mrr'])} | {_pct(m['mrr_file'])} | |",
        "",
        f"- Gold function among the candidates: {m['gold_in_candidates']:.3f}"
        + (
            f"; shown to the LLM: {m['gold_shown_to_llm']:.3f}"
            if m.get("gold_shown_to_llm") is not None
            else ""
        ),
        f"- Candidates per bug: {m['mean_candidates']}; LLM calls: {m['llm_calls']}",
        *[
            f"- Wilson 95% interval, function Top-{k}: "
            f"{_wilson_text((m.get('wilson') or {}).get(f'top_{k}'))}"
            for k in TOP_KS
            if m.get("wilson")
        ],
        "",
    ]
    return "\n".join(lines)


def detection_summary(config: str, m: dict[str, Any], meta: dict[str, Any]) -> str:
    if not m.get("n_functions"):
        return f"# Bug detection: {config}\n\nNo finished samples.\n"

    def row(name: str, b: dict[str, Any]) -> str:
        bm = BinaryMetrics.model_validate(b)
        return (
            f"| {name} | {bm.precision:.3f} | {bm.recall:.3f} | {bm.f1:.3f} | {bm.accuracy:.3f} |"
        )

    pairs = m["pairs"]
    auc = "N/A" if m["auc"] is None else f"{m['auc']:.3f}"
    lines = [
        f"# Bug detection: {config}",
        "",
        *_status_lines(meta),
        f"- {m['n_bugs']} bugs, each shown as its buggy and fixed function in separate requests.",
        f"- Failed requests, scored as wrong answers: {m['n_failed']}",
        "- A fixed function may still hold another bug, so false positives are an upper bound.",
        "",
        "| Scoring | Precision | Recall | F1 | Accuracy |",
        "|---|---:|---:|---:|---:|",
        row("Any defect in the function", m["function_level"]),
        row("Defect at the fixed lines", m["at_gold_lines"]),
        "",
        f"- F1 95% CI: {_ci(m['ci_f1']).strip() or 'N/A'}; AUC: {auc}",
        f"- Told apart from the fix: {pairs['discrimination']:.3f} "
        f"(only buggy {pairs['only_buggy']}, both {pairs['both_flagged']}, "
        f"neither {pairs['neither']}, only fixed {pairs['only_fixed']})",
        f"- LLM calls: {m['llm_calls']}; LLM findings rejected: {m['llm_rejected']}",
        *(
            [
                "- Wilson 95% intervals (any defect in the function): precision "
                f"{_wilson_text(m['wilson']['precision'])}; recall "
                f"{_wilson_text(m['wilson']['recall'])}; told apart from the fix "
                f"{_wilson_text(m['wilson']['detection_rate'])}"
            ]
            if m.get("wilson")
            else []
        ),
        "",
    ]
    return "\n".join(lines)


def comparison_summary(task: str, comparison: dict[str, Any], meta: dict[str, Any]) -> str:
    lines = [f"# Configuration comparison: {task}", "", *_status_lines(meta), ""]
    for name, table in comparison.items():
        lines += [
            f"## {name}",
            "",
            "| A | B | n | Only A right | Only B right | McNemar p |",
            "|---|---|---:|---:|---:|---:|",
        ]
        lines += [
            f"| {t['a']} | {t['b']} | {t['n']} | {t['only_a_correct']} | {t['only_b_correct']} | "
            f"{t['p_value']:.4f} |"
            for t in table
        ]
        lines.append("")
    lines.append("p-values are not corrected for the number of comparisons.")
    return "\n".join(lines) + "\n"


def audit_summary(audit: dict[str, Any]) -> str:
    reasons = Counter(audit["ineligible"])
    lines = [
        f"# BugsInPy eligibility audit: {audit['split']}",
        "",
        f"- Bugs in the split's small-fix pool: {audit['pool']}",
        f"- Usable: {audit['usable']} of {audit['checked']} checked",
        "",
    ]
    if reasons:
        lines += ["| Reason not usable | Bugs |", "|---|---:|"]
        lines += [f"| {r} | {n} |" for r, n in reasons.most_common()]
        lines.append("")
    return "\n".join(lines)
