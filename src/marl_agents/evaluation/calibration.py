"""Small, transparent calibration: L2-regularised logistic regression by Newton's method.

Used to set the hunk-risk weights from the CodeReviewer *validation* split (never the test split).
A handful of named coefficients, printed and documented, not a black-box model.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (tiny dense systems)."""
    n = len(b)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ValueError("singular system")
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_logistic(
    x: Sequence[Sequence[float]],
    y: Sequence[int],
    l2: float = 1.0,
    max_iter: int = 50,
    tol: float = 1e-8,
) -> tuple[float, list[float]]:
    """Return (intercept, coefficients). The intercept is not regularised."""
    k = len(x[0]) if x else 0
    w = [0.0] * (k + 1)  # w[0] = intercept
    rows = [[1.0, *map(float, r)] for r in x]
    for _ in range(max_iter):
        grad = [0.0] * (k + 1)
        hess = [[0.0] * (k + 1) for _ in range(k + 1)]
        for r, t in zip(rows, y, strict=True):
            p = _sigmoid(sum(wi * xi for wi, xi in zip(w, r, strict=True)))
            for i in range(k + 1):
                grad[i] += (p - t) * r[i]
                for j in range(i, k + 1):
                    hess[i][j] += p * (1 - p) * r[i] * r[j]
        for i in range(k + 1):
            for j in range(i):
                hess[i][j] = hess[j][i]
            if i:
                grad[i] += l2 * w[i]
                hess[i][i] += l2
        step = _solve(hess, grad)
        w = [wi - si for wi, si in zip(w, step, strict=True)]
        if max(abs(s) for s in step) < tol:
            break

    return w[0], w[1:]


def predict(intercept: float, coef: Sequence[float], row: Sequence[float]) -> float:
    return _sigmoid(intercept + sum(c * v for c, v in zip(coef, row, strict=True)))
