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

## 🧠 System Tools

### 1. `switch_model`
*   **Purpose**: Dynamically switches the active AI backend (e.g., Gemini 1.5 Pro to Local Llama 3).
*   **Parameters**: `model_name`.

---

> [!TIP]
> **Proactive Triage**: Upon case initialization, EYE automatically uses a combination of `query_database`, `report_add_chart`, and `report_add_data_table` to build a "Master Forensic Triage Report" following the **Ghassan Elsman Protocol**.
