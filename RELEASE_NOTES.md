# Crow-Eye Release Notes

---

## Version 0.14.1 — Whole-Disk Evidence, Chain of Custody & Large-Case Correlation

**Release date:** 2026-10-10 · **Baseline:** 0.14.0. Figures are measured against that release.

### Overview

Version 0.14.1 makes the evidence Crow-Eye collects complete, and the way it handles that evidence provable. Two themes run through it:

- **Complete evidence.** The MFT parser follows the `$MFT` through its data runs, so every fragment is read: deleted entries, real file sizes and correct names included. Renames are kept as old → new pairs. Browsers are parsed from collected folders and forensic images with the same 37 tables as a live parse. Every user's registry hive replays its own transaction logs, matched to its owner.
- **Provable handling.** Every collection and parse writes a chain-of-custody record: what was read, how, and what Crow-Eye changed on the machine. Each copy is verified against its source, shadow copies Crow-Eye creates are deleted when the run ends, and each case keeps a hash-chained ledger of everything done to it.

Around those themes, re-parsing a case adds only what is new, forensic images are checked before extraction, the Correlation Engine streams large cases and keeps the statistics of a stopped run, and the GUI and UI are enhanced across the application. A measured comparison with 0.14.0 is at the end of these notes.

### Highlights

- **The whole MFT**, read through its own data runs: deleted entries, NTFS fixups, real file sizes, long names and a rename log.
- **Browser parsing on offline folders and forensic images**, with the same 37 tables as a live parse.
- **Chain of custody:** a record per run, a case ledger and a viewer.
- **Re-parsing adds only what is new**, and the Parse Status Report says how much was new.
- **Forensic images are checked before extraction**, and problems are named with the fix.
- **The Correlation Engine handles large cases.** Feathers stream, semantic mapping finishes, Stop is honoured, and an unfinished run still shows its statistics.
- **Linux:** the Python source version starts on Debian 12 and Ubuntu 23.04 and later.

---

### MFT and USN Journal

- **Every fragment of the `$MFT`.** The parser located record N at the start of the `$MFT` plus N × 1,024 bytes, which holds only within the first fragment. On the test machine that is 205,056 of 3,320,832 records. Later records were read from unrelated clusters and dropped without an error. The `$MFT` is now read through its data runs, both live and in the raw-disk copy used for offline imports. 3,320,633 records are read, deleted entries included. The count matches the MFT size Windows reports.
- **NTFS fixups are applied.** The last two bytes of every 512-byte stride were never restored, which corrupted 13,601 names on one `$MFT`. There are none now.
- **Real file sizes.** Every file stored outside its MFT record read as size 0, Amcache.hve included. The size is now read from the attribute header. Alternate data streams no longer add to it.
- **Extension records are merged into their file.** A file whose names or data sit in an extension record no longer appears as a nameless, zero-byte entry.
- **Long names first.** The correlator preferred the 8.3 alias (`MIGRAT~1.DAT`) to the long name. On one case, rows named by an alias fell from 136,996 to 2,975.
- **Renames, old name → new name.** `filename_changes` in `mft_usn_correlated_analysis.db` pairs each journal rename with its new name, folder and a *moved* flag: 4,107 renames on one case, 395 of them moves.
- **Correlation:**
  - Journal-only events get a full path, from the MFT folder or, when the folder is gone, from the journal's own records.
  - A parent folder whose record now holds another folder is shown as `[Reused Parent]`.
  - Re-correlating rebuilds instead of duplicating rows.
  - USN v3 file IDs decode correctly.
  - An offline case is never correlated with the examiner's own disk.
- **Counted in records.** Parse Status reported "MFT 18,094,212", the rows of four MFT tables added together. It now reports MFT records. A file's 8.3 alias is no longer recorded as a second hard link (2.2 million false `Hardlinks` rows on one case).
- **Faster:**

  | Step | 0.14.0 | 0.14.1 |
  |---|---:|---:|
  | Live MFT insert, 1.4 million records | 101 s | **51 s** |
  | Offline MFT, 200,000 records | 30 s | **16 s** |
  | MFT–USN correlation, 7.10.2026 `$MFT` | 322 s | **258 s** |

- **Offline volumes keep their own label** (`OFFLINE`, `OFFLINE_1`, …), and a second volume's `$MFT` or `$J` is parsed instead of skipped.
- **The USN journal is collected into a readable file.** The name `$UsnJrnl:$J` wrote it into an alternate data stream behind a 0-byte file. Older collections are still read.

### Browser Forensics

- **Offline folders and forensic images.** The Offline Importer, Parse Offline Artifacts and Forensic Image Parsing produce the same 37 tables as a live parse. On the same machine, 34 tables match the live parse row for row. The others differ only in case-path columns and 3 Service Worker rows.
- **Each profile keeps its folder tree.** Browser files are collected under `live_acquisition/Browser/<source>/Users/<name>/...`, so two images, drive roots or hosts never merge.
- **Owners come from the evidence.** The user is the `Users` folder the profile came from, never the analyst's own profile above the case. The SID is read from the evidence's SOFTWARE hive.
- **Include browser cache** (on by default). Turning it off skips the HTTP and Service Worker caches: on the test machine that is 4.4 GB of a 5.1 GB profile, and the parse drops from 19 minutes to 41 seconds.
- **Older Chrome formats on images:** pre-2018 cookie columns, pre-M86 session files and the old top-sites table. On a 2016 image, 724 cookies, 143 session entries and 10 top sites are now read.
- **Uncheckpointed rows are read.** Copies were opened in a mode that ignores the `-wal` file, losing committed rows. This affected live parsing too.
- **Search engines' creation dates are read.** Chromium stores them in WebKit time, and they were read as Unix seconds, so every one came out blank.

### Registry

- **Every user's hive replays its own transaction logs.** Users' hives were collected into one folder, and renamed collisions separated hives from their logs. One user's transactions could be replayed into another user's hive, and two parses of the same image gave 11,387 and 13,358 records. Each user's files now keep their folder (`Registry_Hives\Users\<name>\...`). A log is replayed only into the hive its header names.
- **Verified:** two separate parses of the same image give identical counts in all 124 registry tables.
- **Rows name their owner** (`NTUSER.DAT[<name>]`) in the form the live parser writes.
- **The analyst's name is no longer put on the evidence.** A case stored under `C:\Users\<analyst>\` labelled every unowned user hive with the analyst's name.

### Event Logs

- **617 events have their own description** (426 before), keyed by provider and Event ID in `configs/event_descriptions.json`. The text follows the message templates Windows ships where one exists. Before, an ID meant the same thing for every provider, so EventSystem 4625 read "An account failed to log on".
- **On the measured case**, the share of rows with a real description rose from 11.0% to 74.8% for System and from 33.4% to 100% for Security.
- **Each event's own record number** (`RecordNumber`) is stored, so identical-looking events stay distinct.
- **Live timestamps are converted to UTC.** They were labelled UTC while still in local time.
- **Offline rows keep their payload** after the description, so queries on fields such as `LogonType` keep working.

### Chain of Custody

- **One record per run**, `<case>/logs/custody_<run>.json`, with its SHA-256 beside it. It covers Crow-Claw, live Parse All, image parsing, single-artifact parses, Offline Importer collections and offline parses. Each record holds:
  - who ran it, where and when (UTC), and the tool version and settings;
  - per source file: size and times read before the copy, how it was read (standard copy, shadow copy, raw disk, in place), and the SHA-256 of source and copy, which must match;
  - what Crow-Eye changed on the machine: processes and services started, and shadow copies created, used and deleted;
  - per artifact: rows read, new and already present, and the hash of every database written.
- **A case ledger**, `<case>/logs/custody_ledger.jsonl`, records case creation and every open, run, export, evidence import, settings change (secrets are never written), correlation and Dynamic Linking run. Each line carries the SHA-256 of the line before it, so an edit, removal or reorder breaks the chain.
- **Case → Chain of Custody…** opens a record with an integrity badge, every source with its verdict, the footprint, and a **Case ledger** tab that walks the chain.
- **Shadow copies:**
  - A snapshot Crow-Eye creates is deleted at the end of the run, by the ID its creation returned. Existing snapshots are never touched.
  - A snapshot older than 30 minutes is no longer read as the live file.
  - The setting that forbids creating snapshots now works.
  - Advice to run `vssadmin delete shadows /all` or `cleanmgr.exe` on the target is gone.
- **File headers are checked** for hives, logs, event logs, SRUM, Prefetch, LNK, Jump Lists, `$I` and `$MFT`. Before, every file was reported valid without being read.
- **Image integrity.** An E01's section headers are read before extraction: whether it carries an acquisition hash, and whether its segments hold the whole disk. A 6.4 GB E01 declaring a 992.7 GB disk held 1.4% of it, and nothing said so. It is now a pre-flight warning.
- **Nothing is written to the target's system drive.** Working files go under `<case>/tmp`, and the SRUM engine no longer leaves `edb.*` files in the working folder. Crow-Eye warns when the case folder is on the drive being examined.

### Re-parsing Adds Only What Is New

- A second live parse of the same machine duplicated or deleted data:
  - Amcache stored every row twice;
  - SRUM removed duplicates only within one run;
  - the MFT child tables were plain inserts;
  - Event Logs and Browsers dropped their earlier rows.
- Every parser now stores only the rows the case does not hold, through one shared writer, and earlier rows are kept.
- On a second parse of the same evidence: Amcache 0 new of 6,235, MFT 0 new of 1,208,321 records, Event Logs 0 new of 70,895 with earlier events kept.

### Parse Status and Forensic Image Diagnostics

- **New and Already present columns.** *Records* is what the run read: "1,024 record(s) read: 0 new, 1,024 already in the case."
- **Failed and partial rows expand** to the error, the parser's warning and error lines with the traceback, and the database rows before and after.
- **Forensic images are checked before extraction.** Formats are identified by content, and unsupported ones are named (L01, AD1, AFF, archives, QCOW, VDI). Each partition's boot sector is read, BitLocker included.
- **Mistakes and problems are named with the fix:**
  - investigator mistakes: a later segment chosen, segments missing, a folder chosen instead of an image, no partition selected, the image stored inside the case;
  - image problems: corrupted or locked images, BitLocker volumes, unreadable file systems, no Windows installation.
- **Errors stop the run before extraction, and warnings ask before continuing.** Both appear in the image window's **Issues** tab and in the report.
- **Correct statuses:**
  - an artifact found but not copied is *Failed* or *Access denied*, not *Not found*;
  - a crashed batch records what finished;
  - unsupported Prefetch versions and dirty SRUM databases read as *Unsupported format*.
- **The image window is redesigned:** setup on the left, the run on the right, and a fixed action bar. The Windows partition is pre-selected.

### Collection and Parsing

- **Administrator rights:**
  - Before a live parse that needs rights, Crow-Eye offers *Restart as Administrator*, *Run anyway* or *Cancel*.
  - After a parse Windows refused, one pop-up names the refused artifacts.
  - The restart reopens the same case.
  - Refusals are classified *Access denied*, including Amcache and SRUM, which used to read *does not exist*.
- **Cancel stops everything.** Queued parsers are dropped, and running ones are ended with their child processes. Closing the window mid-parse asks first. A run that had to be ended still leaves its custody record, and its shadow copy is deleted.
- **Every subprocess call has a timeout.** A hung parser held the whole live Parse All indefinitely.
- **A live checklist** in the parsing dialog: one row per artifact with status, records, time and warnings, a *Now:* line, and the log folded below.
- **Offline Importer:**
  - *Select Files* collects only the chosen files.
  - *Collect* after a *Scan* copies exactly as a direct collection.
  - *Cancel* keeps what was copied.
  - EVTX, SRUM and LNK are read from Crow-Claw collections, which they used to miss.
- **Parse automatically after collection**, a new setting in **Settings → Parsing** (on by default).
- **Crow-Claw** shows 14/14. It always collected all 14 artifacts, but a rate limit dropped the last progress line.
- **Faster:**
  - Registry offline parse: 153 s → 84 s.
  - LNK and Jump List profile walk: 30.6 s → 18.1 s.
  - A Brave Service Worker cache: projected from 332 s to about 45 s.

### Loading and Responsiveness

- **Dashboards no longer freeze the window.** Queries run off the interface thread, and the newest request wins. The longest stall on the measured case is 172 ms:
  - a timeline day click: 70 s → 3.1 s;
  - SRUM open: 25–37 s → 6.5 s.
- **Event Logs are paged.** On one case, loading went from 2.9 s to 0.30 s, and memory after opening the case from about 1,060 MB to 750 MB. Sorting, search and export cover every row.
- **Tables are filled once per case open**, with sorting off during the fill, so rows no longer land in the wrong place.
- **Background scans and parses run off the window**, and Cancel reaches them.

### Case Logging

- **New log files:** `offline_importer.log`, `crow_claw.log`, `image_parsing.log` and `semantic_mapping.log`. All are listed in **Settings → Logs**, together with the collection manifest, import results and image partition table.
- **Every parser run is framed in `parsers.log`**, from its start line to its outcome. That includes the worker processes of a live Parse All, which had no case logging.
- **Logs in colour**, in Settings → Logs, the parsing dialog and the full-log window, with a level filter, find and follow.
- `console.log` rotates at 10 MB.

### Visualizations

- **The MFT/USN dashboard is rebuilt:**
  - one six-month strip for both sources, with a colour per USN reason;
  - every aggregate counted in SQL (a journal day's drill-down was capped at 6,000 events, and one day held 283,585);
  - renames shown old → new, and an all-records list;
  - a **Charts** button on the correlated table.

  On a 3.5-million-row case, the overview opens in 2.9 s and the strip in 4.7 s.
- **One User Activity dashboard** covers the 28 Shell Items and registry user-activity tables, now including UserAssist, BAM and DAM, and camera, microphone and location use. Each table's **Charts** button opens it on its own source.

### Anatomy

- **The anatomy pages ship with Crow-Eye** (13 pages) and open in an in-app viewer at the right section, with no internet needed.
- **Every User Activity table has its own section:** the key and hive, the value format, which timestamp exists and what it bounds, and what the table proves and does not.

### User Behavior Analytics

- **Behaviours: 65 → 81.** Sixteen browser rules:
  - visits by site category (file sharing, paste, anonymisers, cryptocurrency, remote access, AI chat, hacking resources), counting only a person's own navigation;
  - web searches;
  - downloads, graded by risk, and the downloads the browser opened;
  - inferred uploads, marked as inferred;
  - chat applications, cryptocurrency wallet extensions, tabs left open, and media played.

  The site categories are data in `uba/config/site_categories.json`. No rule reads autofill, typed page content, usernames, session tokens or storage contents.
- **Files, not journal records.** "N files were created" counted every journal record, about 3.4 times the files. It now counts files.
- **Fewer false findings:** browser-shipped extensions are no longer risky extensions, and the history-gap rule works per profile.
- **Collected cases are no longer read as the examiner's activity.** The LNK and Jump List collection skips Crow-Eye case folders, which held 433 of 636 LNK rows on one machine.

### Eye AI

- **`query_user_behavior`**, a new tool, runs the 81 UBA rules once per case and answers for any day, range or user, with the evidence rows behind each event. Tools: 31 → 32.
- **Setup in four steps.** An API key is stored only after its connection test passes.
- The Eye's built-in queries name the columns that exist.

### Correlation Engine and Timeline

- **Large cases run.** The Identity engine read each feather completely into memory: about 18 GB for one 3.8-million-row MFT feather on a 15 GB machine. Feathers now stream: about 2.1 GB on that case, which correlates its 483,525 identities.
- **Semantic mapping finishes.** On a 842,334-match case it took 55 minutes, 43 of them in an FTS5 prefilter that kept 99.8% of the matches. A sample now decides whether the prefilter can filter. Candidates are read in chunks, and progress is logged. On a 105,309-match wing: 138 s → 86 s, with identical labels.
- **Stop works.** Cancel never reached the engine, and semantic mapping never checked it. The window killed the thread after 15 seconds, leaving no statistics. The engine now stops within seconds, inside semantic mapping too, and saves what it has. The window waits for that.
- **A stopped or unfinished run still has a Summary.** Statistics are saved before semantic mapping. For a run that never saved them, matches, identities and records per feather are counted from what it left. A small **CANCELLED** or **NOT FINISHED** label marks it.
- **Matches by Feather counts every feather.** Feathers with an underscore in their name (`mft_usn`, `security_logs`, `amcache_app`) read 0.
- **Opening a case no longer breaks the next correlation.** It closed every database connection in the process, the engine's own included.
- **Correlation Engine 1.8.0.** Each timestamp is parsed once per feather. The full test pipeline went from 3,968 s to 2,278 s with identical matches.
- **Wing conditions** named MFT/USN columns that do not exist, so the mass-delete and ransomware rules could never fire. Use **Update default wings** to refresh a case.
- **Settings → Semantic Mappings** sets the semantic-mapping engine: worker threads, the prefilter threshold, chunk size and a detailed debug log.
- **Dynamic Linking statistics:** after *Link Gathering* and *Run Dynamic Linking*, a statistics window shows what was linked, by source, category and table. The counts are honest: a value already known is no longer counted again on every run.
- **Timeline:** the LNK and Jump List lanes are drawn, and the MFT/USN lane covers all its rows.

### Interface

- **GUI and UI enhancements across the application:** Settings, Database Search, the Correlation Engine, Crow-Claw, the Offline Importer, Forensic Images, Row Details and the loading dialog have a refreshed, consistent design.
- **Colour that carries meaning is kept:** status, score and severity colours.
- **Bundled fonts:** Barlow Semi Condensed and JetBrains Mono, under the SIL Open Font License.
- **Standard columns are colour-coded** in every artifact table: times, paths, hashes, users, sizes, names, IDs, values, flags and network fields.
- **One scroll-bar style** everywhere.
- **Row Details** groups fields by kind and adds a filter. *Copy all* and *Export* (TXT, CSV, JSON) work.
- **A busy notice** says when a click lands while Crow-Eye is parsing or loading.

### Linux

- **The Python source version starts on Debian 12 and Ubuntu 23.04 and later.** It installed into the system Python, which those systems refuse. It now creates its venv first. A root `requirements.txt` lists the dependencies, with Windows-only packages marked.
- **The same case parses identically on both platforms:** all 196 tables in 33 databases have the same row counts.
- **Fixed on the way:** Linux path handling for AmCache, Firefox profiles and ShimCache; font substitutes; and web views that paint without a GPU.

### Bug Fixes

- **Elevated live parses never exported the SAM and SECURITY hives**, losing the user-account and security-policy detail.
- **A browser re-parse kept the first parse's values.** Changed rows are now updated in place.
- **A live Parse All could sit in the browser stage for 40 minutes** while its re-parse check scanned the whole profile for every row.
- **ShimCache reported "Failed"** when every entry was already in the case.
- **MFT ended "Partial, exit code 1"** because 24 invalid extension records rolled back the whole merge.
- **Offline and image LNK and Jump List parsing failed every time.**
- **A purged USN journal range ended the volume's parse.**
- **The Eye did not open**, raising `NameError`. Other undefined names were fixed across several packages, and a test now runs pyflakes over every package.
- **An exception inside a Qt slot no longer closes the application.**
- **The Parse Status report opened after a parse showed plain white table headers.**
- **A time-window wing could return no matches** because of an error in a log line.

### Known Limitations

- With browser data from more than one source in a case, SIDs are left empty: a collected SOFTWARE hive cannot be tied to its source.
- On offline and image cases, browser path columns point into the case folder. The part after `Users\` is the original location on the evidence drive.
- Hives collected before this version have no owner folder and stay labelled `NTUSER.DAT[1]`. Re-collect to name the owner.
- A stopped correlation keeps only the semantic labels found before the stop.

### Compatibility and Upgrading

- **Existing cases are not modified**, and they open as before.
- **Parse the evidence into a new case** to apply the MFT, browser and registry fixes. A re-parse into an existing case adds only new rows, so rows produced by the earlier code remain.
- **Correlation:** use **Update default wings** in existing cases.
- **New settings:**
  - Settings → Parsing → *Parse automatically after collection*;
  - Settings → Semantic Mappings → *Semantic mapping engine*.
- **Upgrading:** replace the source tree. On Linux, run `python3 "Crow Eye.py"`; it creates its venv on first start.

### Measured Against 0.14.0

| Measure | 0.14.0 | 0.14.1 |
|---|---:|---:|
| Renames recorded old → new (one case) | 0 | **4,107** |
| Modes that parse browsers | live | **live, offline, image** |
| Copies verified against their source | none | **every copy** |
| Shadow copies Crow-Eye created, left on the target | all | **none** |
| Rows stored again by a second parse of the same machine | all (Amcache, SRUM, MFT) | **none** |
| Longest interface stall while a dashboard loads | 70 s | **172 ms** |
| User Behavior Analytics behaviours | 65 | **81** |
| Event IDs with their own description | 426 | **617** |
| Test files in this repository | 84 | **89** |

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
