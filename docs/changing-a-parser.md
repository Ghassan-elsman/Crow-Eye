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
| Writing rows | `utils/dedupe_insert.py`: `insert_new()` (rows not stored yet, NULL-safe) + `ensure_identity_index()` + a `Tally` whose `as_result()` is the parser's return |

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

### Parse status — why a table is empty
Every parse records one outcome per artifact (`utils/parse_status.py` → `<case>/logs/parse_status.json`),
and the **i** button above an empty table reads it through `utils/table_sources.py`.
- **A new registry table:** add it to `REGISTRY_TABLE_WIDGETS` in `utils/table_sources.py` as well as to
  `table_mapping` (place 3 above). `test_table_sources_complete.py` fails until the two agree.
- **A new non-registry tab:** add its widget to `_STATIC_SOURCES` in the same file.
- **A table that is often legitimately empty:** add one plain sentence to `configs/empty_table_hints.json`
  saying when that is normal. That sentence is what the investigator reads.
- **A new artifact / parser:** add it to `ARTIFACTS` and `probe_sources()` in `utils/parse_status.py`, give
  the live task an artifact key in `utils/concurrency/standalone_parsers.py`, and map its offline type
  name in `_TYPE_ALIASES`.
- **Return a real result** (dict with `success` / `records` / `errors`), or an explicit `status` when the
  parser already knows why it stopped. A bare `None` with no fresh database is recorded as **Failed**.
- **Report what the run added**: `records` = rows read, `inserted` = new to the case, `duplicates` =
  already there (`Tally.as_result()` builds exactly this). Without them Parse Status falls back to the
  database's row delta. An unchanged database after a successful run is **Parsed** ("no new rows"), never
  "no output database".

### Re-parse — add only what is new
Running a parser twice on the same machine must **add the new rows and nothing else**:
- **Never** `DROP` or `DELETE` a table or a profile's rows to avoid duplicates. What has since rolled out
  of the live source (old events, aged-out history) is lost from the case with them.
- **Never** a plain `INSERT` into a table with no identity. Write through `insert_new()`, keyed on what
  identifies the evidence (a record number, a key + its write time, or every column but `parsed_at`).
  `parsed_at` is never part of an identity: it differs on every run.
- Guards use `IS`, not `=`. `NULL = NULL` is never true, so a row with an empty column passes a `=`
  guard on every run (the Recycle Bin did).
- A guard that compares raw value names with column names never matches (Amcache: `ProgramId` vs
  `program_id`, every row stored twice). The test is the row count after a second run, not the code.
- Identity indexes are plain, not UNIQUE: a case parsed before already holds duplicates, and a UNIQUE
  index cannot be built on it. Those cases keep their rows; only new ones are checked.
- **The identity index must be selective.** Every new row looks itself up through it: an index on
  `(source_path, store_kind)` - two values - made each insert scan a profile's whole local storage, and
  a live Parse All sat in the browser stage for 40+ minutes. Index the columns that tell rows apart
  (origin + key + seq; url + time), check with `EXPLAIN QUERY PLAN` that it says `SEARCH ... USING
  INDEX` on all of them, and time a second parse of real data.
- **A table that was empty when the run began needs no check:** take a plain INSERT for it (SRUM and
  Browsers record `empty_at_start` per table), so a first parse costs nothing extra.
- **A table with a UNIQUE key whose other columns change** (visit counts, last-access times, versions):
  `INSERT ... ON CONFLICT(key) DO UPDATE SET ... WHERE col IS NOT excluded.col` - `OR IGNORE` keeps the
  first parse's values for ever.
- A batch retried row by row after a failure must run in a SAVEPOINT: `executemany` is not atomic, and
  the rows before the bad one get stored twice.
- Guarded by `correlation_engine/tests/test_reparse_adds_only_new.py`: a new writer gets a "twice -> 0
  new" test there.

### Logging — what the case log says about your parser
Every parser runs inside `utils/parse_logging.artifact_run()`, called by `ParserInvoker.invoke_parser`
(offline / image) and the live runner (`utils/concurrency/standalone_parsers.py`). It logs the start and
`done: N records in Xs` under `Artifacts_Collectors.run.<artifact>` → `parsers.log`, copies what the
parser prints into that logger, and feeds the parsing dialog's checklist.
- **Log with `logging.getLogger(__name__)`**, never `logging.info(...)`: the root logger reaches no
  component file. `test_parse_logging.py` fails on a root-logger call in the parser folders.
- **A new module in `Artifacts_Collectors/`** (or `MFT and USN journal/`) is also imported by its bare
  name: add it to `PARSER_MODULES` in `utils/logging_setup.py`, or its records miss `parsers.log`.
- **Report the file you are on** with `run.file(path)` when the parser is handed the `ArtifactRun`, and
  print progress bars with `\r` - the dialog shows the last one as its *Now:* line, the log skips them.

### Per-user files — keep the owner's folder
`NTUSER.DAT`, `UsrClass.dat`, LNK files and Jump Lists exist once per user under the same names. Collectors
place them through `Artifacts_Collectors/user_artifact_paths.py` (`Users\<name>\...`), so a hive stays
beside its own `.LOG1/.LOG2` and the folder names the owner. A new per-user artifact type goes in
`PER_USER_TYPES` there; read the owner back with `owner_from_path()` (after a transaction-log replay,
on `registry_transaction_log.source_path_for(path)` - the replayed copy is a temp file).

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

## 4. Traps that fail quietly

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

**A raw-disk read of a file must follow its data runs.** The `$MFT` is a file, and on a drive in use
for a while it is fragmented. `MFT_Claw` and the raw-disk `$MFT` copier located record N at
`mft_lcn * cluster + N * 1024`, which holds only inside the first fragment: one C: drive's `$MFT` was in
17 fragments and the parse kept 205,056 of 3.3 million records. Past the first fragment the reads land
on unrelated clusters, the `FILE` signature check fails, and the record is dropped at debug level -
"Parsing errors: 0". The tell is a USN journal whose files are mostly "not in the MFT", and a record
count that matches the first run's length exactly. Read through `utils/ntfs_runs.py`
(`mft_layout`, `read_stream`). A non-resident attribute's real size is in its header at 0x30 - reading
only resident sizes made every file over ~700 bytes read as empty.

---

## 5. Verify what reached the screen

Row counts, not "it ran":

- parse before and after, and diff row counts per table — existing tables keep or increase, never lose
- **parse twice**: the second run reports 0 new (Parse Status: *already present*) and no table grows
- the GUI tab's `rowCount()` equals `SELECT count(*)` from the table. If any of the four GUI touch
  points is missing, the tab renders empty while the database has rows, and every structural check
  still passes
- for offline work, confirm the parsed data belongs to the **image**, not the analyst's machine — task
  names, hostnames and timestamp era are the giveaways
