# How UBA rules work

This page explains how User Behavior Analytics (UBA) turns parsed artifacts into
behaviour events, written from the code in `uba/`. It covers what a rule is, what a
run does, how a person is attributed, how severity and confidence are set, where a
new built-in rule has to be added, and what changes when analysts can write their
own rules.

## 1. A rule has two halves

A UBA rule is **metadata in JSON** plus **a Python extractor**. The JSON says what
the rule is called, how serious it is and which data it needs. The extractor holds
every condition: which rows count, who the actor is, and what the sentence says.
The JSON contains no conditions at all.

### The metadata: `uba/config/behavior_rules.json`

The file holds 81 rules (version `"2"`) and a `requires_collection` list. The rule
for an erased event log looks like this:

```json
{
  "id": "log_cleared",
  "matrix_row": 30,
  "behavior_class": "system",
  "activity": "log_cleared",
  "title": "Event log erased",
  "extractor": "log_cleared",
  "severity": "critical",
  "color_token": "class_system",
  "requires": {
    "tables":   { "logs": ["SecurityLogs", "SystemLogs"] },
    "log_eids": { "SecurityLogs": [1102], "SystemLogs": [104] },
    "log_eids_mode": "any"
  }
}
```

| Field | Meaning |
|---|---|
| `id` | Unique rule id. Events carry it as `rule_id`. |
| `behavior_class` | `user`, `application`, `system_app` or `system`: whose layer of the activity matrix the behaviour belongs to. |
| `activity` | The activity family shown on the card (`logon`, `file_opened`, `log_cleared`...). Several rules can share one activity. |
| `title` | The name shown in the coverage panel, the rule picker and the switch lists. |
| `extractor` | The name of the Python function that implements the rule. |
| `severity` | The default: `routine`, `notable`, `suspicious` or `critical`. |
| `requires` | What the case must hold for the rule to run. Drives the coverage panel. |
| `how`, `degrade_note` | Optional text for the coverage panel. |
| `log_join` | Optional: the event log a rule corroborates with, and the time delta. |

`requires` has these keys:

- `tables`: `{logical_db: [tables]}`. Every table must exist, or the rule is `unavailable`.
- `any_tables`: the same shape, but one table is enough.
- `log_eids` with `log_eids_mode` (`all` or `any`): the event IDs the rule needs. If they are missing, the rule is `degraded`.
- `optional_log_eids`: corroborating event IDs. If they are missing, the rule still runs from disk artifacts, marked `degraded`.

The logical database names (`registry`, `logs`, `prefetch`, `lnk`, `browser`...) are
resolved to files in `Target_Artifacts` by `uba/utils/db_access.py::DB_CANDIDATES`.

`uba/engine/rule_loader.py::load_rules()` validates the file when it loads. It checks
the required keys, unique ids, a valid class and severity, and that `requires` is an
object. When any browser rule is present, it also validates
`uba/config/site_categories.json`. A broken rules file fails at load, not in the middle
of an analysis.

### The extractor: Python

`uba/engine/extractors/__init__.py::EXTRACTORS` maps each `extractor` name to a
function `extractor(ctx, rules) -> list[BehaviorEvent]`. For the erased log:

```python
# uba/engine/extractors/logs.py
def log_cleared(ctx, rules) -> List[BehaviorEvent]:
    rule = rules[0]
    events = []
    for rowid, eid, ts, user, keywords, desc in _security_rows(ctx, [1102]):
        ts = normalize_ts(ts)
        actor = _subject_actor(ctx, keywords, user, "the security log")
        events.append(_mk(
            rule, ts, actor,
            "The Windows security event log was erased — activity records "
            "before this moment were deliberately removed",
            [EvidenceRef(db="logs", table="SecurityLogs", rowids=[rowid], count=1)],
            ctx=ctx))
    for rowid, eid, ts, source, user, keywords, desc in _system_rows(ctx, [104]):
        ...   # System 104: a log erased, with no account recorded -> empty actor
    return events
```

What happens in it:

1. **The query.** `_security_rows(ctx, [1102])` reads `SecurityLogs` read-only through
   the case's connection pool (`ctx.pool`). Every evidence database is opened with
   `mode=ro`, so a rule cannot change evidence.
2. **The actor.** `_subject_actor` reads the SID in the record's own payload
   (SubjectUserSid, the first field) through `ctx.resolver.from_sid`. When the
   payload has no SID, it falls back to the row's account name through
   `from_account_name`. Section 3 explains the ladder.
3. **The event.** `_mk(...)` builds a `BehaviorEvent` (`uba/engine/models.py`). It
   copies `rule_id`, `behavior_class`, `activity` and the default `severity` from the
   rule. It adds the time, the actor (type, name, basis and SID), a plain-English
   `description`, and an `EvidenceRef(db, table, rowids)` pointing at the exact source
   rows. The UI and Eye open those rows from it.

One extractor can serve several rules. `usn_file_activity` serves five file rules in
one pass over the USN journal; `scheduled_tasks` serves two;
`browser_site_visits` serves seven. Each rule says in its own JSON which part it
covers (an event ID, a category).

## 2. The run

`uba/engine/behavior_engine.py::BehaviorEngine.run()` analyses one case:

1. **Actors.** `ActorResolver` loads the human profiles from `UserProfiles` (and from
   AmCache's user inventory as a fallback): SID, account name and profile folder.
2. **Sessions.** `SessionBuilder` (`uba/engine/sessions.py`) pairs sign-ins
   (4624, logon types 2/10/11) with sign-outs (4634/4647) into interactive sessions.
   Workstation unlocks (type 7) attach to the session they fall in. Each event is
   later labelled with the user signed in at its time (`session_user`). That label
   says who was signed in. It is never used as attribution.
3. **Coverage.** `CoverageAnalyzer` (`uba/engine/coverage.py`) gives every rule a
   status from its `requires`:
   - `active`: everything is there.
   - `degraded`: the tables are there but the event IDs are not (auditing is off).
   - `unavailable`: the tables were not parsed.
   - `off`: turned off in Settings (see below).
4. **Extractors.** Rules are grouped by extractor. Each extractor runs **once** for
   all the rules that share it and are neither `unavailable` nor `off`. An extractor
   that fails is logged, and its rules are marked `unavailable` with the reason; the
   rest of the run continues.
5. **The person key.** Each event gets the case's computer name (`host`, from the
   registry's ComputerName, else the name the System log records). Every `User`
   event whose actor is a profile gets that profile's SID (`actor_sid`).
6. **The store.** Events go into `UBAEventStore` (`uba/engine/event_store.py`), a
   private in-memory SQLite database that is indexed for the window's filters and
   pages.

**The stored answer.** The UBA window and Eye call `run_or_load()`, not `run()`. It
writes the store and its coverage, sessions and statistics to
`<case>/UBA/uba_events.db` (`uba/engine/persisted_store.py`). Later calls reuse that
file while it is fresh. "Fresh" means that the stamp it was built from still matches:

- the rules file's version, SHA-256 and rule count;
- the engine's own source;
- every evidence database's size and modification time;
- the set of rules turned off;
- the analyst's own rules (`user_rules_hash`, section 6).

A re-parse or a switched rule therefore produces a new run, and opening the window
again does not.

**Switches.** Settings → User Behavior and the window's Rules view both edit one
setting, `uba_disabled_rules` in `global_config.json`
(`uba/engine/rule_switches.py`). A rule that is off is not handed to its extractor.
Coverage lists it as `off` ("Turned off in Settings"). Eye names it as turned off,
because a rule that did not run is no evidence that the behaviour did not happen.

## 3. The attribution ladder

`uba/engine/attribution.py::ActorResolver` answers "who did this" with an `Actor`:
`(actor_type, actor_name, actor_basis)` plus the SID in `.sid`. The first step that
resolves wins. If none resolves, the actor stays **empty** and the window shows
"Unattributed". The ladder never guesses.

1. **`from_sid(sid)`**: a SID carried by the artifact or the log record.
   - A well-known SID (S-1-5-18/19/20, DWM, UMFD, service SIDs) → `System`.
   - A human-shaped SID that is a profile on this machine → `User`, with that
     profile's name and SID.
   - A human-shaped SID with no profile → empty.
   - Enriched values such as `S-1-5-21-…-1001 (PC\alice)` are read as the SID before
     the space.
2. **`from_account_name(name)`**: an account name from a log payload or row.
   - System names (`SYSTEM`, `LOCAL SERVICE`, `NETWORK SERVICE`, machine accounts
     `NAME$`, `DWM-n`, `UMFD-n`) → `System`.
   - A name that matches exactly one profile → `User`, with that profile's name and
     SID. The match ignores case, accepts `DOMAIN\name`, and accepts a name that the
     Security log itself records signing in with that profile's SID (a Microsoft
     account's e-mail in 4624/4672).
   - Any other human-looking name → `User` with the name as recorded and **no SID**.
     A name that fits no profile, or fits two, binds to nobody.
3. **`from_user_hive(label, sid, owner)`**: a per-user artifact (UserAssist,
   ShellBags, RecentDocs, MRUs, LNK and jump lists).
   - A SID on the row decides first.
   - Otherwise the row's owner decides: the hive's `user_name`, or the profile folder
     that the shortcut file lives in (`…\Users\<name>\…`).
   - An owner that resolves to no profile leaves the actor empty. So does a shortcut
     outside every profile (ProgramData's Start Menu, `Users\Public`).
   - Only when the row names no owner at all, and the machine has a single profile,
     is that profile the actor.
4. **`from_path(path)`**: a path inside the Windows system area → `System`.
5. Nothing resolved → empty.

`actor_basis` always records which step answered, with the SID when there is one,
for example: `the logon event SID S-1-5-21-…-1001 maps to profile 'Ghass'`. The
window and Eye show it beside the actor.

## 4. Severity, confidence and caveats

- **Severity.** The rule's `severity` is a default. Extractors raise it per event
  when the evidence calls for it. Examples:
  - A Remote Desktop sign-in is `notable`.
  - Five or more failed sign-ins in one hour are `suspicious`.
  - Adding an account to Administrators, or deleting an account, is `suspicious`.
  - An unexpected shutdown is `notable`.
  - A per-user writable autostart path is `suspicious`.

  The rule file does not hold these thresholds; the extractor does.
- **Confidence** is set in code, per event (`uba/engine/models.py`):
  - `corroborated`: an artifact matched by an event-log record within the rule's
    `log_join` delta, such as UserAssist or Prefetch with 4688 within 5 seconds.
  - `artifact-only`: an on-disk artifact with no log to confirm it.
  - `log-only`: an event-log record alone.
  - `presence`: existence evidence only (ShimCache, AmCache files, the Compatibility
    Assistant).
  - `inference`: a heuristic, such as a copy inferred from USN creation bursts.
- **Caveats** state the evidential limit of the artifact in plain words. For example:
  - ShellBags are written by file dialogs as well as by Explorer.
  - A registry key's write time is an upper bound ("at or before").
  - A failed sign-in proves only that a name was typed.

  A caveat is attached to the event, and the window shows it on the card.

Timestamps are UTC strings (`YYYY-MM-DD HH:MM:SS`). Events with no time
(`ts_start = NULL`, for example a run count without run times) are kept and shown in
their own "without exact time" strip. They are never given a time they do not have.
Aggregate events (bursts, one per user per hour or per day) carry
`aggregate_count`, and their evidence holds up to 50 rowids plus the full count.

## 5. The nine places a new built-in rule touches

Missing any of the first four makes the rule silently do nothing. Missing the rest
makes it invisible or mislabelled. There is no error in any case.

| # | Place | Why |
|---|---|---|
| 1 | `uba/engine/extractors/{logs,artifacts,files,browser}.py` | The extractor. Build events with the file's `_mk` helper, so the actor's SID and the rule's class, activity and severity are carried. Call `has_column` before selecting a column an older case may lack: otherwise the query throws inside `_rows`, which logs one line and returns nothing. |
| 2 | `uba/engine/extractors/__init__.py` `EXTRACTORS` | Maps the rule's `extractor` name to the function. An unknown name is logged and the rule never runs. |
| 3 | `uba/config/behavior_rules.json` | The rule. Its `requires` drives coverage; a wrong table name makes it `unavailable`, and then the extractor is never called. Sentinel's `verify-facts.js` re-derives the rule count from this file, so a new rule also updates `0x1Ca` in `sentinel-architecture-data.js`. |
| 4 | `uba/tests/conftest.py` | A fixture row that makes the rule fire. **Without one, the rule's test passes by finding nothing.** The fixture is the only proof that the extractor reads the real schema. Several rules have lost every event to a misspelled column while their run stayed green. |
| 5 | `uba/utils/db_access.py` `DB_CANDIDATES` | Only for a new logical database. Without it the database is never found and the rule is `unavailable`. |
| 6 | `uba/utils/db_access.py` `KEY_TABLES` | Only for a new database. Without it the window's start screen says the case has no parsed data. |
| 7 | `uba/react-uba/src/styles/tokens.js` `ACTIVITY_META` and `SOURCE_BY_TABLE` | For a new activity or table. Without it the card shows the raw activity name and the evidence shows the raw table name. |
| 8 | `uba/react-uba/src/components/icons.jsx` `ALIASES` | For a new activity. Without it the card falls back to a generic file icon. |
| 9 | `uba/tests/test_e2e_real_case.py` `EXCLUDED` | Lists every populated table that the rules deliberately do not read. Without it, the real-case test reports the table as uncovered. |

After editing the React files, rebuild the window: run `npm run build` in
`uba/react-uba`. The dialog loads `dist/index.html`, so nothing changes until then.

Also check two more places:

- **`uba/engine/coverage.py::_SOURCE_LABEL`.** Without a label there, the coverage panel shows the bare table name.
- **`requires_collection` in the rules file.** This is the "Crow-Eye has no parser for this" list. A new rule can retire one of its entries.

**Check the rule against a real case, not only against the fixture.** Count events
per rule against the source table's row count, and read the sentences. A rule that
returns 0 events from a 286-row table is broken, and nothing else will say so.

## 6. Analyst-created rules

Analysts add behaviour rules without writing Python. The built-in
`behavior_rules.json` is never modified, so the 81 built-in rules and their count
(which Sentinel re-derives) stay as they are.

### Where they are kept

One file for every case: `uba_user_rules.json` in Crow-Eye's config folder
(`config/case_history_manager.default_config_dir()`, beside `global_config.json`;
`%APPDATA%\CrowEye\config` on Windows). It is never written into a case folder or
the source tree. `uba/engine/user_rules.py` reads and writes it:

- Saving is atomic (a temporary file replaces the old one, which is kept as `.bak`).
- Each rule records `author` (`{"created_by": "human", "name": ...}`, the shape of the
  Wing editor's `eye_authorship`), `created_utc`, `updated_utc` and `version`. An edit
  keeps `created_utc` and adds 1 to `version`.
- Rules export to JSON and import from it (an export, or a bare list). An imported
  rule whose id exists is skipped unless replacing is asked for; one that fails
  validation is skipped with its reasons.
- A save or delete is recorded in the open case's custody ledger, as a switch change is.

### Two kinds, one condition language

Both kinds are written in the Wing condition language: `conditions` are
`SemanticCondition` dicts (`field_name`, `operator`, `value`, `negate`), combined by
`logic_operator` (AND / OR), plus nested `condition_groups` with their own AND / OR.
They are evaluated by `correlation_engine.config.semantic_mapping.SemanticRule`, the
same class Wing rules use, so the same words mean the same thing. There is no third
rule format. Operators: equals, contains, regex, not_equals, greater_than, less_than,
greater_equal, less_equal, wildcard (has any value). Tests ignore case.

**Table rule** (`"kind": "table"`): one parsed table plus conditions on its columns.

```json
{
  "id": "user_shell_launch_bam", "kind": "table",
  "title": "Command shell started by a person", "activity": "program_run",
  "behavior_class": "user", "severity": "notable",
  "description": "{actor} started the shell {app_name}",
  "source": {"db": "registry", "table": "BAM"},
  "logic_operator": "AND",
  "conditions": [
    {"feather_id": "BAM", "field_name": "app_name", "operator": "regex",
     "value": "^(powershell|pwsh|cmd|wsl|wt|wezterm-gui|openconsole)\\.exe$"},
    {"feather_id": "BAM", "field_name": "sid", "operator": "equals",
     "value": "S-1-5-18", "negate": true}],
  "condition_groups": [],
  "columns": {"time": "last_execution", "time_basis": "exact",
              "actor": {"mode": "sid", "column": "sid"}, "app": "process_path"},
  "aggregation": {"mode": "none"}
}
```

- `source.db` is a `DB_CANDIDATES` logical name, or the path of any other database
  inside `Target_Artifacts` (`db_access.is_file_db_name`: relative, no `..`). Such a
  file's size and mtime join the stored analysis's stamp.
- `columns.time` with `time_basis` `exact`, or `at_or_before` for a last-write time:
  the event then says "at or before" and carries a caveat (the registry's
  `CAVEAT_KEY_TIME` for registry tables). No time column gives timeless events.
- `columns.actor.mode` is resolved through the same `ActorResolver` ladder as the
  built-in rules, so `actor_sid` is set exactly as theirs is:
  - `sid`: the column's SID through `from_sid`;
  - `username`: the column's name through `from_account_name`;
  - `hive_owner`: an optional owner column (a user name, a SID, or a path under
    `\Users\<name>\`) through `from_user_hive`; with none, the only profile on a
    one-profile machine and nobody otherwise;
  - `none`: unattributed.
- `columns.app` fills the program filter (`app_display_name`, as built-ins do).
- `description` is a sentence template: `{actor}`, `{app}`, `{time}`, `{table}`,
  `{count}`, or any column in braces.
- `aggregation.mode`: `none` (one event per row), `per_actor_day`, or `burst` with
  `gap_minutes`. An aggregate event carries `aggregate_count` and up to 50 rowids.
- `requires.tables` is derived from `source`, so coverage treats the rule as it treats
  a built-in one.

**Derived rule** (`"kind": "derived"`): a named filter over behaviours already found.

```json
{
  "id": "user_powershell_prefetch", "kind": "derived",
  "title": "PowerShell ran (Prefetch)", "activity": "program_run",
  "behavior_class": "user", "severity": "suspicious",
  "description": "{description} [PowerShell]",
  "base": {"rule_ids": ["program_run"], "activities": []},
  "conditions": [{"feather_id": "event", "field_name": "details.executable",
                  "operator": "equals", "value": "POWERSHELL.EXE"}]
}
```

Conditions read the event's fields (`rule_id`, `activity`, `actor_name`, `actor_sid`,
`app_name`, `severity`, `description`, `ts_start`...) and `details.<key>`. Each
matching event becomes the rule's own event: its id, title, class, activity and
severity, the base event's time, actor, SID, confidence and caveat, and the base
event's evidence. `details.derived_from` names the base rule and event.

### How a run uses them

1. `BehaviorEngine` loads the built-in rules, then the user rules
   (`user_rules.merged_rules_config`). Each user rule joins the rules list with
   `user_rule: true`, its kind, a derived `requires`, a generated `how`, and the full
   rule as `spec`. Coverage, the rule catalog, the switch lists and the stamp all see
   both.
2. **Validation** (`rule_loader.validate_user_rule`) runs on load and on save. It
   checks the id (snake_case, 3-64 characters), the kind, class, severity, activity,
   operators, regular expressions, the column map and the aggregation. **An id that is
   a built-in rule's id, or that a second user rule repeats, is not loaded at all**,
   because events, switches and coverage refer to a rule by id alone. Any other
   failure keeps the rule listed with its reasons, never run.
3. **The case's own checks** (`extractors/declarative.py`): every column a table rule
   names - in a condition, the column map or the sentence - must exist in the case's
   table (`has_column`). A rule that names a missing one is refused with the reason
   ("The column 'Executable' (a condition) is not in the table 'prefetch_data' in this
   case."): coverage marks it unavailable with that note, the case log says so, and
   the window shows "Not run", never "found nothing". A derived rule may only name
   event fields and `details.<key>`; one whose base rules were all turned off or had
   no data is marked the same way.
4. **Extraction.** Every table rule runs after every built-in extractor; derived
   rules run last, in file order, over the store (so one can build on a table rule or
   an earlier derived rule). Plain equals / contains tests on ASCII text are pushed
   into SQL as `LIKE` to read fewer rows; the condition language still decides every
   row. A rule stops at 20,000 events and its coverage note says so.
5. **Events** carry `user_rule = true` (a store column; the stored analysis format is
   2). Session labels and the person key are applied as for built-in events.
6. **The stamp.** `user_rules_hash` (SHA-256 of the rules as loaded) is part of the
   stored analysis's freshness stamp, so adding, editing or deleting a rule makes the
   next open run the analysis again.
7. **Switches.** A user rule is switched off like any rule (`uba_disabled_rules`);
   coverage then lists it as `off`.

### The Behaviour Rule Creator

`uba/ui/behaviour_rule_dialog.py` is the one editor for both kinds. It is opened
through `open_behaviour_rule_creator(parent, artifacts_dir, rule_id, kind, store,
offer_rerun)`, which applies the busy guard (the main window's feature gate when one
is reachable, otherwise `ui.busy_guard`) and returns what was saved, deleted, and
whether a re-run was asked for. Its doors:

- **The User Behavior window:** the Rules view's "New behaviour rule" button and each
  user rule's Edit button call `UBABridge.openRuleCreator`; the window opens the
  editor and sends `rulesChanged` back, which reloads the list and, when asked,
  re-runs the analysis.
- **The Wing Creator's behavioural mode** ("New behaviour..."), which calls the same
  function.

The editor offers a table picker over the case's databases (`discover_databases`)
with the columns read from the case, the condition table with groups, the column map,
the activity (from the built-in activity list), class and severity, and "Test on this
case", which runs the rule on the open case and shows the count and the first events
(time, person, SID, sentence, evidence) before anything is saved. Saving refuses a
rule that fails validation or names a column the open case lacks, and then offers to
analyse the case again.

### Where they appear

- The Activity Story: the violet "Your rule" icon and badge on each card.
- The coverage page: the icon, the badge, and "Not run" with the reason when refused.
- The switch lists (Rules view and Settings → User Behavior), with an Edit button in
  the window.
- Eye's `query_user_behavior`: each event from a user rule carries `user_rule: true`.
- Behavioural Wings can name a user rule's id as a step, like any built-in rule.
