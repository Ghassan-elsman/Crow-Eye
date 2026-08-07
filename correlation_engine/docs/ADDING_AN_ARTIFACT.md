# Adding a New Artifact to the Correlation Engine

This guide walks through every step needed to plug a new parser into
Crow-Eye's correlation engine so it shows up in the time-based viewer,
the identity-based viewer, and the Evidence-by-Feather summary chart
without touching any engine source code.

If you only need to know the **minimum** to make a new `.db` correlate:
go straight to steps 1 and 7. Everything else is polish that improves
diagnostics, scoring, and visual labeling.

---

## 1. Emit timestamps in the canonical format

Every Crow-Eye parser should call
`utils.time_utils.format_forensic_timestamp(dt)` to render its
timestamps. It produces `"YYYY-MM-DD HH:MM:SS"` in UTC — the format
the engine's `ResilientTimestampParser` recognizes immediately.

```python
from utils.time_utils import format_forensic_timestamp

cursor.execute(
    "INSERT INTO my_table (...) VALUES (?, ?, ?)",
    (..., format_forensic_timestamp(event_time), ...),
)
```

If you must emit a different format (legacy data source, third-party
tool), the engine still handles all of: ISO 8601 with or without `Z`,
`MM/DD/YYYY HH:MM:SS`, `YYYYMMDD`, Windows FILETIME integers, Unix
seconds/ms/μs, and timestamps with trailing parenthetical annotations.
But canonical is faster and unambiguous.

---

## 2. (Optional) Add timestamp column synonyms

If your table has a timestamp column whose name isn't already in
`config/standard_fields/timestamps.json`, add it under the right
category (`timestamp`, `createdtime`, `modifiedtime`, `accessedtime`,
or `bookkeeping`).

The engine's `_TIMESTAMP_FIELDS` is loaded from this JSON. Without
adding your synonym, the engine still might find your timestamp via
its primary-column detector, but it won't be probed when the engine
falls back to the per-record timestamp lookup.

Example: if your parser writes a column called `event_recorded_at`,
add it to the `timestamp` category:

```json
{
  "timestamp": [
    "...",
    "event_recorded_at"
  ]
}
```

Bookkeeping fields go in the `bookkeeping` category so they sift to the
back of the priority list — real event times always win when both are
present.

**Name your parser's bookkeeping column `parsed_at`.** That is the
canonical name every Crow-Eye parser writes, and `utils/parse_time_column.py`
is the single source of truth for it. The legacy aliases still in the
`bookkeeping` category (`parsed_timestamp`, `parse_timestamp`,
`inserted_at`, `created_at`) exist only so case databases written by
older builds keep working — do not use them in new parsers.

---

## 3. (Optional) Add identity field synonyms

If your table has an identity-like column whose name isn't already in
`config/standard_fields/file_paths.json` or
`config/standard_fields/process_identifiers.json`, add it. Names go in
the `filename` category of `file_paths.json`; paths go in the `path`
category.

Without doing this, records with only that identity column will be
counted as "no identity" and won't form matches.

Example for a new column `link_target_name`:

```json
{
  "filename": [
    "...",
    "link_target_name"
  ]
}
```

---

## 4. (Optional) Declare your table's schema

For per-table tuning, add an entry to
`correlation_engine/config/feather_schemas.json`:

```json
{
  "my_table": {
    "artifact_type": "MyArtifact",
    "primary_timestamp_column": "event_recorded_at",
    "secondary_timestamp_columns": ["created_at"],
    "identity_columns_preferred": ["link_target_name", "source_path"],
    "table_kind": "user_activity",
    "multi_timestamp_json_columns": []
  }
}
```

The engine reads this on first open so it doesn't need to detect the
primary timestamp column from a sample value. Without this entry, the
engine falls back to heuristic detection — which works for most tables
but can be misled by columns with timestamp-looking names that aren't
the real activity time (e.g. `parsed_at`).

---

## 5. JSON list of timestamps per row (Prefetch-style fan-out)

If your parser writes a JSON list of timestamps in one column (like
Prefetch `run_times`, which holds up to 8 historical execution times),
declare it:

```json
{
  "my_table": {
    "multi_timestamp_json_columns": [
      {"column": "all_event_times", "format": "datetime_string"}
    ]
  }
}
```

The engine fans each row out into **one virtual record per timestamp**,
so every event in the list gets correlated — not just the latest.

If you adopt `FeatherWriter` (step 7), declare the column via
`writer.declare_multi_timestamp_json("all_event_times")` and the
metadata is stamped into the feather DB itself — no JSON edit needed.

---

## 6. (Optional) Add the artifact type to the registry

Add an entry to `correlation_engine/config/artifact_types.json` so
the wing scoring system can weight your artifact:

```json
{
  "id": "MyArtifact",
  "name": "My New Artifact",
  "description": "Short forensic description",
  "default_weight": 0.3,
  "default_tier": 2,
  "anchor_priority": 5,
  "category": "secondary_evidence",
  "forensic_strength": "medium"
}
```

This drives weighted scoring; without it, your matches still appear
but use a default weight.

---

## 7. Write your DB

### Quick path: keep doing what you do today

The engine reads any SQLite file. Just drop your `.db` into the case
directory alongside the others. The engine picks it up automatically
on the next correlation run.

### Recommended path: use `FeatherWriter`

```python
from correlation_engine.feather.writer import FeatherWriter, ColumnSpec

with FeatherWriter() as w:
    w.open(output_db_path, artifact_type="MyArtifact")
    w.declare_table(
        "my_table",
        columns=[
            ColumnSpec("event_recorded_at", "TEXT",
                       is_timestamp=True, is_primary_timestamp=True),
            ColumnSpec("link_target_name", "TEXT", is_identity=True),
            ColumnSpec("source_path", "TEXT", is_identity=True),
            ColumnSpec("payload", "TEXT"),
        ],
    )
    # Optional: declare a multi-timestamp JSON column
    # w.declare_multi_timestamp_json("all_event_times")

    w.write_batch(parsed_rows)   # iterable of dicts
    w.add_lineage(source_path=raw_source, row_count=len(parsed_rows))
```

This gets you for free:
- WAL mode + transactional batching (50–200× faster than per-row inserts)
- Indexes on declared timestamp and identity columns
- Schema metadata stamped into `feather_metadata` so the engine
  doesn't need to sniff sample values

---

## 8. Add semantic rules (optional)

If your artifact has known patterns the analyst wants surfaced (e.g.
"executions of `cmd.exe` with PowerShell flags suggest LOLBin"), add
a YAML file under
`correlation_engine/config/default_mappings/<your_artifact>.yaml`:

```yaml
mappings:
  - source: "MyArtifact"
    field: "link_target_name"
    pattern: "(cmd|powershell)\\.exe"
    semantic_value: "Shell Execution"
    severity: "info"
    confidence: 0.85
```

---

## 9. Verify

1. Drop your new `.db` into a case directory.
2. Run a wing that includes your artifact.
3. Look at the per-window diagnostics log line:
   ```
   [Time-Window Engine] window=W records_in=N no_identity=N
       parse_cache_hits=N identities=N below_threshold=N
       skipped=N low_confidence_emitted=N matches_emitted=N
       min_feathers=N
   ```
   - `no_identity` should be 0 (or close to it). If it's high, your
     identity column synonym isn't being picked up — recheck step 3.
   - `below_threshold` should be reasonable. If most identities are
     below threshold, your wing's `minimum_matches` setting may be
     too aggressive for this artifact.
4. The Evidence-by-Feather summary chart should show your artifact
   with a non-zero record count.

If something doesn't show up, the engine's `_last_window_correlation_stats`
dict (set on the engine after each window) records every drop reason —
that's the canonical "did we correlate everything?" signal.
