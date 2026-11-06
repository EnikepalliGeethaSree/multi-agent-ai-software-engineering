"""Logistic calibration against closed-form values."""

from __future__ import annotations

import math

import pytest

from marl_agents.evaluation.calibration import fit_logistic, predict


def test_single_binary_feature_recovers_log_odds_ratio() -> None:
    # x=1: 6 positives / 2 negatives (odds 3); x=0: 2 positives / 6 negatives (odds 1/3).
    # Unregularised MLE: intercept = ln(1/3), coefficient = ln(3 / (1/3)) = ln 9.
    x = [[1]] * 8 + [[0]] * 8
    y = [1] * 6 + [0] * 2 + [1] * 2 + [0] * 6
    b0, (b1,) = fit_logistic(x, y, l2=0.0)
    assert b0 == pytest.approx(math.log(1 / 3), abs=1e-6)
    assert b1 == pytest.approx(math.log(9), abs=1e-6)
    assert predict(b0, [b1], [1]) == pytest.approx(0.75, abs=1e-6)


def test_l2_shrinks_coefficients_and_ignores_noise() -> None:
    x = [[1, 0]] * 8 + [[0, 1]] * 8
    y = [1] * 6 + [0] * 2 + [1] * 2 + [0] * 6
    _, free = fit_logistic([[r[0]] for r in x], y, l2=0.0)
    _, shrunk = fit_logistic([[r[0]] for r in x], y, l2=5.0)
    assert 0 < shrunk[0] < free[0]
    _, coef = fit_logistic(x, y, l2=1.0)  # second feature = 1 - first: shares the signal
    assert coef[0] > 0 > coef[1]
