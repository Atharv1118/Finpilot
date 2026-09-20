# FinPilot

**Personal Finance Decision Support Agent** — built for a 36-hour Agentic AI Hackathon.

## 🚀 Live Demo

[**Try FinPilot Live →**](https://finpilot-hackathon.streamlit.app/)

## Problem

Financial information is scattered across bank statements, credit card bills, and
spreadsheets. People can see individual transactions but lack a simple system that
explains where their money is going, flags upcoming obligations, and shows how
everyday spending affects their financial goals.

## Solution

FinPilot is an AI-powered agent that ingests a transaction statement (CSV, with
best-effort PDF support), automatically categorizes and analyzes it, and lets the
user ask natural-language questions that are answered by an LLM calling real tools
against the user's own SQLite data — never by the LLM inventing numbers.

FinPilot does **not** give investment or professional financial advice. It helps
users understand their own financial data and make more informed everyday decisions.

## Features Implemented

- CSV upload with a flexible column-normalization layer (handles `Date`/`Transaction
  Date`/`Narration`, single signed `Amount` or separate `Debit`/`Credit` columns,
  multiple date formats, negative-amount conventions)
- Best-effort PDF statement parsing via `pdfplumber` (falls back to a clear error
  asking for CSV if the table layout isn't recognized)
- Merchant name normalization (`UPI-SWIGGY-123456` → `Swiggy`)
- Transaction categorization: deterministic keyword rules first, LLM fallback for
  anything unmatched, with a persistent merchant→category cache so no merchant is
  ever sent to the LLM twice
- Recurring payment / subscription detection via an explainable heuristic (same
  merchant, similar amount, ~monthly interval — no ML)
- Unusual spending detection via a simple, explainable rule (>2x the category's
  average spend)
- Monthly income/expense summary, category breakdown, and month-over-month trend
- Budget creation and budget-vs-actual comparison with progress bars and a
  "% of budget committed" rollup that includes recurring obligations
- Financial goal tracking (target amount/date, required monthly saving, comparison
  against actual average monthly surplus, on-track/at-risk status)
- Full monthly financial summary (income, expenses, savings, top category, largest
  transaction, recurring expenses, budget status, unusual transactions, goal
  progress, key observations, and action items) — computed deterministically, with
  an optional LLM-written narrative paragraph strictly grounded in those same facts
- Agentic natural-language Q&A: the LLM is given tools (`query_transactions`,
  `get_monthly_summary`, `get_category_spending`, `get_recurring_payments`,
  `get_budget_status`, `get_goal_status`, `compare_months`,
  `get_unusual_transactions`) and must call them to answer — it never invents a
  number
- Deterministic keyword-routed fallback for the assistant when no LLM API key is
  configured, so the whole app still works end-to-end offline
- Graceful handling of empty/malformed CSVs, missing columns, invalid dates,
  duplicate rows, and LLM API failures (with user-facing messages, not tracebacks)

## Architecture

```
                     ┌─────────────────────┐
                     │   Streamlit UI      │
                     │  (app.py, 7 tabs)   │
                     └──────────┬──────────┘
                                │
                     ┌──────────▼──────────┐
                     │   Finance Services   │
                     │ parser / categorizer │
                     │ recurring / anomaly  │
                     │ analytics / goals    │
                     │ summary              │
                     └──────────┬──────────┘
                                │
                     ┌──────────▼──────────┐
                     │       SQLite         │
                     │ transactions/budgets │
                     │ goals/subscriptions  │
                     │ merchant_cache        │
                     └──────────┬──────────┘
                                │
                     ┌──────────▼──────────┐
                     │   Agent (agent/*)    │
                     │  LLM tool-calling    │
                     │  loop over the same  │
                     │  services above      │
                     └─────────────────────┘
```

## Agent Workflow

```
User question
     │
     ▼
LLM (Claude or GPT) decides which tool(s) to call
     │
     ▼
Tool executes a read-only query against services/*.py -> SQLite
     │
     ▼
Tool result (JSON, real numbers) returned to the LLM
     │
     ▼
LLM writes a grounded natural-language answer, citing the real figures
```

If no `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set, `agent/agent.py` falls back to
deterministic keyword-based routing to the same tools, so the demo still runs.

## Tech Stack

- Python, FastAPI-free (Streamlit handles both UI and app logic for speed)
- SQLite (`sqlite3` standard library — no ORM)
- `pandas` for CSV parsing/normalization
- `pdfplumber` for best-effort PDF table extraction
- Anthropic (`claude-sonnet-4-6`) or OpenAI (`gpt-4o-mini`) for categorization
  fallback, tool-calling Q&A, and summary narration

## Project Structure

```
finpilot/
├── app.py                     # Streamlit UI (Dashboard, Upload, Transactions,
│                               #   Budgets, Goals, AI Assistant, Monthly Summary)
├── requirements.txt
├── .env.example
├── README.md
│
├── data/
│   └── sample_transactions.csv   # 3 months of synthetic demo data
│
├── database/
│   ├── db.py                  # SQLite connection + schema
│   ├── models.py               # Dataclasses + category list
│   └── seed.py                 # Loads demo data, default budgets/goals
│
├── services/
│   ├── parser.py                # CSV/PDF parsing + column normalization
│   ├── categorizer.py            # Rules + LLM fallback + merchant cache
│   ├── recurring.py              # Recurring payment heuristic
│   ├── anomaly.py                # Unusual spending heuristic
│   ├── analytics.py              # Summaries, budgets, trends
│   ├── goals.py                  # Goal projections
│   └── summary.py                # Monthly summary assembly
│
├── agent/
│   ├── agent.py                 # LLM abstraction + tool-calling loop + fallback
│   ├── tools.py                  # Tool definitions/dispatch
│   └── prompts.py                # System prompt + suggested questions
│
└── utils/
    └── merchant.py                # Merchant name normalization
```

## Setup

```bash
git clone <your-repo-url>
cd finpilot
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add ONE of: ANTHROPIC_API_KEY or OPENAI_API_KEY
# (Optional -- the app runs fully without either, using deterministic fallbacks.)
```

## Run

```bash
streamlit run app.py
```

Open the URL Streamlit prints (usually `http://localhost:8501`).

## Demo

1. Click **📊 Load Demo Data** in the sidebar. This loads
   `data/sample_transactions.csv` (3 months, June–August 2026) plus default
   budgets and two sample goals ("Emergency Fund", "New Laptop").
2. Walk through **Dashboard** → **Budgets** → **Goals** → **AI Assistant** →
   **Monthly Summary** (see demo script below).
3. Use **🗑️ Reset All Data** to clear everything and start fresh, or use
   **Upload** to try your own CSV.

## Example Questions for the AI Assistant

- "Where did I spend the most this month?"
- "Which subscriptions am I paying for?"
- "What expenses increased compared with last month?"
- "How much of my budget is already committed?"
- "What unusual transactions did you detect?"
- "How is my emergency fund goal progressing?"

## 3–5 Minute Demo Script

1. **Open Dashboard** — show income ₹75,000, expenses, surplus, and savings rate
   cards for August; point out the category bar chart and 3-month trend line.
2. **Show recurring payments** — Netflix, Spotify, Amazon Prime, Rent, etc.,
   auto-detected with no manual tagging.
3. **Show unusual spending** — the flagged ₹18,500 electronics purchase and
   ₹2,850 restaurant bill, each with a plain-language explanation.
4. **Go to Budgets** — show the progress bars and the "Shopping exceeded budget"
   warning, plus the "% of budget committed" rollup.
5. **Go to Goals** — show the Emergency Fund goal's required monthly saving vs.
   actual average surplus, and its on-track status.
6. **Go to AI Assistant** — ask, in order:
   - "Where did I spend the most this month?"
   - "Which subscriptions am I paying for?"
   - "What expenses increased compared with last month?"
   - "How much of my budget is already committed?"
   — Emphasize that every number the assistant states is pulled live from the
   SQLite database via tool calls, not generated by the LLM.
7. **Go to Monthly Summary** — show the full auto-generated summary with key
   observations and action items.

## Limitations

- Demo uses entirely synthetic data (`data/sample_transactions.csv`) — no real
  bank data is included or required.
- CSV is the primary, guaranteed-reliable input format; PDF parsing is
  best-effort and depends on the statement's table layout.
- All financial analysis is informational and descriptive, not prescriptive.
- FinPilot does not provide investment, tax, or professional financial advice,
  and never recommends specific financial products.
- There is no real bank API integration, authentication, or multi-user support —
  this is a single-user local demo by design, to keep the 20-hour build reliable.

## Intentionally Skipped Features

- Authentication / multi-user accounts
- Real bank/aggregator API integrations (Plaid, Account Aggregator, etc.)
- Machine-learning-based anomaly detection or categorization (explainable rules
  were chosen deliberately over ML for reliability and demo transparency)
- Investment, tax, or portfolio advice of any kind
- Docker/microservices/Redis/Postgres — everything runs from one SQLite file
  with `streamlit run app.py`
