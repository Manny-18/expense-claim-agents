"""Agent 1: Document and Data Steward.

Owns the question "is this claim even reviewable?". Evidence sufficiency,
legibility, invoice naming, missing receipt declarations and structural
completeness. It runs first because every downstream agent assumes the data
it reads is worth reading.
"""

from __future__ import annotations

from typing import List

from .. import tools as T
from ..schemas import Finding
from .base import Blackboard, DomainAgent


class IntakeAgent(DomainAgent):
    name = "IntakeAgent"
    role = "Document and Data Steward"
    charter = (
        "Verify that each claim line carries sufficient, legible and correctly named "
        "evidence under section TE-05, and that the claim is structurally complete. "
        "You do not judge whether an expense is within a limit and you do not judge "
        "intent."
    )

    def run(self, board: Blackboard) -> List[Finding]:
        claim, employee = board.claim, board.employee
        findings: List[Finding] = []

        for line in claim.lines:
            findings.extend(T.check_evidence(line, employee))

        # structural completeness
        if not claim.purpose.strip():
            findings.append(Finding(self.name, "ST_NO_PURPOSE", "advisory",
                                    "Claim has no stated business purpose.", "TE-01.2"))
        for line in claim.lines:
            if line.amount <= 0:
                findings.append(Finding(self.name, "ST_BAD_AMOUNT", "violation",
                                        f"Line {line.line_id} has a non positive amount.",
                                        "TE-01.2", line.line_id, max(0.0, line.amount)))
            if line.tax_amount > line.amount:
                findings.append(Finding(self.name, "ST_TAX_GT_AMOUNT", "violation",
                                        f"Line {line.line_id} reports tax of INR "
                                        f"{line.tax_amount:,.0f} on a gross of INR "
                                        f"{line.amount:,.0f}.", "TE-05.1", line.line_id, 0.0,
                                        {"needs_human": True}))
            if line.category == "hotel" and (line.nights or 0) <= 0:
                findings.append(Finding(self.name, "ST_NO_NIGHTS", "advisory",
                                        f"Hotel line {line.line_id} does not state the number of "
                                        "nights; one night assumed.", "TE-02.2", line.line_id))

        board.notes["evidence_ready"] = not any(
            f.severity == "violation" for f in findings)
        return findings
