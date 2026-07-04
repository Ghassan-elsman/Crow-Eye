# Crow-Eye Release Notes

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
- Programs opened (UserAssist), programs run (Prefetch, expanded to per-run events), process creation (4688), program presence (ShimCache/AmCache/MUICache), app installs, app crashes (WER)
- File open/create/delete/copy/rename — renames show the **full name history** (`old → … → current`) reconstructed from the USN journal, with soft-delete (`$R/$I`) resolution
- Folder browsing (ShellBags), recent documents, typed locations, website visits
- USB device connect, device presence, network shares, network connections and per-app data transferred (SRUM)
- Autostart persistence (Run keys + services, escalated when the target runs from a user-writable path), service/driver installs, service state changes
- System start/shutdown, **clock changes**, **event-log clearing**

**Filters:** free-text search, user/actor (incl. "Unattributed" and a signed-in-session toggle), behavior class (user/application/system), severity, application (searchable multi-select across 200+ programs), and datetime range with quick presets (all time / first day / last day / last hour of activity).

**Forensic guarantees**
- Source databases are opened **read-only**; the analysis never touches the evidence.
- Every event carries its provenance (`database → table → rowid`) and opens the real source rows on demand.
- **Actor attribution never guesses**: an event is attributed to a User, an Application, the System — or left empty. Interactive logon sessions are used only as context labels ("during Gass3's session"), never to attribute an action.
- Wording distinguishes deliberate interaction (UserAssist, SRUM foreground) from artifacts an application can also generate (ShellBags, LNK, JumpLists), with explicit caveats on the card.

**Data sources:** Security/System/Application Event Logs, USN Journal, MFT, UserAssist, BAM, Prefetch, ShimCache, AmCache, MUICache, ShellBags, LNK / JumpLists, Recycle Bin, SRUM (application, network, connectivity), and registry hives.

### 🗺️ New: Narrative Map — the Eye's persistent case memory

The Eye AI assistant is stateless between turns; the Narrative Map (`eye/services/narrative_map_service.py` + a new board UI in the Eye window) gives it — and you — a persistent, court-defensible working memory for the case.

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
