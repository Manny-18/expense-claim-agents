"""Agent 4: Integrity and Duplicate Risk Analyst.

Owns section TE-09. This agent has the strongest constraint in the system and
the narrowest authority: under TE-09.5 and TE-11.4 it may **never** cause an
automatic rejection. Its only powers are to disallow a demonstrated duplicate
and to force escalation to a human.

That constraint is deliberate. A false fraud call against an employee is a far
more expensive error than a few hundred rupees overpaid, and an automated
system should not be the thing that makes it.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .. import tools as T
from ..schemas import Finding
from .base import Blackboard, DomainAgent


class FraudRiskAgent(DomainAgent):
    name = "FraudRiskAgent"
    role = "Integrity and Duplicate Risk Analyst"
    charter = (
        "Detect duplicates against this claim and the employee's claim history, split "
        "bills, round amount patterns, expenses on leave dates and other integrity "
        "signals under TE-09. You may escalate and you may disallow a demonstrated "
        "duplicate. You may never conclude that an employee acted dishonestly and you "
        "may never trigger an automatic rejection."
    )

    def run(self, board: Blackboard) -> List[Finding]:
        claim, employee, history = board.claim, board.employee, board.history
        findings: List[Finding] = []

        findings.extend(T.detect_duplicates_within_claim(claim))
        findings.extend(T.detect_duplicates_against_history(claim, history))
        findings.extend(T.detect_splits(claim))
        findings.extend(T.detect_round_amounts(claim))
        findings.extend(T.detect_leave_date_expenses(claim, employee))
        findings.extend(T.detect_weekend_without_engagement(claim))

        # velocity: unusual claim frequency for this employee in the last 30 days
        recent = [h for h in history if h["employee_id"] == employee.employee_id]
        distinct_claims = {h.get("claim_id") for h in recent}
        if len(distinct_claims) >= 6:
            findings.append(Finding(
                self.name, "VELOCITY", "advisory",
                f"{len(distinct_claims)} prior claims on file for this employee. Volume alone "
                "is not a violation, noted for the reviewer's context.",
                "TE-09.3", None, 0.0))

        # enforce the agent's own ceiling on authority
        for f in findings:
            if f.severity == "integrity":
                f.evidence["needs_human"] = True

        board.notes["integrity_flags"] = len([f for f in findings if f.severity == "integrity"])
        return findings
