"""Command line entry point.

    python run_review.py                      review every claim in data/
    python run_review.py --claim CLM-4001     review one claim in full detail
    python run_review.py --json out.json      write every decision to a file
    python run_review.py --provider ollama --model llama3.1:8b
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.llm import LLMClient, set_llm  # noqa: E402
from src.orchestrator import (ExpenseReviewCrew, load_claims, load_employees,  # noqa: E402
                              load_history)

BAR = "=" * 78


def show(decision, claim, verbose: bool) -> None:
    print(BAR)
    print(f"{claim.claim_id}  {decision.outcome}   risk {decision.risk_score}/100")
    print(f"  claimed INR {decision.claimed_total:>12,.2f}")
    print(f"  disallowed INR {decision.disallowed_total:>9,.2f}")
    print(f"  payable INR {decision.approved_total:>12,.2f}")
    print(f"  approver: {decision.required_approver}")
    if decision.reasons:
        print("  reasons:")
        for r in decision.reasons:
            print(f"    - {r}")
    if verbose:
        print("\n  agent trace")
        for t in decision.trace:
            flag = "model" if t.used_llm else "rules"
            print(f"    {t.agent:22} {t.findings_count:>2} finding(s)  "
                  f"{t.duration_ms:>4} ms  [{flag}]  {t.output_summary}")
        print("\n  message to the employee")
        for line in decision.employee_message.splitlines():
            print(f"    {line}")
        print("\n  audit note")
        for line in decision.audit_note.splitlines():
            print(f"    {line}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Review expense claims with the agent crew")
    ap.add_argument("--claim", help="review a single claim id")
    ap.add_argument("--provider", default=None,
                    choices=["offline", "ollama", "gemini", "openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--json", dest="json_out", help="write all decisions to this path")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    client = LLMClient(provider=args.provider, model=args.model)
    set_llm(client)
    crew = ExpenseReviewCrew(load_employees(), load_history(), client)
    print(crew.describe())

    claims = load_claims()
    if args.claim:
        claims = [c for c in claims if c.claim_id == args.claim]
        if not claims:
            raise SystemExit(f"No claim with id {args.claim}")

    decisions = []
    for claim in claims:
        d = crew.review(claim)
        decisions.append(d)
        if not args.quiet:
            show(d, claim, verbose=bool(args.claim))

    print(BAR)
    totals = {
        "claims": len(decisions),
        "claimed": sum(d.claimed_total for d in decisions),
        "disallowed": sum(d.disallowed_total for d in decisions),
        "payable": sum(d.approved_total for d in decisions),
        "escalated": sum(1 for d in decisions if d.outcome == "ESCALATE"),
    }
    print(f"{totals['claims']} claim(s)  claimed INR {totals['claimed']:,.0f}  "
          f"disallowed INR {totals['disallowed']:,.0f}  "
          f"payable INR {totals['payable']:,.0f}  escalated {totals['escalated']}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps([d.to_dict() for d in decisions], indent=2), encoding="utf-8")
        print(f"written: {args.json_out}")


if __name__ == "__main__":
    main()
