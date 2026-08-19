# Live and offline registry parsing: where they differ, and why

Crow-Eye parses the registry two ways. `Artifacts_Collectors/Regclaw.py` reads the running machine
through `winreg`; `Artifacts_Collectors/offline_parsers/offline_RegClaw.py` reads collected hive
files through `python-registry`. They write the same 108 tables into the same `registry_data.db`.

They do **not** produce identical output, and they never can. Some of the difference is the evidence
itself — a hive file cannot contain a key Windows builds in memory at boot — and some is a decision
one parser can make and the other cannot. None of it was written down, so an analyst comparing a
live case against an image had no way to tell a legitimate difference from a bug.

This is that list. It is maintained alongside the guard that enforces it,
`correlation_engine/tests/test_live_offline_agree_on_content.py`.

**Current state: the two parsers agree on 102 of 107 shared tables**, comparing content rather than
row counts. Everything below explains the rest.

---

## 1. What only one side can ever see

### Keys that exist only in memory

Windows builds some keys at boot; they are never written to a hive file, so the offline parser is
right to have nothing for them.

| table | why live only |
|---|---|
| `hivelist` | `HKLM\SYSTEM\CurrentControlSet\Control\hivelist` is the running kernel's map of which hive is mounted where. It is volatile by definition. |
| `active_computer_name` | `Control\ComputerName\ActiveComputerName` is the name in use *right now*. The persistent name is in `ComputerName`, which both parsers read. |

These are the only two. A future volatile key must be added to `VOLATILE` in the guard, or the guard
will report it as a defect.

### Users who are not logged on

This is the asymmetry that runs the other way, and it is the more important one.

* **Live** can only see hives that are **loaded**. `HKEY_USERS` contains an entry for a user only
  while they are logged on (or a service is running as them). A user who logged off an hour ago is
  invisible to a live parse — their `NTUSER.DAT` is on disk, unmounted, unreadable through `winreg`.
* **Offline** reads **every `NTUSER.DAT` and `UsrClass.dat` that was collected**, logged on or not.

So on a multi-user machine the offline parse routinely holds user activity the live parse cannot
reach. This is not a bug in either one. If a live case is missing a user you expected, that user was
not logged on.

### Accounts that are not people

Both parsers now read `HKU\.DEFAULT` and the three service SIDs (`S-1-5-18` LocalSystem, `S-1-5-19`
LocalService, `S-1-5-20` NetworkService). `.DEFAULT` is the profile that applies before anyone logs
on, which makes it a persistence location worth reading — on the machine this was developed against,
LocalService and NetworkService each carry a `Run` entry that nothing reported before.

Their rows are labelled, never resolved to an account name:

```
(.DEFAULT profile)   (LocalSystem)   (LocalService)   (NetworkService)
```

The labels live in `Artifacts_Collectors/user_identity.py` (`SYSTEM_ACCOUNT_LABELS`). Resolving
`S-1-5-18` would produce `NT AUTHORITY\SYSTEM`, which reads like an account a person could log in
as, and these rows sit in the same tables as real user activity.

**This is the one place where live currently reaches further than offline.** Live reads the service
hives through `HKEY_USERS`, which mounts them for any running service. Offline needs the underlying
files, and they are not under `Users\` — they live at
`Windows\ServiceProfiles\LocalService\NTUSER.DAT` and `...\NetworkService\NTUSER.DAT`. Those paths
are collected now, but **a case collected before this change will not contain them**, and its
offline parse will be missing whatever those hives held. On a stock machine that shows up as two
`HKU\(LocalService) Run` / `HKU\(NetworkService) Run` rows present live and absent offline.

### Locked hives

`HKLM\SAM` and `HKLM\SECURITY` cannot be read in place even as Administrator — SAM denies everything
below `SAM\SAM`, and SECURITY denies its own root. The live parser exports them with
`user_identity.live_hive_export()` (SeBackupPrivilege + `NtSaveKeyEx`) into a temporary directory
for the duration of the parse. Offline reads them if they were collected. Never ask an analyst to
`reg save` these by hand — the product does it.

---

## 2. Decisions one parser can make and the other must not

### Who a row belongs to

The canonical form is `MACHINE\username`, defined by `user_identity.display_owner()`.

* **Live** resolves it with `LookupAccountSid`, which answers from the machine the parser is running
  on. That machine *is* the evidence, so the answer is correct.
* **Offline must never do this.** Resolving an image's SIDs against the analyst's own machine
  invents an account that was never on the evidence. Offline derives the owner from the hive itself
  and the SAM that came with it.

Both parsers previously carried a second, ad-hoc path that produced a bare `Ghass` where the other
produced `CROW-PC\Ghass` — the same user under two labels in one table. Both now go through
`display_owner`.

### ControlSets

`SYSTEM\CurrentControlSet` is an alias Windows resolves to whichever set is active, so a live read
sees exactly one. A machine normally carries two — the active set and `LastKnownGood` — and they can
differ: a service disabled since the last successful boot is still enabled in the other set.

**Both parsers now read every `ControlSet00N` and merge them, active set last so it wins.** Live does
this inside `reg_Claw_live` / `get_subkeys_live` rather than at each of the ~56 call sites, so no
reader can be forgotten. Before this, offline merged and live did not, and the two disagreed
silently on any machine with more than one set.

### MRU timestamps

An MRU list carries no per-entry timestamp. The only time the artifact holds is the key's own
last-write, and giving that to whichever entry happens to sit at position 0 attributes a fact about
the key to a row that may not have caused it.

So on `OpenSaveMRU`, `LastSaveMRU`, `RunMRU`, `WordWheelQuery` and `RecentDocs`:

* `access_date` is **empty by design** in both parsers.
* `key_last_write` holds the key's last-write time.
* `mru_position` gives the recency order, from `MRUListEx`.

### Path rendering

`UsrClass.dat`'s own root *is* `HKCU\Software\Classes`, so a path read out of the hive starts at
`Local Settings\...` while a live read through `HKCU` gives
`Software\Classes\Local Settings\...`. Both parsers now record the full `HKCU` form, which is also
what regedit shows. `registry_path` is excluded from the content comparison regardless, because a
live view and a hive file legitimately render paths differently.

---

## 3. Dirty hives — offline only

A hive Windows had open is almost never final. Its base block carries two sequence numbers; when
they differ, the outstanding changes are in the `.LOG1` / `.LOG2` beside it.

**Every dirty hive is replayed before parsing**, by
`Artifacts_Collectors/registry_transaction_log.py`. The recovery is written to a temporary copy —
the evidence is opened read-only and never modified — and that copy is parsed. On the development
machine this recovered five hives and gained keys and values that would otherwise have been missing
(`NTUSER.DAT` alone gained 10 keys and 4 values), with nothing lost.

When replay **cannot** happen — no log collected, a pre-Windows 8 `DIRT`-format log, a log older
than the hive — the hive is still parsed, so the evidence is not lost, and the parser says so on the
console and records it.

### `registry_hive_state`

One row per hive the parse touched, whether anything was replayed or not:

| column | meaning |
|---|---|
| `hive_name`, `hive_path` | which hive |
| `sequence_1`, `sequence_2` | the base block's two sequence numbers; unequal means it was dirty |
| `was_dirty` | 1 if Windows had it open mid-transaction |
| `logs_found`, `log_format` | which logs were beside it, and `new` (HvLE) or `old` (DIRT) |
| `replayed`, `entries_applied`, `pages_applied` | what recovery did |
| `reason` | why it did or did not happen, in words |

**Read this table before trusting a timeline built from an offline registry parse.** A row with
`was_dirty = 1` and `replayed = 0` means every other table may be missing that hive's last
transactions.

A live parse creates the table and leaves it empty: there is no hive file to be dirty, so "no rows"
is the true answer. The table is created either way so a case has the same shape however it was
parsed - a missing table would look like an older build instead of an answer.

It is shown in the GUI as the **Hive State** tab, and it is deliberately *not* in the Feather
Builder's artifact list. Correlation rules are built on evidence with times and actors; this is
provenance about the parse. Putting it in that dropdown would invite rules correlating "the hive was
dirty" against user activity, which is not a finding about the machine.

---

## 4. Drift — the same machine at two moments

A live parse is always later than the image it is compared against, and a running machine keeps
changing. These differences are expected and are not defects:

* **Execution times.** `BAM` last-execution times and `ScheduledTasks` `last_run` / `last_completed`
  move continuously. Running the parser itself writes new BAM entries for the Python interpreter.
* **Lease and counter blobs.** `network_interfaces` `DhcpInterfaceOptions` changes as the DHCP lease
  renews; `Windows_lastupdate_subkeys` holds tick counters.
* **Installed software.** Versions change under you. A package upgrade also rewrites its own version
  *into* paths and display names, so the same service can appear with two different `image_path`
  values — which means **the image can hold rows the live machine no longer has**, not only the
  reverse.
* **Drive letters.** `MountedDevices` reassigns letters as volumes come and go.

The content guard masks dotted version numbers before comparing for exactly this reason, and
excludes the columns listed in its `DRIFTING` set. It does not mask anything else: two values that
still differ once versions are blanked are a failure.

The cheapest way to remove drift from an investigation of a difference is to close the time gap —
re-export the hives immediately before the live parse. Doing that on the development machine took
the differing tables from 13 to 3.

---

## 5. Re-running the comparison

The guard is `correlation_engine/tests/test_live_offline_agree_on_content.py`. It needs two
databases parsed from the same machine state and skips without them:

```
set CROW_EYE_LIVE_DB=...\live\registry_data.db
set CROW_EYE_OFFLINE_DB=...\case\Target_Artifacts\registry_data.db
python -m pytest correlation_engine/tests/test_live_offline_agree_on_content.py
```

**"Identical" means content, not row count.** The comparison that preceded this one diffed per-table
row counts, and reported Shellbags as identical while not one of its 802 rows matched. A count
catches a parser that read nothing and nothing else.

The current comparison:

* derives an **identity** per row — the shortest leading column set that is unique — and compares the
  remaining columns for identities present in both. Rows on only one side are add/remove drift, in
  either direction, and are not failures;
* excludes **provenance** columns (`parsed_at`, `registry_path`, `user_name`, `key_path`, `id`),
  which legitimately differ between a live view and a hive file;
* excludes the **drifting** columns above, and masks version numbers.

Two further checks in the same file need no fixtures and always run: no `#` comment inside a SQL
string (Python is happy, SQLite is not, and the table comes out empty), and no formatted string
written into a numeric column (SQLite keeps it as TEXT, and TEXT sorts above every integer).
