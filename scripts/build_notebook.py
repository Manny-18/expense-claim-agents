"""Author notebooks/demo.ipynb programmatically so it stays in sync with the code."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "demo.ipynb"

md = lambda s: nbf.v4.new_markdown_cell(s.strip())      # noqa: E731
code = lambda s: nbf.v4.new_code_cell(s.strip())        # noqa: E731

cells = [
    md("""
# Expense Claim Adjudication Crew
### Domain expert AI agents for travel and expense review

This notebook walks through the system end to end: the problem, the agent design, a
single claim reviewed in full, the evaluation against hand written labels, and the
honest limitations.

**Run order:** top to bottom. Nothing here needs an API key. The default engine is the
deterministic rule layer, so every number below is reproducible.
"""),

    md("""
## 1. Setup

The only requirement for this notebook is pandas. The agent system itself uses the
standard library only.
"""),
    code("""
import sys, json
from pathlib import Path
import pandas as pd

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT))

from src.orchestrator import ExpenseReviewCrew, load_claims, load_employees, load_history
from src.policy_store import get_policy_store
from src import tools as T

pd.set_option("display.width", 160)
pd.set_option("display.max_colwidth", 70)
print("project root:", ROOT)
"""),

    md("""
## 2. The business process

Travel and expense reimbursement is a high volume, low value, rule dense process. A
mid size consulting firm processes a few thousand claims a month. Each one is checked
against a policy document of roughly fifty clauses by a finance associate who has
about ninety seconds to spend on it.

Three things go wrong in practice:

1. **Leakage.** Over ceiling spend is approved because nobody recomputes a grade
   entitlement at 6pm on a Friday.
2. **Friction.** Legitimate claims are queried because a reviewer is unsure, and the
   employee spends a week chasing a reimbursement of two thousand rupees.
3. **No audit trail.** The reason a claim was approved exists only in the reviewer's
   head, so the control cannot be evidenced to an auditor.

This is a good fit for agents because the work is genuinely multi disciplinary. Policy
entitlement, indirect tax treatment and fraud risk are three different specialisms
that happen to look at the same document.
"""),

    md("""
## 3. The policy, as a retrievable corpus

The policy is chunked by clause identifier rather than by token window, because a
clause is the natural unit of a finance rule and because every disallowance has to
cite one.
"""),
    code("""
policy = get_policy_store()
print(f"{len(policy)} clauses indexed")

for clause, score in policy.search("can I claim wine on a client dinner bill", k=3):
    print(f"\\n[{clause.clause_id}] {clause.section_title}  (similarity {score:.3f})")
    print("   ", clause.text[:200])
"""),

    md("""
## 4. The six agents

Each agent has a narrow charter. The charter is not decoration: it is injected into the
system prompt, and narrowness is the reason a small agent beats one large prompt that
tries to hold the whole policy at once.

Note the authority column. The Integrity analyst has the most alarming job and the
least power, by design.
"""),
    code("""
crew = ExpenseReviewCrew(load_employees(), load_history())
print(crew.describe())

authority = pd.DataFrame([
    ["IntakeAgent",        "Evidence sufficiency, TE-05",        "can disallow an unevidenced line"],
    ["PolicyExpertAgent",  "Entitlements, ceilings, timelines",  "can disallow with a clause"],
    ["TaxComplianceAgent", "GSTIN validity, input tax credit",   "advises, rarely disallows"],
    ["FraudRiskAgent",     "Duplicates and integrity, TE-09",    "can escalate only, never reject"],
    ["AdjudicatorAgent",   "Outcome and approval routing",       "the only agent that sets an outcome"],
    ["CommunicatorAgent",  "Employee message and audit note",    "cannot change the outcome"],
], columns=["agent", "owns", "authority"])
authority
"""),

    md("""
## 5. The central design decision

**An agent never computes a rupee value.**

Arithmetic, date maths, checksum validation and threshold comparison all happen in
ordinary Python in `src/tools.py`, which is unit tested. The language model is used
for two things only: classifying free text whose meaning is genuinely ambiguous, and
writing the explanation.

A finance control that silently miscalculates is worse than no control, and a language
model cannot be audited the way a function with tests can.
"""),
    code("""
# the tool layer is directly testable, which the agent layer is not
print("GSTIN checksum, valid:  ", T.validate_gstin("06AAJCM4321L1ZE"))
print("GSTIN checksum, tampered:", T.validate_gstin("06AAJCM4321L1ZK"))
print()
print("vendor normalisation:",
      T.normalize_vendor("Uber India Pvt. Ltd.") == T.normalize_vendor("  UBER-india "))
"""),

    md("""
## 6. One claim, reviewed in full

CLM-4015 is deliberately messy: a meal over the daily ceiling, and a cab line that
duplicates a line from an earlier claim.
"""),
    code("""
claims = {c.claim_id: c for c in load_claims()}
claim = claims["CLM-4015"]
pd.DataFrame([l.to_dict() for l in claim.lines])[
    ["line_id", "category", "vendor", "expense_date", "city", "amount", "tax_amount"]]
"""),
    code("""
d = crew.review(claim)

print(f"outcome      {d.outcome}")
print(f"claimed      INR {d.claimed_total:>10,.2f}")
print(f"disallowed   INR {d.disallowed_total:>10,.2f}")
print(f"payable      INR {d.approved_total:>10,.2f}")
print(f"risk         {d.risk_score}/100")
print(f"approver     {d.required_approver}")
"""),

    md("""
### What each agent said

Notice that the duplicate finding disallows nothing. TE-09.1 defines a *suspected*
duplicate, and TE-11.4 forbids an automatic rejection on an integrity signal, so the
system records the amount at risk and hands the money decision to a person.
"""),
    code("""
pd.DataFrame([{
    "agent": f.agent, "severity": f.severity, "clause": f.clause,
    "line": f.line_id, "disallows": f.disallowed_amount, "message": f.message,
} for f in d.findings])
"""),
    code("""
pd.DataFrame([t.to_dict() for t in d.trace])
"""),

    md("""
### The two artefacts that leave the system

Most expense automation stops at a decision. The expensive part is what the employee
reads next, so the Communicator writes both the employee message and the audit note
from the same decision object. Note that the employee is never told a line is
"suspicious"; an integrity flag is phrased as a query.
"""),
    code("""
print(d.employee_message)
print("\\n" + "=" * 78 + "\\n")
print(d.audit_note)
"""),

    md("""
## 7. Evaluation

Forty four claims, each labelled by hand from the policy text **before** the system was
run. Labels produced by the system under test would measure nothing.

Two error classes are separated because they cost different things:

* **Leakage**: approving what should have been stopped. The company loses money.
* **Friction**: stopping what should have been approved. The employee loses trust.
"""),
    code("""
import subprocess
out = subprocess.run([sys.executable, "-m", "eval.evaluate"], cwd=ROOT,
                     capture_output=True, text=True)
print(out.stdout[-2600:])
"""),
    code("""
rep = json.loads((ROOT / "eval" / "results.json").read_text())
pd.DataFrame(rep["confusion"]).T
"""),

    md("""
## 8. The stress test matters more than the score

A perfect score on a benchmark written by the same person who wrote the rules measures
internal consistency, not accuracy. The property based stress test is the harder
check: it asserts invariants that must hold for *any* input, and it fuzzes three
hundred perturbed claims looking for a crash or an impossible total.

It found a real defect on its first run. Vendor names were compared with a bare
lowercase strip, so "uber  india" and "Uber India" were different merchants and a
duplicate slipped through. That is exactly the kind of gap a control is supposed to
close, and the label based benchmark never would have caught it.
"""),
    code("""
out = subprocess.run([sys.executable, "-m", "eval.stress_test"], cwd=ROOT,
                     capture_output=True, text=True)
print(out.stdout[-1800:])
"""),

    md("""
## 9. Portfolio view

The same decisions aggregated the way a finance controller would want to see them.
"""),
    code("""
decisions = crew.review_many(load_claims())
df = pd.DataFrame([{
    "claim": d.claim_id, "employee": d.employee_id, "outcome": d.outcome,
    "claimed": d.claimed_total, "disallowed": d.disallowed_total,
    "payable": d.approved_total, "risk": d.risk_score,
} for d in decisions])

summary = df.groupby("outcome").agg(
    claims=("claim", "count"), claimed=("claimed", "sum"),
    disallowed=("disallowed", "sum"), payable=("payable", "sum")).round(0)
display(summary)

total = df["claimed"].sum()
stp = df["outcome"].isin(["APPROVE", "PARTIAL_APPROVE"]).mean()
print(f"\\ntotal claimed      INR {total:,.0f}")
print(f"total disallowed   INR {df['disallowed'].sum():,.0f} "
      f"({df['disallowed'].sum() / total:.1%} of value)")
print(f"straight through   {stp:.0%} of claims settled with no human")
"""),
    code("""
ax = df.groupby("outcome")["claim"].count().plot(
    kind="barh", title="Outcome distribution across 44 claims", figsize=(7, 3))
ax.set_xlabel("claims")
ax.set_ylabel("")
"""),

    md("""
## 10. What this does not do

Stated plainly, because a project that claims no limitations has not been looked at
hard enough.

1. **The receipts are structured data, not images.** A production system needs OCR and
   document understanding on the actual PDF or photograph. Every field this system
   reads would, in reality, be an extraction with its own error rate, and that error
   rate would dominate everything measured here.
2. **The benchmark is synthetic and self authored.** Forty four claims written by the
   person who wrote the rules. Real claims are messier in ways that are hard to
   imagine in advance.
3. **The fraud detection is rule shaped.** It catches the patterns it was told about.
   A genuine fraud detection capability needs labelled historical outcomes and a model
   trained on them, which no student project has access to.
4. **The policy is fictional**, written for this project. A real deployment starts with
   a policy that contradicts itself in three places, which is a discovery problem
   before it is an engineering problem.
5. **Language model variance is unmeasured in the default path.** The offline engine is
   deterministic by design. Running with a live model would introduce variance in the
   free text classification, and that variance should be measured over repeated runs
   before anyone trusts it.

The honest summary: the rule engine is production shaped, the agent layer is a
credible design, and the evaluation proves consistency rather than real world accuracy.
"""),
]

nb = nbf.v4.new_notebook(cells=cells)
nb.metadata = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.11"},
}
OUT.parent.mkdir(exist_ok=True)
nbf.write(nb, OUT)
print(f"written {OUT} with {len(cells)} cells")
