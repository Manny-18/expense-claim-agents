"""Unit tests for the deterministic layer.

These test the tools, not the agents. The tools are where the money is
decided, so they are the part that must be provably correct.

Run:  python -m pytest tests -q      (or: python -m tests.test_tools)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config as C  # noqa: E402
from src import tools as T  # noqa: E402
from src.policy_store import PolicyStore  # noqa: E402
from src.schemas import Claim, Employee, LineItem  # noqa: E402


def emp(grade="B2", **kw):
    base = dict(employee_id="E1", name="Test", grade=grade, base_city="Delhi",
                manager_id="M1", manager_grade="B4", leave_dates=[],
                missing_receipt_uses_this_quarter=0)
    base.update(kw)
    return Employee(**base)


def ln(**kw):
    base = dict(line_id="L1", category="misc", vendor="V", expense_date="2026-10-01",
                amount=100.0, city="Delhi")
    base.update(kw)
    return LineItem(**base)


# ---------------------------------------------------------------- GSTIN ----

def test_gstin_valid():
    assert T.validate_gstin(C.COMPANY_GSTIN)["valid"] is True


def test_gstin_checksum_rejects_tampering():
    bad = C.COMPANY_GSTIN[:14] + ("A" if C.COMPANY_GSTIN[14] != "A" else "B")
    assert T.validate_gstin(bad)["valid"] is False


def test_gstin_absent_and_short():
    assert T.validate_gstin(None)["reason"] == "absent"
    assert T.validate_gstin("06AAJ")["valid"] is False


# ---------------------------------------------------------------- limits ---

def test_hotel_ceiling_exact_boundary_is_allowed():
    line = ln(category="hotel", amount=6490, tax_amount=990, nights=1)  # net 5500
    assert T.check_hotel_ceiling(line, emp("B2")) == []


def test_hotel_ceiling_one_rupee_over():
    line = ln(category="hotel", amount=6491, tax_amount=990, nights=1)
    f = T.check_hotel_ceiling(line, emp("B2"))
    assert len(f) == 1 and abs(f[0].disallowed_amount - 1.0) < 0.01
    assert f[0].clause == "TE-02.2"


def test_hotel_ceiling_scales_with_nights():
    line = ln(category="hotel", amount=22000, tax_amount=0, nights=4)  # 4 x 5500
    assert T.check_hotel_ceiling(line, emp("B2")) == []


def test_meal_cap_is_daily_not_per_bill():
    claim = Claim("C", "E1", "2026-10-05", "outstation_overnight", "p", [
        ln(line_id="L1", category="meals", amount=900, expense_date="2026-10-01"),
        ln(line_id="L2", category="meals", amount=900, expense_date="2026-10-01"),
    ])
    f = T.check_meal_ceilings(claim, emp("B2"))  # metro cap 1500
    assert len(f) == 1 and abs(f[0].disallowed_amount - 300) < 0.01


def test_meal_cap_not_applied_to_local_trip():
    claim = Claim("C", "E1", "2026-10-05", "local", "p", [
        ln(line_id="L1", category="meals", amount=5000, expense_date="2026-10-01")])
    f = T.check_meal_ceilings(claim, emp("B2"))
    assert all(x.disallowed_amount == 0 for x in f)


def test_same_day_trip_halves_the_meal_cap():
    claim = Claim("C", "E1", "2026-10-05", "outstation_same_day", "p", [
        ln(line_id="L1", category="meals", amount=1000, expense_date="2026-10-01")])
    f = T.check_meal_ceilings(claim, emp("B2"))  # 1500 halved to 750
    assert len(f) == 1 and abs(f[0].disallowed_amount - 250) < 0.01


def test_mileage_rate():
    f = T.check_mileage(ln(category="mileage", amount=900, distance_km=60,
                           vehicle_type="four_wheeler"))
    assert abs(f[0].disallowed_amount - 180) < 0.01


def test_mileage_exact_is_clean():
    assert T.check_mileage(ln(category="mileage", amount=405, distance_km=90,
                              vehicle_type="two_wheeler")) == []


# ------------------------------------------------------------- integrity ---

def test_duplicate_flags_but_does_not_disallow():
    claim = Claim("C", "E1", "2026-10-05", "local", "p", [
        ln(line_id="L1", vendor="Uber India", amount=740),
        ln(line_id="L2", vendor="uber  india pvt ltd", amount=742),
    ])
    f = T.detect_duplicates_within_claim(claim)
    assert len(f) == 1
    assert f[0].disallowed_amount == 0.0           # TE-11.4, a human decides
    assert f[0].evidence["needs_human"] is True
    assert f[0].evidence["amount_at_risk"] == 742


def test_duplicate_tolerance_boundary():
    assert T._within_tolerance(1000.0, 1010.0) is True    # exactly one percent
    assert T._within_tolerance(1000.0, 1020.0) is False


def test_vendor_normalisation():
    assert T.normalize_vendor("Uber India Pvt. Ltd.") == T.normalize_vendor("  UBER-india ")


def test_split_detection():
    claim = Claim("C", "E1", "2026-10-05", "local", "p", [
        ln(line_id="L1", vendor="Cafe Noir", amount=940, category="meals"),
        ln(line_id="L2", vendor="Cafe Noir", amount=920, category="meals"),
    ])
    f = T.detect_splits(claim)
    assert len(f) == 1 and f[0].clause == "TE-09.2"


# -------------------------------------------------------------- evidence ---

def test_missing_receipt_quota():
    line = ln(amount=900, receipt_available=False, missing_receipt_declaration=True)
    ok = T.check_evidence(line, emp(missing_receipt_uses_this_quarter=1))
    assert all(x.disallowed_amount == 0 for x in ok)
    blocked = T.check_evidence(line, emp(missing_receipt_uses_this_quarter=2))
    assert any(x.disallowed_amount == 900 for x in blocked)


def test_timeliness_boundaries():
    def age(days):
        from datetime import date, timedelta
        d = date(2026, 10, 10) - timedelta(days=days)
        return Claim("C", "E1", "2026-10-10", "local", "p",
                     [ln(expense_date=d.isoformat())])
    assert T.check_timeliness(age(30)) == []
    assert T.check_timeliness(age(31))[0].code == "TIME_LATE"
    assert T.check_timeliness(age(60))[0].code == "TIME_LATE"
    assert T.check_timeliness(age(61))[0].code == "TIME_BARRED"


# ---------------------------------------------------------------- policy ---

def test_policy_store_indexes_every_clause():
    store = PolicyStore()
    assert len(store) == 47  # every TE-xx.y clause in policy v3.2
    assert store.get("TE-03.2") is not None


def test_policy_retrieval_finds_the_alcohol_clause():
    store = PolicyStore()
    hits = [c.clause_id for c, _ in store.search("is wine on a dinner bill reimbursable", 5)]
    assert "TE-03.2" in hits


def test_approval_ladder():
    assert C.required_approver(10000) == "Reporting manager"
    assert C.required_approver(10001).startswith("Practice head")
    assert C.required_approver(250000) == "Chief Financial Officer"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  pass  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"x FAIL  {fn.__name__}  {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} unit tests passed")
    raise SystemExit(1 if failed else 0)
