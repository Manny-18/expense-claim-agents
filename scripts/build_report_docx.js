// Build the project report as a Word document.
// Usage: node scripts/build_report_docx.js "<Name>" "<Roll No>" "<output.docx>"

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, BorderStyle,
  Table, TableRow, TableCell, WidthType, ShadingType, ImageRun, PageOrientation,
  LevelFormat, convertInchesToTwip,
} = require("docx");

const AUTHOR = process.argv[2] || "Manav Verma";
const ROLL = process.argv[3] || "";
const OUT = process.argv[4] || "project_report.docx";
const ROOT = path.resolve(__dirname, "..");

const INK = "000000";
const MUTED = "000000";
const RULE = "C3CCD8";
const HEADER_BG = "EEF2F7";
const CODE_BG = "F5F7FA";

// ---------------------------------------------------------------- helpers --

const p = (text, opts = {}) => new Paragraph({
  spacing: { after: opts.after ?? 140, line: 300 },
  alignment: opts.align,
  children: [new TextRun({
    text, size: opts.size ?? 23, color: opts.color ?? INK,
    bold: opts.bold, italics: opts.italics, font: "Times New Roman",
  })],
});

// paragraph from [{t, b, i, code}] runs, so bold can appear mid sentence
const rich = (runs, opts = {}) => new Paragraph({
  spacing: { after: opts.after ?? 140, line: 300 },
  alignment: opts.align,
  children: runs.map(r => new TextRun({
    text: r.t, bold: r.b, italics: r.i, size: opts.size ?? 23,
    color: r.color ?? opts.color ?? INK,
    font: "Times New Roman",
  })),
});

const h1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 380, after: 170 },
  children: [new TextRun({ text, font: "Times New Roman", size: 30, bold: true, color: INK })],
});

const h2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 280, after: 130 },
  children: [new TextRun({ text, font: "Times New Roman", size: 24, bold: true, color: INK })],
});

const bullet = (text, level = 0) => new Paragraph({
  numbering: { reference: "bullets", level },
  spacing: { after: 90, line: 300 },
  children: [new TextRun({ text, font: "Times New Roman", size: 23, color: INK })],
});

const numbered = (text) => new Paragraph({
  numbering: { reference: "numbers", level: 0 },
  spacing: { after: 110, line: 300 },
  children: [new TextRun({ text, font: "Times New Roman", size: 23, color: INK })],
});

const code = (lines) => lines.map((line, i) => new Paragraph({
  spacing: { after: i === lines.length - 1 ? 150 : 0, line: 240 },
  shading: { type: ShadingType.CLEAR, fill: CODE_BG },
  indent: { left: 170, right: 170 },
  children: [new TextRun({ text: line || " ", font: "Times New Roman", size: 20, color: INK })],
}));

const rule = () => new Paragraph({
  spacing: { before: 120, after: 200 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE } },
  children: [new TextRun("")],
});

// Letter page, 1 inch margins -> 6.5in of text = 9360 DXA
const TEXT_DXA = 9360;

function table(headers, rows, weights) {
  const w = weights || headers.map(() => 1 / headers.length);
  const widths = w.map(x => Math.round(TEXT_DXA * x));
  widths[widths.length - 1] = TEXT_DXA - widths.slice(0, -1).reduce((a, b) => a + b, 0);

  const cell = (text, i, isHeader) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA },
    shading: isHeader ? { type: ShadingType.CLEAR, fill: HEADER_BG } : undefined,
    margins: { top: 70, bottom: 70, left: 110, right: 110 },
    children: [new Paragraph({
      spacing: { after: 0, line: 260 },
      children: [new TextRun({
        text, font: "Times New Roman", size: 20, bold: isHeader, color: INK,
      })],
    })],
  });

  return new Table({
    width: { size: TEXT_DXA, type: WidthType.DXA },
    columnWidths: widths,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      left: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      right: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 4, color: RULE },
      insideVertical: { style: BorderStyle.SINGLE, size: 4, color: RULE },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((t, i) => cell(t, i, true)),
      }),
      ...rows.map(r => new TableRow({ children: r.map((t, i) => cell(t, i, false)) })),
    ],
  });
}

const spacer = (after = 170) => new Paragraph({ spacing: { after }, children: [new TextRun("")] });

// ------------------------------------------------------------------ body --

const children = [];

// Title block
children.push(new Paragraph({
  spacing: { before: 700, after: 90 },
  alignment: AlignmentType.CENTER,
  children: [new TextRun({
    text: "Domain Expert AI Agents for Travel and Expense Adjudication",
    font: "Times New Roman", bold: true, size: 40, color: INK,
  })],
}));
children.push(p("A multi agent system for policy compliant expense claim review",
  { align: AlignmentType.CENTER, size: 23, color: MUTED, after: 420 }));

children.push(new Paragraph({
  spacing: { after: 70 }, alignment: AlignmentType.CENTER,
  border: { top: { style: BorderStyle.SINGLE, size: 6, color: RULE } },
  children: [new TextRun("")],
}));
children.push(p("Individual Assignment, Agentic AI",
  { align: AlignmentType.CENTER, bold: true, size: 22, after: 70 }));
children.push(p("PGDM (BDA), Batch 2025-27, FORE School of Management",
  { align: AlignmentType.CENTER, size: 20, color: MUTED, after: 70 }));
children.push(p(`${AUTHOR}   |   Roll No. ${ROLL}`,
  { align: AlignmentType.CENTER, bold: true, size: 22, after: 70 }));
children.push(p("Policy under review: Meridian Consulting India Pvt. Ltd. T&E Policy v3.2",
  { align: AlignmentType.CENTER, size: 19, color: MUTED, after: 70 }));
children.push(new Paragraph({
  spacing: { after: 320 }, alignment: AlignmentType.CENTER,
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE } },
  children: [new TextRun("")],
}));

// Abstract box
children.push(new Paragraph({
  spacing: { after: 320, line: 300 },
  shading: { type: ShadingType.CLEAR, fill: HEADER_BG },
  indent: { left: 170, right: 170 },
  border: {
    top: { style: BorderStyle.SINGLE, size: 4, color: RULE },
    bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE },
    left: { style: BorderStyle.SINGLE, size: 4, color: RULE },
    right: { style: BorderStyle.SINGLE, size: 4, color: RULE },
  },
  children: [
    new TextRun({ text: "Summary.  ", font: "Times New Roman", bold: true, size: 20, color: INK }),
    new TextRun({
      text: "Six domain expert agents review a travel and expense claim against a 47 "
        + "clause company policy, decide what is payable, cite the clause behind every "
        + "rupee disallowed, route the claim to the correct approver, and write both the "
        + "message to the employee and the audit note for the file. The system scores 100 "
        + "percent on 44 hand labelled claims and holds 10 property based invariants "
        + "including a 300 claim fuzz run. Section 6.3 explains why the first of those two "
        + "numbers means less than the second.",
      font: "Times New Roman", size: 20, color: INK,
    }),
  ],
}));

// --- 1 -------------------------------------------------------------------
children.push(h1("1. The business process and why it was chosen"));
children.push(p("Travel and expense (T&E) reimbursement is the most ordinary finance process in any services firm, and that is exactly why it was chosen over something more exotic. It is high volume, low value per transaction, and dense with rules. A mid size consulting firm processes a few thousand claims a month against a policy of roughly fifty clauses, and a finance associate has about ninety seconds for each one."));
children.push(p("Three failures recur, and they are not the same failure:"));
children.push(rich([{ t: "Leakage. ", b: true }, { t: "Over ceiling spend gets approved because nobody recomputes a grade entitlement, net of tax, prorated across nights, at six on a Friday. The firm pays money the policy says it should not." }]));
children.push(rich([{ t: "Friction. ", b: true }, { t: "A legitimate claim is queried because the reviewer is not sure, and the employee spends a week chasing two thousand rupees. The cost is in trust and in the reviewer's time, and it never appears in any ledger." }]));
children.push(rich([{ t: "No evidenced control. ", b: true }, { t: "The reason a claim was approved exists only in a reviewer's head. When an auditor asks how the firm knows that its entitlement limits are enforced, there is nothing to show." }]));
children.push(p("A single model prompted with the whole policy can make a plausible decision here, but it cannot do the three things that matter: produce the right number reliably, say which clause the number came from, and behave differently when the stakes change. That is the argument for a multi agent design, and it is an argument about division of expertise rather than about throughput."));

// --- 2 -------------------------------------------------------------------
children.push(h1("2. Why this is genuinely multi agent, and not one prompt in costume"));
children.push(p("The claim document is read by three different specialisms that reach different and independent conclusions about it."));
children.push(rich([
  { t: "A hotel invoice from Bengaluru against a Haryana registration is " },
  { t: "fully reimbursable to the employee", b: true },
  { t: " and simultaneously " },
  { t: "worthless as input tax credit to the company", b: true },
  { t: ". Those are two correct answers to two different questions. A single reviewer, human or model, conflates them, and the usual symptom is a claim approved at the wrong value or a credit register that is quietly wrong all year." },
]));
children.push(p("The same separation holds between entitlement and integrity. Whether a meal exceeded a daily ceiling is arithmetic. Whether a duplicate line is a duplicate is a judgement about a person, and the correct institutional answer to it is almost always to ask a human. The two questions deserve different agents with different authority, which is the design the system implements."));

// --- 3 -------------------------------------------------------------------
children.push(h1("3. Architecture"));

const imgPath = path.join(ROOT, "docs", "architecture.png");
if (fs.existsSync(imgPath)) {
  children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 90 },
    children: [new ImageRun({
      type: "png",
      data: fs.readFileSync(imgPath),
      transformation: { width: 624, height: 420 },
    })],
  }));
  children.push(p("Figure 1. Six domain expert agents over a deterministic tool layer.",
    { align: AlignmentType.CENTER, size: 17, color: MUTED, italics: true, after: 220 }));
}

children.push(rich([
  { t: "The topology is a " }, { t: "blackboard pipeline", b: true },
  { t: ": agents never call each other, they read from and write to one shared state object. At any moment the blackboard can be printed and it shows exactly what the system believes and which agent said it, which is what makes the audit trail a property of the design rather than a logging afterthought." },
]));
children.push(table(
  ["Stage", "Agent or agents", "What happens"],
  [
    ["1", "Intake Agent", "Evidence sufficiency. Short circuits the rest if no line carries any evidence at all."],
    ["2", "Policy Expert, Tax Expert, Integrity Analyst", "Three specialists read and write the same blackboard."],
    ["3", "Adjudicator", "Arbitration. The only agent that sets an outcome."],
    ["4", "Communicator", "Employee message and audit note."],
  ],
  [0.08, 0.34, 0.58],
));
children.push(spacer());
children.push(p("A debate or negotiation topology was considered and rejected. Expense adjudication has a deterministic ground truth: a ceiling is either breached or it is not. Agents arguing about it adds latency and variance and destroys reproducibility, and it buys nothing that arbitration against a fixed precedence order does not already give."));

children.push(h2("3.1 The six agents and their authority"));
children.push(table(
  ["Agent", "Domain", "May disallow", "May escalate", "Sets outcome"],
  [
    ["Intake, Document and Data Steward", "Evidence sufficiency, TE-05", "yes", "yes", "no"],
    ["Policy Entitlement Expert", "Ceilings, conveyance, timelines, TE-02/03/04/07/10", "yes, with a clause", "yes", "no"],
    ["Indirect Tax Expert", "GSTIN validity, blocked credit, TE-06", "rarely", "yes", "no"],
    ["Integrity Risk Analyst", "Duplicates, splits, leave dates, TE-09", "no", "yes", "no"],
    ["Adjudicator", "Outcome and routing, TE-08/11", "no", "n/a", "yes"],
    ["Communicator", "Employee message, audit note", "no", "no", "no"],
  ],
  [0.24, 0.34, 0.16, 0.13, 0.13],
));
children.push(spacer());
children.push(p("Each agent carries a written charter that is injected into its system prompt and that also governs what its code is allowed to do. The charter is not decoration. A narrow agent holding the three clauses that matter outperforms one large prompt holding fifty, and the narrowness is also what makes each agent separately testable."));

// --- 4 -------------------------------------------------------------------
children.push(h1("4. The three decisions this project would defend in a viva"));

children.push(h2("4.1 No agent computes a rupee value"));
children.push(p("Every arithmetic operation, date calculation, checksum validation and threshold comparison happens in src/tools.py, in ordinary Python with twenty unit tests behind it. The language model is used for exactly two things: classifying a free text line whose meaning is genuinely ambiguous, and writing the explanation a human reads."));
children.push(p("This is the single most important choice in the project. A finance control that silently miscalculates is worse than no control, because it is trusted. A function with tests can be audited; a model's arithmetic cannot. The practical consequence is that the system produces identical rupee amounts whether it runs against Llama 3.1 locally, against Gemini, or against nothing at all."));

children.push(h2("4.2 Escalation outranks rejection"));
children.push(p("The Adjudicator applies a fixed precedence order, highest first:"));
children.push(numbered("Any integrity flag, or any finding that asks for a human, forces ESCALATE"));
children.push(numbered("A disallowance with no clause citation is invalid under TE-11.2 and becomes an escalation"));
children.push(numbered("If nothing payable survives, REJECT"));
children.push(numbered("If something was disallowed but a balance remains, PARTIAL APPROVE"));
children.push(numbered("Otherwise APPROVE"));
children.push(p("The order matters more than any individual rule, because it is what stops the system from rejecting a person on a machine's say so. A suspected duplicate consequently disallows nothing. It records the amount at risk in its evidence and hands the money decision to a reviewer. Two genuine taxi rides from the same aggregator on the same day look identical in the data, and the asymmetry of costs is stark: a few hundred rupees overpaid against a false accusation of dishonesty made by software."));
children.push(p("One refinement emerged from testing. An escalation about a line that is already being disallowed in full cannot change the settlement, so the Adjudicator retires it as moot and records that it did. Integrity flags are exempt, because TE-11.4 requires those to reach a person whatever the money does."));

children.push(h2("4.3 The default path has no model in it"));
children.push(p("The offline provider is not a stub. Because the tool layer owns every decision that touches money, the system with no model still produces a complete, correct and auditable decision, and only the narrative wording becomes templated. Three things follow: anyone who clones the repository can reproduce every number in it, the evaluation measures the system rather than the weather inside a model, and a firm with a data residency constraint can run the whole thing on a laptop with Ollama and nothing leaving the building."));

// --- 5 -------------------------------------------------------------------
children.push(h1("5. Implementation notes"));
children.push(rich([{ t: "Policy retrieval. ", b: true }, { t: "The policy is chunked by clause identifier rather than by token window, because a clause is the natural semantic unit of a finance rule and because TE-11.2 requires every disallowance to cite one. Retrieval is TF-IDF with cosine similarity in about forty lines of standard library code, which indexes 47 clauses and needs no vector database or embedding service. For a corpus of this size that is not a compromise; an embedding model would add a dependency and a download to retrieve from a document shorter than this report." }]));
children.push(rich([{ t: "Where the model is actually used. ", b: true }, { t: "The Policy Expert sends a free text line and its four nearest clauses to the model and asks a classification question: does this text fall under one of these clauses? It never asks whether something is allowed in the abstract. A small local model can do the former reliably and cannot do the latter. The Communicator uses the model to rewrite the templated employee message more naturally, and is explicitly forbidden from restating an amount it was not given." }]));
children.push(rich([{ t: "Graceful degradation. ", b: true }, { t: "Every model call is wrapped so that a timeout, a bad key or malformed JSON returns the deterministic fallback rather than raising. A finance run should not fail because a server is slow." }]));
children.push(rich([{ t: "The CrewAI path. ", b: true }, { t: "src/crew_runner.py expresses the same agents and the same tools in CrewAI, so the two designs can be compared directly and so the project can be run inside the framework used in class. The native orchestrator remains the tested path, because it is deterministic, runs with no model, and takes about one millisecond per claim against seconds for the framework path. Both call the identical tool objects, so the arithmetic cannot drift between them." }]));

// --- 6 -------------------------------------------------------------------
children.push(h1("6. Evaluation"));

children.push(h2("6.1 Method"));
children.push(p("44 claims were written covering clean cases, every category of partial disallowance, rejections, escalations, and a set of edge cases chosen specifically to catch false positives: a Saturday expense that carries an engagement code, a claim exactly 30 days old, three round amounts in one claim, a meal in the city of posting."));
children.push(rich([
  { t: "The correct answer for each claim, both the outcome and the rupee disallowance, was " },
  { t: "written by hand from the policy text before the system was run", b: true },
  { t: ". Labels generated by the system under test would measure nothing at all, which is the most common flaw in agent project write ups." },
]));
children.push(p("Two error classes are reported separately because they cost different things:"));
children.push(bullet("Leakage: money approved that policy says should have been stopped"));
children.push(bullet("Friction: money stopped that policy says should have been approved"));

children.push(h2("6.2 Results"));
children.push(table(
  ["Measure", "Result"],
  [
    ["Outcome accuracy", "44 / 44 = 100.0%"],
    ["Exact match, outcome and rupees", "44 / 44 = 100.0%"],
    ["Mean absolute rupee error", "INR 0.00"],
    ["Leakage, money underblocked", "INR 0.00"],
    ["Friction, money overblocked", "INR 0.00"],
    ["Escalations auto paid instead", "0"],
    ["Payable claims auto rejected", "0"],
    ["Mean latency per claim", "0.1 ms"],
  ],
  [0.62, 0.38],
));
children.push(spacer());
children.push(p("Confusion matrix, rows are expected and columns are predicted:", { after: 110 }));
children.push(table(
  ["", "APPROVE", "PARTIAL", "REJECT", "ESCALATE"],
  [
    ["APPROVE", "12", "0", "0", "0"],
    ["PARTIAL_APPROVE", "0", "11", "0", "0"],
    ["REJECT", "0", "0", "7", "0"],
    ["ESCALATE", "0", "0", "0", "14"],
  ],
  [0.3, 0.175, 0.175, 0.175, 0.175],
));
children.push(spacer());
children.push(p("Precision, recall and F1 are 1.000 for all four classes."));

children.push(h2("6.3 Reading that honestly"));
children.push(rich([
  { t: "A perfect score on a benchmark written by the same person who wrote the rules is a measure of " },
  { t: "internal consistency", b: true },
  { t: ", not of real world accuracy. It says the implementation matches the author's reading of the policy. It says nothing about whether that reading survives contact with real claims." },
]));
children.push(p("The first run was not perfect. It scored 40 out of 44, and the four failures were instructive:"));
children.push(table(
  ["Claim", "Symptom", "Diagnosis"],
  [
    ["CLM-2006", "Team lunch disallowed INR 3,000 instead of 1,000", "System bug. The daily meal ceiling was applied to a local claim, but TE-02.3 scopes it to outstation trips, and an internal team meal is governed by the per attendee cap in TE-03.4 instead. The same rupee was disallowed twice under two clauses."],
    ["CLM-2007", "Escalated instead of partially approving", "System bug. A missing vendor GSTIN forced human review on a line already disallowed in full, so the query could not change anything. Fixed by retiring moot escalations."],
    ["CLM-4008, CLM-4013", "Approved instead of escalating", "System bug. Two escalation triggers were never wired to the decision: an entertainment pre approval breach set no human review flag, and the self approval check ran after the outcome had already been computed."],
    ["CLM-4014", "Rejected instead of escalating", "Label error. TE-03.3 is unconditional: an unnamed attendee makes the claim non reimbursable. The system was right and the label was wrong."],
  ],
  [0.17, 0.27, 0.56],
));
children.push(spacer());
children.push(p("The label was corrected and the correction is recorded in the dataset note rather than quietly applied, because changing a label after seeing a result is the easiest way to produce a meaningless benchmark, and the correction only stands because the policy text is explicit."));

children.push(h2("6.4 The stress test is the better evidence"));
children.push(rich([
  { t: "Because the labelled benchmark is self authored, a property based test was added that asserts invariants which must hold for " },
  { t: "any", b: true },
  { t: " input, rather than expected answers for particular inputs." },
]));
children.push(table(
  ["Invariant", "Holds"],
  [
    ["I1  Determinism, the same claim twice gives the same answer", "yes"],
    ["I2  Monotonicity, raising an amount never lowers the disallowance", "yes"],
    ["I3  Boundary exactness, exactly at a ceiling is inside it; one rupee over is caught", "yes"],
    ["I4  Conservation, payable plus disallowed always equals claimed", "yes"],
    ["I5  An integrity flag never produces an automatic rejection", "yes"],
    ["I6  Vendor case and spacing do not defeat duplicate detection", "yes, after a fix"],
    ["I7  Every rupee disallowed cites a clause", "yes"],
    ["Fuzz, 300 randomly perturbed claims", "no crash, no impossible total"],
  ],
  [0.82, 0.18],
));
children.push(spacer());
children.push(p("I6 failed on its first run, and the defect was real. Vendor names were compared with a bare lowercase strip, so two spellings of the same merchant were treated as different vendors and a duplicate passed straight through. A control defeated by a space is not a control. The fix was a normalisation function that strips punctuation and corporate suffixes, and it is now unit tested. The label based benchmark would never have found it, because the benchmark only contains vendor names spelled consistently. That is the argument for property based testing over example based testing in a control environment."));

// --- 7 -------------------------------------------------------------------
children.push(h1("7. Limitations"));
children.push(rich([{ t: "The receipts are structured records, not images. ", b: true }, { t: "A production system needs OCR and document understanding over the actual PDF or photograph, and every field read here would in reality be an extraction with its own error rate. That error rate would dominate everything measured in section 6." }]));
children.push(rich([{ t: "The benchmark is synthetic and self authored. ", b: true }, { t: "44 claims written by the author. Real claims are messier in ways that are hard to imagine in advance." }]));
children.push(rich([{ t: "Integrity detection is rule shaped. ", b: true }, { t: "It catches the patterns it was told about. Genuine fraud detection needs labelled historical outcomes and a model trained on them, which no student project has access to." }]));
children.push(rich([{ t: "The policy is fictional. ", b: true }, { t: "A real deployment begins with a policy that contradicts itself in three places, which is a discovery problem before it is an engineering one. The system does surface one such gap: TE-02.3 sets no ceiling for a meal in the city of posting, so the Policy Expert raises an advisory flagging the gap for the policy owner rather than inventing a limit." }]));
children.push(rich([{ t: "Model variance is unmeasured on the default path. ", b: true }, { t: "Offline is deterministic by construction. Running with a live model would introduce variance in free text classification, and that variance should be measured across repeated runs before anyone trusts it." }]));

// --- 8 -------------------------------------------------------------------
children.push(h1("8. What would come next"));
children.push(rich([{ t: "Document understanding. ", b: true }, { t: "Receipt images to structured lines, with a confidence score per field, and an explicit rule that a low confidence extraction escalates rather than guesses." }]));
children.push(rich([{ t: "Measure the model path. ", b: true }, { t: "Run the full benchmark ten times against a local model and report the variance in the free text classification, which is the only place a model can change an outcome." }]));
children.push(rich([{ t: "Learn from overrides. ", b: true }, { t: "The front end already captures every human override with a written reason. Those are the most valuable labels in the system, and after a few thousand claims they would say far more about where the rules are wrong than any synthetic benchmark." }]));
children.push(rich([{ t: "Policy versioning. ", b: true }, { t: "Clause level diffs between policy versions, so a claim is always adjudicated against the policy in force on its expense date rather than the policy in force today." }]));

// --- 9 -------------------------------------------------------------------
children.push(h1("9. Running it"));
children.push(table(
  ["Command", "What it does"],
  [
    ["python run_review.py --claim CLM-4015", "One claim, reviewed in full detail"],
    ["python -m eval.evaluate", "The benchmark in section 6"],
    ["python -m eval.stress_test", "The invariants in section 6.4"],
    ["python tests/test_tools.py", "20 unit tests"],
    ["streamlit run app/streamlit_app.py", "The reviewer front end"],
    ["jupyter notebook notebooks/demo.ipynb", "The walkthrough"],
  ],
  [0.52, 0.48],
));
children.push(spacer());
children.push(p("Nothing above needs an API key. To run with a model, copy .env.example to .env and set LLM_PROVIDER to ollama, gemini or openai."));

children.push(rule());

// --- appendix ------------------------------------------------------------
children.push(h1("Appendix: policy clauses implemented"));
children.push(table(
  ["Section", "Covers", "Implemented in"],
  [
    ["TE-02", "Grade entitlement matrix, hotel and meal ceilings, travel class", "check_hotel_ceiling, check_meal_ceilings, check_travel_class"],
    ["TE-03", "Meals, alcohol, entertainment, team meals", "check_alcohol, check_entertainment, check_team_meal"],
    ["TE-04", "Conveyance, commute window, mileage rates, cab thresholds", "check_cab_rules, check_mileage, check_fuel_with_mileage"],
    ["TE-05", "Evidence, tax invoices, legibility, missing receipt declarations", "check_evidence"],
    ["TE-06", "GSTIN validity, section 17(5) blocked credit, cross state supply", "validate_gstin, check_gst"],
    ["TE-07", "Submission timelines, 30 and 60 day boundaries", "check_timeliness"],
    ["TE-08", "Approval authority ladder, self approval prohibition", "route_approval"],
    ["TE-09", "Duplicates, splits, round amounts, leave dates, velocity", "detect_duplicates, detect_splits, detect_round_amounts"],
    ["TE-10", "Non reimbursable list, laundry rules", "check_non_reimbursable_text, check_laundry"],
    ["TE-11", "Outcome definitions and precedence", "AdjudicatorAgent"],
  ],
  [0.12, 0.46, 0.42],
));

// ----------------------------------------------------------------- build --

const doc = new Document({
  creator: AUTHOR,
  title: "Domain Expert AI Agents for Travel and Expense Adjudication",
  description: `Agentic AI individual assignment, ${AUTHOR}, Roll No. ${ROLL}`,
  styles: {
    default: {
      document: { run: { font: "Times New Roman", size: 23, color: INK } },
    },
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 420, hanging: 220 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 760, hanging: 220 } } } },
        ],
      },
      {
        reference: "numbers",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 420, hanging: 220 } } } },
        ],
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840, orientation: PageOrientation.PORTRAIT },
        margin: {
          top: convertInchesToTwip(1), bottom: convertInchesToTwip(1),
          left: convertInchesToTwip(1), right: convertInchesToTwip(1),
        },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(OUT, buf);
  console.log(`written ${OUT} (${(buf.length / 1024).toFixed(0)} KB)`);
});
