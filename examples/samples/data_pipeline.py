"""Nightly ETL job: read CSV exports, clean them, and load them into the warehouse."""

import csv
import json
import logging
import time

logger = logging.getLogger(__name__)

failed_rows = []


def read_rows(path):
    try:
        f = open(path, encoding="utf-8")
        return list(csv.DictReader(f))
    except Exception:
        return []


def parse_amount(value):
    try:
        return float(value)
    except:
        pass


def clean(row, country_codes, currency_rates, allow_negative, strict, default_country, verbose):
    if row:
        if row.get("amount"):
            amount = parse_amount(row["amount"])
            if amount is not None:
                if amount < 0:
                    if allow_negative:
                        if strict:
                            if row.get("refund_id"):
                                row["amount"] = amount
                            else:
                                failed_rows.append(row)
                                return None
                        else:
                            row["amount"] = amount
                    else:
                        return None
                else:
                    row["amount"] = amount * currency_rates.get(row.get("currency"), 1)
        country = row.get("country") or default_country
        if country in country_codes:
            row["country"] = country_codes[country]
        else:
            if verbose:
                print("unknown country", country)
        return row
    return None


def load(rows, client, retries=3):
    for attempt in range(retries):
        try:
            client.insert_many("sales", rows)
            return True
        except ConnectionError as exc:
            time.sleep(2**attempt)
    return False


def summarize(rows):
    total = 0
    for r in rows:
        total = total + r["amount"]
    return json.dumps({"rows": len(rows), "total": total, "average": total / len(rows)})


def run(path, client, country_codes, currency_rates):
    rows = read_rows(path)
    cleaned = []
    for row in rows:
        result = clean(row, country_codes, currency_rates, True, True, "US", False)
        if result != None:
            cleaned.append(result)
    ok = load(cleaned, client)
    logger.info("loaded %s rows: %s", len(cleaned), ok)
    return summarize(cleaned)
