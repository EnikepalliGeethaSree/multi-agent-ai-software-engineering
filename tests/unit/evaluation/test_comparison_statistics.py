"""Statistics wired into the comparison tables and BugsInPy scoring (Part 2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from marl_agents.evaluation.comparison import table_md
from marl_agents.evaluation.comparison.detection import codereviewer_tables, planted_table
from marl_agents.evaluation.comparison.statistics import planted_issue_ids
from marl_agents.evaluation.runners import bug_scoring
from marl_agents.evaluation.runs import load_runs
from tests.unit.evaluation.test_comparison import CFG, detection, llm_cfg, save


def _planted(tmp_path: Path, letter: str, key: str, matched: int, tp: int, fp: int,
             missed: list[str]) -> None:  # fmt: skip
    d = {**detection(tp, fp, matched), "missed": missed, "defect_findings": tp + fp}
    exp = {"configuration": {"key": key}, "group_id": "g1"}
    save(tmp_path, f"20260101T00000{letter}Z_planted_{key}".replace("A", "1").replace(
        "C", "3"), {"detection": d}, meta={"experiment": exp, "llm_provider": "groq"},
        config=CFG[letter] if letter == "A" else llm_cfg(letter))  # fmt: skip


def test_planted_table_reports_wilson_counts_and_mcnemar(tmp_path: Path) -> None:
    ids = planted_issue_ids()
    assert len(ids) == 17 and "P13" in ids
    _planted(tmp_path, "A", "static_only", 16, 13, 0, ["P13"])
    _planted(tmp_path, "C", "static_llm", 17, 14, 1, [])
    table = planted_table(load_runs(tmp_path))
    by = {r.configuration.key: r for r in table.rows if r.status == "ok"}  # type: ignore[union-attr]
    assert by["static_only"].ci["recall"] == [pytest.approx(0.7302, abs=1e-4),
                                               pytest.approx(0.9895, abs=1e-4)]  # fmt: skip
    stats = "\n".join(table.statistics)
    assert "A: issues found 0.941 (16/17; 95% CI 0.730-0.990)" in stats
    assert (
        "defect findings correct 0.933 (14/15" in stats
        and "false-positive defect findings 1" in stats
    )
    # A missed only P13, C found everything: one discordant issue, p = 1.0
    assert "A vs C: only A 0, only C 1, both 16, neither 0; exact McNemar p = 1.000" in stats
    assert "counted per finding" in stats and "counted per issue" in stats
    assert "Statistics (Wilson 95% intervals" in table_md(table)


def msg_pred(sid: str, comment: str, ref: str) -> dict[str, Any]:
    return {"sample_id": sid, "label": 1, "comment": comment, "reference": ref, "findings": []}


def test_codereviewer_msg_table_reports_coverage_count_and_paired_bootstrap(
    tmp_path: Path,
) -> None:
    ref = "add a null check before using the value"
    ids = ["s1", "s2", "s3", "s4"]
    meta = {"sample_ids": ids, "split": "test", "llm_provider": "groq", "llm_model": "m"}
    save(tmp_path, "20260101T000000Z_codereviewer_msg_test_static_only_n4",
         {"task": "msg", "n_evaluated": 4, "n_failed": 0}, meta={**meta, "llm_provider": None},
         config=CFG["A"], predictions=[msg_pred("s1", ref, ref)] + [msg_pred(s, "", ref)
                                                                   for s in ids[1:]])  # fmt: skip
    save(tmp_path, "20260102T000000Z_codereviewer_msg_test_static_llm_rag_n4",
         {"task": "msg", "n_evaluated": 4, "n_failed": 0}, meta=meta, config=llm_cfg("D"),
         predictions=[msg_pred(s, ref, ref) for s in ids])  # fmt: skip
    table = codereviewer_tables(load_runs(tmp_path), "msg")[0]
    stats = "\n".join(table.statistics)
    assert "A: coverage 1/4 = 0.250 (1/4; 95% CI" in stats
    assert "D: coverage 4/4 = 1.000 (4/4; 95% CI" in stats
    # D adds a perfect comment on 3 of 4 samples: mean difference +0.75 coverage, +75 BLEU-4.
    assert "D minus A (paired bootstrap, 1,000 resamples, seed 42)" in stats
    assert "coverage +0.75" in stats and "BLEU-4 +75.00" in stats
    assert "Coverage: the share of samples" in stats


def test_codereviewer_cls_table_reports_wilson_intervals(tmp_path: Path) -> None:
    hi = [{"severity": "high", "confidence": 0.8, "rule": None}]
    preds = [{"sample_id": "s1", "label": 1, "findings": hi},
             {"sample_id": "s2", "label": 0, "findings": []}]  # fmt: skip
    save(tmp_path, "20260101T000000Z_codereviewer_cls_test_static_only_n2",
         {"task": "cls", "n_evaluated": 2, "n_failed": 0},
         meta={"sample_ids": ["s1", "s2"], "split": "test"}, config=CFG["A"],
         predictions=preds)  # fmt: skip
    table = codereviewer_tables(load_runs(tmp_path), "cls")[0]
    assert any(s.startswith("A: precision 1.000 (1/1; 95% CI") for s in table.statistics)
    assert any("accuracy 1.000 (2/2;" in s for s in table.statistics)


def _loc_row(sid: str, rank: int | None) -> dict[str, Any]:
    return {"sample_id": sid, "project": "p", "status": "complete", "gold_rank": rank, "ranked_functions": [],
            "gold_functions": ["f"], "ranked_files": [], "gold_file": "a.py",
            "functions_in_repo": 10, "candidates": 5}  # fmt: skip


def test_bugsinpy_localization_and_detection_have_wilson_intervals() -> None:
    m = bug_scoring.score_localization([_loc_row("b1", 1), _loc_row("b2", 4), _loc_row("b3", None)])
    assert m["wilson"]["top_1"]["k"] == 1 and m["wilson"]["top_5"]["k"] == 2
    assert m["wilson"]["top_1"]["low"] == pytest.approx(0.0615, abs=1e-4)  # Wilson 1/3
    summary = bug_scoring.localization_summary(
        "llm_only", m, {"split": "dev", "n_samples": 3, "n_requested": 3, "seed": 42}
    )
    assert "Wilson 95% interval, function Top-1: 0.333 (1/3; 95% CI 0.061-0.792)" in summary
    rows = [
        {
            "sample_id": "b1",
            "project": "p",
            "version": "buggy",
            "status": "complete",
            "flagged": True,
        },
        {
            "sample_id": "b1",
            "project": "p",
            "version": "fixed",
            "status": "complete",
            "flagged": False,
        },
        {
            "sample_id": "b2",
            "project": "p",
            "version": "buggy",
            "status": "complete",
            "flagged": False,
        },
        {
            "sample_id": "b2",
            "project": "p",
            "version": "fixed",
            "status": "complete",
            "flagged": False,
        },
    ]
    d = bug_scoring.score_detection(rows)
    assert d["wilson"]["precision"]["k"] == 1 and d["wilson"]["precision"]["n"] == 1
    assert d["wilson"]["recall"]["n"] == 2 and d["wilson"]["detection_rate"]["k"] == 1


def test_repeated_runs_are_never_pooled_into_more_samples(tmp_path: Path) -> None:
    for i, (matched, missed) in enumerate(((16, ["P13"]), (17, []), (15, ["P13", "P02"]))):
        d = {**detection(13, 0, matched), "missed": missed, "defect_findings": 13}
        exp = {"configuration": {"key": "static_llm"}, "group_id": "g1", "repeat": i + 1}
        save(tmp_path, f"2026010{i + 1}T000000Z_planted_static_llm", {"detection": d},
             meta={"experiment": exp, "llm_provider": "groq"}, config=llm_cfg("C"))  # fmt: skip
    stats = "\n".join(planted_table(load_runs(tmp_path)).statistics)
    assert "C run 1 of 3: issues found 0.941 (16/17;" in stats
    assert "C run 3 of 3: issues found 0.882 (15/17;" in stats
    assert "/51" not in stats  # the same 17 issues three times are not 51 samples
