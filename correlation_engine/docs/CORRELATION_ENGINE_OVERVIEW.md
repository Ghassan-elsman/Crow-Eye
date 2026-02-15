# Correlation Engine Overview

## Table of Contents

- [Introduction](#introduction)
- [What is the Correlation Engine?](#what-is-the-correlation-engine)
- [Core Architectural Principles](#core-architectural-principles)
- [Key Components and Their Interplay](#key-components-and-their-interplay)
- [Overall System Architecture](#overall-system-architecture)
- [Architecture Diagrams](#architecture-diagrams)
  - [System Architecture](#system-architecture)
  - [Data Flow](#data-flow)
  - [Correlation Execution Flow](#correlation-execution-flow)
  - [Dependency Graph](#dependency-graph)
  - [Component Interaction](#component-interaction)
- [Directory Structure](#directory-structure)
  - [engine/ - Core Correlation Engine](#engine---core-correlation-engine)
  - [feather/ - Data Normalization](#feather---data-normalization)
  - [wings/ - Correlation Rules](#wings---correlation-rules)
  - [config/ - Configuration Management](#config---configuration-management)
  - [pipeline/ - Workflow Orchestration](#pipeline---workflow-orchestration)
  - [gui/ - User Interface](#gui---user-interface)
  - [integration/ - Crow-Eye Bridge & Shared Services](#integration---crow-eye-bridge--shared-services)
- [Quick Start Guide](#quick-start-guide)
  - [Common Tasks](#common-tasks)
  - [Modification Scenarios](#modification-scenarios)
- [Detailed Documentation](#detailed-documentation)
- [Additional Resources](#additional-resources)
- [Contributing](#contributing)
- [Getting Help](#getting-help)

---

## Introduction

This document provides a comprehensive overview of the Crow-Eye Correlation Engine architecture. It serves as the main entry point for developers and contributors who want to understand, modify, or extend the correlation engine system.

### Purpose of This Document

- **Understand the System**: Get a high-level view of how all components work together.
- **Navigate the Codebase**: Find the right files to modify for specific tasks.
- **Visualize Architecture**: See diagrams that illustrate system structure and data flow.
- **Quick Reference**: Access common modification scenarios and development tasks.

### Who Should Read This

- Developers new to the Crow-Eye project.
- Contributors adding new features.
- Maintainers debugging issues.
- Anyone needing to understand the correlation engine architecture.

---

## What is the Correlation Engine?

The Crow-Eye Correlation Engine is a highly sophisticated, modular, and optimized system designed for in-depth forensic analysis. It leverages a **dual-engine architecture**—the **Time-Window Scanning Engine (TWSE)** and the **Identity-Based Correlation Engine (IBCE)**—each tailored for different use cases and dataset characteristics. Both engines deliver `O(N log N)` performance.

### Dual-Engine Architecture:
1.  **Time-Window Scanning Engine (TWSE)**: A revolutionary `O(N log N)` systematic temporal analysis approach that scans through forensic timelines in fixed intervals. It's designed for any dataset size with exceptional memory efficiency, achieving significant speed improvements through optimizations like quick empty-window checks, caching, parallel processing, and a two-phase architecture. Semantic analysis is primarily handled in a post-correlation phase for performance.
2.  **Identity-Based Correlation Engine (IBCE)**: A powerful `O(N log N)` strategy that groups records by identity first, then creates temporal anchors within each identity's timeline. Optimized for large datasets with streaming support, it excels at robust identity extraction, normalization, and applying semantic rules and scoring directly during the correlation process.

### Core Architectural Principles:
-   **Modularity and Extensibility**: Components are loosely coupled, allowing for independent development and easy integration of new features or strategies.
-   **Performance and Scalability**: Extensive use of caching, parallel processing, query-based evaluation, and streaming mode efficiently handles massive forensic datasets.
-   **Resilience and Robustness**: Comprehensive error handling, retry mechanisms, graceful degradation, and cancellation support ensure stability and data integrity even under challenging conditions.
-   **Configurability**: Highly configurable parameters through various configuration classes and a centralized configuration manager.
-   **Transparency and User Feedback**: Detailed progress tracking, performance monitoring, and human-readable semantic enrichment enhance user experience and debugging capabilities.

---

## Key Components and Their Interplay:

1.  **Configuration Management (`config` directory)**:
    -   **`ConfigManager`**: Centralized manager for loading, saving, and managing various configuration types.
    -   **`FeatherConfig`, `WingConfig`, `PipelineConfig`**: Core data models for defining data sources, correlation rules, and end-to-end analysis workflows. `PipelineConfig` is the central configuration for orchestrating engine execution.
    -   **`ArtifactTypeRegistry`**: Singleton for managing forensic artifact metadata (weights, tiers, priorities).
    -   **`SemanticMappingManager`**: Manages a hierarchical system of semantic mappings and rules, including FTS5-based field alias matching.
2.  **Database Management (`engine/database_persistence.py` & `feather` directory)**:
    -   **`database_persistence.py` (`ResultsDatabase`, `StreamingMatchWriter`)**: Handles persistence of correlation results (execution results, wing-level results, and individual matches) to SQLite, supporting streaming and data compression.
    -   (`feather/` directory): Manages feather database creation and low-level operations.
3.  **Core Correlation Engines (`engine` directory)**:
    -   **`base_engine.py`**: Defines the `BaseCorrelationEngine` abstract interface, ensuring consistent API for all engine implementations.
    -   **`engine_selector.py`**: Factory for dynamically creating and configuring engine instances (TWSE or IBCE).
    -   **`time_based_engine.py` (`TimeWindowScanningEngine`)**: Implements the Time-Window Scanning strategy with advanced optimizations and resilience features.
    -   **`identity_based_engine_adapter.py` (`IdentityBasedCorrelationEngine`)**: Implements the Identity-Based Correlation strategy, adapting `identifier_correlation_engine.py` to the `BaseCorrelationEngine` interface and integrating shared services.
4.  **Identifier Processing (`engine/identity_extractor.py`, `engine/identity_validator.py`, `engine/identifier_correlation_engine.py`)**:
    -   **`identity_extractor.py`**: Extracts and normalizes identities from records.
    -   **`identity_validator.py`**: Filters out noisy or non-meaningful identity values for high-quality correlation.
    -   **`identifier_correlation_engine.py`**: Manages the in-memory identity-centric state for IBCE.
5.  **Integrated Services (`integration/semantic_mapping_integration.py`, `integration/weighted_scoring_integration.py`)**:
    -   **`semantic_mapping_integration.py`**: Applies semantic rules to correlation results, enriching them with contextual meaning.
    -   **`weighted_scoring_integration.py`**: Calculates weighted confidence scores for matches based on configured rules.
6.  **Performance & Monitoring (`engine/performance_monitor.py`, `engine/performance_analysis.py`, `engine/progress_tracking.py`, `integration/integration_monitor.py`)**:
    -   **`performance_monitor.py`**: Collects fine-grained performance metrics.
    -   **`performance_analysis.py`**: Analyzes performance data to validate complexity and identify bottlenecks.
    -   **`progress_tracking.py`**: Comprehensive system for tracking and reporting progress, time estimation, and cancellation.
    -   **`integration_monitor.py`**: Monitors integration components for performance and health.
7.  **Resilience & Resource Management (`engine/error_handling_coordinator.py`, `engine/database_error_handler.py`, `engine/cancellation_support.py`, `engine/memory_manager.py`, `integration/integration_error_handler.py`)**:
    -   **`error_handling_coordinator.py`**: Central orchestrator for error detection, logging, and recovery.
    -   **`database_error_handler.py`**: Handles database-specific errors with retry logic and fallback strategies.
    -   **`cancellation_support.py`**: Manages graceful cancellation, resource cleanup, and partial results preservation.
    -   **`memory_manager.py`**: Monitors, estimates, and manages memory usage, activating streaming mode to prevent OOM errors.
    -   **`integration_error_handler.py`**: Provides comprehensive error handling and graceful degradation for all integration components.

The Crow-Eye Correlation Engine is a highly sophisticated system designed to tackle the complexities of forensic data analysis effectively. It prioritizes both performance and interpretability, offering powerful tools for investigators.

---

## Overall System Architecture

```mermaid
graph TD
    subgraph "User Interface Layer"
        GUI[Crow-Eye GUI]
    end

    subgraph "Orchestration Layer"
        PipelineLoader[Pipeline Loader<br/>(pipeline/pipeline_loader.py)]
        PipelineExecutor[Pipeline Executor<br/>(pipeline/pipeline_executor.py)]
        EngineSelector[Engine Selector<br/>(engine/engine_selector.py)]
    end

    subgraph "Core Engine Layer"
        TimeWindowEngineAdapter[Time-Window Scanning Engine<br/>(engine/time_based_engine.py)]
        IdentityBasedEngineAdapter[Identity-Based Engine<br/>(engine/identity_based_engine_adapter.py)]
        BaseEngine[BaseCorrelationEngine<br/>(engine/base_engine.py)]
        
        TimeWindowEngineAdapter -- implements --> BaseEngine
        IdentityBasedEngineAdapter -- implements --> BaseEngine
    end
    
    subgraph "Shared Services & Integrations"
        SharedIntegrations[Shared Integrations<br/>(integration/)]
        IntegrationErrorHandler[Integration Error Handler<br/>(integration/integration_error_handler.py)]
        IntegrationMonitor[Integration Monitor<br/>(integration/integration_monitor.py)]
        SemanticMappingIntegration[Semantic Mapping Integration<br/>(integration/semantic_mapping_integration.py)]
        WeightedScoringIntegration[Weighted Scoring Integration<br/>(integration/weighted_scoring_integration.py)]
    end

    subgraph "Configuration Layer"
        ConfigManager[Configuration Manager<br/>(config/config_manager.py)]
        PipelineConfig[PipelineConfig<br/>(config/pipeline_config.py)]
        FeatherConfig[FeatherConfig<br/>(config/feather_config.py)]
        WingConfig[WingConfig<br/>(config/wing_config.py)]
    end

    subgraph "Data & Persistence Layer"
        FeatherDB[(Feather Databases)]
        ResultsDB[(Correlation Results DB)]
    end

    GUI --> PipelineLoader
    PipelineLoader -- loads configs --> ConfigManager
    PipelineLoader --> PipelineExecutor
    PipelineExecutor -- selects & executes --> EngineSelector
    EngineSelector -- instantiates --> TimeWindowEngineAdapter
    EngineSelector -- instantiates --> IdentityBasedEngineAdapter

    PipelineExecutor -- provides configs --> PipelineConfig
    PipelineExecutor -- provides configs --> FeatherConfig
    PipelineExecutor -- provides configs --> WingConfig

    TimeWindowEngineAdapter -- depends on --> SharedIntegrations
    IdentityBasedEngineAdapter -- depends on --> SharedIntegrations
    SharedIntegrations -- uses --> IntegrationErrorHandler
    SharedIntegrations -- uses --> IntegrationMonitor
    SharedIntegrations -- uses --> SemanticMappingIntegration
    SharedIntegrations -- uses --> WeightedScoringIntegration

    TimeWindowEngineAdapter -- accesses --> FeatherDB
    IdentityBasedEngineAdapter -- accesses --> FeatherDB

    TimeWindowEngineAdapter -- persists results --> ResultsDB
    IdentityBasedEngineAdapter -- persists results --> ResultsDB

    ResultsDB --> GUI
    ConfigManager --> GUI

    style GUI fill:#ffff99
    style PipelineLoader fill:#cbe86b
    style PipelineExecutor fill:#cc99ff
    style EngineSelector fill:#ffcc99
    style TimeWindowEngineAdapter fill:#ff9999
    style IdentityBasedEngineAdapter fill:#99ff99
    style BaseEngine fill:#cccccc
    style SharedIntegrations fill:#b0e0e6
    style IntegrationErrorHandler fill:#f08080
    style IntegrationMonitor fill:#add8e6
    style SemanticMappingIntegration fill:#c0c0c0
    style WeightedScoringIntegration fill:#d3d3d3
    style ConfigManager fill:#ffcc99
    style PipelineConfig fill:#f5deb3
    style FeatherConfig fill:#f5deb3
    style WingConfig fill:#f5deb3
    style FeatherDB fill:#99ccff
    style ResultsDB fill:#99ccff

```


## Architecture Diagrams

## Directory Structure

The `correlation_engine` is organized into several key directories, each with a specific responsibility:

### `engine/` - Core Correlation Engine

**Purpose**: Contains the core correlation logic, dual-engine implementations (Time-Window Scanning and Identity-Based), performance monitoring, and resilience infrastructure.

**Key Files/Components**:
-   **`time_based_engine.py`**: Implementation of the Time-Window Scanning Engine (TWSE).
-   **`identity_based_engine_adapter.py`**: Implementation of the Identity-Based Correlation Engine (IBCE).
-   **`engine_selector.py`**: Factory for creating and configuring engine instances.
-   **`feather_loader.py`**: Loads and queries feather databases.
-   **`weighted_scoring.py`**: Calculates weighted scores for matches (core logic).
-   **`performance_monitor.py`**: Collects and reports performance metrics.
-   **`error_handling_coordinator.py`**: Manages overall error handling and recovery.
-   **`cancellation_support.py`**: Provides graceful cancellation and resource management.
-   **`memory_manager.py`**: Monitors and manages memory usage.

**[📖 Detailed Documentation](engine/ENGINE_DOCUMENTATION.md)**

### `feather/` - Data Normalization

**Purpose**: Handles importing forensic artifact data from various sources and normalizing it into the feather format.

**Key Files/Components**:
-   **`database.py`**: Low-level database operations for feather databases.
-   **`feather_builder.py`**: Builds feather databases (integrated via `integration/`).

**[📖 Detailed Documentation](feather/FEATHER_DOCUMENTATION.md)**

### `wings/` - Correlation Rules

**Purpose**: Defines the data models and validation logic for Wing configurations (correlation rules).

**Key Files/Components**:
-   **`core/wing_model.py`**: Defines `Wing`, `FeatherSpec`, `CorrelationRules` data models.
-   **`core/wing_validator.py`**: Validates wing configurations.
-   **`core/artifact_detector.py`**: Detects artifact types (used by feather building).

**[📖 Detailed Documentation](wings/WINGS_DOCUMENTATION.md)**

### `config/` - Configuration Management

**Purpose**: Manages all configuration files (feathers, wings, pipelines) and semantic mappings.

**Key Files/Components**:
-   **`config_manager.py`**: Central configuration management.
-   **`feather_config.py`, `wing_config.py`, `pipeline_config.py`**: Core configuration data models. `PipelineConfig` defines the overall analysis workflow.
-   **`artifact_type_registry.py`**: Manages artifact type definitions.
-   **`semantic_mapping.py`**: Defines semantic mappings and rules, including `FieldAliasFTS`.
-   **`integrated_configuration_manager.py`**: Manages advanced, integrated configuration features.

**[📖 Detailed Documentation](config/CONFIG_DOCUMENTATION.md)**

### `pipeline/` - Workflow Orchestration

**Purpose**: Orchestrates complete analysis workflows, including feather creation, wing execution, and report generation.

**Key Files/Components**:
-   **`pipeline_executor.py`**: The main orchestrator for pipeline execution, utilizing the chosen correlation engine.
-   **`pipeline_loader.py`**: Loads and validates pipeline configurations.
-   **`discovery_service.py`**: Discovers available configurations.
-   **`feather_auto_registration.py`**: Automates feather registration.

**[📖 Detailed Documentation](pipeline/PIPELINE_DOCUMENTATION.md)**

### `gui/` - User Interface

**Purpose**: Provides all GUI components for the correlation engine, enabling user interaction, results visualization, and configuration editing.

**Key Files/Components**: (Only showing core interaction points with the engine)
-   **`main_window.py`**: Main application window.
-   **`pipeline_management_tab.py`**: Manages pipeline creation and execution.
-   **`correlation_results_view.py`, `hierarchical_results_view.py`, `results_viewer.py`**: Display correlation results.
-   **`execution_control.py`**: Controls engine execution from the GUI.
-   **`semantic_mapping_viewer.py`**: Manages semantic mappings.

**[📖 Detailed Documentation](gui/GUI_DOCUMENTATION.md)**

### `integration/` - Crow-Eye Bridge & Shared Services

**Purpose**: Integrates the correlation engine with the main Crow-Eye application, providing auto-generation features, default configurations, and pluggable shared services (e.g., semantic mapping, weighted scoring).

**Key Files/Components**:
-   **`crow_eye_integration.py`**: Main integration bridge with the Crow-Eye application.
-   **`auto_feather_generator.py`**: Automates feather creation.
-   **`case_initializer.py`**: Initializes engine for case analysis.
-   **`interfaces.py`**: Defines abstract interfaces for pluggable engine components (ee.g., `IScoringIntegration`, `ISemanticMappingIntegration`).
-   **`semantic_mapping_integration.py`**: Integration for semantic mapping.
-   **`weighted_scoring_integration.py`**: Integration for weighted scoring.
-   **`integration_error_handler.py`**: Comprehensive error handling for integrations.
-   **`integration_monitor.py`**: Performance and health monitoring for integrations.

**[📖 Detailed Documentation](integration/INTEGRATION_DOCUMENTATION.md)**

---

## Quick Start Guide

### Common Tasks

#### 1. Understanding the Correlation Process

**Start here**: Read the [Correlation Execution Flow](#correlation-execution-flow) diagram above and the [Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide) within the main Engine Documentation.

**Key files to understand**:
-   `engine/engine_selector.py` - Engine factory and selection.
-   `engine/base_engine.py` - Common engine interface.
-   `engine/time_based_engine.py` - Time-Window Scanning correlation strategy implementation.
-   `engine/identity_based_engine_adapter.py` - Identity-Based correlation strategy implementation.
-   `engine/two_phase_correlation.py` - Two-phase architecture components (for TWSE).
-   `engine/feather_loader.py` - How feathers are loaded.
-   `wings/core/wing_model.py` - Wing configuration structure.

**Engine Selection**: Choose the appropriate engine based on your needs:
-   **Any dataset size, systematic temporal analysis**: Time-Window Scanning Engine (TWSE).
-   **Large datasets with comprehensive identity tracking**: Identity-Based Correlation Engine (IBCE).

#### 2. Selecting the Right Correlation Engine

**Decision Factors**:
-   **Dataset Size**: Both engines are optimized for large datasets. TWSE offers systematic temporal analysis across any size. IBCE excels with large datasets requiring identity tracking.
-   **Analysis Goal**: TWSE for discovering temporal proximity, IBCE for understanding entity activity.
-   **Performance**: Both provide `O(N log N)` performance with different optimization strategies.

**See**: [Engine Selection Guide](engine/ENGINE_DOCUMENTATION.md#engine-selection-guide) for detailed decision criteria and use case scenarios within the main Engine Documentation.

#### 3. Adding Support for a New Artifact Type

**Files to modify**:
1.  `integration/feather_mappings.py` - Add column mappings for the new artifact.
2.  `feather/transformer.py` - Add transformation logic if needed.
3.  `config/artifact_type_registry.py` - Register the new artifact type with its properties.
4.  `engine/identity_correlation_engine.py` - Add artifact-specific field mappings for the Identity-Based engine (if applicable).

**See**: [Feather Documentation - Adding New Artifact Type](feather/FEATHER_DOCUMENTATION.md#scenario-adding-support-for-a-new-artifact-type)

#### 4. Modifying Correlation Logic

**Files to modify**:
1.  `engine/time_based_engine.py` - Modify Time-Window Scanning correlation algorithm.
2.  `engine/identity_based_engine_adapter.py` - Modify Identity-Based correlation algorithm.
3.  `engine/weighted_scoring.py` - Modify core scoring logic.
4.  Test with various wings to ensure changes work correctly.

**See**: [Engine Documentation - Common Modification Scenarios](engine/ENGINE_DOCUMENTATION.md#common-modification-scenarios)

#### 5. Adding a New GUI Feature

**Files to modify**:
1.  Create new file in `gui/` (e.g., `graph_view.py`).
2.  Develop a GUI widget (e.g., inheriting from `QWidget`) that can consume `CorrelationResult` or `CorrelationResults` objects.
3.  Integrate the new widget into `gui/main_window.py` or `gui/results_viewer.py`.

**See**: [GUI Documentation - Adding New Feature](gui/GUI_DOCUMENTATION.md#scenario-1-adding-a-new-tab-to-main-window)

#### 6. Adding a New Configuration Option

**Files to modify**:
1.  `wings/core/wing_model.py` - Add field to `CorrelationRules` or `Wing`.
2.  `config/wing_config.py` - Update `WingConfig` (data model) if needed.
3.  `config/pipeline_config.py` - Update `PipelineConfig` if the option is pipeline-level.
4.  Implement logic in relevant engine (`engine/time_based_engine.py` or `engine/identity_based_engine_adapter.py`) to use the new option.
5.  `gui/` - Add UI controls for the new option.

**See**: [Config Documentation - Adding Configuration Option](config/CONFIG_DOCUMENTATION.md#scenario-adding-a-new-configuration-option)

### Modification Scenarios

(Note: This section will be simplified, as `ENGINE_DOCUMENTATION.md` now contains a dedicated "Common Modification Scenarios" section with more detail. This section here will primarily serve as pointers to that more comprehensive guide.)

**For detailed common modification scenarios, refer to the [Common Modification Scenarios](engine/ENGINE_DOCUMENTATION.md#common-modification-scenarios) section in the main Engine Documentation.**

---

## Detailed Documentation

For in-depth information about each directory, including file-by-file documentation, dependency analysis, and impact assessments, see the detailed documentation files:

-   **[Engine Documentation](engine/ENGINE_DOCUMENTATION.md)** - **COMPREHENSIVELY UPDATED!** Core correlation engine, dual-engine details, engine comparison, selection guide, performance, troubleshooting, and detailed file-by-file component documentation.
-   **[Feather Documentation](feather/FEATHER_DOCUMENTATION.md)** - Data normalization, feather database management.
-   **[Wings Documentation](wings/WINGS_DOCUMENTATION.md)** - Correlation rule definitions, validation.
-   **[Config Documentation](config/CONFIG_DOCUMENTATION.md)** - Configuration management, semantic mappings, artifact types.
-   **[Pipeline Documentation](pipeline/PIPELINE_DOCUMENTATION.md)** - Workflow orchestration, automation.
-   **[GUI Documentation](gui/GUI_DOCUMENTATION.md)** - User interface components, visualization.
-   **[Integration Documentation](integration/INTEGRATION_DOCUMENTATION.md)** - Crow-Eye integration layer, pluggable components.
-   **[Wing vs Feather Guide](WING_FEATHER_GUIDE.md)** - Clarifies key concepts.

---

## Additional Resources

-   **[Feather Metadata Documentation](FEATHER_METADATA_OPTIONAL.md)** - Details on feather metadata tables.
-   **[Pipeline Config Manager README](PIPELINE_CONFIG_MANAGER_README.md)** - Pipeline configuration management.
-   **[../gui/README.md](../gui/README.md)** - GUI architecture overview (Note: Adjusted relative path)

---

## Contributing

When contributing to the correlation engine:

1.  **Read the relevant detailed documentation** for the area you're modifying.
2.  **Check the dependency graph** to understand what might be affected.
3.  **Review modification scenarios** for similar changes (see [Common Modification Scenarios](engine/ENGINE_DOCUMENTATION.md#common-modification-scenarios)).
4.  **Test thoroughly** with multiple artifact types and wings.
5.  **Update documentation** if you add new features or change behavior.

---

## Getting Help

If you need help understanding the correlation engine:

1.  Start with this overview document.
2.  Read the detailed documentation for the specific directory.
3.  Look at the diagrams to understand data flow.
4.  Review the code with the documentation as a guide.
5.  Check existing modification scenarios for similar tasks (see [Common Modification Scenarios](engine/ENGINE_DOCUMENTATION.md#common-modification-scenarios)).

---

*Last Updated: February 2026*
*Correlation Engine Version: 0.7.1 (Production-Ready Dual-Engine Architecture)*
*Documentation Version: 0.8 (Major update for engine internals)*
