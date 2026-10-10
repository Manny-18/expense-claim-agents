"""Policy constants and runtime configuration.

Everything a finance team would change at the start of a financial year lives
here, not inside agent logic. Changing a ceiling should never mean editing an
agent.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policy" / "travel_expense_policy_v3.md"
DATA_DIR = ROOT / "data"
EVAL_DIR = ROOT / "eval"

POLICY_VERSION = "v3.2 (effective 01 Apr 2026)"
COMPANY_NAME = "Meridian Consulting India Pvt. Ltd."
COMPANY_GSTIN = "06AAJCM4321L1ZE"

METRO_CITIES = {
    "Delhi",
    "New Delhi",
    "Gurugram",
    "Noida",
    "Mumbai",
    "Bengaluru",
    "Chennai",
    "Kolkata",
    "Hyderabad",
    "Pune",
}

# TE-02.2 hotel room rent ceiling per night, exclusive of taxes
HOTEL_CEILING = {
    "B1": {"metro": 4000, "non_metro": 2800},
    "B2": {"metro": 5500, "non_metro": 3800},
    "B3": {"metro": 7500, "non_metro": 5000},
    "B4": {"metro": 10000, "non_metro": 7000},
    "B5": {"metro": 15000, "non_metro": 11000},
}

# TE-02.3 daily meal ceiling, inclusive of taxes
MEAL_CEILING = {
    "B1": {"metro": 1200, "non_metro": 900},
    "B2": {"metro": 1500, "non_metro": 1100},
    "B3": {"metro": 2000, "non_metro": 1400},
    "B4": {"metro": 2500, "non_metro": 1800},
    "B5": {"metro": 3500, "non_metro": 2500},
}

# TE-02.4 and TE-02.5 travel class entitlement
AIR_CLASS_RANK = {"economy": 1, "premium_economy": 2, "business": 3, "first": 4}
RAIL_CLASS_RANK = {"sleeper": 0, "ac_chair": 1, "ac3": 1, "ac2": 2, "ac1": 3}

AIR_ENTITLEMENT = {  # max rank allowed, by grade and sector length
    "B1": {"domestic": 1, "short_intl": 1, "long_intl": 1},
    "B2": {"domestic": 1, "short_intl": 1, "long_intl": 1},
    "B3": {"domestic": 1, "short_intl": 1, "long_intl": 1},
    "B4": {"domestic": 1, "short_intl": 1, "long_intl": 2},
    "B5": {"domestic": 3, "short_intl": 3, "long_intl": 3},
}

RAIL_ENTITLEMENT = {"B1": 1, "B2": 1, "B3": 2, "B4": 2, "B5": 2}

# TE-04.3 mileage rates in INR per km
MILEAGE_RATE = {"four_wheeler": 12.00, "two_wheeler": 4.50}

# TE-03.4 internal team meal cap per attendee
TEAM_MEAL_PER_HEAD = 800
# TE-03.3 entertainment pre approval threshold
ENTERTAINMENT_PREAPPROVAL = 8000
# TE-04.4 cab thresholds
CAB_JUSTIFICATION_THRESHOLD = 2500
CAB_PREAPPROVAL_THRESHOLD = 5000
# TE-05.1 tax invoice threshold
TAX_INVOICE_THRESHOLD = 1000
# TE-05.4 missing receipt declaration
MISSING_RECEIPT_CAP = 2000
MISSING_RECEIPT_QUARTER_LIMIT = 2
# TE-10.2 laundry
LAUNDRY_MIN_NIGHTS = 4
LAUNDRY_CAP_PER_TRIP = 500
# TE-10.3 tips
TIP_PERCENT_CAP = 0.10

# TE-07 submission timelines, in days
SUBMISSION_NORMAL_DAYS = 30
SUBMISSION_GRACE_DAYS = 60

# TE-08.1 approval authority ladder
APPROVAL_LADDER = [
    (10000, "Reporting manager"),
    (50000, "Practice head (B4 or above)"),
    (200000, "Finance controller"),
    (float("inf"), "Chief Financial Officer"),
]

# TE-09 integrity thresholds
DUPLICATE_AMOUNT_TOLERANCE = 0.01  # one percent
ROUND_AMOUNT_MIN_COUNT = 3
ROUND_AMOUNT_MIN_VALUE = 1000

# TE-10.1 categories and keywords that are never reimbursable
NON_REIMBURSABLE_KEYWORDS = [
    "alcohol", "liquor", "beer", "wine", "whisky", "bar tab", "cigarette",
    "tobacco", "minibar", "mini bar", "in-room movie", "spa", "salon",
    "grooming", "traffic fine", "challan", "penalty", "gym", "fitness",
    "club membership", "personal shopping", "spouse", "family ticket",
    "loyalty", "lounge membership",
]

# Section 17(5) blocked input tax credit categories, TE-06.2
ITC_BLOCKED_CATEGORIES = {"meals", "entertainment"}

# ------------------------------------------------------------------
# Runtime configuration for the language model layer
# ------------------------------------------------------------------

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "offline").strip().lower()
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1:8b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))


def is_metro(city: str) -> str:
    """Return 'metro' or 'non_metro' for a city name."""
    return "metro" if city.strip() in METRO_CITIES else "non_metro"


def required_approver(total: float) -> str:
    for ceiling, approver in APPROVAL_LADDER:
        if total <= ceiling:
            return approver
    return "Chief Financial Officer"
