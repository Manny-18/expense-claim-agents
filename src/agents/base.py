"""The agent contract.

A domain expert agent in this system has four properties:

1. a **narrow charter**: it answers one kind of question and refuses the rest
2. **tools it must use** for anything numeric, rather than reasoning in text
3. an **escalation right**: it can say "a human must look at this" and no
   other agent can overrule that
4. a **citation duty**: every violation it raises names a policy clause

The charter is not decoration. It is injected into the system prompt and it is
the reason a narrow agent outperforms one large prompt that tries to hold the
entire policy at once.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from ..llm import LLMClient, get_llm
from ..policy_store import PolicyStore, get_policy_store
from ..schemas import Claim, Employee, Finding, TraceStep


class Blackboard:
    """Shared working memory passed down the agent chain.

    Agents never call each other. They read and write this object, which keeps
    the pipeline observable: at any point you can print the blackboard and see
    exactly what the system believes and who said it.
    """

    def __init__(self, claim: Claim, employee: Employee, history: List[Dict[str, Any]]):
        self.claim = claim
        self.employee = employee
        self.history = history
        self.findings: List[Finding] = []
        self.trace: List[TraceStep] = []
        self.notes: Dict[str, Any] = {}

    def add(self, findings: List[Finding]) -> None:
        self.findings.extend(findings)

    def by_agent(self, agent: str) -> List[Finding]:
        return [f for f in self.findings if f.agent == agent]

    def disallowed_total(self) -> float:
        """Sum disallowances without double counting a line.

        Where two agents disallow part of the same line, the larger stands;
        a line can never be disallowed for more than its own value.
        """
        per_line: Dict[str, float] = {}
        for f in self.findings:
            if f.disallowed_amount > 0 and f.line_id:
                per_line[f.line_id] = max(per_line.get(f.line_id, 0.0), f.disallowed_amount)
        capped = 0.0
        for line in self.claim.lines:
            capped += min(per_line.get(line.line_id, 0.0), line.amount)
        return round(capped, 2)

    def needs_human(self) -> bool:
        return any(f.severity == "integrity" or f.evidence.get("needs_human")
                   for f in self.findings)


class DomainAgent(ABC):
    name: str = "Agent"
    role: str = ""
    charter: str = ""

    def __init__(self, llm: LLMClient | None = None, policy: PolicyStore | None = None):
        self.llm = llm or get_llm()
        self.policy = policy or get_policy_store()

    @abstractmethod
    def run(self, board: Blackboard) -> List[Finding]:
        """Inspect the blackboard and return this agent's findings."""

    def execute(self, board: Blackboard) -> List[Finding]:
        """Run with timing and trace capture."""
        start = time.perf_counter()
        before_calls = self.llm.call_count
        findings = self.run(board)
        board.add(findings)
        duration = int((time.perf_counter() - start) * 1000)
        board.trace.append(TraceStep(
            agent=self.name,
            role=self.role,
            input_summary=self.input_summary(board),
            output_summary=self.output_summary(findings),
            findings_count=len(findings),
            duration_ms=duration,
            used_llm=self.llm.call_count > before_calls and self.llm.available,
        ))
        return findings

    # -- helpers -----------------------------------------------------------

    def input_summary(self, board: Blackboard) -> str:
        return (f"claim {board.claim.claim_id}, {len(board.claim.lines)} line(s), "
                f"INR {board.claim.claimed_total:,.0f}")

    def output_summary(self, findings: List[Finding]) -> str:
        if not findings:
            return "no issues raised"
        buckets: Dict[str, int] = {}
        for f in findings:
            buckets[f.severity] = buckets.get(f.severity, 0) + 1
        return ", ".join(f"{v} {k}" for k, v in buckets.items())

    def system_prompt(self) -> str:
        return (
            f"You are the {self.name}, a domain expert inside an expense review system "
            f"at a consulting firm.\n"
            f"Role: {self.role}\n"
            f"Charter: {self.charter}\n"
            "Rules you must obey:\n"
            "1. Never invent or recompute a rupee amount. Amounts given to you are already "
            "verified by a deterministic rule engine.\n"
            "2. Cite a policy clause identifier for any statement about what is allowed.\n"
            "3. If the evidence is ambiguous, say so and recommend escalation. Do not guess.\n"
            "4. Stay inside your charter. Another agent owns the rest.\n"
            "5. Write in plain professional English with no em dashes."
        )
