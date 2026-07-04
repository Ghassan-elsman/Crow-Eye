# 👁️ EYE AI Assistant: Forensic Tool Reference

This document serves as the authoritative technical reference for the investigative and reporting tools available to the **EYE AI Forensic Assistant**. These tools enable the agent to interact with the Crow-eye forensic ecosystem, perform deep analysis, and generate professional reports.

---

## 🛠️ Investigative Tools
These tools allow EYE to explore the case environment, query forensic databases, and research external intelligence.

### 1. `query_database`
*   **Purpose**: Executes raw SQL `SELECT` queries against specified forensic databases.
*   **Execution Logic**:
    *   Queries are executed via the `ForensicDatabaseService`.
    *   **TOON Compression**: If the result set exceeds 1000 rows, the handler automatically applies **Table-Oriented Object Notation (TOON)** compression. The AI receives a statistical summary and sample rows (first 10 + last 10), while the full dataset remains available in the UI Data Viewer.
*   **Parameters**:
    *   `database_name` (string): The filename of the target database (e.g., `registry_data.db`).
    *   `sql_query` (string): The SQL statement to execute.

### 1b. `analyze_large_dataset` (Map-Reduce)
*   **Purpose**: Analyze an **entire** large artifact (a full MFT, USN journal, or large batch of LNK/Event records) that is far too big to fit in one context window. EYE should pick this **instead of** `query_database` when the result set would be huge and all of it must be examined.
*   **Execution Logic** (`MapReduceService`):
    *   Fetches every row, then packs them into chunks that each fit under a token budget (default 3000). **Every row lands in exactly one chunk — nothing is split or dropped.**
    *   **Map**: each chunk is summarized for anomalies by the model.
    *   **Reduce**: the per-chunk summaries are synthesized into one consolidated analysis (recursively, if the summaries themselves overflow).
    *   **Chain of custody**: every Map and Reduce payload is sealed by `EvidenceSeal` (`eye_payload_seal.jsonl`) with the `database:table` + row-index range it covered.
    *   **Fail-hard**: if a *single* row exceeds the chunk budget, the tool refuses (select fewer columns / raise budget) rather than splitting one evidence record.
*   **Parameters**:
    *   `database_name` (string), `sql_query` (string, select only needed columns), `instruction` (string — what to look for), `chunk_token_budget` (int, optional, default 3000).
*   **Availability**: included in the constrained-model tool set, because tight local context windows are exactly when it is needed.

### 2. `get_schema`
*   **Purpose**: Retrieves the schema (columns and types) for a specific table.
*   **Usage Policy**: Primarily used as a **fallback mechanism**. If a `query_database` call fails due to schema mismatch, EYE is programmed to call `get_schema` to discover the correct structure and retry.
*   **Parameters**:
    *   `database_name` (string): Target database.
    *   `table_name` (string): Target table.

### 3. `search_artifacts`
*   **Purpose**: Performs a global search across all indexed forensic databases.
*   **Capabilities**: Supports both literal string matches and Regular Expressions (Regex).
*   **Parameters**:
    *   `search_term` (string): The term or pattern to hunt for.
    *   `use_regex` (boolean): Set to `true` for regex-based hunting.

### 4. `query_correlation_results`
*   **Purpose**: Direct interface with the **Crow-eye Correlation Engine**.
*   **Query Types**:
    *   `statistics`: Returns high-level correlation metrics.
    *   `time`: Finds events within a specific temporal window.
    *   `identity`: Correlates data based on `user`, `process`, or `file` identifiers.
*   **Parameters**:
    *   `query_type` (enum: `time`, `identity`, `statistics`).
    *   `identity_type` (optional enum: `user`, `process`, `file`).
    *   `identity_value` (optional string).

### 5. `query_live_forensic_intel`
*   **Purpose**: Research binaries or drivers against live external intelligence feeds.
*   **Sources**:
    *   **LOLBAS**: Living Off The Land Binaries and Scripts.
    *   **LOLDrivers**: Vulnerable and malicious Windows drivers.
    *   **Bootloaders**: Malicious or vulnerable bootloaders.
    *   **LOFL**: Living Off The Land - Fileless (Scripts/Cmdlets).
*   **Parameters**:
    *   `binary_name` (string): Name of the file to research (e.g., `certutil.exe`).

### 6. `list_case_files`
*   **Purpose**: Navigates the active case directory to discover available artifacts.
*   **Security**: Implements path-traversal protection, restricting access to the case root.
*   **Parameters**:
    *   `sub_path` (string, optional): Subdirectory relative to the case root.

### 7. `internet_search`
*   **Purpose**: Fallback research tool for threats or techniques not covered by local RAG or live intelligence APIs.
*   **Parameters**:
    *   `query` (string): The search query.

---

## 📊 Reporting & Visualization Tools
These tools manage the **Living Report Workspace**, allowing EYE to document findings proactively.

### 1. `report_append_section`
*   **Purpose**: Adds a standard Markdown narrative section.
*   **Parameters**: `title`, `markdown_content`.

### 2. `report_add_data_table`
*   **Purpose**: Injects an interactive table populated by a database query.
*   **Parameters**: `database_name`, `sql_query`, `columns`.

### 3. `report_add_chart`
*   **Purpose**: Generates high-fidelity data visualizations.
*   **Supported Types**: `bar`, `line`, `pie`.
*   **Parameters**: `title`, `chart_type`, `labels`, `datasets`.

### 4. `report_add_chat_transcript`
*   **Purpose**: Documents internal reasoning or investigator dialogue within the report.
*   **Parameters**: `messages` (list of `role` and `content` pairs).

### 5. `report_edit_section` / `report_delete_section`
*   **Purpose**: Management tools for refining the investigative report.
*   **Parameters**: `block_id`.

### 6. `export_report`
*   **Purpose**: Triggers a Human-in-the-Loop (HITL) dialog to export the workspace.
*   **Supported Formats**: `HTML` (Interactive), `PDF` (Formal), `Markdown` (Obsidian-ready).

---

## 🧬 Correlation Engine Authoring Tools

These four tools let EYE author and edit correlation configuration —
Wings and Semantic Mappings — on the analyst's behalf. They are
**write actions** governed by GEP Rules 9 / 10 / 11 (see
[eye_architecture.md](./eye_architecture.md#5-the-ghassan-elsman-protocol-gep),
section 5, write side).

> [!IMPORTANT]
> Every authoring call requires a non-empty `reason` (Rule 9) and at
> least one `related_evidence` reference in `database:table:rowid` form
> (Rule 10). The handler refuses calls that miss either.

### 1. `correlation_create_wing`
*   **Purpose**: Create a new Wing (correlation rule) in the active case.
*   **Use when**: the analyst explicitly asks, OR you've spotted a
    correlation pattern that recurs across the case and an explicit
    Wing would speed future analysis.
*   **Key Parameters**:
    *   `wing_name`, `proves`, `description`
    *   `feathers` (list of feather references with `feather_id`,
        `artifact_type`, `weight`, `tier`, `tier_name`)
    *   `time_window_minutes` (default 180), `minimum_matches` (default 1)
    *   `anchor_priority`, `semantic_rules`, `tags`, `case_types`
    *   `reason` — **REQUIRED** (GEP-9 — Reason-Required)
    *   `related_evidence` — **REQUIRED** (GEP-2 — Evidence-Link)
*   **Returns**: `wing_id` (e.g. `eye_wing_a1b2c3d4`), `path` to the
    saved JSON, `human_summary` for chat display, `gep_rules` status.

### 2. `correlation_edit_wing`
*   **Purpose**: Edit a Wing EYE previously authored.
*   **Refuses**: any wing whose `eye_authorship.created_by` does not
    start with `"eye"` (built-in / human-authored wings stay
    read-only). Suggest manual edits to the analyst in those cases.
*   **Key Parameters**: `wing_id` (required), `reason` (required), then
    any subset of the create-tool fields you want to change.
*   **Behavior**: appends to `eye_authorship.edit_history`, bumps
    `last_modified`, writes atomically.

### 3. `correlation_create_semantic_mapping`
*   **Purpose**: Create a Semantic Mapping or multi-condition Semantic
    Rule that turns a technical value into a human-readable forensic
    meaning.
*   **Use when**: you spot a recurring technical artifact in the case
    that has clear forensic significance but isn't already mapped.
*   **Key Parameters**:
    *   `mapping_type`: `"mapping"` (single source/field) or
        `"rule"` (multi-condition AND/OR across feathers)
    *   For `"mapping"`: `source`, `field`, `technical_value` or
        `pattern`, `semantic_value`
    *   For `"rule"`: `conditions[]`, `logic_operator`
    *   `category`, `severity`, `confidence`, `scope`
    *   `reason` — **REQUIRED**
    *   `related_evidence` — **REQUIRED**
*   **Returns**: `artifact_id` (e.g. `eye_mapping_xxxxxxxx` or
    `eye_rule_xxxxxxxx`), `path`, `human_summary`, `gep_rules`.

### 4. `correlation_edit_semantic_mapping`
*   **Purpose**: Edit a Mapping or Rule EYE previously authored.
*   **Refuses**: any artifact not authored by EYE
    (`mapping_source != "eye"` or `eye_authorship.created_by` doesn't
    start with `"eye"`).
*   **Key Parameters**: `artifact_id` (required), `reason` (required),
    then any subset of create-tool fields.

> [!NOTE]
> All four tools persist artifacts under `<case>/Correlation/`
> (subdirectories `wings/` and `semantic_mappings/eye/`). Analysts can
> roll back by deleting the file. Every action is recorded in the
> case audit trail with the full `EyeAuthorship` payload.

---

## 🧠 System Tools

### 1. `switch_model`
*   **Purpose**: Dynamically switches the active AI backend (e.g., Gemini 1.5 Pro to Local Llama 3).
*   **Parameters**: `model_name`.

---

> [!TIP]
> **Proactive Triage**: Upon case initialization, EYE automatically uses a combination of `query_database`, `report_add_chart`, and `report_add_data_table` to build a "Master Forensic Triage Report" following the **Ghassan Elsman Protocol**.
