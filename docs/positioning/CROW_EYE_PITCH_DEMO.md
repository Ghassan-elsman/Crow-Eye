# Crow-Eye — One-Page Pitch & Demo Script

*For buyers, reviewers, and partners. Companion to `CROW_EYE_COMPETITIVE_ANALYSIS.md`.*

---

## The one line

> **We don't detect known bad. We reconstruct everything — and let the truth, not a reputation
> score, decide.**

Detection tools ask *"is this malicious?"* and clear everything that looks legitimate — so a kill
chain built from legitimate tools is invisible to them. Crow-Eye asks *"what happened?"*, correlates
**all** activity across the artifacts that survive log-clearing, trusts nothing, and leaves
interpretation to the semantic layer and the investigator — with every step sealed.

---

## The loop (this is the product — not any single box)

```
                          ┌─────────────────────────────────────────────┐
                          │              GEP / SEALING SPINE             │
                          │   (every step attributable + court-grade)    │
                          └─────────────────────────────────────────────┘
   ▲                                                                          
   │ 1. CORRELATION ENGINE      reconstruct ALL activity (logical, artifact-deep,
   │    trust nothing)          trust-nothing)        →  PROBLEM: a mountain of data
   │                                                                          
   │ 2. TIMELINE                identity-threaded, full-detail, court-traceable
   │    VISUALIZATION                                  →  fixes: "flat firehose"
   │                                                                          
   │ 3. SEMANTIC MAPPING        deferred, governed meaning (legit tools can't hide)
   │                                                  →  fixes: "raw data has no meaning"
   │                                                                          
   │ 4. DYNAMIC LINKING         community / open-source linking (separate layer)
   │                                                  →  fixes: "closed vendor knowledge"
   │                                                                          
   │ 5. THE EYE (AI)            analyzes the huge correlated set under GEP
   │                                                  →  fixes: "no human can read it all"
   │                                                                          
   │ 6. NARRATIVE MAP           sealed Verdict → Narrative → Evidence
   │                                                  →  fixes: "you get lost in the process"
   │                                                                          
   └─► VERDICT                  defensible, sealed, reproducible
```

**Each layer fixes the problem the previous layer creates.** Incumbents own one slice each
(SIEM/EDR = detection, Plaso/Timesketch = timeline, Sigma = rules, i2/Maltego = link analysis,
UEBA = scoring). **None of them spans the loop.**

---

## The 60-second demo (walk ONE case through the whole loop)

The differentiation is invisible until someone connects the layers — so *show the loop, not a box.*

1. **Correlate everything.** Ingest the case; the engine correlates all activity — no "is it bad?"
   filter. (Show the volume — then tame it in the next step.)
2. **The legit tool surfaces.** Open the identity timeline for `powershell.exe` (or PsExec). Every
   competitor called it legit. Here its **full activity thread** appears — Prefetch → SRUM →
   Registry → LNK → USN, same identity, one temporal anchor — with full artifact detail inline.
3. **Semantic mapping flags the pattern.** The boolean rule fires on the *combination* (multi-
   indicator gating), not on any single "bad" object — meaning assigned *after* the evidence, not
   before.
4. **The Eye analyzes the pile.** Ask the Eye to explain the activity; it navigates the correlated
   set no human could read, under GEP, and answers with sourced evidence.
5. **The Narrative Map shows the sealed chain.** Verdict → Narrative → Evidence, hash-chained and
   attributable — the court-defensible story of what happened, end to end.

**Punchline:** "An attacker used only legitimate tools and cleared the logs. Every detection product
said 'clean.' Crow-Eye reconstructed exactly what happened — and sealed it for court."

---

## Three objections + crisp answers

**"This produces way more than an alert — it's a lot of data."**
Yes — because we reconstruct, we don't filter. The identity-threaded timeline + the Eye are how a
human navigates it. This is the tool you run when EDR *missed* it, or when you must *prove* what
happened. Different job from real-time alerting.

**"Sigma / Splunk already do logical correlation."**
True — they're rule-based too. The difference isn't logic; it's **cross-artifact identity
resolution**, **sealed and community-authorable rules**, and **verdict integration**. Sigma
correlates events in one log schema; it can't tell you this Prefetch row, this SRUM row, and this
MFT row are the same executable's story — and its rules carry no chain of custody.

**"EDR already catches living-off-the-land."**
It catches *some* — whatever trips a behavioral rule. Everything else is discarded or cleared, so a
**complete, court-defensible reconstruction is impossible by design.** We retain and correlate
everything, then let evidence — not a score — decide.

---

## Who this is for

IR firms, defense-side / court-facing examiners, forensic labs, training programs, and
privacy / air-gapped investigations — anyone whose pain is **kill-chains from legitimate tools,
anti-forensics / cleared logs, or having to prove what happened.**
