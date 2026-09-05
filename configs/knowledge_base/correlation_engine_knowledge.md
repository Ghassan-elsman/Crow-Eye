# Correlation Engine Knowledge

This sheet teaches EYE how the Crow-Eye Correlation Engine works so it
can answer investigator questions, diagnose "why didn't this match?"
problems, and decide when to author new Wings or Semantic Mappings via
the `correlation_create_wing` and `correlation_create_semantic_mapping`
tools.

When you (EYE) are asked about wings, semantic mappings, the engine,
the two engine strategies, multi-timestamp fan-out, or why a wing
returned zero matches, this is the canonical reference. Cite it
explicitly instead of guessing.

---

## The four pieces

The engine is composed of four named subsystems. Use these terms as
proper nouns when talking to the investigator:

| Term | What it is | Where it lives |
|---|---|---|
| **Feather** | A SQLite database holding one artifact's parsed evidence (Prefetch, Registry, USN, MFT, etc.). | `<case>/Correlation/feathers/*.db` |
| **Wing** | A correlation rule: which feathers to tie together, the time window, the minimum-match threshold, the anchor priority, and the scoring tiers. | `<case>/Correlation/wings/*.json` |
| **Engine** | The runtime that executes a Wing against the case's feathers. Two strategies share the same complexity: **Time-Window Scanning** and **Identity-Based**. Both run at **O(N log N)**. | `correlation_engine/engine/` |
| **Pipeline** | The orchestrator that loads feathers, runs the selected Wings via the chosen Engine, and writes results. | `correlation_engine/pipeline/` |

## How a Wing matches

A Wing tells the engine three things:

1. **Which feathers participate** — a list of feather references, each
   with a `weight` (0.0–1.0) and `tier` (1–4) for weighted scoring.
2. **The time window** — `time_window_minutes` (default 180 = 3 hours).
   Records from different feathers must fall within one window to be
   correlated together.
3. **The match threshold** — `minimum_matches` (default 1). How many
   feathers must contribute a record in the same window before the
   engine emits a correlation match.

Additionally:

- `anchor_priority` — ordered list of artifact types. The engine
  prefers anchors from higher-priority artifacts when multiple are
  available in a window.
- `semantic_rules` — wing-scoped semantic mappings that fire alongside
  the wing's normal output.
- `scoring.thresholds` — confidence bands: `low / medium / high /
  critical` mapped to score ranges (e.g. `{"high": 0.7, "critical":
  0.9}`).

If the analyst asks "why didn't my wing match?", the answer is almost
always one of:

- **`minimum_matches` too high** for the case data
- **`time_window_minutes` too narrow** — events that should correlate
  fell into different windows
- **An identity field is missing** — no anchor extracted; the per-window
  diagnostics will show this as `no_identity > 0`
- **The wing requires a feather the case doesn't have** — check the
  feather paths in the Wing JSON

## How a Semantic Mapping works

A Semantic Mapping turns a *technical value* (like EventID 4624 or
`chrome.exe`) into a *semantic value* the analyst reads (like
"Successful Logon" or "Web Browser Execution").

Two flavors:

- **Mapping** — single source + field + value/pattern → semantic value.
  Use when one field tells the whole story.
- **Rule** — multi-condition AND/OR logic across feathers. Use when
  the meaning only emerges from a combination (e.g. "USB inserted"
  needs both a USBDevices row and a SystemLogs row in the same window).

Scope: `global` (applies everywhere), `wing` (only when this Wing runs),
or `pipeline` (only in a specific Pipeline). Default is `global`.

`mapping_source` records who created it:
- `"built-in"` — shipped with the engine
- `"global"`, `"wing"`, `"rule"` — added by the analyst via the GUI
- `"eye"` — created by you (EYE) via `correlation_create_semantic_mapping`

Only items with `mapping_source="eye"` are editable by EYE.

## The two engines — same complexity

Both engines are **O(N log N)**. Pick by the *question*, not the
dataset size:

- **Time-Window Scanning Engine (TWSE)** — scans the timeline in fixed
  windows, gathers records via indexed timestamp queries, groups them
  by identity inside each window. Best for "what happened during this
  hour?" investigations.

- **Identity-Based Engine (IBCE)** — groups records by identity first,
  then creates temporal anchors within each identity's bucket. Best
  for "show me everything this app/file did across the timeline."

The old documentation in some places still describes the time-based
engine as O(N²). That was the historical anchor-based algorithm, which
was replaced. The current production engine is O(N log N).

## Multi-timestamp fan-out

Some artifacts store **multiple timestamps per row** in a JSON column.
Prefetch's `run_times` is the canonical example — up to 8 historical
execution times per row. Earlier versions only correlated the most
recent one (`last_executed`); 0.11.0 added fan-out, so every timestamp
in the list becomes its own virtual correlation event.

Per-feather declaration lives in
`correlation_engine/config/feather_schemas.json` under
`"multi_timestamp_json_columns"`.

If the analyst says "my Prefetch wing only sees the latest execution,
not the older ones" — the fan-out is the answer. Verify the table is
declared in `feather_schemas.json`.

## Per-window diagnostics

Every time the engine processes a window, it emits an INFO log line
with these fields. This is the canonical "did we lose any evidence?"
signal — read it before anything else when matches are missing.

```
[Time-Window Engine] window=W records_in=N no_identity=N
    parse_cache_hits=N identities=N below_threshold=N
    skipped=N low_confidence_emitted=N matches_emitted=N
    min_feathers=N
```

Field-by-field:

- **`records_in`** — total records the engine pulled into this window.
- **`no_identity`** — records with no extractable identity. If this is
  high, your parser is writing a column the standard fields registry
  doesn't recognize — add the synonym to
  `config/standard_fields/file_paths.json` (filename / path categories).
- **`parse_cache_hits`** — records whose normalization was already
  cached. Pure perf signal; doesn't affect matches.
- **`identities`** — unique normalized identity groups formed in this
  window.
- **`below_threshold`** — identity groups that failed `minimum_matches`.
  If this is high, either lower `minimum_matches` for the wing, widen
  `time_window_minutes`, or enable `low_confidence_review_mode` on the
  scan config to surface them as Low matches.
- **`skipped`** — records dropped entirely (truly invalid).
- **`low_confidence_emitted`** — sub-threshold matches surfaced for
  analyst review (only when `low_confidence_review_mode=True`).
- **`matches_emitted`** — final emitted matches.
- **`min_feathers`** — the threshold used for this run (after applying
  any `min_feathers_override`).

The same data is exposed on
`TimeWindowScanningEngine._last_window_correlation_stats` for
programmatic inspection by other engines/tools.

## The built-in Wings, and what each one asks

Eleven ship by default. Check this list before authoring a new one - the
overlap is usually with a wing that already exists.

| Wing | The question it answers |
|---|---|
| Execution Proof | What ran on this machine, corroborated across Prefetch, ShimCache, AmCache, LNK, jump lists and SRUM |
| Execution Without Trace | What ran but left no Prefetch entry, and whether timestamps were tampered with |
| Persistence Mechanisms | What will run again - Run keys, services, scheduled tasks, Active Setup, Safe Mode, App Paths |
| Account Logon | Who authenticated, and what they did in that session |
| Brute Force / Spray | Repeated failed authentication |
| Lateral Movement | How this host was reached, or reached others |
| USB / Removable Media | What was plugged in, and what was taken |
| User Activity | Where the user went and what they opened |
| Anti-Forensics | What was cleared, wiped or hidden |
| Ransomware Mass Encryption | A mass-rewrite burst |
| **Security Control Tampering** | **Were the defences on at the time?** Mark-of-the-Web handling, VBS and Credential Guard, SMB signing, the zone map, fast startup, event log channels |

**The persistence correction.** `AutoStartPrograms` lists what the Run keys
hold; Windows records separately, in `StartupApproved`, whether each of those
is actually allowed to launch. The rows carry `startup_state` and
`disabled_at`, and the Persistence wing has a rule on each state:

* `pers_autostart_disabled` - the entry does **not** run at logon. On the
  reference system six of ten Run entries were disabled, two of them since
  February, and every one of them had been reported as live persistence.
* `pers_autostart_enabled` - Windows confirms it does run.
* A row whose `startup_state` is `unknown` matches **neither**. Most autostart
  locations have no StartupApproved equivalent at all, and silence is not
  consent - never report an `unknown` row as enabled.

This is an annotation, not a score penalty: `WeightedScoringEngine` clamps
negative weights to zero, so a disabled entry is labelled rather than
discounted. When summarising persistence, say which entries actually run.

## When you (EYE) should author a Wing

Call `correlation_create_wing` when **all** of these are true:

1. The analyst either explicitly asked for a new wing, OR you've
   spotted a correlation pattern that recurs ≥ 3 times in the case
   and would speed future analysis.
2. You can name the **forensic claim** the wing supports
   (`proves` field — e.g. "lateral movement", "data staging",
   "credential theft").
3. You can point to **concrete evidence rows** that motivated it (the
   `related_evidence` array — at least one
   `database:table:rowid` reference). The handler enforces this as
   GEP-2 (Evidence-Link); without it your call is rejected.
4. The pattern isn't already covered by one of the built-in wings
   (Execution Proof, User Activity, etc.). Check first.

**Do not** call the tool to "explore" or "try" — every wing is a
durable artifact in the case directory. If you're unsure, ask the
analyst.

## When you (EYE) should author a Semantic Mapping

Call `correlation_create_semantic_mapping` when:

1. You see a recurring technical value (EventID, file pattern, registry
   path) that has clear forensic significance, AND
2. It isn't already mapped (check the existing semantic outputs in the
   correlation results), AND
3. You can name the human meaning succinctly (e.g.
   "Suspicious svchost.exe spawn", "RDP brute-force attempt"), AND
4. You can cite the rows that motivated it.

Use `mapping_type="rule"` (not "mapping") when the meaning only emerges
from multiple feathers correlating — e.g. "Persistent USB device" needs
both a USBDevices row AND a Registry Run key row.

## The Ghassan Elsman Protocol (GEP) — write side

Three GEP rules govern every authoring call you make. The handlers
enforce them; if you violate any, your tool call fails.

- **Rule 9 — Reason-Required.** The `reason` parameter must be a
  non-empty forensic justification. "Because the user asked" is not a
  reason. "Recurring 4624 + svchost.exe at 03:00 across three days
  suggests automated lateral movement" is.
- **Rule 10 — Evidence-Link.** `related_evidence` must be a non-empty
  array of `database:table:rowid` references. The handler attempts to
  resolve each one. Unresolved refs (DB locked, row deleted, schema
  drift) trigger a soft warning — the wing/mapping is still persisted
  with the failed refs recorded in
  `eye_authorship.unresolved_evidence_refs`. Empty `related_evidence`
  is a hard block.
- **Rule 11 — Eye-Stamped.** Every artifact you create carries an
  `eye_authorship` block with your model name, the time, the reason,
  the evidence refs, and a per-rule compliance record. This is
  populated by the handler automatically — you do not need to supply
  it.

## Audit trail

Every Wing or Mapping you author is recorded in the case audit trail.
Analysts can filter the wings catalog for "EYE-authored" items, view
the full `EyeAuthorship` block in the Compliance Panel, and roll back
by deleting the file (paths returned to you in the tool result).

EYE **never** edits a Wing or Mapping authored by someone else.
`correlation_edit_wing` and `correlation_edit_semantic_mapping` refuse
to operate on anything whose `eye_authorship.created_by` does not
start with `"eye"`. If the analyst asks you to modify a built-in wing,
suggest the change they should make manually in the GUI instead.
