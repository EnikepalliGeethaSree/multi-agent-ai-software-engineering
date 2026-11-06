"""Binary classification metrics (quality estimation, planted-issue detection)."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class BinaryMetrics(BaseModel):
    n: int
    tp: int
    fp: int
    tn: int
    fn: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    positive_rate: float


def _safe(num: float, den: float) -> float:
    return num / den if den else 0.0


def binary_metrics(y_true: Sequence[int], y_pred: Sequence[int]) -> BinaryMetrics:
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred differ in length")
    tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == 0 and p == 1)
    tn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == 0 and p == 0)
    fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == 1 and p == 0)
    n = len(y_true)
    precision = _safe(tp, tp + fp)
    recall = _safe(tp, tp + fn)
    return BinaryMetrics(
        n=n,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        accuracy=_safe(tp + tn, n),
        precision=precision,
        recall=recall,
        f1=_safe(2 * precision * recall, precision + recall),
        positive_rate=_safe(tp + fp, n),
    )


def roc_auc(y_true: Sequence[int], scores: Sequence[float]) -> float | None:
    """AUC-ROC via the Mann-Whitney U statistic (ties count 1/2). None if one class is absent."""
    pos = [s for t, s in zip(y_true, scores, strict=True) if t == 1]
    neg = [s for t, s in zip(y_true, scores, strict=True) if t == 0]
    if not pos or not neg:
        return None
    # Rank-based O(n log n): average ranks for ties.
    ordered = sorted((s, t) for s, t in zip(scores, y_true, strict=True))
    ranks = [0.0] * len(ordered)
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rank_sum_pos = sum(r for r, (_, t) in zip(ranks, ordered, strict=True) if t == 1)
    u = rank_sum_pos - len(pos) * (len(pos) + 1) / 2
    return u / (len(pos) * len(neg))


def bootstrap_ci(
    values: Sequence[T],
    statistic: Callable[[list[T]], float],
    n_boot: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval of `statistic` over resampled `values`."""
    rng = random.Random(seed)
    items = list(values)
    if not items:
        return (math.nan, math.nan)
    stats = sorted(
        statistic([items[rng.randrange(len(items))] for _ in items]) for _ in range(n_boot)
    )
    lo = stats[int((alpha / 2) * n_boot)]
    hi = stats[min(int((1 - alpha / 2) * n_boot), n_boot - 1)]
    return (lo, hi)
