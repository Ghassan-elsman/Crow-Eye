# Changing a parser, or adding one

A parser is never finished when it parses. Its output has to reach the database, the GUI, the
correlation engine and the Eye — and every one of those is a separate place that must be told the
table exists. Miss one and the data is written and never seen, with no error anywhere.

This is the checklist, derived from adding Scheduled Tasks to the registry parser.

---

## 1. Prove it before it touches the parser

Write the new section as a **standalone script**, run it against the **live system**, and check the
output against something observable — regedit, Task Scheduler, `Get-ScheduledTask`. Only once it is
right, fold it into the parser, mirror it into the offline variant, and re-run.

This is not ceremony. Two examples from one afternoon:

- The Scheduled Tasks work first aimed at `SYSTEM\CurrentControlSet\Services\Schedule\TaskCache`.
  That key exists, but has **no TaskCache under it** — the real one is in the **SOFTWARE** hive. The
  wrong path returns **zero rows and no error**: a silently empty artifact that ships green.
- Two binary field offsets were wrong. `last_completed` read at `0x18` instead of `0x1C` decoded as
  the year **6916**. `last_result` read at `0x14` instead of `0x18` returned **0 on all 285 tasks** —
  indistinguishable from "no failures on this machine". Only comparing against
  `Get-ScheduledTaskInfo` proved it.

**A wrong offset usually decodes to a plausible value rather than raising.** Ground truth, not
confidence.

For anything offline or image-based, drive **Crow-Eye's own pipeline** rather than calling `dissect`
directly — otherwise you are testing around the product, not through it:

```
ImageCollectionCoordinator.collect_from_image(image, partitions, artifact_type_filter)
    -> ArtifactTypeDetector      (registry patterns ^SOFTWARE, ^SYSTEM, ...)
    -> ParserInvoker.invoke_parser('Registry')
    -> _resolve_registry_hive_paths() -> offline_RegClaw
```

---

## 2. Reuse — do not add

| Need | Use |
|---|---|
| Any timestamp | `utils/time_utils`: `filetime_to_datetime()` then `format_forensic_timestamp()` — both UTC |
| Parser bookkeeping | `parsed_at`, and nothing else |
| Binary blob decoding | `Artifacts_Collectors/registry_binary_parser.py`, beside the BAM/DAM/RecentDocs/UserAssist decoders |
| Anything autostart-shaped | `AutoStartPrograms(location, program_name, command, parsed_at)` — `location` distinguishes the source key |

Add a **new table** only when no existing one holds that shape. A new **column** on an existing table
is preferable to a new table. Scheduled Tasks earned a table because triggers, last run and last
result have no home anywhere else — but its command still also goes into `AutoStartPrograms`, so
persistence queries see tasks beside the Run keys.

---

## 3. Update these, or the work is invisible

### The parsers
- `Artifacts_Collectors/<Parser>.py` — the live path
- `Artifacts_Collectors/offline_parsers/offline_<Parser>.py` — the offline path
- the **EXE tree** (`Crow-Eye EXE dev/Crow-Eye`) as well as source

### The GUI — four separate places
| # | Where | Controls |
|---|---|---|
| 1 | `data/registry_loader.py` → `registry_tables` | which tables the loader will read |
| 2 | `Crow Eye.py` → `_load_registry_data_worker` → `table_names` | which tables the worker actually loads |
| 3 | `Crow Eye.py` → `_populate_registry_tables` → `table_mapping` | table name → the `QTableWidget` it fills |
| 4 | `Crow Eye.py` tab block | the tab + `QTableWidget` (`setup_standard_table`, `Registry_widget.addTab`) and its `setTabText` in the retranslate block |

The **Parse Registry** and **Parse All Artifacts** actions need no change — they already call the
parser. It is the display path that does not know.

### The correlation engine
- `correlation_engine/config/artifact_types.json` — the source of truth
- `correlation_engine/config/artifact_type_registry.py` → `_load_hardcoded_defaults` — the fallback
  used when the JSON is missing. **Both**, or they disagree silently.
- `correlation_engine/feather/ui/main_window.py` — the artifact-type dropdown; a type absent there
  cannot be selected
- `correlation_engine/config/semantic_mapping.py` — if the new fields should map to shared concepts

### The Eye
Tables are auto-discovered from `sqlite_master`, so no Eye **code** change is needed. What Eye does
not get for free is *meaning*:

- `configs/knowledge_base/<artifact>_knowledge.md` — what the artifact is
- `configs/knowledge_base/parser_mappings.json` — artifact → parser file, offline parser, output DB;
  bump `version` and `last_updated`
- `configs/knowledge_base/Global_schema_database_Reference.md` — the **live** schema doc, named in
  `configs/llm_config.json` and routed to by `eye/services/intent_engine.py`.
  `global_schema_reference.md` is a 399-byte orphan stub: editing it looks right and changes nothing.

### Crow-Eye Sentinel
A parser's tables **are** the endpoint schema. See
[the Sentinel README](../../Crow-Eye%20Sentinel/README.md) — `extract-schema.js` derives the schema by
reading these parser sources, and the Sentinel CI gate fails until it is regenerated.

---

## 4. Two traps that fail quietly

**Non-ASCII in parser `print()`.** Parsers run **in-process** under `ParserInvoker`, printing to a
console that is `cp1252` by default on Windows. A single `✓` raises `UnicodeEncodeError` and aborts
the entire parse (`success=False, records=0`). Where a `try/except` wraps the section it degrades into
a misleading warning instead — the same bug, quieter. Keep parser output ASCII: `[OK]`, `[FAIL]`,
`->`. Guarded by `correlation_engine/tests/test_parser_console_safe.py`.

Do **not** fix this by reconfiguring `sys.stdout` — these run inside the PyQt application and would
mutate the host's stdout.

**A parser must create its own output directory.** `reg_Claw` writes to `case_root/Target_Artifacts/`,
and nothing else in the codebase creates it. Without `os.makedirs(..., exist_ok=True)` the parse dies
on a bare sqlite `unable to open database file`.

---

## 5. Verify what reached the screen

Row counts, not "it ran":

- parse before and after, and diff row counts per table — existing tables keep or increase, never lose
- the GUI tab's `rowCount()` equals `SELECT count(*)` from the table. If any of the four GUI touch
  points is missing, the tab renders empty while the database has rows, and every structural check
  still passes
- for offline work, confirm the parsed data belongs to the **image**, not the analyst's machine — task
  names, hostnames and timestamp era are the giveaways
