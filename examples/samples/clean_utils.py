"""Small, well-tested text and number helpers (negative control: no defects expected)."""

from __future__ import annotations

import re
from collections.abc import Iterable

_SLUG_INVALID = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_length: int = 60) -> str:
    """Lowercase URL slug made of letters, digits and single hyphens.

    >>> slugify("Hello, World!")
    'hello-world'
    """
    slug = _SLUG_INVALID.sub("-", text.lower()).strip("-")
    return slug[:max_length].rstrip("-")


def chunked(values: list[int], size: int) -> list[list[int]]:
    """Split `values` into consecutive lists of at most `size` items."""
    if size <= 0:
        raise ValueError("size must be positive")
    return [values[i : i + size] for i in range(0, len(values), size)]


def safe_mean(values: Iterable[float]) -> float | None:
    """Arithmetic mean, or None for an empty input."""
    items = list(values)
    if not items:
        return None
    return sum(items) / len(items)


def clamp(value: float, low: float, high: float) -> float:
    """Limit `value` to the closed interval [low, high]."""
    if low > high:
        raise ValueError("low must not exceed high")
    return max(low, min(value, high))


def percent(part: float, whole: float) -> float:
    """`part` as a percentage of `whole`; 0.0 when `whole` is 0."""
    if whole == 0:
        return 0.0
    return 100.0 * part / whole


def truncate(text: str, width: int, suffix: str = "...") -> str:
    """Shorten `text` to at most `width` characters, ending with `suffix` when cut."""
    if width < len(suffix):
        raise ValueError("width is smaller than the suffix")
    if len(text) <= width:
        return text
    return text[: width - len(suffix)] + suffix
