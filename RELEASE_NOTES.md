# Crow-Eye Release Notes

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
