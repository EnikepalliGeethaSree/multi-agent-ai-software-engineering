"""Rater agreement for ordinal 1-5 ratings (LLM judge vs. human, human vs. human).

- Quadratic-weighted Cohen's kappa: chance-corrected agreement where a 4-vs-5 disagreement costs
  far less than 1-vs-5 (the standard choice for ordinal scales).
- Spearman rank correlation (average ranks for ties) and Pearson correlation.
- Exact and within-one agreement rates (easy to explain).
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _check(a: Sequence[float], b: Sequence[float]) -> None:
    if len(a) != len(b):
        raise ValueError("rating lists differ in length")


def pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    _check(a, b)
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return cov / math.sqrt(va * vb)


def average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    _check(a, b)
    return pearson(average_ranks(a), average_ranks(b))


def weighted_kappa(
    a: Sequence[int], b: Sequence[int], categories: Sequence[int] = (1, 2, 3, 4, 5)
) -> float | None:
    """Cohen's kappa with quadratic weights. None when undefined (e.g. both raters constant)."""
    _check(a, b)
    n = len(a)
    if n == 0:
        return None
    idx = {c: i for i, c in enumerate(categories)}
    k = len(categories)
    observed = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        observed[idx[x]][idx[y]] += 1
    row = [sum(r) for r in observed]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    weight = [[((i - j) ** 2) / ((k - 1) ** 2) for j in range(k)] for i in range(k)]
    num = sum(weight[i][j] * observed[i][j] for i in range(k) for j in range(k))
    den = sum(weight[i][j] * row[i] * col[j] / n for i in range(k) for j in range(k))
    if den == 0:
        return None
    return 1 - num / den


def agreement_rates(a: Sequence[int], b: Sequence[int]) -> dict[str, float]:
    _check(a, b)
    n = max(len(a), 1)
    return {
        "exact": sum(1 for x, y in zip(a, b, strict=True) if x == y) / n,
        "within_one": sum(1 for x, y in zip(a, b, strict=True) if abs(x - y) <= 1) / n,
    }
