"""
app.py

FinPilot -- Personal Finance Decision Support Agent
Streamlit UI entry point. Run with:  streamlit run app.py
"""

import os
import traceback

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from database.db import init_db
from database.seed import load_sample_data
from services.parser import parse_uploaded_file
from services.categorizer import categorize_transactions
from services.recurring import detect_recurring_from_db, get_subscriptions
from services.anomaly import detect_unusual_spending
from services import analytics
from services import goals as goals_service
from services.summary import generate_monthly_summary
from database.seed import store_transactions
from agent.agent import run_agent_query, get_llm_client
from agent.prompts import SUGGESTED_QUESTIONS

st.set_page_config(page_title="FinPilot", page_icon="💰", layout="wide")

init_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def has_data() -> bool:
    return len(analytics.list_available_months()) > 0


def month_selector(key="month_select", label="Month"):
    months = analytics.list_available_months()
    if not months:
        return None
    return st.selectbox(label, months, index=0, key=key)


def rupee(value) -> str:
    try:
        return f"₹{value:,.0f}"
    except (TypeError, ValueError):
        return "₹0"


def llm_status_badge():
    client = get_llm_client()
    if client:
        st.caption(f"🤖 AI provider: **{client.provider.title()}** connected")
    else:
        st.caption("⚙️ No AI API key configured -- running on deterministic rules/fallback only.")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("💰 FinPilot")
st.sidebar.caption("Personal Finance Decision Support Agent")

page = st.sidebar.radio(
    "Navigate",
    ["Dashboard", "Upload", "Transactions", "Budgets", "Goals", "AI Assistant", "Monthly Summary"],
)

st.sidebar.divider()

if st.sidebar.button("📊 Load Demo Data", use_container_width=True):
    with st.spinner("Loading synthetic demo dataset..."):
        try:
            count = load_sample_data(reset_first=True)
            st.sidebar.success(f"Loaded {count} demo transactions.")
        except Exception as e:
            st.sidebar.error(f"Failed to load demo data: {e}")

if st.sidebar.button("🗑️ Reset All Data", use_container_width=True):
    from database.db import reset_db

    reset_db()
    st.sidebar.info("All data cleared.")

st.sidebar.divider()
llm_status_badge()

st.sidebar.divider()
st.sidebar.caption(
    "FinPilot provides financial data analysis and decision support. "
    "It does not provide investment or professional financial advice."
)


# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------

def page_dashboard():
    st.title("FinPilot")
    st.subheader("Understand your spending. Track your obligations. Plan your goals.")

    if not has_data():
        st.info("No data yet. Load the demo dataset from the sidebar, or go to **Upload** to add your own statement.")
        return

    months = analytics.list_available_months()
    month = st.selectbox("Viewing month", months, index=0)

    summary = analytics.get_monthly_summary(month)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Monthly Income", rupee(summary["income"]))
    c2.metric("Monthly Expenses", rupee(summary["expenses"]))
    c3.metric("Surplus", rupee(summary["surplus"]))
    c4.metric("Savings Rate", f"{summary['savings_rate_pct']:.1f}%")

    st.divider()

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("#### Spending by Category")
        cat_data = summary["category_breakdown"]
        if cat_data:
            df = pd.DataFrame(cat_data).set_index("category")
            st.bar_chart(df["total"])
        else:
            st.caption("No expense data for this month.")

        st.markdown("#### Monthly Trend")
        trend = analytics.get_monthly_trend()
        if len(trend) > 1:
            trend_df = pd.DataFrame(trend).set_index("month")[["income", "expenses"]]
            st.line_chart(trend_df)
        else:
            st.caption("Upload more than one month of data to see a trend line.")

    with col_right:
        st.markdown("#### Recurring Payments")
        subs = get_subscriptions()
        if subs:
            for s in subs:
                st.write(f"**{s['merchant']}** — {rupee(s['amount'])}/{s['frequency']}")
            st.caption(f"Total monthly recurring: {rupee(sum(s['amount'] for s in subs))}")
        else:
            st.caption("No recurring payments detected yet.")

        st.markdown("#### Unusual Transactions")
        unusual = detect_unusual_spending(month)
        if unusual:
            for u in unusual[:5]:
                st.warning(f"**{u['merchant']}** — {rupee(u['amount'])}  \n{u['explanation']}")
        else:
            st.caption("No unusual transactions detected this month.")


# ---------------------------------------------------------------------------
# UPLOAD
# ---------------------------------------------------------------------------

def page_upload():
    st.title("Upload a Statement")
    st.write(
        "Upload a transaction statement (CSV recommended; PDF supported on a best-effort basis). "
        "FinPilot will parse, categorize, and store the transactions automatically."
    )

    uploaded = st.file_uploader("Choose a file", type=["csv", "pdf"])

    if uploaded is not None:
        if st.button("Process File", type="primary"):
            with st.spinner("Parsing file..."):
                result = parse_uploaded_file(uploaded.name, uploaded.getvalue())

            if not result.ok:
                st.error("Could not extract any transactions from this file.")
                for err in result.errors[:10]:
                    st.write(f"- {err}")
                return

            st.success(f"Parsed {len(result.transactions)} transactions.")
            if result.skipped_rows:
                st.warning(f"Skipped {result.skipped_rows} row(s) due to missing/invalid data.")
            if result.errors:
                with st.expander("View parsing warnings"):
                    for err in result.errors[:30]:
                        st.write(f"- {err}")

            with st.spinner("Categorizing transactions..."):
                categorized = categorize_transactions(result.transactions)

            store_transactions(categorized)

            with st.spinner("Detecting recurring payments..."):
                detect_recurring_from_db()

            st.success("Done! Your data is now available on the Dashboard.")
            preview_df = pd.DataFrame(categorized)[["date", "description", "amount", "transaction_type", "category"]]
            st.dataframe(preview_df, use_container_width=True)

    st.divider()
    st.markdown("##### Expected CSV format")
    st.code(
        "date,description,amount\n"
        "2026-08-01,Salary Credit,75000\n"
        "2026-08-02,Swiggy,450\n"
        "2026-08-03,Netflix,649\n"
        "2026-08-04,Uber,320\n",
        language="csv",
    )
    st.caption(
        "Also supports common bank export variants: 'Transaction Date', 'Narration', "
        "'Debit'/'Credit' columns, and negative amounts for expenses."
    )


# ---------------------------------------------------------------------------
# TRANSACTIONS
# ---------------------------------------------------------------------------

def page_transactions():
    st.title("Transactions")

    if not has_data():
        st.info("No transactions yet. Load demo data or upload a statement.")
        return

    with st.expander("Filters", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            months = ["All"] + analytics.list_available_months()
            month_filter = st.selectbox("Month", months)
        with col2:
            from database.models import CATEGORIES

            category_filter = st.selectbox("Category", ["All"] + CATEGORIES)
        with col3:
            merchant_filter = st.text_input("Merchant search")

    start_date = f"{month_filter}-01" if month_filter != "All" else None
    end_date = f"{month_filter}-31" if month_filter != "All" else None

    txns = analytics.get_transactions(
        start_date=start_date,
        end_date=end_date,
        category=None if category_filter == "All" else category_filter,
        merchant=merchant_filter or None,
    )

    if not txns:
        st.warning("No transactions match these filters.")
        return

    df = pd.DataFrame(txns)[["date", "description", "normalized_merchant", "amount", "transaction_type", "category", "is_recurring"]]
    df = df.rename(columns={"normalized_merchant": "merchant", "is_recurring": "recurring"})
    df["recurring"] = df["recurring"].map({1: "Yes", 0: "No"})
    st.dataframe(df, use_container_width=True, height=500)
    st.caption(f"{len(df)} transaction(s) shown.")


# ---------------------------------------------------------------------------
# BUDGETS
# ---------------------------------------------------------------------------

def page_budgets():
    st.title("Budgets")

    from database.models import CATEGORIES

    with st.expander("Set / update a budget", expanded=not analytics.get_budgets()):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            category = st.selectbox("Category", CATEGORIES, key="budget_cat")
        with col2:
            limit = st.number_input("Monthly limit (₹)", min_value=0, step=500, value=5000, key="budget_limit")
        with col3:
            st.write("")
            st.write("")
            if st.button("Save Budget"):
                analytics.set_budget(category, float(limit))
                st.success(f"Budget set for {category}: {rupee(limit)}")
                st.rerun()

    budgets = analytics.get_budgets()
    if not budgets:
        st.info("No budgets set yet.")
        return

    if not has_data():
        st.info("Budgets are set, but there's no transaction data yet to compare against.")
        return

    month = month_selector(label="Compare against month")
    status = analytics.get_budget_status(month)

    st.markdown(f"### Budget vs Actual — {month}")
    for s in status:
        over = s["over_budget"]
        label = f"{s['category']}: {rupee(s['spent'])} / {rupee(s['monthly_limit'])} ({s['pct_used']:.0f}% used)"
        if over:
            st.error(label + f"  —  {rupee(abs(s['remaining']))} over budget")
        else:
            st.write(label)
        st.progress(min(s["pct_used"] / 100, 1.0))

        if st.button(f"Remove {s['category']} budget", key=f"del_{s['category']}"):
            analytics.delete_budget(s["category"])
            st.rerun()

    commitment = analytics.get_budget_commitment_summary(month)
    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Budget", rupee(commitment["total_budget"]))
    c2.metric("Total Spent", rupee(commitment["total_spent"]))
    c3.metric("Remaining Budget", rupee(commitment["remaining_budget"]))
    c4.metric("% Committed", f"{commitment['pct_committed']:.0f}%")
    st.caption(f"Monthly recurring expenses (subscriptions, rent, etc.): {rupee(commitment['monthly_recurring_expenses'])}")


# ---------------------------------------------------------------------------
# GOALS
# ---------------------------------------------------------------------------

def page_goals():
    st.title("Financial Goals")
    st.caption("This is financial data analysis, not investment advice.")

    with st.expander("Create a new goal", expanded=not goals_service.get_goals()):
        col1, col2, col3 = st.columns(3)
        with col1:
            name = st.text_input("Goal name", value="Emergency Fund")
        with col2:
            target_amount = st.number_input("Target amount (₹)", min_value=0, step=1000, value=50000)
        with col3:
            current_saved = st.number_input("Current saved (₹)", min_value=0, step=1000, value=0)
        target_date = st.date_input("Target date")
        if st.button("Create Goal"):
            goals_service.create_goal(name, float(target_amount), str(target_date), float(current_saved))
            st.success(f"Goal '{name}' created.")
            st.rerun()

    goals = goals_service.get_goal_status()
    if not goals:
        st.info("No goals yet. Create one above.")
        return

    for g in goals:
        with st.container(border=True):
            st.markdown(f"### {g['name']}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Target", rupee(g["target_amount"]))
            col2.metric("Saved so far", rupee(g["current_saved"]))
            col3.metric("Remaining", rupee(g["remaining_amount"]))

            pct = 0 if g["target_amount"] == 0 else min(g["current_saved"] / g["target_amount"], 1.0)
            st.progress(pct)

            status_icon = {"on_track": "✅", "at_risk": "⚠️", "achieved": "🎉"}.get(g["status"], "")
            st.write(f"{status_icon} {g['explanation']}")
            st.caption(f"Target date: {g['target_date']}  |  Months left: {g['months_left']}  |  "
                       f"Required monthly saving: {rupee(g['required_monthly_saving'])}")

            if st.button(f"Delete '{g['name']}'", key=f"del_goal_{g['id']}"):
                goals_service.delete_goal(g["id"])
                st.rerun()


# ---------------------------------------------------------------------------
# AI ASSISTANT
# ---------------------------------------------------------------------------

def page_assistant():
    st.title("FinPilot Assistant")
    st.caption("Ask anything about your finances -- answers are grounded in your real uploaded data.")
    llm_status_badge()

    if not has_data():
        st.info("Load demo data or upload a statement first so the assistant has something to analyze.")
        return

    st.markdown("**Try asking:**")
    cols = st.columns(3)
    for i, q in enumerate(SUGGESTED_QUESTIONS):
        if cols[i % 3].button(q, key=f"suggest_{i}", use_container_width=True):
            st.session_state["pending_question"] = q

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    for role, content in st.session_state["chat_history"]:
        with st.chat_message(role):
            st.write(content)

    question = st.chat_input("Ask about your finances...")
    if st.session_state.get("pending_question"):
        question = st.session_state.pop("pending_question")

    if question:
        st.session_state["chat_history"].append(("user", question))
        with st.chat_message("user"):
            st.write(question)

        with st.chat_message("assistant"):
            with st.spinner("Analyzing your data..."):
                try:
                    answer = run_agent_query(question)
                except Exception as e:
                    answer = f"Something went wrong answering that: {e}"
            st.write(answer)

        st.session_state["chat_history"].append(("assistant", answer))


# ---------------------------------------------------------------------------
# MONTHLY SUMMARY
# ---------------------------------------------------------------------------

def page_monthly_summary():
    st.title("Monthly Financial Summary")

    if not has_data():
        st.info("No data yet. Load demo data or upload a statement.")
        return

    month = month_selector(label="Summary for month")
    with st.spinner("Generating summary..."):
        summary = generate_monthly_summary(month)

    st.markdown(f"## {month} Financial Summary")

    c1, c2, c3 = st.columns(3)
    c1.metric("Income", rupee(summary["income"]))
    c2.metric("Expenses", rupee(summary["expenses"]))
    c3.metric("Savings", rupee(summary["savings"]))

    if summary["narrative"]:
        st.info(summary["narrative"])

    if summary["top_category"]:
        st.write(f"**Top category:** {summary['top_category']['category']} — {rupee(summary['top_category']['total'])}")
    if summary["largest_transaction"]:
        lt = summary["largest_transaction"]
        st.write(f"**Largest transaction:** {lt['description']} — {rupee(lt['amount'])} on {lt['date']}")
    st.write(f"**Recurring expenses:** {rupee(summary['recurring_total'])}/month")

    if summary["over_budget"]:
        st.write("**Budget status:**")
        for b in summary["over_budget"]:
            st.error(f"{b['category']} exceeded budget by {rupee(abs(b['remaining']))}")
    else:
        st.write("**Budget status:** All categories within budget.")

    st.markdown("#### Key Observations")
    for o in summary["observations"]:
        st.write(f"- {o}")

    st.markdown("#### Action Items")
    for a in summary["action_items"]:
        st.write(f"- {a}")

    if summary["goals"]:
        st.markdown("#### Goal Progress")
        for g in summary["goals"]:
            st.write(f"- **{g['name']}**: {g['explanation']}")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

try:
    if page == "Dashboard":
        page_dashboard()
    elif page == "Upload":
        page_upload()
    elif page == "Transactions":
        page_transactions()
    elif page == "Budgets":
        page_budgets()
    elif page == "Goals":
        page_goals()
    elif page == "AI Assistant":
        page_assistant()
    elif page == "Monthly Summary":
        page_monthly_summary()
except Exception as e:
    st.error(f"Something went wrong: {e}")
    with st.expander("Technical details"):
        st.code(traceback.format_exc())
