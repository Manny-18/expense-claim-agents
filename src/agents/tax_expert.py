"""Agent 3: Indirect Tax and Input Credit Expert.

Owns section TE-06. This agent exists because reimbursement correctness and
tax recoverability are different questions with different answers, and a
single reviewer agent tends to conflate them. A hotel bill from another state
is fully reimbursable to the employee and simultaneously worthless as input
credit to the company. Treating that as one judgement produces wrong numbers
on both sides.

Its output is mostly informational: it rarely disallows, but it quantifies
the input tax credit the company can and cannot recover, which is the number
the finance controller actually cares about.
"""

from __future__ import annotations

from typing import List

from .. import tools as T
from ..schemas import Finding
from .base import Blackboard, DomainAgent


class TaxComplianceAgent(DomainAgent):
    name = "TaxComplianceAgent"
    role = "Indirect Tax and Input Credit Expert"
    charter = (
        "Validate vendor GSTINs, classify each line for input tax credit eligibility "
        "under section 17(5) and TE-06, and quantify recoverable and blocked credit. "
        "You do not decide whether an expense is reimbursable to the employee; that "
        "belongs to the Policy Entitlement Expert."
    )

    def run(self, board: Blackboard) -> List[Finding]:
        findings: List[Finding] = []
        for line in board.claim.lines:
            findings.extend(T.check_gst(line))

        recoverable = sum(f.evidence.get("itc_recoverable", 0.0) for f in findings)
        blocked = sum(f.evidence.get("itc_blocked", 0.0) for f in findings)
        lost = sum(f.evidence.get("itc_lost", 0.0) for f in findings)

        board.notes["itc"] = {
            "recoverable": round(recoverable, 2),
            "blocked_by_law": round(blocked, 2),
            "lost_to_bad_documentation": round(lost, 2),
        }

        if lost > 0:
            findings.append(Finding(
                self.name, "GST_CREDIT_LEAKAGE", "advisory",
                f"INR {lost:,.0f} of input tax credit is at risk purely because of missing or "
                "invalid vendor GSTINs. This is recoverable if the vendor reissues the invoice.",
                "TE-06.1", None, 0.0, {"itc_lost": round(lost, 2)}))

        return findings
