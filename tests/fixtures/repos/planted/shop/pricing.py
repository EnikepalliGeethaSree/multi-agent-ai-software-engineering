"""Pricing rules (planted-issue fixture)."""


def compute_price(base, qty, customer_type, coupon, region, season, loyalty_years, currency):
    price = base * qty
    if customer_type == "vip":
        if region == "eu":
            if season == "winter":
                if loyalty_years > 5:
                    if coupon:
                        price *= 0.5
                    else:
                        price *= 0.6
                else:
                    price *= 0.7
            elif season == "summer":
                price *= 0.8
            else:
                price *= 0.9
        elif region == "us":
            if coupon:
                price *= 0.75
            else:
                price *= 0.85
        else:
            price *= 0.95
    elif customer_type == "staff":
        price *= 0.5 if qty < 10 else 0.4
    elif customer_type == "new":
        if coupon == "WELCOME":
            price -= 5
        elif coupon == "FRIEND":
            price -= 3
    if currency == "eur":
        price *= 0.92
    elif currency == "gbp":
        price *= 0.79
    return price


def average_price(prices):
    return sum(prices) / len(prices)


def apply_discount(price, discount):
    if discount == None:
        return price
    return price - price * discount


def parse_quantity(text):
    try:
        return int(text)
    except Exception:
        return None


def total_with_tax(price):
    return price * (1 + TAX_RATE)
