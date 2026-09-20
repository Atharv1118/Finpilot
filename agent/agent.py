"""
agent/agent.py

LLM provider abstraction plus the agentic tool-calling loop that powers the
"Ask anything about your finances" chat tab.

Design:
- get_llm_client() picks Anthropic or OpenAI based on which API key is set
  (ANTHROPIC_API_KEY takes priority). Returns None if neither is configured.
- LLMClient.complete(prompt) is a simple single-turn text completion, used by
  services/categorizer.py and services/summary.py for non-agentic text tasks.
- run_agent_query(question) runs the full tool-calling loop: the LLM decides
  which FinPilot tool(s) to call, tools execute against real SQLite data, and
  results are fed back until the LLM produces a final grounded answer.
- If no API key is configured, run_agent_query falls back to deterministic
  keyword-based routing (fallback_answer) so the demo still works offline.
"""

import os
import json
from typing import Optional, List, Dict

from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOL_SPECS, dispatch_tool

MAX_TOOL_ITERATIONS = 4
ANTHROPIC_MODEL = "claude-sonnet-4-6"
OPENAI_MODEL = "gpt-4o-mini"
GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class LLMClient:
    def __init__(self, provider: str, api_key: str):
        self.provider = provider
        self.api_key = api_key

    def complete(self, prompt: str, max_tokens: int = 500, system: Optional[str] = None) -> str:
        if self.provider == "anthropic":
            return self._anthropic_complete(prompt, max_tokens, system)
        if self.provider == "gemini":
            return self._gemini_complete(prompt, max_tokens, system)
        return self._openai_complete(prompt, max_tokens, system)

    def _anthropic_complete(self, prompt, max_tokens, system):
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system or "You are a helpful financial data assistant.",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")

    def _openai_complete(self, prompt, max_tokens, system):
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system or "You are a helpful financial data assistant."},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content or ""

    def _gemini_complete(self, prompt, max_tokens, system):
        # Gemini exposes an OpenAI-compatible API, so we reuse the installed
        # openai package without adding another dependency.
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=GEMINI_BASE_URL)
        resp = client.chat.completions.create(
            model=GEMINI_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system or "You are a helpful financial data assistant."},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content or ""


def get_llm_client() -> Optional[LLMClient]:
    # Free Gemini is preferred for the hackathon deployment.
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if gemini_key:
        return LLMClient("gemini", gemini_key)
    if anthropic_key:
        return LLMClient("anthropic", anthropic_key)
    if openai_key:
        return LLMClient("openai", openai_key)
    return None


# ---------------------------------------------------------------------------
# Agentic tool-calling loop
# ---------------------------------------------------------------------------

def _openai_tool_specs() -> List[Dict]:
    """Convert Anthropic-style TOOL_SPECS into OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec["input_schema"],
            },
        }
        for spec in TOOL_SPECS
    ]


def _run_anthropic_agent(question: str, api_key: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": question}]

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=800,
            system=SYSTEM_PROMPT,
            tools=TOOL_SPECS,
            messages=messages,
        )

        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text").strip() or \
                "I couldn't generate a response. Please try rephrasing your question."

        messages.append({"role": "assistant", "content": resp.content})

        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                result = dispatch_tool(block.name, block.input or {})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    return "I looked into several data points but couldn't finish forming an answer. Please try a more specific question."


def _run_openai_agent(question: str, api_key: str) -> str:
    return _run_openai_compatible_agent(question, api_key, OPENAI_MODEL, None)


def _run_gemini_agent(question: str, api_key: str) -> str:
    return _run_openai_compatible_agent(question, api_key, GEMINI_MODEL, GEMINI_BASE_URL)


def _run_openai_compatible_agent(question: str, api_key: str, model: str, base_url: Optional[str]) -> str:
    from openai import OpenAI

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    tools = _openai_tool_specs()

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.chat.completions.create(
            model=model,
            max_tokens=800,
            messages=messages,
            tools=tools,
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:
            return (msg.content or "").strip() or \
                "I couldn't generate a response. Please try rephrasing your question."

        messages.append({"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls})

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            result = dispatch_tool(call.function.name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                }
            )

    return "I looked into several data points but couldn't finish forming an answer. Please try a more specific question."


# ---------------------------------------------------------------------------
# Deterministic fallback (no LLM configured)
# ---------------------------------------------------------------------------

def fallback_answer(question: str) -> str:
    """
    Keyword-based routing to tools so the assistant tab still works with no
    API key configured. Grounded in the same real data, just without natural
    language flexibility.
    """
    from agent.tools import (
        tool_get_category_spending,
        tool_get_recurring_payments,
        tool_compare_months,
        tool_get_budget_status,
        tool_get_goal_status,
        tool_get_unusual_transactions,
        tool_get_monthly_summary,
    )

    q = question.lower()

    if "subscription" in q or "recurring" in q:
        data = tool_get_recurring_payments()
        if not data["subscriptions"]:
            return "No recurring payments or subscriptions have been detected yet."
        lines = [f"- {s['merchant']}: ₹{s['amount']:,.0f}/{s['frequency']}" for s in data["subscriptions"]]
        return (
            f"You have {data['count']} recurring payment(s), totaling ₹{data['total_monthly_recurring']:,.0f}/month:\n"
            + "\n".join(lines)
        )

    if "budget" in q and ("committed" in q or "status" in q or "left" in q or "remaining" in q):
        data = tool_get_budget_status()
        if "error" in data:
            return data["error"]
        return (
            f"For {data['month']}: ₹{data['total_spent']:,.0f} of ₹{data['total_budget']:,.0f} budget spent "
            f"({data['pct_committed']:.0f}% committed). Remaining: ₹{data['remaining_budget']:,.0f}. "
            f"Monthly recurring obligations: ₹{data['monthly_recurring_expenses']:,.0f}."
        )

    if "increase" in q or "compare" in q or "last month" in q:
        data = tool_compare_months()
        if "error" in data:
            return data["error"]
        increases = [c for c in data["changes"] if c["difference"] > 0]
        if not increases:
            return f"No categories increased from {data['month_b']} to {data['month_a']}."
        lines = [f"- {c['category']}: +₹{c['difference']:,.0f} ({c['pct_change']:.0f}%)" for c in increases[:5]]
        return f"Compared with {data['month_b']}, these categories increased in {data['month_a']}:\n" + "\n".join(lines)

    if "unusual" in q or "anomal" in q:
        data = tool_get_unusual_transactions()
        if not data["unusual_transactions"]:
            return "No unusual transactions detected."
        lines = [u["explanation"] for u in data["unusual_transactions"][:5]]
        return "\n".join(lines)

    if "goal" in q or "emergency fund" in q:
        data = tool_get_goal_status()
        if not data["goals"]:
            return "No financial goals have been set yet."
        lines = [f"{g['name']}: {g['explanation']}" for g in data["goals"]]
        return "\n\n".join(lines)

    if "spend the most" in q or "where did i spend" in q or "top categor" in q:
        data = tool_get_category_spending()
        if not data["categories"]:
            return "No spending data available yet."
        top = data["categories"][0]
        return f"Your highest spending category this month is {top['category']}, with ₹{top['total']:,.0f} spent."

    # Generic fallback: monthly summary
    data = tool_get_monthly_summary()
    if "error" in data:
        return "No transaction data available yet. Please upload a statement first."
    return (
        f"For {data['month']}: income ₹{data['income']:,.0f}, expenses ₹{data['expenses']:,.0f}, "
        f"surplus ₹{data['surplus']:,.0f} ({data['savings_rate_pct']:.0f}% savings rate). "
        f"(No AI API key is configured, so this is a direct data lookup rather than a natural-language answer. "
        f"Add ANTHROPIC_API_KEY or OPENAI_API_KEY to .env for richer answers.)"
    )


def run_agent_query(question: str) -> str:
    """Main entry point used by the Streamlit chat tab."""
    client = get_llm_client()
    if client is None:
        return fallback_answer(question)

    try:
        if client.provider == "anthropic":
            return _run_anthropic_agent(question, client.api_key)
        if client.provider == "gemini":
            return _run_gemini_agent(question, client.api_key)
        return _run_openai_agent(question, client.api_key)
    except Exception as e:
        return f"The AI assistant hit an error calling the LLM API ({e}). Falling back to direct data lookup:\n\n" + fallback_answer(question)
