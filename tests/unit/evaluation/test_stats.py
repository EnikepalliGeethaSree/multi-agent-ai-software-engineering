"""evaluation/stats.py against hand-computed values (cross-checked with SciPy when written)."""

from __future__ import annotations

import pytest

from marl_agents.evaluation.stats import comment_scores, mcnemar, paired_bootstrap, wilson


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [
        (16, 17, 0.7302, 0.9895),  # planted: static only found 16 of 17
        (12, 17, 0.4687, 0.8672),
        (1, 5, 0.0362, 0.6245),
        (13, 14, 0.6853, 0.9873),
        (0, 10, 0.0, 0.2775),  # z^2 / (n + z^2) at 0/n
        (10, 10, 0.7225, 1.0),
    ],
)
def test_wilson_interval_known_values(k: int, n: int, low: float, high: float) -> None:
    p = wilson(k, n)
    assert p.value == pytest.approx(k / n)
    assert p.low == pytest.approx(low, abs=1e-4) and p.high == pytest.approx(high, abs=1e-4)


def test_wilson_edge_cases_and_text() -> None:
    empty = wilson(0, 0)
    assert empty.value is None and empty.text() == "N/A (0/0)"
    assert wilson(16, 17).text() == "0.941 (16/17; 95% CI 0.730-0.990)"
    with pytest.raises(ValueError):
        wilson(5, 4)


def test_mcnemar_exact_known_values() -> None:
    # A found 1 item B missed, B found 6 items A missed, 10 found by both, 3 by neither.
    a = [True] * 1 + [False] * 6 + [True] * 10 + [False] * 3
    b = [False] * 1 + [True] * 6 + [True] * 10 + [False] * 3
    r = mcnemar(a, b)
    assert (r.only_a, r.only_b, r.both, r.neither, r.n) == (1, 6, 10, 3, 20)
    assert r.p_value == pytest.approx(0.125)  # 2 * (C(7,0) + C(7,1)) / 2^7
    assert mcnemar([False] * 5, [True] * 5).p_value == pytest.approx(0.0625)  # 2 / 2^5
    assert mcnemar([True, False], [True, False]).p_value == 1.0  # no discordant pairs
    assert "exact McNemar p = 0.125" in r.text("A", "C")


def test_paired_bootstrap_constant_shift_has_a_point_interval() -> None:
    a = [1.0, 2.0, 3.0, 4.0]
    r = paired_bootstrap(a, [x + 1.5 for x in a])
    assert r.diff == pytest.approx(1.5) and r.low == pytest.approx(1.5)
    assert r.high == pytest.approx(1.5) and r.p_value == 0.0
    assert r.n_boot == 1000 and r.seed == 42


def test_paired_bootstrap_no_difference() -> None:
    r = paired_bootstrap([0.2, 0.5, 0.9], [0.2, 0.5, 0.9])
    assert r.diff == 0 and r.low == 0 and r.high == 0 and r.p_value == 1.0


def test_paired_bootstrap_two_samples_by_hand() -> None:
    # deltas [1, 0]: resampled means are 0, 0.5, 1 with probabilities 1/4, 1/2, 1/4.
    r = paired_bootstrap([0.0, 0.0], [1.0, 0.0])
    assert r.diff == pytest.approx(0.5) and r.mean_a == 0 and r.mean_b == pytest.approx(0.5)
    assert r.low == 0.0 and r.high == 1.0
    assert r.p_value == pytest.approx(0.5, abs=0.06)  # 2 * P(mean <= 0) = 2 * 1/4


def test_paired_bootstrap_is_reproducible_and_paired() -> None:
    a = [0.1, 0.4, 0.35, 0.8, 0.0, 0.9]
    b = [0.3, 0.4, 0.5, 0.7, 0.2, 1.0]
    assert paired_bootstrap(a, b) == paired_bootstrap(a, b)
    assert paired_bootstrap(a, b, seed=1) != paired_bootstrap(a, b, seed=2)
    with pytest.raises(ValueError):
        paired_bootstrap([1.0], [1.0, 2.0])


def test_comment_scores_scales_and_coverage() -> None:
    ref = "please add a null check before using the config value here"
    same = comment_scores(ref, ref)
    assert same["bleu4"] == pytest.approx(100) and same["rouge_l"] == pytest.approx(100)
    assert same["chrf"] == pytest.approx(100) and same["coverage"] == 1.0
    assert comment_scores(ref, "") == {"bleu4": 0.0, "rouge_l": 0.0, "chrf": 0.0, "coverage": 0.0}
