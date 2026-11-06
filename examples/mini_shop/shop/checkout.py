"""Checkout: turn a cart into an order total and a receipt."""

from __future__ import annotations

from shop.money import apply_tax, format_cents
from shop.users import get_user

TAX_RATE = 0.18


def cart_total(prices: list[float]) -> float:
    total = 0.0
    for price in prices:
        total += price
    return total


def checkout(user_id: int, prices: list[float]) -> str:
    user = get_user(user_id)
    subtotal = cart_total(prices)
    total = apply_tax(subtotal, TAX_RATE)
    return f"Receipt for {user['email']}: {format_cents(total)}"


def save_receipt(receipt: str, path: str) -> int:
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(receipt + "\n")
        return 0
    except OSError:
        return -1
