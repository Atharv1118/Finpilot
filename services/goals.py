"""
services/goals.py

Financial goal CRUD and projections (e.g. "Emergency Fund: ₹50,000 by March 2027").
Purely arithmetic -- no investment advice, no recommendations on WHERE to put money,
only what the numbers imply about pace given current spending behavior.
"""

from datetime import datetime
from typing import List, Dict

from database.db import get_cursor
from services.analytics import average_monthly_surplus


def create_goal(name: str, target_amount: float, target_date: str, current_saved: float = 0.0) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO goals (name, target_amount, target_date, current_saved) VALUES (?, ?, ?, ?)",
            (name, target_amount, target_date, current_saved),
        )
        return cur.lastrowid


def update_goal_savings(goal_id: int, current_saved: float):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE goals SET current_saved = ? WHERE id = ?", (current_saved, goal_id))


def delete_goal(goal_id: int):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM goals WHERE id = ?", (goal_id,))


def get_goals() -> List[Dict]:
    with get_cursor() as cur:
        cur.execute("SELECT id, name, target_amount, target_date, current_saved FROM goals ORDER BY target_date")
        return [dict(r) for r in cur.fetchall()]


def _months_between(today: datetime, target: datetime) -> int:
    months = (target.year - today.year) * 12 + (target.month - today.month)
    return max(months, 1)


def analyze_goal(goal: Dict) -> Dict:
    """
    Returns the goal enriched with:
        remaining_amount, months_left, required_monthly_saving,
        average_monthly_surplus, status ('on_track' | 'at_risk' | 'achieved'),
        explanation (plain-language, deterministic -- no LLM needed)
    """
    today = datetime.today()
    try:
        target_date = datetime.strptime(goal["target_date"], "%Y-%m-%d")
    except ValueError:
        target_date = today

    remaining_amount = max(goal["target_amount"] - goal["current_saved"], 0.0)
    months_left = _months_between(today, target_date)
    required_monthly = remaining_amount / months_left if months_left > 0 else remaining_amount
    surplus = average_monthly_surplus()

    if remaining_amount <= 0:
        status = "achieved"
        explanation = f"You've already reached your '{goal['name']}' goal. 🎉"
    elif surplus >= required_monthly:
        status = "on_track"
        explanation = (
            f"You need approximately ₹{required_monthly:,.0f}/month to reach this goal. "
            f"Your recent average monthly surplus is ₹{surplus:,.0f}. "
            f"Based on your recent spending pattern, this goal is within your projected monthly surplus."
        )
    else:
        status = "at_risk"
        shortfall = required_monthly - surplus
        explanation = (
            f"You need approximately ₹{required_monthly:,.0f}/month to reach this goal, "
            f"but your recent average monthly surplus is only ₹{surplus:,.0f} "
            f"(a shortfall of ₹{shortfall:,.0f}/month). At the current pace, you may not reach "
            f"this goal by {goal['target_date']} unless spending is reduced or the timeline is extended."
        )

    return {
        **goal,
        "remaining_amount": round(remaining_amount, 2),
        "months_left": months_left,
        "required_monthly_saving": round(required_monthly, 2),
        "average_monthly_surplus": surplus,
        "status": status,
        "explanation": explanation,
    }


def get_goal_status() -> List[Dict]:
    return [analyze_goal(g) for g in get_goals()]
