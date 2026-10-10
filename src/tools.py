"""Deterministic tools: the hands of the agent system.

Design rule for this project: **an agent never computes a rupee value and
never decides a limit breach by reading text.** Arithmetic, date maths,
checksum validation and threshold comparison all happen here, in ordinary
Python that can be unit tested. The language model is used only for
classification of free text and for explanation.

This is the single most important design choice in the project. A finance
control that silently miscalculates is worse than no control at all, and a
language model cannot be audited the way a function with tests can.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from . import config as C
from .schemas import Claim, Employee, Finding, LineItem, parse_date

GSTIN_CODE_POINTS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}


# ---------------------------------------------------------------------------
# Tool 1: GSTIN validation (real checksum, not a regex guess)
# ---------------------------------------------------------------------------


def validate_gstin(gstin: Optional[str]) -> Dict[str, Any]:
    """Validate a GSTIN structurally and by its modulus 36 checksum."""
    if not gstin:
        return {"valid": False, "reason": "absent", "state_code": None}

    g = gstin.strip().upper()
    if len(g) != 15:
        return {"valid": False, "reason": "length is not 15 characters", "state_code": None}
    if not GSTIN_PATTERN.match(g):
        return {"valid": False, "reason": "does not match the GSTIN format", "state_code": g[:2]}
    if g[:2] not in VALID_STATE_CODES:
        return {"valid": False, "reason": f"state code {g[:2]} is not issued", "state_code": g[:2]}

    factor, total = 2, 0
    for i in reversed(range(14)):
        cp = GSTIN_CODE_POINTS.index(g[i])
        product = factor * cp
        factor = 1 if factor == 2 else 2
        total += (product // 36) + (product % 36)
    expected = GSTIN_CODE_POINTS[(36 - (total % 36)) % 36]

    if expected != g[14]:
        return {
            "valid": False,
            "reason": f"checksum mismatch, expected {expected}",
            "state_code": g[:2],
        }
    return {"valid": True, "reason": "ok", "state_code": g[:2]}


# ---------------------------------------------------------------------------
# Tool 2: evidence sufficiency (TE-05)
# ---------------------------------------------------------------------------


def check_evidence(line: LineItem, employee: Employee) -> List[Finding]:
    f: List[Finding] = []
    a = "IntakeAgent"

    if not line.receipt_available:
        if line.missing_receipt_declaration:
            if line.amount > C.MISSING_RECEIPT_CAP:
                f.append(Finding(a, "EV_MRD_OVER_CAP", "violation",
                                 f"Missing Receipt Declaration used on INR {line.amount:,.0f}, "
                                 f"above the INR {C.MISSING_RECEIPT_CAP:,} cap.",
                                 "TE-05.4", line.line_id, line.amount))
            elif employee.missing_receipt_uses_this_quarter >= C.MISSING_RECEIPT_QUARTER_LIMIT:
                f.append(Finding(a, "EV_MRD_QUOTA", "violation",
                                 f"Employee has already used {employee.missing_receipt_uses_this_quarter} "
                                 "Missing Receipt Declarations this quarter; the limit is two.",
                                 "TE-05.4", line.line_id, line.amount))
            else:
                f.append(Finding(a, "EV_MRD_ACCEPTED", "advisory",
                                 "Missing Receipt Declaration accepted within quarterly quota.",
                                 "TE-05.4", line.line_id, 0.0))
        else:
            f.append(Finding(a, "EV_NO_RECEIPT", "violation",
                             "No receipt and no Missing Receipt Declaration.",
                             "TE-05.1", line.line_id, line.amount))
    else:
        if not line.receipt_legible:
            f.append(Finding(a, "EV_ILLEGIBLE", "violation",
                             "Receipt image is not legible, vendor, date or total cannot be read.",
                             "TE-05.5", line.line_id, line.amount))
        if line.amount >= C.TAX_INVOICE_THRESHOLD and not line.invoice_no:
            f.append(Finding(a, "EV_NO_INVOICE_NO", "violation",
                             f"Claim line of INR {line.amount:,.0f} has no tax invoice number; "
                             "a GST compliant invoice is required at or above INR 1,000.",
                             "TE-05.1", line.line_id, line.amount))

    if line.category == "hotel" and line.invoice_name == "third_party":
        f.append(Finding(a, "EV_THIRD_PARTY_INVOICE", "violation",
                         "Hotel invoice is in a third party name.",
                         "TE-05.3", line.line_id, line.amount))
    return f


# ---------------------------------------------------------------------------
# Tool 3: entitlement ceilings (TE-02, TE-03)
# ---------------------------------------------------------------------------


def check_hotel_ceiling(line: LineItem, employee: Employee) -> List[Finding]:
    if line.category != "hotel":
        return []
    band = C.is_metro(line.city)
    nights = max(1, line.nights or 1)
    ceiling = C.HOTEL_CEILING[employee.grade][band] * nights
    net = round(line.amount - line.tax_amount, 2)  # ceiling is exclusive of taxes
    if net > ceiling:
        excess = round(net - ceiling, 2)
        return [Finding("PolicyExpertAgent", "LIM_HOTEL", "violation",
                        f"Room rent of INR {net:,.0f} for {nights} night(s) in a {band.replace('_', ' ')} "
                        f"city exceeds the grade {employee.grade} ceiling of INR {ceiling:,.0f}. "
                        f"Excess of INR {excess:,.0f} is disallowed.",
                        "TE-02.2", line.line_id, excess,
                        {"ceiling": ceiling, "net_claimed": net, "nights": nights})]
    return []


def check_meal_ceilings(claim: Claim, employee: Employee) -> List[Finding]:
    """Meal ceilings are daily caps tested on the sum of the day (TE-03.1).

    Two scoping rules that are easy to get wrong and expensive when wrong:

    * TE-02.3 sets the daily ceiling for an employee **on an outstation trip**.
      It does not govern a meal taken in the city of posting, so applying it to
      a local claim would disallow money the policy never restricted.
    * An internal team meal is governed by the per attendee cap in TE-03.4, not
      by the individual's daily ceiling. Testing it against both would disallow
      the same rupee twice under two different clauses.
    """
    findings: List[Finding] = []
    outstation = claim.trip_type in {"outstation_overnight", "outstation_same_day"}

    by_day: Dict[Tuple[str, str], List[LineItem]] = defaultdict(list)
    for line in claim.lines:
        if line.category == "meals" and "team" not in line.description.lower():
            by_day[(line.expense_date, line.city)].append(line)

    same_day_trip = claim.trip_type == "outstation_same_day"

    for (day, city), lines in sorted(by_day.items()):
        band = C.is_metro(city)
        ceiling = C.MEAL_CEILING[employee.grade][band]
        if same_day_trip:
            ceiling = ceiling * 0.5  # TE-03.5
        claimable = sum(l.amount - l.alcohol_amount for l in lines)

        if not outstation:
            # The policy sets no ceiling for a meal in the city of posting. Rather
            # than invent one, surface the gap for the policy owner.
            if claimable > ceiling:
                findings.append(Finding(
                    "PolicyExpertAgent", "GAP_LOCAL_MEAL", "advisory",
                    f"Meals of INR {claimable:,.0f} on {day} in the city of posting exceed the "
                    f"outstation daily ceiling of INR {ceiling:,.0f}, but TE-02.3 sets no "
                    "ceiling for local meals. Nothing is disallowed; flagged for the policy "
                    "owner.", "TE-02.3", lines[0].line_id, 0.0,
                    {"policy_gap": True, "day": day}))
            continue

        if claimable > ceiling:
            excess = round(claimable - ceiling, 2)
            biggest = max(lines, key=lambda l: l.amount)
            findings.append(Finding(
                "PolicyExpertAgent", "LIM_MEALS", "violation",
                f"Meals on {day} in {city} total INR {claimable:,.0f} against a daily ceiling of "
                f"INR {ceiling:,.0f} for grade {employee.grade}"
                + (" (halved for a same day return trip)" if same_day_trip else "")
                + f". Excess of INR {excess:,.0f} is disallowed.",
                "TE-03.1" if not same_day_trip else "TE-03.5",
                biggest.line_id, excess,
                {"day": day, "city": city, "ceiling": ceiling, "claimed": claimable,
                 "line_ids": [l.line_id for l in lines]}))
    return findings


def check_alcohol(line: LineItem) -> List[Finding]:
    if line.alcohol_amount > 0 or line.contains_alcohol:
        amt = line.alcohol_amount if line.alcohol_amount > 0 else line.amount
        return [Finding("PolicyExpertAgent", "NR_ALCOHOL", "violation",
                        f"Alcohol of INR {amt:,.0f} is not reimbursable in any circumstance.",
                        "TE-03.2", line.line_id, round(amt, 2))]
    return []


def check_non_reimbursable_text(line: LineItem) -> List[Finding]:
    """Keyword screen over the free text description (TE-10.1)."""
    blob = f"{line.description} {line.vendor}".lower()
    hits = [k for k in C.NON_REIMBURSABLE_KEYWORDS if k in blob]
    # alcohol is handled by its own tool with an explicit amount
    hits = [h for h in hits if h not in {"alcohol", "liquor", "beer", "wine", "whisky", "bar tab"}]
    if hits:
        return [Finding("PolicyExpertAgent", "NR_ITEM", "violation",
                        f"Line matches the non reimbursable list ({', '.join(hits)}).",
                        "TE-10.1", line.line_id, line.amount, {"keywords": hits})]
    return []


def check_entertainment(line: LineItem) -> List[Finding]:
    if line.category != "entertainment":
        return []
    f: List[Finding] = []
    if not line.client_attendee_named or not line.attendees:
        f.append(Finding("PolicyExpertAgent", "ENT_NO_ATTENDEE", "violation",
                         "Client entertainment with no named client attendee is not reimbursable.",
                         "TE-03.3", line.line_id, line.amount))
        return f
    if not line.engagement_code:
        f.append(Finding("PolicyExpertAgent", "ENT_NO_CODE", "violation",
                         "Client entertainment without an engagement code is not reimbursable.",
                         "TE-03.3", line.line_id, line.amount))
        return f
    if line.amount > C.ENTERTAINMENT_PREAPPROVAL and not line.pre_approved:
        f.append(Finding("PolicyExpertAgent", "ENT_NO_PREAPPROVAL", "violation",
                         f"Entertainment of INR {line.amount:,.0f} exceeds INR "
                         f"{C.ENTERTAINMENT_PREAPPROVAL:,} without pre approval from a B4 or above.",
                         "TE-03.3", line.line_id, 0.0, {"needs_human": True}))
    return f


def check_team_meal(line: LineItem) -> List[Finding]:
    """Internal team meals, capped per attendee (TE-03.4)."""
    if line.category != "meals" or "team" not in line.description.lower():
        return []
    heads = max(1, len(line.attendees))
    cap = C.TEAM_MEAL_PER_HEAD * heads
    if not line.attendees:
        return [Finding("PolicyExpertAgent", "TM_NO_LIST", "violation",
                        "Internal team meal without an attendee list.",
                        "TE-03.4", line.line_id, line.amount)]
    if line.amount > cap:
        excess = round(line.amount - cap, 2)
        return [Finding("PolicyExpertAgent", "TM_OVER_CAP", "violation",
                        f"Team meal of INR {line.amount:,.0f} for {heads} attendees exceeds the "
                        f"INR {C.TEAM_MEAL_PER_HEAD} per head cap (INR {cap:,.0f}). "
                        f"Excess of INR {excess:,.0f} is disallowed.",
                        "TE-03.4", line.line_id, excess)]
    return []


def check_travel_class(line: LineItem, employee: Employee) -> List[Finding]:
    if line.category == "air" and line.travel_class:
        hours = line.sector_hours or 0
        sector = "domestic" if hours <= 3.5 else ("short_intl" if hours <= 6 else "long_intl")
        allowed = C.AIR_ENTITLEMENT[employee.grade][sector]
        taken = C.AIR_CLASS_RANK.get(line.travel_class, 1)
        if taken > allowed:
            return [Finding("PolicyExpertAgent", "CLS_AIR", "violation",
                            f"{line.travel_class.replace('_', ' ')} class on a {sector.replace('_', ' ')} "
                            f"sector is above the grade {employee.grade} entitlement.",
                            "TE-02.4", line.line_id, 0.0,
                            {"needs_human": True})]
    if line.category == "rail" and line.travel_class:
        allowed = C.RAIL_ENTITLEMENT[employee.grade]
        taken = C.RAIL_CLASS_RANK.get(line.travel_class, 1)
        if taken > allowed:
            return [Finding("PolicyExpertAgent", "CLS_RAIL", "violation",
                            f"Rail class {line.travel_class} is above the grade {employee.grade} "
                            "entitlement.", "TE-02.5", line.line_id, 0.0, {"needs_human": True})]
    return []


# ---------------------------------------------------------------------------
# Tool 4: conveyance and mileage (TE-04)
# ---------------------------------------------------------------------------


def check_mileage(line: LineItem) -> List[Finding]:
    if line.category != "mileage":
        return []
    if not line.distance_km or not line.vehicle_type:
        return [Finding("PolicyExpertAgent", "MIL_INCOMPLETE", "violation",
                        "Mileage claim without distance or vehicle type cannot be verified.",
                        "TE-04.3", line.line_id, line.amount)]
    rate = C.MILEAGE_RATE.get(line.vehicle_type)
    if rate is None:
        return [Finding("PolicyExpertAgent", "MIL_BAD_VEHICLE", "violation",
                        f"Unknown vehicle type '{line.vehicle_type}'.",
                        "TE-04.3", line.line_id, line.amount)]
    entitled = round(line.distance_km * rate, 2)
    if line.amount > entitled + 0.5:
        excess = round(line.amount - entitled, 2)
        return [Finding("PolicyExpertAgent", "MIL_OVER_RATE", "violation",
                        f"{line.distance_km:g} km at INR {rate:.2f} per km entitles INR {entitled:,.0f}; "
                        f"INR {line.amount:,.0f} was claimed. Excess of INR {excess:,.0f} is disallowed.",
                        "TE-04.3", line.line_id, excess,
                        {"entitled": entitled, "rate": rate})]
    return []


def check_fuel_with_mileage(claim: Claim) -> List[Finding]:
    """TE-04.3 forbids a fuel bill alongside mileage for the same journey date."""
    mileage_dates = {l.expense_date for l in claim.lines if l.category == "mileage"}
    out: List[Finding] = []
    for line in claim.lines:
        if line.category in {"misc", "cab"} and "fuel" in f"{line.description} {line.vendor}".lower():
            if line.expense_date in mileage_dates:
                out.append(Finding("PolicyExpertAgent", "MIL_FUEL_DOUBLE", "violation",
                                   "Fuel claimed on the same date as a mileage claim. Mileage already "
                                   "includes fuel, so the fuel line is disallowed.",
                                   "TE-04.3", line.line_id, line.amount))
    return out


def check_cab_rules(line: LineItem) -> List[Finding]:
    if line.category != "cab":
        return []
    f: List[Finding] = []
    hour = line.journey_start_hour
    purpose = (line.journey_purpose or "").lower()
    if purpose in {"home", "office"} and hour is not None and 9 <= hour < 19:
        f.append(Finding("PolicyExpertAgent", "CAB_COMMUTE", "violation",
                         f"Home to office travel at {hour:02d}:00 falls inside the 09:00 to 19:00 "
                         "window and is a personal commute.",
                         "TE-04.2", line.line_id, line.amount))
        return f
    if line.amount > C.CAB_PREAPPROVAL_THRESHOLD and not line.pre_approved:
        f.append(Finding("PolicyExpertAgent", "CAB_PREAPPROVAL", "violation",
                         f"Cab fare of INR {line.amount:,.0f} exceeds INR "
                         f"{C.CAB_PREAPPROVAL_THRESHOLD:,} without pre approval.",
                         "TE-04.4", line.line_id, 0.0, {"needs_human": True}))
    elif line.amount > C.CAB_JUSTIFICATION_THRESHOLD and not line.justification.strip():
        f.append(Finding("PolicyExpertAgent", "CAB_NO_JUSTIFICATION", "violation",
                         f"Cab fare of INR {line.amount:,.0f} exceeds INR "
                         f"{C.CAB_JUSTIFICATION_THRESHOLD:,} with no written justification.",
                         "TE-04.4", line.line_id, 0.0, {"needs_human": True}))
    return f


def check_laundry(claim: Claim, line: LineItem) -> List[Finding]:
    if line.category != "laundry":
        return []
    nights = max((l.nights or 0) for l in claim.lines) if claim.lines else 0
    if nights < C.LAUNDRY_MIN_NIGHTS:
        return [Finding("PolicyExpertAgent", "LND_SHORT_TRIP", "violation",
                        f"Laundry is reimbursable only on trips of {C.LAUNDRY_MIN_NIGHTS} nights or "
                        f"more; this trip has {nights} night(s).",
                        "TE-10.2", line.line_id, line.amount)]
    if line.amount > C.LAUNDRY_CAP_PER_TRIP:
        excess = round(line.amount - C.LAUNDRY_CAP_PER_TRIP, 2)
        return [Finding("PolicyExpertAgent", "LND_OVER_CAP", "violation",
                        f"Laundry of INR {line.amount:,.0f} exceeds the INR {C.LAUNDRY_CAP_PER_TRIP} "
                        f"per trip cap. Excess of INR {excess:,.0f} is disallowed.",
                        "TE-10.2", line.line_id, excess)]
    return []


# ---------------------------------------------------------------------------
# Tool 5: timeliness (TE-07)
# ---------------------------------------------------------------------------


def check_timeliness(claim: Claim) -> List[Finding]:
    submitted = parse_date(claim.submitted_date)
    out: List[Finding] = []
    for line in claim.lines:
        age = (submitted - parse_date(line.expense_date)).days
        if age > C.SUBMISSION_GRACE_DAYS:
            out.append(Finding("PolicyExpertAgent", "TIME_BARRED", "violation",
                               f"Expense dated {line.expense_date} was submitted {age} days later, "
                               f"beyond the {C.SUBMISSION_GRACE_DAYS} day hard limit. Not payable.",
                               "TE-07.3", line.line_id, line.amount, {"age_days": age}))
        elif age > C.SUBMISSION_NORMAL_DAYS:
            out.append(Finding("PolicyExpertAgent", "TIME_LATE", "violation",
                               f"Expense dated {line.expense_date} was submitted {age} days later. "
                               "Between 31 and 60 days a written justification and B4 approval are "
                               "required, so this needs a human approver rather than a rejection.",
                               "TE-07.2", line.line_id, 0.0,
                               {"age_days": age, "needs_human": True}))
        elif age < 0:
            out.append(Finding("FraudRiskAgent", "TIME_FUTURE", "integrity",
                               f"Expense dated {line.expense_date} is after the submission date "
                               f"{claim.submitted_date}.",
                               "TE-09.4", line.line_id, 0.0, {"needs_human": True}))
    return out


# ---------------------------------------------------------------------------
# Tool 6: integrity and duplicate detection (TE-09)
# ---------------------------------------------------------------------------


def detect_duplicates_within_claim(claim: Claim) -> List[Finding]:
    """Flag, do not disallow.

    TE-09.1 defines a *suspected* duplicate. Two genuine taxi rides from the
    same aggregator on the same day can look identical, so the system records
    the amount at risk in the evidence and leaves the money decision to the
    human reviewer, as TE-11.4 requires.
    """
    out: List[Finding] = []
    seen: List[LineItem] = []
    for line in claim.lines:
        for prior in seen:
            if (normalize_vendor(prior.vendor) == normalize_vendor(line.vendor)
                    and prior.expense_date == line.expense_date
                    and _within_tolerance(prior.amount, line.amount)):
                out.append(Finding("FraudRiskAgent", "DUP_IN_CLAIM", "integrity",
                                   f"Line {line.line_id} duplicates line {prior.line_id}: same vendor "
                                   f"({line.vendor}), same date ({line.expense_date}) and an amount "
                                   f"within one percent.",
                                   "TE-09.1", line.line_id, 0.0,
                                   {"duplicate_of": prior.line_id, "needs_human": True,
                                    "amount_at_risk": line.amount}))
                break
        seen.append(line)
    return out


def detect_duplicates_against_history(claim: Claim, history: List[Dict[str, Any]]) -> List[Finding]:
    """History rows: employee_id, claim_id, line_id, vendor, expense_date, amount."""
    out: List[Finding] = []
    mine = [h for h in history if h["employee_id"] == claim.employee_id
            and h.get("claim_id") != claim.claim_id]
    for line in claim.lines:
        for h in mine:
            if (normalize_vendor(str(h["vendor"])) == normalize_vendor(line.vendor)
                    and str(h["expense_date"]) == line.expense_date
                    and _within_tolerance(float(h["amount"]), line.amount)):
                out.append(Finding("FraudRiskAgent", "DUP_HISTORY", "integrity",
                                   f"Line {line.line_id} matches a line already submitted in claim "
                                   f"{h['claim_id']}: same vendor, same date, amount within one percent.",
                                   "TE-09.1", line.line_id, 0.0,
                                   {"prior_claim": h["claim_id"], "needs_human": True,
                                    "amount_at_risk": line.amount}))
                break
    return out


def detect_splits(claim: Claim) -> List[Finding]:
    """Two or more lines, same vendor and date, each just under a threshold."""
    out: List[Finding] = []
    groups: Dict[Tuple[str, str], List[LineItem]] = defaultdict(list)
    for line in claim.lines:
        groups[(normalize_vendor(line.vendor), line.expense_date)].append(line)

    for (vendor, day), lines in groups.items():
        if len(lines) < 2:
            continue
        total = sum(l.amount for l in lines)
        just_under = [l for l in lines
                      if 0.75 * C.TAX_INVOICE_THRESHOLD <= l.amount < C.TAX_INVOICE_THRESHOLD]
        if len(just_under) >= 2 and total >= C.TAX_INVOICE_THRESHOLD:
            out.append(Finding("FraudRiskAgent", "SPLIT_SUSPECT", "integrity",
                               f"{len(just_under)} lines from {lines[0].vendor} on {day} each sit just "
                               f"below the INR {C.TAX_INVOICE_THRESHOLD:,} invoice threshold but total "
                               f"INR {total:,.0f}. This has the shape of a split bill.",
                               "TE-09.2", lines[0].line_id, 0.0,
                               {"line_ids": [l.line_id for l in lines], "needs_human": True}))
    return out


def detect_round_amounts(claim: Claim) -> List[Finding]:
    rounds = [l for l in claim.lines
              if l.amount >= C.ROUND_AMOUNT_MIN_VALUE and abs(l.amount - round(l.amount)) < 1e-9
              and int(round(l.amount)) % 100 == 0]
    if len(rounds) >= C.ROUND_AMOUNT_MIN_COUNT:
        return [Finding("FraudRiskAgent", "ROUND_PATTERN", "advisory",
                        f"{len(rounds)} lines above INR 1,000 end in exactly 00. This is a review flag, "
                        "not a rejection.",
                        "TE-09.3", None, 0.0, {"line_ids": [l.line_id for l in rounds]})]
    return []


def detect_leave_date_expenses(claim: Claim, employee: Employee) -> List[Finding]:
    out: List[Finding] = []
    leave = set(employee.leave_dates)
    for line in claim.lines:
        if line.expense_date in leave:
            out.append(Finding("FraudRiskAgent", "LEAVE_DATE", "integrity",
                               f"Expense dated {line.expense_date} falls on an approved leave day and "
                               "needs an explanation.",
                               "TE-09.4", line.line_id, 0.0, {"needs_human": True}))
    return out


def detect_weekend_without_engagement(claim: Claim) -> List[Finding]:
    out: List[Finding] = []
    for line in claim.lines:
        d = parse_date(line.expense_date)
        if d.weekday() >= 5 and not line.engagement_code and line.amount >= 2000:
            out.append(Finding("FraudRiskAgent", "WEEKEND_NO_CODE", "advisory",
                               f"Expense of INR {line.amount:,.0f} on {d.strftime('%A')} "
                               f"{line.expense_date} carries no engagement code.",
                               "TE-09.4", line.line_id, 0.0))
    return out


VENDOR_NOISE = re.compile(r"\b(pvt|private|ltd|limited|llp|inc|co|company|india)\b")


def normalize_vendor(name: str) -> str:
    """Canonical vendor key for matching.

    "Uber India Pvt Ltd", "  uber   india " and "UBER-INDIA" are the same
    merchant. Without this, duplicate detection is defeated by a space, which
    is exactly the kind of gap a control is supposed to close.
    """
    s = (name or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = VENDOR_NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _within_tolerance(a: float, b: float) -> bool:
    base = max(abs(a), abs(b), 1.0)
    return abs(a - b) / base <= C.DUPLICATE_AMOUNT_TOLERANCE


# ---------------------------------------------------------------------------
# Tool 7: GST and input tax credit (TE-06)
# ---------------------------------------------------------------------------


def check_gst(line: LineItem) -> List[Finding]:
    out: List[Finding] = []
    a = "TaxComplianceAgent"

    if line.amount >= C.TAX_INVOICE_THRESHOLD:
        result = validate_gstin(line.gstin)
        if not result["valid"]:
            if result["reason"] == "absent":
                out.append(Finding(a, "GST_ABSENT", "violation",
                                   f"No vendor GSTIN on an invoice of INR {line.amount:,.0f}. "
                                   "Input tax credit cannot be claimed and the invoice is not GST "
                                   "compliant.", "TE-05.1", line.line_id, 0.0,
                                   {"itc_lost": round(line.tax_amount, 2), "needs_human": True}))
            else:
                out.append(Finding(a, "GST_INVALID", "violation",
                                   f"Vendor GSTIN {line.gstin} is invalid: {result['reason']}.",
                                   "TE-06.1", line.line_id, 0.0,
                                   {"itc_lost": round(line.tax_amount, 2), "needs_human": True}))
        else:
            if line.category in C.ITC_BLOCKED_CATEGORIES:
                out.append(Finding(a, "GST_ITC_BLOCKED", "info",
                                   f"Food and beverage falls under blocked credit. INR "
                                   f"{line.tax_amount:,.0f} of tax is not recoverable; the line is "
                                   "reimbursed at gross.", "TE-06.2", line.line_id, 0.0,
                                   {"itc_blocked": round(line.tax_amount, 2)}))
            elif line.category == "hotel" and result["state_code"] != C.COMPANY_GSTIN[:2]:
                out.append(Finding(a, "GST_CROSS_STATE", "info",
                                   f"Hotel invoice carries state code {result['state_code']}, outside "
                                   "the state of registration, so CGST and SGST credit is unavailable. "
                                   "Reimbursed at gross.", "TE-06.3", line.line_id, 0.0,
                                   {"itc_blocked": round(line.tax_amount, 2)}))
            else:
                out.append(Finding(a, "GST_ITC_OK", "info",
                                   f"Input tax credit of INR {line.tax_amount:,.0f} is recoverable.",
                                   "TE-06.1", line.line_id, 0.0,
                                   {"itc_recoverable": round(line.tax_amount, 2)}))

    if line.category in {"air", "rail"} and line.booked_via_travel_desk:
        if C.COMPANY_GSTIN not in (line.description or ""):
            out.append(Finding(a, "GST_NO_CORP_GSTIN", "advisory",
                               "Travel desk booking does not carry the Meridian GSTIN. Under TE-06.4 "
                               "this is a recoverable error: approve and return the invoice to the "
                               "travel desk for amendment.", "TE-06.4", line.line_id, 0.0))
    return out


# ---------------------------------------------------------------------------
# Tool 8: approval routing and risk scoring
# ---------------------------------------------------------------------------


def route_approval(approved_total: float, employee: Employee) -> Dict[str, Any]:
    approver = C.required_approver(approved_total)
    self_approval_risk = approver == "Reporting manager" and employee.manager_id == employee.employee_id
    return {"required_approver": approver, "self_approval_conflict": self_approval_risk}


SEVERITY_WEIGHT = {"info": 0, "advisory": 3, "violation": 8, "integrity": 25}


def risk_score(findings: List[Finding], claimed_total: float, disallowed_total: float) -> int:
    score = sum(SEVERITY_WEIGHT.get(f.severity, 0) for f in findings)
    if claimed_total > 0:
        score += int(40 * min(1.0, disallowed_total / claimed_total))
    return int(max(0, min(100, score)))
