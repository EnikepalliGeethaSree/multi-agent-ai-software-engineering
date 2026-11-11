"""Part 3.13: human rating sheet for generated review comments, and its scoring.

Export (after the configuration-D CodeReviewer runs exist):

    python -m marl_agents.evaluation.human_rating export --run <run folder name>

writes `results/manual_label/comment_rating.csv`: sample id, the diff, the generated comment, the
human reference comment, and empty 1-3 columns for two raters (relevance, correctness,
actionability). Nothing is filled in by the tool. Samples are a seeded random choice among those
with a non-empty comment; if fewer are available than asked for, all of them are exported and the
count is printed.

Scoring (after both raters filled the sheet):

    python -m marl_agents.evaluation.human_rating score

prints, per dimension, each rater's mean, the mean of both, Cohen's kappa (nominal) and quadratic
weighted kappa (ordinal, reused from metrics), on the rows both raters completed.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any

from marl_agents.config import PROJECT_ROOT
from marl_agents.evaluation.metrics.agreement import weighted_kappa
from marl_agents.evaluation.metrics.localization import cohen_kappa

SHEET = PROJECT_ROOT / "results" / "manual_label" / "comment_rating.csv"
DATASET = PROJECT_ROOT / "data" / "cache" / "codereviewer_msg_test_py.jsonl"
DIMENSIONS = ("relevance", "correctness", "actionability")
RATERS = ("r1", "r2")
SCALE = (1, 2, 3)
COLUMNS = [
    "sample_id", "diff", "generated_comment", "reference_comment",
    *[f"{r}_{d}" for r in RATERS for d in DIMENSIONS], "notes",
]  # fmt: skip


def export_sheet(
    predictions: list[dict[str, Any]],
    patches: dict[str, str],
    out: Path,
    n: int = 50,
    seed: int = 42,
) -> int:
    rows = [p for p in predictions if str(p.get("comment") or "").strip()]
    rng = random.Random(seed)
    chosen = rng.sample(rows, min(n, len(rows)))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for p in chosen:
            writer.writerow({
                "sample_id": p["sample_id"],
                "diff": patches.get(p["sample_id"], ""),
                "generated_comment": p.get("comment", ""),
                "reference_comment": p.get("reference", ""),
            })  # fmt: skip
    return len(chosen)


def _rating(value: str, where: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    if value not in {str(s) for s in SCALE}:
        raise ValueError(f"{where}: rating must be 1, 2 or 3, not {value!r}")
    return int(value)


def score_sheet(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out: dict[str, Any] = {"sheet": str(path), "rows": len(rows), "dimensions": {}}
    for d in DIMENSIONS:
        pairs = []
        for i, row in enumerate(rows, start=2):
            a = _rating(row.get(f"r1_{d}", ""), f"row {i}, r1_{d}")
            b = _rating(row.get(f"r2_{d}", ""), f"row {i}, r2_{d}")
            if a is not None and b is not None:
                pairs.append((a, b))
        r1, r2 = [a for a, _ in pairs], [b for _, b in pairs]
        n = len(pairs)
        out["dimensions"][d] = {
            "rated_by_both": n,
            "mean_r1": sum(r1) / n if n else None,
            "mean_r2": sum(r2) / n if n else None,
            "mean_both": (sum(r1) + sum(r2)) / (2 * n) if n else None,
            "cohen_kappa": cohen_kappa([str(x) for x in r1], [str(x) for x in r2]) if n else None,
            "weighted_kappa_quadratic": weighted_kappa(r1, r2, SCALE) if n else None,
        }
    return out


def _patches() -> dict[str, str]:
    out: dict[str, str] = {}
    if DATASET.is_file():
        with DATASET.open(encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                out[r["sample_id"]] = r.get("patch", "")
    return out


def main(argv: list[str] | None = None) -> int:
    from marl_agents.evaluation.runs import load_run

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--run", required=True, help="configuration-D CodeReviewer msg run folder")
    ex.add_argument("--n", type=int, default=50)
    ex.add_argument("--out", type=Path, default=SHEET)
    sc = sub.add_parser("score")
    sc.add_argument("--sheet", type=Path, default=SHEET)
    args = parser.parse_args(argv)
    if args.cmd == "export":
        run = load_run(PROJECT_ROOT / "experiments" / "results" / args.run)
        if run is None or run.configuration is None or run.configuration.key != "static_llm_rag":
            print("error: --run must be a saved configuration-D (static_llm_rag) run")
            return 2
        if args.out.exists():
            print(
                f"error: {args.out} exists; move it to results/archive/ first (never overwritten)"
            )
            return 2
        count = export_sheet(run.predictions(), _patches(), args.out, args.n)
        print(f"exported {count} comments (asked for {args.n}) to {args.out}")
        return 0
    print(json.dumps(score_sheet(args.sheet), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
