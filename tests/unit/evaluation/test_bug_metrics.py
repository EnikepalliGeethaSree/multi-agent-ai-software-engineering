"""Metric implementations against values worked out by hand."""

import math

import pytest

from marl_agents.evaluation.metrics import (
    cohen_kappa,
    localization_metrics,
    mcnemar_exact,
    pair_outcomes,
    random_top_k,
)
from marl_agents.evaluation.runners import bug_scoring as scoring


def test_localization_by_hand() -> None:
    # Bug 1: gold function first. Bug 2: gold third, its file first. Bug 3: not found.
    m = localization_metrics(
        [["a.py::f", "a.py::g"], ["b.py::x", "b.py::y", "c.py::z"], ["d.py::p"]],
        [{"a.py::f"}, {"c.py::z"}, {"e.py::q"}],
        [["a.py"], ["c.py", "b.py"], ["d.py"]],
        [{"a.py"}, {"c.py"}, {"e.py"}],
    )
    assert m.n == 3
    assert m.top_function["top_1"] == pytest.approx(1 / 3)
    assert m.top_function["top_3"] == pytest.approx(2 / 3)
    assert m.top_file["top_1"] == pytest.approx(2 / 3)
    assert m.mrr_function == pytest.approx((1 + 1 / 3 + 0) / 3)
    assert m.mrr_file == pytest.approx((1 + 1 + 0) / 3)


def test_localization_rejects_mismatched_inputs() -> None:
    with pytest.raises(ValueError):
        localization_metrics([["a"]], [], [["a"]], [{"a"}])


def test_random_baseline_by_hand() -> None:
    assert random_top_k(10, 1, 1) == pytest.approx(0.1)
    assert random_top_k(10, 1, 5) == pytest.approx(0.5)
    # 2 gold of 4, top 1: 1/2. Top 2: miss only if both picks are non-gold, 1/6.
    assert random_top_k(4, 2, 1) == pytest.approx(0.5)
    assert random_top_k(4, 2, 2) == pytest.approx(1 - 1 / 6)
    assert random_top_k(3, 2, 2) == 1.0
    assert random_top_k(0, 1, 1) == 0.0


def test_mcnemar_exact_by_hand() -> None:
    # 1 vs 5 discordant: 2 * (C(6,0) + C(6,1)) / 2^6 = 2 * 7 / 64.
    assert mcnemar_exact(1, 5) == pytest.approx(14 / 64)
    assert mcnemar_exact(5, 1) == pytest.approx(14 / 64)
    # 0 vs 6: 2 / 64.
    assert mcnemar_exact(0, 6) == pytest.approx(2 / 64)
    assert mcnemar_exact(3, 3) == 1.0
    assert mcnemar_exact(0, 0) == 1.0


def test_pair_outcomes_by_hand() -> None:
    o = pair_outcomes([True, True, False, False], [True, False, False, True])
    assert (o.both_flagged, o.only_buggy, o.neither, o.only_fixed) == (1, 1, 1, 1)
    assert o.discrimination == 0.25


def test_flagging_everything_scores_zero_discrimination() -> None:
    assert pair_outcomes([True, True], [True, True]).discrimination == 0.0


def test_cohen_kappa_by_hand() -> None:
    a = ["x", "x", "y", "y"]
    b = ["x", "y", "y", "y"]
    # observed 3/4; chance (2/4)(1/4) + (2/4)(3/4) = 1/2; kappa = (3/4 - 1/2) / (1/2) = 1/2.
    assert cohen_kappa(a, b) == pytest.approx(0.5)
    assert cohen_kappa(["x", "y"], ["x", "y"]) == 1.0
    assert cohen_kappa(["x", "x"], ["x", "x"]) is None
    assert cohen_kappa([], []) is None


def loc_row(sample: str, rank: int | None, status: str = "complete", shown: int = 0) -> dict:
    gold = f"a.py::{sample}"
    names = ["a.py::other"] * ((rank or 1) - 1) + ([gold] if rank else [])
    return {
        "sample_id": sample,
        "project": "p",
        "configuration": "c",
        "status": status,
        "gold_rank": rank,
        "gold_functions": [gold],
        "gold_file": "a.py",
        "ranked_functions": names,
        "ranked_files": ["a.py"],
        "functions_in_repo": 10,
        "candidates": 5,
        "candidates_shown": shown,
        "llm_calls": 1,
    }


def test_failed_sample_is_a_miss_not_absent() -> None:
    m = scoring.score_localization([loc_row("a", 1), loc_row("b", 1, status="failed")])
    assert m["n"] == 2 and m["n_failed"] == 1
    assert m["top_function"]["top_1"] == 0.5
    assert m["gold_in_candidates"] == 0.5
    assert m["random_expected"]["top_1"] == pytest.approx(0.1)


def test_gold_shown_to_llm_is_the_ceiling_on_its_score() -> None:
    m = scoring.score_localization([loc_row("a", 2, shown=3), loc_row("b", 4, shown=3)])
    assert m["gold_shown_to_llm"] == 0.5
    assert scoring.score_localization([loc_row("a", 2)])["gold_shown_to_llm"] is None


def det_row(sample: str, version: str, flagged: bool, status: str = "complete", at: bool = False):
    return {
        "sample_id": sample,
        "project": "p",
        "configuration": "c",
        "version": version,
        "status": status,
        "flagged": flagged,
        "flagged_at_gold": at,
        "top_priority": 3.5 if flagged else 0.0,
        "llm_calls": 1,
    }


def test_detection_by_hand() -> None:
    rows = [
        det_row("a", "buggy", True, at=True),  # TP at the gold lines
        det_row("a", "fixed", False),  # TN
        det_row("b", "buggy", True, at=False),  # TP, but elsewhere in the function
        det_row("b", "fixed", True, at=True),  # FP, under both scorings
        det_row("c", "buggy", False),  # FN
        det_row("c", "fixed", False),  # TN
    ]
    m = scoring.score_detection(rows)
    loose, strict = m["function_level"], m["at_gold_lines"]
    assert (loose["tp"], loose["fp"], loose["tn"], loose["fn"]) == (2, 1, 2, 1)
    assert loose["precision"] == pytest.approx(2 / 3) and loose["recall"] == pytest.approx(2 / 3)
    assert (strict["tp"], strict["fp"], strict["fn"]) == (1, 1, 2)
    assert strict["recall"] == pytest.approx(1 / 3) and strict["precision"] == 0.5
    assert m["pairs"]["only_buggy"] == 1 and m["pairs"]["both_flagged"] == 1
    assert m["pairs"]["neither"] == 1
    assert m["pairs"]["discrimination"] == pytest.approx(1 / 3, abs=1e-3)


def test_failed_detection_is_the_wrong_answer_on_both_versions() -> None:
    rows = [det_row("a", "buggy", True, "failed"), det_row("a", "fixed", False, "failed")]
    m = scoring.score_detection(rows)
    loose = m["function_level"]
    assert (loose["tp"], loose["fp"], loose["tn"], loose["fn"]) == (0, 1, 0, 1)
    assert m["n_failed"] == 2 and m["pairs"]["n"] == 0


def test_empty_runs_do_not_crash() -> None:
    assert scoring.score_localization([]) == {"n": 0}
    assert scoring.score_detection([]) == {"n": 0}
    meta = {"split": "dev", "seed": 1, "n_samples": 0, "n_requested": 1}
    assert "No finished" in scoring.localization_summary("c", {"n": 0}, meta)
    assert "No finished" in scoring.detection_summary("c", {"n": 0}, meta)


def test_comparison_counts_discordant_samples_on_shared_samples_only() -> None:
    a = {"s1": True, "s2": True, "s3": False, "only_in_a": True}
    b = {"s1": True, "s2": False, "s3": False}
    row = scoring.compare({"a": a, "b": b})[0]
    assert (row["n"], row["only_a_correct"], row["only_b_correct"]) == (3, 1, 0)
    assert row["p_value"] == 1.0


def test_summaries_state_the_subset_and_mock_runs() -> None:
    meta = {
        "split": "dev", "seed": 42, "n_samples": 1, "n_requested": 2, "pending": 1,
        "provider": "mock", "uses_llm": True,
    }  # fmt: skip
    text = scoring.localization_summary(
        "llm_only", scoring.score_localization([loc_row("a", 1)]), meta
    )
    assert "n=1 bugs" in text and "seed 42" in text
    assert "Incomplete" in text and "Mock LLM" in text
    meta["uses_llm"] = False
    text = scoring.localization_summary(
        "static_only", scoring.score_localization([loc_row("a", 1)]), meta
    )
    assert "Mock LLM" not in text


def test_bug_type_agreement_uses_only_labels_both_raters_gave() -> None:
    result = scoring.type_agreement(
        [{"a": "logic", "b": "boundary", "c": "logic"}, {"a": "logic", "b": "logic"}]
    )
    assert result["n"] == 2 and result["agreed"] == {"a": "logic"}
    with pytest.raises(ValueError):
        scoring.type_agreement([{"a": "logic"}])


def test_localization_by_type() -> None:
    rows = [loc_row("a", 1), loc_row("b", 2), loc_row("c", 1)]
    by_type = scoring.localization_by_type(rows, {"a": "logic", "b": "logic"})
    assert by_type == {"logic": {"n": 2, "top_1": 0.5}}


def test_bootstrap_interval_contains_the_estimate() -> None:
    rows = [loc_row(str(i), 1 if i % 2 else None) for i in range(20)]
    m = scoring.score_localization(rows)
    lo, hi = m["ci_top_1"]
    assert lo <= m["top_function"]["top_1"] <= hi and not math.isnan(lo)
