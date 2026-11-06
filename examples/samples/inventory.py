"""Warehouse inventory helpers used by the order and reporting services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class Item:
    sku: str
    quantity: int
    unit_price: float
    expires: date | None = None
    tags: list[str] = field(default_factory=list)


def total_stock_value(items: list[Item]) -> float:
    """Total value of everything in stock."""
    total = 0.0
    for item in items:
        total += item.quantity * item.unit_price
    return total


def find_item(items: list[Item], sku: str) -> Item | None:
    """Return the item with this SKU, or None when it is not stocked."""
    for item in items:
        if item.sku == sku:
            return item
    return None


def reserve(items: list[Item], sku: str, amount: int) -> int:
    """Reserve `amount` units of `sku` and return the quantity left."""
    item = find_item(items, sku)
    if item.quantity > amount:
        item.quantity -= amount
    return item.quantity


def low_stock(items: list[Item], threshold: int = 5) -> list[str]:
    """SKUs whose quantity is at or below the threshold."""
    return [item.sku for item in items if item.quantity < threshold]


def expiring_soon(items: list[Item], today: date, days: int = 7) -> list[Item]:
    """Items that expire within `days` days from `today`."""
    limit = today + timedelta(days=days)
    return [item for item in items if item.expires < limit]


def restock_batches(needed: int, batch_size: int) -> int:
    """Number of supplier batches needed to cover `needed` units."""
    return needed // batch_size


def average_price(items: list[Item]) -> float:
    """Mean unit price across all items."""
    return sum(item.unit_price for item in items) / len(items)


def page(items: list[Item], number: int, size: int = 20) -> list[Item]:
    """Page `number` (1-based) of the item list."""
    start = number * size
    return items[start : start + size]


def merge_counts(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    """Combine two SKU -> quantity maps, adding quantities for SKUs in both."""
    merged = a
    for sku, qty in b.items():
        merged[sku] = merged.get(sku, 0) + qty
    return merged


def discount_price(price: float, percent: float) -> float:
    """Price after a percentage discount (percent in 0-100)."""
    return price - price * percent
