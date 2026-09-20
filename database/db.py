"""
database/db.py

SQLite connection handling and schema creation for FinPilot.
Uses plain sqlite3 (no ORM) to keep the project simple and dependency-light.
"""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "finpilot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT DEFAULT 'Other',
    transaction_type TEXT DEFAULT 'debit',
    is_recurring INTEGER DEFAULT 0,
    account TEXT DEFAULT 'default',
    normalized_merchant TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL UNIQUE,
    monthly_limit REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_amount REAL NOT NULL,
    target_date TEXT NOT NULL,
    current_saved REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant TEXT NOT NULL,
    amount REAL NOT NULL,
    frequency TEXT DEFAULT 'monthly',
    next_expected_date TEXT
);

CREATE TABLE IF NOT EXISTS merchant_cache (
    merchant TEXT PRIMARY KEY,
    category TEXT NOT NULL
);
"""


def get_connection():
    """Return a new SQLite connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_cursor(commit: bool = False):
    """Context manager yielding a cursor; commits and closes automatically."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()


def init_db():
    """Create all tables if they do not already exist. Safe to call repeatedly."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def reset_db():
    """Danger: wipes all transactional data. Used only by the 'reset demo' button."""
    conn = get_connection()
    try:
        conn.executescript(
            """
            DELETE FROM transactions;
            DELETE FROM subscriptions;
            DELETE FROM merchant_cache;
            """
        )
        conn.commit()
    finally:
        conn.close()
