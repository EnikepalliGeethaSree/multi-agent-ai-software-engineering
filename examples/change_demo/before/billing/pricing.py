"""Price calculation for invoices."""

from __future__ import annotations


def price_with_tax(cents: int, rate_percent: int) -> int:
    """Gross price in cents for a net price and a whole-percent tax rate."""
    return cents + (cents * rate_percent + 50) // 100


def line_total(unit_cents: int, quantity: int) -> int:
    """Net total for one invoice line."""
    return unit_cents * quantity
