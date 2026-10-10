"""Property based stress test.

The labelled benchmark in evaluate.py is written by the same person who wrote
the rules, so a high score there measures internal consistency and nothing
more. This file tries to break the system instead, by asserting **invariants**
that must hold for any input rather than checking specific expected answers.

Seven invariants are tested:

I1  Determinism            the same claim reviewed twice gives the same answer
I2  Monotonicity           raising a line amount never lowers the disallowance
I3  Boundary exactness     a value exactly at a ceiling is inside it
I4  Conservation           payable plus disallowed always equals claimed
I5  No auto reject on risk an integrity flag never produces a REJECT
I6  Normalisation          vendor case and spacing do not defeat duplicate
                           detection
I7  Citation completeness  every rupee disallowed cites a policy clause

Run:  python -m eval.stress_test
"""

from __future__ import annotations

import copy
import random
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.orchestrator import build_default_crew, load_claims  # noqa: E402
from src.schemas import Claim  # noqa: E402

PASS, FAIL = "pass", "FAIL"
results: List[tuple] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, PASS if ok else FAIL, detail))
    mark = " " if ok else "x"
    print(f"{mark} {name:46} {PASS if ok else FAIL}  {detail}")


def main() -> int:
    crew = build_default_crew()
    claims = load_claims()
    by_id = {c.claim_id: c for c in claims}
    rng = random.Random(20261011)

    # ---- I1 determinism --------------------------------------------------
    mismatches = 0
    for c in claims:
        a, b = crew.review(c), crew.review(c)
        if (a.outcome, a.approved_total) != (b.outcome, b.approved_total):
            mismatches += 1
    record("I1 determinism over 44 claims, two passes", mismatches == 0,
           f"{mismatches} mismatch(es)")

    # ---- I2 monotonicity -------------------------------------------------
    base = by_id["CLM-2001"]  # hotel over ceiling
    prev = -1.0
    monotone = True
    for extra in [0, 500, 1500, 4000, 9000]:
        probe = copy.deepcopy(base)
        probe.claim_id = f"{base.claim_id}-M{extra}"
        probe.lines[0].amount = base.lines[0].amount + extra
        d = crew.review(probe)
        if d.disallowed_total < prev - 0.01:
            monotone = False
        prev = d.disallowed_total
    record("I2 disallowance rises with the amount", monotone,
           f"final disallowance INR {prev:,.0f}")

    # ---- I3 boundary exactness ------------------------------------------
    # B1 metro hotel ceiling is 4,000 net of tax
    probe = copy.deepcopy(base)
    probe.lines[0].amount = 4400.0
    probe.lines[0].tax_amount = 400.0  # net exactly 4,000
    at_ceiling = crew.review(probe)
    probe2 = copy.deepcopy(probe)
    probe2.claim_id = "CLM-2001-OVER"
    probe2.lines[0].amount = 4401.0
    just_over = crew.review(probe2)
    record("I3 exactly at ceiling is allowed",
           at_ceiling.disallowed_total == 0 and at_ceiling.outcome == "APPROVE",
           f"{at_ceiling.outcome}, disallowed {at_ceiling.disallowed_total}")
    record("I3 one rupee over is caught",
           abs(just_over.disallowed_total - 1.0) < 0.01,
           f"disallowed INR {just_over.disallowed_total}")

    # ---- I4 conservation of value ---------------------------------------
    bad = []
    for c in claims:
        d = crew.review(c)
        if abs((d.approved_total + d.disallowed_total) - d.claimed_total) > 0.01:
            bad.append(c.claim_id)
    record("I4 payable plus disallowed equals claimed", not bad, ", ".join(bad[:3]))

    # ---- I5 an integrity flag never auto rejects -------------------------
    violators = []
    for c in claims:
        d = crew.review(c)
        if any(f.severity == "integrity" for f in d.findings) and d.outcome == "REJECT":
            violators.append(c.claim_id)
    record("I5 integrity flags never auto reject", not violators, ", ".join(violators[:3]))

    # ---- I6 vendor normalisation -----------------------------------------
    dup = copy.deepcopy(by_id["CLM-4002"])
    dup.claim_id = "CLM-4002-NORM"
    dup.lines[1].vendor = "  uber   india "
    normalised = crew.review(dup)
    caught = any(f.code.startswith("DUP") for f in normalised.findings)
    record("I6 duplicate survives case and spacing change", caught,
           f"outcome {normalised.outcome}")

    # ---- I7 every disallowed rupee is cited ------------------------------
    uncited = []
    for c in claims:
        d = crew.review(c)
        for f in d.findings:
            if f.disallowed_amount > 0 and not f.clause.strip():
                uncited.append(f"{c.claim_id}:{f.code}")
    record("I7 every disallowance cites a clause", not uncited, ", ".join(uncited[:3]))

    # ---- fuzz: random perturbation must never crash or go negative -------
    crashes, negatives = 0, 0
    for i in range(300):
        src = rng.choice(claims)
        probe = copy.deepcopy(src)
        probe.claim_id = f"FUZZ-{i:04d}"
        for line in probe.lines:
            line.amount = round(max(1.0, line.amount * rng.uniform(0.2, 3.0)), 2)
            line.tax_amount = round(line.tax_amount * rng.uniform(0.0, 2.5), 2)
            if rng.random() < 0.3:
                line.gstin = None
            if rng.random() < 0.2:
                line.receipt_available = False
            if rng.random() < 0.2:
                line.nights = rng.randint(0, 9)
        try:
            d = crew.review(probe)
            if d.approved_total < -0.001 or d.disallowed_total < -0.001:
                negatives += 1
            if d.approved_total > d.claimed_total + 0.01:
                negatives += 1
        except Exception as exc:  # noqa: BLE001
            crashes += 1
            if crashes <= 3:
                print(f"    crash on {probe.claim_id}: {type(exc).__name__}: {exc}")
    record("Fuzz 300 perturbed claims, no crash", crashes == 0, f"{crashes} crash(es)")
    record("Fuzz 300 perturbed claims, no impossible total", negatives == 0,
           f"{negatives} impossible total(s)")

    failed = [r for r in results if r[1] == FAIL]
    print("\n" + "=" * 70)
    print(f"{len(results) - len(failed)}/{len(results)} invariants hold")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
