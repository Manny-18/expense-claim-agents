# Expense Claim Adjudication Crew

**Domain expert AI agents for travel and expense reimbursement**

Six specialist agents review a travel and expense claim against a fifty clause
company policy, decide what is payable, cite the clause behind every rupee they
disallow, route the claim to the right approver, and write both the message to
the employee and the audit note for the file.

![Architecture](docs/architecture.png)

```
44 labelled claims     outcome accuracy 100%, exact rupee match 100%
10 invariants          all hold, including a 300 claim fuzz run with no crash
20 unit tests          all pass
47 policy clauses      indexed and retrievable by clause id
~1 ms per claim        offline, deterministic, no API key needed
```

The 100% figure is honest arithmetic on a benchmark the author wrote, which makes it a
measure of internal consistency rather than of real world accuracy. The property based
stress test is the harder evidence, and it caught a real defect. Both are discussed in
[docs/project_report.md](docs/project_report.md).

---

## Quick start

No API key, no model, no framework. Python 3.9 or newer.

```bash
git clone https://github.com/Manny-18/expense-claim-agents.git
cd expense-claim-agents

python run_review.py --claim CLM-4015      # one claim, in full detail
python run_review.py                       # all 44 claims
python -m eval.evaluate                    # accuracy against hand written labels
python -m eval.stress_test                 # 10 invariants and a 300 claim fuzz run
python tests/test_tools.py                 # 20 unit tests
```

For the front end and the notebook:

```bash
pip install -r requirements.txt
streamlit run app/streamlit_app.py         # reviewer interface
jupyter notebook notebooks/demo.ipynb      # the full walkthrough
```

### Running it with a real model

The system works with no model because every decision that touches money is made by a
deterministic tool. A model adds free text classification and better written employee
messages, and changes no rupee amount.

```bash
cp .env.example .env            # then edit it

# a local model, nothing leaves your machine
ollama pull llama3.1:8b
LLM_PROVIDER=ollama LLM_MODEL=llama3.1:8b python run_review.py --claim CLM-4010

# or a hosted model
LLM_PROVIDER=gemini GEMINI_API_KEY=... python run_review.py
```

On an Intel MacBook the 8b model is slow but workable. `llama3.2:3b` is a better fit if
8b is sluggish; the rupee results are identical either way.

---

## The problem

Travel and expense reimbursement is high volume, low value and rule dense. A finance
associate gets roughly ninety seconds per claim and a policy of about fifty clauses.
Three things go wrong:

| Failure | What it costs |
|---|---|
| **Leakage** | Over ceiling spend is approved because nobody recomputes a grade entitlement on a Friday evening |
| **Friction** | A legitimate claim is queried because the reviewer is unsure, and the employee chases INR 2,000 for a week |
| **No audit trail** | The reason for an approval lives in the reviewer's head, so the control cannot be evidenced |

It suits a multi agent design because the work is genuinely multi disciplinary. Policy
entitlement, indirect tax treatment and integrity risk are three different specialisms
reading the same document and reaching different conclusions about it.

## The six agents

| Agent | Owns | Authority |
|---|---|---|
| **Intake** (Document and Data Steward) | Evidence sufficiency, legibility, invoice naming, TE-05 | Can disallow an unevidenced line |
| **Policy Entitlement Expert** | Grade ceilings, meals, conveyance, mileage, timelines, TE-02/03/04/07/10 | Can disallow, must cite a clause |
| **Indirect Tax Expert** | GSTIN checksum, section 17(5) blocked credit, TE-06 | Advises and quantifies credit; rarely disallows |
| **Integrity Risk Analyst** | Duplicates, splits, round amounts, leave dates, TE-09 | **Escalate only. May never reject.** |
| **Adjudicator** | Outcome and approval routing, TE-08/11 | The only agent that sets an outcome |
| **Communicator** | Employee message and audit note | Cannot change the outcome |

Each agent has a written charter that is injected into its system prompt. Narrowness is
the point: a narrow agent with the right three clauses in front of it beats one large
prompt trying to hold the whole policy at once.

## Three design decisions worth defending

**1. No agent computes a rupee value.** Arithmetic, date maths, GSTIN checksums and
threshold comparisons all live in `src/tools.py` as ordinary tested Python. The model
classifies free text and writes explanations, and nothing else. A finance control that
silently miscalculates is worse than no control, and a language model cannot be audited
the way a function with tests can.

**2. Escalation outranks rejection.** The Integrity analyst has the most alarming job and
the least power. Under TE-09.5 and TE-11.4 it may flag and escalate but never reject. A
wrong fraud call against an employee costs far more than a few hundred rupees overpaid,
and a machine should not be the thing that makes it. A suspected duplicate therefore
disallows nothing; it records the amount at risk and hands the decision to a person.

**3. The default path has no model in it.** Offline is the default, so every result in
this repository is reproducible by anyone who clones it, and the evaluation measures the
system rather than the weather inside a model.

## Repository layout

```
policy/travel_expense_policy_v3.md   the 47 clause T&E policy the system reasons over
src/
  config.py          entitlement matrices, rates, thresholds (change a limit here only)
  schemas.py         Claim, LineItem, Finding, Decision
  tools.py           the deterministic layer: every rupee is decided here
  policy_store.py    clause level chunking and TF-IDF retrieval, standard library only
  llm.py             provider router: offline, Ollama, Gemini, OpenAI compatible
  agents/            the six domain experts, one file each
  orchestrator.py    blackboard pipeline with a short circuit
  crew_runner.py     optional CrewAI wiring of the same agents and the same tools
app/streamlit_app.py reviewer front end: queue, trace, override with a reason
eval/
  ground_truth.csv   44 claims labelled by hand from the policy, before any run
  evaluate.py        accuracy, confusion matrix, leakage and friction in rupees
  stress_test.py     10 invariants plus a 300 claim fuzz run
tests/test_tools.py  20 unit tests on the arithmetic
notebooks/demo.ipynb the full walkthrough with outputs saved
docs/project_report.md  the written submission
```

## How it is evaluated

Two things are measured, because a system can be right about the outcome and wrong about
the money.

- **Outcome accuracy** against 44 hand labelled claims, with a confusion matrix and per
  class precision and recall.
- **Rupee accuracy**, split into the two errors that cost different things: *leakage*
  (approving what should have been stopped, the company loses money) and *friction*
  (stopping what should have been approved, the employee loses trust).

The labels were written from the policy text before the system was run. One label was
found to be wrong during the first evaluation and corrected, which is recorded in the
dataset and in the report rather than quietly fixed.

The stress test asserts invariants that must hold for any input: determinism,
monotonicity, exact boundary behaviour, conservation of value, no auto rejection on an
integrity flag, vendor name normalisation, and a citation behind every disallowed rupee.
It found a genuine defect on its first run, where vendor names were compared with a bare
lowercase strip so that `uber  india` and `Uber India` were treated as different
merchants and a duplicate slipped through. The label based benchmark would never have
caught it.

## What this does not do

The receipts here are structured records, not photographs, so a production system needs
document understanding with its own error rate that would dominate everything measured
here. The benchmark is synthetic and self authored. The integrity checks are rule shaped
and catch only the patterns they were told about. The policy is fictional, and a real
deployment starts with a policy that contradicts itself. These are expanded in the
report, where they belong.

---

Built for the Agentic AI individual assignment, PGDM (BDA) 2025-27, FORE School of
Management. Author: Aman Aggarwal, Roll No. 065064.
