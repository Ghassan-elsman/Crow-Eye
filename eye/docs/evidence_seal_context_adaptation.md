# Evidence Seal & Context Adaptation — Chain of Custody for What the AI Saw

This document describes how the **Eye** AI assistant routes prompts to a model
backend, how it **adapts** an outgoing payload to fit a model's context window,
and how every byte it drops is captured — the **real content and its offsets**,
not just hashes — into an auditable, tamper-evident **Evidence Seal** and surfaced in the
**Compliance UI**.

## Why this exists

When a payload (system prompt + history + tool results + user message) exceeds
the model's usable context window, the Eye must shrink it. The forensic
requirement is that this is never silent: for every reduction we must be able to
prove, later and to an adversary, **exactly which bytes the model processed and
which were dropped**, where those bytes came from, and that the record has not
been tampered with.

## Routing to the backend

`eye/services/model_router.py::ModelRouter` is the single dispatch point. Based
on the active profile it routes `generate()` to one of:

- **Local CLI backends** (`GenericCLIBackend`) — e.g. ollama / vLLM CLIs.
- **Local server backends** (`OllamaBackend`, `LMStudioBackend`) — REST APIs.
- **Cloud API backends** (`OpenAIBackend`, `AnthropicBackend`, `GeminiBackend`).

All implement `eye/backends/base.py::LLMBackend.generate(system_prompt,
user_message, tools, history)`. These map to Eye's three deployment modes
(Cloud / Offline Server / CLI `eye-agent`).

## Sizing the window: where `max_total_tokens` comes from

The usable window is derived from the **active backend model's real context
window**, not a flat default. At `ContextManager` init (and on every model
switch) `_resolve_context_window()` sets `max_total_tokens`:

The source is the **backend wherever it can report its real window**, with a
static fallback. `_resolve_context_window` resolves in this order:

1. **Live backend introspection** — `ModelRouter.get_context_window()` →
   `LLMBackend.get_context_window()`. Gemini returns its `input_token_limit`;
   Ollama reads `*.context_length` from `/api/show`; LM Studio reads
   `loaded/max_context_length` from `/api/v0/models`. Anthropic / OpenAI / CLI
   return `None` (their APIs don't expose it). The model's **full** window is
   used; no safety cap (the 10% output reserve is taken downstream in
   `guarded_generate`).
2. **Static registry** — `eye/services/context_window_registry.py`, a no-network
   name→window table, covers the non-reporting cloud APIs (Claude ≈ 200K,
   GPT-4o ≈ 128K, ...).
3. **Fallback** — the configured `context_window.max_total_tokens` (default 64K)
   for unknown models.

**Local servers** additionally keep being sized **downward** at call time by the
`n_ctx:` error probe in `query_processor.py` — so an introspected "trained"
window that exceeds how the model was actually loaded is still corrected.

Set `context_window.lock_max_total_tokens: true` to pin the configured value and
disable auto-resolution. This is what lets the Eye refuse an over-context payload
on a tiny local model yet read a 34K evidence core on a 200K cloud model without
any config change.

The per-component **`token_budget`** sub-allocations (conversation history /
system prompt / tool results / RAG) scale with the resolved window too, via
`_scale_token_budget()`: a ~10% response reserve is held back, then the
remainder is split on fixed forensic proportions (history 45% · system prompt
22% · tool results 22% · RAG 11%) — history and tool results get the most
because they carry the evidence. So on a 200K model history alone can hold ~81K
tokens instead of the old fixed 8K. An explicit `context_window.token_budget` in
config is honored verbatim and disables this scaling. The budget is recomputed on
every model switch.

## Context adaptation: the `guarded_generate` ladder

Every model call goes through `eye/services/query_processor.py::guarded_generate`,
which is the single choke point. It applies a strict ladder:

1. **SELF-HEAL — summarize.** If the assembled payload exceeds `usable`
   (`max_total_tokens` minus a 10% output reserve), non-protected messages are
   collapsed into one summary. Protected = `pinned`, `preserve_evidence`,
   `is_tool_result`, `is_summary`.
2. **SELF-HEAL — drop.** If still too large, the oldest non-protected messages
   are dropped one at a time until it fits.
3. **FAIL HARD.** If the irreducible evidence core still overflows, the query is
   **refused** (`ContextOverflowError`) and a `REFUSED_OVERFLOW` event is logged.
   Evidence is never silently truncated. The refused over-limit payload is still
   **sealed** before raising, flagged `sent_to_model: false` and carrying the
   self-heal `cut_details`, so the Compliance panels record what the Eye refused
   to send (and the cuts that occurred) instead of nothing — a refused, shrunk
   turn would otherwise leave the seal log empty.
4. **SEAL** the exact (possibly slimmed) payload (`sent_to_model: true`), then
   call the model.

A separate path caps oversized **tool output** in memory before it enters
history (`TRUNCATED_TOOL_OUTPUT`), keeping the kept head and recording the
dropped tail.

`guarded_generate`'s self-heal does not mutate the persistent on-disk history —
it slims only the *outgoing* payload, as a per-call safety net.

Separately, **`HistoryManager.manage_history`** *does* compact the persistent
on-disk history, but only when it approaches the **full usable window**
(`ContextManager.usable_context_tokens()` — the same value `guarded_generate`
gates on, so the two layers agree). When it compacts, evidence-flagged and
`pinned` messages are preserved verbatim and every summarized message is recorded
in the audit trail as a `SUMMARIZED` event (with its hash + dropped content), so
the persistent compaction is itself provable and never silent. The append-only
records that constitute the evidence of custody — the payload seal chain and the
truncation audit log — are never rewritten.

## The `cut_detail` record

All three cut sites build one canonical record via
`EvidenceSeal.build_cut_detail(...)` so the schema is identical everywhere:

| Field | Meaning |
|-------|---------|
| `action` | `SUMMARIZED` \| `TRUNCATED` \| `TRUNCATED_TOOL_OUTPUT` |
| `message_id`, `role`, `iteration`, `token_count` | provenance of the cut |
| `sha256` | SHA-256 of the original (pre-cut) message |
| `cut_range` | `{unit:"chars", total, processed:[0,p], dropped:[p,total]}` — the explicit byte/char range of the split within the original message |
| `cut_content` | bounded **inline preview** of the dropped bytes (`CUT_PREVIEW_CHARS`, default 4000) |
| `cut_content_len` / `cut_content_sha256` | full length + hash of the dropped bytes |
| `cut_content_sidecar` | relative path to the sidecar holding the **complete** dropped bytes (set only when the content exceeds the inline cap) |
| `processed_content` (+ `_len` / `_sha256` / `_sidecar`) | same, for the surviving bytes |
| `processed_file_offsets` / `dropped_file_offsets` | **forensic-artifact offsets** found in each portion (MFT record → computed file offset, event IDs, DB row IDs, IPs, registry/file paths, SHA-1, USN, app IDs) |

Two distinct notions of "offset" are therefore captured:

- **Cut range** — *where in the message* the split happened (kept vs dropped char ranges).
  The split type is passed explicitly (`processed_is_prefix`): the tool-output cap keeps a
  literal head slice (`processed:[0,p]`, `dropped:[p,total]`), while a summary or outright
  drop has no kept prefix (`processed:[0,0]`, whole message dropped). `total` is derived as
  `p + len(dropped)` so `dropped`'s length always equals `cut_content_len`.
- **Forensic-artifact offsets** — *what evidence handles* appear in each portion (e.g.
  `record_number 8888 → computed_file_offset 9101312`). MFT record→offset uses
  `EvidenceSeal.MFT_RECORD_SIZE` (default 1024 B), emitted as `record_size` so a verifier
  can re-derive (4096-B volumes need a different size). IPv4 markers are octet-validated.
  For content larger than `OFFSET_SCAN_MAX_CHARS`, only the head + tail are swept (markers
  cluster at the cut boundary); the full bytes remain in the sidecar for manual review.

### Redacted, verifiable artifacts

Every recorded copy describes the **redacted** artifact. `build_cut_detail` sanitizes the
texts once up front (stripping secrets like API keys), and the hashes, lengths, inline
previews, offset scans, and sidecars are all derived from that *same* redacted text. So a
verifier who recomputes the SHA-256 of a sidecar file gets exactly the recorded
`cut_content_sha256`, and `cut_content_len` matches the sidecar's byte count. (Hashing
un-redacted text while storing redacted bytes — the original bug — made the seal
unverifiable whenever redaction triggered.)

### Bounded inline + sidecar

To keep the logs readable while preserving every byte, content over
`CUT_PREVIEW_CHARS` is previewed inline and the **complete** (redacted) bytes are written
to a per-hash sidecar by `EvidenceSeal.spill_dropped_payload()`:

```
<case>/EYE_Logs/dropped_payloads/<sha256>.txt
```

`spill_dropped_payload` hashes exactly the bytes it writes and names the file after that
hash, so it is self-verifying. Sidecars are deduplicated by content hash and best-effort
(a write failure never breaks the investigation). Content at or under the cap stays fully
inline with no sidecar.

### One seal per drop

Within a single turn the model may be called several times (one per tool-loop iteration),
producing several payload seals. A tool-output cap is folded into the **first** seal after
it occurs and not re-attached to later seals (a high-water mark in `query_processor`), so
each dropped tool output is recorded exactly once across the turn; the `iteration` field
still identifies which payload it belonged to.

## The seal and its hash chain

`EvidenceSeal.seal()` appends one record per payload to
`<case>/EYE_Logs/eye_payload_seal.jsonl`. Each record folds the previous record's
hash into its own:

```
seal_hash = SHA256(prev_seal_hash + payload_sha256 + metadata_sha256)
```

`metadata_sha256` covers the phase, query, model, token count, evidence refs and
**all cut_details**, so altering or removing any record (or any dropped-byte
record) breaks the chain. `eye_bridge.get_payload_seals()` re-verifies the chain
end-to-end and reports `chain_valid`.

The sequence bump, chain link, and append are serialized by an internal lock, and
`process_query` holds `cm._lock` for the whole turn. A single case directory must have a
single `EvidenceSeal` writer — two writers on one case dir would fork the chain.

### Seal failures are never silent

If `seal()` raises, `guarded_generate` records a visible `SEAL_FAILED` event in
the audit trail and emits an error step — a chain-of-custody gap is itself made
provable rather than swallowed.

### Full sent payload (independently reproducible seals)

By default (`context_window.store_full_payload`, on) the **complete redacted
payload** the model saw — `<<SYSTEM>>` + history + `<<USER>>` + `<<TOOLS>>` — is
spilled to a per-hash sidecar `sealed_payloads/<sha>.txt` and referenced from the
seal as `payload_sidecar`. So the Compliance log alone can *reproduce* (not only
*verify*) each turn. The sidecar's content hashes to `payload_sha256`, which is
already in `seal_hash`, so it is tamper-evident with no change to the chain math;
verification re-hashes the **decompressed** plaintext.

To bound disk, the most recent `sealed_payload_recent_uncompressed` payloads
(default 10) stay plain `.txt`; older sidecars are compressed to `.txt.zst`
(zstd) or `.txt.gz` (stdlib fallback) — the recency window is rebuilt from the
seal log on startup and older payloads compacted. `eye_bridge.get_sealed_payload_full(sha)`
decompresses on demand for the Compliance panel's "View full payload" control.

## The audit trail

`eye/services/truncation_auditor.py::TruncationAuditor` mirrors every decision to
`<case>/EYE_Logs/truncation_audit.log` (and exports `audit_trail.json`). Actions:
`SUMMARIZED`, `TRUNCATED`, `PRESERVED`, `PINNED`, `UNPINNED`, `BUDGET_REDUCED`,
`REFUSED_OVERFLOW`, `SEAL_FAILED`. The metadata carries the same `cut_detail`
fields (preview, offsets, `cut_range`, sidecar ref). API keys are redacted from
both the seal and the audit log.

The audit log is **tamper-evident**, not append-only by convention: each line
ends with `chain = sha256(prev_chain + line)`, recovered across sessions, so any
edit/reorder/deletion is detectable. `TruncationAuditor.verify_chain()` checks it
end-to-end and `eye_bridge.get_truncation_events` reports `chain_valid` to the
Compliance panel (parallel to the seal chain). Events are written **through** to
disk on every `log_event` (no in-memory buffering window), so a crash cannot lose
a recorded custody event.

## File layout (`<case>/EYE_Logs/`)

```
eye_payload_seal.jsonl      hash-chained per-payload seals (incl. cut_details)
truncation_audit.log        append-only audit events
audit_trail.json            structured export of the audit log
dropped_payloads/<sha>.txt  full bytes of any cut whose preview was bounded
sealed_payloads/<sha>.txt    full sent payload per seal (older ones .txt.zst/.gz)
```

## Compliance UI

The Compliance window (`ProtocolCompliancePanel.tsx`) exposes the data through
the QWebChannel bridge:

- **Evidence Seals** — `get_payload_seals` → per-payload seals + chain validity.
- **Context Events** — `get_truncation_events` → the audit trail.
- **Processed vs Dropped Payload** (dedicated section) — `get_payload_cut_details`
  flattens every `cut_detail` across all seals. Each row shows the action, the
  `cut_range`, the `ForensicDiff` of processed-vs-dropped content with
  artifact-offset badges, and a **"Load full dropped bytes"** control that calls
  `get_dropped_payload_full(sha256)` to read the complete bytes from the sidecar
  on demand (hash-validated; traversal-proof).

## Tests

`eye/tests/test_truncation_logging.py` covers: offset extraction, the
`build_cut_detail` schema (cut_range, capped preview, sidecar creation + hash for
over-cap content, no sidecar for small content), self-heal summarize/drop
logging, tool-output capping, API-key redaction, and the `SEAL_FAILED` marker.

Run:

```
python -m unittest eye.tests.test_truncation_logging -v
```
