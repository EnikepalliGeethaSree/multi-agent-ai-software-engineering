"""Money helpers. All amounts are integer cents."""

from __future__ import annotations


def to_cents(amount: str) -> int:
    """Parse a decimal string such as "12.50" into cents (1250)."""
    units, _, fraction = amount.strip().partition(".")
    fraction = (fraction + "00")[:2]
    return int(units) * 100 + int(fraction)


def apply_tax(cents: int, rate_percent: int) -> int:
    """Add tax given as a whole percentage, e.g. apply_tax(1000, 18) -> 1180."""
    if rate_percent < 0:
        raise ValueError("rate_percent must not be negative")
    return cents + (cents * rate_percent + 50) // 100


def format_cents(cents: int) -> str:
    """Render cents as a price string, e.g. 1180 -> "11.80"."""
    return f"{cents // 100}.{cents % 100:02d}"
