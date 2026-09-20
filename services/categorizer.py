"""
services/categorizer.py

Categorizes transactions into a fixed set of categories using:
  1. Deterministic keyword/merchant rules (fast, free, no API needed)
  2. LLM fallback for anything the rules don't recognize (batched to save calls)
  3. A persistent merchant->category cache (SQLite) so a merchant is only ever
     sent to the LLM once.

Never invents categories outside the fixed CATEGORIES list.
"""

import json
from typing import List, Dict

from database.db import get_cursor
from database.models import CATEGORIES
from utils.merchant import normalize_merchant

# Deterministic keyword -> category rules. Checked against the lowercased
# description AND normalized merchant name.
RULES = [
    (["swiggy", "zomato", "restaurant", "food", "cafe", "dine", "eat", "dominos",
      "pizza", "kfc", "mcdonald", "starbucks", "hotel"], "Food"),
    (["amazon", "flipkart", "myntra", "ajio", "shopping", "mall", "store", "mart"], "Shopping"),
    (["uber", "ola", "rapido", "irctc", "fuel", "petrol", "diesel", "metro",
      "taxi", "cab", "bus", "train", "parking"], "Transport"),
    (["electricity", "electric board", "mseb", "water bill", "gas agency",
      "broadband", "wifi", "airtel", "jio", "vodafone", "utility", "utilities"], "Utilities"),
    (["netflix", "spotify", "amazon prime", "hotstar", "youtube premium",
      "subscription", "audible", "apple music"], "Subscriptions"),
    (["hospital", "pharmacy", "clinic", "doctor", "medical", "medicine", "health"], "Healthcare"),
    (["college", "tuition", "course", "udemy", "coursera", "school", "exam fee",
      "education"], "Education"),
    (["movie", "cinema", "pvr", "inox", "bookmyshow", "concert", "game", "entertainment"], "Entertainment"),
    (["rent", "landlord", "lease"], "Rent"),
    (["salary", "payroll", "stipend"], "Salary"),
    (["transfer", "sent to", "received from", "self transfer", "imps", "neft to"], "Transfer"),
    (["emi", "loan", "insurance", "lic", "premium", "credit card bill", "bill payment"], "Bills"),
]


def rule_based_category(description: str, merchant: str) -> str:
    text = f"{description} {merchant}".lower()
    for keywords, category in RULES:
        if any(kw in text for kw in keywords):
            return category
    return None


def _get_cached_category(merchant: str) -> str:
    with get_cursor() as cur:
        cur.execute("SELECT category FROM merchant_cache WHERE merchant = ?", (merchant,))
        row = cur.fetchone()
        return row["category"] if row else None


def _cache_category(merchant: str, category: str):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO merchant_cache (merchant, category) VALUES (?, ?) "
            "ON CONFLICT(merchant) DO UPDATE SET category = excluded.category",
            (merchant, category),
        )


def _llm_batch_categorize(items: List[Dict]) -> Dict[str, str]:
    """
    items: list of {"merchant": str, "description": str}
    Returns: {merchant: category}
    Falls back to 'Other' for everything if no LLM is configured or the call fails.
    """
    from agent.agent import get_llm_client

    client = get_llm_client()
    if client is None or not items:
        return {item["merchant"]: "Other" for item in items}

    unique_merchants = {item["merchant"]: item["description"] for item in items}
    listing = "\n".join(f'- Merchant: "{m}" | Example description: "{d}"' for m, d in unique_merchants.items())

    prompt = (
        "Classify each merchant below into EXACTLY ONE of these categories:\n"
        f"{', '.join(CATEGORIES)}\n\n"
        "Merchants:\n"
        f"{listing}\n\n"
        "Respond with ONLY a JSON object mapping each merchant name (exactly as given) "
        "to one category from the list. No prose, no markdown fences."
    )

    try:
        text = client.complete(prompt, max_tokens=1000)
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        mapping = json.loads(text)
        cleaned = {}
        for m in unique_merchants:
            cat = mapping.get(m, "Other")
            cleaned[m] = cat if cat in CATEGORIES else "Other"
        return cleaned
    except Exception:
        return {m: "Other" for m in unique_merchants}


def categorize_transactions(transactions: List[Dict]) -> List[Dict]:
    """
    Mutates and returns the given transaction dicts, adding 'category' and
    'normalized_merchant' keys. Runs rules first, batches only the leftovers to
    the LLM (or persistent cache), so API usage stays minimal.
    """
    needs_llm = []

    for txn in transactions:
        merchant = normalize_merchant(txn["description"])
        txn["normalized_merchant"] = merchant

        rule_cat = rule_based_category(txn["description"], merchant)
        if rule_cat:
            txn["category"] = rule_cat
            continue

        cached = _get_cached_category(merchant)
        if cached:
            txn["category"] = cached
            continue

        needs_llm.append(txn)

    if needs_llm:
        batch_input = [{"merchant": t["normalized_merchant"], "description": t["description"]} for t in needs_llm]
        results = _llm_batch_categorize(batch_input)
        for txn in needs_llm:
            category = results.get(txn["normalized_merchant"], "Other")
            txn["category"] = category
            _cache_category(txn["normalized_merchant"], category)

    return transactions
