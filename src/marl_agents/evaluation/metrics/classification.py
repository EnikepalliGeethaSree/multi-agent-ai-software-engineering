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


def average_precision(y_true: Sequence[int], scores: Sequence[float]) -> float | None:
    """PR-AUC as average precision: sum over score thresholds of (R_k - R_k-1) * P_k.

    Tied scores form one threshold (as in scikit-learn). Its chance level is the positive base
    rate. None when there is no positive example.
    """
    pairs = sorted(zip(scores, y_true, strict=True), key=lambda x: -x[0])
    n_pos = sum(1 for _, t in pairs if t == 1)
    if not n_pos:
        return None
    ap, tp, fp, prev_recall, i = 0.0, 0, 0, 0.0, 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            tp += pairs[j][1] == 1
            fp += pairs[j][1] != 1
            j += 1
        recall = tp / n_pos
        ap += (recall - prev_recall) * (tp / (tp + fp))
        prev_recall, i = recall, j
    return ap


def mcc(m: BinaryMetrics) -> float | None:
    """Matthews correlation coefficient; None when a row or column of the matrix is empty."""
    den = math.sqrt((m.tp + m.fp) * (m.tp + m.fn) * (m.tn + m.fp) * (m.tn + m.fn))
    return (m.tp * m.tn - m.fp * m.fn) / den if den else None


def balanced_accuracy(m: BinaryMetrics) -> float | None:
    """Mean of the true-positive and true-negative rates; None if a class is absent."""
    if not (m.tp + m.fn) or not (m.tn + m.fp):
        return None
    return (m.tp / (m.tp + m.fn) + m.tn / (m.tn + m.fp)) / 2


def brier_score(y_true: Sequence[int], probs: Sequence[float]) -> float | None:
    """Mean squared difference between the predicted probability and the 0/1 label."""
    if not y_true:
        return None
    return sum((p - t) ** 2 for t, p in zip(y_true, probs, strict=True)) / len(y_true)


def precision_at_fraction(
    y_true: Sequence[int], scores: Sequence[float], fraction: float = 0.10
) -> tuple[float, int] | None:
    """Share of positives among the top `fraction` of items by score, and how many items that is.

    The cut is ceil(fraction * n) items; ties at the cut are broken by the original order.
    """
    n = len(y_true)
    if not n:
        return None
    k = max(1, math.ceil(fraction * n))
    order = sorted(range(n), key=lambda i: -scores[i])[:k]
    return sum(y_true[i] for i in order) / k, k


def always_positive(y_true: Sequence[int]) -> dict[str, float]:
    """The flag-everything baseline: precision = accuracy = base rate, recall = 1."""
    base = sum(y_true) / len(y_true) if y_true else 0.0
    return {
        "precision": base,
        "recall": 1.0 if base else 0.0,
        "f1": 2 * base / (1 + base) if base else 0.0,
        "accuracy": base,
    }
