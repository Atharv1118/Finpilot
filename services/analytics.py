"""
services/analytics.py

All numeric financial calculations live here: monthly income/expense summaries,
category breakdowns, budget-vs-actual comparisons, and month-to-month trends.

Every function returns plain dicts/lists of real, calculated numbers -- these
are the "ground truth" that the AI assistant's tools read from. Nothing here
ever calls an LLM.
"""

from datetime import datetime
from typing import List, Dict, Optional
from collections import defaultdict

from database.db import get_cursor


def _all_transactions() -> List[Dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, date, description, amount, category, transaction_type, "
            "is_recurring, normalized_merchant FROM transactions ORDER BY date"
        )
        return [dict(r) for r in cur.fetchall()]


def list_available_months() -> List[str]:
    txns = _all_transactions()
    months = sorted({t["date"][:7] for t in txns}, reverse=True)
    return months


def get_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    merchant: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
) -> List[Dict]:
    txns = _all_transactions()
    if start_date:
        txns = [t for t in txns if t["date"] >= start_date]
    if end_date:
        txns = [t for t in txns if t["date"] <= end_date]
    if category:
        txns = [t for t in txns if t["category"].lower() == category.lower()]
    if merchant:
        txns = [t for t in txns if merchant.lower() in (t["normalized_merchant"] or "").lower()]
    if min_amount is not None:
        txns = [t for t in txns if t["amount"] >= min_amount]
    if max_amount is not None:
        txns = [t for t in txns if t["amount"] <= max_amount]
    return txns


def get_category_spending(month: Optional[str] = None) -> List[Dict]:
    """Returns [{category, total}] for debit transactions, sorted descending."""
    txns = _all_transactions()
    if month:
        txns = [t for t in txns if t["date"].startswith(month)]

    totals = defaultdict(float)
    for t in txns:
        if t["transaction_type"] == "debit":
            totals[t["category"]] += t["amount"]

    return sorted(
        [{"category": k, "total": round(v, 2)} for k, v in totals.items()],
        key=lambda x: x["total"],
        reverse=True,
    )


def get_monthly_summary(month: str) -> Dict:
    """
    month: 'YYYY-MM'
    Returns income, expenses, surplus, savings rate, top category, largest
    transaction, and category breakdown for the given month.
    """
    txns = [t for t in _all_transactions() if t["date"].startswith(month)]

    income = sum(t["amount"] for t in txns if t["transaction_type"] == "credit")
    expenses = sum(t["amount"] for t in txns if t["transaction_type"] == "debit")
    surplus = income - expenses
    savings_rate = (surplus / income * 100) if income > 0 else 0.0

    category_breakdown = get_category_spending(month)
    top_category = category_breakdown[0] if category_breakdown else None

    debit_txns = [t for t in txns if t["transaction_type"] == "debit"]
    largest_txn = max(debit_txns, key=lambda t: t["amount"], default=None)

    return {
        "month": month,
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "surplus": round(surplus, 2),
        "savings_rate_pct": round(savings_rate, 1),
        "top_category": top_category,
        "largest_transaction": largest_txn,
        "category_breakdown": category_breakdown,
        "transaction_count": len(txns),
    }


def compare_months(month_a: str, month_b: str) -> Dict:
    """
    Compares category-level spending between two months (month_a vs month_b).
    Returns which categories increased/decreased and by how much.
    """
    cats_a = {c["category"]: c["total"] for c in get_category_spending(month_a)}
    cats_b = {c["category"]: c["total"] for c in get_category_spending(month_b)}

    all_categories = set(cats_a) | set(cats_b)
    changes = []
    for cat in all_categories:
        a = cats_a.get(cat, 0.0)
        b = cats_b.get(cat, 0.0)
        diff = a - b
        pct = (diff / b * 100) if b > 0 else (100.0 if a > 0 else 0.0)
        changes.append(
            {
                "category": cat,
                f"{month_a}_total": round(a, 2),
                f"{month_b}_total": round(b, 2),
                "difference": round(diff, 2),
                "pct_change": round(pct, 1),
            }
        )

    changes.sort(key=lambda c: c["difference"], reverse=True)
    return {"month_a": month_a, "month_b": month_b, "changes": changes}


def get_monthly_trend() -> List[Dict]:
    """Returns [{month, income, expenses, surplus}] across all available months."""
    months = list_available_months()
    trend = []
    for m in sorted(months):
        summary = get_monthly_summary(m)
        trend.append(
            {
                "month": m,
                "income": summary["income"],
                "expenses": summary["expenses"],
                "surplus": summary["surplus"],
            }
        )
    return trend


def average_monthly_surplus(last_n_months: int = 3) -> float:
    trend = get_monthly_trend()
    if not trend:
        return 0.0
    recent = trend[-last_n_months:]
    return round(sum(t["surplus"] for t in recent) / len(recent), 2)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

def set_budget(category: str, monthly_limit: float):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?) "
            "ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit",
            (category, monthly_limit),
        )


def delete_budget(category: str):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM budgets WHERE category = ?", (category,))


def get_budgets() -> List[Dict]:
    with get_cursor() as cur:
        cur.execute("SELECT category, monthly_limit FROM budgets ORDER BY category")
        return [dict(r) for r in cur.fetchall()]


def get_budget_status(month: str) -> List[Dict]:
    """
    Returns per-category budget vs actual for the given month:
    [{category, monthly_limit, spent, pct_used, remaining, over_budget}]
    """
    budgets = {b["category"]: b["monthly_limit"] for b in get_budgets()}
    spending = {c["category"]: c["total"] for c in get_category_spending(month)}

    status = []
    for category, limit in budgets.items():
        spent = spending.get(category, 0.0)
        pct_used = (spent / limit * 100) if limit > 0 else 0.0
        status.append(
            {
                "category": category,
                "monthly_limit": limit,
                "spent": round(spent, 2),
                "pct_used": round(pct_used, 1),
                "remaining": round(limit - spent, 2),
                "over_budget": spent > limit,
            }
        )
    return sorted(status, key=lambda s: s["pct_used"], reverse=True)


def get_budget_commitment_summary(month: str) -> Dict:
    """
    Summarizes how much of total budget is already committed/spent this month,
    including recurring obligations.
    """
    from services.recurring import total_monthly_recurring

    status = get_budget_status(month)
    total_budget = sum(s["monthly_limit"] for s in status)
    total_spent = sum(s["spent"] for s in status)
    recurring = total_monthly_recurring()

    return {
        "month": month,
        "total_budget": round(total_budget, 2),
        "total_spent": round(total_spent, 2),
        "remaining_budget": round(total_budget - total_spent, 2),
        "pct_committed": round((total_spent / total_budget * 100) if total_budget > 0 else 0.0, 1),
        "monthly_recurring_expenses": recurring,
        "categories": status,
    }
