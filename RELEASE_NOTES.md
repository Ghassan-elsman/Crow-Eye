# Crow-Eye Release Notes

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

### 🔧 Fixes

- **AI setup — "Validate & Save" now always works.** Configuring a model backend could silently do nothing if you pressed Back and then Next in the setup wizard. The final step now reliably validates the connection and saves your configuration regardless of how you navigated the wizard.
- **Local Ollama server on a LAN or custom address is now honored.** When Ollama was configured as a Local Server, the Eye ignored the address you entered and always tried `localhost:11434`. It now connects to the endpoint you configured — a dedicated AI server on your LAN or a non-default port.

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
