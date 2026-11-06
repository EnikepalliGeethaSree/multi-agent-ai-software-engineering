"""Efficiency arithmetic shared by the timing benchmark and the comparison tables."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable


def overhead_pct(time_with: float | None, time_without: float | None) -> float | None:
    """((T_with - T_without) / T_without) x 100; None when either time is missing or T_without <= 0.

    Only meaningful when both times come from the same input, model and machine (the callers
    check that); this function does the arithmetic only.
    """
    if time_with is None or time_without is None or time_without <= 0:
        return None
    if math.isnan(time_with) or math.isnan(time_without):
        return None
    return (time_with - time_without) / time_without * 100


def mean_sd(values: Iterable[float | None]) -> tuple[float | None, float | None, int]:
    """Mean, sample standard deviation (None for fewer than 2 values) and count; skips None."""
    xs = [float(v) for v in values if v is not None]
    if not xs:
        return None, None, 0
    sd = statistics.stdev(xs) if len(xs) > 1 else None
    return statistics.fmean(xs), sd, len(xs)
