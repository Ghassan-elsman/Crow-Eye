# Narrative Map — implementation overview

The **Narrative Map** is the Eye's persistent working memory: the verdict it is
driving toward, the **narratives** (themes/claims) it is proving, and the
evidence under each. It is shown to the investigator as an editable map and is
injected into the Eye's context every turn. Every change — Eye or human — is
written to compliance.

This overview is the analysis of what already exists, what we edit, and how
compliance wraps it. Logic is settled; this is the build picture.

---

## 1. The logic (settled)

- A **big question** sets the **verdict** target.
- The Eye **plans the themes first** (top-down). Each theme opens as a
  **narrative** — provisional until proven.
- Under each narrative the decomposer runs **atomic, provable sub-questions** —
  the real investigation units that drive queries.
- Evidence found drops into its narrative. End states per narrative:
  - **proven** — has evidence (kept).
  - **negative finding** — the Eye checked and found nothing; the absence is the
    result (kept, evidence-backed by the null query).
  - dropped — a theme that yielded nothing and isn't worth recording.
- **Authorship rule:** an **Eye** narrative always carries evidence (it never
  asserts the unsupported — GEP R10). Only a **human** narrative may stand
  empty: a *hypothesis* to steer the Eye, or an **absolute** stipulated fact.
- Narratives roll up to the verdict.

Narratives are **broader** than sub-questions: many atomic sub-questions /
several pieces of evidence roll up into one narrative.

---

## 2. What already exists in the Eye (we reuse, not rebuild)

The map is largely a **persistent projection of data the Eye already produces**:

| Map concept | Already produced by | Anchor |
| --- | --- | --- |
| Theme plan → narratives | `_plan_investigation()` → `{strategy, sub_questions, user_premises}` | `query_processor.py:2775`, called `:1461` |
| Narrative state (open→proven) | `checklist` items `{q, status, kind}` + `_update_checklist()` | `query_processor.py:1450, 1657` |
| Atomic sub-questions | decomposition `checklist` (kind=question) | `query_processor.py:1468` |
| Evidence under a narrative | tool results / ledger + **Living Report blocks** + semantic `db:table#rowid` | `_build_subquestion_context` `:144`, report_engine blocks |
| Reasoning trace (persisted) | `_capture_reasoning_trace()` | `query_processor.py:2452` |
| Per-claim verification | `_evaluate_gep_turn()` (GEP) | `query_processor.py:2241` |
| Provenance who/why/when | `EyeAuthorship` (created_by, reason, related_evidence) | `correlation_engine/config/eye_authorship.py` |
| Tamper-evident audit | `EvidenceSeal` hash chain + `truncation_auditor` + `_audit_event()` | `evidence_seal.py`, `query_processor.py:2577` |

So the new code is: a **store** that turns plan + checklist + evidence into a
durable narrative graph, a **context injector**, a **bridge + UI**, and the
**compliance wrapper** around edits.

---

## 3. What we edit / implement

### New: `eye/services/narrative_map_service.py`
Owns the map. Responsibilities:
- Load/save `<case>/EYE_Logs/narrative_map.json` (`{verdict, narratives[], evidence[], links[]}`).
- `ingest_plan(strategy, sub_questions)` — open provisional narratives from a
  theme plan (top-down).
- `attach_evidence(narrative_id, evidence)` / `mark_negative()` / `commit()` —
  promote provisional → proven/negative as the checklist resolves.
- `apply_edit(event)` — the single write choke point (Eye tools + human UI both
  go through here); validates GEP, stamps `EyeAuthorship`, seals to compliance.
- Serializers: `overview_block()` (Tier A) and `relevant_slice(subq, budget)` (Tier B).

### Edit: `eye/services/context_manager.py`
- Construct the service beside `case_context_manager` (`:167`).
- In `_build_system_prompt` after Case Context (`:984`), inject
  `narrative_map_service.overview_block()` — the compact memory overview.
- Add token-budget key `case_memory` (≈800).

### Edit: `eye/services/query_processor.py`
- **STAGE 4b** (`:1461`): after `_plan_investigation`, call
  `narrative_map_service.ingest_plan(...)` so the planned themes become
  provisional narratives (top-down) and are visible immediately.
- **STAGE 4c** `_build_subquestion_context` (`:144`): add a per-sub-question
  **relevant narrative slice** (`relevant_slice`) using the same keyword-overlap
  scoring it already uses for report blocks — so each sub-question sees only its
  narratives, never the whole map.
- As the `checklist` resolves (`_update_checklist`, `:1657`) and the reasoning
  trace is captured (`_capture_reasoning_trace`, `:2452`), promote provisional
  narratives to proven/negative and attach the evidence (report block ids,
  `db:table:rowid`).

### Edit: `eye/bridge/eye_bridge.py`
- `get_narrative_map()`, `commit_map_edit(json)`, signal `narrative_map_updated`.

### Edit: `eye/ui/react/src/` (UI already prototyped)
- Mount `<NarrativeMap/>` (today `EvidenceMap.tsx`; rename to NarrativeMap) at
  `App.tsx` `view==='map'` (already wired) as a tab/window.
- Hydration accepts the service JSON; base/absolute kinds, free evidence,
  right-click menu already built in the prototype.

### Seed: `eye/ui/react/src/build_evidence_map.py`
- Promote into the service as the bootstrap that turns an existing
  `eye_report_workspace.json` into a starting map for legacy cases.

---

## 4. Compliance — every change is sealed (non-negotiable)

Because the map **feeds the model's context**, the memory and its audit trail
are the same object. Every map mutation routes through
`narrative_map_service.apply_edit(event)`, which:

1. **Validates GEP** (reuse `eye_authorship.py`): **R9** reason required, **R10**
   evidence-link, **R11** eye-stamped. The R10 exemption is explicit and
   recorded: only a **human absolute** narrative may carry no evidence.
2. **Stamps `EyeAuthorship`** (`created_by` = `eye:<model>` | `investigator`,
   `reason`, `related_evidence`, timestamp).
3. **Seals** the event to `<case>/EYE_Logs/narrative_map_audit.jsonl` using the
   existing `EvidenceSeal` hash-chain (each record folds in the previous hash —
   one altered/removed row breaks the chain).
4. **Surfaces** it via `_audit_event("MAP_EDIT", …)` → `truncation_auditor`, so
   the existing **Compliance panel** (`ProtocolCompliancePanel.tsx`) shows map
   edits next to payload seals and GEP turns — no new compliance UI needed.

Audited event kinds: `CREATE`, `EDIT`, `ATTACH`/`DETACH` evidence,
`MARK_ABSOLUTE`/`MARK_BASE`, `MARK_NEGATIVE`, `NOTE`, `LINK`, `DELETE`. Eye-driven
promotions during a question (plan→provisional→proven) are audited the same way,
so the chain of custody covers the Eye's own memory writes, not just human edits.

---

## 5. Context injection — respects sub-question decomposition

Two tiers, so we never dump the whole map per sub-question:

- **Tier A (once/turn):** compact `## Case Memory` overview beside Case Context —
  one line per narrative + verdict, state badges, absolute = `(established)`,
  empty-base = `(⚠ hypothesis)`. ~800 tokens, survives truncation (Priority 1).
- **Tier B (per sub-question):** only the narratives/evidence overlapping that
  sub-question expand, inside the existing `## Per Sub-Question Context` block.

Absolute narratives always ride Tier A so the Eye builds on established facts
instead of re-deriving them.

---

## 6. Phases

1. **Read-only memory** — service loads/seeds the map; Tier A overview injected;
   `get_narrative_map()` feeds the UI. No writes.
2. **Live plan ingest** — STAGE 4b opens provisional narratives from the theme
   plan; Tier B selective slices.
3. **Sealed writes** — `commit_map_edit` + Eye promotions, all GEP-validated,
   sealed, and shown in the Compliance panel; human editing live.
4. **Auto-grow / negative findings** — promote/attach as checklist resolves;
   record dead-ends as negative findings.

---

## 7. Decisions locked vs open

**Locked:** name = Narrative Map · top-down theme planning · Eye narratives
always evidence-backed · humans may add empty/absolute narratives · two-tier
context injection · all changes sealed to compliance.

**Open:** (a) overview token budget — fixed ~800 vs % of prompt (recommend
fixed); (b) keep every checked-but-empty theme as a negative finding, or only
keep ones that matter (recommend: keep negatives only when the sub-question
explicitly sought presence/absence); (c) Phase-4 auto-grow — Eye proposes and
human confirms new **absolute** narratives, vs Eye writes directly under GEP.
