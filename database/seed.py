"""
database/seed.py

Loads the bundled sample_transactions.csv into the database, running it
through the same parsing -> categorization -> storage -> recurring-detection
pipeline as a real upload, and sets up default demo budgets and a goal so the
dashboard, budgets, and goals tabs all have something to show immediately.
"""

import os

from database.db import get_cursor, reset_db
from services.parser import parse_csv_bytes
from services.categorizer import categorize_transactions
from services.recurring import detect_recurring_from_db
from services.analytics import set_budget
from services.goals import create_goal, get_goals

SAMPLE_CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample_transactions.csv")

DEFAULT_BUDGETS = {
    "Food": 8000,
    "Shopping": 6000,
    "Transport": 5000,
    "Entertainment": 3000,
    "Bills": 4000,
    "Subscriptions": 2000,
    "Healthcare": 3000,
}


def store_transactions(transactions):
    with get_cursor(commit=True) as cur:
        for t in transactions:
            cur.execute(
                "INSERT INTO transactions (date, description, amount, category, "
                "transaction_type, account, normalized_merchant) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    t["date"],
                    t["description"],
                    t["amount"],
                    t.get("category", "Other"),
                    t["transaction_type"],
                    t.get("account", "default"),
                    t.get("normalized_merchant"),
                ),
            )


def load_sample_data(reset_first: bool = True):
    """Loads the bundled sample CSV plus default budgets/goal. Used by the 'Load Demo Data' button."""
    if reset_first:
        reset_db()

    with open(SAMPLE_CSV_PATH, "rb") as f:
        file_bytes = f.read()

    result = parse_csv_bytes(file_bytes)
    if not result.ok:
        raise RuntimeError(f"Failed to parse sample data: {result.errors}")

    categorized = categorize_transactions(result.transactions)
    store_transactions(categorized)
    detect_recurring_from_db()

    for category, limit in DEFAULT_BUDGETS.items():
        set_budget(category, limit)

    if not get_goals():
        create_goal("Emergency Fund", 50000, "2027-03-01", 20000)
        create_goal("New Laptop", 65000, "2026-12-01", 15000)

    return len(categorized)
