# Crow-Eye Release Notes

---

## Version 0.13.0 — Registry Depth & Timeline Coverage Release

**Release date:** 2026-09-05

**Baseline:** **v0.12.7**, the previous release. Every figure below was measured against that tree.

Two themes. The registry is now read as a **file** as well as through the running system, which reaches keys the live API will not return, the free space where deleted keys and values still sit, and two structures a tree walk cannot see at all — registry tables go from 29 to 81. And the artifacts the parsers already collect now reach the rest of the application: the Timeline plots 133 time columns where it plotted 53, Database Search resolves each artifact to its own database, and the Eye gains a chronology tool that sweeps every database in the case.

| | v0.12.7 | 0.13.0 |
|---|---:|---:|
| Registry tables | 29 | **81** |
| AmCache tables | 17 | **29** |
| Timeline artifact types / time columns / databases | 13 / 53 / 8 | **17 / 133 / 11** |
| UBA behaviours | 40 | **53** |
| Eye forensic tools | 30 | **31** |
| Default Wings | 10 | **11** |
| Test files in this repository | 59 | **68** |

---

### The registry read as a file, past the ACL

A live parse reads the running registry through `winreg`, which is the right way to reach the merged view, volatile keys, `CurrentControlSet` and the redirected 32-bit view — none of which exist in a hive file. Some keys, though, are denied to `winreg` even for an elevated administrator, and the API returns nothing rather than an error that distinguishes denied from empty.

- Measured on a live machine, elevated: walking `HKLM\SYSTEM\CurrentControlSet\Enum\USB` through `winreg` reaches **110 keys**; the same hive read as a file yields **868**. The device `Properties` subkeys are among those denied, and they hold the FILETIMEs recording when a USB device was last connected.
- Crow-Eye already had two ways through, and the registry parser could reach neither: `crow_claw`'s file accessor (standard copy → Volume Shadow Copy → raw disk) and the `SeBackupPrivilege` + `NtSaveKeyEx` export used for `HKLM\SAM` and `HKLM\SECURITY`. Both are now available to it. It falls back through them in order and records which one it used.
- **The evidence is never written to.** The hive file is copied out and the copy is what gets read; the copy's SHA-256 is recorded with the parse, so the case itself carries the proof rather than a test.
- **Every hive reader replays the transaction logs.** A hive Windows has not finished writing keeps its most recent changes in `.LOG1`/`.LOG2`, and replaying them onto a working copy is what makes the read reflect the state the machine was in. The offline registry parser did this; AmCache, ShimCache, SRUM, the SECURITY hive reader and the user-identity reader each opened the raw file. The replay is now done once per hive and shared by all of them.
- **A parse can decline to create a Volume Shadow Copy.** Acquisition wants one made if none exists; a parse should not have to write to the machine holding the evidence in order to read it. That choice now belongs to the analyst rather than the accessor.

### Deleted keys and values, class names, and key security

Deleting a registry key does not erase it. Windows flips the cell's size field from negative to positive, marks the space free, and moves on; the signature, the name, the timestamp and the pointers remain until something allocates over them. Walking the registry *tree* cannot see any of it.

Crow-Eye now walks the hive's **allocator** as well as its tree, and records what only that pass reaches:

- **Deleted keys and values.** On the hives this was written against, **1,451 keys and 6,347 values** sat in free space in `SOFTWARE` alone. They land in `registry_carved_keys` and `registry_carved_values`, with the time still attached where the record carries one.
- **Class names.** An `nk` record can carry a second string beside its name, in its own cell, and it is where the four keys under `Control\Lsa` keep the machine's boot key. Most registry viewers do not render the field. It is now in `registry_class_names`.
- **Key security.** Owner, group and DACL, from the shared security descriptors a hive stores once and points many keys at (`registry_security_descriptors`). The SACL is deliberately not requested: it needs a privilege that, if refused, fails the whole call rather than that one part.
- **Every row recovered from free space is marked as such**, in a `record_state` column present in each table that can show one, so an analyst reading any table can tell a carved row from a live one without knowing which table means what.
- A hive is compacted from time to time, which rewrites its free space, so the parser also records **how much recoverable history the file still holds** — absence of carved records is then a measurement rather than an implication.

### Nineteen keys that nothing was reading

Publishing an article listing every registry key Crow-Eye opens made the opposite question answerable — what does it not open — and **nineteen keys** came back that hold real data on a reference system.

- **Explorer's `StartupApproved` records whether each autostart entry is allowed to launch.** Six of ten HKCU `Run` entries on the reference system are disabled, which `AutoStartPrograms` now reports alongside the entry itself.
- The rest arrive as **ten new tables** — `app_paths`, `app_permissions`, `hid_devices`, `network_cards`, `safe_boot_services`, `SecurityPosture`, `shared_dlls`, `startup_approved`, `system_configuration` and `zone_map`. Nineteen keys make ten tables because `StartupApproved` is read in both HKLM and HKCU, seven keys aggregate into `system_configuration`, and three more into `SecurityPosture` — which also reads one of those seven, `Session Manager\Power`. The other new registry tables come from the hive-structure pass above and from accuracy work that had not yet reached a release: **52 new registry tables in a parsed case since v0.12.7, 29 → 81**, with nothing removed.
- The collectors take the *reader* as an argument, so the live parser passes its `winreg` readers and the offline parser its hive readers, and **the two produce the same rows from the same code**. A key absent on a given Windows build produces a shorter list, never a failed parse. Every new table is listed with the key it reads in the appendix at the end of this section.

### Shellbag timestamps are converted with the evidence machine's bias

A DOS date/time — the format Shellbags and shell items store — carries no timezone. It is the **evidence machine's** wall clock, and labelling it UTC relabels a local reading rather than converting it.

- The parse now takes the evidence machine's UTC bias and converts with it, so the value becomes a real UTC moment.
- Where the bias is not known, the local reading is returned **unchanged and recorded as local** rather than given a zone it does not have. Not knowing is something the case can now state.
- Shellbag times in a case parsed by an earlier version were stored as local time under a UTC label; re-parsing the evidence produces the corrected value.

### AmCache records what the hive actually holds

- **17 → 29 tables.** Every column is a registry value name *observed* in a real `Amcache.hve` rather than inferred from documentation, and the comment above each table records how many entries that subkey held on the reference system.
- **`key_last_write` is captured** — the moment the Compatibility Appraiser wrote the entry. It is a bound rather than an event time, and how much ordering it supports differs per table because the Appraiser writes in batches: all 373 `Mare` entries share one timestamp, 90% of 445 driver binaries share one, while `InventoryApplicationFile` has 1,086 distinct times across 5,212 rows. The notes on the column say so.
- **`DeviceCensus` and nine subkeys that were empty on every available system now use a name/value shape** — `WHERE name = 'AADDeviceId'` — rather than a fixed column list. `DeviceCensus` alone carries 237 distinct value names across 16 entries and Windows adds more each release, so a hand-written column list is stale on arrival. Anything Microsoft adds next lands in `UnknownSubkeys` rather than being dropped.
- **AmCache's dates are locale-formatted text in at least three shapes**, and are now normalised on the way in — which is also what lets AmCache appear on the Timeline. The twelve new tables are listed in the appendix.

### The ShimCache trailing blob is decoded

The data blob at the end of a ShimCache record is an **array of 12-byte slots**, each `(tag, type, value)` as three little-endian DWORDs. Every blob length on 165 live records was a multiple of 12.

Only the tags the bytes established are named, each checked against something read independently of the cache:

- **The executable's machine type** agreed with the PE header of the file on disk on **296 of 300** files that still exist; the four disagreements are files replaced since the cache recorded them, which is the artifact being right rather than the decode being wrong.
- **An operating-system-binary flag**, 164 of 165 against "path under `C:\Windows`", where the single exception is a third-party driver package staged in `DriverStore` — the flag is right and the path was the imperfect proxy.
- The remaining tags sit at 94–97% correlation, close enough to the base rates to be coincidence. They are recorded and left unnamed.

### One map decides what the Timeline plots

The map deciding what the Timeline plots lived in two files that had drifted apart: one filed Shellbags under `Shellbags` and the other under `ShellBag`; one had DAM and USB storage and the other did not; one carried `UserAssist.focus_time`, which is a duration rather than a time. There is now one map, `timeline/data/artifact_map.py`, and both halves of it are required for an artifact to appear.

- **53 → 133 mapped time columns, 13 → 17 artifact types, 8 → 11 databases.**
- **AmCache plots for the first time.** Its dates are locale text (`MM/DD/YYYY …`) and SQLite's `datetime()` returns NULL for those rather than raising, so the lane drew nothing; normalising them on ingest fixes it.
- **Windows Event Log coverage is no longer a handful of event IDs.** 65 significant IDs are mapped by name, and the remaining records are reachable rather than absent.
- **Deleted-file activity, `$FILE_NAME` times and filename changes** from the MFT/USN correlation now plot, as do user accounts, network profiles and app permissions.
- **A registry key's write time is drawn as an upper bound**, not an event time — writing any value under a key updates the whole key. Those columns are labelled as bounded (`≤ T`) in the lane, the tooltip and the detail view, and can be switched off so a timeline reads as exact times only.
- **`parsed_at` — when Crow-Eye ran — is bookkeeping and cannot be plotted as evidence** anywhere.
- DAM, Scheduled Tasks and registry changes have their own colours; the renderer's palette is kept in step with the map the shipping timeline draws from.

### Database Search resolves each artifact to its own database

- **Each entry in the search tree now searches the database that holds it.** The resolver consulted a name map before the table signatures, and `Log_Claw.db` was listed there for almost everything, so five entries named after registry and LNK artifacts offered the three Windows Event Log tables. Signatures decide now.
- **Imported evidence can be searched.** Imported and custom databases were discovered and enhanced with their table lists, then dropped before reaching the tree, because the tree was built from five hand-written category lists. Databases are grouped by the category each one already carries, which `DatabaseManager` had been setting all along.
- **One read per physical file.** Six logical names resolve to the single `Log_Claw.db`; the search now reads it once, reports each hit once, and no longer spends five other databases' share of the per-database result cap on duplicates.
- **The timestamp detector reads the Timeline's map** instead of guessing from column names, and no longer treats `account_expires` and `account_created` as counters because "account" contains "count".

### Eye: chronology, and knowing what the model can do

- **New tool — `query_timeline`.** One chronological sweep across every database in the case, driven by the same map the Timeline plots from. It needs no correlation run and no embedding server, and it replaces a per-database `query_database` walk in which any database the model does not think of is simply missing from the answer.
- **Sealed chronology answers record what was searched.** The window and the artifacts reached are part of the provenance, because "nothing happened then" is a claim about coverage; without it an absent database cannot be told from an empty one. The exact-versus-bounded split is sealed too, so a key's upper bound cannot be used to support "X happened at T".

### User Behavior Analytics — 40 → 53 behaviours

- Thirteen new rule-driven behaviours, chiefly around registry-recorded activity.
- **A bag's view kind is stated where it is known.** Windows files an Explorer window's view settings separately from a common file dialog's, and the parser records which, so the caveat is kept only where the case genuinely cannot tell.
- **A key write time is phrased as a bound** in the narrative, for the same reason the Timeline labels it as one.
- The coverage panel names the new registry artifacts rather than showing the bare table name.

### Correlation: rules, feathers and run records

- **Semantic rules keep every declared field.** Rules were rebuilt by hand-listing constructor arguments, so `technique_id`, `tactic`, `rule_type`, the multi-indicator flags and the advanced-rule blocks were parsed and then discarded. Rules are now built through the same path that declares them, and `disabled` is read from a field that exists, so switching a rule off works.
- **Time-window queries keep one timezone convention.** Timestamps inside the time-based engine are naive UTC; converting to and from Unix seconds through the standard library's defaults reads a naive value as local, and asking for an aware one yields a value that cannot be compared against the window. Both conversions now go through helpers that hold the convention, and the reason is written where the next person will look.
- **The user column survives feather generation.** The generator dropped the last column by position to strip parser bookkeeping; the schema had moved, and `user_name` was the column being dropped from Shellbags, MUICache, OpenSaveMRU and LastSaveMRU — the column those wings correlate on. Bookkeeping columns are excluded by name now.
- **A result row is written after the numbers it describes exist**, and the two writers of that table agree on its columns.
- **Sub-threshold groups are no longer emitted by default.** `low_confidence_review_mode` defaulted to on so that nothing would be discarded silently. Nothing is silent with it off either: every dropped group is counted, a sample is kept with its identities and feathers, both are reported in the run's evidence accounting, and the log names the flag that shows them as Low matches.
- **Execution totals are derived from the result rows they summarise** rather than from whatever the caller passed.
- **Semantic evidence names what matched** — the value the analyst can see and the source it came from — instead of echoing the rule's own pattern.
- **The ATT&CK catalogue names the techniques the registry Wings cite**, so a coverage roll-up can name what it covers.
- **The cascade-tree setting is read.** The identity view's configuration import raised on every launch and the exception was swallowed.
- **Code that could never run has been removed** rather than left as a spare: Python keeps the last definition of a repeated name, and one of the dead copies was a `query_identities_by_anchor_time` that ignored the time window the live one honours.
- **A new default Wing: Security Control Tampering** (10 → 11 rule packs shipped).

### Wings validate against the artifact types they name

A wing's `anchor_priority` is the order in which it prefers to anchor a correlation, and anchor selection matches those entries against the artifact types of **the wing's own feathers**. Validation compared them against a list of 17 coarse categories instead (`Registry`, `Logs`, `Persistence`), so a wing naming a concrete type — `SecurityLogs`, `ShellBags`, `AutoStartPrograms`, `SystemConfiguration`, `SystemLogs` — was rejected before it started, and a rejected wing looks on screen like a wing that found nothing.

- Anchor priority is now checked against the wing's own feathers, and an entry that matches nothing is a **warning rather than a refusal**: a preference that cannot apply is inert. All eleven shipped Wings run.
- **Eleven artifact types reached the artifact detector under their table names only.** The sixteen registry tables added this release arrived as `startup_approved` and `zone_map` while the feather generator and the Wings use the CamelCase artifact type (`StartupApproved`, `ZoneMap`). Both forms are registered now, so the Feather Builder offers them.
- **Each identity wing writes one result row.** The row is created when the wing starts and updated when it reports; the identity engine now records which row it streamed into, so the report updates that row rather than adding a second copy of it.

### Changes that affect a case correlated by an earlier version

Three changes alter how findings from an earlier version read. Existing cases are never modified — they are read correctly by 0.13.0 — but a case correlated before this release should be re-read with these in mind, and re-correlating it is the way to get the new definitions applied.

- **What counts as a match.** `minimum_matches` meant "the feathers that must corroborate" in the wing schema and in the validator, and "total feathers" in both engines, so a wing saying `1` accepted a single feather and corroborated nothing. There is now one definition of the floor — one feather to observe, plus `minimum_matches` to corroborate, never below two — and every engine asks for it. A run made by an earlier version therefore contains single-feather rows that this release would not emit.
- **What a confidence score means.** With weighted scoring off, the score was the number of feathers a match spanned, written into the field consumers read as a normalised 0–1 value and judge against the 0.7 / 0.4 / 0.2 thresholds, so a match could render above "Confirmed" on a raw count. The score is now normalised; the count is still reported, under a name that says what it is.
- **Match counts recorded per identity wing.** Execution totals are the sum of a run's result rows, and an identity wing's row was written twice, so totals recorded by an earlier version count each identity wing's matches twice. A case opened in 0.13.0 is read correctly without being rewritten.

### A multi-wing run reads each feather once

- **Results are built once, when the run finishes.** Each completed wing used to rebuild the unified identity view from the database — every match of every wing so far, re-read and re-parsed on the interface thread — while the next wing was already running. Wings now report as they finish and the results are assembled once, at the end.
- **A feather is read once per run, not once per wing.** Each wing executes in its own pipeline run, so each re-opened every feather it names and re-derived every identity, and the shipped Wings share feathers heavily (`mft_usn` appears in eight of eleven). A run-scoped cache keyed on the feather file's identity rather than its path does that work once and hands each wing its own copy. A feather rewritten mid-run is never served from the previous contents, and the cache reports what it reused in the execution log.
- **Results start loading the moment the run ends.** The "Execution Complete" notice ran its own event loop, so the signal that builds the Results Viewer fired only after it was dismissed. The notice no longer blocks, and the results load underneath it with the same "Loading identity data…" progress the load-from-database path uses.
- **One wing is ticked when a pipeline loads — the widest one.** Every wing used to arrive checked, so pressing Execute on a default pipeline ran all eleven. The default is the wing drawing on the most feathers (Execution Proof, with 14); **Select All** is one click away.
- **The Identity engine is the default.** The pipeline default was the Time-Window engine while the Execution tab's dropdown said Identity-Based, so which one ran depended on whether a pipeline had been loaded. A new pipeline — including the one a new case creates for itself — now says `identity_based`, and the dropdown resolves its default by name rather than by position in a list whose order is not a contract. **Pipelines you already have are left alone:** a saved pipeline naming an engine keeps it, and one saved before the field existed still reads as time-window, because changing that would alter how an existing case runs.
- **The Correlation Engine opens on Pipeline Manager**, rather than reopening wherever the last session stopped. The explicit **Load Session** action still restores the tab it recorded.

### The Wing Breakdown says what happened to each wing

- A **Status** column — Completed, Failed or Skipped — with the wing's own error or skip reason in the tooltip, so a wing that could not run does not read as a wing that found nothing.
- Each wing's **own** duration rather than the pipeline run's wall clock, so a live run and the same run read back from the database agree.
- Wings are numbered once across the run; the numbering used to restart inside each execution.
- **The header no longer clips its own labels**, and a wing's full name is shown rather than elided. A stylesheet on the surrounding frame was being inherited by the table inside it — a `QTableWidget` is a `QFrame` — which pushed the header into its own border.

### Eye-Describe: every section addressable, every byte map drawn from a real artifact

The anatomy pages at **crow-eye.com/Eye-Describe** take each artifact apart byte by byte. They are part of the product but not part of the download: they are live on the site, and they are what the Anatomy button in the application opens.

- **Every section is addressable — 130 of 130.** `registry_anatomy`, which documents UserAssist, BAM and DAM, RecentDocs, TypedPaths, WordWheelQuery, USBSTOR, MountedDevices, TaskCache and MUICache, had eleven sections, five sub-headings and no ids, so nothing could link into it and a search for "UserAssist forensics" had nowhere to land. Slugs are named for the artifact (`#userassist`, `#bam-dam`, `#usb-devices`) rather than for the phrasing of a heading.
- **The hub is an index rather than a card wall** — a 23-row artifact table saying what each artifact records and where it is taken apart, with the registry artifacts pointing at the sections that document them, and the two long-form guides (the boot process, and the registry's own internals) reachable from the front door.
- **A page that names a structure another page dissects says so.** Cross-page references went **14 → 22**, and the link check now matches single-quoted `href`s as well as double-quoted ones.
- **The byte maps are drawn from real artifacts, not hand-written hex.** Four pages carry a live map — AmCache, Registry, ShimCache and Shellbags — and three of them are regenerated from the machine's own hive by their own generator, so the page cannot drift from the artifact. A test runs each generator and fails if the committed page moves.

### An Anatomy button above every documented table

An examiner reading a table of Shellbag rows had no route from the row in front of them to what that row is.

- **51 tables across 11 artifact pages** carry a button that opens the Eye-Describe explanation at the section describing their own records, rather than at the top of a page.
- Only tables a page genuinely documents get one; a button that landed on a directory instead of an explanation would teach an examiner to stop trusting it.
- The anchors are a contract with the site, and a test checks every one of them against the pages themselves, so a section renamed there cannot quietly break a button here. They are the ids the addressability pass created, which is why the two halves ship together.

### Fixes

- **The five forensic-image parsing strategies (E01 and the rest) load.** They were imported under a bare module name with no package, so the import ladder inside each one fell through to an absolute branch that could not resolve. They are imported as a package now, and a test loads all five.
- **Parsing in a separate process reports to the loading screen.** `print()` from a spawned process reaches nobody, because the dialog captures stdout in the parent; those log lines are forwarded through the same progress channel the rest of the run uses.
- **Registry tables are filled by column name rather than by position**, so a schema change cannot reorder what an examiner is reading.

### Under the hood

- **59 → 68 test files in this repository.** The correlation engine's own suite (another ninety-odd checks) is not published: its fixtures carry case state, so `correlation_engine/tests/` stays out of the repo. The ones here are mostly the uncomfortable kind — that both registry parsers agree on *content* rather than on row count, that every decoded value matches something read independently of the artifact, that no GUI column is written by nothing, that a semantic rule can actually fire, that a parser's console output survives a `cp1252` terminal, and that the Timeline's map and the databases agree.
- **`docs/changing-a-parser.md`** — the canonical procedure for changing or adding a parser, including the places a new table has to be registered or its rows are written and never displayed.
- The README architecture diagram shows **dirty-hive replay**: transaction logs applied to a working copy, so a hive Windows had not finished writing is read in the state it was in.


### Appendix: what 0.13.0 added, key by key

Counted from the shipped code at both tags: **53 new `CREATE TABLE` statements**
across the registry parsers and **12** in AmCache. The 29 → 81 figure quoted
above counts the tables a parsed case ends up holding; this counts the table
definitions that are new since v0.12.7 — one of the 53 is not exercised on the reference system, which is why a parsed case gains 52. Paths are relative to the hive root —
`HKCU\` marks the per-user ones. Every key each table reads is documented in
`configs/knowledge_base/registry_knowledge.md`.

#### Autostart, execution and scheduling

| Table | Key | What it records |
|---|---|---|
| `startup_approved` | `CurrentVersion\Explorer\StartupApproved` (HKLM + HKCU) | Whether each autostart entry is **allowed to launch**, and when it was switched off. A Run value is a request; this is the answer |
| `safe_boot_services` | `Control\SafeBoot\{Minimal,Network}` | What still starts in Safe Mode — the boot used to clean a machine, which is why persistence gets placed here |
| `app_paths` | `CurrentVersion\App Paths` | How a bare command name resolves to an executable, from the key's default value |
| `ScheduledTasks` | `SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache` | Registered tasks, their actions and their triggers |
| `CompatibilityAssistant` | `HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store` | A value name here is a program that ran |
| `RecentApps` | `HKCU\Software\Microsoft\Windows\CurrentVersion\Search\RecentApps` | Per-user program execution; absent on some builds |
| `FeatureUsage` | `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FeatureUsage` | Explorer's own per-program counters |

#### User activity and Explorer

| Table | Key | What it records |
|---|---|---|
| `explorer_advanced` | `HKCU\…\Explorer\Advanced` | `ShowSuperHidden=1` is off by default — switching it on means somebody went looking for protected OS files |
| `file_exts` | `Explorer\FileExts\<.ext>` | `UserChoice\ProgId` is the association the **user picked**, which outranks the machine default |
| `cid_size_mru` | `Explorer\ComDlg32\CIDSizeMRU` | Applications that opened a common file dialog, `position` 0 most recent |
| `MountPoints2` | `HKCU\…\Explorer\MountPoints2` and `…\Map Network Drive MRU` | `##server#share` entries prove this user mounted that remote share |
| `OfficeDocuments` | `HKCU\Software\Microsoft\Office` | Files opened, and files the user **enabled content** for |
| `ApplicationArtifacts` | `HKCU\Software\` — `SimonTatham\PuTTY` (Sessions, SshHostKeys), `Martin Prikryl\WinSCP 2\Sessions`, `WinRAR`, `7-Zip`, `Sysinternals`, `TeamViewer`, `FileZilla Client`, `RealVNC` | Host names and file paths left behind by remote-access and archive tools |
| `regedit_lastkey` | `Applets\Regedit` | The key this user last had selected in regedit, plus saved Favorites |
| `programs_cache` | `Explorer\StartPage2` | Start-menu program list as a shell-item blob; presence and size only |
| `printer_connections` | `HKCU\Printers\Connections` | Network printers this user attached; the subkey encodes `,,server,printer` |

#### Network and remote access

| Table | Key | What it records |
|---|---|---|
| `NetworkProfiles` | `SOFTWARE\Microsoft\Windows NT\CurrentVersion\NetworkList`, both subtrees — `Profiles` and `Signatures\Unmanaged` | One row per network: name, category, dates, gateway MAC and DNS suffix, joined on `ProfileGuid`. Flattened into one row-per-value table the two halves never meet |
| `network_adapters` | `Control\Network\{4d36e972-…}` | Adapter GUID to the name shown in `ncpa.cpl`, so an interface GUID elsewhere in the case can be named |
| `network_cards` | `Windows NT\CurrentVersion\NetworkCards` | The adapter inventory by installation index — names cards that no longer have an interface |
| `NetworkShares` | `SYSTEM\CurrentControlSet\Services\LanmanServer\Shares` | Shares this machine offered |
| `RDPClientMRU` | `HKCU\Software\Microsoft\Terminal Server Client` | **Outbound** RDP — servers this user connected to, with the username hint |
| `rdp_tcp` | `Control\Terminal Server\WinStations\RDP-Tcp` | A changed `PortNumber` hides RDP from a port scan; `UserAuthentication` 0 disables NLA |
| `dnscache_parameters` | `Services\Dnscache\Parameters` | `ServiceDll` should be `dnsrslvr.dll`; a replacement is a svchost-hosted load point |

#### Devices and storage

| Table | Key | What it records |
|---|---|---|
| `hid_devices` | `Enum\HID` | Human interface devices — keyboards, mice, and anything presenting itself as one |
| `device_classes` | `Control\DeviceClasses\{GUID}` | Device arrival per class; only the disk, volume, storage-adapter and USB class GUIDs |
| `wpdbusenum` | `Enum\SWD\WPDBUSENUM` | The missing hop in USB attribution: ties a volume GUID to the device that provided it |
| `usbstor_start` | `Services\usbstor` | `Start` 4 means USB storage is **disabled**, so an empty USB history is a setting rather than an absence |
| `ConnectedDevices` | `SOFTWARE\Microsoft\Windows Portable Devices\Devices`, `Services\BTHPORT\Parameters\Devices`, `Windows NT\CurrentVersion\EMDMgmt` | Portable, Bluetooth and ReadyBoost-eligible devices seen by this machine |
| `volume_info_cache` | `CurrentVersion\Explorer\VolumeInfoCache` | Drive letter to the volume label the user actually saw |

#### Security posture and policy

| Table | Key | What it records |
|---|---|---|
| `SecurityPosture` | `Policies\Attachments`, `Control\DeviceGuard`, `Services\LanmanWorkstation\Parameters`, `Control\Session Manager\Power` | Six settings — `SaveZoneInformation`, `EnableVirtualizationBasedSecurity`, `LsaCfgFlags`, `RequireSecuritySignature`, `AllowInsecureGuestAuth`, `HiberbootEnabled` — recorded **whether or not the value is present**, with the Windows default beside it |
| `DefenderExclusions` | `SOFTWARE\Microsoft\Windows Defender\Exclusions` and the `Policies\` copy | Paths, extensions and processes excluded from scanning, and which of the two set it |
| `FirewallRules` | `Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules` and `Services\PortProxy\<proto>\<transport>` | Rules as stored, and port-proxy forwards |
| `zone_map` | `Internet Settings\ZoneMap` | A host moved into Trusted Sites runs content every other zone blocks |
| `app_permissions` | `CapabilityAccessManager\ConsentStore` | Which applications hold consent for microphone, camera or location, and when each last used it |
| `windows_script_host` | `Microsoft\Windows Script Host\Settings` | Usually absent, which means enabled; an explicit `Enabled=0` is someone turning scripting off |
| `files_not_to_snapshot` | `Control\BackupRestore\FilesNotToSnapshot` | An added entry removes a file from every shadow copy taken afterwards |
| `group_policy_history` | `CurrentVersion\Group Policy\History` | Which GPOs applied, and when |

#### System identity and configuration

| Table | Key | What it records |
|---|---|---|
| `machine_guid` | `Microsoft\Cryptography` | Survives profile reimaging — the steadiest single answer to "is this the same host" |
| `active_computer_name` | `Control\ComputerName\ActiveComputerName` | The name in use **this boot**; differs from `ComputerName` after a rename with no reboot |
| `product_options` | `Control\ProductOptions` | `ProductType`: `WinNT` is a workstation, `ServerNT`/`LanmanNT` a server |
| `os_install_history` | `SYSTEM\Setup` and its `Source OS` subkeys | The in-place upgrade trail: which build the machine came from, and when |
| `system_configuration` | `Session Manager\Power`, `Nls\Language`, `Services\W32Time\Parameters`, `Services\Tcpip\Parameters`, `Windows Search\Gather`, `Explorer\Shell Folders`, `Explorer\Taskband` | Settings rather than artifacts, each decoded or left unsaid |
| `system_environment` | `Control\Session Manager\Environment` | Machine-wide `PATH` and friends — a prepended directory is a hijack primitive |
| `shared_dlls` | `CurrentVersion\SharedDLLs` | Reference counts for shared libraries; occasionally the only surviving record that a DLL was installed |
| `hivelist` | `Control\hivelist` | Backing file of every loaded hive — how you confirm the hives collected are the ones in use |
| `winevt_channels` | `Services\EventLog` and `CurrentVersion\WINEVT\Channels` | Which logs were on, and how big |

#### Hive structure — no key path, read from the file itself

| Table | Source | What it records |
|---|---|---|
| `registry_carved_keys` | free space (`nk` cells with a positive size field) | Keys unlinked from the tree and still in the file |
| `registry_carved_values` | free space (`vk` cells) | Values the same way, with the time where the record carries one |
| `registry_class_names` | the `nk` class cell | The second string a key can carry — where `Control\Lsa` keeps the boot key |
| `registry_security_descriptors` | the hive's shared `sk` cells | Owner, group and DACL, with the count of keys sharing each descriptor |
| `registry_key_times` | every `nk` last-write time | The write times themselves, as bounds rather than event times |
| `registry_value_changes` | tree walk vs allocator walk | Values that differ between what the tree reaches and what the file holds |
| `registry_hive_state` | the hive header and log files | Whether the hive was dirty, which transaction logs were replayed, and how much free space remains to carve |

#### AmCache — 12 new tables (17 → 29)

Every column is a value name observed in a real `Amcache.hve`. Each table is
named for the `Root\` subkey it reads, bar the two carving tables, which come
from the hive's free space.

| Table | What it records |
|---|---|
| `InventoryApplicationAppV` | App-V virtualised application packages |
| `InventoryApplicationDriver` | Drivers an installed application brought with it |
| `InventoryApplicationFramework` | Runtimes and frameworks an application depends on |
| `InventoryDevicePci` | PCI devices by vendor, device and subsystem id |
| `InventoryDeviceSensor` | Sensors present on the machine |
| `InventoryMiscellaneousWAMAccounts` | Web Account Manager accounts — cloud identities bound to the machine |
| `InventoryAcpiPhatHealthRecord` | ACPI platform health records |
| `InventoryAcpiPhatVersionElement` | ACPI firmware component versions |
| `DriverPackageExtended` | Driver packages, one row per registry value |
| `MareBackupApps` | The Appraiser's backup application list — hash and SID state, 85 entries on the reference system |
| `AmcacheCarvedKeys` | Keys carved from the hive's free space, marked as carved |
| `AmcacheCarvedValues` | Values the same way |
---

## Version 0.12.7 — Correlation Correctness & Provenance Release

**Release date:** 2026-08-08

This release fixes a **correctness bug in MFT ↔ USN correlation that could attribute a deleted file's journal history to a different file**, and removes a long-standing source of timeline confusion by giving the parser's own bookkeeping timestamp a single, unmistakable name. Both change what Crow-Eye reports on a case, so read the two sections below before working an existing investigation. Alongside them, the Eye now determines — and tells you — whether the model you selected can actually call forensic tools, instead of assuming it can and failing opaquely mid-query.

### 🔗 Fixed: MFT ↔ USN correlation was joining on the wrong key

Correlation matched a journal event to an MFT record using **only the record number**. That is not an identity.

- **The sequence number was discarded.** NTFS reuses an MFT record when the file occupying it is deleted, incrementing the record's sequence number to mark that it now means something else. Matching on the record number alone attached the **deleted file's journal events to whichever file later inherited its record** — a complete, confident-looking timeline for the wrong file, with nothing to indicate anything was wrong. Correlation is now keyed on the full file reference (record **and** sequence number).
- **The volume was ignored.** An MFT record number is unique per volume, not per machine, so record 5000 on `C:` was merged with record 5000 on `D:` — two unrelated files collapsed into one row, each one's timestamps attributed to the other. Every join, lookup and correlated row now carries the volume letter.
- **Reconstructed paths could cross disks.** Path rebuilding followed parent record numbers without regard to volume, splicing one disk's directory tree into another's.
- **Journal-only activity was silently dropped.** Correlation walked MFT records, so an event whose file has no MFT record was discarded — and the "has MFT record" column was hard-coded to say it did. A file created and deleted between two collections leaves **no MFT record at all**; the journal is the only place it ever existed. Those events are now kept and marked `JOURNAL_ONLY`.
- **The name the journal recorded at the time of the event is now stored** (`usn_filename`, plus the file reference and security ID). The difference between that name and the name the MFT holds now *is* the rename evidence — it was being fetched and thrown away.
- Correlated rows now also carry file extension, size, in-use state and alternate-data-stream counts, and the "standard information present" flag reports the real answer instead of always saying yes.

**What this means for existing cases.** A case correlated by an earlier version holds rows produced by the broken match. On first open, Crow-Eye **detects that and rebuilds the correlated table**, telling you on the loading screen that it is doing so and why. Nothing is lost: the correlated database is derived entirely from the MFT and USN databases in the case folder, which are never modified. Leaving the old rows in place would have meant known-wrong correlations sitting alongside correct ones with no way to tell them apart.

### 🕒 Changed: one name for the parser's own timestamp — `parsed_at`

Every parser records **when Crow-Eye parsed the artifact** next to each row. That column shipped under four different names, and in the Registry tables it was called `timestamp` — which reads, to any analyst, as the time the activity happened. It was worse than cosmetic: `timestamp` was ranked as a *real activity* time, so the Correlation Engine and the Timeline could anchor findings on the moment Crow-Eye ran.

- All parsers — live and offline — now write **`parsed_at`**, and every tab displays it as **"Parsed At"**.
- **Existing cases are not modified and stay fully readable.** Crow-Eye resolves whichever name a database actually uses and relabels it on screen, so an older case opens exactly as before, with the column now clearly identified.
- The Correlation Engine and Timeline treat `parsed_at` and all its legacy spellings as bookkeeping only — they can no longer be mistaken for evidence.
- **Removed the Network Interfaces lane from the Timeline.** Its only timestamp was the bookkeeping column, so the lane was plotting *when Crow-Eye ran* as though it were network activity. Interface configuration is still available in the Registry tab. A second lane, Network List Profiles, queried a table no parser has ever created and always returned nothing.

### 🤖 New: the Eye tells you whether your model can call tools

The Eye is agentic — everything it does for you runs through forensic tool calls — yet it decided whether a model could call tools by matching its **name** against `gemma`, and optimistically assumed every other model could. A local GGUF, a fine-tune or a fresh provider model that could not function-call was sent the full tool payload anyway, and the failure surfaced as an opaque server error in the middle of a query.

- Capability is now **determined**, through a ladder of increasingly expensive checks — cached result, the provider's own metadata, known model families, then a live probe against the model itself — and Crow-Eye records **how it knew**.
- **Settings → Eye shows the verdict with its provenance**, plus a **Re-test** button that probes the live model. "Verified by a live probe" and "assumed because we recognise the name" are very different claims, and you can see which one you have.
- A model confirmed unable to function-call is **no longer sent a tool payload at all** — it is taught the text tool-call protocol instead, and told so once, clearly. A merely *assumed* verdict never changes what is sent, so a wrong guess can never quietly disable tools on a model that supports them.

### 🖥️ Fixed: User Behavior Analytics could not open from a source checkout

Running Crow-Eye from a clone of the repository and opening **User Behavior Analytics** produced *"UBA interface build not found — run npm install && npm run build"*, and nothing in the application ever built it.

- **UBA is now built at startup like the Timeline and the Eye.** Crow-Eye's start-up build step handled those two but had no step for UBA at all — it was added after that step was written and never wired in, so the interface was never built by anything.
- **The UBA and Timeline interfaces now ship prebuilt.** A packaging rule intended for Python build output was also matching the compiled interfaces, so they never reached the repository. Both are now included (about 300 KB each), which means **neither needs Node.js to open** — this matters on an isolated or air-gapped workstation, where Crow-Eye cannot download Node.
- **A clone no longer rebuilds an interface it already has.** Start-up treated a missing `node_modules` folder as reason to rebuild, so a fresh checkout tried to download Node and rebuild files that were already present and current. It now rebuilds only when the interface is genuinely missing, or when you have edited its source with a development environment installed.

The Eye's own interface is still built on first launch — it is a 9 MB bundle, and shipping it prebuilt would add that to the repository on every rebuild.

### 🔧 Fixes

- **The Pipeline Builder could not be opened from Settings.** Both **Edit** and **Create** in Settings → Pipeline Management failed immediately with *"Failed to open Pipeline Builder"* — the builder was being handed the wrong configuration manager, one that carries none of the signals it listens to. It now shares the same configuration manager as the Correlation Engine, so a feather or wing added in one appears in the other while both are open. Opening the builder from the Correlation Engine window was never affected.
- **Renaming a pipeline while editing it no longer leaves a duplicate behind.** The file is named after the pipeline, so renaming used to write a second pipeline and keep the original — the rename now moves it.
- **Local CLI agents were invoked with flags that do not exist.** The Claude CLI profile passed `--prompt` and `--system-prompt` (the real flags are `-p` and `--append-system-prompt`), so every invocation failed on flag parsing. The Ollama CLI profile hard-coded `llama3` as an argument, so **the model you configured was ignored** and every investigation ran against whatever `llama3` happened to be installed.
- **Choosing certain providers silently failed to save.** The configuration schema's list of valid backends had not kept up with the provider catalogue, so connectivity validated, the write then failed, and the choice was never persisted. There is now a single list of supported backends that the schema is tested against.
- **Ollama can now be configured as a local server during setup** — the router always supported it, but the wizard only offered it as a CLI agent, so a LAN Ollama could not be set up at all. A placeholder model name is also resolved to a model that is actually installed, rather than being sent literally.
- **"Connect to <provider>…" no longer leaves an unusable model name behind.** The placeholder is resolved to a model the provider actually serves before it is saved, preferring one that is both live and recommended — a provider's catalogue can list models that reject every request.
- **Retry classification now reads the HTTP status code** instead of searching the error text. A real 503 whose message mentioned a previous 429 was never retried, and a permanent 400 complaining about `max_tokens: 500` was retried three times with backoff.
- Retired Gemini 1.5 models were removed from the model menu — they no longer serve requests, so offering them handed you a broken selection.
- The Eye's configuration is now located relative to the application rather than the working directory, so it is found however Crow-Eye is launched.
- **Terminal colour codes no longer appear as escape sequences in the loading screen log**, which now also has a status line for long-running steps.
- Icons in the Settings, Eye, image-parsing and offline-importer dialogs are drawn at a consistent size.

### 📋 Wording: how we describe defensibility

Crow-Eye's documentation and the Ghassan Elsman Protocol now describe outputs as **traceable to source records and backed by an auditable, tamper-evident chain**, rather than "court-defensible" or "legal-grade". Nothing about the evidence handling changed — the hash chain, the Evidence Seal and the Compliance trail are the same. The new wording states precisely what the tool guarantees and leaves admissibility, which depends on jurisdiction and process, to the people who decide it.

---

## Version 0.12.6 — Bring-Your-Own-Model & Evidence Custody Release

**Release date:** 2026-07-26

This release makes the Eye work with **whatever model the investigator already has a key for**, and turns imported evidence into a first-class, tamper-evident part of the case. You can now connect OpenRouter, NVIDIA, Groq, Mistral, xAI (Grok), DeepSeek, and Kimi alongside OpenAI/Anthropic/Gemini — a single API key each — and the Eye picks the most capable *tool-calling* model automatically. Every piece of external evidence you bring in — a database, a third-party report, an email export, browser-tool output — is now hashed, listed with a live integrity check, and readable by the Eye. Plus a broad responsiveness pass so the model menu and suggested actions feel instant.

### 🔌 New: Bring-your-own-model — seven more providers

Connect the AI backend you already use. Every new provider is a **single-key, OpenAI-compatible** setup in Settings.

- **Added providers** — **OpenRouter**, **NVIDIA**, **Groq**, **Mistral**, **xAI (Grok)**, **DeepSeek**, and **Kimi (Moonshot)**, alongside the existing OpenAI, Anthropic, and Gemini. OpenRouter alone fans out to essentially every model behind one key.
- **Fixed Google AI Studio / Gemini key detection** — the model list came back empty on the modern `google-genai` SDK, making a valid `AIza…` key look broken. It now discovers models correctly, and any provider falls back to a built-in "common models" list when live detection is unavailable.
- **Smarter recommendations** — because the Eye is agentic (it calls forensic tools), the **recommended** model for each provider is now the most powerful one that **supports tool calling** (e.g. DeepSeek-Chat over the non-tool Reasoner). Every provider ships an offline "common models" quick-pick.

### 🔀 New: Model switching that verifies itself

- Switching model or provider now **validates the key and model on a background thread** before committing. If it can't connect, the Eye **reverts to the previous model** and tells you exactly why — no silent hangs.
- The switch persists the correct backend configuration for **every** provider (previously only OpenAI/Anthropic/Gemini were mapped correctly).

### 🗂️ New: Imported Evidence window + chain of custody

- A dedicated **Imported Evidence window** (top bar and Case Settings) lists **every** imported item — databases and documents — with **SHA-256 hashes of both the original file and the in-case copy**, size, source path, and a **live integrity verdict** (Verified / mismatch / missing). Hashing runs off the UI thread, so multi-GB databases never freeze the app.
- **Import reports, email, and browser-tool output *verbatim*** — PDF, HTML, TXT/MD/LOG, and email exports (`.eml`/`.mbox`) are copied into the case **without conversion** (because third-party output is often a report, not a table), hashed, and readable by the Eye via the new **`read_imported_evidence`** tool.
- Imported evidence — databases *and* documents — now appears in the **Compliance** activity stream as `IMPORT` entries with their hashes, and the list **auto-refreshes** the moment an import finishes.

### 🧭 Improved: Narrative Map shows the real evidence

- Evidence cards now display the **actual source rows** — auto-loaded in the inspector and in the double-click detail popup — for both native and imported evidence, correctly resolving native-vs-imported databases that share a filename.
- Evidence produced by a **non-database tool or a text-mode (non-function-calling) model** now shows its **full captured text** instead of a dead-end "no source" message.
- Compliance entries **deep-link** to their Verdict / Narrative / Evidence card in the Narrative Map.

### ⚡ Improved: Responsiveness

- **The model dropdown opens instantly.** It used to freeze the UI on every open (a live network call plus up to ten OS-keychain reads on the GUI thread). It now opens immediately from a cached list and refreshes in the background.
- **Suggested-action chips run on a single click** with an instant running indicator; a small pencil icon inserts the action into the message box to edit first. Typing in long conversations no longer lags.

---

## Version 0.12.5 — Universal Import & Investigator Experience Release

**Release date:** 2026-07-18

This release opens Crow-Eye up to the *rest of the world's* forensic data and makes the Eye AI reason over it as a first-class citizen. You can now bring an external dataset — a SQLite database, or a CSV/JSON export from Plaso, Autopsy, Volatility, an EDR, or any custom tool — straight into a case, and the Eye will query it, correlate it against the artifacts Crow-Eye already parsed, and place it on the Timeline. Alongside that, a broad experience pass fixes readability, removes emoji from the UI in favor of designed icons, and closes several launch-crash bugs.

*(Versions 0.12.1–0.12.4 were installer-only builds; this is the next published source release, so the changes below span everything since 0.12.0.)*

### 📥 New: Universal Evidence Import

Bring third-party forensic data into an open case and analyze it next to the natively-parsed artifacts.

- **Two entry points** — an **"Add Evidence"** button in the Eye AI top bar, and an **Import Evidence** action in the Settings/onboarding dialog (both share one flow).
- **Any of three formats** — import a **SQLite `.db`/`.sqlite`** directly, or a **CSV / JSON / JSONL** that is **auto-converted to SQLite** using the built-in Feather converter (headless `FeatherImporter`): columns are sanitized, nested JSON is flattened, and the primary timestamp column is auto-detected and normalized to ISO-8601. Conversion runs on a background thread so large files never freeze the UI.
- Imported data lands in a dedicated `Target_Artifacts/Imported_Evidence/` folder and is **auto-discovered** by the Eye — no manual registration; the model's schema view refreshes immediately.

### 🔗 New: The Eye analyzes imported evidence *with* the case — and finds correlations

- Imported databases are surfaced to the Eye as **first-class "Imported Evidence"**, and the assistant is directed to cross-reference them against native artifacts (corroborate / conflict / silent).
- A new deterministic tool, **`correlate_imported_evidence`**, checks whether the imported data shares **identities** (filenames, users, IPs, hashes) or **timestamps** with native artifacts, returning concrete `database:table:rowid` matches. It runs **proactively at case-open triage** (adding an "Imported Evidence Correlation" report section) *and* on demand.
- The Eye now also has **full query access to the Correlation Engine's results database** (`query_database` / `get_schema` on `correlation_results.db`), on top of the existing time/identity/statistics tool.

### 🕒 Timeline: imported evidence, on the grid

- Imported events are rendered in the Timeline's **Artifacts lane** and are **connected** to matching native events by the existing shared-name + time-window correlation, so external data lines up with what the machine actually did.
- Removed the non-functional default browser right-click menu ("View page source" / "Save page") from the Timeline; the app's own row context menus are unaffected.

### 🎨 Experience: readability, iconography, and behavior analytics

- **App-wide dark theme for dialogs** — a global palette + popup stylesheet fixes the unreadable *black-text-on-dark-background* popups that appeared in message boxes and several dialogs.
- **Emoji → designed icons** — replaced the remaining colorful emojis across the **Timeline**, the **Eye** UI, the **PyQt dialogs** (settings, database search, partition, startup), and the **collector GUIs** with clean inline-SVG / CrowEyeIcons iconography; the "default" and "advanced" markers were redesigned as line icons to match the set.
- **User Behavior Analytics (UBA)** now opens reliably — the analytics UI is shipped built, resolving the "Build Missing" prompt on first open.

### 🔧 Fixes & correctness

- **Cross-database search fixed** — the Eye's `search_artifacts` tool now actually searches *every* database in the case and tags each hit with its source database (previously it silently returned nothing).
- **No duplicate-evidence analysis** — the Eye no longer double-counts the Correlation Engine's auto-generated "feather" copies of native artifacts.
- Fixed **launch crashes** in the **Offline Importer** and the **Forensics Image Parsing** dialog, and the **Eye AI first-run** splash issue.

---

## Version 0.12.0 — Behavioral Intelligence & Case Narrative Release

**Release date:** 2026-07-04

The 0.12.0 release turns Crow-Eye's parsed artifacts into answers a human can read. Two new subsystems headline the release: **UBA (User Behavior Analytics)** — a plain-English "what did this user do" storyline built from every artifact in the case — and the **Narrative Map** — a persistent, tamper-evident case-memory board shared between the investigator and the Eye AI assistant. Underneath them, case management was hardened end to end.

### 🧠 New: User Behavior Analytics (UBA)

A brand-new analysis window (`uba/`, toolbar button or `Ctrl+Shift+B`) that reads the case's parsed artifact databases and renders user, application, and system behavior as a plain-English activity storyline — readable by a manager or HR reviewer, defensible by a forensic examiner.

**Three views**
- **Activity Story** — a chronological, day-grouped feed of behavior events. Each card is a plain-English sentence with an activity icon; expand it inline for the forensic proof (confidence tier + `source → detail` evidence list + evidentiary caveats), or double-click for full paged drill-down into the actual source records.
- **Activity Map** — a per-day × hour-of-day heatmap. Brightness = activity volume, color = the most serious activity that hour; click a cell to filter the storyline to it.
- **What we can see** — an honesty report. Every detection is labeled **Working / Limited / No data / By design** for this specific case, with *how* it detects and *which* artifacts it draws on — so absence of data is never silently read as absence of activity.

**40 declarative behavior detections** (`uba/config/behavior_rules.json`) spanning routine → notable → suspicious → critical:
- Sign-in / sign-out, workstation unlock, remote-desktop logons, admin logons, credential use, account creation/changes (incl. admin-group additions)
- Programs opened (UserAssist), programs run (Prefetch, expanded to per-run events), process creation (4688), program presence (ShimCache/AmCache/MUICache), app installs, app crashes (Application Event Log 1001)
- File open/create/delete/copy/rename — renames show the **full name history** (`old → … → current`) reconstructed from the USN journal, with soft-delete (`$R/$I`) resolution
- Folder browsing (ShellBags), recent documents, typed locations, website visits
- USB device connect, device presence, network shares, network connections and per-app data transferred (SRUM)
- Autostart persistence (Run keys + services, escalated when the target runs from a user-writable path), service/driver installs, service state changes
- System start/shutdown, **clock changes**, **event-log clearing**

**Filters:** free-text search, user/actor (incl. "Unattributed" and a signed-in-session toggle), behavior class (user/application/system), severity, application (searchable multi-select across 200+ programs), and datetime range with quick presets (all time / first day / last day / last hour of activity).

**Forensic guarantees**
- Source databases are opened **read-only**; the analysis never touches the evidence.
- Every event carries its provenance (`database → table → rowid`) and opens the real source rows on demand.
- **Actor attribution never guesses**: an event is attributed to a User, an Application, the System — or left empty. Interactive logon sessions are used only as context labels ("during `<user>`'s session"), never to attribute an action.
- Wording distinguishes deliberate interaction (UserAssist, SRUM foreground) from artifacts an application can also generate (ShellBags, LNK, JumpLists), with explicit caveats on the card.

**Data sources:** Security/System/Application Event Logs, USN Journal, MFT, UserAssist, BAM, Prefetch, ShimCache, AmCache, MUICache, ShellBags, LNK / JumpLists, Recycle Bin, SRUM (application, network, connectivity), and registry hives.

### 🗺️ New: Narrative Map — the Eye's persistent case memory

The Eye AI assistant is stateless between turns; the Narrative Map (`eye/services/narrative_map_service.py` + a new board UI in the Eye window) gives it — and you — a persistent, auditable, tamper-evident working memory for the case.

- **A strict three-level story structure**: one **Verdict** (open / proven / unproven) → **Narratives** (the claims being established: proven, open, negative finding, hypothesis, stipulated fact) → **Evidence** (artifact-backed facts). Rendered as a free-form 2D board: drag cards anywhere, collapse/expand, link/unlink narratives, attach/detach evidence, park unassigned evidence in a tray.
- **Human and AI edit the same map.** Investigator notes are injected verbatim into the Eye's next prompt, so human guidance actually steers the model. An **"Investigate this narrative"** action hands any narrative back to the Eye to work.
- **Tamper-evident chain of custody.** Every change flows through a single commit choke point that enforces the Ghassan Elsman Protocol (GEP) rules — reason required, evidence linked, eye-stamped — and appends to a **hash-chained audit log** (`narrative_map.json` + `narrative_map_audit.jsonl` under the case's `EYE_Logs/`). `verify_chain()` re-walks the log and detects tampering, even of human-readable fields; the Audit tab and Compliance panel surface the full history.
- **Forensic guardrail:** an AI-authored narrative can never be marked *proven* with zero evidence — removing its last evidence auto-converts it to a **negative finding** (the absence becomes the finding).
- Evidence cards store the source SQL query and database, so the detail window reloads the real rows on demand — the map never becomes a copy of the evidence, only a pointer to it.

### 📁 Improved: Case Management

- **Recent-case history** (`config/case_history_manager.py`): every case gets a UUID with created / last-accessed / last-opened timestamps, **favorites**, tags, and status. The startup menu lists recent cases; history auto-dedupes by path and evicts oldest non-favorites when full.
- **Crash-safe persistence**: history and global config are written atomically (`.tmp` write → `.bak` backup → atomic rename), so a crash mid-save can no longer corrupt them.
- **Case validation**: opening a case checks the directory, `Target_Artifacts/`, and expected databases, returning structured errors and warnings instead of failing silently.
- **Case config import/export** as standalone JSON, plus importing another case's data into the current case.
- **Case templates** (`cases/templates/templates.json`): new cases start with ready-made semantic mappings (e.g. 4624 → "User Login") and default scoring weights.
- **Schema validation + migration**: older case configs upgrade cleanly on open — no manual editing.

### 👁️ Eye AI Assistant improvements

- **Cloud model backends**: Google **Gemini** and **OpenAI** backends (`eye/backends/cloud_api/`) alongside the existing Anthropic and local-model support. API keys are stored in the **OS keyring** via the credential manager — never in files, never in the repo.
- **Report Builder** (`ReportBuilderPanel.tsx`): a drag-and-drop, AI/investigator-collaborative report editor that pulls narratives and findings straight from the Narrative Map.
- **GEP Protocol Compliance panel**: live view of protocol-rule compliance over the Eye's actions.

### 🔧 Other changes

- New UBA toolbar icon and a dedicated crimson theme for the UBA window.
- UBA engine ships with its own pytest suite (89 tests, including an end-to-end run against a real case).
- New competitive-analysis and pitch docs under `docs/positioning/`.

---

## Version 0.11.0 — Reliability & Extensibility Release

A deep reliability and accuracy pass over the Correlation Engine, closing the most common "where did my evidence go?" gaps. Full details live in the [README's Correlation Engine section](README.md#-correlation-engine).

**Highlights**
- **No dropped evidence**: multi-timestamp fan-out (every Prefetch `run_time` correlated, not just the latest), tolerant timestamp parser (FILETIME, `YYYYMMDD`, annotated strings), duplicates preserved as evidence, 290+ identity-field synonyms.
- **Accuracy fixes from a real ~700K-record case**: identity engine records-seen went from 3,558 → **745,615** (a filter bug was aborting per-row iteration); log records no longer collapse to their event provider as the identity; placeholder strings (`N/A`, `Unknown`, nil-GUIDs) rejected as identities; path-based **impersonation alerts** (trusted vs suspicious install locations).
- **Honest diagnostics**: per-window drop ledger with named buckets — every record either lands in a match or in a named drop bucket.
- **One source of truth**: field synonyms in `config/standard_fields/*.json` (98 identity categories, 1,146 column synonyms), per-table feather metadata in `feather_schemas.json` — extend by editing JSON, not code.
- **FeatherWriter**: transactional batched inserts (50–200× faster large imports), schema metadata stamped into the feather DB.
- **96-test regression suite** locking in every fix.
