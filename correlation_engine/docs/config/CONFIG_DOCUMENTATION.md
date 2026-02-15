# Config Directory Documentation

## Table of Contents

- [Overview](#overview)
- [Directory Structure](#directory-structure)
- [Distinction Between 'config/' and 'configs/' Directories](#distinction-between-config-and-configs-directories)
- [Key Concepts](#key-concepts)
- [Configuration Loading & Reloading Workflow](#configuration-loading--reloading-workflow)
- [Files in This Directory](#files-in-this-directory)
  - [config_manager.py](#config_managerpy)
  - [integrated_configuration_manager.py](#integrated_configuration_managerpy)
  - [artifact_type_registry.py](#artifact_type_registrypy)
  - [artifact_types.json](#artifact_typesjson)
  - [centralized_score_config.py](#centralized_score_configpy)
  - [score_configuration_manager.py](#score_configuration_managerpy)
  - [semantic_config.py](#semantic_configpy)
  - [semantic_mapping.py](#semantic_mappingpy)
  - [semantic_mapping_discovery.py](#semantic_mapping_discoverypy)
  - [semantic_rule_validator.py](#semantic_rule_validatorpy)
  - [configuration_change_handler.py](#configuration_change_handlerpy)
  - [configuration_conflict_resolver.py](#configuration_conflict_resolverpy)
  - [configuration_migration.py](#configuration_migrationpy)
  - [score_config_migration_tool.py](#score_config_migration_toolpy)
  - [feather_config.py](#feather_configpy)
  - [wing_config.py](#wing_configpy)
  - [pipeline_config.py](#pipeline_configpy)
  - [session_state.py](#session_statepy)
  - [identifier_extraction_config.py](#identifier_extraction_configpy)
  - [pipeline_config_manager.py](#pipeline_config_managerpy)
  - [case_configuration_file_manager.py](#case_configuration_file_managerpy)
  - [case_configuration_manager.py](#case_configuration_managerpy)
  - [case_specific_configuration_manager.py](#case_specific_configuration_managerpy)
  - [default_mappings/ Subdirectory](#default_mappings-subdirectory)
- [Common Modification Scenarios](#common-modification-scenarios)
- [Configuration File Formats](#configuration-file-formats)
- [See Also](#see-also)

---

## Overview

The **config/** directory is a highly complex and foundational part of the Crow-Eye Correlation Engine. It provides a comprehensive, multi-layered system for managing all aspects of configuration, from low-level file operations and data models to high-level case management, conflict resolution, and dynamic updates. Its primary goal is to ensure flexibility, extensibility, consistency, and persistence of various settings critical to the correlation process.

### Purpose
- Define data models for feathers, wings, and pipelines.
- Manage global, case-specific, and integrated configurations (semantic mappings, scoring, progress tracking, engine selection).
- Centralize definitions for artifact types and scoring parameters.
- Handle loading, saving, and persistence of all configuration files (JSON).
- Validate configuration structures and semantic rules.
- Resolve conflicts between different configuration levels (global, pipeline, wing, case).
- Provide mechanisms for live configuration updates via an observer pattern.
- Manage low-level file operations: creation, validation, repair, compression, archiving, and migration of case-specific configurations.
- Support high-level case configuration management: switching, comparison, copying, export/import.

### How It Fits in the Overall System

The `config` directory is a **foundational and pervasive layer** within the correlation engine. It has minimal internal dependencies within the `correlation_engine` beyond its own files and the core Python standard library. Other components of the correlation engine (e.g., `engine/`, `pipeline/`, `gui/`, `integration/`) heavily depend on and consume configurations managed here to drive their behavior.

**Key Consumers**:
- `engine/` components: Utilize scoring configurations, semantic mappings, and artifact type definitions to perform correlation logic.
- `pipeline/` components: Load pipeline configurations to orchestrate analysis workflows.
- `gui/` components: Display and allow editing of configurations, manage session state, and react to dynamic configuration changes.
- `integration/` components: Generate default configurations, interact with case-specific settings, and provide seamless integration with the main Crow-Eye application.

## Directory Structure

```
Crow-Eye/correlation_engine/config/
├── __pycache__/
├── default_mappings/             # Default semantic mapping files (YAML/JSON/Python)
├── __init__.py
├── artifact_type_registry.py     # Singleton registry for artifact type definitions
├── artifact_types.json           # JSON file for artifact type definitions
├── case_configuration_file_manager.py # Low-level file operations for case configs
├── case_configuration_manager.py # High-level case config management (compare, copy, export)
├── case_specific_configuration_manager.py # Manages case-specific semantic & scoring overrides
├── centralized_score_config.py   # Dataclass for global score configuration (thresholds, weights)
├── config_manager.py             # Basic CRUD for feather/wing/pipeline JSON files
├── configuration_change_handler.py # Notifies components of config changes via observer pattern
├── configuration_conflict_resolver.py # Detects and resolves conflicts between config levels
├── configuration_migration.py    # Utilities for migrating old config formats
├── feather_config.py             # Dataclass for Feather configurations
├── identifier_extraction_config.py # Dataclasses for identifier extraction & timestamp parsing
├── integrated_configuration_manager.py # Manages global/case-specific integrated configs (scoring, semantic, progress)
├── pipeline_config_manager.py    # Central coordinator for pipeline lifecycle (session, discovery, loading)
├── pipeline_config.py            # Dataclass for Pipeline configurations
├── score_config_migration_tool.py # Tool to scan codebase and create centralized score config
├── score_configuration_manager.py # Singleton manager for CentralizedScoreConfig (loading, updating, callbacks)
├── semantic_config.py            # Dataclass for semantic mapping system configuration (paths, thresholds, performance)
├── semantic_mapping_discovery.py # Service to discover/load semantic mappings from various sources/formats
├── semantic_mapping.py           # Core semantic mapping system: FieldAliasFTS, SemanticMapping, SemanticRule, SemanticMappingManager
├── semantic_rule_validator.py    # Validates semantic rule JSON files against schema
└── session_state.py              # Dataclasses for session state, metadata, and status tracking (+ SessionStateManager)
```

## Distinction Between 'config/' and 'configs/' Directories

The Crow-Eye project contains two similarly named directories related to configuration, which serve distinct purposes:

-   **`Crow-Eye/config/` (Singular)**:
    This directory primarily houses the *implementation logic* for configuration management within the Correlation Engine. It contains Python modules (e.g., `configuration_manager.py`, `case_history_manager.py`, `data_models.py`) responsible for loading, saving, validating, and managing various configuration types. It also stores *dynamic* configuration data, such as session-specific or active case-specific JSON files (e.g., `last_case.json`, temporary `case_X.json` files generated during a session). Essentially, `Crow-Eye/config/` is where the **system and its Python code for handling configurations** reside.

-   **`Crow-Eye/configs/` (Plural)**:
    This directory serves as the *storage location* for the actual static configuration *files* that define the behavior of the Correlation Engine. These are typically user-editable JSON/YAML files that describe feathers, wings, pipelines, and semantic rules (e.g., `semantic_rules_default.json`, and subdirectories like `feathers/`, `wings/`, `pipelines/` containing their respective configurations). These files are loaded and interpreted by the Python modules found in `Crow-Eye/config/`. In essence, `Crow-Eye/configs/` is where the **configuration data files themselves** are kept.

**Summary**:
-   `Crow-Eye/config/`: **Implementation (Python code) and dynamic/session configuration data files.**
-   `Crow-Eye/configs/`: **Static configuration data files (JSON/YAML) that define system behavior.**

## Key Concepts

## Configuration Loading & Reloading Workflow

```mermaid
graph TD
    subgraph "Configuration Management Workflow"
        start((Start)) --> load_global(Load Global Configs<br/>(integrated_configuration_manager.py))
        load_global --> check_case(Check for Case-Specific Overrides<br/>(case_specific_configuration_manager.py))
        check_case -- Case Overrides Present --> merge_configs(Merge Configs<br/>(configuration_conflict_resolver.py))
        check_case -- No Case Overrides --> effective_config(Form Effective Config)
        merge_configs --> effective_config
        
        effective_config --> init_components(Initialize Components with Config<br/>(semantic_mapping_integration.py,<br/>weighted_scoring_integration.py, etc.))
        init_components --> monitor_changes(Monitor for Config Changes<br/>(configuration_change_handler.py))
        
        monitor_changes -- Change Detected --> handle_change(Handle Config Change<br/>(configuration_change_handler.py))
        handle_change --> validate_change(Validate & Assess Impact)
        validate_change --> notify_listeners(Notify Listeners)
        notify_listeners --> update_components(Update Affected Components)
        update_components --> monitor_changes
    end

    style start fill:#fff,stroke:#333,stroke-width:2px
    style load_global fill:#f9f,stroke:#333,stroke-width:2px
    style check_case fill:#ccf,stroke:#333,stroke-width:2px
    style merge_configs fill:#bbf,stroke:#333,stroke-width:2px
    style effective_config fill:#afa,stroke:#333,stroke-width:2px
    style init_components fill:#bbf,stroke:#333,stroke-width:2px
    style monitor_changes fill:#ffc,stroke:#333,stroke-width:2px
    style handle_change fill:#f9f,stroke:#333,stroke-width:2px
    style validate_change fill:#ccf,stroke:#333,stroke-width:2px
    style notify_listeners fill:#afa,stroke:#333,stroke-width:2px
    style update_components fill:#bbf,stroke:#333,stroke-width:2px

```


-   **FeatherConfig**: Describes how raw artifact data is transformed into a standardized SQLite "feather" database.
-   **WingConfig**: Defines a correlation "rule," specifying feathers to use, time windows, filters, and scoring parameters.
-   **PipelineConfig**: Orchestrates a complete analysis workflow, linking `FeatherConfig`s and `WingConfig`s with execution settings, engine choices, and output options.
-   **Artifact Type Registry**: A centralized, singleton repository for forensic artifact definitions (weights, tiers, priorities).
-   **Centralized Score Configuration**: A single source of truth for global scoring parameters (thresholds, tier weights, penalties, bonuses).
-   **Semantic Mapping**: Translates technical values from artifacts into human-readable semantic meanings, using advanced rules and fuzzy field matching.
-   **Case-Specific Configuration**: Allows global settings (e.g., semantic mappings, scoring weights) to be overridden or extended for individual forensic cases.
-   **Integrated Configuration**: Aggregates various system-wide settings (semantic mapping, scoring, progress tracking, engine selection) that can be globally defined or case-specifically overridden.
-   **Observer Pattern**: Enables dynamic updates where components register to be notified and react to changes in configuration without requiring application restarts.
-   **Conflict Resolution**: Mechanisms to detect and resolve discrepancies when configurations are defined at multiple hierarchical levels (global, pipeline, wing, case).
-   **Configuration Migration**: Tools and utilities to manage the evolution of configuration file formats, ensuring backward compatibility.

## Files in This Directory

### config_manager.py

**Purpose**: This module implements a non-singleton `ConfigManager` class that provides basic CRUD (Create, Read, Update, Delete) operations for Feather, Wing, and Pipeline JSON configuration files. It organizes these files within a specified configuration directory structure and includes schemas for basic validation. It also handles the loading and saving of `weighted_scoring.json` and `semantic_mapping.json` global configurations with validation.

**Key Classes**:
1.  **`ConfigManager`**: Manages file-based JSON configurations.

**Key Methods**:
-   `__init__(self, config_directory: str = "configs")`: Initializes with a root directory for configurations.
-   `save_feather_config(self, config: FeatherConfig, custom_name: Optional[str] = None) -> str`: Saves a FeatherConfig to `feathers/` subdirectory.
-   `load_feather_config(self, config_name: str) -> FeatherConfig`: Loads a FeatherConfig by name. (Similar methods for Wing and Pipeline configs).
-   `list_feather_configs(self) -> List[str]`: Lists available FeatherConfigs. (Similar methods for Wing and Pipeline configs).
-   `delete_feather_config(self, config_name: str)`: Deletes a FeatherConfig. (Similar methods for Wing and Pipeline configs).
-   `get_config_info(self, config_type: str, config_name: str) -> Dict`: Gets summary info.
-   `export_config(self, config_type: str, config_name: str, export_path: str)`: Exports a config.
-   `import_config(self, config_type: str, import_path: str, new_name: Optional[str] = None)`: Imports a config.
-   `get_weighted_scoring_config(self) -> Optional[Dict]`: Loads global weighted scoring config (`weighted_scoring.json`).
-   `save_weighted_scoring_config(self, config: Dict) -> bool`: Saves global weighted scoring config.
-   `get_semantic_mapping_config(self) -> Optional[Dict]`: Loads global semantic mapping config (`semantic_mapping.json`).
-   `save_semantic_mapping_config(self, config: Dict) -> bool`: Saves global semantic mapping config.
-   `validate_config_structure(self, config_data: Dict[str, Any], config_type: str) -> Tuple[bool, List[str]]`: Validates config data against predefined schemas.
-   `save_config_atomic(self, config_data: Dict, config_path: Path) -> Tuple[bool, str]`: Atomically saves configuration to prevent corruption.

**Dependencies**: `json`, `logging`, `pathlib`, `tempfile`, `shutil`, `FeatherConfig`, `WingConfig`, `PipelineConfig`.

**Dependents**: Used by UI components and other managers for basic config file operations.

**Impact**: MEDIUM - Provides file-level persistence for core configurations.

---

### integrated_configuration_manager.py

**Purpose**: This module implements `IntegratedConfigurationManager`, a non-singleton class that manages an aggregated set of system-wide configurations: semantic mapping, weighted scoring, progress tracking, and engine selection. It handles loading global defaults, merging with case-specific overrides, and applies an observer pattern to notify registered components of configuration changes. This is distinct from the main application's `ConfigurationManager` (which often handles higher-level case management and PyQt signals).

**Key Classes**:
1.  **`SemanticMappingConfig` (dataclass)**: Configuration specific to semantic mapping.
2.  **`WeightedScoringConfig` (dataclass)**: Configuration specific to weighted scoring.
3.  **`ProgressTrackingConfig` (dataclass)**: Configuration for progress reporting.
4.  **`EngineSelectionConfig` (dataclass)**: Configuration for engine selection behavior.
5.  **`CaseSpecificConfig` (dataclass)**: Configuration for case-specific overrides.
6.  **`IntegratedConfiguration` (dataclass)**: Aggregates all the above configurations.
7.  **`IntegratedConfigurationManager`**: Manages global and effective integrated configurations.

**Key Methods**:
-   `__init__(self, config_directory: str = "configs")`: Initializes the manager, loads global config.
-   `_load_global_configuration(self)`: Loads `integrated_config.json` or creates default.
-   `_parse_configuration_data(self, config_data: Dict[str, Any]) -> IntegratedConfiguration`: Parses raw dict into dataclass.
-   `_save_global_configuration(self)`: Saves global configuration to `integrated_config.json`.
-   `get_global_configuration(self) -> IntegratedConfiguration`: Returns the global config.
-   `get_effective_configuration(self) -> IntegratedConfiguration`: Returns the merged global + case-specific config.
-   `load_case_specific_configuration(self, case_id: str) -> bool`: Loads case-specific overrides from `cases/{case_id}.json`.
-   `save_case_specific_configuration(self, case_config: CaseSpecificConfig) -> bool`: Saves case-specific overrides.
-   `_update_effective_configuration(self)`: Merges global and case-specific configs, notifies listeners.
-   `validate_configuration(self, config: IntegratedConfiguration) -> Dict[str, Any]`: Validates the integrated configuration.
-   `resolve_configuration_conflicts(...)`: (Delegates to `ConfigurationConflictResolver` for complex scenarios).
-   `add_configuration_change_listener(self, listener: callable)`: Registers an observer.
-   `_notify_configuration_change(self)`: Notifies registered listeners of changes.
-   `register_observer(self, callback: callable)`: Alias for `add_configuration_change_listener`.

**Dependencies**: `json`, `logging`, `pathlib`, `dataclasses`, `datetime`, `artifact_type_registry` (for default weights), `case_specific_configuration_manager` (for `CaseSpecificConfig`).

**Dependents**: Core engine components, UI for global settings, components using observer pattern for live updates.

**Impact**: CRITICAL - Manages system-wide settings, enables dynamic updates and case-specific overrides.

---

### artifact_type_registry.py

**Purpose**: This module implements a **singleton** `ArtifactTypeRegistry`. It provides a centralized, consistent source of truth for forensic artifact type definitions (ID, name, description, default weights, tiers, anchor priorities, categories, forensic strength) across the application. It loads these definitions from `artifact_types.json`, falling back to hard-coded defaults if the file is not found or corrupted. Supports dynamic reloading.

**Key Classes**:
1.  **`ArtifactType` (dataclass)**: Represents a single artifact definition.
2.  **`ArtifactTypeRegistry` (singleton)**: The manager for all artifact types.

**Key Methods**:
-   `__new__`, `__init__`: Singleton implementation and initialization.
-   `_load_default_configuration()`: Loads `artifact_types.json` or creates default.
-   `_find_config_file()`: Locates `artifact_types.json`.
-   `_load_from_file(config_path: Path)`: Loads from JSON.
-   `_create_default_configuration()`: Creates default `artifact_types.json`.
-   `_load_hardcoded_defaults()`: Fallback to in-code defaults.
-   `get_all_types() -> List[str]`: Get all artifact type IDs.
-   `get_artifact(self, artifact_id: str) -> Optional[ArtifactType]`: Get specific artifact definition.
-   `get_default_weight(self, artifact_id: str) -> float`: Get default weight.
-   `get_default_tier(self, artifact_id: str) -> int`: Get default tier.
-   `get_anchor_priority_list() -> List[str]`: Get types sorted by anchor priority.
-   `get_default_weights_dict() -> Dict[str, float]`: Get dictionary of all default weights.
-   `register_artifact(self, artifact: ArtifactType) -> bool`: Register or update an artifact.
-   `reload() -> bool`: Reloads definitions from file.
-   `is_valid_artifact_type(self, artifact_id: str) -> bool`: Checks validity.
-   `get_artifacts_by_category(self, category: str) -> List[ArtifactType]`: Filters by category.
-   `get_artifacts_by_forensic_strength(self, strength: str) -> List[ArtifactType]`: Filters by strength.
-   `get_version() -> str`: Get registry version.
-   `get_artifact_count() -> int`: Get count of registered types.
-   **`get_registry() -> ArtifactTypeRegistry`**: Global access function for the singleton instance.

**Dependencies**: `json`, `logging`, `pathlib`, `dataclasses`, `threading.Lock`.

**Dependents**: `integrated_configuration_manager`, `wing_config`, `score_configuration_manager`, scoring and semantic mapping logic, feather generation.

**Impact**: CRITICAL - Centralizes all artifact metadata, crucial for consistent scoring and semantic evaluation.

---

### artifact_types.json

**Purpose**: This JSON file stores the definitions for forensic artifact types used by the `ArtifactTypeRegistry`. It contains properties such as `id`, `name`, `description`, `default_weight`, `default_tier`, `anchor_priority`, `category`, and `forensic_strength`. It serves as the primary external source for the registry's data.

**Structure**: A JSON object containing a `version` and an `artifact_types` array, where each element is an artifact definition.

**Example Entry**:
```json
{
  "id": "Logs",
  "name": "Event Logs",
  "description": "Windows Event Logs (Security, System, Application)",
  "default_weight": 0.4,
  "default_tier": 1,
  "anchor_priority": 1,
  "category": "primary_evidence",
  "forensic_strength": "high"
}
```

**Dependencies**: Consumed by `artifact_type_registry.py`.

**Impact**: HIGH - Direct source for artifact metadata.

---

### centralized_score_config.py

**Purpose**: This module defines the `CentralizedScoreConfig` dataclass, which acts as a single source of truth for all score-related configurations. It ensures consistency across wings, engines, and GUI components by defining global parameters for score interpretation thresholds, tier weights for evidence levels, scoring penalties, and bonuses. It includes methods for self-validation and persistence.

**Key Classes**:
1.  **`CentralizedScoreConfig` (dataclass)**: Holds all global scoring parameters.

**Key Fields**:
-   `thresholds` (Dict[str, float]): Defines score ranges for interpretations (e.g., 'low', 'medium', 'high').
-   `tier_weights` (Dict[str, float]): Weights assigned to different evidence tiers (e.g., 'tier1', 'tier2').
-   `penalties` (Dict[str, float]): Penalties applied for specific conditions (e.g., 'missing_primary').
-   `bonuses` (Dict[str, float]): Bonuses applied for specific conditions (e.g., 'exact_time_match').
-   `version` (str): Configuration version.
-   `last_updated` (str): Timestamp of last update.

**Key Methods**:
-   `to_dict()`: Converts to dictionary.
-   `to_json()`: Converts to JSON string.
-   `save_to_file(file_path: str)`: Saves config to a JSON file.
-   `load_from_file(file_path: str) -> CentralizedScoreConfig`: Loads config from a JSON file.
-   `get_default() -> CentralizedScoreConfig`: Returns a default configuration instance.
-   `interpret_score(self, score: float) -> str`: Interprets a numerical score into a human-readable string.
-   `get_tier_weight(self, tier: int) -> float`: Retrieves weight for a given tier.
-   `validate() -> bool`: Validates configuration values (e.g., ranges, non-negativity).

**Dependencies**: `json`, `logging`, `pathlib`, `dataclasses`, `datetime`, `typing`.

**Dependents**: `score_configuration_manager`, `weighted_scoring` (in `engine/`), GUI for display.

**Impact**: CRITICAL - Centralizes scoring logic and parameters for the entire correlation engine.

---

### score_configuration_manager.py

**Purpose**: This module provides a **singleton** `ScoreConfigurationManager`. It acts as the central access point and manager for the `CentralizedScoreConfig` instance, ensuring all components reference the same up-to-date scoring configuration. It handles loading the configuration (from file or default), applying updates, validating changes, and notifying registered components of score-related configuration updates via a callback mechanism.

**Key Classes**:
1.  **`ScoreConfigurationManager` (singleton)**: Manages the `CentralizedScoreConfig`.

**Key Methods**:
-   `__new__(cls)`: Singleton pattern implementation (thread-safe).
-   `load_configuration(self, config_path: Optional[str] = None) -> CentralizedScoreConfig`: Loads config from file or uses default.
-   `get_configuration(self) -> CentralizedScoreConfig`: Returns the currently loaded config (loads default if none yet).
-   `update_configuration(self, new_config: CentralizedScoreConfig, save: bool = True)`: Updates the config, validates, saves, and notifies listeners.
-   `_notify_components(self)`: Notifies all registered callbacks of a config update.
-   `register_update_callback(self, callback: Callable[[CentralizedScoreConfig], None])`: Registers a function to be called on updates.
-   `unregister_update_callback(self, callback: Callable[[CentralizedScoreConfig], None])`: Unregisters a callback.
-   `validate_consistency(self) -> List[str]`: Checks for potential inconsistencies in score configuration usage.
-   `get_config_path() -> Optional[str]`: Returns path of loaded config file.
-   `reload_configuration()`: Reloads config from file.
-   `reset_to_default()`: Resets config to default values.
-   `export_configuration(self, export_path: str)`: Exports current config to file.

**Dependencies**: `logging`, `pathlib`, `typing`, `threading`, `centralized_score_config`.

**Dependents**: `wing_config` (to get score thresholds/tier weights), `integrated_configuration_manager`, `weighted_scoring` (in `engine/`), GUI components.

**Impact**: CRITICAL - Provides centralized, dynamic management of scoring parameters across the system.

---

### semantic_config.py

**Purpose**: This module defines the `SemanticConfig` dataclass, a centralized, type-safe configuration for the entire semantic mapping system. It encapsulates settings for file paths (default rules, custom rules, schema), confidence thresholds, severity levels, state flags (enabled, strict validation), performance parameters (batch size, cache), progress reporting, and error handling for semantic rule processing. It includes methods for validation and persistence, and provides global access to a default instance.

**Key Classes**:
1.  **`SemanticConfig` (dataclass)**: Holds all configuration parameters for semantic mappings.

**Key Fields**:
-   `rules_file_path`, `custom_rules_file_path`, `schema_file_path`: Paths to rule files.
-   `default_confidence_threshold`, `min_confidence`, `max_confidence`: Confidence thresholds.
-   `severity_levels`: List of valid severity levels.
-   `enabled`, `validate_on_load`, `strict_validation`: Feature flags.
-   `batch_size`, `cache_size`, `cache_ttl_seconds`: Performance settings.
-   `enable_progress_reporting`, `progress_update_interval`: Progress settings.
-   `continue_on_error`, `max_errors_before_abort`, `log_json_parse_errors`: Error handling settings.
-   `rule_priority_order`: Order for applying rules.

**Key Methods**:
-   `validate() -> Tuple[bool, List[str]]`: Validates configuration values.
-   `from_file(config_path: str) -> SemanticConfig`: Loads config from JSON file.
-   `to_file(config_path: str, indent: int = 2)`: Saves config to JSON file.
-   `get_default() -> SemanticConfig`: Returns a default config instance.
-   `to_dict()`, `from_dict(config_dict: Dict[str, Any])`: Convert to/from dict.
-   `get_rules_file_path()`, `get_custom_rules_file_path()`, `get_schema_file_path()`: Resolve absolute paths.
-   `is_severity_valid(severity: str) -> bool`, `get_severity_index(severity: str) -> int`, `is_confidence_valid(confidence: float) -> bool`: Validation helpers.
-   **`get_global_config() -> SemanticConfig`**: Global access for the default instance.

**Dependencies**: `json`, `os`, `dataclasses`, `typing`, `pathlib`.

**Dependents**: `semantic_mapping`, `semantic_rule_validator`, GUI components.

**Impact**: CRITICAL - Centralizes the configuration for the entire semantic mapping system.

---

### semantic_mapping.py

**Purpose**: This module implements a comprehensive and highly optimized semantic mapping system. It translates technical values from forensic artifacts into human-readable semantic meanings. This involves:
-   **Field Alias Matching**: Using `FieldAliasFTS` (SQLite FTS5) for fast, fuzzy, and robust field name lookup.
-   **Basic Mappings**: `SemanticMapping` dataclass for direct value-to-semantic translations.
-   **Advanced Rules**: `SemanticCondition` and `SemanticRule` dataclasses for complex, multi-field rules with AND/OR logic and confidence scoring.
-   **Hierarchical Management**: `SemanticMappingManager` which stores and applies global, wing-specific, and pipeline-specific rules/mappings with clear priority. It loads built-in default rules and custom rules from JSON files.

**Key Classes**:
1.  **`FieldAliasFTS`**: Uses SQLite FTS5 for fast, fuzzy field alias matching. Loads aliases from `Crow-Eye/config/standard_fields/` JSON files.
2.  **`SemanticMapping` (dataclass)**: Basic value-to-semantic mapping.
3.  **`SemanticCondition` (dataclass)**: A single condition for a `SemanticRule`, with smart field lookup.
4.  **`SemanticRule` (dataclass)**: An advanced rule composed of `SemanticCondition`s with logical operators.
5.  **`SemanticMappingManager`**: The central manager for all semantic mappings and rules.

**Key Methods (of `SemanticMappingManager`):**
-   `__init__()`: Initializes, loads default rules/mappings.
-   `add_mapping(self, mapping: SemanticMapping)`: Adds a basic mapping.
-   `get_mappings_by_artifact(self, artifact_type: str) -> List[SemanticMapping]`: Filters mappings by artifact type.
-   `add_rule(self, rule: SemanticRule)`: Adds an advanced rule.
-   `get_rules(self, scope: str = "global", ...) -> List[SemanticRule]`: Gets rules by scope.
-   `get_all_rules_for_execution(...) -> List[SemanticRule]`: Gets all applicable rules with priority.
-   `apply_to_record(self, record: Dict[str, Any], ...) -> List[SemanticMapping]`: Applies mappings to a record.
-   `apply_rules_to_identity(self, identity_record: Dict[str, Any], ...) -> List[SemanticRule]`: Applies rules to an identity record.
-   `save_to_file(self, file_path: Path, ...)`: Saves mappings/rules to JSON.
-   `load_from_file(self, file_path: Path)`: Loads mappings/rules from JSON.

**Dependencies**: `json`, `logging`, `re`, `uuid`, `sqlite3`, `threading`, `dataclasses`, `pathlib`, `typing`, `functools`.

**Dependents**: Correlation engine components for semantic evaluation, GUI for rule management.

**Impact**: CRITICAL - Implements the core semantic evaluation logic, crucial for interpreting correlation results.

---

### semantic_mapping_discovery.py

**Purpose**: This module provides a `SemanticMappingDiscovery` service that automatically discovers and loads semantic mapping configurations from various sources and formats, and merges them into a `SemanticMappingManager`. It supports YAML, JSON, and Python files, prioritizes mappings (Wing-specific > Global > Built-in), and can detect conflicts. It's essential for flexible and extensible semantic rule management.

**Key Classes**:
1.  **`MappingSource` (dataclass)**: Represents a discovered mapping file (path, format, scope, priority).
2.  **`SemanticMappingDiscovery`**: The core service for discovery and loading mapping files.

**Key Methods**:
-   `__init__(self, debug_mode: bool = False)`: Initializes with search paths.
-   `discover_mappings(self, wing_dir: Optional[Path] = None) -> List[MappingSource]`: Finds all mapping files in configured paths.
-   `_discover_in_directory(self, directory: Path, scope: str, priority: int, ...)`: Helper to scan directories.
-   `load_all_mappings(self, manager: SemanticMappingManager, ...) -> int`: Loads all discovered mappings into a `SemanticMappingManager` based on priority.
-   `load_from_source(self, source: MappingSource) -> List[SemanticMapping]`: Loads mappings from a single source file (delegates to parsers).
-   `parse_yaml(self, file_path: Path) -> List[SemanticMapping]`: Parses YAML mapping files.
-   `parse_json(self, file_path: Path) -> List[SemanticMapping]`: Parses JSON mapping files.
-   `parse_python(self, file_path: Path) -> List[SemanticMapping]`: Parses Python mapping files.
-   `detect_conflicts(self, manager: SemanticMappingManager) -> List[Dict[str, Any]]`: Detects value conflicts in loaded mappings.
-   `get_coverage_statistics(self, manager: SemanticMappingManager) -> Dict[str, Any]`: Provides statistics on mapping coverage.
-   **`discover_and_load_mappings(manager: SemanticMappingManager, ...)`**: Convenience function to perform discovery and loading.

**Discovery Paths**:
-   Global: `~/.crow-eye/semantic_mappings/`
-   Wing-specific: `<wing_dir>/semantic_mappings/`
-   Built-in: `correlation_engine/config/default_mappings/`

**Dependencies**: `json`, `logging`, `yaml`, `pathlib`, `typing`, `dataclasses`, `importlib.util`, `sys`, `semantic_mapping`.

**Dependents**: `integrated_configuration_manager`, GUI for rule management.

**Impact**: HIGH - Provides flexible and extensible management for semantic rule loading.

---

### semantic_rule_validator.py

**Purpose**: This module provides a `SemanticRuleValidator` to rigorously validate semantic rule JSON files against expected structural and content-based criteria. It ensures data integrity before rules are loaded into the system by checking JSON syntax, schema structure (for rules and conditions), field types/values, and provides detailed error reporting with actionable suggestions.

**Key Classes**:
1.  **`ValidationError` (dataclass)**: Represents a single validation error with context (rule ID, field, message, severity, suggestion).
2.  **`ValidationResult` (dataclass)**: Aggregates all errors and warnings from a validation run.
3.  **`SemanticRuleValidator`**: The core validator class.

**Key Methods**:
-   `__init__(self, schema_path: Optional[Path] = None)`: Initializes with an optional JSON schema path.
-   `_load_schema(self) -> Optional[Dict[str, Any]]`: Loads an external JSON schema.
-   `validate_file(self, json_path: Path) -> ValidationResult`: Validates an entire JSON file containing rules.
-   `validate_rule(self, rule: Any, rule_index: int) -> List[ValidationError]`: Validates a single `SemanticRule` object.
-   `_validate_condition(self, condition: Any, rule_id: Optional[str], rule_index: int, cond_index: int) -> List[ValidationError]`: Validates a single `SemanticCondition` object.
-   `generate_error_report(self, result: ValidationResult) -> str`: Generates a human-readable summary of validation results.

**Validations Performed**:
-   File existence and readability.
-   JSON syntax.
-   Top-level structure (must be dict with 'rules' list).
-   Rule structure (required fields, types, valid enums for operators, severity, scope).
-   Condition structure (required fields, types, valid operators, regex validity).
-   Unique rule IDs (warning for duplicates).

**Dependencies**: `json`, `logging`, `re`, `dataclasses`, `pathlib`, `typing`.

**Dependents**: `semantic_mapping`, GUI rule editors.

**Impact**: MEDIUM - Ensures the quality and correctness of semantic rules.

---

### configuration_change_handler.py

**Purpose**: This module implements a `ConfigurationChangeHandler`, which acts as a centralized notification system for configuration changes. It uses an observer pattern to allow components to register as listeners for specific configuration sections (e.g., semantic mapping, weighted scoring) or for all changes. When a configuration is updated (e.g., via `IntegratedConfigurationManager`), this handler detects affected sections and notifies relevant listeners, enabling dynamic reactions without requiring application restarts. It also includes validation and impact assessment for proposed changes.

**Key Classes**:
1.  **`ConfigurationChangeEvent` (dataclass)**: Event object detailing old/new configurations, changed sections, and timestamp.
2.  **`ConfigurationChangeHandler`**: The core manager for configuration change notifications.

**Key Methods**:
-   `__init__(self)`: Initializes the listener registry.
-   `register_listener(self, section: str, callback: Callable[[ConfigurationChangeEvent], None])`: Registers a callback for a specific config section.
-   `unregister_listener(self, section: str, callback: Callable)`: Unregisters a callback.
-   `handle_configuration_change(self, old_config: IntegratedConfiguration, new_config: IntegratedConfiguration)`: Detects changes, creates an event, and notifies listeners.
-   `_detect_changed_sections(self, old_config: IntegratedConfiguration, new_config: IntegratedConfiguration) -> List[str]`: Identifies which sections of `IntegratedConfiguration` have changed.
-   `_notify_listeners(self, event: ConfigurationChangeEvent)`: Iterates and calls registered listeners.
-   `validate_configuration_change(self, old_config: IntegratedConfiguration, new_config: IntegratedConfiguration) -> Dict[str, Any]`: Assesses the impact and conflicts of a proposed change.
-   `_assess_change_impact(self, section: str, old_config: IntegratedConfiguration, new_config: IntegratedConfiguration) -> Dict[str, Any]`: Determines the severity and description of a change's impact.
-   `_check_configuration_conflicts(self, config: IntegratedConfiguration) -> List[str]`: Identifies logical conflicts within the `IntegratedConfiguration`.
-   **`get_configuration_change_handler() -> ConfigurationChangeHandler`**: Global access function for the singleton instance.
-   **`register_configuration_listener(...)`**, **`unregister_configuration_listener(...)`**, **`notify_configuration_change(...)`**: Convenience functions for global listener management.

**Dependencies**: `logging`, `typing`, `dataclasses`, `integrated_configuration_manager`.

**Dependents**: `integrated_configuration_manager` (which uses it to notify changes), UI components, engine integrations.

**Impact**: HIGH - Enables dynamic, live configuration updates and ensures consistency across components.

---

### configuration_conflict_resolver.py

**Purpose**: This module provides a `ConfigurationConflictResolver` to systematically detect and resolve conflicts between different hierarchical levels of configuration: global, pipeline-specific, wing-specific, and case-specific. It defines a clear priority order (Case > Wing > Pipeline > Global) and supports various resolution strategies (e.g., precedence, additive merge).

**Key Classes**:
1.  **`ConflictSeverity` (Enum)**: Severity levels (LOW, MEDIUM, HIGH, CRITICAL).
2.  **`ResolutionStrategy` (Enum)**: Strategies for conflict resolution.
3.  **`ConfigurationConflict` (dataclass)**: Represents a single conflict.
4.  **`ConflictResolutionResult` (dataclass)**: Summarizes the overall resolution process.
5.  **`ConfigurationConflictResolver`**: The core resolver class.

**Key Methods**:
-   `__init__(self)`: Initializes with known resolution strategies.
-   `resolve_configuration_conflicts(self, global_config: IntegratedConfiguration, ...) -> ConflictResolutionResult`: Main entry point for conflict resolution.
-   `_detect_all_conflicts(...)`: Identifies conflicts across all sections.
-   `_detect_semantic_mapping_conflicts(...)`, `_detect_weighted_scoring_conflicts(...)`, etc.: Specific conflict detection for each config section.
-   `_resolve_conflicts(...)`: Applies resolution strategies to detected conflicts.
-   `_resolve_case_precedence(...)`, `_resolve_wing_precedence(...)`, etc.: Implement specific resolution strategies.
-   `_apply_resolved_value(self, config: IntegratedConfiguration, conflict: ConfigurationConflict)`: Applies the resolved value to the target configuration object.
-   `_generate_conflict_id()`: Generates unique ID for conflicts.
-   `log_configuration_decisions(self, conflicts: List[ConfigurationConflict], log_level: str = "INFO")`: Logs resolution details.
-   `get_conflict_summary(self, conflicts: List[ConfigurationConflict]) -> Dict[str, Any]`: Provides conflict statistics.

**Priority Order (Highest to Lowest)**:
1.  Case-specific configuration
2.  Wing-specific configuration
3.  Pipeline-specific configuration
4.  Global configuration

**Dependencies**: `logging`, `typing`, `dataclasses`, `enum`, `integrated_configuration_manager`.

**Dependents**: `integrated_configuration_manager` (for merging global/case config), pipeline execution.

**Impact**: CRITICAL - Ensures consistent and predictable behavior when multiple configuration sources are involved.

---

### configuration_migration.py

**Purpose**: This module provides `ConfigurationMigration` utilities for safely migrating existing configurations (like `integrated_config.json` and wing JSON files) to newer formats when the schema or structure evolves. It handles specific migration steps, checks if migration is needed, creates backups, and can perform migration on application startup.

**Key Classes**:
1.  **`ConfigurationMigration` (static utility class)**: Contains static methods for migration tasks.

**Key Methods**:
-   `migrate_integrated_config(config_path: Path) -> bool`: Migrates `integrated_config.json` (e.g., adds default weights from artifact registry).
-   `migrate_wing_config(wing_config_path: Path) -> bool`: Migrates wing JSON files (e.g., adds `anchor_priority` from artifact registry).
-   `migrate_all_configurations(config_directory: Path) -> Dict[str, Any]`: Iterates and migrates all relevant files in a directory.
-   `check_migration_needed(config_path: Path) -> bool`: Checks if a file needs migration based on version markers or content.
-   **`migrate_on_startup(config_directory: str = "configs") -> bool`**: Main function to run migration checks and execution on startup.

**Migration Logic**:
-   For `integrated_config.json`: Adds missing `default_weights` to `weighted_scoring` from `artifact_type_registry`.
-   For wing JSONs: Adds missing `anchor_priority` to `wing_data` from `artifact_type_registry`.
-   Adds `migration_history` to config files to track versions.

**Dependencies**: `json`, `logging`, `pathlib`, `typing`, `datetime`, `artifact_type_registry` (for migration logic).

**Dependents**: Application startup process (via `migrate_on_startup`).

**Impact**: HIGH - Ensures backward compatibility and smooth transitions during software updates.

---

### score_config_migration_tool.py

**Purpose**: This module provides a `ScoreConfigMigrationTool` to assist in the process of centralizing score definitions. It can scan the codebase for scattered, hard-coded score values (thresholds, tier weights), extract them, consolidate them into a new `CentralizedScoreConfig` object, and save this to a `score_config.json` file. It includes features for generating a migration report, creating backups, and validating the migration outcome, along with rollback capabilities.

**Key Classes**:
1.  **`ScoreDefinitionLocation` (dataclass)**: Location details of a found score definition.
2.  **`MigrationReport` (dataclass)**: Summarizes migration operations.
3.  **`ScoreConfigMigrationTool`**: The core tool for performing score config migration.

**Key Methods**:
-   `__init__(self, root_path: str = "Crow-Eye")`: Initializes with root path and exclusion patterns.
-   `scan_for_old_definitions() -> List[ScoreDefinitionLocation]`: Scans Python/JSON files using regex for old score definitions.
-   `_scan_file(self, file_path: Path) -> List[ScoreDefinitionLocation]`: Scans a single file.
-   `extract_score_values(self, definitions: List[ScoreDefinitionLocation]) -> CentralizedScoreConfig`: Consolidates found values into a `CentralizedScoreConfig`.
-   `create_centralized_config_file(self, config: CentralizedScoreConfig, output_path: str) -> str`: Saves the consolidated config to `score_config.json`.
-   `create_backup() -> str`: Creates a backup of modified files.
-   `validate_migration() -> Tuple[bool, List[str]]`: Checks if migration was successful (config created, old definitions removed).
-   `_count_manager_usage() -> int`: Counts files using `ScoreConfigurationManager`.
-   `rollback_migration() -> bool`: Restores files from backup.
-   `run_migration(...) -> MigrationReport`: Orchestrates the complete migration process.
-   `generate_migration_summary() -> str`: Creates a human-readable summary report.

**Scanning Mechanism**: Uses regex patterns (e.g., `r"'low'\s*:\s*(0\.\d+)"`) to identify score thresholds and tier weights in code.

**Dependencies**: `ast` (though not directly used in the snippet for scanning, typically for Python code analysis), `json`, `logging`, `re`, `shutil`, `dataclasses`, `datetime`, `pathlib`, `typing`, `centralized_score_config`, `score_configuration_manager`.

**Dependents**: Developer-invoked for migration tasks.

**Impact**: HIGH - Facilitates the transition from scattered, hard-coded score definitions to a centralized, manageable system.

---

### feather_config.py

**Purpose**: This module defines the `FeatherConfig` dataclass, which serves as a data model for storing metadata about how a "feather" (a standardized SQLite database containing forensic artifact data) was created from raw source data. It encapsulates all necessary information for identifying, sourcing, mapping, transforming, and managing a feather.

**Key Classes**:
1.  **`FeatherConfig` (dataclass)**: Stores feather creation and metadata details.

**Key Fields**:
-   **Identification**: `config_name`, `feather_name`, `artifact_type`.
-   **Source Information**: `source_database`, `source_table`.
-   **Column Mapping**: `selected_columns`, `column_mapping` (original to feather column).
-   **Transformation Settings**: `timestamp_column`, `timestamp_format`.
-   **Output**: `output_database`.
-   **Optional Fields**: `application_column`, `path_column`.
-   **Metadata**: `created_date`, `created_by`, `description`, `notes`.
-   **Statistics**: `total_records`, `date_range_start`, `date_range_end`.

**Key Methods**:
-   `to_dict()`: Converts to dictionary for serialization.
-   `to_json(indent: int = 2)`: Converts to JSON string.
-   `save_to_file(file_path: str)`: Saves config to a JSON file.
-   `from_dict(data: dict) -> FeatherConfig`: Creates from dictionary.
-   `from_json(json_str: str) -> FeatherConfig`: Creates from JSON string.
-   `load_from_file(file_path: str) -> FeatherConfig`: Loads config from a JSON file.

**Dependencies**: `json`, `dataclasses`, `datetime`, `typing`.

**Dependents**: `config_manager`, `pipeline_config`, feather creation tools (e.g., `feather_builder` in `feather/`).

**Impact**: MEDIUM - Defines the structure for feather configurations, central to data ingestion.

---

### wing_config.py

**Purpose**: This module defines the `WingConfig` dataclass, which serves as a data model for storing the configuration of a "wing" (a correlation rule). It comprehensively details the rule, including identification, descriptive metadata, specific feathers to be used (via `WingFeatherReference`), correlation parameters (e.g., `time_window_minutes`, `minimum_matches`), filtering options, anchor priority, weighted scoring settings, and wing-specific semantic rules. It includes robust deserialization logic for backward compatibility and integrates with `ScoreConfigurationManager` for centralized scoring parameters.

**Key Classes**:
1.  **`WingFeatherReference` (dataclass)**: Defines a feather's role within a wing (path, type, weight, tier).
2.  **`WingConfig` (dataclass)**: The main wing configuration data model.

**Key Fields (of `WingConfig`):**
-   **Identification**: `config_name`, `wing_name`, `wing_id`.
-   **Wing Definition**: `description`, `proves`, `author`.
-   **Feathers Used**: `feathers` (List of `WingFeatherReference`).
-   **Correlation Rules**: `time_window_minutes`, `minimum_matches`.
-   **Filters**: `target_application`, `target_file_path`, `target_event_id`, `apply_to`.
-   **Anchor Priority**: `anchor_priority` (List[str], auto-populated from `artifact_type_registry`).
-   **Weighted Scoring**: `use_weighted_scoring`, `scoring` (legacy dictionary for direct JSON compatibility).
-   **Wing-Specific Semantic Rules**: `semantic_rules` (List[Dict]).
-   **Metadata**: `created_date`, `last_modified`, `version`, `tags`, `case_types`.

**Key Methods**:
-   `__post_init__()`: Initializes `ScoreConfigurationManager` instance.
-   `get_score_thresholds() -> Dict[str, float]`: Retrieves thresholds from `ScoreConfigurationManager`.
-   `get_tier_weights() -> Dict[str, float]`: Retrieves tier weights from `ScoreConfigurationManager`.
-   `to_dict()`, `to_json(indent: int = 2)`: Serialization methods.
-   `save_to_file(file_path: str)`: Saves config to JSON.
-   `from_dict(data: dict) -> WingConfig`: Deserializes with extensive backward compatibility and migration logic.
-   `load_from_file(file_path: str) -> WingConfig`: Loads config from JSON.

**Dependencies**: `json`, `dataclasses`, `datetime`, `typing`, `score_configuration_manager`, `artifact_type_registry`.

**Dependents**: `config_manager`, `pipeline_config`, correlation engine execution.

**Impact**: CRITICAL - Defines the core correlation rules and their associated parameters.

---

### pipeline_config.py

**Purpose**: This module defines the `PipelineConfig` dataclass, which acts as a comprehensive, end-to-end configuration for an entire analysis workflow. It orchestrates multiple feather preparations, wing executions, and reporting. It consolidates identification, case information, references to `FeatherConfig`s and `WingConfig`s, execution settings (including engine selection and filters), semantic mapping/scoring settings, debug flags, output options, and general metadata.

**Key Classes**:
1.  **`PipelineConfig` (dataclass)**: Stores the complete pipeline definition.

**Key Fields**:
-   **Identification**: `config_name`, `pipeline_name`, `description`.
-   **Case Information**: `case_name`, `case_id`, `investigator`.
-   **Feather/Wing References**: `feather_configs` (List[FeatherConfig]), `wing_configs` (List[WingConfig]).
-   **Execution Settings**: `auto_create_feathers`, `auto_run_correlation`.
-   **Engine Selection & Filters**: `engine_type`, `time_period_start`, `time_period_end`, `identity_filters`, `identity_filter_case_sensitive`.
-   **Semantic Mapping/Scoring**: `semantic_mapping_config` (Dict), `weighted_scoring_config` (Dict - legacy), `identity_semantic_phase_enabled`, `semantic_rules` (List[Dict]), `scoring_config` (Dict - pipeline-level).
-   **Debug/Logging**: `debug_mode`, `verbose_logging`.
-   **Output Settings**: `output_directory`, `generate_report`, `report_format`.
-   **Metadata**: `created_date`, `last_modified`, `last_executed`, `version`, `tags`, `notes`.

**Key Methods**:
-   `to_dict()`, `to_json(indent: int = 2)`: Serialization methods.
-   `save_to_file(file_path: str)`: Saves config to JSON.
-   `from_dict(data: dict) -> PipelineConfig`: Deserializes with extensive backward compatibility for new fields.
-   `load_from_file(file_path: str) -> PipelineConfig`: Loads config from JSON.
-   `add_feather_config(self, feather_config: FeatherConfig)`, `add_wing_config(self, wing_config: WingConfig)`: Helpers for adding sub-configs.
-   `get_feather_config(self, config_name: str)`, `get_wing_config(self, config_name: str)`: Helpers for retrieving sub-configs.

**Dependencies**: `json`, `dataclasses`, `datetime`, `typing`, `FeatherConfig`, `WingConfig`.

**Dependents**: `config_manager`, `pipeline_config_manager`, `pipeline_executor` (in `pipeline/`).

**Impact**: CRITICAL - Defines the blueprint for full analysis workflows.

---

### session_state.py

**Purpose**: This module defines a suite of dataclasses that serve as data models for managing various states and metadata within the Pipeline Configuration Manager and the broader correlation engine. These structures are crucial for session persistence, configuration discovery, pipeline loading status, validation results, and bundling a loaded pipeline with all its dependencies. It also includes the `SessionStateManager` for managing the `SessionState` persistence to file.

**Key Classes**:
1.  **`SessionState` (dataclass)**: Persistent GUI session state (last pipeline, window geometry, preferences).
2.  **`PipelineMetadata` (dataclass)**: Metadata for a discovered pipeline (for UI display).
3.  **`FeatherMetadata` (dataclass)**: Metadata for a discovered feather.
4.  **`WingsMetadata` (dataclass)**: Metadata for a discovered wing.
5.  **`DiscoveryResult` (dataclass)**: Aggregates all discovered pipeline, feather, and wing metadata.
6.  **`ConnectionStatus` (dataclass)**: Status of a feather database connection.
7.  **`ValidationResult` (dataclass)**: General results of configuration validation (used by various validators).
8.  **`PartialLoadInfo` (dataclass)**: Details of components that failed to load during a pipeline load.
9.  **`LoadStatus` (dataclass)**: Overall status of a pipeline load operation (complete, partial, errors).
10. **`PipelineBundle` (dataclass)**: A complete, loaded pipeline with all its `PipelineConfig`, `FeatherConfig`s, `WingConfig`s, database connections, and load status. This is the main return type when a pipeline is successfully loaded.
11. **`InitializationResult` (dataclass)**: Result of the `PipelineConfigurationManager`'s startup initialization.
12. **`ErrorResponse` (dataclass)**: Standardized structure for error messages with severity and recovery actions.
13. **`SessionStateManager`**: Manages the loading, saving, and updating of the `SessionState` object to `session.json` within a case directory.

**Key Methods (of `SessionStateManager`):**
-   `__init__(self, case_directory: Path)`: Initializes with the case's correlation directory.
-   `load_session() -> Optional[SessionState]`: Loads session from `session.json`.
-   `save_session(self, state: SessionState)`: Saves session to file.
-   `set_last_pipeline(self, pipeline_path: str, pipeline_name: str = "")`: Updates last pipeline in session.
-   `clear_session()`: Deletes session file.
-   `update_preferences(self, preferences: Dict[str, Any])`, `update_window_geometry(self, geometry: Dict[str, int])`, `update_active_tab(self, tab_index: int)`: Updates specific session preferences.
-   `_backup_corrupted_session()`: Creates a backup if `session.json` is corrupted.

**Dependencies**: `json`, `dataclasses`, `datetime`, `typing`, `pathlib`, `PipelineConfig`, `FeatherConfig`, `WingConfig`.

**Dependents**: `pipeline_config_manager`, GUI components for managing session and displaying metadata.

**Impact**: HIGH - Provides crucial data structures and persistence for managing the state and operational flow of the correlation engine.

---

### identifier_extraction_config.py

**Purpose**: This module defines dataclasses for configuring how identifiers are extracted from forensic artifacts and how timestamps are parsed. These configurations are central to the correlation process, especially for the Identity-Based Correlation Engine, as they dictate how data is normalized and matched. The configurations are bundled into a `WingsConfig` object, which acts as a set of operational parameters for the correlation engine. This `WingsConfig` is distinct from the `WingConfig` (defined in `wing_config.py`), which defines a correlation rule.

**Key Classes**:
1.  **`IdentifierExtractionConfig` (dataclass)**: Configures rules for extracting identifiers (e.g., from file names, paths).
2.  **`TimestampParsingConfig` (dataclass)**: Configures custom timestamp formats, default timezone, and fallback options.
3.  **`WingsConfig` (dataclass)**: Aggregates identifier extraction, anchor time window, timestamp parsing, and correlation database name into a single configuration object for engine operation.

**Key Fields (of `WingsConfig`):**
-   `identifier_extraction` (`IdentifierExtractionConfig`): Settings for identifier extraction.
-   `anchor_time_window_minutes` (int): Time window for grouping temporal anchors.
-   `timestamp_parsing` (`TimestampParsingConfig`): Settings for timestamp interpretation.
-   `correlation_database` (str): Name of the database for correlation results.

**Key Methods (of `WingsConfig`):**
-   `from_dict(data: Dict[str, Any]) -> WingsConfig`: Creates from dictionary.
-   `load_from_file(config_path: str) -> WingsConfig`: Loads from JSON file.
-   `to_dict() -> Dict[str, Any]`: Converts to dictionary.
-   `save_to_file(config_path: str)`: Saves to JSON file.
-   `get_extraction_strategy() -> Dict[str, bool]`: Returns extraction strategy as a dict.

**Dependencies**: `json`, `dataclasses`, `typing`, `pathlib`.

**Dependents**: Correlation engine implementations (e.g., `identity_correlation_engine.py`), `pipeline_config` (might reference/contain this config).

**Impact**: MEDIUM - Directly influences how identifiers are processed and how timestamps are interpreted by the correlation engines.

---

### pipeline_config_manager.py

**Purpose**: This module implements `PipelineConfigurationManager`, the central coordinator for all pipeline configuration operations. It provides a unified API for the GUI and orchestrates the complete lifecycle of pipelines by composing and utilizing several specialized sub-managers and services. Its responsibilities include initialization, loading, switching, creation, and refreshing of pipelines, as well as managing session state, configuration discovery, and auto-registration of feathers.

**Key Classes**:
1.  **`PipelineConfigurationManager`**: The central coordinator for pipeline lifecycle management.

**Key Methods**:
-   `__init__(self, case_directory: Path)`: Initializes with a case's correlation directory and sets up sub-managers.
-   `initialize() -> InitializationResult`: Loads session, discovers configs, auto-loads last pipeline.
-   `load_pipeline(self, pipeline_path: str) -> PipelineBundle`: Loads a specific pipeline.
-   `switch_pipeline(self, new_pipeline_path: str) -> PipelineBundle`: Switches to another pipeline.
-   `get_available_pipelines() -> List[PipelineMetadata]`: Returns a list of discovered pipelines.
-   `get_current_pipeline() -> Optional[PipelineBundle]`: Returns the currently loaded pipeline.
-   `create_pipeline(self, pipeline_config: PipelineConfig) -> str`: Creates and saves a new pipeline config file.
-   `auto_register_feather(self, database_path: str, artifact_type: str, ...) -> FeatherConfig`: Registers a new feather.
-   `refresh_configurations()`: Re-scans for available configurations.
-   `get_discovery_result() -> Optional[DiscoveryResult]`: Returns the latest discovery results.
-   `get_session_state() -> Optional[SessionState]`: Returns current session state.
-   `update_session_preferences(...)`, `update_window_geometry(...)`, `update_active_tab(...)`: Delegates to `SessionStateManager` for updates.
-   `get_feather_configs() -> List[FeatherConfig]`: Returns registered feather configs.
-   `validate_database(self, database_path: str) -> tuple[bool, Optional[str]]`: Validates a feather database.

**Composed Sub-Managers/Services**:
-   `SessionStateManager` (from `session_state.py`)
-   `ConfigurationDiscoveryService` (from `../pipeline/discovery_service.py`)
-   `PipelineLoader` (from `../pipeline/pipeline_loader.py`)
-   `FeatherAutoRegistrationService` (from `../pipeline/feather_auto_registration.py`)

**Dependencies**: `pathlib`, `typing`, and various dataclasses and managers from `session_state`, `pipeline_config`, `feather_config`, and the `../pipeline` modules.

**Dependents**: GUI components that interact with pipeline management.

**Impact**: CRITICAL - Central orchestration point for the entire pipeline management system.

---

### case_configuration_file_manager.py

**Purpose**: This module provides `CaseConfigurationFileManager`, a robust manager for low-level file operations concerning case-specific configurations. It handles the physical storage, retrieval, validation, repair, compression, archiving, and cleanup of case configuration files (semantic mappings, scoring weights, metadata) within dedicated `cases/{case_id}/` directories. It also manages configuration templates.

**Key Classes**:
1.  **`ConfigurationFileInfo` (dataclass)**: Metadata about a config file.
2.  **`ConfigurationTemplate` (dataclass)**: Defines a template for new config files.
3.  **`CaseConfigurationFileManager`**: Manages low-level case config file operations.

**Key Methods**:
-   `__init__(self, cases_directory: str = "cases")`: Initializes with a root directory for case configs.
-   `_load_templates()`, `_create_default_templates()`, `_save_templates()`: Manages configuration templates.
-   `get_file_info(self, file_path: Path, case_id: str, file_type: str) -> ConfigurationFileInfo`: Retrieves file metadata and validity.
-   `_calculate_file_checksum(self, file_path: Path) -> str`: Calculates SHA-256 checksum.
-   `validate_configuration_file(self, file_path: Path, file_type: str) -> Dict[str, Any]`: Validates JSON structure and content for specific types.
-   `_validate_semantic_mappings_file(...)`, `_validate_scoring_weights_file(...)`, `_validate_metadata_file(...)`: Type-specific validation.
-   `repair_configuration_file(self, file_path: Path, file_type: str) -> bool`: Attempts to fix corrupted JSON files.
-   `_fix_json_content(self, content: str)`, `_repair_semantic_mappings_data(...)`, etc.: Helper methods for repair.
-   `create_from_template(self, template_name: str, case_id: str, case_name: str = "") -> Dict[str, Any]`: Creates config data from a template.
-   `compress_configuration_file(self, file_path: Path) -> bool`, `decompress_configuration_file(self, compressed_path: Path) -> bool`: Handles file compression.
-   `archive_old_configurations(self, days_old: int = 30) -> int`: Moves old files to an archive and compresses.
-   `cleanup_empty_case_directories() -> int`: Removes empty case directories.
-   `get_configuration_statistics() -> Dict[str, Any]`: Provides statistics on config files.

**Case Directory Structure**: Manages files within `cases/{case_id}/`, `templates/`, and `archive/`.

**Dependencies**: `json`, `logging`, `gzip`, `shutil`, `pathlib`, `typing`, `dataclasses`, `datetime`, `timedelta`, `hashlib`, `tempfile`.

**Dependents**: `case_configuration_manager`.

**Impact**: HIGH - Provides robust, low-level file management and integrity features for case configurations.

---

### case_configuration_manager.py

**Purpose**: This module provides `CaseConfigurationManager`, a high-level manager that orchestrates comprehensive case configuration management. It offers features for automatic case switching, comparing configurations between cases, copying/merging configurations, and exporting/importing entire case configurations (including semantic mappings, scoring weights, and metadata). It also implements a change tracking mechanism (observer pattern) to notify listeners of configuration modifications.

**Key Classes**:
1.  **`CaseConfigurationComparison` (dataclass)**: Result of comparing two case configs.
2.  **`ConfigurationExportResult` (dataclass)**: Result of an export operation.
3.  **`ConfigurationChangeEvent` (dataclass)**: Event object for tracking config changes (distinct from `configuration_change_handler.py`'s event).
4.  **`CaseConfigurationManager`**: The core high-level case config manager.

**Key Methods**:
-   `__init__(self, cases_directory: str = "cases")`: Initializes sub-managers and change tracking.
-   `add_change_listener(self, listener: Callable[[ConfigurationChangeEvent], None])`, `_notify_change_listeners(...)`: Observer pattern for case config changes.
-   `switch_to_case(self, case_id: str, auto_create: bool = True) -> bool`: Switches active case, loads its configs.
-   `get_current_case_id() -> Optional[str]`: Returns current case ID.
-   `compare_case_configurations(self, source_case_id: str, target_case_id: str, use_cache: bool = True) -> CaseConfigurationComparison`: Compares configurations between two cases.
-   `_compare_semantic_mappings(...)`, `_compare_scoring_weights(...)`, `_compare_metadata(...)`: Helper methods for comparison.
-   `_generate_comparison_recommendations(...)`, `_check_merge_compatibility(...)`: Generate recommendations and check merge conflicts.
-   `copy_case_configuration(self, source_case_id: str, target_case_id: str, components: Optional[List[str]] = None, merge_strategy: str = 'replace') -> bool`: Copies configs between cases.
-   `_copy_semantic_mappings(...)`, `_copy_scoring_weights(...)`, `_copy_metadata(...)`: Helper methods for copying.
-   `export_case_configuration_with_results(...)`, `import_case_configuration_with_results(...)`: Handles import/export of full case configs.
-   `get_configuration_change_history(...)`: Retrieves history of config changes.
-   `clear_comparison_cache()`: Clears comparison results cache.
-   `get_configuration_statistics() -> Dict[str, Any]`: Provides comprehensive stats (file, case summary, change history).
-   `perform_maintenance() -> Dict[str, Any]`: Orchestrates maintenance operations (file cleanup, validation).

**Composes Sub-Managers**:
-   `CaseSpecificConfigurationManager` (from `case_specific_configuration_manager.py`)
-   `CaseConfigurationFileManager` (from `case_configuration_file_manager.py`)
-   `CaseSpecificConfigurationIntegration` (from `../integration/case_specific_configuration_integration.py`)

**Dependencies**: `logging`, `json`, `pathlib`, `typing`, `dataclasses`, `datetime`, `shutil`.

**Dependents**: UI for case management, core application logic that interacts with case settings.

**Impact**: CRITICAL - Provides the highest-level management for forensic case configurations, enabling complex operations.

---

### case_specific_configuration_manager.py

**Purpose**: This module provides `CaseSpecificConfigurationManager`, a manager dedicated to handling configuration settings that are specific to individual forensic cases. It allows for case-specific semantic mappings, scoring weights, and metadata to be loaded, saved, and managed, effectively enabling overrides or extensions to global configurations on a per-case basis. It uses caching for performance and includes methods for creating default case configurations.

**Key Classes**:
1.  **`CaseSemanticMappingConfig` (dataclass)**: Data model for case-specific semantic mappings.
2.  **`CaseScoringWeightsConfig` (dataclass)**: Data model for case-specific scoring weights.
3.  **`CaseConfigurationMetadata` (dataclass)**: Metadata for a case's configuration (name, description, tags, status flags).
4.  **`CaseSpecificConfigurationManager`**: Manages case-specific configurations.

**Key Methods**:
-   `__init__(self, cases_directory: str = "cases")`: Initializes with the root cases directory.
-   `create_case_directory(self, case_id: str) -> Path`: Creates the directory structure for a new case.
-   `get_case_directory(self, case_id: str) -> Path`: Returns path to a case directory.
-   `case_exists(self, case_id: str) -> bool`: Checks if a case exists.
-   `list_cases() -> List[str]`: Lists all available case IDs.
-   `get_case_metadata(self, case_id: str) -> Optional[CaseConfigurationMetadata]`: Loads metadata for a case.
-   `save_case_metadata(self, metadata: CaseConfigurationMetadata) -> bool`: Saves case metadata.
-   `has_semantic_mappings(self, case_id: str) -> bool`, `load_case_semantic_mappings(self, case_id: str) -> Optional[CaseSemanticMappingConfig]`, `save_case_semantic_mappings(...)`, `create_default_semantic_mappings(...)`: Manages case-specific semantic mappings.
-   `has_scoring_weights(self, case_id: str) -> bool`, `load_case_scoring_weights(self, case_id: str) -> Optional[CaseScoringWeightsConfig]`, `save_case_scoring_weights(...)`, `create_default_scoring_weights(...)`: Manages case-specific scoring weights.
-   `delete_case_configuration(self, case_id: str, backup: bool = True) -> bool`: Deletes a case's configuration.
-   `copy_case_configuration(self, source_case_id: str, target_case_id: str, ...)`: Copies configs between cases.
-   `backup_case_configuration(self, case_id: str) -> bool`: Creates a backup of a case's configs.
-   `export_case_configuration(self, case_id: str, export_path: str) -> bool`, `import_case_configuration(self, import_path: str, target_case_id: Optional[str] = None) -> bool`: Handles export/import.
-   `validate_case_configuration(self, case_id: str) -> Dict[str, Any]`: Validates a case's configuration files.
-   `clear_cache(self, case_id: Optional[str] = None)`: Clears internal caches.
-   `get_configuration_summary() -> Dict[str, Any]`: Provides a summary of all case configurations.

**Dependencies**: `json`, `logging`, `pathlib`, `typing`, `dataclasses`, `datetime`, `shutil`, `semantic_mapping`, `integrated_configuration_manager`.

**Dependents**: `case_configuration_manager`, `integrated_configuration_manager`.

**Impact**: HIGH - Provides granular control and management of configuration settings on a per-forensic case basis.

---

### default_mappings/ Subdirectory

**Purpose**: This subdirectory contains default semantic mapping definitions for various common forensic artifact types. These mappings are stored in YAML, JSON, or Python file formats and provide initial, standardized field translations (e.g., mapping "EventID" to "Event ID") that can be loaded by `SemanticMappingDiscovery` and `SemanticMappingManager`. They serve as a base that can be overridden or extended by global, pipeline-specific, or wing-specific semantic rules.

**Files**:
-   `browser_history.yaml`
-   `event_logs.yaml`
-   `file_system.yaml`
-   `prefetch.yaml`
-   `registry.yaml`
-   ... (and other YAML, JSON, or Python files defining mappings)

**Structure**: Typically contain a list of `SemanticMapping` objects or a dictionary of mappings, depending on the file format (as parsed by `semantic_mapping_discovery.py`).

**Dependencies**: Consumed by `semantic_mapping_discovery.py` and `semantic_mapping.py`.

**Impact**: MEDIUM - Provides sensible default semantic mappings, reducing manual configuration effort.

---

## Common Modification Scenarios

This section outlines common tasks and where modifications would typically occur within the `config` directory.

### Scenario 1: Adding a New Global Configuration Setting

**Problem**: Introduce a new system-wide setting (e.g., a new engine parameter, a global filter threshold) that needs to be persisted and optionally overridden per case.

**Files to Modify**:
1.  **`integrated_configuration_manager.py`**:
    *   Add the new field to the relevant configuration dataclass (`SemanticMappingConfig`, `WeightedScoringConfig`, `ProgressTrackingConfig`, `EngineSelectionConfig`) or create a new dataclass if it's a new category.
    *   Update `IntegratedConfiguration` to include this new dataclass/field.
    *   Update `_parse_configuration_data()` to correctly parse/default the new setting.
    *   Update `_detect_changed_sections()` in `configuration_change_handler.py` (if applicable) and relevant validation/conflict detection logic.
2.  **JSON Schema (if any)**: Update the JSON schema for `integrated_config.json` if formal schema validation is used elsewhere.
3.  **GUI (in `gui/`)**: Add UI controls to manage this new setting.

**Impact**: HIGH - Affects global behavior, persistence, and potential case-specific overrides.

---

### Scenario 2: Defining a New Artifact Type or Modifying Existing Artifact Metadata

**Problem**: Add support for a new forensic artifact (e.g., "BrowserCache") or change properties of an existing one (e.g., default weight of "Prefetch").

**Files to Modify**:
1.  **`artifact_types.json`**: Add a new entry for the artifact or modify existing properties. This is the primary source.
2.  **`artifact_type_registry.py`**: (Rarely needed unless changing core logic, but ensures `ArtifactType` dataclass matches JSON fields).
3.  **`centralized_score_config.py`**: Update `default_weights` in `CentralizedScoreConfig` (if not pulled from registry automatically).
4.  **`integrated_configuration_manager.py`**: Update `_get_default_weights_from_registry()` fallback if needed.
5.  **`score_config_migration_tool.py`**: Update `extract_score_values()` if this new artifact type might be found hard-coded in old files.

**Impact**: MEDIUM - Affects how artifacts are recognized and scored throughout the system.

---

### Scenario 3: Implementing a New Semantic Rule or Default Semantic Mapping

**Problem**: Add a new rule to detect specific forensic events (e.g., "Malware Execution Pattern") or a new basic mapping (e.g., "EventID 4624" → "User Login").

**Files to Modify**:
1.  **`semantic_mapping.py`**:
    *   If a new rule, ensure `SemanticRule` and `SemanticCondition` can represent it.
    *   Add the new rule/mapping to the `_load_default_rules()` or `_load_default_mappings()` methods in `SemanticMappingManager` (for built-in rules).
2.  **`default_mappings/` Subdirectory**: Create a new YAML/JSON/Python file, or modify an existing one, to define the new mapping/rule.
3.  **`semantic_rule_validator.py`**: Update validation logic if the new rule/mapping introduces new syntax or requirements.

**Impact**: HIGH - Directly influences the interpretation of correlation results.

---

### Scenario 4: Creating a New Case-Specific Override Configuration

**Problem**: Introduce a new type of configuration that can be customized on a per-case basis (e.g., case-specific identity normalization rules).

**Files to Modify**:
1.  **`case_specific_configuration_manager.py`**:
    *   Create a new dataclass (e.g., `CaseIdentityNormalizationConfig`) for the new configuration type.
    *   Add `has_`, `load_`, `save_`, `create_default_` methods for this new config type.
    *   Update `CaseConfigurationMetadata` to track its existence.
2.  **`case_configuration_file_manager.py`**:
    *   Define a new `config_file` entry (e.g., `self.config_files['identity_normalization'] = 'identity_normalization.json'`).
    *   Implement `_validate_identity_normalization_file()` and `_repair_identity_normalization_data()`.
3.  **`case_configuration_manager.py`**:
    *   Update `compare_case_configurations()`, `copy_case_configuration()`, `export_case_configuration_with_results()`, `import_case_configuration_with_results()` to handle the new config type.
4.  **`integrated_configuration_manager.py`**:
    *   Add a field to `CaseSpecificConfig` (e.g., `identity_normalization_path: Optional[str]`).
    *   Update `_update_effective_configuration()` to merge/load the new config type.

**Impact**: HIGH - Adds new dimensions of customizability per case, requiring changes across multiple manager components.

---

### Scenario 5: Refactoring or Migrating Old Hard-Coded Score Definitions

**Problem**: Remove hard-coded scoring parameters from various Python files and centralize them into `score_config.json`.

**Files to Use/Modify**:
1.  **`score_config_migration_tool.py`**: Run this tool to scan the codebase, extract values, and create `score_config.json`.
2.  **Codebase files**: Manually update the Python files identified by the migration tool to replace hard-coded values with references to `ScoreConfigurationManager`.

**Impact**: HIGH - Essential for maintaining a single source of truth for scoring parameters.

---

## Configuration File Formats

This section provides examples of the key JSON configuration file formats used within this directory.

### artifact_types.json (Managed by `artifact_type_registry.py`)
```json
{
  "version": "1.0",
  "description": "Centralized artifact type definitions for Crow-Eye Correlation Engine",
  "artifact_types": [
    {
      "id": "Logs",
      "name": "Event Logs",
      "description": "Windows Event Logs (Security, System, Application)",
      "default_weight": 0.4,
      "default_tier": 1,
      "anchor_priority": 1,
      "category": "primary_evidence",
      "forensic_strength": "high"
    },
    {
      "id": "Prefetch",
      "name": "Prefetch Files",
      "description": "Windows Prefetch execution artifacts",
      "default_weight": 0.3,
      "default_tier": 1,
      "anchor_priority": 2,
      "category": "primary_evidence",
      "forensic_strength": "high"
    }
  ]
}
```

### integrated_config.json (Managed by `integrated_configuration_manager.py`)
```json
{
  "semantic_mapping": {
    "enabled": true,
    "global_mappings_path": "config/semantic_mappings.json",
    "case_specific": { "enabled": true, "storage_path": "cases/{case_id}/semantic_mappings.json" }
  },
  "weighted_scoring": {
    "enabled": true,
    "score_interpretation": { ... },
    "default_weights": { "Logs": 0.4, "Prefetch": 0.3, ... },
    "validation_rules": { ... },
    "case_specific": { "enabled": true, "storage_path": "cases/{case_id}/scoring_weights.json" }
  },
  "progress_tracking": { "enabled": true, "update_frequency_ms": 500 },
  "engine_selection": { "default_engine": "identity_based" },
  "case_specific": null,
  "version": "1.0",
  "created_date": "2024-02-14T10:00:00Z",
  "last_modified": "2024-02-14T10:00:00Z"
}
```

### score_config.json (Managed by `score_configuration_manager.py`)
```json
{
  "thresholds": {
    "low": 0.3,
    "medium": 0.5,
    "high": 0.7,
    "critical": 0.9
  },
  "tier_weights": {
    "tier1": 1.0,
    "tier2": 0.8,
    "tier3": 0.6,
    "tier4": 0.4
  },
  "penalties": {
    "missing_primary": 0.2
  },
  "bonuses": {
    "exact_time_match": 0.1
  },
  "version": "1.0",
  "last_updated": "2024-02-14T10:00:00Z"
}
```

### Feather Config (Example - Defined in `feather_config.py`)
```json
{
  "config_name": "prefetch_analysis",
  "feather_name": "Prefetch Data (Case 1)",
  "artifact_type": "Prefetch",
  "source_database": "C:/cases/case_1/raw/prefetch.db",
  "output_database": "C:/cases/case_1/correlation/feathers/prefetch_v1.db",
  "column_mappings": { ... },
  "transformations": [ ... ],
  "created_date": "2024-02-14T10:00:00Z"
}
```

### Wing Config (Example - Defined in `wing_config.py`)
```json
{
  "wing_id": "execution_proof_wing",
  "wing_name": "Execution Proof Wing",
  "description": "Correlates Prefetch and ShimCache...",
  "feathers": [ ... ],
  "correlation_rules": {
    "time_window_minutes": 10,
    "minimum_matches": 2
  },
  "anchor_priority": ["Prefetch", "ShimCache", "SRUM"],
  "use_weighted_scoring": true,
  "semantic_rules": [ ... ],
  "created_date": "2024-02-14T11:00:00Z"
}
```

### Pipeline Config (Example - Defined in `pipeline_config.py`)
```json
{
  "pipeline_name": "Full Case Analysis Pipeline",
  "description": "A complete pipeline for analyzing all execution-related artifacts...",
  "case_name": "Case 2024-001",
  "engine_type": "identity_based",
  "feather_configs": [ ... ],
  "wing_configs": [ ... ],
  "time_period_start": "2024-01-01T00:00:00",
  "identity_filters": ["chrome.exe"],
  "scoring_config": { ... },
  "debug_mode": true,
  "output_directory": "reports/full_analysis",
  "generate_report": true,
  "created_date": "2024-02-14T12:00:00Z"
}
```

### Case-Specific Semantic Mappings (e.g., `cases/{case_id}/semantic_mappings.json`)
```json
{
  "case_id": "case_alpha",
  "enabled": true,
  "mappings": [
    {
      "source": "SecurityLogs",
      "field": "EventID",
      "technical_value": "4624",
      "semantic_value": "Custom User Login"
    }
  ],
  "inherit_global": true,
  "override_global": false,
  "version": "1.0",
  "last_modified": "2024-02-14T13:00:00Z"
}
```

### Case-Specific Scoring Weights (e.g., `cases/{case_id}/scoring_weights.json`)
```json
{
  "case_id": "case_alpha",
  "enabled": true,
  "default_weights": {
    "Logs": 0.5,
    "Prefetch": 0.2
  },
  "score_interpretation": { ... },
  "inherit_global": true,
  "override_global": false,
  "version": "1.0",
  "last_modified": "2024-02-14T13:00:00Z"
}
```

### Case Metadata (e.g., `cases/{case_id}/case_metadata.json`)
```json
{
  "case_id": "case_alpha",
  "case_name": "My Alpha Investigation",
  "description": "Initial analysis of a suspicious workstation.",
  "created_date": "2024-02-10T09:00:00Z",
  "last_modified": "2024-02-14T14:00:00Z",
  "tags": ["malware", "insider-threat"],
  "has_semantic_mappings": true,
  "has_scoring_weights": true,
  "version": "1.0"
}
```

---

## See Also
- [Main Correlation Engine Overview](../CORRELATION_ENGINE_OVERVIEW.md)
- [Wings Documentation](../wings/WINGS_DOCUMENTATION.md)
- [Pipeline Documentation](../pipeline/PIPELINE_DOCUMENTATION.md)
- [Artifact Type Registry Guide](ARTIFACT_TYPE_REGISTRY.md)
- [Configuration Reload Guide](CONFIGURATION_RELOAD.md)
- [Weight Precedence Guide](WEIGHT_PRECEDENCE.md)
- [Integration Interfaces Guide](../integration/INTEGRATION_INTERFACES.md)
