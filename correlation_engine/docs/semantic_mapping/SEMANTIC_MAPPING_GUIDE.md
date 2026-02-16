# Semantic Mapping System

This document describes the Semantic Mapping system within Crow-Eye's Correlation Engine, detailing its purpose, core components, and how it integrates with other parts of the application.

## 1. Purpose of Semantic Mapping

The Semantic Mapping system is designed to bridge the gap between raw, technical forensic data and human-understandable forensic intelligence. It achieves this by:

*   **Translating Technical Values:** Converting obscure event IDs, registry keys, or file paths into clear, meaningful descriptions (e.g., `EventID 4624` -> "User Login").
*   **Identifying Patterns:** Recognizing complex patterns across multiple artifacts and fields to infer significant activities (e.g., a process execution event combined with a network connection could indicate "Suspicious Network Activity").
*   **Enhancing Correlation Results:** Enriching correlated events with semantic labels, categories, severities, and confidence scores, making analysis more intuitive and efficient.
*   **Providing Context:** Giving forensic investigators immediate context about what an event or a series of events might signify.
*   **Normalizing Field Names:** Addressing inconsistencies in field naming across different forensic tools and artifacts, ensuring robust rule evaluation.

## 2. Core Components

The Semantic Mapping system is built around several key Python classes:

### 2.1. `SemanticMapping` (Basic Mapping)

The `SemanticMapping` class represents a simple, direct translation from a technical value to a semantic one.

*   **Attributes:**
    *   `source`: The name of the artifact source (e.g., "SecurityLogs", "Prefetch").
    *   `field`: The specific field within the artifact (e.g., "EventID", "executable_name").
    *   `technical_value`: The exact technical value to match (or a regex pattern).
    *   `semantic_value`: The human-readable meaning (e.g., "User Login").
    *   `description`: An optional detailed explanation.
    *   `artifact_type`: General type of artifact (e.g., "Logs", "Registry").
    *   `category`: A categorization of the semantic meaning (e.g., "authentication", "file_access").
    *   `severity`: The perceived severity (e.g., "info", "low", "medium", "high", "critical").
    *   `pattern`: A regular expression for more flexible matching.
    *   `conditions`: A list of additional multi-field conditions for more precise matching.
    *   `confidence`: A score (0.0 to 1.0) indicating the reliability of the mapping.
    *   `scope`: Defines where the mapping applies ("global", "wing", "pipeline").

*   **Functionality:**
    *   `matches(value)`: Checks if a given value matches the `technical_value` or `pattern` of the mapping.
    *   `evaluate_conditions(record)`: Evaluates any additional multi-field conditions against a record.

### 2.2. `SemanticCondition` (Advanced Rule Condition)

`SemanticCondition` instances are building blocks for more complex `SemanticRule`s. Each condition specifies a criterion to be met.

*   **Attributes:**
    *   `feather_id`: The ID of the feather (artifact parser) the condition applies to.
    *   `field_name`: The name of the field to check within that feather's record.
    *   `value`: The target value for the condition, or `"*"` for a wildcard.
    *   `operator`: How the `value` should be compared (`"equals"`, `"contains"`, `"regex"`, `"wildcard"`).

*   **Functionality:**
    *   `matches(record)`: Evaluates if the condition holds true for a given record.
    *   **Smart Field Name Matching:** Critically, this method uses `_smart_field_lookup` which leverages the `FieldAliasFTS` system to intelligently match field names, handling variations like case, underscores, and aliases (e.g., "EventID", "event_id", "Event ID" can all map to "eventid").

### 2.3. `SemanticRule` (Advanced Rule)

The `SemanticRule` class allows for the creation of sophisticated rules by combining multiple `SemanticCondition`s with logical operators.

*   **Attributes:**
    *   `rule_id`: A unique identifier for the rule.
    *   `name`: A descriptive name for the rule.
    *   `semantic_value`: The semantic outcome if the rule matches.
    *   `description`: A detailed description of what the rule identifies.
    *   `conditions`: A list of `SemanticCondition` objects that must be evaluated.
    *   `logic_operator`: `"AND"` or `"OR"`, determining how conditions are combined.
    *   `scope`: Defines where the rule applies ("global", "wing", "pipeline").
    *   `category`, `severity`, `confidence`: Metadata similar to `SemanticMapping`.

*   **Functionality:**
    *   `evaluate(records)`: Takes a dictionary of records (keyed by `feather_id`) and evaluates all its conditions based on the `logic_operator`.

### 2.4. `SemanticMappingManager`

This is the orchestrator of the entire semantic mapping system.

*   **Functionality:**
    *   **Manages Mappings and Rules:** Stores `SemanticMapping` and `SemanticRule` objects, organized by their `scope` (global, wing, pipeline).
    *   **Hierarchical Priority:** When applying rules or mappings, it respects a priority order: Wing-specific > Pipeline-specific > Global. This allows for fine-grained control and overrides.
    *   **Loading:** Loads default mappings and rules from internal definitions and from external JSON configuration files (`semantic_rules_default.json`, `semantic_rules_custom.json`).
    *   **`apply_to_record(record, artifact_type, wing_id, pipeline_id)`:** Applies all relevant `SemanticMapping`s to a single record and returns a list of matching mappings, sorted by confidence. It also applies `SemanticRule`s for identity-level records.
    *   **`apply_rules_to_identity(identity_record, wing_id, pipeline_id)`:** Specifically evaluates `SemanticRule`s against an identity record, which is crucial for the Identity-Based Correlation Engine.
    *   **File I/O:** Handles saving and loading mappings and rules to/from JSON files.

### 2.5. `FieldAliasFTS` (FTS5 Field Alias System)

An internal utility for `SemanticCondition`'s smart field matching.

*   **Purpose:** To provide robust and fast matching of field names even when they vary significantly (e.g., `event_id`, `EventID`, `Event Id`).
*   **Technology:** Utilizes an in-memory SQLite database with FTS5 (Full-Text Search Engine) to store canonical field names and their aliases.
*   **Mechanism:** Loads a comprehensive set of default aliases from JSON files located in `config/standard_fields/` (e.g., `event_identifiers.json`, `process_identifiers.json`). It can perform exact, case-insensitive, normalized, and fuzzy/alias matching.

## 3. Integration with Other Python Files

The Semantic Mapping system is deeply integrated across the Crow-Eye Correlation Engine:

*   **`correlation_engine/config/semantic_mapping.py` (Current file):**
    *   This file defines the core data structures (`SemanticMapping`, `SemanticCondition`, `SemanticRule`) and the central management logic (`SemanticMappingManager`, `FieldAliasFTS`). It is the heart of the system.

*   **`correlation_engine/wings/ui/semantic_mapping_dialog.py`:**
    *   This GUI component is responsible for providing a user interface to create, edit, and manage individual `SemanticMapping`s and `SemanticRule`s.
    *   It imports `SemanticCondition` and `SemanticRule` directly from `correlation_engine.config.semantic_mapping` to handle the data models.
    *   It interacts with an instance of `SemanticMappingManager` to add, update, and delete semantic configurations based on user input.

*   **`correlation_engine/wings/ui/main_window.py`:**
    *   The main application window integrates the semantic mapping management interface as a dedicated "Semantic Mappings" tab.
    *   It calls functions from `semantic_mapping_dialog.py` to display the creation/editing dialogs.
    *   It likely uses the `SemanticMappingManager` to load and display the existing semantic rules and mappings within the main UI table (`semantic_mappings_table`).

*   **`correlation_engine/identity_semantic_phase/*` (Implied):**
    *   The `SemanticMappingManager`'s `apply_rules_to_identity` method is specifically designed for evaluating rules against identity records. This suggests that the Identity-Based Correlation Engine (or a dedicated "identity semantic phase") will heavily utilize this manager to enrich identity correlation results with semantic context. This phase would be responsible for calling `SemanticMappingManager.apply_rules_to_identity` with the relevant identity data.

*   **`correlation_engine/engine/*` (Core Correlation Logic):**
    *   The core correlation engines (Time-Window Scanning Engine and Identity-Based Correlation Engine) will interact with `SemanticMappingManager` to apply semantic context to their results.
    *   After records are correlated, the `apply_to_record` method will be invoked for individual records to add semantic tags.
    *   For identity-level correlation, `apply_rules_to_identity` will be called to derive higher-level semantic interpretations.

*   **`correlation_engine/integration/semantic_mapping_integration.py` (Mentioned in `README.md`):**
    *   This file likely defines an interface or a concrete implementation for how the semantic mapping system integrates with the broader Crow-Eye framework. It acts as a bridge, ensuring that the semantic analysis results are properly passed to other components that consume them. It would implement `ISemanticMappingIntegration` as stated in the documentation.

*   **`configs/semantic_rules_default.json` & `configs/semantic_rules_custom.json`:**
    *   These JSON files, managed by the `SemanticMappingManager`, store the default and user-defined `SemanticRule`s and `SemanticMapping`s. This allows for persistent configuration and easy modification of semantic definitions without changing the code.

*   **`config/standard_fields/*.json`:**
    *   These configuration files provide the initial alias definitions for the `FieldAliasFTS` system, which is crucial for robust field name matching.

## 4. How Semantic Mapping Works (Workflow)

1.  **Initialization:**
    *   When the Correlation Engine starts, `SemanticMappingManager` is initialized.
    *   `FieldAliasFTS` is initialized, loading default field aliases from JSON files.
    *   `SemanticMappingManager` loads default `SemanticMapping`s and `SemanticRule`s (both built-in and from JSON config files).

2.  **User Configuration (via GUI):**
    *   Investigators can use the "Semantic Mappings" tab in the GUI (`main_window.py` and `semantic_mapping_dialog.py`) to:
        *   Define new `SemanticMapping`s (e.g., map a specific registry value to "Persistence Mechanism").
        *   Create complex `SemanticRule`s with multiple `SemanticCondition`s (e.g., "IF process A executed AND process B created a file THEN 'Malicious Payload Dropper'").
        *   These configurations are then saved by the `SemanticMappingManager` to custom JSON files.

3.  **Correlation Process:**
    *   As the correlation engine processes forensic records:
        *   For individual records, `SemanticMappingManager.apply_to_record()` is called. This method iterates through applicable `SemanticMapping`s and evaluates if they match the record's values, potentially using regex and multi-field conditions.
        *   For identity-level records (results of identity correlation), `SemanticMappingManager.apply_rules_to_identity()` is called. This evaluates the more complex `SemanticRule`s against the aggregated identity data.

4.  **Field Name Normalization:**
    *   During condition evaluation, `SemanticCondition`'s `matches` method intelligently looks up field names using `FieldAliasFTS`. This ensures that rules written with one field name (e.g., "EventID") can correctly match data where the field might be named differently (e.g., "event_id").

5.  **Result Enrichment:**
    *   Any matching `SemanticMapping`s or `SemanticRule`s enrich the original forensic records or correlation results with their `semantic_value`, `category`, `severity`, and `confidence` scores.

6.  **Display:**
    *   The enriched results are then displayed in the GUI viewers, where "Semantic Columns" provide immediate insight into the meaning of the detected activities.

This comprehensive system provides a powerful and flexible way to transform raw forensic data into actionable intelligence.