"""Agent 5: Adjudicator.

Owns section TE-08 and TE-11. It is the only agent allowed to produce an
outcome, and it does so by arbitration rather than by re-reasoning: it reads
the findings the expert agents produced and applies a fixed precedence order.

Precedence, highest first:

1. **Escalation beats everything.** Any integrity flag, or any finding that
   asks for a human, forces ESCALATE. TE-11.3 and TE-11.4 put the burden of a
   clean rejection on the reviewer, not the employee.
2. **An uncited disallowance is invalid** under TE-11.2 and is converted into
   an escalation rather than silently applied.
3. If nothing payable survives, REJECT.
4. If something was disallowed but a balance remains, PARTIAL_APPROVE.
5. Otherwise APPROVE.

The order matters more than any individual rule. It is what stops the system
from rejecting a person on a machine's say so.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .. import config as C
from .. import tools as T
from ..schemas import Decision, Finding
from .base import Blackboard, DomainAgent

SEVERITY_ORDER = {"integrity": 0, "violation": 1, "advisory": 2, "info": 3}


class AdjudicatorAgent(DomainAgent):
    name = "AdjudicatorAgent"
    role = "Claim Adjudicator and Approval Router"
    charter = (
        "Arbitrate the findings of the expert agents into one outcome under TE-11, "
        "compute the payable amount, and route the claim to the correct approval "
        "authority under TE-08. You never create new findings about the expense "
        "itself and you never overrule an escalation."
    )

    def run(self, board: Blackboard) -> List[Finding]:
        findings: List[Finding] = []

        # TE-11.2: a disallowance with no clause cannot stand
        for f in board.findings:
            if f.disallowed_amount > 0 and not f.clause.strip():
                f.disallowed_amount = 0.0
                f.evidence["needs_human"] = True
                findings.append(Finding(
                    self.name, "ADJ_UNCITED", "advisory",
                    f"A disallowance raised by {f.agent} cited no clause, so it was converted "
                    "into an escalation.", "TE-11.2", f.line_id, 0.0, {"needs_human": True}))

        claimed = board.claim.claimed_total
        disallowed = board.disallowed_total()
        approved = round(max(0.0, claimed - disallowed), 2)

        # A query about a line that is not being paid cannot change the
        # settlement, so it must not cost a human their attention. Integrity
        # flags are exempt: TE-11.4 requires those to reach a person whatever
        # the money does.
        findings.extend(self._retire_moot_escalations(board))

        routing = T.route_approval(approved, board.employee)
        extra_escalation = False
        if routing["self_approval_conflict"]:
            extra_escalation = True
            findings.append(Finding(
                self.name, "ADJ_SELF_APPROVAL", "violation",
                "The claimant is their own approver, which TE-08.2 prohibits. Routing up one "
                "level.", "TE-08.2", None, 0.0, {"needs_human": True}))

        outcome = self._decide(board, approved, disallowed, extra_escalation)

        board.notes["outcome"] = outcome
        board.notes["approved_total"] = approved
        board.notes["disallowed_total"] = disallowed
        board.notes["required_approver"] = routing["required_approver"]
        return findings

    # ------------------------------------------------------------------

    def _retire_moot_escalations(self, board: Blackboard) -> List[Finding]:
        """Drop human review requests that cannot change the payable amount."""
        per_line: Dict[str, float] = {}
        for f in board.findings:
            if f.line_id and f.disallowed_amount > 0:
                per_line[f.line_id] = max(per_line.get(f.line_id, 0.0), f.disallowed_amount)
        fully_disallowed = {l.line_id for l in board.claim.lines
                            if per_line.get(l.line_id, 0.0) >= l.amount - 0.009}

        notes: List[Finding] = []
        for f in board.findings:
            if (f.evidence.get("needs_human") and f.severity != "integrity"
                    and f.line_id in fully_disallowed):
                f.evidence["needs_human"] = False
                f.evidence["moot"] = "line is already not payable"
                notes.append(Finding(
                    self.name, "ADJ_MOOT_QUERY", "info",
                    f"The query raised by {f.agent} on line {f.line_id} ({f.code}) does not "
                    "change the settlement because that line is disallowed in full, so it "
                    "was not escalated.", "TE-11.1", f.line_id, 0.0))
        return notes

    def _decide(self, board: Blackboard, approved: float, disallowed: float,
                extra_escalation: bool = False) -> str:
        if board.needs_human() or extra_escalation:
            return "ESCALATE"
        if approved <= 0.009:
            return "REJECT"
        if disallowed > 0:
            return "PARTIAL_APPROVE"
        return "APPROVE"

    # ------------------------------------------------------------------

    def build_decision(self, board: Blackboard) -> Decision:
        claimed = board.claim.claimed_total
        disallowed = board.notes.get("disallowed_total", board.disallowed_total())
        approved = board.notes.get("approved_total", round(claimed - disallowed, 2))
        outcome = board.notes.get("outcome", "ESCALATE")
        approver = board.notes.get("required_approver", C.required_approver(approved))

        ordered = sorted(
            board.findings,
            key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), -f.disallowed_amount))

        reasons = [f"[{f.clause or 'n/a'}] {f.message}"
                   for f in ordered if f.severity in {"integrity", "violation"}][:8]
        if not reasons:
            reasons = ["Every line is within entitlement, evidenced and timely."]

        return Decision(
            claim_id=board.claim.claim_id,
            employee_id=board.claim.employee_id,
            outcome=outcome,
            claimed_total=claimed,
            disallowed_total=disallowed,
            approved_total=approved,
            risk_score=T.risk_score(board.findings, claimed, disallowed),
            required_approver=approver,
            reasons=reasons,
            findings=ordered,
            trace=board.trace,
        )
