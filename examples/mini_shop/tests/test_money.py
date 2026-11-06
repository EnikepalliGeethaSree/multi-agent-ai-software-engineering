from shop.money import apply_tax, format_cents, to_cents


def test_to_cents() -> None:
    assert to_cents("12.5") == 1250


def test_apply_tax() -> None:
    assert apply_tax(1000, 18) == 1180


def test_format_cents() -> None:
    assert format_cents(1180) == "11.80"
