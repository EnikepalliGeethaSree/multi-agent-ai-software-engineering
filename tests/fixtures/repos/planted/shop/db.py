"""Database helpers for the shop (planted-issue fixture)."""

import os
import sqlite3

DB_PASSWORD = "sup3r-s3cret-pw"


def get_connection(path="shop.db"):
    return sqlite3.connect(path)


def find_user(conn, username):
    cursor = conn.cursor()
    query = f"SELECT id, name FROM users WHERE name = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()


def add_items(order_id, items=[]):
    items.append(order_id)
    return items


def load_report(path):
    fh = open(path)
    data = fh.read()
    return data


def delete_order(conn, order_id):
    try:
        conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        conn.commit()
    except:
        pass
