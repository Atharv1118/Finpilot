"""
utils/merchant.py

Normalizes messy bank-statement descriptions into clean merchant names so that
recurring-payment detection and categorization can group transactions reliably.

Examples handled:
    "UPI-SWIGGY-123456"        -> "Swiggy"
    "SWIGGY*ORDER"              -> "Swiggy"
    "Swiggy India Pvt Ltd"      -> "Swiggy"
    "NETFLIX.COM"               -> "Netflix"
    "Netflix Subscription"      -> "Netflix"
"""

import re

# Known merchant aliases: pattern (lowercase, matched with `in`) -> canonical name.
# Order matters only in that longer/more specific keys should be checked first;
# we sort by key length descending at lookup time to avoid accidental partial hits.
KNOWN_MERCHANTS = {
    "swiggy": "Swiggy",
    "zomato": "Zomato",
    "uber": "Uber",
    "ola": "Ola",
    "rapido": "Rapido",
    "netflix": "Netflix",
    "spotify": "Spotify",
    "amazon prime": "Amazon Prime",
    "amazon": "Amazon",
    "flipkart": "Flipkart",
    "myntra": "Myntra",
    "hotstar": "Disney+ Hotstar",
    "youtube premium": "YouTube Premium",
    "electricity": "Electricity Board",
    "electric board": "Electricity Board",
    "mseb": "Electricity Board",
    "rent": "Rent",
    "salary": "Salary",
    "gym": "Gym Membership",
    "airtel": "Airtel",
    "jio": "Jio",
    "vodafone": "Vodafone Idea",
    "lic": "LIC Premium",
    "gas": "Gas Agency",
    "hospital": "Hospital",
    "pharmacy": "Pharmacy",
    "clinic": "Clinic",
    "college": "College Fees",
    "tuition": "Tuition",
    "udemy": "Udemy",
    "coursera": "Coursera",
    "bookmyshow": "BookMyShow",
    "pvr": "PVR Cinemas",
    "inox": "INOX",
    "irctc": "IRCTC",
    "ongoing": "Other",
}

# Boilerplate tokens stripped out before matching / before falling back to the
# cleaned raw description as the "merchant" name.
NOISE_PATTERNS = [
    r"\bUPI\b",
    r"\bIMPS\b",
    r"\bNEFT\b",
    r"\bRTGS\b",
    r"\bPOS\b",
    r"\bORDER\b",
    r"\bPVT\b",
    r"\bLTD\b",
    r"\bLIMITED\b",
    r"\bINDIA\b",
    r"\bSUBSCRIPTION\b",
    r"\bPAYMENT\b",
    r"\bTXN\b",
    r"\bREF\b",
    r"\.COM\b",
    r"\bDEBIT\b",
    r"\bCREDIT\b",
    r"\bCARD\b",
]

NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE)
NUMERIC_RE = re.compile(r"\d{3,}")
SEPARATOR_RE = re.compile(r"[\-\*_/|]+")
MULTISPACE_RE = re.compile(r"\s+")


def normalize_merchant(description: str) -> str:
    """
    Convert a raw bank statement description into a clean, canonical merchant name.
    Falls back to a title-cased, de-noised version of the original text when no
    known merchant alias matches.
    """
    if not description:
        return "Unknown"

    raw = description.strip()
    lowered = raw.lower()

    # 1. Try known merchant aliases first (longest key first to prefer specificity,
    #    e.g. "amazon prime" over the generic "amazon").
    for key in sorted(KNOWN_MERCHANTS.keys(), key=len, reverse=True):
        if key in lowered:
            return KNOWN_MERCHANTS[key]

    # 2. No known alias -> clean up the raw text to produce a readable merchant name.
    cleaned = SEPARATOR_RE.sub(" ", raw)
    cleaned = NOISE_RE.sub(" ", cleaned)
    cleaned = NUMERIC_RE.sub(" ", cleaned)
    cleaned = MULTISPACE_RE.sub(" ", cleaned).strip()

    if not cleaned:
        return "Unknown"

    return cleaned.title()
