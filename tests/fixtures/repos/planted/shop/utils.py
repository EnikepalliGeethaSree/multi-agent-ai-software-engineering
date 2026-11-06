"""Small, clean helpers (negative control: should produce no bug/security findings)."""

from __future__ import annotations


def slugify(text: str) -> str:
    """Lower-case `text` and join its words with dashes."""
    return "-".join(text.lower().split())


def chunked(items: list[int], size: int) -> list[list[int]]:
    """Split `items` into lists of at most `size` elements."""
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i : i + size] for i in range(0, len(items), size)]


def clamp(value: float, low: float, high: float) -> float:
    """Clamp `value` to the closed interval [low, high]."""
    if low > high:
        raise ValueError("low must not exceed high")
    return max(low, min(high, value))
