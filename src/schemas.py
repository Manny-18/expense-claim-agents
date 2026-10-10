"""Data contracts shared by every agent.

Plain dataclasses are used deliberately: the whole pipeline must run on a
laptop with no framework installed, and a reviewer should be able to read a
claim object without learning a validation library.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# Enumerated vocabularies (kept as plain strings so JSON stays human readable)
# --------------------------------------------------------------------------

GRADES = ["B1", "B2", "B3", "B4", "B5"]

CATEGORIES = [
    "hotel",
    "meals",
    "entertainment",
    "cab",
    "mileage",
    "air",
    "rail",
    "laundry",
    "misc",
]

TRIP_TYPES = ["outstation_overnight", "outstation_same_day", "local", "none"]

OUTCOMES = ["APPROVE", "PARTIAL_APPROVE", "REJECT", "ESCALATE"]

SEVERITIES = ["info", "advisory", "violation", "integrity"]


# --------------------------------------------------------------------------
# Core objects
# --------------------------------------------------------------------------


@dataclass
class Employee:
    employee_id: str
    name: str
    grade: str
    base_city: str
    manager_id: str
    manager_grade: str
    leave_dates: List[str] = field(default_factory=list)
    missing_receipt_uses_this_quarter: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LineItem:
    """One expense line inside a claim."""

    line_id: str
    category: str
    vendor: str
    expense_date: str  # ISO yyyy-mm-dd
    amount: float  # gross amount the employee is claiming, in INR
    city: str

    description: str = ""
    tax_amount: float = 0.0
    gstin: Optional[str] = None
    invoice_no: Optional[str] = None

    receipt_available: bool = True
    receipt_legible: bool = True
    missing_receipt_declaration: bool = False
    invoice_name: str = "employee"  # employee | company | third_party

    # category specific fields
    nights: Optional[int] = None  # hotel
    attendees: List[str] = field(default_factory=list)  # meals, entertainment
    client_attendee_named: bool = False  # entertainment
    contains_alcohol: bool = False
    alcohol_amount: float = 0.0
    distance_km: Optional[float] = None  # mileage
    vehicle_type: Optional[str] = None  # four_wheeler | two_wheeler
    travel_class: Optional[str] = None  # economy | premium_economy | business | ac3 | ac2
    sector_hours: Optional[float] = None  # air
    journey_start_hour: Optional[int] = None  # cab, 0 to 23
    journey_purpose: Optional[str] = None  # client_site | airport | station | office | home

    justification: str = ""
    pre_approved: bool = False
    booked_via_travel_desk: bool = False
    client_rechargeable: bool = False
    engagement_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LineItem":
        known = {f for f in LineItem.__dataclass_fields__}
        return LineItem(**{k: v for k, v in d.items() if k in known})


@dataclass
class Claim:
    claim_id: str
    employee_id: str
    submitted_date: str
    trip_type: str
    purpose: str
    lines: List[LineItem] = field(default_factory=list)

    @property
    def claimed_total(self) -> float:
        return round(sum(l.amount for l in self.lines), 2)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["claimed_total"] = self.claimed_total
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Claim":
        return Claim(
            claim_id=d["claim_id"],
            employee_id=d["employee_id"],
            submitted_date=d["submitted_date"],
            trip_type=d.get("trip_type", "none"),
            purpose=d.get("purpose", ""),
            lines=[LineItem.from_dict(l) for l in d.get("lines", [])],
        )


@dataclass
class Finding:
    """A single observation produced by an agent.

    `disallowed_amount` is the rupee value this finding removes from the
    payable total. A finding can be a violation without disallowing anything,
    for example a missing corporate GSTIN under TE-06.4.
    """

    agent: str
    code: str
    severity: str
    message: str
    clause: str = ""
    line_id: Optional[str] = None
    disallowed_amount: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TraceStep:
    agent: str
    role: str
    input_summary: str
    output_summary: str
    findings_count: int
    duration_ms: int
    used_llm: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Decision:
    claim_id: str
    employee_id: str
    outcome: str
    claimed_total: float
    disallowed_total: float
    approved_total: float
    risk_score: int
    required_approver: str
    reasons: List[str] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    employee_message: str = ""
    audit_note: str = ""
    trace: List[TraceStep] = field(default_factory=list)
    decided_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "employee_id": self.employee_id,
            "outcome": self.outcome,
            "claimed_total": self.claimed_total,
            "disallowed_total": self.disallowed_total,
            "approved_total": self.approved_total,
            "risk_score": self.risk_score,
            "required_approver": self.required_approver,
            "reasons": self.reasons,
            "findings": [f.to_dict() for f in self.findings],
            "employee_message": self.employee_message,
            "audit_note": self.audit_note,
            "trace": [t.to_dict() for t in self.trace],
            "decided_at": self.decided_at,
        }


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()
