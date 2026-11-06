"""Agreement metrics against hand-computed values."""

from __future__ import annotations

import math

import pytest

from marl_agents.evaluation.metrics import (
    agreement_rates,
    pearson,
    spearman,
    weighted_kappa,
)
from marl_agents.evaluation.metrics.agreement import average_ranks


def test_weighted_kappa_hand_computed() -> None:
    assert weighted_kappa([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    # 2x2, independent raters: observed disagreement 2 = expected 2 -> kappa 0
    assert weighted_kappa([1, 1, 2, 2], [1, 2, 1, 2], categories=(1, 2)) == pytest.approx(0.0)
    # one 1-vs-2 disagreement out of 5: num = 1/16, den = 85/16/5 = 17/16 -> 1 - 1/17
    assert weighted_kappa([1, 2, 3, 4, 5], [2, 2, 3, 4, 5]) == pytest.approx(16 / 17)
    # a 1-vs-5 disagreement costs more than a 4-vs-5 one
    near = weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 5, 5])
    far = weighted_kappa([1, 2, 3, 4, 5], [5, 2, 3, 4, 5])
    assert near is not None and far is not None and near > far
    assert weighted_kappa([3, 3], [3, 3]) is None  # undefined, not 1 or 0
    assert weighted_kappa([], []) is None


def test_rank_correlations_hand_computed() -> None:
    assert average_ranks([1, 2, 2, 3]) == [1, 2.5, 2.5, 4]
    # ranks a=[1,2.5,2.5,4], b=[1,3,2,4]: cov 4.5, va 4.5, vb 5 -> 4.5 / sqrt(22.5)
    assert spearman([1, 2, 2, 3], [1, 3, 2, 4]) == pytest.approx(4.5 / math.sqrt(22.5))
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert pearson([1, 1, 1], [1, 2, 3]) is None
    with pytest.raises(ValueError):
        spearman([1], [1, 2])


def test_agreement_rates() -> None:
    assert agreement_rates([1, 2, 3, 5], [1, 3, 5, 5]) == {"exact": 0.5, "within_one": 0.75}
