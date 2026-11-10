"""Statistics for every results table: intervals and paired tests.

- `wilson`: Wilson score 95% interval for a proportion (recall, precision, detection rate, Top-k).
  Unlike the normal approximation it stays inside [0, 1] and behaves at 0/n and n/n, which matters
  for small benchmarks such as the 17 planted issues.
- `mcnemar`: exact two-sided McNemar test for paired yes/no outcomes on the same items (e.g. which
  planted issues configurations A and C found). Only discordant items carry information.
- `paired_bootstrap`: difference of means between two configurations scored on the same samples,
  with a percentile interval from resampling *samples* (both scores of a sample move together).
  Used for BLEU-4, ROUGE-L, chrF and coverage, which are all means of per-sample scores.

All results are Pydantic models so they can be stored in metrics files and shown by the dashboard.
Each function is tested against hand-computed values (tests/unit/evaluation/test_stats.py).
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

from pydantic import BaseModel

from marl_agents.evaluation.metrics.localization import mcnemar_exact
from marl_agents.evaluation.metrics.text import chrf, rouge_l, sentence_bleu

Z95 = 1.959963984540054
N_BOOT = 1000
SEED = 42


class Proportion(BaseModel):
    """k of n, with its Wilson interval. `value`, `low` and `high` are None when n = 0."""

    k: int
    n: int
    value: float | None
    low: float | None
    high: float | None

    def text(self, digits: int = 3) -> str:
        if self.value is None:
            return f"N/A ({self.k}/{self.n})"
        return (
            f"{self.value:.{digits}f} ({self.k}/{self.n}; 95% CI "
            f"{self.low:.{digits}f}-{self.high:.{digits}f})"
        )


def wilson(k: int, n: int, z: float = Z95) -> Proportion:
    """Wilson score interval for k successes out of n."""
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    if n == 0:
        return Proportion(k=0, n=0, value=None, low=None, high=None)
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return Proportion(k=k, n=n, value=p, low=max(0.0, centre - half), high=min(1.0, centre + half))


class McNemar(BaseModel):
    """Paired yes/no outcomes of A and B on the same items."""

    n: int
    both: int
    only_a: int
    only_b: int
    neither: int
    p_value: float

    def text(self, a: str = "A", b: str = "B") -> str:
        return (
            f"{a} vs {b}: only {a} {self.only_a}, only {b} {self.only_b}, both {self.both}, "
            f"neither {self.neither}; exact McNemar p = {self.p_value:.3f} (n = {self.n})"
        )


def mcnemar(a: Sequence[bool], b: Sequence[bool]) -> McNemar:
    """Exact two-sided McNemar test; `a[i]` and `b[i]` are outcomes on the same item."""
    pairs = list(zip(a, b, strict=True))
    only_a = sum(1 for x, y in pairs if x and not y)
    only_b = sum(1 for x, y in pairs if y and not x)
    return McNemar(
        n=len(pairs),
        both=sum(1 for x, y in pairs if x and y),
        only_a=only_a,
        only_b=only_b,
        neither=sum(1 for x, y in pairs if not x and not y),
        p_value=mcnemar_exact(only_a, only_b),
    )


class PairedDiff(BaseModel):
    """mean(b) - mean(a) over paired samples, with a percentile bootstrap interval."""

    n: int
    mean_a: float
    mean_b: float
    diff: float
    low: float
    high: float
    p_value: float  # two-sided: share of resampled differences on the other side of zero, x2
    n_boot: int
    seed: int

    def text(self, digits: int = 2) -> str:
        return (
            f"{self.diff:+.{digits}f} (95% CI {self.low:+.{digits}f} to {self.high:+.{digits}f}, "
            f"bootstrap p = {self.p_value:.3f}, n = {self.n})"
        )


def paired_bootstrap(
    a: Sequence[float], b: Sequence[float], n_boot: int = N_BOOT, seed: int = SEED
) -> PairedDiff:
    """Paired bootstrap of the difference of means (b - a), resampling samples with replacement."""
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    n = len(a)
    if n == 0:
        raise ValueError("no samples")
    deltas = [float(y) - float(x) for x, y in zip(a, b, strict=True)]
    rng = random.Random(seed)
    boots = sorted(sum(deltas[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = boots[int(0.025 * n_boot)]
    hi = boots[min(int(0.975 * n_boot), n_boot - 1)]
    observed = sum(deltas) / n
    if observed == 0 and all(d == 0 for d in deltas):
        p = 1.0
    else:
        below = sum(1 for x in boots if x <= 0) / n_boot
        above = sum(1 for x in boots if x >= 0) / n_boot
        p = min(1.0, 2 * min(below, above))
    return PairedDiff(
        n=n, mean_a=sum(map(float, a)) / n, mean_b=sum(map(float, b)) / n, diff=observed,
        low=lo, high=hi, p_value=p, n_boot=n_boot, seed=seed,
    )  # fmt: skip


def comment_scores(reference: str, comment: str) -> dict[str, float]:
    """Per-sample comment scores on the reporting scales: BLEU-4, ROUGE-L, chrF 0-100; coverage 0/1.

    Coverage = 1 when the configuration produced a comment for the sample (a non-empty top finding),
    0 otherwise. Averaged over samples it is the share of samples with a comment; an empty comment
    scores 0 on the text metrics.
    """
    return {
        "bleu4": 100 * sentence_bleu(reference, comment),
        "rouge_l": 100 * rouge_l(reference, comment),
        "chrf": 100 * chrf(reference, comment),
        "coverage": 1.0 if comment else 0.0,
    }
