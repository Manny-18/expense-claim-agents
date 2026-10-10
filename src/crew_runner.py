"""Optional CrewAI wiring of the same agents and the same tools.

Why this file exists, and why it is not the main path.

The native orchestrator in orchestrator.py is the tested implementation. It
has no framework dependency, it runs offline, it is deterministic, and every
decision it makes is reproducible, which is what an audited finance control
needs. This file shows the identical agent design expressed in CrewAI, so the
two can be compared directly, and so the project can be run inside the
framework used in class.

What changes when you switch:

    native orchestrator          CrewAI
    -------------------------    ------------------------------------------
    deterministic                model dependent, varies between runs
    runs with no model           needs a running model for every agent
    about 1 ms per claim         seconds per claim
    tools called directly        tools called through the model's tool use
    full trace by construction   trace depends on the framework's verbosity

The tools are the same objects in both paths, so the rupee arithmetic cannot
drift between them. That is the point of keeping the tool layer independent
of any framework.

Requires:  pip install crewai crewai-tools
Run:       python -m src.crew_runner CLM-2001
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict

from . import tools as T
from .orchestrator import load_claims, load_employees, load_history
from .policy_store import get_policy_store
from .schemas import Claim, Employee

CREWAI_MISSING = (
    "CrewAI is not installed. This file is the optional framework path.\n"
    "Install it with:  pip install crewai crewai-tools\n"
    "The tested path needs nothing extra:  python run_review.py"
)


def _require_crewai():
    try:
        from crewai import Agent, Crew, Process, Task  # noqa: F401
        from crewai.tools import tool  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(CREWAI_MISSING) from exc
    from crewai import Agent, Crew, Process, Task
    from crewai.tools import tool
    return Agent, Crew, Process, Task, tool


def build_crew(claim: Claim, employee: Employee, history):
    """Build a CrewAI crew whose tools are this project's tool layer."""
    Agent, Crew, Process, Task, tool = _require_crewai()
    policy = get_policy_store()

    # --- tools, thin wrappers so the model gets JSON it can reason over ----

    @tool("lookup_policy")
    def lookup_policy(question: str) -> str:
        """Retrieve the policy clauses most relevant to a question. Always cite the
        TE identifier returned here rather than relying on memory."""
        return policy.context_for(question, k=4)

    @tool("check_entitlement_limits")
    def check_entitlement_limits(_: str = "") -> str:
        """Run every deterministic entitlement and ceiling check on the claim and
        return the findings as JSON. Never compute a limit yourself."""
        out = []
        for line in claim.lines:
            out += T.check_hotel_ceiling(line, employee)
            out += T.check_alcohol(line)
            out += T.check_non_reimbursable_text(line)
            out += T.check_entertainment(line)
            out += T.check_team_meal(line)
            out += T.check_travel_class(line, employee)
            out += T.check_mileage(line)
            out += T.check_cab_rules(line)
            out += T.check_laundry(claim, line)
        out += T.check_meal_ceilings(claim, employee)
        out += T.check_fuel_with_mileage(claim)
        out += T.check_timeliness(claim)
        return json.dumps([f.to_dict() for f in out], default=str)

    @tool("check_evidence_and_tax")
    def check_evidence_and_tax(_: str = "") -> str:
        """Run the evidence sufficiency checks and the GST and input tax credit checks.
        Returns JSON findings."""
        out = []
        for line in claim.lines:
            out += T.check_evidence(line, employee)
            out += T.check_gst(line)
        return json.dumps([f.to_dict() for f in out], default=str)

    @tool("check_integrity")
    def check_integrity(_: str = "") -> str:
        """Run duplicate, split, round amount and leave date detection. Returns JSON
        findings. These findings may never cause an automatic rejection."""
        out = (T.detect_duplicates_within_claim(claim)
               + T.detect_duplicates_against_history(claim, history)
               + T.detect_splits(claim)
               + T.detect_round_amounts(claim)
               + T.detect_leave_date_expenses(claim, employee))
        return json.dumps([f.to_dict() for f in out], default=str)

    @tool("describe_claim")
    def describe_claim(_: str = "") -> str:
        """Return the claim and the employee record as JSON."""
        return json.dumps({"claim": claim.to_dict(), "employee": employee.to_dict()},
                          default=str)

    common = dict(verbose=True, allow_delegation=False)

    intake = Agent(
        role="Document and Data Steward",
        goal="Establish whether each claim line carries sufficient evidence under TE-05.",
        backstory="You have processed expense documentation for a decade and you can tell "
                  "a compliant tax invoice from a payment slip at a glance.",
        tools=[describe_claim, check_evidence_and_tax, lookup_policy], **common)

    policy_expert = Agent(
        role="Policy Entitlement Expert",
        goal="Apply grade entitlements, ceilings, conveyance rules and timelines, citing "
             "a clause for every disallowance.",
        backstory="You wrote half of the current travel policy and you know which clause "
                  "governs which situation without guessing.",
        tools=[check_entitlement_limits, lookup_policy], **common)

    fraud = Agent(
        role="Integrity and Duplicate Risk Analyst",
        goal="Surface duplicates and integrity signals, and escalate them. You never "
             "conclude that a person was dishonest and you never reject a claim.",
        backstory="You run the continuous controls monitoring programme and you have seen "
                  "enough false positives to be careful with an accusation.",
        tools=[check_integrity, describe_claim], **common)

    adjudicator = Agent(
        role="Claim Adjudicator",
        goal="Combine the findings into one outcome of APPROVE, PARTIAL APPROVE, REJECT or "
             "ESCALATE, and route it to the right approver under TE-08.",
        backstory="You are the finance controller's delegate. Escalation beats rejection "
                  "whenever the evidence is ambiguous.",
        tools=[lookup_policy], **common)

    t1 = Task(description=f"Review the evidence on claim {claim.claim_id}.",
              expected_output="A list of evidence findings with clause references.",
              agent=intake)
    t2 = Task(description="Apply every entitlement, ceiling, conveyance and timeline rule.",
              expected_output="A list of policy findings, each with a clause and a rupee "
                              "disallowance where one applies.",
              agent=policy_expert, context=[t1])
    t3 = Task(description="Check the claim for duplicates and integrity signals.",
              expected_output="A list of integrity findings, each marked for human review.",
              agent=fraud, context=[t1])
    t4 = Task(description=(
                  "Decide the outcome. Rules of precedence: any integrity finding or any "
                  "request for human review forces ESCALATE; an uncited disallowance is "
                  "invalid; if nothing is payable the outcome is REJECT; if something was "
                  "disallowed but a balance remains the outcome is PARTIAL APPROVE; "
                  "otherwise APPROVE."),
              expected_output="JSON with keys outcome, approved_total, disallowed_total, "
                              "required_approver and reasons.",
              agent=adjudicator, context=[t1, t2, t3])

    return Crew(agents=[intake, policy_expert, fraud, adjudicator],
                tasks=[t1, t2, t3, t4], process=Process.sequential, verbose=True)


def main() -> None:  # pragma: no cover
    claim_id = sys.argv[1] if len(sys.argv) > 1 else "CLM-2001"
    claims = {c.claim_id: c for c in load_claims()}
    if claim_id not in claims:
        raise SystemExit(f"Unknown claim {claim_id}")
    claim = claims[claim_id]
    employee = load_employees()[claim.employee_id]
    crew = build_crew(claim, employee, load_history())
    print(crew.kickoff())


if __name__ == "__main__":  # pragma: no cover
    main()
