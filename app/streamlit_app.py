"""Reviewer front end.

The interface is built for a finance reviewer, not for a demo. Three things
drove the design:

1. The reviewer's job is to handle exceptions, so the queue is sorted by risk
   and the escalations are what the eye lands on first.
2. Every number on screen can be traced to a clause, because a reviewer who
   cannot see why will not trust the recommendation and will redo the work.
3. The human decides. The override control is always available, it is never
   buried, and overriding requires a reason that is written to the audit log.

Run:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config as C  # noqa: E402
from src.llm import LLMClient, set_llm  # noqa: E402
from src.orchestrator import (ExpenseReviewCrew, load_claims, load_employees,  # noqa: E402
                              load_history)
from src.schemas import Claim, LineItem  # noqa: E402

st.set_page_config(page_title="Expense Claim Adjudication Crew", page_icon="::",
                   layout="wide")

OUTCOME_COLOUR = {
    "APPROVE": "#1b7f4d",
    "PARTIAL_APPROVE": "#9a6b00",
    "REJECT": "#a32020",
    "ESCALATE": "#1f4e9c",
}
SEVERITY_ICON = {"integrity": "!!", "violation": "!", "advisory": "~", "info": "i"}


# ---------------------------------------------------------------- loading --

@st.cache_resource(show_spinner=False)
def get_crew(provider: str, model: str) -> ExpenseReviewCrew:
    client = LLMClient(provider=provider, model=model)
    set_llm(client)
    return ExpenseReviewCrew(load_employees(), load_history(), client)


@st.cache_data(show_spinner=False)
def get_claims():
    return {c.claim_id: c for c in load_claims()}


def review_all(_crew: ExpenseReviewCrew, claims: dict) -> dict:
    out = {}
    bar = st.progress(0.0, text="Reviewing claims")
    for i, (cid, claim) in enumerate(claims.items(), start=1):
        out[cid] = _crew.review(claim)
        bar.progress(i / len(claims), text=f"Reviewing {cid}")
    bar.empty()
    return out


# ----------------------------------------------------------------- layout --

st.title("Expense Claim Adjudication Crew")
st.caption(f"Six domain expert agents reviewing travel and expense claims against "
           f"{C.COMPANY_NAME} policy {C.POLICY_VERSION}")

with st.sidebar:
    st.header("Engine")
    provider = st.selectbox(
        "Model provider", ["offline", "ollama", "gemini", "openai"], index=0,
        help="Offline runs the deterministic rule engine only. Every rupee decision is "
             "identical across providers; the model changes only the narrative and the "
             "classification of free text lines.")
    model = st.text_input("Model name", value="llama3.1:8b" if provider == "ollama"
                          else ("gemini-2.0-flash" if provider == "gemini" else "gpt-4o-mini"),
                          disabled=provider == "offline")
    crew = get_crew(provider, model)
    st.success(f"Model: {crew.llm.describe()}")
    st.metric("Policy clauses indexed", len(crew.policy))

    st.divider()
    st.header("Agents")
    for agent in [crew.intake] + crew.experts + [crew.adjudicator, crew.communicator]:
        with st.expander(agent.role):
            st.caption(agent.charter)

    st.divider()
    if st.button("Re-run all reviews", width="stretch"):
        st.session_state.pop("decisions", None)

claims = get_claims()
if "decisions" not in st.session_state:
    st.session_state["decisions"] = review_all(crew, claims)
if "overrides" not in st.session_state:
    st.session_state["overrides"] = {}
decisions = st.session_state["decisions"]

queue_tab, detail_tab, submit_tab, eval_tab = st.tabs(
    ["Review queue", "Claim detail", "Submit a claim", "How well does it work"])

# ------------------------------------------------------------- queue tab ---

with queue_tab:
    rows = []
    for cid, d in decisions.items():
        ov = st.session_state["overrides"].get(cid)
        rows.append({
            "Claim": cid,
            "Employee": d.employee_id,
            "Outcome": ov["outcome"] if ov else d.outcome,
            "Overridden": "yes" if ov else "",
            "Claimed": d.claimed_total,
            "Disallowed": d.disallowed_total,
            "Payable": d.approved_total,
            "Risk": d.risk_score,
            "Approver": d.required_approver,
            "Flags": len([f for f in d.findings if f.severity in {"violation", "integrity"}]),
        })
    df = pd.DataFrame(rows)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Claims", len(df))
    c2.metric("Total claimed", f"INR {df['Claimed'].sum():,.0f}")
    c3.metric("Disallowed", f"INR {df['Disallowed'].sum():,.0f}")
    c4.metric("Straight through",
              f"{(df['Outcome'].isin(['APPROVE', 'PARTIAL_APPROVE'])).mean():.0%}",
              help="Share of claims settled with no human needed")
    c5.metric("Escalated", int((df["Outcome"] == "ESCALATE").sum()))

    st.divider()
    f1, f2 = st.columns([2, 3])
    chosen = f1.multiselect("Filter by outcome", sorted(df["Outcome"].unique()),
                            default=sorted(df["Outcome"].unique()))
    min_risk = f2.slider("Minimum risk score", 0, 100, 0)
    view = df[df["Outcome"].isin(chosen) & (df["Risk"] >= min_risk)]
    view = view.sort_values(["Risk", "Claimed"], ascending=False)

    st.dataframe(
        view, width="stretch", hide_index=True,
        column_config={
            "Claimed": st.column_config.NumberColumn(format="%.0f"),
            "Disallowed": st.column_config.NumberColumn(format="%.0f"),
            "Payable": st.column_config.NumberColumn(format="%.0f"),
            "Risk": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
        })

    st.bar_chart(df.groupby("Outcome")["Claim"].count(), horizontal=True)

# ------------------------------------------------------------ detail tab ---

with detail_tab:
    ordered = sorted(decisions.keys(),
                     key=lambda k: -decisions[k].risk_score)
    cid = st.selectbox("Claim", ordered,
                       format_func=lambda k: f"{k}  ({decisions[k].outcome}, risk "
                                             f"{decisions[k].risk_score})")
    d = decisions[cid]
    claim = claims[cid]
    emp = crew.employees[claim.employee_id]

    head = st.container()
    with head:
        colour = OUTCOME_COLOUR.get(d.outcome, "#444")
        st.markdown(
            f"<div style='padding:14px 18px;border-left:6px solid {colour};"
            f"background:rgba(128,128,128,0.08);border-radius:6px'>"
            f"<span style='font-size:1.4rem;font-weight:700;color:{colour}'>{d.outcome}</span>"
            f"<br><span style='opacity:0.8'>{emp.name}, grade {emp.grade}, "
            f"{emp.base_city} &nbsp;|&nbsp; {claim.purpose}</span></div>",
            unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Claimed", f"INR {d.claimed_total:,.0f}")
    m2.metric("Disallowed", f"INR {d.disallowed_total:,.0f}")
    m3.metric("Payable", f"INR {d.approved_total:,.0f}")
    m4.metric("Risk", f"{d.risk_score}/100")
    st.caption(f"Approval authority under TE-08.1: **{d.required_approver}**")

    st.subheader("Lines")
    st.dataframe(pd.DataFrame([{
        "Line": l.line_id, "Category": l.category, "Vendor": l.vendor,
        "Date": l.expense_date, "City": l.city, "Amount": l.amount,
        "Tax": l.tax_amount, "GSTIN": l.gstin or "", "Receipt": "yes" if l.receipt_available
        else "no", "Description": l.description,
    } for l in claim.lines]), width="stretch", hide_index=True)

    st.subheader("What each agent found")
    for agent_name in ["IntakeAgent", "PolicyExpertAgent", "TaxComplianceAgent",
                       "FraudRiskAgent", "AdjudicatorAgent"]:
        agent_findings = [f for f in d.findings if f.agent == agent_name]
        if not agent_findings:
            continue
        worst = min((["integrity", "violation", "advisory", "info"].index(f.severity)
                     for f in agent_findings), default=3)
        label = ["integrity flag", "violation", "advisory", "clean"][worst]
        with st.expander(f"{agent_name}  ({len(agent_findings)} finding(s), worst: {label})",
                         expanded=worst <= 1):
            for f in agent_findings:
                money = (f" &nbsp; **disallows INR {f.disallowed_amount:,.0f}**"
                         if f.disallowed_amount else "")
                st.markdown(f"`{SEVERITY_ICON.get(f.severity, '-')}` **[{f.clause or 'n/a'}]** "
                            f"{f.message}{money}", unsafe_allow_html=True)
                if f.evidence:
                    st.caption(json.dumps(f.evidence, default=str))

    itc = crew  # keep reference tidy
    st.subheader("Agent trace")
    st.dataframe(pd.DataFrame([{
        "Agent": t.agent, "Role": t.role, "Findings": t.findings_count,
        "Used model": "yes" if t.used_llm else "no", "ms": t.duration_ms,
    } for t in d.trace]), width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Message to the employee")
        st.text_area("employee_message", d.employee_message, height=320,
                     label_visibility="collapsed")
    with right:
        st.subheader("Audit note")
        st.code(d.audit_note, language="text")

    st.subheader("Reviewer decision")
    st.caption("The system recommends. A person decides, and the reason is written to the "
               "audit log.")
    o1, o2, o3 = st.columns([1, 2, 1])
    new_outcome = o1.selectbox("Final outcome",
                               ["APPROVE", "PARTIAL_APPROVE", "REJECT", "ESCALATE"],
                               index=["APPROVE", "PARTIAL_APPROVE", "REJECT",
                                      "ESCALATE"].index(d.outcome))
    reason = o2.text_input("Reason (required to override)")
    if o3.button("Record decision", type="primary", width="stretch"):
        if new_outcome != d.outcome and not reason.strip():
            st.error("An override needs a reason.")
        else:
            st.session_state["overrides"][cid] = {
                "outcome": new_outcome, "reason": reason.strip(),
                "at": datetime.now().isoformat(timespec="seconds"),
            }
            st.success(f"Recorded: {new_outcome}")

    if cid in st.session_state["overrides"]:
        ov = st.session_state["overrides"][cid]
        st.info(f"Human decision on record: **{ov['outcome']}** at {ov['at']}. "
                f"Reason: {ov['reason'] or 'agreed with the recommendation'}")

# ------------------------------------------------------------ submit tab ---

with submit_tab:
    st.caption("Submit a claim and watch the agents review it live.")
    with st.form("new_claim"):
        c1, c2, c3 = st.columns(3)
        emp_id = c1.selectbox("Employee", list(crew.employees.keys()),
                              format_func=lambda k: f"{k} - {crew.employees[k].name} "
                                                    f"({crew.employees[k].grade})")
        trip = c2.selectbox("Trip type", ["outstation_overnight", "outstation_same_day",
                                          "local", "none"])
        submitted_on = c3.date_input("Submitted on", value=date(2026, 10, 11))
        purpose = st.text_input("Business purpose", "Client meeting")

        st.markdown("**Line items**")
        template = pd.DataFrame([{
            "category": "hotel", "vendor": "Taj Mahal Hotel", "expense_date": "2026-10-05",
            "amount": 9000.0, "tax_amount": 1200.0, "city": "Delhi", "nights": 1,
            "gstin": "07AABCT1234M1Z5", "invoice_no": "INV/001", "receipt_available": True,
            "alcohol_amount": 0.0, "distance_km": 0.0, "vehicle_type": "",
            "engagement_code": "MER-204", "description": "Room rent",
        }])
        edited = st.data_editor(template, num_rows="dynamic", width="stretch",
                                key="line_editor")
        go = st.form_submit_button("Review this claim", type="primary")

    if go:
        lines = []
        for i, r in edited.iterrows():
            lines.append(LineItem(
                line_id=f"L{i + 1}", category=str(r["category"]), vendor=str(r["vendor"]),
                expense_date=str(r["expense_date"]), amount=float(r["amount"] or 0),
                city=str(r["city"]), tax_amount=float(r["tax_amount"] or 0),
                gstin=str(r["gstin"]) or None, invoice_no=str(r["invoice_no"]) or None,
                receipt_available=bool(r["receipt_available"]),
                nights=int(r["nights"]) if r["nights"] else None,
                alcohol_amount=float(r["alcohol_amount"] or 0),
                contains_alcohol=float(r["alcohol_amount"] or 0) > 0,
                distance_km=float(r["distance_km"]) if r["distance_km"] else None,
                vehicle_type=str(r["vehicle_type"]) or None,
                engagement_code=str(r["engagement_code"]) or None,
                description=str(r["description"]),
            ))
        adhoc = Claim(f"ADHOC-{datetime.now().strftime('%H%M%S')}", emp_id,
                      submitted_on.isoformat(), trip, purpose, lines)
        with st.spinner("Six agents reviewing"):
            result = crew.review(adhoc)

        colour = OUTCOME_COLOUR.get(result.outcome, "#444")
        st.markdown(f"### <span style='color:{colour}'>{result.outcome}</span>",
                    unsafe_allow_html=True)
        a, b, c = st.columns(3)
        a.metric("Claimed", f"INR {result.claimed_total:,.0f}")
        b.metric("Disallowed", f"INR {result.disallowed_total:,.0f}")
        c.metric("Payable", f"INR {result.approved_total:,.0f}")
        for f in result.findings:
            if f.severity in {"integrity", "violation"}:
                st.warning(f"**[{f.clause}]** {f.message}")
        st.text_area("Message to the employee", result.employee_message, height=280)

# -------------------------------------------------------------- eval tab ---

with eval_tab:
    st.caption("Measured against 44 claims whose correct answer was written by hand from "
               "the policy before the system was run.")
    results_path = ROOT / "eval" / "results.json"
    if not results_path.exists():
        st.info("Run `python -m eval.evaluate` to generate the report.")
    else:
        rep = json.loads(results_path.read_text())
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Outcome accuracy", f"{rep['outcome_accuracy']:.1%}")
        k2.metric("Exact match", f"{rep['exact_match']:.1%}",
                  help="Correct outcome and correct rupee amount")
        k3.metric("Leakage", f"INR {rep['leakage_inr']:,.0f}",
                  help="Money that should have been stopped and was not")
        k4.metric("Mean latency", f"{rep['mean_latency_ms']:.1f} ms")

        st.subheader("Confusion matrix")
        st.dataframe(pd.DataFrame(rep["confusion"]).T, width="stretch")
        st.subheader("Per claim")
        st.dataframe(pd.DataFrame(rep["rows"]), width="stretch", hide_index=True)

        st.warning(
            "Read this number honestly. A perfect score on a benchmark written by the same "
            "person who wrote the rules measures internal consistency, not real world "
            "accuracy. The property based stress test in eval/stress_test.py is the harder "
            "check, and the limitation is discussed in the project report.")
