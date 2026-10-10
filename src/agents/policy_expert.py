"""Agent 2: Policy Entitlement Expert.

Owns sections TE-02, TE-03, TE-04, TE-07 and TE-10: grade entitlements, meal
and hotel ceilings, conveyance rules, timeliness and the non reimbursable
list.

This agent also demonstrates the retrieval half of the system. For any line
whose description is free text that the keyword screen cannot settle, it
pulls the closest policy clauses out of the TF-IDF index and asks the model
to classify the line against those clauses only. The model is never asked
"is this allowed?" in the abstract; it is asked "does this text fall under
one of these three clauses?", which is a classification task a small local
model can actually do.
"""

from __future__ import annotations

from typing import List

from .. import tools as T
from ..schemas import Finding, LineItem
from .base import Blackboard, DomainAgent

AMBIGUOUS_CATEGORIES = {"misc", "entertainment"}


class PolicyExpertAgent(DomainAgent):
    name = "PolicyExpertAgent"
    role = "Policy Entitlement Expert"
    charter = (
        "Apply the grade entitlement matrix, the daily ceilings, the conveyance and "
        "mileage rules, the submission timelines and the non reimbursable list. Every "
        "disallowance you raise must cite a clause. You do not assess tax treatment and "
        "you do not assess intent or fraud."
    )

    def run(self, board: Blackboard) -> List[Finding]:
        claim, employee = board.claim, board.employee
        findings: List[Finding] = []

        # deterministic checks, line by line
        for line in claim.lines:
            findings.extend(T.check_hotel_ceiling(line, employee))
            findings.extend(T.check_alcohol(line))
            findings.extend(T.check_non_reimbursable_text(line))
            findings.extend(T.check_entertainment(line))
            findings.extend(T.check_team_meal(line))
            findings.extend(T.check_travel_class(line, employee))
            findings.extend(T.check_mileage(line))
            findings.extend(T.check_cab_rules(line))
            findings.extend(T.check_laundry(claim, line))

        # claim level checks
        findings.extend(T.check_meal_ceilings(claim, employee))
        findings.extend(T.check_fuel_with_mileage(claim))
        findings.extend(T.check_timeliness(claim))

        # retrieval assisted classification of free text lines
        already_flagged = {f.line_id for f in findings if f.severity == "violation"}
        for line in claim.lines:
            if line.category in AMBIGUOUS_CATEGORIES and line.line_id not in already_flagged:
                verdict = self._classify_ambiguous(line)
                if verdict:
                    findings.append(verdict)

        return findings

    # ------------------------------------------------------------------

    def _classify_ambiguous(self, line: LineItem) -> Finding | None:
        """Classify a free text line against retrieved clauses."""
        query = f"{line.category} {line.vendor} {line.description}"
        context = self.policy.context_for(query, k=4)

        if not self.llm.available:
            # Offline behaviour: never silently allow an unexplained line of
            # material value. Flag it for a human rather than guessing.
            if line.amount >= 2000 and not line.description.strip():
                return Finding(self.name, "AMB_NO_DESCRIPTION", "advisory",
                               f"Line {line.line_id} of INR {line.amount:,.0f} has no description, "
                               "so its business purpose cannot be established.",
                               "TE-01.2", line.line_id, 0.0, {"needs_human": True})
            return None

        prompt = (
            f"Policy clauses retrieved for this line:\n{context}\n\n"
            f"Expense line:\n"
            f"- category: {line.category}\n"
            f"- vendor: {line.vendor}\n"
            f"- description: {line.description or '(none)'}\n"
            f"- amount: INR {line.amount:,.0f}\n"
            f"- engagement code: {line.engagement_code or '(none)'}\n\n"
            "Decide whether this line is clearly reimbursable, clearly not reimbursable, "
            "or ambiguous. Return JSON with keys: verdict (one of allowed, not_allowed, "
            "ambiguous), clause (a TE identifier from the list above), reason (one sentence)."
        )
        result = self.llm.complete_json(
            self.system_prompt(), prompt,
            fallback={"verdict": "ambiguous", "clause": "TE-01.2",
                      "reason": "The model was unavailable, so a human should review."})

        verdict = str(result.get("verdict", "ambiguous")).lower()
        clause = str(result.get("clause", "TE-01.2"))
        reason = str(result.get("reason", "")).strip()[:300]

        if verdict == "not_allowed":
            return Finding(self.name, "AMB_NOT_ALLOWED", "violation",
                           f"Classified as not reimbursable: {reason}",
                           clause, line.line_id, line.amount, {"llm_classified": True})
        if verdict == "ambiguous":
            return Finding(self.name, "AMB_UNCLEAR", "advisory",
                           f"Business purpose is unclear: {reason}",
                           clause, line.line_id, 0.0,
                           {"needs_human": True, "llm_classified": True})
        return None
