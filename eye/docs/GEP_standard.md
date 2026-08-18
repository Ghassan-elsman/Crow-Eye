# The Ghassan Elsman Protocol (GEP)
### A Standard for AI-Assisted Digital Forensics

**Status:** Draft standard · **Author:** Ghassan Elsman · **Version:** 1.1

> **v1.1** — GEP-6 (Completeness) clarified to require **coverage disclosure**: a conforming
> system must disclose which sources it consulted versus those available, and whether any result
> was a sample rather than the full set.

---

## Purpose & scope
The **Ghassan Elsman Protocol (GEP)** defines *how an AI system should be used in digital
forensics and incident response (DFIR)*. It is **vendor-neutral and tool-agnostic**: it applies
to any AI — cloud model, local model, agent, or assistant — that reads, reasons over, or reports
on digital evidence. It is **not** a product specification; it is a set of principles a conforming
implementation must uphold so that AI-assisted findings remain **truthful, traceable to source
records, and backed by an auditable, tamper-evident chain**, and so that the human investigator stays in control.

The GEP governs the *use of AI*, not the artifacts themselves. It says nothing about which
operating system, file system, or tool is analyzed — only about how an AI must behave when it does.

A system "conforms to the GEP" when it can demonstrably satisfy every principle below. Each
principle states the rule, why it matters, what compliance looks like, and how to verify it.

---

## The principles

### GEP-1 — Evidence Primacy
**Rule.** Every conclusion derives **only** from artifacts the AI actually examined. The AI must
never guess, assume, or fabricate. Where evidence is absent, that absence is reported as a fact —
it is not filled in by inference.
**Why.** Forensics is a search for ground truth; a confident fabrication is worse than "unknown."
**Compliance.** Answers contain no claim that is not backed by an examined artifact; missing data
is stated plainly.
**Verify.** Trace each assertion back to a source; un-sourced assertions are violations.

### GEP-2 — Traceability (Evidence-Link)
**Rule.** Every factual statement is linked to a **specific source record** — e.g.
`database:table:row`, a file path + offset, an event record id, or a content hash.
**Why.** A finding that cannot be located again cannot be reviewed, reproduced, or challenged.
**Compliance.** Each fact carries (or can produce on demand) its precise provenance handle.
**Verify.** Follow any cited handle and recover the exact underlying record.

### GEP-3 — Specificity & Chronology
**Rule.** Findings state **exact** UTC timestamps, identifiers (users, hosts, PIDs, SIDs), and
full paths, and are organized **chronologically**.
**Why.** Vague or relative times destroy timelines; precision is what makes a sequence defensible.
**Compliance.** No "recently / a while ago"; concrete values, ordered in time.
**Verify.** Every event has an absolute timestamp and a determinable order.

### GEP-4 — Cross-Corroboration
**Rule.** Conclusions rest on **multiple corroborating sources** wherever possible. Corroboration,
silence, and **conflict** between sources are all reported; a single-source claim is flagged as such.
**Why.** Independent artifacts confirming the same fact raise confidence; conflicts reveal tampering
or gaps.
**Compliance.** Important conclusions cite ≥2 sources or explicitly note they are single-source.
**Verify.** For a key finding, confirm the supporting sources and that conflicts were surfaced.

### GEP-5 — Premise Verification (No Deference)
**Rule.** Claims and hypotheses supplied by the human (or by other tools) are treated as
**hypotheses to test**, not facts. The AI proves or disproves them against artifacts and states an
explicit verdict; it never simply defers to an assertion.
**Why.** An assistant that agrees with a wrong premise launders error into "evidence."
**Compliance.** Asserted premises receive a CONFIRMED / REFUTED / INCONCLUSIVE verdict with backing.
**Verify.** Feed a false premise; a conforming system refutes it with contradicting evidence.

### GEP-6 — Completeness (No Silent Omission)
**Rule.** Evidence is **never silently dropped, truncated, or summarized away**. When a dataset is
too large to examine in one pass, the system discloses this and handles it (e.g. analyzes it in
segments) — it does not hide the gap or present a sample as the whole. The system also discloses
its **coverage**: which sources it consulted versus those available, and whether any result was a
**sample** rather than the full set.
**Why.** Silent truncation produces conclusions that look complete but are not — the most dangerous
failure mode for AI in forensics. A sample presented as the whole, or relevant sources left
unexamined without saying so, are the same failure in a different form.
**Compliance.** Any reduction of what the AI saw is disclosed and recorded; large data is processed
in full or explicitly bounded. Each answer surfaces a coverage statement — consulted vs. available
sources, and sample-vs-full — so a reviewer can see exactly what was and was not examined.
**Verify.** Inspect the record for any unreported reduction between the source data and what was
analyzed, and confirm the coverage statement: that the sources said to be consulted were, and that
any sampled result is flagged (not presented as complete).

### GEP-7 — Integrity & Non-Repudiation (Chain of Custody)
**Rule.** The AI **never modifies evidence**. **Exactly** what it analyzed and **every action** it
took are recorded **tamper-evidently** (e.g. hash-chained) and are **reproducible/provable** after
the fact.
**Why.** An auditable, tamper-evident chain requires proving what the model saw and did, and that
the record was not altered.
**Compliance.** Read-only access to evidence; an append-only, tamper-evident log of inputs + actions.
**Verify.** Re-compute the integrity chain; any break or missing entry is detectable.

### GEP-8 — Transparency & Explainability
**Rule.** The AI's **reasoning, the tools it used, and the data it saw** are visible and auditable
by the investigator — during and after the analysis.
**Why.** A black-box conclusion cannot be trusted, reviewed, or defended.
**Compliance.** Tool calls, retrieved data, and the reasoning trail are surfaced (live and logged).
**Verify.** For any answer, reconstruct which tools ran and which data informed it.

### GEP-9 — Human Authority (Assistant, Not Replacement)
**Rule.** The AI **augments** the investigator, who remains the decision-maker. Significant or
durable actions are **attributable** (who/what/why), **justified**, and subject to **human
verification**.
**Why.** Accountability and judgment must stay with a qualified human; AI is a force-multiplier,
not an authority.
**Compliance.** Durable/consequential actions carry an author + reason and are reviewable;
nothing irreversible happens without a path to human oversight.
**Verify.** Each durable artifact shows its author and justification and can be rolled back/reviewed.

### GEP-10 — Defensibility
**Rule.** Output is **objective, precise**, and structured for independent legal or corporate
review — neutral language, standard terminology, clear exhibits.
**Why.** Findings often end up in legal or disciplinary proceedings; tone and structure matter.
**Compliance.** No editorializing; professional, structured reporting suitable for review.
**Verify.** A reviewer unfamiliar with the case can follow the report and its evidence.

---

## Conformance
An implementation is **GEP-conforming** if it upholds GEP-1 … GEP-10 and can **demonstrate** each
(via its logs, its evidence-integrity record, and its surfaced reasoning). Partial conformance
should be declared per-principle.

## Appendix — Reference implementation
**Crow-Eye's "Eye"** is the reference implementation of the GEP. How each principle is realized in
the Eye (read-only DB access, evidence sealing + hash-chained IDs, no-silent-truncation with
map-reduce, premise verification, per-turn compliance evaluation, human-in-the-loop authorship,
etc.) is documented in `eye_architecture.md` §5, "How the Eye implements the GEP." The Eye's own
**Operating Rules** (its system-prompt behavior and tooling) are *how it achieves answers*; they
are distinct from — and exist to **uphold** — the GEP principles defined here.
