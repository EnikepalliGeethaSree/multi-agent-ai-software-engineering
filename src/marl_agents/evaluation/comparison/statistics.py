"""Intervals and paired tests for the comparison tables (built on evaluation/stats.py).

Each function fills `Row.ci` (metric -> [low, high]) and returns lines for the table's
"Statistics" block. With several runs per configuration the intervals use the pooled counts and
the paired tests use the latest run of each configuration; the text says so.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

from marl_agents.config import PROJECT_ROOT
from marl_agents.core.schemas import Severity
from marl_agents.evaluation.comparison.models import Row
from marl_agents.evaluation.metrics import binary_metrics
from marl_agents.evaluation.runs import SavedRun
from marl_agents.evaluation.stats import comment_scores, mcnemar, paired_bootstrap, wilson

ANSWER_KEY = PROJECT_ROOT / "tests" / "fixtures" / "repos" / "planted_expected.json"
LOW = Severity.LOW.rank
MSG_METRICS = ("bleu4", "rouge_l", "chrf", "coverage")
MSG_LABEL = {"bleu4": "BLEU-4", "rouge_l": "ROUGE-L", "chrf": "chrF", "coverage": "coverage"}


def _letter(row: Row) -> str:
    return (row.configuration.letter if row.configuration else None) or row.label


def planted_issue_ids() -> list[str]:
    try:
        data = json.loads(ANSWER_KEY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(i["id"]) for i in data.get("issues", [])]


def planted_statistics(rows: list[Row], chosen: dict[str, list[SavedRun]]) -> list[str]:
    """Wilson intervals for issue recall and defect precision; exact McNemar on found issues."""
    ids = planted_issue_ids()
    lines: list[str] = []
    found: dict[str, list[bool]] = {}
    for row in rows:
        if row.status != "ok" or row.configuration is None:
            continue
        runs = chosen.get(row.configuration.key) or []
        dets = [r.metrics["detection"] for r in runs]
        matched = sum(int(d["matched"]) for d in dets)
        expected = sum(int(d["expected"]) for d in dets)
        tp = sum(int(d.get("tp", d.get("defect_true_positives", 0))) for d in dets)
        defect = sum(int(d.get("defect_findings", 0)) for d in dets)
        fp = sum(int(d.get("fp", defect - tp)) for d in dets)
        rec, prec = wilson(matched, expected), wilson(tp, tp + fp)
        row.ci["recall"] = [rec.low, rec.high]
        row.ci["precision"] = [prec.low, prec.high]
        pooled = f" (pooled over {len(runs)} runs)" if len(runs) > 1 else ""
        lines.append(
            f"{_letter(row)}{pooled}: issues found {rec.text()}; defect findings correct "
            f"{prec.text()}; false-positive defect findings {fp}"
        )
        if ids and runs:
            missed = set(runs[-1].metrics["detection"].get("missed") or [])
            found[_letter(row)] = [i not in missed for i in ids]
    for a, b in itertools.combinations(found, 2):
        lines.append(mcnemar(found[a], found[b]).text(a, b) + " (issues found, latest runs)")
    if found:
        lines.append(
            "Precision is counted per finding (defect-class findings that match an issue / all "
            "defect-class findings); recall is counted per issue (issues matched / 17)."
        )
    return lines


def _cls_counts(preds: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    y = [int(p["label"]) for p in preds]
    flags = [
        int(any(Severity(f["severity"]).rank >= LOW for f in p.get("findings", []))) for p in preds
    ]
    bm = binary_metrics(y, flags)
    return bm.tp, bm.fp, bm.tn, bm.fn


def codereviewer_statistics(
    task: str,
    rows: list[Row],
    preds: dict[str, dict[str, dict[str, Any]]],
    common: list[str],
) -> list[str]:
    """cls: Wilson intervals. msg: Wilson for coverage, paired bootstrap of every metric vs A."""
    lines: list[str] = []
    scored = [r for r in rows if r.status == "ok" and r.run_ids]
    if not common or not scored:
        return lines
    if task == "cls":
        for row in scored:
            tp, fp, tn, fn = _cls_counts([preds[row.run_ids[-1]][i] for i in common])
            p, r, acc = wilson(tp, tp + fp), wilson(tp, tp + fn), wilson(tp + tn, len(common))
            row.ci.update(precision=[p.low, p.high], recall=[r.low, r.high])
            lines.append(f"{_letter(row)}: precision {p.text()}; recall {r.text()}; "
                         f"accuracy {acc.text()}")  # fmt: skip
        return lines
    per: dict[str, dict[str, list[float]]] = {}
    for row in scored:
        samples = [preds[row.run_ids[-1]][i] for i in common]
        scores = [comment_scores(str(s.get("reference") or ""), str(s.get("comment") or ""))
                  for s in samples]  # fmt: skip
        per[_letter(row)] = {m: [s[m] for s in scores] for m in MSG_METRICS}
        covered = int(sum(per[_letter(row)]["coverage"]))
        cov = wilson(covered, len(common))
        row.ci["coverage"] = [cov.low, cov.high]
        lines.append(f"{_letter(row)}: coverage {covered}/{len(common)} = {cov.text()}")
    pairs = [("A", x) for x in ("B", "C", "D")] + [("C", "D"), ("B", "D")]
    for a, b in pairs:
        if a in per and b in per:
            diffs = "; ".join(
                f"{MSG_LABEL[m]} {paired_bootstrap(per[a][m], per[b][m]).text()}"
                for m in MSG_METRICS
            )
            lines.append(f"{b} minus {a} (paired bootstrap, 1,000 resamples, seed 42): {diffs}")
    lines.append(
        "Coverage: the share of samples for which the configuration produced a comment (its "
        "top-ranked in-scope finding was not empty). Empty comments score 0 on BLEU-4, ROUGE-L "
        "and chrF. Paired tests use the latest run of each configuration."
    )
    return lines
