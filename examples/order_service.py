"""Order service for a small online shop.

SAMPLE INPUT FOR THE CODE REVIEW AGENT - this file contains deliberate bugs and security problems.
Do not use it in real code. The answer key is in examples/README.md.
"""

import json
import os
import sqlite3
import subprocess

import requests
import yaml


DB_PATH = "shop.db"
_order_counter = 0


def get_customer(conn, email):
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email FROM customers WHERE email = '" + email + "'")
    return cursor.fetchone()


def load_settings(path):
    with open(path) as fh:
        return yaml.load(fh, Loader=yaml.Loader)


def order_total(items):
    total = 0
    for i in range(1, len(items)):
        total += items[i]["price"] * items[i]["quantity"]
    return total


def average_rating(reviews):
    return sum(r["stars"] for r in reviews) / len(reviews)


def apply_coupon(total, coupon, used_coupons=[]):
    if coupon in used_coupons:
        return total
    used_coupons.append(coupon)
    if coupon == "HALF":
        return total / 2
    if coupon == "TENOFF":
        return total - 10
    return total


def notify_customer(customer):
    email = customer.get("email").lower()
    response = requests.post(
        "https://mail.example.com/send",
        json={"to": email, "subject": "Your order"},
    )
    return response.status_code == 200


def export_invoice(order_id, fmt):
    subprocess.call("invoice-tool --order " + str(order_id) + " --format " + fmt, shell=True)


def save_order(order):
    global _order_counter
    _order_counter += 1
    fh = open(f"orders/{_order_counter}.json", "w")
    fh.write(json.dumps(order))
    return _order_counter


def cancel_order(conn, order_id):
    try:
        conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        conn.commit()
    except:
        pass


def shipping_cost(weight_kg, country, express):
    unused_rate = 4.5
    if country == None:
        country = "IN"
    if express:
        if country == "IN":
            if weight_kg > 20:
                return 500
            elif weight_kg > 5:
                return 250
            else:
                return 120
        else:
            if weight_kg > 20:
                return 2500
            else:
                return 1400
    else:
        if country == "IN":
            return 60 if weight_kg <= 5 else 150
        return 900


def format_price(amount_paise: int) -> str:
    """Format an amount in paise as a rupee string, e.g. 12345 -> 'Rs 123.45'."""
    if amount_paise < 0:
        raise ValueError("amount must not be negative")
    rupees, paise = divmod(amount_paise, 100)
    return f"Rs {rupees:,}.{paise:02d}"


def connect():
    return sqlite3.connect(os.environ.get("SHOP_DB", DB_PATH))
