"""Evaluation harness.

Two things are measured, because an adjudication system can be right about
the outcome and wrong about the money:

1. **Outcome accuracy** against the hand authored labels, with a confusion
   matrix and per class precision and recall.
2. **Rupee accuracy**: the disallowed amount against the expected disallowed
   amount, reported as mean absolute error and as total leakage. Leakage is
   the amount the system would have paid out that policy says it should not,
   which is the number a finance controller will ask for first.

Two error classes are separated because they cost very different things:

* **Leakage**, approving what should have been stopped. The company loses money.
* **Friction**, stopping what should have been approved. The employee loses
  time and trust, and finance absorbs a query.

Run:  python -m eval.evaluate
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.orchestrator import build_default_crew, load_claims  # noqa: E402
from src.schemas import Decision  # noqa: E402

OUTCOMES = ["APPROVE", "PARTIAL_APPROVE", "REJECT", "ESCALATE"]
PAYING = {"APPROVE", "PARTIAL_APPROVE"}


def load_truth() -> Dict[str, dict]:
    rows = json.loads((ROOT / "eval" / "ground_truth.json").read_text(encoding="utf-8"))
    return {r["claim_id"]: r for r in rows}


def confusion(pairs: List[tuple]) -> Dict[str, Dict[str, int]]:
    m = {a: {p: 0 for p in OUTCOMES} for a in OUTCOMES}
    for actual, predicted in pairs:
        m[actual][predicted] = m[actual].get(predicted, 0) + 1
    return m


def per_class(m: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, float]]:
    out = {}
    for label in OUTCOMES:
        tp = m[label][label]
        fn = sum(m[label][p] for p in OUTCOMES) - tp
        fp = sum(m[a][label] for a in OUTCOMES) - tp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        out[label] = {"support": tp + fn, "precision": round(precision, 3),
                      "recall": round(recall, 3), "f1": round(f1, 3)}
    return out


def run() -> dict:
    crew = build_default_crew()
    claims = load_claims()
    truth = load_truth()

    print(crew.describe())
    print(f"\nEvaluating {len(claims)} claims\n" + "=" * 78)

    pairs, rows = [], []
    abs_err, leakage, friction = 0.0, 0.0, 0.0
    total_ms = 0

    for claim in claims:
        d: Decision = crew.review(claim)
        t = truth[claim.claim_id]
        pairs.append((t["expected_outcome"], d.outcome))
        err = abs(d.disallowed_total - t["expected_disallowed"])
        abs_err += err
        if d.disallowed_total < t["expected_disallowed"]:
            leakage += t["expected_disallowed"] - d.disallowed_total
        else:
            friction += d.disallowed_total - t["expected_disallowed"]
        total_ms += sum(s.duration_ms for s in d.trace)

        ok = "PASS" if d.outcome == t["expected_outcome"] and err < 0.5 else "FAIL"
        rows.append({
            "claim_id": claim.claim_id, "scenario": t["scenario"], "status": ok,
            "expected_outcome": t["expected_outcome"], "actual_outcome": d.outcome,
            "expected_disallowed": t["expected_disallowed"],
            "actual_disallowed": d.disallowed_total,
            "claimed": d.claimed_total, "approved": d.approved_total,
            "risk": d.risk_score,
        })
        flag = " " if ok == "PASS" else "x"
        print(f"{flag} {claim.claim_id}  {t['scenario'][:38]:38} "
              f"exp {t['expected_outcome']:15} got {d.outcome:15} "
              f"disallow exp {t['expected_disallowed']:>9,.0f} got {d.disallowed_total:>9,.0f}")

    m = confusion(pairs)
    correct = sum(m[o][o] for o in OUTCOMES)
    n = len(pairs)
    exact = sum(1 for r in rows if r["status"] == "PASS")

    # a stricter, business relevant view: did we correctly decide whether to
    # pay without a human, and did we never auto reject something payable?
    auto_pay_errors = sum(1 for a, p in pairs if a == "ESCALATE" and p in PAYING)
    wrong_rejects = sum(1 for a, p in pairs if a in PAYING and p == "REJECT")

    print("=" * 78)
    print(f"Outcome accuracy        {correct}/{n} = {correct / n:.1%}")
    print(f"Exact match (outcome and rupees)  {exact}/{n} = {exact / n:.1%}")
    print(f"Mean absolute rupee error         INR {abs_err / n:,.2f}")
    print(f"Leakage (underblocked)            INR {leakage:,.2f}")
    print(f"Friction (overblocked)            INR {friction:,.2f}")
    print(f"Escalations auto paid instead     {auto_pay_errors}")
    print(f"Payable claims auto rejected      {wrong_rejects}")
    print(f"Mean latency per claim            {total_ms / n:.1f} ms")

    print("\nConfusion matrix (rows are expected, columns are predicted)")
    header = "".join(f"{o[:9]:>12}" for o in OUTCOMES)
    print(f"{'':18}{header}")
    for a in OUTCOMES:
        print(f"{a:18}" + "".join(f"{m[a][p]:>12}" for p in OUTCOMES))

    print("\nPer class")
    pc = per_class(m)
    print(f"{'class':18}{'support':>9}{'precision':>11}{'recall':>9}{'f1':>8}")
    for label, s in pc.items():
        print(f"{label:18}{s['support']:>9}{s['precision']:>11.3f}"
              f"{s['recall']:>9}{s['f1']:>8}")

    report = {
        "n_claims": n,
        "outcome_accuracy": round(correct / n, 4),
        "exact_match": round(exact / n, 4),
        "mean_abs_rupee_error": round(abs_err / n, 2),
        "leakage_inr": round(leakage, 2),
        "friction_inr": round(friction, 2),
        "escalations_auto_paid": auto_pay_errors,
        "payable_auto_rejected": wrong_rejects,
        "mean_latency_ms": round(total_ms / n, 1),
        "confusion": m,
        "per_class": pc,
        "rows": rows,
        "model": crew.llm.describe(),
    }
    (ROOT / "eval" / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    import csv
    with (ROOT / "eval" / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\nWritten: eval/results.json and eval/results.csv")
    return report


if __name__ == "__main__":
    run()
