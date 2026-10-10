# Crow-Eye Release Notes

---

## Version 0.14.1 — Whole-Disk Evidence, Chain of Custody & Large-Case Correlation

**Release date:** 2026-10-10 · **Baseline:** 0.14.0. All figures below are measured against that release.

### Overview

Version 0.14.1 is organised around four themes:

- **Complete evidence.** The MFT parser reads the whole `$MFT`, not its first fragment: 3,320,633 records on the test machine instead of 205,056, deleted entries included. Browsers parse from collected folders and forensic images as well as live systems. Every user's registry hive replays its own transaction logs.
- **Chain of custody.** Every collection, parse, export, import and settings change leaves a record. Copies are verified against their source. Shadow copies Crow-Eye creates are deleted when the run ends. The case keeps a hash-chained ledger of everything done to it.
- **Large cases, correct results.** The Correlation Engine streams its feathers, so a 3.8-million-row MFT no longer exhausts memory. Semantic mapping finishes in minutes instead of an hour, Stop works inside it, and a run that did not finish still shows its statistics. A second parse of the same machine adds only what is new.
- **One look, and Linux.** Every window uses the website's design, standard columns are colour-coded, and the Python source version starts on current Linux distributions.

| Measure | 0.14.0 | 0.14.1 |
|---|---:|---:|
| Live MFT records read on a 17-fragment `$MFT` (test machine) | 205,056 (first fragment only) | **3,320,633**, deleted entries included |
| MFT rows with an `[Unknown Parent]` path | 50,848 | **135** |
| MFT file names with corrupted bytes (one `$MFT`) | 13,601 | **0** (NTFS fixups applied) |
| In-use files whose size read as 0 | 122,682 of 152,131 | **38,053 of 1,209,142** (genuinely empty files) |
| Renames recorded old → new | 0 | **4,107**, 395 of them moves |
| MFT record count shown in Parse Status | rows of four tables summed ("18,094,212") | **records** (3,320,633) |
| Modes that parse browsers | live | **live, offline folder, forensic image** |
| Copies verified against their source | none | **every copy** |
| Shadow copies Crow-Eye created, left on the target | all of them | **deleted at the end of the run** |
| Run kinds with a custody record | 0 | **8**, plus a hash-chained case ledger |
| Rows stored again by a second parse of the same machine | all of them (Amcache, SRUM, MFT) | **none**; only new rows are added |
| Identity engine memory on a 3.8-million-row MFT feather | ~18 GB (did not finish) | **~2.1 GB** |
| Semantic mapping, 105,309 matches | 138 s | **86 s**, identical labels |
| A run stopped during semantic mapping | thread killed after 15 s, Summary empty | **stops in seconds, saves, opens marked CANCELLED** |
| Longest GUI stall while a dashboard loads | the whole query (a timeline day: 70 s) | **172 ms** |
| User Behavior Analytics behaviours | 65 | **81** |
| Event IDs with their own description | 426 | **617** |
| Eye forensic tools | 31 | **32** |
| Correlation Engine | 1.7.0 | **1.8.0** |
| Python source version on Debian 12 / Ubuntu 23.04+ | did not start | **starts, builds its venv, opens every window** |
| Test files in this repository | 84 | **89** |

### Highlights

- **The whole MFT.** Every fragment of the `$MFT` is read through its data runs, with NTFS fixups applied, real file sizes, long names ahead of 8.3 aliases, and a rename log (old name → new name).
- **Chain of custody.** One record per run, a case-wide hash-chained ledger, a **Case → Chain of Custody…** viewer, verified copies, and shadow copies cleaned up by their own ID.
- **Browsers everywhere.** Offline folders and forensic images produce the same 37 tables as a live parse, older Chrome formats included.
- **Correlation on large cases.** Feathers stream; semantic mapping skips a prefilter that filtered nothing; Stop is honoured; a stopped or unfinished run keeps its statistics and charts, labelled **NOT FINISHED** or **CANCELLED**.
- **Parse twice, store once.** Every parser adds only rows the case does not hold, and Parse Status reports read / new / already present.
- **Forensic images say what went wrong.** A pre-flight check names unsupported formats, missing segments, BitLocker, partial acquisitions and investigator mistakes before extraction starts.
- **The website's look everywhere**, colour-coded columns, logs in colour, and a live parse checklist.
- **Linux.** The Python source version starts on Debian 12 / Ubuntu 23.04+ and parses a collected case identically to Windows.

---

### Complete Evidence

#### MFT and USN — the whole `$MFT`, real sizes, renames old → new

- **The live MFT parser read only the first fragment of the `$MFT`.** It located record N at
  `start of the $MFT + N × 1024`, which holds only until the first fragment ends. On this machine the
  `$MFT` is in 17 fragments; the first holds 205,056 records and the parse stopped there, every later
  record read from unrelated clusters and was dropped as "not a FILE record" with no error. That is why
  97% of the USN journal's files were "not in the MFT", why 49,000 paths read `[Unknown Parent]`, and
  why no deleted entry was ever listed. The `$MFT` is now read through its own data runs: 3,320,633
  records, 1,624,197 of them deleted entries, in 7 min 17 s (it was 231 s for 205,056 one-at-a-time
  reads; reads are now 1 MB at a time). The raw-disk `$MFT` copy used for offline imports had the
  same assumption and is fixed the same way.
- **Real file sizes.** Every file stored outside its MFT record (anything over ~700 bytes) had size 0,
  Amcache.hve included; the size is now read from the attribute header, and an alternate data stream
  no longer adds to it. Amcache.hve reads 9,175,040 bytes, its size on disk.
- **A file's names and size in extension records are merged into the file.** A file with many hard
  links keeps some names in another record; it had no name and size 0, and the extension record
  showed up as a nameless file.
- **Renames, old name → new name.** `filename_changes` (in `mft_usn_correlated_analysis.db`) is now the
  rename log: each RENAME_OLD_NAME journal record paired with the RENAME_NEW_NAME that follows it for
  the same file, with the old and new folders and a *moved* flag - 4,107 renames on one case, 395 of
  them moves. Each file's renames are also on its correlated rows (`filename_change_timeline`), and
  its other current names (hard links) in `namespace_evolution`. The MFT keeps current names only,
  so this is the only name history there is.
- **Correlation:**
  - journal-only events get a full path, from the folder in the MFT or - when the folder is gone -
    named from the journal's own records (0 events without a folder, was most of 247,224);
  - a parent folder whose record now holds another folder is shown as `[Reused Parent]`, not walked
    into a path the file was never in;
  - re-correlating rebuilds instead of appending (every MFT-only row was duplicated each time);
  - USN v3 file ids (32 hex digits) decode correctly;
  - the report counts files by volume, record and sequence.
- **The dashboard** pages every day list (a day with 42,543 new files used to stop at 200), adds an
  all-records list across every day (USN records, MFT files or renames), shows renames as
  *old → new*, applies the same filters to every overview number, accepts a pasted `C:\…` path in the
  search, draws dates back to 1980 and says how many fall outside, and no longer writes to the case.
  On a 3.5-million-row case the overview opens in 2.9 s and the strip in 4.7 s.
- **The correlation wings' MFT/USN conditions named columns that do not exist** (`reason`,
  `si_created`, `fn_created`, `path`): the mass-delete and both ransomware rules could never fire, and
  the timestomp rule compared a time with itself. They name the real columns now; the admin-share
  rule looks for a program written straight into `C:\Windows` (where ADMIN$ lands) instead of any
  path with a `$` in it, which matched `$MFT`. A file's eight MFT times join the correlation windows
  once, not once per journal event. Use **Update default wings** to refresh an existing case.

#### MFT and USN — real names, every record counted, one timeline

- **The MFT parser now applies NTFS fixups.** NTFS replaces the last two bytes of every 512-byte stride of a record with a sequence number, and keeps the real bytes in the record's fixup array. They were never put back. On a real `$MFT`, 44,628 of 201,656 records decoded a different name once fixed; 13,601 names held control characters (`…REV_D8.\x06ock` for `.lock`); some names were wrong but looked valid (`8wekyb3d8bhwe`); and some records lost their long name entirely. After the fix: **0** corrupted names.
- **Long names, not 8.3 aliases.** The correlator kept a file's DOS name (`MIGRAT~1.DAT`) ahead of its Win32 name (`migration.dat`), and every path built through it inherited the alias. On one case, rows named by an 8.3 alias fell from 136,996 to 2,975, and paths with an 8.3 component from 181,609 to 16,590. Row count and the key columns are otherwise identical.
- **The name columns were never written.** `filename_change_timeline` and `namespace_evolution` were filled and then rolled back, because the connection closed without a commit; they were empty on every case. They are now written (see *renames* above). The 8.3 alias is no longer recorded as a "change": it was 96% of those rows, and the Timeline plotted each one as "File renamed".
- **Correlation never parses the examiner's own disk into an offline case.** The MFT/USN *correlate* action, and the offline wrapper, re-parsed the live MFT and USN of the machine Crow-Eye runs on before correlating. They now correlate the databases already parsed; the live machine is parsed only for a live case that has neither.
- **Offline MFT / USN:**
  - each collected volume keeps its own label (`OFFLINE`, `OFFLINE_1`, …), where all of them were `OFFLINE`;
  - a second volume's `$MFT` or `$J` is parsed, where it was skipped because the first had filled the table;
  - correlation runs once per batch, after both, where it ran from each side, once against the previous run's journal;
  - an existing correlation is rebuilt when its inputs are newer, where it was kept for ever.
- **The MFT/USN dashboard, rebuilt:**
  - one six-month day strip for both sources: MFT files created / modified (distinct files) and **one row per USN reason flag, each with its own colour**;
  - every aggregate is counted in SQL. A day's drill-down read at most 6,000 events, and one journal day held 283,585;
  - names and paths for journal-only events, which were blank: 87% of one case's events belong to a reused MFT entry. The folder is rebuilt from the journal itself when it is no longer in the MFT;
  - files opened by volume, record **and** sequence number;
  - a **Charts** button on the correlated MFT/USN table, which had none.

#### MFT parse and MFT–USN correlation: faster, and counted in records

- **The live MFT parse no longer slows down as it goes.** It committed every 1,000 records and kept the secondary indexes up to date row by row, so each batch was slower than the last: 9 min 47 s for 3,320,832 records. It now uses the offline path's bulk mode (10,000 records per batch, secondary indexes rebuilt once at the end). On 1.4 million records the insert time halves (101 s → 51 s) and stays linear.
- **MFT is counted in records, not table rows.** Parse Status read "MFT 18,094,212": the rows of `mft_records`, `mft_standard_info`, `mft_file_names` and `mft_data_attributes` added together. It now reports MFT records (3,320,633), and the log gives the row total beside it.
- **Hard links are real hard links.** The record header's link count includes the 8.3 alias of a long name, so every file with a short name was recorded as hard-linked: 2,202,687 `Hardlinks` rows on one case, about 95,000 of them real. Only records with more than one real name get a row now. Directories, which cannot be hard-linked, and extension records, whose count is not the file's, get none.
- **The MFT–USN correlator** reads its MFT query in the primary key's order. It used to sort every joined row before returning the first, 30 s of a 70 s read. Its forensic report counts distinct files over the columns themselves, and "Top 10 Files by Journal Events" replaces a grouping of every row by name and path (17.5 s → 0.9 s). Correlating the 7.10.2026 `$MFT` went from 322 s to 258 s with an identical correlated table. The progress bar counts MFT records instead of rows, so it no longer reads past 100%.
- **Why a case now holds many more MFT rows than under 0.14.0.** 0.14.0 read only the first fragment of the `$MFT`, which on the test machine is 205,056 of 3,320,832 records. The rest was dropped without an error. The new count matches Windows: `fsutil fsinfo ntfsinfo` reports 3.17 GB of MFT, exactly 3,320,832 records of 1,024 bytes. In-use files are within 1% of a live walk of the drive. About 1.5 million of the records are deleted entries, still named, which the old parser never saw.

#### Measured on this machine, live and elevated

The complete live MFT (3,320,633 records) correlated with the live journal (216,572 events):
Amcache.hve and `anatomy_links.py` are found under the record and sequence `fsutil` reports, with
their real sizes and full paths; no journal event points past the end of the MFT (with the old
parser 97% did); 9,824 renames, 754 of them moves; deleted files whose folder record now holds
another folder are marked `[Reused Parent]` (808,976 rows, all of them deleted entries). The
correlation itself took 356 s for 3.5 million rows.

#### Browsers from offline folders and forensic images

Browser data is now parsed from collected folders and forensic images, not only from the live machine. The **Offline Importer**, **Parse Offline Artifacts** and **Forensic Image Parsing** produce the same 37 tables in `browser_analysis.db` as a live parse, and the Parse Status Report records Browser as *Parsed* (or *Not found*) for those modes instead of *Not run*.

| Measure | 0.14.0 | This release |
|---|---:|---:|
| Modes that parse browsers | live | **live, offline folder, forensic image** |
| Tables, offline/image | 0 | **37** |
| Content match, offline vs live (same machine) | — | **34 of 37 tables row for row**; the rest differ only in case-path columns and 3 Service Worker rows |

#### How browser collection works

- **Each profile keeps its folder tree.** Every other artifact is collected into one folder per type under its file name. A browser cannot be: every profile has its own `History`, and only the folders above it say which user, browser and profile it belongs to. Browser files are collected to `live_acquisition/Browser/<source>/Users/<name>/AppData/...`, where `<source>` is `vol_<N>_<id>` for partition N of an image, `src_<folder>_<id>` for each imported source, and `live` for Crow-Claw. The `<id>` is a short hash of the image or folder path, so two images, two drive roots or two hosts in one export never merge.
- **Browser files are recognised by where they sit**, inside a `Users\<name>\AppData` profile, before the filename rules run. A `.url` file inside a profile is browser evidence, not an LNK. Windows XP `Documents and Settings` profiles and trees without a user folder are handled too. A tree with no user folder is filed under a pseudo-user named for the folder it was found in.
- **Owners come from the evidence, never from the analyst's machine.** The user is the `Users` folder the profile came from. A `Users` folder *above* the imported folder (the analyst's own profile) is never taken as the owner. The SID is read from the evidence's own SOFTWARE hive (ProfileList, with `<SID>.bak` treated as `<SID>`). It is assigned only when the case holds one browser source: hives are stored flat and cannot be tied to a source, so with several the SID is withheld and the parse records why. A Firefox `profiles.ini` path that points outside the collected tree is ignored, not read from the analyst's disk.
- **Include browser cache** (on by default) in the Forensic Image and Offline Importer windows. The HTTP cache, Service Worker CacheStorage and Firefox `cache2` are most of a profile's size: on the test machine, 4.4 GB of 5.1 GB and 44,544 of 50,431 files. Turning the option off skipped them, cut the parse from 19 minutes to 41 seconds, and left every other table unchanged.
- **Crow-Claw** collects browser profiles with the same layout, through its file accessor, so a locked database falls back to a shadow copy. Browser is collected **last**, after `$MFT` and `$UsnJrnl`, so the largest artifact cannot fill the drive first. A full drive now stops the browser step, and a second collection refreshes the earlier copies instead of keeping them.
- **Re-parsing a case is stable.** Each profile's earlier rows are replaced, not added to. Twelve tables have no unique key and used to double on every re-parse, on live cases too.

#### Older browsers on images

Images are often years old. Measured on a 2016 image, these were read as empty and now parse:

- **Cookies:** pre-2018 Chrome names the columns `secure`, `httponly` and `persistent`. The cookie table failed on them, and 724 cookies are now read.
- **Sessions:** pre-M86 Chrome keeps `Current Session`, `Last Session`, `Current Tabs` and `Last Tabs` in the profile folder. 143 session entries are now read.
- **Top sites:** older Chrome uses a `thumbnails` table. 10 top sites are now read.
- A file that is present but unreadable, such as a `Preferences` file with damaged clusters, is reported as a warning for that profile instead of producing a silently empty table.

#### Browser search engines - creation date

`browser_search_engines.date_created` was read as Unix seconds; current Chromium stores it in WebKit
time (microseconds since 1601), like `last_modified` beside it, so every value came out blank. It is
now read by its scale (old builds' Unix seconds still read). A built-in engine stores 0 and stays
blank.

#### Registry: every user's hive replays its own transaction logs

Two parses of the same image gave 11,387 and 13,358 registry records. Every user's `NTUSER.DAT` and `UsrClass.dat` was collected into one folder and the name collisions renamed - `NTUSER.DAT` became `NTUSER_1.DAT` but its log became `NTUSER.DAT_1.LOG1` - so no hive kept its own logs. Which user got `_1` changed from run to run, and the replay applied one user's transactions to another user's hive, or none.

- **Each user's files keep their folder.** The Offline Importer, Crow-Claw and forensic-image extraction now collect to `Registry_Hives\Users\<name>\NTUSER.DAT` (with its `.LOG1` / `.LOG2`), `...\AppData\Local\Microsoft\Windows\UsrClass.dat` and `Windows\ServiceProfiles\<account>\NTUSER.DAT`. The same applies to LNK files and Jump Lists, which keep their owner's `Recent` folder. The same user name from a second partition or a second image gets `<name>_2`, and the choice is remembered in `live_acquisition\user_folders.json`, so a re-run lands in the same folder.
- **Two users' identical files are no longer deduplicated.** Each is its own evidence.
- **A log is replayed only into the hive it belongs to.** A log's base block carries its hive's path and resource-manager GUID; a log written for another hive is refused, recorded and logged. When this happens in a case collected by this version, it is reported as the *Registry log belongs to another hive* issue.
- **Cases collected before this version are matched by content.** In an old flat folder each hive picks the logs whose header names it, whatever they were renamed to. The two earlier runs of the same image now replay identically.
- **Rows name their owner after a replay.** A replayed hive is a temporary copy; its owner is now read from the folder it was collected from. Per-user hives are labelled `NTUSER.DAT[Hunter]`, the form the live parser writes, in the hive-state and structure tables, instead of `NTUSER.DAT[1]`.
- **Verified:** two separate image parses of `4orensics.001` now give identical counts in all 124 registry tables (13,314 records each).

#### Event descriptions

- **617 events now have their own text** (426 before), in `configs/event_descriptions.json`:
  - 160 taken from the wording this version of Windows ships for them;
  - Sysmon's 30 event types and PowerShell 4100 written by hand.
  Every ID in the forensic channels (Sysmon, PowerShell, Task Scheduler, Terminal Services, RDP, Defender, WMI, BITS, Firewall, AppLocker) now has text.
- **`scripts/curate_event_descriptions.py`** proposes more from a case's gaps. It never writes the catalogue on its own: entries are reviewed, marked approved, then merged. Existing cases keep their old text until re-parsed.

#### Event descriptions — one table, by provider

- **One curated table of (provider, Event ID) descriptions**, `configs/event_descriptions.json`, used by both the live and the offline event-log parsers. The lookup knows the provider. Before, an ID meant the same thing for every source, so EventSystem 4625 read "An account failed to log on", and 9,725 application rows read "Application hang.".
- **Wrong labels corrected:**
  - 4670 means permissions on an object changed;
  - 7036 names the state the service entered;
  - Winlogon 7001 is a user logon notification;
  - MsiInstaller 1033 means a product was installed;
  - WER 1001 is a fault bucket report.
- **Entries checked against Windows itself.** Where a provider ships a message template (`Get-WinEvent -ListProvider`), the wording follows it. Examples: URL reservations (`HttpService` 112, with the process and user) and VBS trustlets starting and stopping.
- **Offline rows keep their payload** after the sentence (`<text> | <EventData>`), so queries on `LogonType` and the like keep working.
- **Live fixes:**
  - timestamps are converted from local time to UTC (they were labelled UTC while still being local);
  - the user is the event's SID, not whichever insert came first;
  - an event log with an unfamiliar file name is routed by the channel recorded in its events.

---

### Chain of Custody

#### Chain of custody for live collection

- **One record per run**, `custody_<run id>.json` with a `.sha256` beside it. The record is never overwritten: each run gets its own file, and an edit after closing no longer matches the hash. The files appear under **Settings → Logs → Chain of custody**.
- **Per source file:**
  - path and size;
  - the modified, accessed and created times, read *before* the file is copied;
  - how it was read: standard copy, shadow copy (with its ID and creation time), raw disk or in-place read;
  - SHA-256 of the source and of the copy, and whether they match.
  A raw-disk read has no independent source hash, and the record says *unverifiable* rather than *verified*.
- **Live Parse All** reads evidence where it lies. Before parsing, it records an inventory of the files it is about to read: the hives, Amcache, SRUM, Prefetch, the event logs, LNK and Jump Lists, and the Recycle Bin `$I` files. Each gets its size, times and SHA-256. Locked files are recorded with the reason they could not be hashed. A hive acquired through a shadow copy gets a source/copy hash pair even though the copy is temporary.
- **The footprint on the target:**
  - every process Crow-Eye started (`vssadmin`, `powershell`, `net start VSS`, `esentutl`), with its purpose and how it ended;
  - services started;
  - shadow copies created, deleted, used, or left behind.
- **A warning when the case folder is on the drive being examined.** Writing there can overwrite unallocated clusters that still hold deleted files. The run is not blocked.
- **Image parsing** records the image's segments with their sizes and times, and its integrity (below).

#### Chain of custody — a ledger for the whole case, and what the records missed

- **Every case now keeps one ledger of everything done to it**, `<case>/logs/custody_ledger.jsonl`:
  case created and opened (with the Crow-Eye version and the collection settings in force), every run
  started and ended (with the SHA-256 of its record), every export, every evidence import into Eye
  (source and copy hashes, and failed imports), every settings change (old → new; API keys and other
  secrets are never written), and every correlation or Dynamic Linking run (the database's SHA-256
  before and after). Each line carries the SHA-256 of the line before it. Editing, removing or moving
  a line breaks the chain. A run record rewritten or deleted after it closed no longer matches its
  line, and a ledger cut short no longer holds the line a record points at. The viewer's new
  **Case ledger** tab walks the chain and says *intact* or names each problem.
- **A shadow copy Crow-Eye created could be left on the machine for good.** When shadow storage is
  full, Windows deletes the oldest snapshot to make room for the new one, so the count does not rise
  (4 → 3 on one live run). The count check then called the creation a failure. The new snapshot was
  never registered as Crow-Eye's own, the parsers recorded it as "used-existing", and it was never
  deleted. The ShadowID that `Create()` returns now decides: if it is on the volume, it is Crow-Eye's,
  and it is deleted at the end of the run. The record names the older snapshot Windows removed
  (`evicted-by-windows`), because that one cannot be brought back.
- **Records for the runs that had none:** every single-artifact parse button (live and offline), each
  Offline Importer collection or scan, each offline parse, and the image scan (a ledger line). An
  Offline Importer copy is now verified: the copy's SHA-256 against the source's, which the
  duplicate check had already taken. Before, the copy was never checked.
- **What a live parse reads and writes, written down:**
  - each artifact's outcome, with anything other than parsed / not on this machine as a failure (the
    record said "0 failures" while Parse Status listed failed artifacts);
  - the SHA-256 of every database the run wrote, `-wal` files included, hashed and not checkpointed;
  - how SAM and SECURITY were really read: an `NtSaveKeyEx` export, with the export's hash, deleted
    after the parse. They had shown only "PermissionError";
  - the raw `$MFT` and USN journal reads (data runs, records, journal ID and USN range), which have no
    file to hash;
  - each browser database copy, with source and copy hashes;
  - the SRUM working copy's SHA-256 before and after an `esentutl /p` repair, which can discard pages;
  - the time zone, locale and versions of the decoding libraries;
  - transaction logs, service-account hives, Desktop and Start Menu shortcuts, browser history files
    and `$R` Recycle Bin files in the source inventory.
- **Two runs open at once keep two records.** One global "open record" meant the second run took over
  the first's. A process that fails to start is now a failure entry. Files opened with their default
  program are recorded as footprint, as are elevation relaunches. After a parse is ended by force,
  its snapshot is deleted *before* the record is rebuilt, so the record says so.
- **The viewer** gains **Artifacts**, **Outputs** and **Case ledger** tabs. It also shows the
  environment, and which worker process did what. The operating system line was empty: it read keys
  the record never writes. Empty tabs now say what was *recorded* ("No process … was recorded for this
  run"), not what happened.

#### Chain of custody — what each artifact entry carries

- Each artifact's entry in the custody record now carries the rows read, new and already present, the database totals before and after, and, for failures, the error and the log excerpt.
- The record's summary and the ledger's "run ended" line total new versus already-present rows.
- Identity indexes a run adds to case databases are listed per artifact, with a "database changed" ledger line. Skipped MFT extension records and browser files that could not be read (locked) become custody warnings and failures.
- The custody viewer's Artifacts tab shows New, Already present and the error.

#### Chain-of-custody viewer

- **Case → Chain of Custody…** (and Settings → Logs) opens a run's record in a readable form:
  - who, where, when, and the options used;
  - an integrity badge: the record's SHA-256 still matches, or it does not;
  - every source with its verdict (copy verified, mismatch, not verifiable, read in place hashed or not hashed), filterable to problems only, and exportable as CSV;
  - processes started, shadow copies created and deleted (any left behind are marked), failures and warnings, and the raw JSON.

#### Shadow copies

- **Created, recorded and deleted.** A snapshot Crow-Eye creates is deleted when the collection or parse ends, by the `ShadowID` that creation returned. Crow-Eye never uses `vssadmin delete shadows /all` or "delete the newest", so a snapshot that was already on the machine is never touched. A delete that fails is recorded as *left behind* and shown in the collection summary.
- **An old snapshot is no longer read as the live file.** When a file was locked, the collector used the newest snapshot on the volume, whatever its age. With System Restore on, that can be weeks old, and the "live" SYSTEM hive or event log was then weeks old with nothing saying so. A snapshot older than 30 minutes is now not used:
  - if creating one is allowed, a fresh one is made;
  - otherwise the next method (raw disk, or the live hive export) reads the current file.
  The decision is in the custody record.
- **The setting that forbids snapshot creation now works.** *Settings → Parsing → allow snapshot creation* was saved to the user's settings folder. The parsers read it from a file in the program folder that nothing writes, so it always read as *on*. They now read the saved setting, and SRUM honours it too.
- **Advice that destroyed evidence is gone.** VSS error messages told the analyst to run `vssadmin delete shadows /all` or `cleanmgr.exe` on the target. Existing shadow copies and unallocated space are evidence. The advice now points to raw disk access and says not to free space on the machine.
- Turning snapshot creation off no longer crashes a locked-file copy.

#### Copies and headers

- **File headers are checked.** The validator compared an enum with the string the collector passes, so every file was reported valid without being read. Headers are now checked for:
  - hives and their transaction logs;
  - event logs and the SRUM database;
  - Prefetch (`SCCA` or the Windows 10 `MAM` wrapper);
  - LNK files and Jump Lists;
  - Recycle Bin `$I` records and `$MFT`.
  AmCache is now checked as a registry hive; it was being checked as SQLite.
- **Raw backup-semantics copy:**
  - `SeBackupPrivilege` is now enabled before the open; it was held but never enabled;
  - the open offers delete sharing;
  - an invalid handle is recognised on 64-bit Python;
  - failures report their real Windows error code instead of 0.
- **Collection timestamps are UTC.**

#### Image integrity

Every E01 is checked before extraction, by reading the section headers (seconds, not hours):

- whether it carries an acquisition MD5/SHA-1 to verify against;
- whether its segments hold the whole disk it declares.

On the test image, a 6.4 GB E01 declaring a 992.7 GB disk held **13.95 GB (1.4%)**: an acquisition that stopped early. It opened, its first gigabytes parsed, and nothing said the rest was missing. Both facts are now pre-flight warnings and are written to the custody record. Re-reading the whole image to recompute its hash is available, but is not run by default.

#### Files written to the target or the working folder

- **Temporary work goes under `<case>/tmp`** while a collection or parse runs: hive copies, log replays, the SRUM working copy and browser databases. Before, it went to `%TEMP%` on the examined machine's system drive.
- **SRUM's ESE engine no longer writes `edb.chk`, `edb.log`, `edbres*.jrs` and `edbtmp.log` into the working folder.** The engine's paths were never set. The two parameter calls that did exist used the wrong IDs: 64 is the page size, not *Recovery*. Measured on a SRUM database, the records are unchanged (49,669 / 214,557 / 2,997 / 2,153 / 58,945), and nothing is left in the working folder (5 files before).
- **The MFT/USN forensic report is written beside its database** in the case, not into the working folder.

---

### Correlation and Analysis

#### The Correlation Engine runs on large cases; collectors count right; faster parsing; every window styled

**Correlation Engine (Identity engine):**
- **Large cases run.** The engine read each feather completely into memory: one 3.8-million-row MFT feather was about 18 GB of Python objects on a 15 GB machine, and the app froze until it was restarted. Feathers now stream in batches. The engine keeps a small reference per row and reads the full row back only when a match is written.
  - Case 7.10.2026 loads in about 2.1 GB and correlates its 483,525 identities.
  - Peak memory on a small case: 979 MB → 650 MB.
- **The Execution panel shows what is happening:** "Loading mft_usn: 2,605,000 / 3,831,549 rows" and then "Correlating identities: n / N" on the bar, the status line and the log. Before, it showed "0/1 (0.0%)" for as long as an hour. The status update for each wing is no longer dropped.
- **Cancel works.** The engine received no Cancel at all (the call raised an error), and the window killed the thread after 2 seconds. It now stops between read batches and inside semantic mapping, saves its partial results, and the window waits for that to finish (see *Semantic mapping finishes* below).
- **No evidence is lost to the duplicate check.** Two MFT records of one file that shared a timestamp were treated as duplicates and one was dropped. Only identical rows are merged now. On the measured case, 15,909 matches keep records they used to lose; all other results are unchanged.
- **The Time Period Filter works.** It never filtered anything because of a parser error. The default stays on (the last year): records outside the range are dropped and counted under "Dropped by filter".

**Collectors:**
- **Crow-Claw shows 14/14.** It always collected all 14 artifacts, but a rate limit dropped the "(14/14)" message, so the window showed 13/14 for the whole Web Browsers step. The percentage no longer reaches 100% at the start of the last artifact, and the final summary counts partially collected artifacts. (It said 534 files / 3.74 GB against a real 52,969 / 9.44 GB.)
- **The USN journal is collected into a readable file.** The `:` in `$UsnJrnl:$J` wrote the journal into an NTFS alternate data stream behind a 0-byte file, so offline USN parsing read nothing. The copy is now `$UsnJrnl_$J`, and older collections are still read from their stream.
- **The Offline Importer reads EVTX, SRUM and LNK from a Crow-Claw collection.** They looked in other folder names and read nothing; LNK still reported success. Also:
  - DRIVERS, BBI and ELAM hives are detected;
  - "System Information.lnk" is a shortcut, not a registry hive;
  - AmCache is parsed once, not three times;
  - the MFT-USN correlation runs only when both MFT and USN parsed.
- Each parser log line is written once (they were written twice).

**Faster parsing, same output** (compared row for row before and after):

| Step | Before | After |
|---|---:|---:|
| Offline Registry parse | 153 s | 84 s |
| Offline MFT, 200k records | 30 s | 16 s |
| MFT-USN correlator, MFT query | 9.7 s | 4.0 s |

- **Registry:** each hive is opened once per parse instead of once per lookup.
- **MFT:** records are read in 4 MB chunks, secondary indexes are rebuilt once after the load, and a volume not yet in the database takes the plain insert path.

**Every window styled:**
- **Menu bars** (File / Edit / View / Help in the Correlation Engine, Feather Builder, Wings Creator and Offline Importer) and their drop-down menus are in the site look: separators, disabled items, check marks and submenu arrows.
- **Windows themed for the first time:**
  - Custody Viewer, Elevation, Dynamic Linking and its stats;
  - Search Filter, Partition;
  - the Case and Startup dialogs;
  - the Eye onboarding wizard, Case Setup, Case Summary and approval dialogs;
  - the main window's message boxes and progress dialog.

#### Semantic mapping finishes, and a stopped run keeps its results

Semantic mapping labels correlation matches ("Web Browser Activity", "LOLBin Execution") after they are written. On large runs it decided how long the whole correlation took:

| Semantic mapping step, 7.10.2026 (842,334 matches) | Time | Result |
|---|---:|---|
| Build the FTS5 prefilter index | 10 min | |
| One MATCH query over 855 search terms | 33 min | kept 99.8% of the matches |
| The rules themselves | 11 min | |

On a larger case (858,732 matches) the run was still in that query an hour later, and the results never opened.

- **The prefilter is skipped when it cannot filter.** A sample of about 2,000 matches estimates how many it would keep. At 50% or more it is not built, and every match is scanned. Skipping it can only add candidates: the rules still decide every label. On a 105,309-match wing the phase went from 138 s to 86 s with the same 4,669 labels.
- **Candidates are read and matched in chunks** (20,000 by default) instead of in one read that held every match's records. Progress is logged per chunk: "Semantic mapping: 40,000 / 102,349 matches scanned".
- **The prefilter index is rebuilt for each run.** One left by an earlier run held none of the new run's matches, so it found nothing and the phase fell back to a full scan after paying for the query.
- **Stop works inside semantic mapping.** The phase never checked the flag, so Stop waited 15 s and then killed the thread: no totals, no statistics, no log line. It now checks between chunks and every 500 matches. The window waits for the run to save what it found, staying responsive, before a forced stop is considered. On the test case the run stopped about 1 s after Stop and had saved everything about 8 s later. The labels found before the stop are kept.
- **A stopped run opens its results**, marked **CANCELLED**. The Summary shows its statistics and charts, and the Wing Breakdown says *Stopped*. Before, a stopped run opened nothing.
- **Statistics are saved before semantic mapping starts.** Feather statistics and the execution's totals were written only after it, so a run that stopped or was killed inside it left an empty Summary. They are now written as soon as the matches are, and again at the end.
- **A run that never finished still has a Summary.** When a result has matches but no saved statistics, the Summary counts them from what the run left behind:
  - matches and identities per feather, from the stored matches;
  - records per feather, from the feather databases the wing read.
  
  It shows a small **NOT FINISHED** label, the time as *unknown*, and *Not finished* in the Wing Breakdown.
- **Matches per feather counted every feather.** The count kept only the text before the first underscore, so `mft_usn`, `security_logs`, `amcache_app` and every other underscored feather read 0 matches and were missing from the Matches by Feather chart.
- **Identities are reconciled once per wing.** A streaming run merged every identity a second time at the end, finding nothing new, about 6 s per wing.
- **Opening a case no longer breaks the next correlation.** It closed every database connection in the process, including the engine's in-memory semantic-mapping index, and the next run logged "Cannot operate on a closed database" for every field it tried to map. Only the connections on the closing case's own databases are closed now.
- **Semantic mapping has its own log and settings.**
  - `<case>/logs/semantic_mapping.log`, also in `correlation.log`, listed under **Semantic mapping** in Settings → Logs. Each run records the settings it used, whether the prefilter was used and why, and its progress.
  - **Settings → Semantic Mappings → Semantic mapping engine:** worker threads, the coverage above which the prefilter is skipped, candidates per chunk, and an optional detailed debug log, written to `<case>/logs/semantic_mapping_debug.log` in UTC.
  - The options file `configs/semantic_mapping_config.json` is found from the application's folder, not the working folder.

#### Correlation engine 1.8.0

- **Faster time-window scans.** Each timestamp is now parsed once per feather instead of once per window, and the commonest ISO shapes skip the failing `strptime` formats. The parser was 74% of a profiled run. All 11 wings of the test pipeline found exactly the same matches as before (count and a hash over every match).

  | Measure (16-2-2026 pipeline) | 1.7.0 | 1.8.0 |
  |---|---:|---:|
  | User Activity Correlation | 531.7 s | **373.1 s** |
  | Full pipeline | 3,968 s | **2,278 s** |
  | Execution Proof Correlation | 230.7 s | **116.3 s** |

- **Fixed: a wing could return no matches because of a log line.** The time estimate was printed with a variable that one branch never set, and the error aborted the whole wing's scan. It hit "Security Control Tampering Correlation" whenever its inputs held no records at the estimate; on a case where they did, real matches could be lost the same way.
- **Unix timestamps convert to UTC** in the range and fallback paths, not to the examiner's local time.

#### Parse twice, store once — re-parsing adds only what is new

Running the live parser a second time on the same machine used to duplicate data or delete it.

- **Duplicated.** Amcache stored every row twice: its existence check compared raw value names (`ProgramId`) with column names (`program_id`) and never matched. Case 7.10.2026 held 13,681 Amcache rows, 6,841 of them distinct. SRUM removed duplicates only within one run (457,593 rows, 230,848 distinct). The MFT's child tables were a plain INSERT.
- **Deleted.** Event Logs dropped their tables at every run. Browsers deleted each profile's earlier rows. History and events that had since rolled out of the live source were lost from the case.

Every writer now stores only the rows the case does not hold yet, through one shared writer (`utils/dedupe_insert.py`, NULL-safe, backed by a plain identity index). Each parser reports how many rows it read, how many were new and how many were already present.

- **Event Logs** now store the event's own record number (`RecordNumber`, the EventRecordID). Two identical-looking events stay two events, and a re-parse matches on it. Events stored before the column existed are matched by content.
- **ShimCache** matches on path, modified time and size, so an entry that moves down the cache is not stored again.
- **Recycle Bin**'s check handles empty columns, and it no longer writes a `.bak` copy at every run.
- **Cases parsed before this release keep the duplicates already in them.** Only new parses are deduplicated.

| Second parse of the same evidence | Before | Now |
|---|---:|---:|
| Amcache (6,235 rows) | 6,235 stored again | **0 new** |
| MFT (1,208,321 records, offline `$MFT`) | child rows stored again | **0 new** |
| Event Logs (70,895 events) | tables dropped and rebuilt | **0 new**, earlier events kept |
| Browsers | each profile's earlier rows deleted | **kept**, only new rows added |

#### Parse Status says what a run added, and why something failed

- **New and Already present columns.** `Records` is now what the run read, not the database total. "MFT 19,090,321" was four tables summed. A re-parse reads like "1,024 record(s) read: 0 new, 1,024 already in the case."
- **Failed and partial rows expand** to the error, the parser's own warning and error lines with the full traceback (colour-coded), and the database rows before and after. **Show parser log** opens that artifact's lines. The loading dialog's checklist shows "12 new, 1,012 already present".
- **ShimCache no longer shows "Failed".** It read 1,024 entries, all already in the case. Nothing was written, so its database was unchanged, and an unchanged database was read as "produced no output database". That can no longer happen to any parser.
- **MFT no longer ends "Partial, exit code 1".** 24 extension records pointed at base records that do not exist (file content read as a record number). One foreign-key error rolled back the whole merge and left 53,223 extension records unmerged. Invalid ones are now skipped and listed as a warning. The exit code is no longer reported as a record count ("1 records").

#### Forensic image parsing says what went wrong

An image parse now ends the way a live parse does: with the **Parse Status Report**, one row per artifact, and above it the problems that belong to the whole run. Before, most of these reached the analyst as a console line or not at all, and an image that never opened reported *"Extraction completed successfully"* with 0 artifacts.

- **Checked before anything starts.** The file is identified by its content, not its name:
  - **Formats:** EWF/E01, Ex01, VHDX, VHD, VMDK (descriptor or sparse extent), ISO and raw (MBR, GPT or a bare volume).
  - **Unsupported formats are named:** L01, AD1, AFF, ZIP/7-Zip/RAR, QCOW and VDI.
  - **Each partition's boot sector is read** (NTFS, FAT, exFAT, ReFS, **BitLocker**), and its file system is checked for `Windows\System32\config`.
- **Investigator mistakes are named, with what to do:**
  - a later segment chosen (`.E02`, `.002`, or a VMware extent instead of its descriptor);
  - segments missing from the set;
  - a text file or a folder chosen as the image (the folder message points to the Offline Importer);
  - no partition selected;
  - the image stored inside the case folder;
  - a case folder that cannot be written;
  - too little free space.
- **Image problems are named, with what to do:**
  - an unreadable or corrupted image;
  - an image locked by a running virtual machine;
  - a missing reader library;
  - a BitLocker volume;
  - a partition with no readable file system. When the boot sector declares NTFS but the file system will not open, the issue says the image may be a partial acquisition.
  - no Windows installation on the selected partitions;
  - folders the file system refused to list.
- **Errors stop the run before extraction; warnings ask "Continue anyway?".** Every issue appears in the window's new **Issues** tab and in the report, with its cause and the fix.
- **Statuses that were wrong:**
  - An artifact found in the image but not copied was reported *Not found (not a failure)*; it is now *Failed* or *Access denied*, with the reason.
  - Artifacts left out by the type filter are *Not run: not selected*.
  - A batch that crashed recorded nothing; it now records what finished, marks the rest *Not run*, and adds a *Parsing stopped* issue.
  - A cancelled parse marks its unfinished artifacts *Not run*, and a cancelled live parse now shows its report.
  - Prefetch files with an unsupported version, which were skipped silently, now make Prefetch *Unsupported format* and name the files.
  - A dirty SRUM database read as *Dependency missing*; it now reads *Unsupported format*.
  - A registry hive the parser cannot read read as *Failed*; it now reads *Unsupported format*.
  - The MFT/USN correlation now has its own row.
- **One report per session.** Each run keeps its own rows, so a later run no longer overwrites an earlier report. The report no longer opens on top of the Parse Artifacts dialog. The header shows the image and the partitions read.
- **ISO images open.** The window passed a list of paths where pycdlib needs one.

#### Forensic Image Parsing window, redesigned

- **Two columns:**
  - **Setup (left):** the image with health badges; partitions with file system, size, a Windows mark and a BitLocker lock; extraction settings in a grid.
  - **Run (right):** progress with *Found / Extracted / Failed / Elapsed*, then *Artifacts*, *Log* and *Issues* tabs.
- **A fixed action bar** at the bottom: *Start analysis*, *Cancel*, *Parse artifacts*, *Export results*, *Close*. It sits outside the scrolling area and cannot be clipped. The window sizes itself to the screen, with a minimum of 960 x 640. The old fixed minimum of 1100 x 800 overrode the layout and hid the Start button.
- **The Windows partition is pre-selected.** Automatic parsing reads only what this extraction collected, instead of re-parsing every earlier import in the case. The same path in two images of one case no longer overwrites the earlier entry.
- **The window follows the case.** Opening another case clears the previous case's image, results and issues.

#### UBA, Timeline, LNK

- **UBA counts files, not journal records.** "N files were created" counted every journal record of
  every file (~3.4× the files; edits ~19×); it now counts files and gives the record count beside.
  A folder that was not read is *an unknown folder*, not *the drive root*; paths are matched by
  volume, record and sequence; the AmCache shortcut query read a column that does not exist; a bare
  `6` is no longer read as 2001-01-01 00:00:06; a time with an offset is converted to UTC.
- **The LNK and Jump List collection skips Crow-Eye case folders.** It walks the whole profile, and an
  examiner's old cases hold other machines' shortcuts - 433 of 636 LNK rows on one machine, which UBA
  then told as this user's activity.
- **Timeline:** the LNK and Jump List lanes were empty (their query named a removed column); the
  MFT/USN lane covered only its first 1,000 rows (only one of its nine time columns was narrowed per
  slice); the AmCache heat map read unparseable raw dates.

#### Browser behaviour in User Behavior Analytics — 16 new rules (65 → 81)

UBA reads the browser databases for what a person searched for, the kinds of site they went to, what they downloaded and opened, and what they left open.

- **Curated site categories**, kept as data in `uba/config/site_categories.json` (validated at start-up, editable without code):
  - file-sharing;
  - paste;
  - anonymiser (Tor and `.onion`, web proxies, throwaway e-mail);
  - cryptocurrency;
  - remote-access tools and tunnels;
  - AI chat;
  - hacking resources.
  SharePoint and Google Docs are deliberately not file-sharing: visiting them is ordinary work.
- **Only a person's own navigation counts**: a link, a typed address, a bookmark or a form. A frame, a redirect or a reload does not. An advert that embeds a file-sharing widget is not a visit to it. One event per user, browser, day and category, naming the hosts.
- **Web searches**, read from search-engine result pages (Google, Bing, DuckDuckGo, YouTube and others) and from what was typed into the address bar.
- **Downloads, graded once each**, in this order:
  - flagged by the browser;
  - from a risky source: a public raw IP, plain http, or a risky site. Suspicious when the file is also a program;
  - a program, script, installer or disk image. A double extension (`invoice.pdf.exe`) is called out;
  - anything else.
  Downloads from this machine (`127.0.0.1`) and the local network are never "risky": on a real case a local web app was the only plain-http source there was. Firefox downloads are read too.
- **Downloads the browser opened** are a separate event. The browser records *that* a file was opened, not when, and the event says so.
- **Inferred uploads.** A form submitted to a file-sharing or paste site, excluding sign-in and account pages. It is marked *inferred*: a form submission does not prove a file was attached.
- **Chat and collaboration apps** whose profile was collected: Discord, Slack, Teams, Signal, WhatsApp, Telegram, Element, Skype, Zoom.
- **Cryptocurrency wallet extensions** (MetaMask, Phantom, Coinbase Wallet, Trust, Binance, Exodus, Ronin, TronLink, Keplr, Rabby, OKX and others). Each says whether the wallet holds stored data. The storage is counted, never read.
- **Tabs open when the browser last closed.** Raised to *notable* when a tab was on a sensitive site. Read from Chromium's `Session_` files only: `Tabs_` files are the recently-*closed* list.
- **Media played**, with the watch time per site.
- **Saved logins** are now counted per site category (hosts and counts, never the account).
- **The history-gap rule works per profile** and includes Firefox: one browser's cookies say nothing about another browser's quiet history.
- **Fewer false findings in existing rules:**
  - Browser-shipped component extensions (Web Store, Microsoft Store, Edge Feedback, Brave) are no longer reported as risky extensions. They were 5 of 9 on a real case.
  - `signin.allowed`, a policy default, no longer reads as "signed in with sync".
- **Privacy.** No rule reads:
  - autofill or form-history values;
  - what was typed into pages;
  - saved-login usernames;
  - session tokens (a Discord token is enough to sign in as its owner);
  - extension or web-storage contents.
  Tests plant secrets in every one of those columns and check that none reaches an event.
- **The "Jump to a day" strip showed nothing on some cases.** It walked at most 800 days from the *first* event. One artifact with a timestamp years older than the rest used up all 800 days, and the strip read "800 days, 2 with activity" on a case with 28,000 events. It now ends at the latest activity and counts what falls before it.

#### Eye can run User Behavior Analytics

- A new Eye tool, **`query_user_behavior`**, runs the same 81 UBA rules as the UBA window, once per case, then answers for any day, range or user: who did what, when, how sure, and the evidence rows behind each event. It also reports which behaviours could not be looked for because their artifact was not parsed.

#### Eye setup

The first-run setup (and *Settings → Eye AI → Change backend*) is four steps with a step bar -
welcome, connection type, backend & model, test & save - pre-filled from the saved setup, with
missing fields and an unusual key format named in the window. **An API key is written to the
credential store only after the connection test passes** (it was stored before testing, so a typo
stayed behind). The test runs off the GUI thread and says why it failed in words; *Settings → Eye AI*
shows the connection with a *Test connection* button. Cancelling the first-run setup says so instead
of the Eye silently not opening.

#### Dynamic Linking statistics

After **Link Gathering** and after **Run Dynamic Linking**, a statistics window shows what was linked and where it came from. **Statistics of last run** reopens it.

- **By source:** every rule under the database and table it read, with the value and name columns, the rows read and what became of them: new, merged into a known value, already known, rejected. Skipped and failed rules say why.
- **By category**, **Linked in tables** (for each artifact table, how many rows now carry a linked name, and from which sources) and **Mapping database** (every link by source).
- **The same numbers are in `dynamic_linking.log`,** one line per rule and a summary per run. `GatherHistory` keeps them per run, so a past run can be shown again.
- **The counts are honest now.** Every rule used to report every mapping it saw, so a value already known counted again on every run. A rule whose database was missing printed a console line and left no record; it is now *Skipped: amcache.db not parsed in this case*. A failing custom rule read as *success, 0*.
- **Fixed:**
  - A name containing a comma (service display names such as `@%SystemRoot%\system32\x.dll,-101`) was never recognised as already stored, so every run appended it again and the stored name grew without limit.
  - A custom rule with a mistyped column linked the literal column name to every row; SQLite reads an unknown quoted name as text. The columns are now checked first and the rule fails, naming them.
  - The intelligence database's schema version was never written, so every open re-ran every migration.

#### Dynamic Linking statistics — after Link Gathering

- The **By source** and **By category** tabs were empty after *Link Gathering* followed by *Run Dynamic Linking*. They now show the gather's rules, labelled with when the gather ran.
- *Link Gathering* shows its statistics again (a button signal turned them off). The manual rule is kept in the run history. A reopened run shows its real time, not the moment it was reopened.

#### One User Activity dashboard: Shell Items & Registry

The registry tables that record what a user ran or set had no dashboard, beside shell-item tables that had one. They are sources of the same dashboard now, renamed **User Activity: Shell Items & Registry**, and every one of these tables has a **Charts** button that opens it on its own source:

- **On the day strip, by their own time:**
  - **UserAssist** (run count, focus count and focus time);
  - **BAM** and **DAM** (last run per account).
- **Listed undated:** these hold only their key's write time, one upper bound shared by every entry, and plotting all of them on that day would be a false spike. The key time is shown in each item's detail.
  - **FeatureUsage**;
  - **Compatibility Assistant**;
  - **File associations** (FileExts);
  - **ProgramsCache**.
- UserAssist's session counters and BAM's `Version` / `SequenceNumber` values are not listed.
- When the selected source has no dated items, the strip says so instead of drawing every source as an empty row.

#### One User Activity view

- **One window, one timeline.** The **Charts** button on any of the 28 Shell Items and registry user-activity tables opens the same *User Activity* window. A second click re-points that window instead of opening another. Every source stays on the timeline and the clicked one is highlighted; *Show only* still filters.
- **Camera, microphone and location use** (`ConsentStore`) is a source of its own, dated by each app's last-used start time.

#### Anatomy for every table, inside the app

- **Every User Activity table has its own section**, on the Shell Items or the Registry anatomy page. Each section covers:
  - the key and hive;
  - the value format and how Crow-Eye decodes it;
  - which timestamp exists and what it bounds;
  - what the table proves and what it does not;
  - how it appears on the dashboard.
  Every table's **Anatomy** button opens its own section.
- **The pages ship with Crow-Eye** (`docs/anatomy`, 13 pages) and open in an in-app viewer at the right section, with no internet needed. Links between bundled pages stay in the viewer; anything else opens in the browser.
- **16 registry keys the parsers read were missing from the Registry anatomy key tables.** These included BAM, DAM, CIDSizeMRU, StartPage2, Regedit, credential providers and firewall rules. The check that guards the page could not see a key path written as two adjacent string literals; it now reads string constants the way Python joins them.
- **A dead registry read was removed.** The live parser read `Control\SessionManager\...` (no space) for two values that do not exist there. It never returned a row, and the page listed the misspelt key.

#### Charts load without freezing the window

Every dashboard ran its queries on the GUI thread, so the window froze and the loading overlay stopped mid-animation. Queries now run on a small thread pool and answer through a signal. The newest request wins, so an older answer cannot overwrite a newer view or clear its overlay.

| Measured on case 7.10.2026 | Before | Now |
|---|---:|---:|
| Longest GUI-thread stall while any of the 7 dashboards loads | the whole query | **172 ms** |
| Timeline: one day click | 70 s | **3.1 s** |
| SRUM: one day's detail | 8.9 s | **0.05 s** (the date filter now uses the index) |
| SRUM: open | 25–37 s | **6.5 s**, loaded once instead of twice |
| Browser: open (bounds) | 3.3 s | **0.3 s** |
| MFT/USN: alternate-data-stream files | 5.2 s | **0.02 s** after a re-parse (new index) |
| MFT/USN: events by reason | 2.6 s | **0.5 s** after a re-parse (covering index) |

- Each answer is cached until a filter or the database changes.
- Each call's duration and size go to the visualizations log.
- Long application, domain and path names on the activity charts are shortened in the middle instead of losing their start.
- SRUM's CPU-cycles total is shown compactly, with the exact figure on hover.

---

### Collection, Parsing and Logs

#### When Crow-Eye is not running as Administrator

- **Asked before, told after.**
  - **Before** a live parse that needs rights (Parse All, or a single MFT, USN, Prefetch, SRUM, Amcache, event-log, registry, browser or Recycle Bin parse), one question: *Restart as Administrator*, *Run anyway* or *Cancel*. Parse All used to refuse outright.
  - **After** a live parse that Windows refused, one pop-up names the refused artifacts and offers the restart. It appears in place of the Parse Status report, never as well, and the report is one click away.
- **Restart as Administrator reopens the same case** (`--open-case`). It is refused while a parse is running. If the Windows prompt is declined, Crow-Eye says so and carries on.
- **A refusal is now called a refusal.**
  - `PermissionError`, Windows errors 5, 32 and 1314, and the MFT and USN parsers' new exit code 5 are classified *Access denied*, whatever language the message is in.
  - A parser that stops itself (`sys.exit`) is *Failed*.
  - Amcache and SRUM read **"does not exist"** on every unelevated run. `os.path.exists()` answers *False* for a file Windows refuses to show; they are now *Access denied*, with the reason.

#### Parser processes: cancel, close and timeouts

- **Cancel stops everything.**
  - Queued parsers are dropped. Running ones get 3 seconds, then their process trees are ended, including the processes they started (esentutl, PowerShell).
  - Cancelling used to wait for every queued parser, and the pool workers outlived Crow-Eye.
  - What had not finished is reported *Not run (cancelled)*.
- **Closing the window mid-parse asks first:** *Wait for it to finish* or *Stop and close*. Closing during a loading screen warns that a database may be incomplete.
- **A killed run still leaves a custody record.** Each process journals its share as it works. If the run had to be ended, the record is rebuilt from the journals and marked *terminated*. A run cut short by a crash is rebuilt the next time the case opens. The run's shadow copy is still deleted.
- **One shadow copy per run.** The collector makes one before the parsers start, and every parser reads from it. The pool workers' file reads and shadow-copy use now reach the run's custody record, and their scratch files go under the case instead of the examined machine's `%TEMP%`.
- **A parser that calls `sys.exit()` no longer ends the whole collection.** MFT, USN and the correlation used to never run after it, with nothing reported.
- **The MFT–USN correlation no longer runs when the MFT was not parsed.** It reported an empty correlation as if it had worked. It is now *Not run*, with the reason.
- **Every subprocess call has a timeout**, enforced by a source-scan test. Before, a hung parser held the correlation, and with it the whole live Parse All, indefinitely. npm and parser timeouts end the whole process tree.
- **Parser processes start faster and leaner.** Each one re-ran Crow-Eye's whole start-up: pip scans, the React build check and, unelevated, the UAC prompt, which then exited the child before it parsed anything. About 0.9 s and 70 MB per child, down from 1.3 s and 132 MB, with no launches.

#### Loading and responsiveness

- **Event Logs are paged.** 85,000 events were built into 800,000 table cells at every case open. The three log tabs now show only the rows on screen.

  | Measure | Before | After |
  |---|---:|---:|
  | Event Logs load (3.10.2026 case) | ~2.9 s | **0.30 s** |
  | Crow-Eye memory after opening that case | ~1,060 MB | **~750 MB** |

  - Header clicks sort the whole table, numerically for numbers.
  - The toolbar search queries the logs' database.
  - Export writes every row (37,052 System rows in 0.4 s).
  - The headers read *Event ID*, *Time (UTC)*, … instead of the database column names.
- **Registry tables are filled once per case open.** Two loader steps refilled the same tabs before the main load, and the LNK table a second time. Removing them was checked on a real case: 159 tables and 40,016 rows came out identical.
- **Registry and partition tables fill with sorting off.** With sorting on, every cell write re-sorted the table, and a row that moved mid-fill took the rest of its cells to the wrong row.
- **No event-loop pumping inside fill loops.** A click handled in one of those pumps could start a second load inside the first. Loading screens keep animating through a repaint-only call, and a case load can no longer start again inside itself.
- **Parse Offline Artifacts' automatic scan runs off the window.** The scan and the parse used to run on the GUI thread. They now run in workers, and Cancel works.
- **Image parsing can be cancelled** once extraction has finished. Before, Cancel reached nothing.
- **The Windows partition is remembered per case** instead of being detected again at every open.
- **Search results switch to the right tab.** The toolbar search never switched to a nested tab for most tables.

#### Faster parsing

| Measure | Before | After |
|---|---:|---:|
| Brave Service Worker cache, 26,674 entries | 332 s (8.7 ms per cold open) | **~45 s projected** (1.2 ms per cold open, eight in flight - measured on Edge's cache); identical rows |
| MFT and USN during live **Parse All** | started after the whole pool | **run beside the pool** in a process of their own |
| LNK & Jump Lists profile walk (873,260 files) | 30.6 s | **18.1 s**, the same 1,122 files in the same order |
| Feature gate "does this case have data" (GUI thread) | 1.9 s | **0.006 s** |
| Image extraction | each file written, then read back for its SHA-256 | **hashed while it is written** |
| Prefetch | full database integrity check before every file | **once per run** |

- **USN journals extracted from images keep their oldest records.** The sparse-`$J` probe could skip up to 4 MB of data at the start of the journal.

#### Parse and loading screens; logs in colour

- **Logs read like an IDE**: in Settings → Logs, in the parse dialog's log pane and in the full-log window, with a level filter (all / warnings / errors), find, follow and copy.
- **A parse row says what its warning was.** Hover it: every message and skipped file is listed. The amber icon now comes from the artifact's outcome, so one corrupt Prefetch file of 362 no longer turns the row amber. The Time column no longer flickers. The Crow-Eye logo is back in the dialog.
- **Prefetch says why** a file could not be parsed or was only partly parsed.
- **After a parse, the loading screen**, not the parsing screen, fills the tables, one row per step. The Parse Status report opens as soon as it closes, where before it waited out a fixed 1.8–3 s.

#### The parsing dialog shows a live checklist

- **One row per artifact, filled in as it runs:** status, records, time and warnings. *Not found (not a failure)* rows read as such, in the Parse Status vocabulary.
- **What is happening now:** a *Now:* line shows the artifact and the file or hive being read, or the parser's own progress line, which used to be dropped. The clock gives an estimate of the time left once two artifacts have finished.
- **The log is still there,** folded behind *Show log (n lines)*.
- **The single-artifact parse buttons:**
  - the dialog shows the parse's own title;
  - it says *parsed and loaded N records*, *nothing to parse* or *see the Parse Status Report* instead of *completed successfully* before anything was checked;
  - Cancel leaves the parser to finish its current work and does not load its results.
- **The loading stays visible:** the console capture now continues through the table load after a live parse. Loading parsed data after an offline or image parse shows its own checklist; it used to fill the tables with nothing on screen.

#### Loading and parsing dialogs

- **A cancelled or crashed live Parse All always ends.**
  - The collector always reports *done*, even when it is cancelled or raises.
  - The progress reader stops when the collector process dies instead of waiting for ever.
  - Cancel shuts the workers down off the GUI thread.
- **Background workers can no longer finish unseen.** Five wait loops started the worker before connecting to its *finished* signal, so a fast worker could finish first and leave the dialog waiting. A worker that raises `SystemExit` now reports back too.
- **Fewer, cheaper updates:**
  - log lines are batched in the worker process (every 200 ms) and in the dialog;
  - the log view keeps the last 5,000 lines and HTML-escapes them;
  - the progress slots no longer re-enter the event loop.
- **The event-log tables fill without freezing** the window: sorting is off during the fill and the UI is pumped every 50 rows.

#### Busy notice, and the window that is in the way

- Clicking a tab or a table while Crow-Eye is still parsing or loading now says so: a popup the first time in a run, then a banner. The click still goes through.
- A click on the main window while a dialog is waiting for an answer brings that dialog forward and names it.

#### Offline Importer

- **Select Files** collects only the chosen files; choosing a folder replaces the selection.
- Parse results are matched to their artifacts by id, not by position, so the right files are marked parsed.
- **Collect** after a **Scan** copies exactly as a direct collection does: per-user folders, `.LOG` files beside their hives, the same ids, in the background.
- Failures are reported as failures ("completed with N error(s)"), and the found / copied counters move during the run.
- **Cancel** keeps everything copied so far, indexed and ready to parse.
- Event Logs and SRUM type filters. The ShimCache filter matches what the detector finds.
- A file already in the case is "already in the case", not a failure. A case switch clears the previous case's results.

#### Parse automatically after collection

New in **Settings → Parsing** (on by default): the Offline Importer parses exactly what a COLLECT
brought in as soon as it finishes (a SCAN still waits for Parse); *Parse Offline Artifacts* scans and
parses a never-scanned acquisition without asking; and Image Parsing's *Parse automatically after
extraction* starts from it. Off, each stops at a ready Parse button.

#### Logs: Offline Importer, Crow-Claw and image parsing

- **Their own case log files**, listed under their own groups in **Settings -> Logs**:
  - `offline_importer.log`
  - `crow_claw.log`
  - `image_parsing.log`
- **Settings -> Logs also lists** what these tools leave in the case:
  - the collection manifest;
  - the import results and the artifact hash list;
  - the image partition table;
  - `parsing_errors.log`.
- **Records that were lost:**
  - The window logs of all three tools were never saved; they now go to these files.
  - Crow-Claw and image parsing printed to a console that the packaged build does not have; they now use the logger.
  - Crow-Claw's error traceback is now logged.
  - The image window loaded a second copy of the importer, whose records never reached a log.
- **Rotated backups stay with their file:** `crow_eye.log.1` is grouped with `crow_eye.log`. Without an open case, the panel shows the application log. `console.log` now rotates at 10 MB; it used to grow without limit.
- **The Offline Importer opened from Crow-Eye collected into `~/.crow_eye/tmp/scan`** until a first collection finished, and kept the previous case after a case switch. It, Crow-Claw and the image window now bind to the open case every time they open.
- **Smaller fixes:**
  - The importer's in-window log is written from worker threads safely.
  - Registry parsing no longer writes `regclaw_errors.log` into the working folder.
  - Printing no longer raises in the packaged build when no case is capturing output.
  - Check-mark glyphs in Crow-Claw's shadow-copy checker and the importer's launcher are now ASCII.

#### Every parser and analysis step reaches the case logs

- **Each parser run is framed in `parsers.log`:** a start line with the source, everything the parser prints while it runs (at its level: `[ERROR]` lines as errors, `[WARNING]` as warnings), and a closing line - for example `done: Registry, 13,314 records in 127.9s, 0 warning(s)`. Most parsers report only through `print()`; their output used to reach `console.log` with no name on it.
- **Live Parse All runs its parsers in worker processes, which had no case logging at all.** Their records are now sent to Crow-Eye and filed under the case.
- **Loggers that reached no component file now do:**
  - the registry parsers (live and offline), the SECURITY-hive and user-identity readers, which logged on the root logger;
  - parser modules imported by their own name (`Regclaw`, `MFT_Claw`, `USN_Claw`, ...).
- **What the parsing dialog shows is also logged.**
- **More components log their work:**
  - the correlation pipeline's run;
  - UBA's per-extractor counts and rule coverage;
  - the main window's parse and load phases (`gui.log`).
- **Fixed:**
  - The USN parser created `.\Target_Artifacts` and an empty log in the working folder whenever it was imported; its run log now opens beside its database when it runs.
  - The MFT parser added a new log handler on every run, so a second parse wrote each line twice.

#### From the last case's logs

- VSS writers in state 5 (waiting) are no longer reported as failed.
- "VSS service not running" is informational (it starts on demand), and the 116 "VSSErrorReporter initialized" lines are gone.
- Registry: USB `Properties` access-denied (expected even elevated) is one summary line with a count, and missing Shellbags keys are no longer errors.
- Traceback lines after the first are logged as errors, not information.
- Browser files locked by a running browser (Cookies) are copied through the shadow-copy and raw-read chain. A file still unread is a Parse Status detail and a custody failure, never a plain "Parsed".
- The Database Search window no longer raises on close.
- Eye's built-in queries name the columns that actually exist (Prefetch, Amcache, Run keys, RecentDocs).

---

### The Look

#### The look — the website's theme, colour-coded columns, one scroll bar

- **The loading dialog is now in the website's style:**
  - a dark card with a hairline edge, rounded corners, a soft indigo glow, and the indigo → cyan strip
    along the top;
  - the title in Barlow Semi Condensed, with no pulsing box; a slim gradient progress bar with its
    count above it; the "Now:" line and the log in JetBrains Mono;
  - a rose-on-hover Cancel, and checklist icons in the site's tones.
  
  It can be **moved** (drag any empty part) and **resized** (the corner grip). The text no longer
  overlaps when the dialog is made small.
- **Both website fonts ship with Crow-Eye** (SIL Open Font License; the licences sit beside the font
  files). A Qt stylesheet only ever uses the first font it names, so a font that was not installed
  fell back to Qt's default. The fonts are now registered at start-up.
- **Standard columns have their own colour in every artifact table:**

  | Column | Colour |
  |---|---|
  | times (created, modified, accessed, last written …) | cyan |
  | paths, keys and URLs | light indigo |
  | hashes | violet |
  | users and SIDs | pink |
  | sizes | orange |
  | names | bold white |
  | `parsed_at` | dimmed |

  Counters, durations and time-zone fields that only look like times (`times_used`, `focus_time`,
  `time_zone_name`) stay plain.
- **Settings → Eye AI fits the window.** At the 900 × 700 minimum the page was 866 px wide in a
  690 px view, with no horizontal scroll bar, so the right of every row was cut off, including Test
  connection and Change backend. Long checkbox texts now wrap, the form lets rows wrap, the buttons sit
  under the connection details, and number boxes stop at a sensible width. Minimum content width:
  337 px.
- **One scroll-bar style everywhere:** slate on near-black, indigo on hover, cyan while dragged. The
  custody viewer, Parse Status, the Offline Importer and the correlation windows showed native white
  scroll bars, and five different recipes were in use elsewhere.

#### Columns — four new colour groups, a brighter `parsed_at`

- `parsed_at` is a brighter slate (`#94A3B8`).
- **IDs and record numbers** (amber), **registry values and data** (green), **flags and status** (rose), and **network and devices** (teal) join the seven existing groups. They rank below those groups, so `file_id` is still a hash, `user_id` a user and `last_seen_time` a time.

#### Collectors and Settings keep their style; the progress bar is still when idle

- **The Offline Importer's progress bar moved while nothing ran.** The bar draws a gliding light at 0 and a sweep until it reaches 100%, and the importer never switched that off. It moved at open, after a cancel, and after an error. It now moves only while a collection runs, and a finished run shows 100%. Forensic Images already behaved; Crow-Claw uses a plain bar.
- **Why windows lost style.** Converting a window to the website's look removes each widget's own style sheet and keeps what it meant as a role. That reading kept only colour and size, so these were lost:
  - bold at weight 600: every Settings form label and Crow-Claw's admin line;
  - boxed read-outs: "current file" and "access method";
  - underlined panel titles;
  - the monospace timer;
  - small bold headings;
  - the green "Enabled" checkbox.

  A `:disabled` colour also made every Eye AI checkbox label grey, and a change in round 18 promoted 14pt labels to page titles. The reading now keeps all of these, as roles in the one site sheet: read-out, mono, caption, underlined section, bold, and checkbox status colours.
- **One button family everywhere.** Plain buttons now use the same font as the main-action, outline, delete and amber buttons beside them, so toolbars no longer mix two fonts. Crowded rows (Settings → Semantic Mappings) use a dense size so nothing is clipped.
- **Settings sets its look before building its pages**, as every other window does. It also opens faster: 6.0 s → 2.0 s on the measured machine. Its message boxes and the fallback mapping dialog are themed too.
- **Crow-Claw:** the artifact details and configured-paths panes are mono log wells again, like the collection log.
- **Parse Artifacts:** the summary and error dialogs it opens after a run were never themed. They are now. Failed and partial artifact types are coloured too, not only successes.
- Table headers keep the round-16 design: transparent, with a hairline.

#### The Correlation Engine in the website's look

The Correlation Engine now uses the website's look, as the loading dialog, Settings and the collectors already do. The engine covers the main window, Feather Builder, Wings Creator, Semantic Mapping, the pipeline and results dialogs, and Settings → Pipelines. Nothing moved and nothing was renamed: only the style changed.

- **Fonts:** Barlow Semi Condensed and JetBrains Mono everywhere, including the execution log, the JSON viewer and the charts. Before, the engine used Segoe UI, Arial, Consolas and a font the app does not ship.
- **One button family by role**, instead of green, blue, red, orange and slate buttons that each meant something different:
  - RUN, Resume, Load Selected, Save and Add use the indigo→cyan main-action button;
  - everyday actions (Load Last Results, Browse, Export, Refresh, Reset, Select All, Cancel, Close) use an outline;
  - Cancel during a run, Remove and Delete are rose;
  - states in between (Pausing…, Cancelling…, Retry) are amber.
- **Colours that carry meaning keep it**, on one set of status colours:
  - scores: high green, medium amber, low rose;
  - severities: critical and high rose, medium amber, low green;
  - statuses, validation messages and the Issues tab.

  An old table rule painted every cell one colour and hid all of these. It is gone.
- **Charts:** the same feather now has the same colour in the bar and the pie chart. Both charts use the site palette.
- **One style source:**
  - the three old `.qss` files are deleted;
  - about 390 per-widget style sheets are down to 10, most of which only clear a sheet or set a log well;
  - the window's sheet is no longer applied twice.

  The engine window opens about 25% faster (0.058 s → 0.044 s). Loading results takes the same time (12.5 s on the measured case).

| Measure | Before | Now |
|---|---:|---:|
| Correlation Engine per-widget style sheets | 389, plus 3 `.qss` files | **10**, no `.qss` |
| Engine windows left open after reopening it | one more per open | **one per case** |
| Engine window construction | 0.058 s | **0.044 s** |

**Fixed while restyling:**

- **Results**
  - In the time-window tree, the score and semantic colours were drawn one column to the right.
  - **Critical** severities were painted green.
  - Score colours looked for words the engines never write (Strong / Good / Partial Match; Critical … Minimal), so most scores had no colour.
  - The scoring breakdown never updated when a match was selected (wrong number of arguments, error swallowed), and a stored selection was read from the wrong place.
  - The results tab's filter controls did nothing.
  - Unmapped fields in the semantic table raised an error instead of showing "(no mapping)".
  - The pie chart highlighted the wrong slice under the cursor.
  - **Retry** stacked a new error banner on top of the old one each time.
- **Detail dialogs**
  - Time-window search looked for semantic values under a key that never exists.
  - A record without a confidence value stopped its detail dialog from opening.
  - An internal `_semantic_mappings` entry showed as a field row.
  - Column titles were clipped.
- **Windows**
  - Reopening the Correlation Engine built a new window every time and never released the old ones. It now raises the window already open for the same case.
  - Feather Builder and Wings Creator windows are released when closed.
  - A second notice in the pipeline builder within 3 seconds restored the first notice instead of the text before it.
  - The Anatomy offline dialog was never styled: it imported a name that did not exist.
- **Labels**
  - "Simple & Advanced" and "Semantic Mapping & Matched Rules" showed as "Simple _Advanced" and "Mapping _Matched" (a single `&` is a keyboard-shortcut marker).
  - "Tip: Tip:" is now "Tip:".
- **In the shared theme, so other windows benefit too**
  - In a dialog styled after it was built, columns sized to their content clipped their titles ("XECUTION II").
  - In those dialogs, button and title fonts fell back to plain text, and OK / Save / Cancel came out lower-case.
  - A status label was drawn inside a coloured box.

#### Crow-Claw, Offline Importer and Forensic Images in the website's look; a better Row Details

- **Crow-Claw, the Offline Importer** (and its Parse Artifacts dialog) and **Forensic Images** take the same look as Settings and Database Search. Colours that carry meaning keep it:
  - the administrator pill and the green/red path labels;
  - Found / Collected counters;
  - the image window's badges and its Issues tab, whose severity colour now shows.

  Progress bars keep their text ("37% - Collecting: Prefetch (3/12)").
- **Row Details** (double-click any row) keeps its sections and indentation: File Info, Timestamps, Attributes, Directories / Files side by side, Resources. On top of that:
  - a header card;
  - a filter box;
  - *Show empty fields*;
  - every other field in a card for what it holds (Times, Paths & names, Identity, Values & flags, Other);
  - values in their kind's colour (the table columns' palette);
  - right-click to copy a value.
- **Copy all and Export (TXT, CSV, JSON) now work.** They used to produce an empty clipboard and an empty file.
- **Fixed while checking the work** (an independent review of rounds 15-17):
  - A **browser** re-parse kept the first parse's values (visit counts, last-access times, extension versions). A changed row is now updated in place, still never duplicated.
  - A recycled cache file name no longer overwrites a body an earlier row describes.
  - A live Parse All sat in the browser stage for 40+ minutes on this machine: the re-parse check scanned nearly a profile's whole storage for every row. The check is now an index seek: 60,000 rows re-checked in 0.4 s, and a first parse skips it.
  - A failed SRUM batch no longer stores rows twice when retried row by row.
  - A parser that stops without a result is reported FAILED again, not "no new rows".
  - MFT / USN no longer carry the previous run's counts into a failed run.
  - **Elevated live parse: the SAM and SECURITY hives were never exported.** A decorator had been displaced onto a helper added above the export function, so every live parse raised and dropped the user-account and security-policy detail. Found by running the suite elevated; on this machine the export now yields 7 accounts and the temporary copies are deleted.
  - Event Logs' new `RecordNumber` column is in the correlation engine's fallback columns, so an older case still builds an empty feather.
  - Each window's sheet is applied once (the app's scrollbar policy made it look different and it was applied twice). Opening is about as fast as before: Row Details 15 fields 0.016 s, 150 fields 0.11 s.

#### Settings, Eye AI and Database Search in the website's look

The loading and parsing dialog's design now covers the rest of the windows people configure and search in:
- **Settings**, every page, including Eye AI and Logs;
- Eye AI's **Advanced Context & Token Budget** dialog;
- **Database Search** and **Saved Searches**.

They share one theme (`ui/site_theme.py`):
- Barlow Semi Condensed and JetBrains Mono;
- slate cards;
- pill buttons: indigo for the main action, a ghost outline for the rest, rose on hover for anything that stops or deletes;
- quiet tables with uppercase headers and indigo selection;
- the log views' level pills.

The Eye's own name is never uppercased.

- **Faster:** each window sets one stylesheet instead of one per widget. Database Search's per-widget styling (about 490 lines) is gone, and scrolling 5,000 results repaints faster (0.16 s -> 0.09 s for 50 steps).
- **No glow, native frame.** These windows keep the native Windows title bar, with snapping, minimise and maximise. There is no translucent glow, which would make every table repaint cost more.
- **The loading dialog's glow is cached.** It used to be redrawn as 14 rounded outlines on every progress-bar frame. It is now drawn once per window size: 0.16 ms -> 0.008 ms a frame, pixel-identical. The logo's breathing halo stops while the checklist is shown.
- **Fixed on the way:**
  - The Advanced dialog's Token Budget spin boxes were squeezed until their numbers did not show. Each tab now scrolls.
  - Table headers drew in the general font instead of their own.

- **The Parse Status report that opens after a parse showed plain white table headers.** Opened over the main window, its table header was styled under the main window's look before the report's own, and setting the report's look later never reached it. Opened from the Case menu it looked right. The header is re-styled once the report's look is set, and its count columns are right-aligned over their numbers.

---

### Platform

#### Linux (Python source version)

Tested in Docker. A first-run test used Debian 12 with only the system Python, which is externally managed (PEP 668). A second container (`python:3.12`, Xvfb) opened every window and parsed a collected Windows case.

- **It now starts on Debian 12 / Ubuntu 23.04+.** It used to `pip install` into the system Python before creating its venv, and those systems refuse that, so Crow-Eye exited. It now creates its venv first and installs inside it.
  - A half-made venv (no pip) is rebuilt instead of reused.
  - A missing `python3-venv` gets the `apt install` line.
  - Start-up output printed before the restart into the venv is no longer lost.
- **A root `requirements.txt`**, with Windows-only packages marked, and the Qt system libraries Linux needs listed in it. `beautifulsoup4` was missing from the requirement list.
- **Every module imports on Linux** (482 of 488). The other 6 fail the same way on Windows: five modules nothing imports, and Crow-Claw's setup script. Windows-only imports in the Recycle Bin parser, the file signature detector and the USN parser are guarded. The USN parser no longer runs `pip install wmi` at import.
- **Windows:**
  - the main window builds with all 210 tables;
  - the Eye, the User Activity dashboard and the Anatomy viewer render;
  - Crow-Claw and the Partition Analyzer are hidden, since they need a running Windows.
- **Fonts:** `Consolas` and `Segoe UI` map to DejaVu Sans Mono / Noto / DejaVu Sans. Hex views, offset columns and path tables were rendering in a proportional font.
- **Web views paint without a GPU.** In a VM or container with no GPU render node (`/dev/dri`), Chromium's GPU process fails and a web view can stay blank. Software rendering is now used there (`CROW_EYE_KEEP_GPU=1` overrides). The sandbox is turned off where the kernel forbids unprivileged user namespaces.
- **The same collected case parses identically on both platforms.** A 2016 Windows case was parsed through the Offline Importer on Windows and on Linux, and all 196 tables in 33 databases have the same row counts. The comparison covered the registry, AmCache, event logs, Prefetch, LNK/Jump Lists, SRUM and MFT.
- **AmCache found nothing on Linux.** The parser looked for a lowercase `amcache` folder; the collected folder is `AmCache`.
- **Offline browser parsing found no Firefox profile on Linux.** The vendor paths were joined as one folder name (`Mozilla\Firefox`).
- **Other path and setting fixes:**
  - ShimCache finds a `system` hive whatever its case;
  - image extraction classifies folders correctly;
  - settings live in `~/.config/crow-eye`;
  - the default cases folder is `~/Cases`;
  - a Linux host is not reported as a failed Windows-partition detection.

---

### Bug Fixes

- **Eye AI did not open:** `NameError: name 'CrowEyeStyles' is not defined`.
- **Undefined names, each a `NameError` when its line ran:**
  - `identity_correlation_engine` had no `logger` (142 uses);
  - `report_parser` had no `json`, so chart blocks came back empty;
  - the case coordinator had no `os`, so scanned-artifact metadata was never saved.
  The same class of bug was fixed in the timeline renderer, the timestamp parser, the feather builder, the SRUM offline parser, AmCache and Image parsing. A test now runs pyflakes over every package.
- **An exception inside a Qt slot no longer closes the application.** It is logged and shown.
- **`show_error` referenced the exception after its block had ended**, which aborted the application.
- **The analyst's own name was put on the evidence's registry hives.** For a case stored under `C:\Users\<analyst>\...`, every user hive collected without a profile folder was labelled `NTUSER.DAT[<analyst>]`. The owner was read from the analyst's own `Users` folder above the case. Now only a `Users` folder inside the collected tree names the owner. Found by comparing a Windows and a Linux parse of the same case: the Linux case path had no `Users` folder, and the labels differed.
- **A parse hung with no error** when the root logger had no handlers (scripted or headless runs). The first warning it printed was written back into the captured output from inside the capture, which then waited on its own lock.
- **Crow-Claw and Dynamic Linking could be opened mid-parse.** They were the two openers without the busy guard every other tool has; Dynamic Linking now also waits for case data.
- **Shellbags lost `value_name` in the correlation engine** when a feather was built from the fallback column list, which had not been updated when the column was added to the parser.
- **The offline event-log, LNK and live event-log databases went to the working folder** when `Target_Artifacts` did not exist yet.
- **SQLite `-wal` rows were dropped.** Copied databases were opened with `immutable=1`, which makes SQLite ignore the `-wal` file. Measured: 1 of 2 committed rows was read. Copies are now opened read-only with the WAL applied. This affected live parsing as well.
- **Same-named databases shared a temporary folder**, so one profile's leftover `-wal` could attach to another profile's database. Each copy now gets its own folder.
- **The same profile was parsed twice on live systems.** `AppData\Local\Application Data` is a junction back to `Local`, so a profile found through it was listed twice (Spark Desktop on the test machine). Profiles are now deduplicated by their real path.
- **Extracted cache bodies could overwrite each other** across sources with the same browser, user and profile names. Extraction folders now include the profile's path.
- **Image extraction stopped on an artifact type with no case folder.** One unmapped type ended the whole extraction with an empty result. It is now reported for that item only.
- **Image streaming skipped the leading zeros of any file over 100 MB.** That logic was written for `$UsnJrnl:$J`. Browser files are now copied byte for byte.
- **The Jump Lists type filter matched nothing** in the Forensic Image and Offline Importer windows (`JumpLists` instead of `link_jumplist`), and the main window had no refresh entry for `link_jumplist`.
- **Offline and image LNK / Jump List parsing failed every time.** The parser was called with a progress callback it did not accept, and it reported *1 record* when it did run. It now parses, and reports the records written.
- **USN Journal: purged journal ranges ended the volume's parse.** The writer for the `deleted_entries` table did not exist, so reaching a range Windows had purged raised an error. The range is now recorded.
- **Parser console output is ASCII** in the MFT / USN parsers too; a block-character progress bar or a check mark aborts a parse on a cp1252 console. The guard test now covers that folder.
- **The MFT record of a file with an 8.3 alias was reported as a hard link** (see *MFT parse and MFT–USN correlation* above).
- **A test hard-coded a private case path.** The UBA end-to-end test now reads its case from `CROW_EYE_UBA_TEST_CASE` and skips without it.

### Known Limitations

- With browser trees from more than one source in a case, SIDs are left empty. A collected SOFTWARE hive cannot be tied to the source it came from.
- On offline and image cases, `source_path`, `manifest_path` and the extracted-key path point into the case folder. The part after `Users\` is the original location on the evidence drive.
- Clicking a live **Parse Browsers** button on an offline or image case still parses the analyst's own machine, as every live parse button does.
- LNK and Jump List rows have no owner column; the owner is the `Users\<name>` folder in `Source_Path`.
- Hives collected before this version have no owner folder, so their labels stay `NTUSER.DAT[1]`. Re-collect to name the owner.
- Cases parsed before this release keep the rows already in them: a re-parse adds only what is new. For the whole-MFT, name, size and hard-link fixes, parse the evidence into a fresh case.
- A stopped correlation keeps the semantic labels found before the stop; the rest of its matches have none. Resume or re-run the wing to label them.
- Statistics counted for an unfinished run have no extraction rate: how many records yielded an identity is recorded only when the run saves its statistics.

### Compatibility and Upgrading

- **Source release.** Run `python "Crow Eye.py"`. A root `requirements.txt` now lists the dependencies, Windows-only packages marked.
- **Existing cases open as before.** To pick up the parser fixes (whole MFT, NTFS fixups and names, real sizes, hard links, browser offline/image parsing, per-user registry replay), parse the evidence into a new case.
- **Correlation wings:** use **Update default wings** to refresh an existing case's MFT/USN conditions.
- **New settings:** *Settings → Parsing → Parse automatically after collection* (on by default) and *Settings → Semantic Mappings → Semantic mapping engine*.
- **New test variable:** `CROW_EYE_UBA_TEST_CASE` for the UBA end-to-end test.

---

## Version 0.14.0 — Visualizations & Browser Forensics Release (pre-release)

**Release date:** 2026-10-03 · **Status:** pre-release (source). The installer published on crow-eye.com remains 0.13.0.
**Baseline:** 0.13.0. All figures below are measured against that release.

---

### Overview

Version 0.14.0 is organised around three themes:

- **Visualization.** Six artifacts gain an interactive dashboard, opened directly from the artifact table under review.
- **Browser forensics.** Browser data becomes a first-class parsed artifact. A new parser covers the Chromium family, the Firefox family and Electron applications, and its output feeds the Timeline, Database Search, User Behavior Analytics and the Eye.
- **Transparency and stability.** Every parse records why each artifact did or did not produce data. Every case keeps its own logs. Features that could read half-written data are now held until parsing and loading complete.

| Measure | 0.13.0 | 0.14.0 |
|---|---:|---:|
| Visualization dashboards | 0 | **6** |
| Artifact tables with a **Charts** button | 0 | **37** |
| Browser tables (`browser_analysis.db`) | 0 | **37** |
| Timeline artifact types / time columns | 17 / 133 | **18 / 175** |
| User Behavior Analytics behaviours | 53 | **65** |
| Registry hive types carved for deleted keys and values | 6 | **10** |
| SRUM native columns retained | — | **+25** |
| Written explanations for empty tables | 0 | **86** |
| Features gated during parsing and loading | 0 | **39** |
| Eye forensic tools | 31 | 31 |
| Test files in this repository | 68 | **84** |

### Highlights

- **Six visualization dashboards:** SRUM, MFT/USN, LNK & Jump Lists, Prefetch, Shell Items and Browser. Each opens from the table it describes.
- **Browser forensics:** 37 tables from Chromium-family browsers, Firefox-family browsers and Electron applications. Stored secrets are preserved and never decrypted.
- **Parse Status Report:** ten outcomes per artifact. A **Why empty?** button explains every empty table.
- **Per-case logging:** each component writes its own log under `<case>/logs/`, browsable in **Settings → Logs**.
- **No feature opens on half-written data.** 39 features are gated while a parse or load is running.
- **Data corrections:**
  - USN Journal timestamps restored;
  - offline event logs written again;
  - Shellbags no longer merged;
  - SRUM application names decoded;
  - UBA sign-in sessions rebuilt.

---

### Visualization Dashboards

Each dashboard opens from a **Charts** button in the row above an artifact table, beside **Anatomy**. The analyst starts from the table under review rather than from a separate tool.

| Dashboard | Opens from | Principal views | Insights raised |
|---|---|---|---|
| **SRUM** | The five SRUM tables; each opens on its own provider | Activity heat map per provider, records by provider, most active applications, network sent/received per day, activity by user | Applications that sent far more than they received; applications seen on a single day |
| **MFT / USN** | MFT and USN tables | Change activity by category (create, delete, rename, data, metadata), most active directories and file types, per-file lifecycle with `$STANDARD_INFORMATION` against `$FILE_NAME` times | Timestomp candidates; USN Journal gaps; files deleted but still present in the MFT; alternate data streams |
| **LNK & Jump Lists** | LNK and Automatic Jump List tables | Files opened per source, by application, most opened directories and file types, volume and device history | Targets on removable volumes, network shares, and Temp / Downloads / AppData |
| **Prefetch** | Prefetch table | Executions coloured by run location (System, Program Files, user profile / Temp, removable media, other), most-run programs, execution device history, program profile with loaded resources | Programs run from user-writable locations; programs run only once; resources loaded from outside System and Program Files |
| **Shell Items** | 20 Registry tables: Shellbags, OpenSaveMRU, LastSaveMRU, CIDSizeMRU, RecentDocs, TypedPaths, RunMRU, WordWheelQuery, MUICache, User Shell Folders, three shell-extension tables, RDPClientMRU, Office MRU, MountPoints2, TypedURLs, RecentApps, per-application MRUs, Regedit last key | Activity by source, most visited places, most referenced files, all items, volumes and shares. Opens filtered to the table it was launched from | Network and removable targets; Shellbag folder times that disagree with the registry write; users |
| **Browser** | Browser history, downloads, cookies, cache, shortcuts and search-engine tables | Activity by type (visits, searches, downloads, cookies, cache) pivoted on domain, typed versus clicked visits, what was typed, downloads, per-domain detail across every browser table | Domains with traces but no history row; downloads the browser flagged; executables and scripts downloaded |

**Common behaviour across all six dashboards:**

- **Continuous day strip.** One cell always represents one day, including days with no activity. Earlier prototypes plotted only active days. On one browser case that drew 134 cells for 226 days and erased the gaps that are often of investigative interest.
- **Six-month window with a range overview.** The strip opens on the most recent six months. The analyst can step with **Previous / Next 6 months**, **Latest** or the arrow keys, or jump by clicking the whole-range overview (one bar per week, current window outlined). This replaces horizontal scrolling that exceeded 20,000 pixels on multi-year cases.
- **Drill-down to the source.** Day → hour → item. Every item view ends with the **full source record**, meaning every column of the underlying row.
- **Secrets are withheld, not hidden.** Passwords, cookie values and payment-card fields appear as *present but withheld*. The existence of a stored secret is itself a finding; its value is not displayed.
- **Insights carry their subjects.** Each insight lists the records behind its count, so a figure such as "7 programs ran from Temp" opens those seven programs.
- **Undated records are retained.** Sources that store no timestamp (MUICache, User Shell Folders, shell-extension registrations) appear in **All items** as *undated*, regardless of the date range. They are never placed on the day strip.

### Browser Forensics

A new parser, `Browser_Claw`, writes **37 tables** to `browser_analysis.db`: 29 for Chromium-format data and 8 for Gecko-format data.

**Coverage:**
- **Chromium family:** 25 named vendor builds, including Chrome (five channels), Edge, Brave, Opera, Vivaldi, Yandex, Epic, CocCoc, Whale and Comodo Dragon. Any other Chromium-based browser is discovered from its profile layout.
- **Firefox family:** Firefox, LibreWolf, Waterfox, Pale Moon, SeaMonkey and Tor Browser.
- **Electron applications:** 15 named applications (Slack, Discord, Teams, Signal, WhatsApp, Telegram, Element, Skype, Notion, Obsidian, VS Code, Claude and others). An adaptive scan picks up any application with a LevelDB or IndexedDB store.

**Artifacts:**
- history, downloads, cookies, cache, sessions, autofill and addresses, bookmarks, extensions and extension storage;
- local storage, IndexedDB, service workers, top sites, shortcuts, search engines, favicons, media history, DIPS (bounce tracking), network state;
- the Firefox equivalents of these.

**Evidence handling:**
- **Provenance on every row:** browser, vendor, user, SID, profile, source path and `parsed_at`.
- **Uncheckpointed data is read.** SQLite databases are read from a working copy that includes their `-wal`, `-journal` and `-shm` files, so rows the browser has written but not yet checkpointed are included. A locked file falls back to a raw copy.
- **Stored secrets are preserved and never decrypted.** Passwords, cookie values and card data are recorded as found (base64, together with the encryption scheme and the DPAPI-wrapped master key). Their existence is evidenced without Crow-Eye reading them.

**Integration:**
- **Timeline:** a new **Browser** lane with 42 time columns. Each has an event label (*Page visited*, *Download started*, *Cookie last sent*, *Site first stored data*) and always uses the record's own event time, never the parse time.
- **Database Search:** a **Browser Activity** category.
- **User Behavior Analytics:** nine browser behaviours (see below).
- **Eye:**
  - a browser knowledge base;
  - the `browser_analysis.db` schema in its schema reference (13 table sections);
  - a parser mapping entry;
  - retrieval keywords, so browser questions reach the right tables.

**Availability:** live systems in this release. Offline and image parsing of browser data is not yet supported. On those cases the Parse Status Report records Browser as *not run*, rather than implying that nothing was found.

### Parse Status and Empty-Table Explanations

Previously, an empty evidence table looked the same whether the artifact was absent from the machine or the parser had failed. Every parse now records the reason.

- **Ten outcomes per artifact**, recorded for live, offline and image parses across 12 artifacts:
  - not failures: *parsed*, *no records*, *source not found*, *feature disabled*;
  - other outcomes: *unsupported format*, *access denied*, *dependency missing*, *partial*, *failed*, *not run*.

  A machine that lacks an artifact is a normal machine, and the report presents it as such.
- **Parse Status Report.** It is displayed once after each parse, after the data has loaded, with one row per artifact. It can be reopened from **Case → Parse Status Report…**. It replaces a completion message that reported success regardless of collector failures.
- **Why empty?** A button at the left of the row above every empty table identifies the artifact, database and table behind it, and gives the recorded reason. 86 written explanations back it (12 per artifact, 74 per table).
- **Storage:** results are written to `<case>/logs/parse_status.json` (the last 25 runs) and `parse_status.log`.

### Case Logging

- **Logs per case.** Each case writes its logs to `<case>/logs/`:
  - a combined `crow_eye.log`;
  - one log per component: parsers, timeline, visualizations, correlation, eye, uba, dynamic linking, gui, case data, parse status;
  - `console.log`, which captures all console output. The windowless build previously discarded it.
- **Rotation:** log files rotate at 5 MB, keeping three backups. An application log is written from launch, before any case is open.
- **Settings → Logs** lists every log by component, including parser logs and `EYE_Logs`. Any file can be opened in full, together with its rotated backups, oldest first.

### Stability and Responsiveness

- **Non-blocking loading.** The loading window no longer blocks the application, so Settings and the case remain readable during a parse.
- **39 gated features.** Opening a feature against tables still being written is what previously crashed the interface.
  - **Work.** Starting another parse, import or case switch while one is running is refused. The message states what is running and for how long.
  - **Views.** The Timeline, UBA, the Eye, Database Search, the Correlation Engine, Dynamic Linking and every dashboard offer **Open when ready**: the feature opens as soon as the work completes.
  - **No data.** A feature that needs data the case lacks says so. A database counts only if it holds rows.
- **Progress indication:**
  - Every progress bar shows continuous motion and an elapsed-time clock, and the reported percentage is never synthesised.
  - The window keeps repainting while tables are populated, so Windows no longer marks it *Not Responding*.
  - Progress is mirrored on the Windows taskbar button.
- **Correlation Engine.** Pipeline runs and Feather imports are refused while Crow-Eye is parsing or loading. A running pipeline marks the application busy.
- **Window integration.** Settings, the Eye windows, UBA, Dynamic Linking and the Correlation Engine have their own taskbar buttons and the Crow-Eye icon.

### Registry

- **Shellbags:**
  - **Same-name items are kept apart.** Two items with the same name under one key, such as two *Pictures* folders or two phones' storage, were merged into one row. Rows are now keyed on the new `value_name` column as well.
  - **Items without a decodable name are kept.** Control-panel entries, MTP device delegates and property-store roots were skipped, which also broke the path of every folder beneath them. They are now recorded, labelled by their shell-item class.
  - **Write time per folder.** `last_written` and `time_basis` are taken from each bag's own key, matching the value Shellbags Explorer reports.
  - `UsrClass ...\ShellNoRoam\BagMRU` is now enumerated.
- **Four additional hives:**
  - COMPONENTS, DRIVERS, BBI and ELAM are collected with their transaction logs and carved for deleted keys and values, class names and security descriptors.
  - COMPONENTS is typically the second-largest hive on a system and was previously not examined at all.
  - The collection size estimate rises from 100 MB to 165 MB.
- **Hive reorganisation is recorded.** `registry_hive_state.reorganized_at` records when Windows last compacted each hive. Compaction discards freed cells, so a low carved count is meaningful only when read alongside it.

### SRUM

- **ESE recovery:**
  - Collection now includes the ESE checkpoint (`.jfm`, `.chk`) and transaction logs.
  - A database left dirty by an unclean shutdown is soft-recovered before it is opened, which includes data committed but not yet flushed.
  - Destructive repair is used only as a last resort.
  - The path taken is recorded in `srum_metadata`, in seven new columns that include `db_state`.
- **Application identity decoding.** Store-style AppIds previously yielded timestamp fragments as application names on approximately 18% of timeline rows. Three identity forms are now decoded into application name, path and hosted services.
- **Duplicates removed.** Byte-identical duplicate rows, 44% of one case's energy rows, are discarded.
- **Raw numbers.** Numeric fields are stored as numbers rather than formatted strings, which corrects dashboard totals.
- **25 additional native columns**, including battery design and full-charge capacity, wake counts and application-timeline counters.

### User Behavior Analytics

- **Behaviours: 53 → 65.**
  - **Sign-in:** failed logons; and Winlogon sign-in and sign-out notifications, which are written on every Windows system without auditing configured.
  - **Browser (nine):**
    - web history and downloads, including flagged downloads;
    - abnormal browser exits and download save locations;
    - account sync and risky extensions;
    - stored secrets (counts only, never values);
    - gaps in browser history, presented as an inference with its caveat.
  - **Modified:**
    - sign-out now includes event 4647;
    - boot/shutdown now includes events 6005 and 6006;
    - registry-based web browsing defers to the browser rules.
- **Sign-in sessions rebuilt.**
  - Logons and logoffs are paired by Logon ID; same-second ordering had previously discarded every logoff on a real case.
  - A session with no recorded sign-out has no duration, where durations were previously invented.
  - Duplicate records are merged, an unlock resumes the existing session, and service accounts are excluded.
- **Image-imported cases.** The offline event-log parser stores its fields in a different format, and every sign-in disappeared on those cases. Both formats are now read.
- **Interface:**
  - a **Sign-ins** view (one row per session; selecting one narrows the story to that window);
  - a **day rail** covering the whole case;
  - a detection-rule picker with event counts;
  - a coverage filter.

### Eye AI

- **Browser knowledge:**
  - a dedicated knowledge file;
  - schema reference entries for `browser_analysis.db`;
  - a parser mapping;
  - retrieval keywords (*browser*, *chrome*, *firefox*, *cookie*, *download history* and others).
- **Parser mappings 3.5 → 3.8.** SRUM now resolves to its real tables instead of a table that does not exist.
- **Knowledge-base updates:** the registry knowledge base explains how hive reorganisation affects carved counts. The SRUM knowledge base covers recovery state and the new columns.
- **Logging.** All Eye services and backends now write to the case's `eye.log`.
- **Tools.** The forensic tool set is unchanged at 31. Browser data is reached through the knowledge base and schema reference, not a dedicated tool.

### Correlation Engine and Timeline

- **Matches by Feather chart.** The results chart drew 132,446 identities for one feather on a chart whose largest real value was 1,029. Both copies of the chart now draw from a single source chosen per run.
- **Timeline:**
  - a **Browser** lane (see above);
  - labels hidden when points are crowded;
  - URLs ending in `/` no longer display as *Unknown*.
- **Database Search:** a **Browser Activity** category over six browser tables.

### Bug Fixes

- **USN Journal records had no timestamps.** A local helper shadowed the conversion function it was meant to call and recursed until a suppressed `RecursionError`, leaving **244,014 rows without a time**.
- **Offline event logs wrote no rows while reporting success.** The timestamp validator required fractional seconds that the writer never produced.
- **The USN parser disabled application-wide logging** by removing every root log handler on import.
- **Stray output directories.** Several parsers configured logging at import time, and the MFT/USN correlator created a `Target_Artifacts` folder in whatever directory Crow-Eye was launched from. Both are corrected.
- **MFT/USN subprocess output** is now captured into the case log.
- **Registry `BrowserHistory`** was written into the browser module's table; it now has its own.
- **Image and offline imports** report how many artifact files were parsed, rather than a blanket success message.
- The **loading window icon** was missing when running from source.

### Known Limitations

- Browser parsing is available for live systems only. Offline and image support is planned.
- The Eye answers browser questions through its knowledge base and the database schema; there is no dedicated browser tool yet.
- This is a source pre-release. The installer on crow-eye.com remains 0.13.0.

### Compatibility and Upgrading

- **Existing cases are not modified.** Cases created by earlier versions open as before and are never rewritten without a re-parse.
- **In-place migrations:**
  - Shellbags gain `value_name`, `last_written` and `time_basis`. Re-parsing fills the write times and claims existing rows rather than duplicating them.
  - `registry_hive_state` gains `reorganized_at`.
  - SRUM tables gain their new columns.
- **Recommended re-parse:** SRUM, USN Journal and offline event logs, so that the corrections above take effect. The data already in a case was produced by the earlier code.
- **Upgrading:** replace the source tree. No further steps are required. The six dashboards ship prebuilt and open from a clone without Node.js.

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
