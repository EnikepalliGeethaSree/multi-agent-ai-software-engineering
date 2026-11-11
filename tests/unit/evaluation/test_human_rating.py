"""Part 3.13: rating sheet export (no ratings filled in) and scoring with hand-computed kappa."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from marl_agents.evaluation.human_rating import COLUMNS, export_sheet, score_sheet


def test_export_leaves_every_rating_empty(tmp_path: Path) -> None:
    preds = [{"sample_id": f"s{i}", "comment": f"c{i}" if i % 3 else "", "reference": f"r{i}"}
             for i in range(9)]  # fmt: skip
    out = tmp_path / "sheet.csv"
    n = export_sheet(preds, {"s1": "@@ diff"}, out, n=50)
    assert n == 6  # only samples with a comment; fewer than 50 available
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert list(rows[0].keys()) == COLUMNS
    assert all(r[c] == "" for r in rows for c in COLUMNS if c.startswith(("r1_", "r2_")))
    assert all(r["generated_comment"] for r in rows)


def test_scoring_means_and_kappa_by_hand(tmp_path: Path) -> None:
    out = tmp_path / "sheet.csv"
    ratings = [(3, 3), (2, 2), (1, 2), (3, 3)]  # relevance: r1 vs r2
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for i, (a, b) in enumerate(ratings):
            w.writerow({"sample_id": f"s{i}", "r1_relevance": a, "r2_relevance": b})
        w.writerow({"sample_id": "blank"})  # not rated yet: left out
    rel = score_sheet(out)["dimensions"]["relevance"]
    assert rel["rated_by_both"] == 4
    assert rel["mean_r1"] == pytest.approx(9 / 4) and rel["mean_r2"] == pytest.approx(10 / 4)
    # observed 3/4; chance = P1(1)P2(1) + P1(2)P2(2) + P1(3)P2(3) = 0 + 1/4*2/4 + 2/4*2/4 = 3/8
    assert rel["cohen_kappa"] == pytest.approx((0.75 - 0.375) / (1 - 0.375))
    assert score_sheet(out)["dimensions"]["correctness"]["rated_by_both"] == 0


def test_out_of_scale_rating_is_an_error(tmp_path: Path) -> None:
    out = tmp_path / "sheet.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerow({"sample_id": "s", "r1_relevance": 5, "r2_relevance": 1})
    with pytest.raises(ValueError, match="1, 2 or 3"):
        score_sheet(out)
