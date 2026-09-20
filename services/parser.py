"""
services/parser.py

Parses uploaded transaction files (CSV primary, PDF secondary/best-effort) into
a normalized list of transaction dicts:

    {"date": "YYYY-MM-DD", "description": str, "amount": float, "transaction_type": "debit"|"credit"}

Handles common bank export variants:
    - Separate Debit/Credit columns instead of a single signed Amount
    - Column names like "Transaction Date", "Narration", "Particulars"
    - Negative amounts meaning debit
    - Missing/blank rows, duplicate rows, invalid dates
"""

import io
import re
from datetime import datetime
from typing import List, Dict, Tuple

import pandas as pd

# Maps many possible source column names (lowercased, whitespace-stripped) to
# our normalized field names.
COLUMN_ALIASES = {
    "date": "date",
    "transaction date": "date",
    "txn date": "date",
    "value date": "date",
    "posting date": "date",
    "description": "description",
    "narration": "description",
    "particulars": "description",
    "details": "description",
    "remarks": "description",
    "transaction details": "description",
    "amount": "amount",
    "transaction amount": "amount",
    "debit": "debit",
    "withdrawal": "debit",
    "withdrawal amt": "debit",
    "debit amount": "debit",
    "credit": "credit",
    "deposit": "credit",
    "deposit amt": "credit",
    "credit amount": "credit",
}

INCOME_KEYWORDS = [
    "salary", "stipend", "refund", "cashback", "interest credited", "dividend",
    "bonus", "reimbursement", "credited by", "credit interest", "payroll",
]

DATE_FORMATS = [
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d-%b-%Y",
    "%b %d, %Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
]


class ParseResult:
    def __init__(self):
        self.transactions: List[Dict] = []
        self.errors: List[str] = []
        self.skipped_rows: int = 0

    @property
    def ok(self) -> bool:
        return len(self.transactions) > 0


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in COLUMN_ALIASES:
            rename_map[col] = COLUMN_ALIASES[key]
    return df.rename(columns=rename_map)


def _parse_date(value) -> str:
    """Try a list of known date formats; return ISO string or raise ValueError."""
    if pd.isna(value):
        raise ValueError("empty date")

    if isinstance(value, (datetime, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")

    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Last resort: let pandas try to infer it.
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        raise ValueError(f"unrecognized date format: {text!r}")
    return parsed.strftime("%Y-%m-%d")


def _to_float(value) -> float:
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    text = re.sub(r"[₹$,\s]", "", text)
    if text in ("", "-", "nan"):
        return 0.0
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"unrecognized amount: {value!r}")


def parse_csv_bytes(file_bytes: bytes) -> ParseResult:
    result = ParseResult()

    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except Exception:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), sep=";")
        except Exception as e:
            result.errors.append(f"Could not read file as CSV: {e}")
            return result

    if df.empty:
        result.errors.append("The uploaded file has no rows.")
        return result

    df = _normalize_columns(df)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "date" not in df.columns:
        result.errors.append(
            "No date column found. Expected one of: Date, Transaction Date, Value Date."
        )
        return result

    if "description" not in df.columns:
        # Some exports only have a narration-like column under a different name we
        # didn't catch; fall back to the first text-ish column that isn't date/amount.
        candidate = None
        for col in df.columns:
            if col not in ("date", "amount", "debit", "credit") and df[col].dtype == object:
                candidate = col
                break
        if candidate:
            df = df.rename(columns={candidate: "description"})
        else:
            result.errors.append("No description/narration column found.")
            return result

    has_amount = "amount" in df.columns
    has_debit_credit = "debit" in df.columns or "credit" in df.columns

    if not has_amount and not has_debit_credit:
        result.errors.append(
            "No amount column found. Expected 'Amount' or separate 'Debit'/'Credit' columns."
        )
        return result

    for idx, row in df.iterrows():
        try:
            date_str = _parse_date(row["date"])
            description = str(row.get("description", "")).strip()
            if not description or description.lower() == "nan":
                result.skipped_rows += 1
                continue

            if has_debit_credit:
                debit = _to_float(row.get("debit", 0))
                credit = _to_float(row.get("credit", 0))
                if credit > 0 and debit == 0:
                    amount, txn_type = credit, "credit"
                elif debit > 0 and credit == 0:
                    amount, txn_type = debit, "debit"
                elif debit == 0 and credit == 0:
                    result.skipped_rows += 1
                    continue
                else:
                    # Both populated (unusual) -> net it out.
                    net = credit - debit
                    amount, txn_type = abs(net), ("credit" if net >= 0 else "debit")
            else:
                raw_amount = _to_float(row.get("amount", 0))
                if raw_amount == 0:
                    result.skipped_rows += 1
                    continue
                amount = abs(raw_amount)
                if raw_amount < 0:
                    # Explicit negative sign always means an expense.
                    txn_type = "debit"
                else:
                    # Plain positive amount: many simple exports (including this
                    # hackathon's own sample format) don't use sign to indicate
                    # direction, so infer income vs expense from the description.
                    desc_lower = description.lower()
                    txn_type = "credit" if any(k in desc_lower for k in INCOME_KEYWORDS) else "debit"

            result.transactions.append(
                {
                    "date": date_str,
                    "description": description,
                    "amount": round(amount, 2),
                    "transaction_type": txn_type,
                }
            )
        except Exception as e:
            result.skipped_rows += 1
            result.errors.append(f"Row {idx + 2}: skipped ({e})")

    # De-duplicate exact repeats (same date+description+amount+type) which commonly
    # happen when a user re-uploads an overlapping statement period.
    seen: set = set()
    deduped = []
    for t in result.transactions:
        key = (t["date"], t["description"], t["amount"], t["transaction_type"])
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    result.transactions = deduped

    return result


def parse_pdf_bytes(file_bytes: bytes) -> ParseResult:
    """
    Best-effort PDF statement parsing using pdfplumber. This is SECONDARY support --
    CSV remains the guaranteed, reliable path. If pdfplumber is unavailable or the
    statement's table layout isn't recognized, we return a clear error rather than
    guessing at wrong numbers.
    """
    result = ParseResult()
    try:
        import pdfplumber
    except ImportError:
        result.errors.append(
            "PDF support requires the 'pdfplumber' package, which is not installed. "
            "Please export your statement as CSV instead."
        )
        return result

    try:
        rows = []
        header = None
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if not table:
                    continue
                if header is None:
                    header = [str(c or "").strip() for c in table[0]]
                    body = table[1:]
                else:
                    body = table
                for r in body:
                    rows.append(r)

        if header is None or not rows:
            result.errors.append(
                "Could not detect a transaction table in this PDF. Please try CSV instead."
            )
            return result

        df = pd.DataFrame(rows, columns=header)
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        return parse_csv_bytes(csv_buffer.getvalue().encode("utf-8"))

    except Exception as e:
        result.errors.append(f"PDF parsing failed: {e}. Please try CSV instead.")
        return result


def parse_uploaded_file(filename: str, file_bytes: bytes) -> ParseResult:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return parse_pdf_bytes(file_bytes)
    return parse_csv_bytes(file_bytes)
