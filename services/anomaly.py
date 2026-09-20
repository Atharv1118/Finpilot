"""
services/anomaly.py

Flags unusual (anomalous) spending using simple, explainable rules -- no
statistical models beyond a per-category average:

    A debit transaction is "unusual" if its amount is more than 2x the
    average debit amount for its own category (computed from all other
    transactions in that category).

Returns clear, human-readable explanations for the UI and the AI assistant.
"""

from statistics import mean
from typing import List, Dict
from collections import defaultdict

from database.db import get_cursor

THRESHOLD_MULTIPLIER = 2.0
MIN_SAMPLES_FOR_BASELINE = 2  # need at least this many other txns to trust the average


def detect_unusual_spending(month: str = None) -> List[Dict]:
    """
    month: optional 'YYYY-MM' filter. If omitted, scans all transactions but
    still computes each category's baseline from ALL debit transactions (so a
    single month's anomaly is judged against overall typical spending).
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, date, description, amount, category, normalized_merchant "
            "FROM transactions WHERE transaction_type = 'debit'"
        )
        rows = [dict(r) for r in cur.fetchall()]

    by_category = defaultdict(list)
    for r in rows:
        by_category[r["category"]].append(r)

    anomalies = []
    for category, txns in by_category.items():
        if len(txns) < MIN_SAMPLES_FOR_BASELINE + 1:
            continue

        for target in txns:
            others = [t["amount"] for t in txns if t["id"] != target["id"]]
            if len(others) < MIN_SAMPLES_FOR_BASELINE:
                continue
            baseline = mean(others)
            if baseline <= 0:
                continue

            if month and not target["date"].startswith(month):
                continue

            if target["amount"] > baseline * THRESHOLD_MULTIPLIER:
                anomalies.append(
                    {
                        "id": target["id"],
                        "date": target["date"],
                        "description": target["description"],
                        "merchant": target["normalized_merchant"],
                        "category": category,
                        "amount": target["amount"],
                        "category_average": round(baseline, 2),
                        "explanation": (
                            f"This {category.lower()} transaction (₹{target['amount']:,.0f}) is "
                            f"{target['amount'] / baseline:.1f}x higher than your typical "
                            f"{category.lower()} spending (avg ₹{baseline:,.0f})."
                        ),
                    }
                )

    return sorted(anomalies, key=lambda a: a["amount"], reverse=True)
