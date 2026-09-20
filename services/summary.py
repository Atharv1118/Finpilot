"""
services/summary.py

Builds the "Monthly Financial Summary" -- income, expenses, savings, top
category, largest transaction, recurring expenses, budget status, unusual
transactions, and goal progress -- combining all other services' outputs.

All numbers come from deterministic calculations (services/analytics.py etc).
An LLM is used ONLY to phrase the "Key observations" and "Action items" text
in natural language, grounded strictly in the facts computed below. If no LLM
is configured, a deterministic template produces the same sections without it.
"""

from typing import Dict

from services.analytics import get_monthly_summary, get_budget_status, compare_months, list_available_months
from services.recurring import get_subscriptions, total_monthly_recurring
from services.anomaly import detect_unusual_spending
from services.goals import get_goal_status


def _previous_month(month: str) -> str:
    months = sorted(list_available_months())
    if month in months:
        idx = months.index(month)
        if idx > 0:
            return months[idx - 1]
    return None


def build_summary_facts(month: str) -> Dict:
    """Gathers every deterministic fact needed for the summary. No LLM calls here."""
    monthly = get_monthly_summary(month)
    budget_status = get_budget_status(month)
    subscriptions = get_subscriptions()
    recurring_total = total_monthly_recurring()
    unusual = detect_unusual_spending(month)
    goals = get_goal_status()

    prev_month = _previous_month(month)
    comparison = compare_months(month, prev_month) if prev_month else None

    over_budget = [b for b in budget_status if b["over_budget"]]

    return {
        "month": month,
        "monthly": monthly,
        "budget_status": budget_status,
        "over_budget": over_budget,
        "subscriptions": subscriptions,
        "recurring_total": recurring_total,
        "unusual": unusual,
        "goals": goals,
        "comparison": comparison,
    }


def _deterministic_observations(facts: Dict) -> list:
    observations = []
    monthly = facts["monthly"]

    if monthly["top_category"]:
        observations.append(
            f"Your top spending category was {monthly['top_category']['category']} "
            f"at ₹{monthly['top_category']['total']:,.0f}."
        )

    for b in facts["over_budget"]:
        observations.append(
            f"{b['category']} spending exceeded budget by ₹{abs(b['remaining']):,.0f}."
        )

    if facts["comparison"]:
        biggest_increase = next(
            (c for c in facts["comparison"]["changes"] if c["difference"] > 0), None
        )
        if biggest_increase and biggest_increase["difference"] > 0:
            observations.append(
                f"{biggest_increase['category']} spending increased by "
                f"₹{biggest_increase['difference']:,.0f} "
                f"({biggest_increase['pct_change']:.0f}%) compared with the previous month."
            )

    if facts["unusual"]:
        top = facts["unusual"][0]
        observations.append(
            f"An unusually large {top['category'].lower()} transaction of ₹{top['amount']:,.0f} "
            f"was detected ({top['merchant']})."
        )

    at_risk_goals = [g for g in facts["goals"] if g["status"] == "at_risk"]
    for g in at_risk_goals:
        observations.append(f"Goal '{g['name']}' is at risk of missing its target date at the current pace.")

    if not observations:
        observations.append("No major concerns detected this month -- spending looks stable.")

    return observations


def _deterministic_action_items(facts: Dict) -> list:
    actions = []
    if facts["over_budget"]:
        cats = ", ".join(b["category"] for b in facts["over_budget"])
        actions.append(f"Review spending in: {cats}.")
    if facts["subscriptions"]:
        actions.append(f"Review your {len(facts['subscriptions'])} active recurring subscriptions/payments.")
    if facts["unusual"]:
        actions.append("Check the flagged unusual transactions for accuracy or duplicate charges.")
    at_risk_goals = [g for g in facts["goals"] if g["status"] == "at_risk"]
    if at_risk_goals:
        actions.append("Reconsider timeline or monthly savings for at-risk goals.")
    if not actions:
        actions.append("Maintain your current monthly saving rate.")
    return actions


def generate_monthly_summary(month: str) -> Dict:
    """
    Returns a full structured summary dict ready for display, containing both
    the raw facts and human-readable observations/action items.
    """
    facts = build_summary_facts(month)

    observations = _deterministic_observations(facts)
    actions = _deterministic_action_items(facts)

    # Optional: ask the LLM to smooth the observations into a short narrative
    # paragraph, STRICTLY based on the facts already computed (no new numbers).
    from agent.agent import get_llm_client

    client = get_llm_client()
    narrative = None
    if client is not None:
        try:
            fact_lines = "\n".join(f"- {o}" for o in observations)
            prompt = (
                "You are a financial summary writer. Using ONLY the facts below, write a "
                "short (2-3 sentence) natural-language narrative summarizing the user's month. "
                "Do not introduce any numbers that are not already present in the facts. "
                "Do not give investment advice.\n\nFacts:\n" + fact_lines
            )
            narrative = client.complete(prompt, max_tokens=200).strip()
        except Exception:
            narrative = None

    return {
        "month": month,
        "income": facts["monthly"]["income"],
        "expenses": facts["monthly"]["expenses"],
        "savings": facts["monthly"]["surplus"],
        "savings_rate_pct": facts["monthly"]["savings_rate_pct"],
        "top_category": facts["monthly"]["top_category"],
        "largest_transaction": facts["monthly"]["largest_transaction"],
        "recurring_total": facts["recurring_total"],
        "subscriptions": facts["subscriptions"],
        "budget_status": facts["budget_status"],
        "over_budget": facts["over_budget"],
        "unusual_transactions": facts["unusual"],
        "goals": facts["goals"],
        "comparison": facts["comparison"],
        "observations": observations,
        "action_items": actions,
        "narrative": narrative,
    }
