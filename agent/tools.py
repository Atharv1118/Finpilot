"""
agent/tools.py

Defines the tools the AI assistant may call. Each tool queries real data via
services/*.py -- the LLM never gets direct database access and never invents
numbers; it can only read what these functions actually return.

TOOL_SPECS is written in Anthropic's tool-use JSON schema format. agent.py
converts it to OpenAI's function-calling format when that provider is used.
"""

from typing import Dict, Any

from services import analytics, recurring, anomaly, goals as goals_service


def _latest_month_if_missing(month):
    if month:
        return month
    months = analytics.list_available_months()
    return months[0] if months else None


def tool_query_transactions(start_date=None, end_date=None, category=None,
                             merchant=None, min_amount=None, max_amount=None) -> Dict[str, Any]:
    txns = analytics.get_transactions(start_date, end_date, category, merchant, min_amount, max_amount)
    return {"count": len(txns), "transactions": txns[:50]}  # cap payload size


def tool_get_monthly_summary(month=None) -> Dict[str, Any]:
    month = _latest_month_if_missing(month)
    if not month:
        return {"error": "No transaction data available."}
    return analytics.get_monthly_summary(month)


def tool_get_category_spending(month=None) -> Dict[str, Any]:
    month = _latest_month_if_missing(month)
    return {"month": month, "categories": analytics.get_category_spending(month)}


def tool_get_recurring_payments() -> Dict[str, Any]:
    subs = recurring.get_subscriptions()
    return {
        "subscriptions": subs,
        "count": len(subs),
        "total_monthly_recurring": recurring.total_monthly_recurring(),
    }


def tool_get_budget_status(month=None) -> Dict[str, Any]:
    month = _latest_month_if_missing(month)
    if not month:
        return {"error": "No transaction data available."}
    return analytics.get_budget_commitment_summary(month)


def tool_get_goal_status() -> Dict[str, Any]:
    return {"goals": goals_service.get_goal_status()}


def tool_compare_months(month_a=None, month_b=None) -> Dict[str, Any]:
    months = analytics.list_available_months()
    if not month_a:
        month_a = months[0] if months else None
    if not month_b:
        month_b = months[1] if len(months) > 1 else None
    if not month_a or not month_b:
        return {"error": "Not enough months of data to compare."}
    return analytics.compare_months(month_a, month_b)


def tool_get_unusual_transactions(month=None) -> Dict[str, Any]:
    return {"unusual_transactions": anomaly.detect_unusual_spending(month)}


TOOL_FUNCTIONS = {
    "query_transactions": tool_query_transactions,
    "get_monthly_summary": tool_get_monthly_summary,
    "get_category_spending": tool_get_category_spending,
    "get_recurring_payments": tool_get_recurring_payments,
    "get_budget_status": tool_get_budget_status,
    "get_goal_status": tool_get_goal_status,
    "compare_months": tool_compare_months,
    "get_unusual_transactions": tool_get_unusual_transactions,
}


TOOL_SPECS = [
    {
        "name": "query_transactions",
        "description": "Search raw transactions with optional filters. Use for specific lookups like 'show my transport transactions' or 'transactions over ₹2000'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                "category": {"type": "string", "description": "One of the fixed FinPilot categories"},
                "merchant": {"type": "string", "description": "Partial merchant name to search for"},
                "min_amount": {"type": "number"},
                "max_amount": {"type": "number"},
            },
        },
    },
    {
        "name": "get_monthly_summary",
        "description": "Get income, expenses, surplus, savings rate, top category, and largest transaction for a given month. Omit month to use the latest available month.",
        "input_schema": {
            "type": "object",
            "properties": {"month": {"type": "string", "description": "YYYY-MM, optional"}},
        },
    },
    {
        "name": "get_category_spending",
        "description": "Get total spending broken down by category for a given month (or latest month if omitted). Use for 'where did I spend the most' type questions.",
        "input_schema": {
            "type": "object",
            "properties": {"month": {"type": "string", "description": "YYYY-MM, optional"}},
        },
    },
    {
        "name": "get_recurring_payments",
        "description": "Get all detected recurring payments/subscriptions with amounts and frequency, plus total monthly recurring cost.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_budget_status",
        "description": "Get budget vs actual spending per category for a given month, including how much of the total budget is already committed/spent. Use for 'how much of my budget is committed' questions.",
        "input_schema": {
            "type": "object",
            "properties": {"month": {"type": "string", "description": "YYYY-MM, optional"}},
        },
    },
    {
        "name": "get_goal_status",
        "description": "Get all financial goals with progress, required monthly savings, and whether they're on track.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "compare_months",
        "description": "Compare category-level spending between two months to see what increased or decreased. Omit both to compare the two most recent months.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month_a": {"type": "string", "description": "YYYY-MM, the more recent month"},
                "month_b": {"type": "string", "description": "YYYY-MM, the earlier month to compare against"},
            },
        },
    },
    {
        "name": "get_unusual_transactions",
        "description": "Get transactions flagged as unusually large compared to the user's typical spending in that category, with explanations. Omit month for all-time.",
        "input_schema": {
            "type": "object",
            "properties": {"month": {"type": "string", "description": "YYYY-MM, optional"}},
        },
    },
]


def dispatch_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"Unknown tool '{name}'"}
    try:
        return fn(**{k: v for k, v in arguments.items() if v is not None})
    except Exception as e:
        return {"error": f"Tool '{name}' failed: {e}"}
