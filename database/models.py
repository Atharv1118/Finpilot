"""
database/models.py

Lightweight dataclasses describing FinPilot's core entities.
These are NOT an ORM layer -- database/db.py uses raw sqlite3 for simplicity.
The dataclasses exist purely for type-hinting and readability across services.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Transaction:
    id: Optional[int]
    date: str  # ISO format YYYY-MM-DD
    description: str
    amount: float  # always positive; sign is carried by transaction_type
    category: str
    transaction_type: str  # 'debit' or 'credit'
    is_recurring: bool
    account: str
    normalized_merchant: Optional[str]


@dataclass
class Budget:
    id: Optional[int]
    category: str
    monthly_limit: float


@dataclass
class Goal:
    id: Optional[int]
    name: str
    target_amount: float
    target_date: str  # ISO format YYYY-MM-DD
    current_saved: float


@dataclass
class Subscription:
    id: Optional[int]
    merchant: str
    amount: float
    frequency: str
    next_expected_date: Optional[str]


CATEGORIES = [
    "Food",
    "Shopping",
    "Transport",
    "Bills",
    "Subscriptions",
    "Healthcare",
    "Education",
    "Entertainment",
    "Rent",
    "Utilities",
    "Salary",
    "Transfer",
    "Other",
]

# Categories that represent money coming IN rather than going out.
INCOME_CATEGORIES = {"Salary", "Transfer"}
