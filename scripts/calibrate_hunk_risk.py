"""Fit the hunk-risk weights on a CodeReviewer *validation* run (never on test).

    python scripts/calibrate_hunk_risk.py experiments/results/<..._hunkrisk_cls_valid_n...>

Features are fixed in advance (see FEATURES). Uses the cross-hunk-adjusted signals: on real changes
those rules are reliable, on single CodeReviewer hunks they misfire. Writes calibration.json into
the run directory and prints the constants to paste into agents/code_review/risk.py.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from marl_agents.evaluation.calibration import fit_logistic, predict
from marl_agents.evaluation.metrics import roc_auc

FEATURES = [
    "finding_high",  # any critical/high finding in the hunk
    "finding_medium",
    "finding_low",  # low or info
    "sensitive_api",
    "error_handling",
    "signature_change",
    "removes_function",
    "has_dependents",
    "log2_size",  # log2(1 + changed lines)
]
L2 = 1.0


def features(row: dict) -> list[float]:  # type: ignore[type-arg]
    sev = row.get("severities_adj", {})
    sig = set(row.get("signals_adj", []))
    return [
        float(sev.get("critical", 0) + sev.get("high", 0) > 0),
        float(sev.get("medium", 0) > 0),
        float(sev.get("low", 0) + sev.get("info", 0) > 0),
        float("sensitive_api" in sig),
        float("error_handling" in sig),
        float("signature_change" in sig),
        float("removes_function" in sig),
        float("has_dependents" in sig),
        math.log2(1 + row["size"]),
    ]


def main(run_dir: Path) -> int:
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    if meta.get("split") != "valid":
        print(f"refusing: {run_dir.name} is split={meta.get('split')!r}; calibrate on 'valid' only")
        return 2
    rows = [
        json.loads(line)
        for line in (run_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    x = [features(r) for r in rows]
    y = [r["label"] for r in rows]
    intercept, coef = fit_logistic(x, y, l2=L2)
    scores = [100 * predict(intercept, coef, row) for row in x]
    ordered = sorted(scores)
    p65 = ordered[int(0.65 * (len(ordered) - 1))]
    p90 = ordered[int(0.90 * (len(ordered) - 1))]
    out = {
        "source_run": run_dir.name,
        "n": len(rows),
        "base_rate": sum(y) / len(y),
        "l2": L2,
        "intercept": intercept,
        "coefficients": dict(zip(FEATURES, coef, strict=True)),
        "thresholds": {"high_p90": p90, "medium_p65": p65},
        "valid_auc_in_sample": roc_auc(y, scores),
    }
    (run_dir / "calibration.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
