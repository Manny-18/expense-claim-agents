"""Agent 6: Employee Communication Specialist.

Owns the last mile that most automation projects skip. A correct decision
delivered badly still produces a ticket to the finance helpdesk, and the
helpdesk cost is often larger than the amount in dispute.

This agent writes two artefacts from the same decision:

* an **employee message**, plain, specific about what to do next, and never
  accusatory even when the finding is an integrity flag
* an **audit note**, terse and clause referenced, written for the approver
  and for the file

The language model is used here and nowhere else in a way that touches the
employee directly, so the prompt forbids it from restating amounts other than
those passed to it, and a full template fallback exists for offline runs.
"""

from __future__ import annotations

from typing import List

from .. import config as C
from ..schemas import Decision, Finding
from .base import Blackboard, DomainAgent

OUTCOME_OPENING = {
    "APPROVE": "Your claim has been approved in full.",
    "PARTIAL_APPROVE": "Your claim has been approved in part.",
    "REJECT": "Your claim could not be reimbursed.",
    "ESCALATE": "Your claim needs a human reviewer before it can be settled.",
}


class CommunicatorAgent(DomainAgent):
    name = "CommunicatorAgent"
    role = "Employee Communication Specialist"
    charter = (
        "Turn a settled decision into a clear message for the employee and a terse "
        "audit note for the approver. You never change the outcome, never restate an "
        "amount that was not given to you, and never imply dishonesty. An integrity "
        "flag is described to the employee as a query, not an accusation."
    )

    def run(self, board: Blackboard) -> List[Finding]:
        return []  # this agent produces text, not findings

    def write(self, board: Blackboard, decision: Decision) -> None:
        decision.employee_message = self._employee_message(decision)
        decision.audit_note = self._audit_note(decision)

    # ------------------------------------------------------------------

    def _employee_message(self, d: Decision) -> str:
        template = self._template_message(d)
        if not self.llm.available:
            return template

        bullets = "\n".join(f"- [{f.clause}] {f.message}" for f in d.findings
                            if f.severity in {"violation", "integrity"})[:2500]
        prompt = (
            f"Outcome: {d.outcome}\n"
            f"Claimed: INR {d.claimed_total:,.0f}\n"
            f"Disallowed: INR {d.disallowed_total:,.0f}\n"
            f"Payable: INR {d.approved_total:,.0f}\n"
            f"Approver: {d.required_approver}\n"
            f"Findings:\n{bullets or '- none'}\n\n"
            "Write a short email to the employee, six sentences at most. State the outcome, "
            "the payable amount, the specific reason for any disallowance with its clause, and "
            "exactly what the employee should do next. Do not use the words fraud, suspicious "
            "or violation when writing to the employee. Do not use em dashes."
        )
        res = self.llm.complete(self.system_prompt(), prompt, temperature=0.3, max_tokens=400)
        text = (res.text or "").strip()
        return text if len(text) > 80 else template

    def _template_message(self, d: Decision) -> str:
        lines = [OUTCOME_OPENING.get(d.outcome, ""), ""]
        lines.append(f"Claim {d.claim_id}")
        lines.append(f"Submitted value: INR {d.claimed_total:,.2f}")

        if d.outcome in {"APPROVE", "PARTIAL_APPROVE"}:
            lines.append(f"Payable to you: INR {d.approved_total:,.2f}")
        if d.disallowed_total > 0:
            lines.append(f"Not reimbursable: INR {d.disallowed_total:,.2f}")

        reasoned = [f for f in d.findings if f.severity in {"violation", "integrity"}]
        if reasoned:
            lines.append("")
            lines.append("Why:")
            for f in reasoned[:6]:
                prefix = "Query" if f.severity == "integrity" else "Adjustment"
                lines.append(f"  {prefix} [{f.clause}]: {f.message}")

        lines.append("")
        if d.outcome == "ESCALATE":
            lines.append(f"Next step: {d.required_approver} will review the points above. "
                         "You may be asked for a short explanation or a clearer copy of a "
                         "receipt. No action is needed from you until then.")
        elif d.outcome == "REJECT":
            lines.append("Next step: if you believe this is incorrect, reply to this message "
                         "with the supporting document and it will be reopened.")
        else:
            lines.append(f"Next step: payment will be released after sign off by "
                         f"{d.required_approver}, normally in the next payment run.")

        lines.append("")
        lines.append(f"Reviewed against policy {C.POLICY_VERSION}.")
        return "\n".join(lines)

    def _audit_note(self, d: Decision) -> str:
        parts = [
            f"CLAIM {d.claim_id} | EMP {d.employee_id} | {d.outcome} | risk {d.risk_score}/100",
            f"Claimed {d.claimed_total:,.2f} | Disallowed {d.disallowed_total:,.2f} | "
            f"Payable {d.approved_total:,.2f} | Authority: {d.required_approver}",
        ]
        for f in d.findings:
            if f.severity in {"integrity", "violation"}:
                tag = f.line_id or "claim"
                parts.append(f"  {f.severity.upper():9} {f.clause:9} {tag:8} {f.code}: "
                             f"{f.message}")
        parts.append(f"Decided {d.decided_at} by the agent pipeline, policy {C.POLICY_VERSION}.")
        return "\n".join(parts)
