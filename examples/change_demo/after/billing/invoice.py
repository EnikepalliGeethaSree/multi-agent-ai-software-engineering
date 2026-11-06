"""Invoice assembly."""

from __future__ import annotations

from billing.pricing import line_total, price_with_tax


def invoice_total(lines: list[tuple[int, int]], rate_percent: int) -> int:
    """Gross total of (unit_cents, quantity) lines."""
    net = sum(line_total(unit, qty) for unit, qty in lines)
    return price_with_tax(net, rate_percent)
