"""Fault localization and paired-detection metrics. Hand-computed cases are in the unit tests."""

from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import BaseModel

from marl_agents.evaluation.metrics.retrieval import hit_at_k, reciprocal_rank

TOP_KS = (1, 3, 5)


class LocalizationMetrics(BaseModel):
    """Averages over all samples. A sample with no ranking counts as a miss, never as absent."""

    n: int
    top_function: dict[str, float]
    top_file: dict[str, float]
    mrr_function: float
    mrr_file: float


def localization_metrics(
    ranked_functions: Sequence[Sequence[str]],
    gold_functions: Sequence[set[str]],
    ranked_files: Sequence[Sequence[str]],
    gold_files: Sequence[set[str]],
) -> LocalizationMetrics:
    n = len(ranked_functions)
    if not n == len(gold_functions) == len(ranked_files) == len(gold_files):
        raise ValueError("inputs differ in length")

    def mean(values: list[float]) -> float:
        return sum(values) / n if n else 0.0

    def tops(ranked: Sequence[Sequence[str]], gold: Sequence[set[str]]) -> dict[str, float]:
        return {
            f"top_{k}": mean([hit_at_k(r, g, k) for r, g in zip(ranked, gold, strict=True)])
            for k in TOP_KS
        }

    return LocalizationMetrics(
        n=n,
        top_function=tops(ranked_functions, gold_functions),
        top_file=tops(ranked_files, gold_files),
        mrr_function=mean(
            [reciprocal_rank(r, g) for r, g in zip(ranked_functions, gold_functions, strict=True)]
        ),
        mrr_file=mean(
            [reciprocal_rank(r, g) for r, g in zip(ranked_files, gold_files, strict=True)]
        ),
    )


def random_top_k(n_candidates: int, n_gold: int, k: int) -> float:
    """Chance that a random ordering of the candidates has a gold item in its first k."""
    if n_gold <= 0 or n_candidates <= 0:
        return 0.0
    if k >= n_candidates or n_gold > n_candidates - k:
        return 1.0
    miss: float = math.comb(n_candidates - n_gold, k) / math.comb(n_candidates, k)
    return 1.0 - miss


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs of a paired comparison."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    tail: float = sum(math.comb(n, i) for i in range(min(only_a, only_b) + 1)) / 2**n
    return min(1.0, 2 * tail)


class PairOutcomes(BaseModel):
    """What happened to each bug's buggy and fixed versions of the same function."""

    n: int
    both_flagged: int
    only_buggy: int
    only_fixed: int
    neither: int

    @property
    def discrimination(self) -> float:
        """Share of bugs told apart from their fix. Flagging everything scores zero."""
        return self.only_buggy / self.n if self.n else 0.0


def pair_outcomes(buggy_flagged: Sequence[bool], fixed_flagged: Sequence[bool]) -> PairOutcomes:
    pairs = list(zip(buggy_flagged, fixed_flagged, strict=True))
    return PairOutcomes(
        n=len(pairs),
        both_flagged=sum(1 for b, f in pairs if b and f),
        only_buggy=sum(1 for b, f in pairs if b and not f),
        only_fixed=sum(1 for b, f in pairs if f and not b),
        neither=sum(1 for b, f in pairs if not b and not f),
    )


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Agreement of two raters on nominal labels; None when chance agreement is total."""
    if len(a) != len(b):
        raise ValueError("raters differ in length")
    n = len(a)
    if n == 0:
        return None
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    labels = set(a) | set(b)
    chance = sum((list(a).count(x) / n) * (list(b).count(x) / n) for x in labels)
    return None if chance == 1 else (observed - chance) / (1 - chance)
