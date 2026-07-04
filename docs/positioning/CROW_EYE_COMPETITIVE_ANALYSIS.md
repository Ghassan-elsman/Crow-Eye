# Crow-Eye — Competitive Analysis

*How Crow-Eye's Correlation Engine and the wider platform differ from existing security and
forensics tooling. Claims about Crow-Eye are grounded in the codebase; competitor claims are
architecture-level and flagged where a live verification pass would harden them.*

---

## 1. The core thesis: reconstruction, not detection

Almost every adjacent tool is built to answer one question: **"is this bad?"** It starts from a
model of known-bad (signatures, IOCs, rules) or anomaly, evaluates each entity against it, and
**clears** everything that looks legitimate. Detection is a *trust-and-filter* model — its entire
job is to throw away the boring 99% so an analyst sees the 1%.

Crow-Eye answers a different question: **"what happened?"** It correlates **all** activity —
suspicious or not — builds the complete identity/temporal story, **trusts nothing**, and defers
meaning to the Semantic Mapping layer or the investigator.

These are not the same job done better or worse. They are **different jobs**, and the detection
model has structural blind spots the reconstruction model does not.

| | Detection (SIEM / EDR / UEBA / Sigma) | Reconstruction (Crow-Eye) |
|---|---|---|
| Question | "Is this malicious?" | "What happened?" |
| Default stance | Trust & clear what looks legit | Trust nothing; correlate all activity |
| Output | Alerts (the suspicious 1%) | Complete, navigable reconstruction |
| Meaning assigned | At ingestion, by the engine | Deferred to semantic layer + investigator |
| Primary data | Logs (deep), artifacts (overview) | Artifacts (deep) + logs |
| Defensibility | "the model scored it 0.87" | Sealed, source-traceable evidence chain |

---

## 2. What the Correlation Engine actually does (code-grounded)

The model is **structural-link-first, rules-second, score-last** — and sealed throughout.

1. **Feathers** — normalize heterogeneous artifacts (Prefetch, SRUM, MFT/USN, Registry, EVTX,
   LNK, Amcache, Shimcache…) from any source (Plaso / Autopsy / Volatility / CSV / JSON) into a
   common SQLite shape.
2. **Engines establish the link by structure, not similarity:**
   - **Identity Correlation Engine** (`correlation_engine/engine/identity_correlation_engine.py`) —
     extracts identifiers (executable, user, path, host…), clusters records that *share an identity*
     across different artifacts, builds **temporal anchors**, and classifies each row as
     **primary / secondary / supporting** evidence. The link exists because two artifacts literally
     reference the same entity.
   - **Time-Window Engine** — links records by temporal proximity within a sliding window.
3. **Semantic Rules** (`config/semantic_mapping.py` → `SemanticRule.evaluate`,
   `engine/semantic_rule_evaluator.py`) — decide *meaning* with explicit boolean logic:
   `conditions[]`, `logic_operator` AND/OR, per-feather field operators
   (`equals / contains / regex / wildcard / > / < …`), and **multi-indicator gating**
   (`_requires_multi_indicator`, `_min_indicators`) so a weak pattern can't fire on a single signal.
   Rules carry `scope` (global / wing / pipeline), `severity`, and `eye_authorship` provenance.
4. **Scoring is interpretation applied *after* the logic** — `config/centralized_score_config.py` is
   tier-weighted (tier1–4 evidence weights; low/medium/high/critical thresholds; penalties/bonuses).
   It **ranks and labels an already-established logical correlation**; it does not create one.

> **One-line model:** shared-identity / temporal **link** → boolean **rule** → tier-weighted
> **score**, all **sealed** and attributable.

---

## 3. The competitor landscape (split honestly into three camps)

Lumping competitors together is where the pitch gets risky. They are not one thing:

| Camp | Examples | How they correlate | Crow-Eye's edge |
|---|---|---|---|
| **Risk / UEBA** | Exabeam, Securonix, Darktrace, Sentinel UEBA | weighted statistical risk aggregation | **Wins outright** — their "0.87" is undefensible; Crow-Eye gives a traceable logical relationship |
| **Rule / SIEM** | Sigma (incl. `correlation`), Splunk, Elastic, Velociraptor VQL, Chainsaw | boolean rules over a **single normalized log stream** | **Not** "logic vs no-logic" — edge is cross-artifact **identity resolution** + **sealed/authorable** rules + **verdict integration** |
| **Artifact-graph** | Magnet AXIOM Connections, IBM i2, Maltego | entity/relationship graphs (i2/Maltego human-drawn; Connections auto) | relational, but **closed / not rule-authorable / not sealed / not neutral** |

> ⚠️ **Do not claim "they have no logical correlation."** Sigma/Splunk/Velociraptor are boolean and
> rule-based; a knowledgeable buyer will counter with "Sigma has done that for a decade." The
> defensible claim is the *combination* below, not "they have no logic."

---

## 4. Two structural blind spots Crow-Eye exploits

### Blind spot 1 — the legit-tool kill chain
A modern intrusion is mostly **Living-off-the-Land**: PowerShell, `rundll32`, `certutil`, `wmic`,
PsExec, RDP, scheduled tasks, signed binaries. Each is a legitimate tool. A detection engine
evaluates each one and returns **"legit"** — because in isolation it *is*. The attack lives in the
**sequence and relationships**, not in any single "bad" object.

- Detection clears each step → the chain is invisible.
- Crow-Eye never clears anything. It correlates the **activity** (same identity across Prefetch →
  SRUM → Registry → LNK → USN within a temporal anchor) and surfaces the *pattern of execution*
  regardless of whether each piece looks benign.

### Blind spot 2 — log-shallow vs artifact-deep
Competitors correlate **logs in detail, artifacts as overview.** That fails exactly when it matters:

- **Logs are attacker-controllable** — auditing can be off, never enabled, or cleared
  (`wevtutil cl`). A log-centric correlator goes blind.
- **Execution artifacts persist anyway** — Prefetch, Amcache, Shimcache, SRUM, UserAssist, LNK,
  JumpLists record that a program *ran* independent of event-log auditing. Crow-Eye's Feathers
  normalize and correlate these **deeply**, so it reconstructs execution even against anti-forensics.

Against a competent attacker who (a) uses legit tools and (b) suppresses logging, the detection
model is blind on **both** axes; artifact-deep reconstruction still sees it.

---

## 5. The timeline advantage

The canonical forensic timeline is the **super-timeline** (Plaso/log2timeline → Timesketch):
millions of **flat, thin** rows, **no identity threading**, detail-on-pivot. A haystack, not a story.

Crow-Eye's timeline (`correlation_engine/gui/timeline_widget.py`) plots full **`EvidenceRow`**
records *inside* `identity_detail_dialog.py` and `anchor_detail_dialog.py` — so it is
**identity-scoped and anchor-scoped with full artifact detail inline.** Pick an identity → see its
complete activity thread through time, every event carrying its full source record.

**This answers the volume objection.** "Correlate everything, trust nothing" risks drowning the
investigator. The identity-threaded, full-detail timeline turns the mountain into a *per-entity
story* — the human-facing surface that makes the trust-nothing philosophy usable. And because each
point is a full `EvidenceRow`, every event is **traceable to its source record** — the timeline is
court-grade, not a lossy summary.

> ⚠️ Don't say "no one connects identity in a timeline" — AXIOM has timeline + Connections. The
> precise claim: *no one threads **full artifact detail by resolved identity, neutrally across all
> activity**, in one navigable timeline that feeds a sealed verdict.*

---

## 6. The integrated loop (the actual moat)

No single feature is the moat — the **integration** is. Each layer solves the failure mode created
by the previous one:

1. **Correlation Engine** — reconstructs *all* activity, logically, artifact-deep, trusting
   nothing. → Creates a mountain of correlated data.
2. **Timeline visualization** — identity-threaded, full detail. → Makes the mountain a per-entity
   story.
3. **Semantic Mapping** — deferred, governed interpretation. → Assigns meaning without pre-judging,
   so legit-looking tools can't hide.
4. **Dynamic Linking** — *separate* community / open-source-based linking layer (kept distinct from
   the Correlation Engine's Wings/Feathers — see `feedback_dynamic_linking_vs_correlation`). → Opens
   what-links-to-what to community knowledge instead of a closed vendor model.
5. **The Eye (AI)** — analyzes the huge correlated set a human can't read, under GEP. → Solves "no
   human can analyze all of it."
6. **Narrative Map** — sealed Verdict→Narrative→Evidence working memory. → Keeps a deep,
   branching investigation oriented and provable; you don't get lost in the process.
7. **GEP / sealing** — the integrity spine through all six. → Makes the whole chain court-grade.

**Closed loop: reconstruct → visualize → interpret → extend → analyze → orient → seal.** The
incumbents each own *one slice* (SIEM/EDR = detection, Plaso = timeline, Sigma = rules, i2 = link
analysis, UEBA = scoring). None spans the loop, and none is trust-nothing reconstruction feeding an
AI navigator feeding a sealed reasoning map.

---

## 7. Honest caveats (kept in deliberately)

These survive contact with a sharp skeptic only if stated honestly:

- **Trust-nothing costs volume.** You produce the whole activity graph, not an alert — interpretation
  moves to the semantic layer + human. This is **IR / forensic reconstruction, not real-time SOC
  alerting.** Position it as "what you run when EDR missed it, or when you must prove what happened,"
  not "EDR but better."
- **Modern EDR catches *some* LOL behaviorally.** Don't say "they always see legit." Say: *they
  retain and reason over only what trips a behavioral rule; everything else is discarded or cleared,
  so a complete, court-defensible reconstruction is impossible by design.*
- **Rule engines have logic too.** The edge over Sigma/Splunk is identity resolution + sealing +
  authorability + verdict integration — not "we're logical, they're not."
- **Scale/UX is where these tools win or lose.** Full-detail, all-activity timelines are an
  engineering problem; identity/anchor *scoping* is the design choice that keeps it tractable.

---

## 8. Verdict

**Keep developing it.** The moat is real and is the *integration*, which no competitor spans. The
two decisive risks are **not capability**:

1. **Legibility** — the differentiation is invisible until someone connects the layers; people
   pattern-match Crow-Eye to "another security product." Make the loop obvious (see
   `CROW_EYE_PITCH_DEMO.md`).
2. **Demand** — find the buyer who feels the pain the loop solves: kill-chains from legit tools,
   anti-forensics / cleared logs, "prove what happened in court." Likely buyers: IR firms,
   defense-side examiners, forensic labs, training programs, privacy/air-gapped cases.

---

### Verification notes
- Crow-Eye claims trace to: `correlation_engine/engine/identity_correlation_engine.py`,
  `engine/semantic_rule_evaluator.py`, `config/semantic_mapping.py`,
  `config/centralized_score_config.py`, `gui/timeline_widget.py`,
  `gui/identity_detail_dialog.py`, `gui/anchor_detail_dialog.py`.
- Before external use, run a live check on: current **Sigma `correlation`** capabilities, and what
  **Magnet AXIOM Connections** publicly claims about identity-in-timeline — so no comparison can be
  falsified.
