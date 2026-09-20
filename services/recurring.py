"""
services/recurring.py

Detects recurring payments (subscriptions, rent, bills, etc.) using a simple,
explainable heuristic -- NOT machine learning:

    A normalized merchant is "recurring" if it appears at least twice with
    amounts within ~15% of each other, and the gap between consecutive
    occurrences is roughly monthly (24-40 days) on average.

Writes results to the `subscriptions` table and flags matching rows in
`transactions.is_recurring`.
"""

from datetime import datetime, timedelta
from statistics import mean
from typing import List, Dict
from collections import defaultdict

from database.db import get_cursor

MIN_OCCURRENCES = 2
AMOUNT_TOLERANCE = 0.15  # 15%
MIN_GAP_DAYS = 20
MAX_GAP_DAYS = 40


def _amounts_similar(amounts: List[float]) -> bool:
    avg = mean(amounts)
    if avg == 0:
        return False
    return all(abs(a - avg) / avg <= AMOUNT_TOLERANCE for a in amounts)


def _gaps_regular(dates: List[datetime]) -> bool:
    dates = sorted(dates)
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    if not gaps:
        return False
    return all(MIN_GAP_DAYS <= g <= MAX_GAP_DAYS for g in gaps)


def detect_recurring_from_db() -> List[Dict]:
    """
    Scans all stored transactions, detects recurring merchants, updates
    transactions.is_recurring, refreshes the subscriptions table, and returns a
    summary list of detected subscriptions.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, date, amount, normalized_merchant, transaction_type FROM transactions "
            "WHERE transaction_type = 'debit'"
        )
        rows = [dict(r) for r in cur.fetchall()]

    grouped = defaultdict(list)
    for r in rows:
        merchant = r["normalized_merchant"] or "Unknown"
        grouped[merchant].append(r)

    detected = []
    recurring_txn_ids = []

    for merchant, txns in grouped.items():
        if len(txns) < MIN_OCCURRENCES:
            continue

        amounts = [t["amount"] for t in txns]
        try:
            dates = [datetime.strptime(t["date"], "%Y-%m-%d") for t in txns]
        except ValueError:
            continue

        if _amounts_similar(amounts) and _gaps_regular(dates):
            avg_amount = round(mean(amounts), 2)
            latest_date = max(dates)
            next_expected = (latest_date + timedelta(days=30)).strftime("%Y-%m-%d")

            detected.append(
                {
                    "merchant": merchant,
                    "amount": avg_amount,
                    "frequency": "monthly",
                    "next_expected_date": next_expected,
                    "occurrences": len(txns),
                }
            )
            recurring_txn_ids.extend(t["id"] for t in txns)

    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE transactions SET is_recurring = 0")
        if recurring_txn_ids:
            cur.executemany(
                "UPDATE transactions SET is_recurring = 1 WHERE id = ?",
                [(i,) for i in recurring_txn_ids],
            )
        cur.execute("DELETE FROM subscriptions")
        for d in detected:
            cur.execute(
                "INSERT INTO subscriptions (merchant, amount, frequency, next_expected_date) "
                "VALUES (?, ?, ?, ?)",
                (d["merchant"], d["amount"], d["frequency"], d["next_expected_date"]),
            )

    return sorted(detected, key=lambda d: d["amount"], reverse=True)


def get_subscriptions() -> List[Dict]:
    with get_cursor() as cur:
        cur.execute("SELECT merchant, amount, frequency, next_expected_date FROM subscriptions ORDER BY amount DESC")
        return [dict(r) for r in cur.fetchall()]


def total_monthly_recurring() -> float:
    subs = get_subscriptions()
    return round(sum(s["amount"] for s in subs), 2)
