from shop.pricing import apply_discount, average_price
from shop.utils import chunked, slugify


def test_average_price():
    assert average_price([1, 2, 3]) == 2


def test_apply_discount():
    assert apply_discount(100, 0.1) == 90


def test_utils():
    assert slugify("Hello World") == "hello-world"
    assert chunked([1, 2, 3], 2) == [[1, 2], [3]]
