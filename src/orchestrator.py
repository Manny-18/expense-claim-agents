"""The orchestrator: a blackboard pipeline with a short circuit.

Topology is sequential with one conditional branch, which is the right shape
for an adjudication problem:

    IntakeAgent
        |
        +-- if evidence is fatally missing on every line, short circuit
        |
    PolicyExpertAgent  ---+
    TaxComplianceAgent ---+--> all read and write the same blackboard
    FraudRiskAgent     ---+
        |
    AdjudicatorAgent   (arbitration, the only agent that sets an outcome)
        |
    CommunicatorAgent  (writes to the employee and to the file)

A debate or negotiation topology was considered and rejected. Expense
adjudication has a deterministic ground truth: a limit is either breached or
it is not. Agents arguing about it adds cost and variance and removes the
audit trail, which is the one thing a finance control cannot lose.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import config as C
from .agents import (AdjudicatorAgent, Blackboard, CommunicatorAgent, FraudRiskAgent,
                     IntakeAgent, PolicyExpertAgent, TaxComplianceAgent)
from .llm import LLMClient, get_llm
from .policy_store import get_policy_store
from .schemas import Claim, Decision, Employee


class ExpenseReviewCrew:
    """Build once, review many claims."""

    def __init__(self, employees: Dict[str, Employee],
                 history: Optional[List[Dict[str, Any]]] = None,
                 llm: Optional[LLMClient] = None):
        self.employees = employees
        self.history = history or []
        self.llm = llm or get_llm()
        self.policy = get_policy_store()

        kwargs = {"llm": self.llm, "policy": self.policy}
        self.intake = IntakeAgent(**kwargs)
        self.experts = [
            PolicyExpertAgent(**kwargs),
            TaxComplianceAgent(**kwargs),
            FraudRiskAgent(**kwargs),
        ]
        self.adjudicator = AdjudicatorAgent(**kwargs)
        self.communicator = CommunicatorAgent(**kwargs)

    # ------------------------------------------------------------------

    def review(self, claim: Claim) -> Decision:
        employee = self.employees.get(claim.employee_id)
        if employee is None:
            raise KeyError(f"Unknown employee {claim.employee_id}")

        board = Blackboard(claim, employee, self.history)

        self.intake.execute(board)

        if self._totally_unevidenced(board):
            # Short circuit: nothing downstream can add value, and running the
            # fraud agent on a claim with no evidence would only generate noise.
            board.notes["short_circuit"] = True
        else:
            for agent in self.experts:
                agent.execute(board)

        self.adjudicator.execute(board)
        decision = self.adjudicator.build_decision(board)
        self.communicator.write(board, decision)
        return decision

    def review_many(self, claims: Iterable[Claim]) -> List[Decision]:
        return [self.review(c) for c in claims]

    # ------------------------------------------------------------------

    def _totally_unevidenced(self, board: Blackboard) -> bool:
        fatal = {"EV_NO_RECEIPT", "EV_ILLEGIBLE", "EV_MRD_OVER_CAP", "EV_MRD_QUOTA"}
        bad_lines = {f.line_id for f in board.findings if f.code in fatal}
        return len(board.claim.lines) > 0 and len(bad_lines) == len(board.claim.lines)

    def describe(self) -> str:
        agents = [self.intake] + self.experts + [self.adjudicator, self.communicator]
        rows = [f"  {a.name:22} {a.role}" for a in agents]
        return (f"ExpenseReviewCrew\n  model: {self.llm.describe()}\n"
                f"  policy clauses indexed: {len(self.policy)}\n" + "\n".join(rows))


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def load_employees(path: Path | str = C.DATA_DIR / "employees.json") -> Dict[str, Employee]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return {r["employee_id"]: Employee(**r) for r in rows}


def load_claims(path: Path | str = C.DATA_DIR / "claims.json") -> List[Claim]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Claim.from_dict(r) for r in rows]


def load_history(path: Path | str = C.DATA_DIR / "claim_history.json") -> List[Dict[str, Any]]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def build_default_crew(llm: Optional[LLMClient] = None) -> "ExpenseReviewCrew":
    return ExpenseReviewCrew(load_employees(), load_history(), llm)
