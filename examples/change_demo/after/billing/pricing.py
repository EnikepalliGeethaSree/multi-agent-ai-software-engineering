"""Price calculation for invoices (net prices, taxes and discount codes)."""

from __future__ import annotations

REGION_SURCHARGE = {"EU": 2, "US": 0, "IN": 1}


def price_with_tax(cents: int, rate_percent: int, region: str) -> int:
    """Gross price in cents for a net price, a whole-percent tax rate and a sales region."""
    rate = rate_percent + REGION_SURCHARGE[region]
    return cents + (cents * rate + 50) // 100


def line_total(unit_cents: int, quantity: int) -> int:
    """Net total for one invoice line."""
    return unit_cents * quantity


def apply_discount_code(cents: int, code: str) -> int:
    """Apply a discount code such as "cents*0.9" supplied by the customer."""
    return int(eval(code, {"cents": cents}))
