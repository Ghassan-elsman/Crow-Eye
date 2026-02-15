# Engine Directory Documentation

## Table of Contents

- [Overview](#overview)
- [High-Level Architecture & Dual-Engine System](#high-level-architecture--dual-engine-system)
  - [Dual-Engine Architecture Benefits](#dual-engine-architecture-benefits)
  - [Engine Comparison](#engine-comparison)
  - [Dual-Engine Interaction with Shared Services](#dual-engine-interaction-with-shared-services)
- [Engine Selection Guide](#engine-selection-guide)
- [IBCE Internal Workflow](#ibce-internal-workflow)
- [Time-Window Scanning Engine (TWSE)](#time-window-scanning-engine-twse)
- [TWSE Internal Workflow (Two-Phase Correlation)](#twse-internal-workflow-two-phase-correlation)
- [Identity-Based Correlation Engine (IBCE)](#identity-based-correlation-engine-ibce)
- [Core Components](#core-components)
  - [Abstract Interfaces (`base_engine.py`, `integration/interfaces.py`)](#abstract-interfaces-base_enginepy-integrationinterfacespy)
  - [Engine Orchestration (`engine_selector.py`, `pipeline/pipeline_executor.py`, `pipeline/pipeline_loader.py`, `config/pipeline_config.py`)](#engine-orchestration-engine_selectorpy-pipelinepipeline_executorpy-pipelinepipeline_loaderpy-configpipeline_configpy)
  - [Data Loading & Processing (`feather_loader.py`)](#data-loading--processing-feather_loaderpy)
  - [Identity & Temporal Management (`identity_extractor.py`, `identity_validator.py`, `identifier_correlation_engine.py`, `identifier_extraction_pipeline.py`, `time_based_engine.py`, `two_phase_correlation.py`, `timestamp_parser.py`, `weighted_scoring.py`)](#identity--temporal-management-identity_extractorpy-identity_validatorpy-identifier_correlation_enginepy-identifier_extraction_pipelinepy-time_based_enginepy-two_phase_correlationpy-timestamp_parserpy-weighted_scoringpy)
  - [Result Management (`correlation_result.py`, `query_interface.py`, `database_persistence.py`)](#result-management-correlation_resultpy-query_interfacepy-database_persistencepy)
  - [Integrated Services (`integration/semantic_mapping_integration.py`, `integration/weighted_scoring_integration.py`)](#integrated-services-integrationsemantic_mapping_integrationpy-integrationweighted_scoring_integrationpy)
  - [Monitoring & Error Handling (`integration/integration_monitor.py`, `integration/integration_error_handler.py`, `performance_monitor.py`, `performance_analysis.py`, `progress_tracking.py`, `error_handling_coordinator.py`, `cancellation_support.py`, `memory_manager.py`, `correlation_statistics.py`, `parallel_window_processor.py`)](#monitoring--error-handling-integrationintegration_monitorpy-integrationintegration_error_handlerpy-performance_monitorpy-performance_analysispy-progress_trackingpy-error_handling_coordinatorpy-cancellation_supportpy-memory_managerpy-correlation_statisticspy-parallel_window_processorpy)
- [Files in This Directory (`engine/`)](#files-in-this-directory-engine)
  - [base_engine.py](#base_enginepy)
  - [cancellation_support.py](#cancellation_supportpy)
  - [correlation_engine.py](#correlation_enginepy)
  - [correlation_result.py](#correlation_resultpy)
  - [correlation_statistics.py](#correlation_statisticspy)
  - [data_structures.py](#data_structurespy)
  - [database_error_handler.py](#database_error_handlerpy)
  - [database_persistence.py](#database_persistencepy)
  - [engine_selector.py](#engine_selectorpy)
  - [error_handling_coordinator.py](#error_handling_coordinatorpy)
  - [feather_loader.py](#feather_loaderpy)
  - [identifier_correlation_engine.py](#identifier_correlation_enginepy)
  - [identifier_extraction_pipeline.py](#identifier_extraction_pipelinepy)
  - [IDENTIFIER_EXTRACTION_README.md](#identifier_extraction_readmemd)
  - [identity_based_engine_adapter.py](#identity_based_engine_adapterpy)
  - [identity_extractor.py](#identity_extractorpy)
  - [identity_validator.py](#identity_validatorpy)
  - [memory_manager.py](#memory_managerpy)
  - [parallel_window_processor.py](#parallel_window_processorpy)
  - [performance_analysis.py](#performance_analysispy)
  - [performance_monitor.py](#performance_monitorpy)
  - [progress_tracking.py](#progress_trackingpy)
  - [query_interface.py](#query_interfacepy)
  - [time_based_engine.py](#time_based_enginepy)
  - [timestamp_parser.py](#timestamp_parserpy)
  - [two_phase_correlation.py](#two_phase_correlationpy)
  - [weighted_scoring.py](#weighted_scoringpy)
  - [__init__.py](#__init__py)
- [Files in Other Directories Referenced by Engine Components](#files-in-other-directories-referenced-by-engine-components)
  - [\`config/pipeline_config.py\`](#configpipeline_configpy)
  - [\`integration/semantic_mapping_integration.py\`](#integrationsemantic_mapping_integrationpy)
  - [\`integration/integration_error_handler.py\`](#integrationintegration_error_handlerpy)
  - [\`integration/integration_monitor.py\`](#integrationintegration_monitorpy)
  - [\`integration/interfaces.py\`](#integrationinterfacespy)
  - [\`integration/weighted_scoring_integration.py\`](#integrationweighted_scoring_integrationpy)
  - [\`pipeline/pipeline_executor.py\`](#pipelinepipeline_executorpy)
  - [\`pipeline/pipeline_loader.py\`](#pipelinepipeline_loaderpy)
- [Common Modification Scenarios](#common-modification-scenarios)
- [Testing](#testing)
- [See Also](#see-also)

---

## Overview

The `engine/` directory contains the core correlation logic of the Crow-Eye Correlation Engine. This is where the actual temporal correlation happens, where forensic artifacts (Feathers) are processed, matched based on defined rules (Wings), scored for confidence, and where comprehensive results are generated and managed.

### Purpose

-   **Execute Wing configurations:** Drive the correlation process using predefined rules and data sources.
-   **Implement correlation strategies:** Provide dual-engine capabilities (Time-Window Scanning and Identity-Based) for diverse analysis needs.
-   **Load and query Feather databases:** Efficiently access and retrieve forensic data.
-   **Calculate confidence scores:** Assign meaningful scores to identified correlations.
-   **Parse various timestamp formats:** Ensure robust handling of temporal data.
-   **Extract and validate identity information:** Standardize and clean identifiers for reliable matching.
-   **Manage persistence:** Store correlation results in a queryable database.
-   **Monitor and report progress:** Provide real-time feedback and detailed performance metrics.
-   **Handle errors and ensure resilience:** Implement graceful degradation and recovery mechanisms.

### How It Fits in the Overall System

The `engine/` is the **heart** of the correlation system. It interacts with:

-   **Input**:
    -   `config/`: Provides `PipelineConfig`, `FeatherConfig`, and `WingConfig` to define the analysis.
    -   `pipeline/`: The `PipelineExecutor` orchestrates the execution flow.
    -   Feather databases: The raw, processed forensic data.
-   **Output**:
    -   `CorrelationResult` objects: Structured findings of the correlation.
    -   Results Database: Persistent storage of all correlation outcomes.
-   **Integrated Services**:
    -   `integration/`: Provides shared services like semantic mapping and weighted scoring, as well as monitoring and error handling.
    -   `wings/`: Defines the structure of `Wing` objects which encapsulate correlation rules.

The `engine/` directory is crucial for translating high-level analysis goals (defined in `PipelineConfig` and `WingConfig`) into concrete correlation actions and actionable results.

---

## High-Level Architecture & Dual-Engine System

The Crow-Eye Correlation Engine is a highly sophisticated, modular, and optimized system designed for in-depth forensic analysis. It leverages a **dual-engine architecture**—the **Time-Window Scanning Engine (TWSE)** and the **Identity-Based Correlation Engine (IBCE)**—each tailored for different use cases and dataset characteristics. Both engines deliver `O(N log N)` performance with different optimization strategies.

### Dual-Engine Architecture Benefits

-   **Flexibility**: Choose the right engine for your dataset size and analysis goals.
-   **Performance**: Both engines offer `O(N log N)` complexity with distinct optimization strategies. The IBCE, in particular, excels with large datasets through streaming.
-   **Scalability**: Both engines efficiently handle large datasets using strategies like two-phase architecture, smart memory management, parallel processing, and streaming modes.
-   **Memory Efficiency**: Optimized memory usage with intelligent caching, disk spilling (`WindowDataStorage` in TWSE), and incremental result persistence (`StreamingMatchWriter` in IBCE).
-   **Error Resilience**: Robust error handling (`IntegrationErrorHandler`), automatic retry mechanisms, and graceful degradation ensure continuous operation even when facing issues.

```mermaid
graph TD
    subgraph "User Interface Layer"
        GUI[Crow-Eye GUI]
    end

    subgraph "Orchestration Layer"
        PipelineLoader[Pipeline Loader]
        PipelineExecutor[Pipeline Executor]
        EngineSelector[Engine Selector]
    end

    subgraph "Core Engine Layer"
        TimeWindowEngineAdapter[Time-Window Scanning Engine<br/>(time_based_engine.py)<br/>O(N log N) Complexity<br/>Systematic Temporal Analysis]
        IdentityBasedEngineAdapter[Identity-Based Engine<br/>(identity_based_engine_adapter.py)<br/>O(N log N) Complexity<br/>Identity-First Clustering]
        BaseEngine[BaseCorrelationEngine<br/>(base_engine.py)<br/>Abstract Interface]
        
        TimeWindowEngineAdapter -- implements --> BaseEngine
        IdentityBasedEngineAdapter -- implements --> BaseEngine
    end
    
    subgraph "Data & Persistence Layer"
        FeatherDB[(Feather Databases)]
        ResultsDB[(Correlation Results DB)]
        ConfigManager[Configuration Manager<br/>(config/)]
        SharedIntegrations[Shared Integrations<br/>(integration/)]
    end

    GUI --> PipelineLoader
    PipelineLoader --> PipelineExecutor
    PipelineExecutor --> EngineSelector
    PipelineExecutor --> TimeWindowEngineAdapter
    PipelineExecutor --> IdentityBasedEngineAdapter

    EngineSelector --> TimeWindowEngineAdapter
    EngineSelector --> IdentityBasedEngineAdapter

    TimeWindowEngineAdapter --> FeatherDB
    TimeWindowEngineAdapter --> ResultsDB
    TimeWindowEngineAdapter --> ConfigManager
    TimeWindowEngineAdapter --> SharedIntegrations

    IdentityBasedEngineAdapter --> FeatherDB
    IdentityBasedEngineAdapter --> ResultsDB
    IdentityBasedEngineAdapter --> ConfigManager
    IdentityBasedEngineAdapter --> SharedIntegrations

    ResultsDB --> GUI
    ConfigManager --> GUI
    SharedIntegrations --> GUI

    style GUI fill:#ffff99
    style PipelineLoader fill:#cbe86b
    style PipelineExecutor fill:#cc99ff
    style EngineSelector fill:#ffcc99
    style TimeWindowEngineAdapter fill:#ff9999
    style IdentityBasedEngineAdapter fill:#99ff99
    style BaseEngine fill:#cccccc
    style FeatherDB fill:#99ccff
    style ResultsDB fill:#99ccff
    style ConfigManager fill:#ffcc99
    style SharedIntegrations fill:#b0e0e6
```

### Engine Comparison

The table below provides a detailed comparison between the Time-Window Scanning Engine (TWSE) and the Identity-Based Correlation Engine (IBCE). This matrix highlights their distinct approaches, strengths, and optimal use cases.

| Feature                      | Time-Window Scanning Engine (TWSE) (`time_based_engine.py`)                                                                                                        | Identity-Based Correlation Engine (IBCE) (`identity_based_engine_adapter.py`)                                                                                                                    |
| :--------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |

### Dual-Engine Interaction with Shared Services

```mermaid
graph TD
    subgraph "Core Engine Layer"
        TWSE[Time-Window Scanning Engine<br/>(time_based_engine.py)]
        IBCE[Identity-Based Correlation Engine<br/>(identity_based_engine_adapter.py)]
        BaseEngine[BaseCorrelationEngine<br/>(base_engine.py)]

        TWSE -- implements --> BaseEngine
        IBCE -- implements --> BaseEngine
    end

    subgraph "Shared Integration Services"
        SemanticMapping[Semantic Mapping Integration<br/>(integration/semantic_mapping_integration.py)]
        WeightedScoring[Weighted Scoring Integration<br/>(integration/weighted_scoring_integration.py)]
        IntegrationErrorHandler[Integration Error Handler<br/>(integration/integration_error_handler.py)]
        IntegrationMonitor[Integration Monitor<br/>(integration/integration_monitor.py)]
        Interfaces[Interfaces<br/>(integration/interfaces.py)]
    end

    subgraph "Engine Support Services"
        ProgressTracking[Progress Tracking<br/>(progress_tracking.py)]
        CancellationSupport[Cancellation Support<br/>(cancellation_support.py)]
        ErrorHandlingCoord[Error Handling Coordinator<br/>(error_handling_coordinator.py)]
        PerformanceMonitoring[Performance Monitoring<br/>(performance_monitor.py)]
        MemoryManagement[Memory Management<br/>(memory_manager.py)]
        FeatherLoader[Feather Loader<br/>(feather_loader.py)]
        TimestampParser[Timestamp Parser<br/>(timestamp_parser.py)]
    end

    TWSE -- utilizes --> SemanticMapping
    TWSE -- utilizes --> WeightedScoring
    TWSE -- utilizes --> IntegrationErrorHandler
    TWSE -- utilizes --> IntegrationMonitor
    TWSE -- utilizes --> ProgressTracking
    TWSE -- utilizes --> CancellationSupport
    TWSE -- utilizes --> ErrorHandlingCoord
    TWSE -- utilizes --> PerformanceMonitoring
    TWSE -- utilizes --> MemoryManagement
    TWSE -- utilizes --> FeatherLoader
    TWSE -- utilizes --> TimestampParser

    IBCE -- utilizes --> SemanticMapping
    IBCE -- utilizes --> WeightedScoring
    IBCE -- utilizes --> IntegrationErrorHandler
    IBCE -- utilizes --> IntegrationMonitor
    IBCE -- utilizes --> ProgressTracking
    IBCE -- utilizes --> CancellationSupport
    IBCE -- utilizes --> ErrorHandlingCoord
    IBCE -- utilizes --> PerformanceMonitoring
    IBCE -- utilizes --> MemoryManagement
    IBCE -- utilizes --> FeatherLoader
    IBCE -- utilizes --> TimestampParser

    SemanticMapping -- uses --> Interfaces
    WeightedScoring -- uses --> Interfaces

```

| **Primary Grouping Mechanism** | **Fixed Time Windows First:** Divides the entire forensic timeline into predefined, fixed-size, and potentially overlapping time windows (`time_window_minutes`, `scanning_interval_minutes`).                                                                    | **Identities First:** Groups *all* evidence by a common, normalized identity (`identity_extractor.py`) across the entire dataset, regardless of initial temporal proximity.                        |
| **Correlation within Group** | **Cross-Feather Matching within Windows:** Within each fixed time window, it efficiently queries and processes records from *different feathers* that share a common "identity" (extracted via `_extract_identity_from_record`) and meet minimum feather requirements. | **Temporal Anchors within Identities:** *Within each grouped identity's timeline*, it then clusters chronologically proximate events (`_create_temporal_anchors` in `identity_based_engine_adapter.py`) into "anchors" based on a specified `time_window_minutes`. |
| **Data Access Strategy**     | **Optimized Window-Centric Queries:** Leverages `OptimizedFeatherQuery` and `WindowQueryManager` (both in `time_based_engine.py`) to retrieve records specifically for each time window.                                                                              | **Hash-Based Identity-Centric Collection:** Loads all relevant records, then organizes them into identities using a hash-based index (`identity_index`) for `O(1)` average-case lookup/addition.   |
| **Preprocessing Focus**      | **Time Range Optimization:** Strong emphasis on robust time range detection, statistical outlier filtering, and aggressively skipping empty time windows (`quick_check_window_has_records`).                                                                        | **Aggressive Identity Normalization:** Intense focus on extracting, validating, and *aggressively normalizing* identity strings (`identity_extractor.py`, `identity_validator.py`).               |
| **Parallelism**              | Explicitly designed to use `parallel_window_processor.py` to process multiple time windows concurrently.                                                                                                                                                 | The core processing per identity is generally sequential, but `identity_based_engine_adapter.py` can manage and execute multiple wings (pipelines) which can be processed in parallel at a higher level of orchestration. |
| **Memory Management**        | Utilizes `two_phase_correlation.py` (`WindowDataStorage`) to transparently spill intermediate window data to disk if configured memory limits are reached.                                                                                                   | Employs `database_persistence.py` (`StreamingMatchWriter`) to write final matches directly to disk when the volume of results is large, ensuring constant memory usage.                         |
| **Primary Analytical Goal**  | To discover **broad temporal patterns** and "what happened when" questions, especially focusing on relationships between disparate artifact types within specific, fixed timeframes.                                                                               | To **trace specific entity activity** (e.g., an application, file, or user) over time, answering "what did this file/process do?" questions.                                                   |
| **Performance Driver**       | `O(N log N)` complexity driven by efficient, indexed database range queries and orchestration of many distinct time windows. `log N` from database indexing.               | `O(N log N)` complexity from initial global sorting of all timestamped evidence (`_create_temporal_anchors`) before identity-specific temporal clustering. `log N` from sorting.              |
| **Semantic Mapping**         | Primarily in a post-correlation phase, but can apply some pre-filtering if configured.                                                                                | Integrated directly within the process (`semantic_mapping_integration.py`) with robust error handling and fallback strategies.                                                                   |
| **Scoring**                  | Utilizes `weighted_scoring.py` directly.                                                                                                                           | Integrated via `weighted_scoring_integration.py` for case-specific configuration, validation, and advanced interpretation.                                                                         |
| **Key Components**           | `time_based_engine.py`, `two_phase_correlation.py`, `parallel_window_processor.py`, `memory_manager.py`                                                               | `identity_based_engine_adapter.py`, `identifier_correlation_engine.py`, `identity_extractor.py`, `identity_validator.py`, `identifier_extraction_pipeline.py`, `query_interface.py`                  |

---

### Engine Selection Guide

Choosing the correct engine is crucial for optimal performance and relevant results. The Crow-Eye Correlation Engine provides flexibility to match various forensic investigation scenarios.

#### Decision Matrix

| Criterion                 | Time-Window Scanning Engine (TWSE)                                                 | Identity-Based Correlation Engine (IBCE)                                                  |
| :------------------------ | :--------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------- |
| **Primary Goal**          | Discover all temporal relationships; broad timeline reconstruction.                | Trace specific entity activity; deep dive into a particular application, user, or file.   |
| **Dataset Size**          | Any size; particularly efficient for datasets requiring extensive temporal slicing. | Large datasets (`> 1,000` records) where robust identity tracking is paramount.            |
| **Focus of Analysis**     | "What happened when?" in a general sense, across all available evidence.           | "What did *this entity* do over time?" Focus on the lifecycle of specific identities.     |
| **Memory Footprint**      | Excellent, especially for very large `N` due to `WindowDataStorage` spilling.      | Excellent, near-constant memory for very large `N` due to `StreamingMatchWriter`.         |
| **Performance**           | High performance through parallel window processing and aggressive empty-window skipping. | High performance through optimized identity grouping and dynamic temporal clustering within identities. |
| **Identity Management**   | Identifies identities within time windows; secondary to temporal grouping.         | **Core Strength**: Aggressive normalization, validation, and tracking of unique identities. |
| **Semantic Analysis**     | Applied effectively in a post-correlation phase.                                   | Integrated directly into the correlation process, enabling richer match context.            |
| **Use Cases**             | General timeline creation, anomaly detection across entire datasets, broad event mapping. | Tracing malware execution, user activity profiling, application usage patterns, focused incident response. |

#### Dataset Size Thresholds & Recommendations

-   **Small Datasets (< 100 records):**
    *   **Recommendation:** Either engine works well. TWSE might offer a more granular, systematic temporal breakdown.
    *   **Rationale:** Overhead of sophisticated optimizations is negligible.
    *   **Choose:** TWSE for detailed temporal insights; IBCE if identity tracking is still a primary need.

-   **Medium Datasets (100-1,000 records):**
    *   **Recommendation:** Both are efficient. Choice depends on analytical focus.
    *   **Choose:** TWSE for in-depth temporal patterns; IBCE for cleaner, identity-centric results.

-   **Large Datasets (1,000-10,000 records):**
    *   **Recommendation:** Both are highly performant.
    *   **Choose:** TWSE for comprehensive temporal analysis (especially with parallel processing); IBCE for robust identity tracking and clustering.

-   **Very Large Datasets (> 10,000 records):**
    *   **Recommendation:** Both engines are highly suitable, leveraging advanced scalability features.
    *   **Choose:** TWSE for overall temporal relationships; IBCE for entity-centric activity. Both use streaming/two-phase architectures automatically.

---

## Time-Window Scanning Engine (TWSE)

```mermaid
graph TD
    subgraph "TWSE Workflow (Two-Phase Correlation)"
        start((Start)) --> generate_windows(Generate Time Windows)
        generate_windows --> process_windows{Process Each Time Window}
        
        process_windows -- For Each Window --> quick_check(Quick Check Window<br/>(two_phase_correlation.py))
        quick_check -- Has Records? --> detailed_correlation(Detailed Correlation<br/>(time_based_engine.py))
        quick_check -- No Records? --> skip_window(Skip Window)
        
        detailed_correlation --> extract_identities(Extract Identities)
        extract_identities --> match_records(Match Records Across Feathers)
        match_records --> apply_scoring(Apply Weighted Scoring)
        apply_scoring --> persist_matches(Persist Matches<br/>(database_persistence.py))
        
        skip_window --> end_window(End Window Processing)
        persist_matches --> end_window
        
        end_window --> all_windows_processed{All Windows Processed?}
        all_windows_processed -- Yes --> end((End))
        all_windows_processed -- No --> process_windows
    end

    style start fill:#fff,stroke:#333,stroke-width:2px
    style end fill:#fff,stroke:#333,stroke-width:2px
    style generate_windows fill:#f9f,stroke:#333,stroke-width:2px
    style process_windows fill:#afa,stroke:#333,stroke-width:2px
    style quick_check fill:#ccf,stroke:#333,stroke-width:2px
    style detailed_correlation fill:#bbf,stroke:#333,stroke-width:2px
    style extract_identities fill:#bbf,stroke:#333,stroke-width:2px
    style match_records fill:#bbf,stroke:#333,stroke-width:2px
    style apply_scoring fill:#f9f,stroke:#333,stroke-width:2px
    style persist_matches fill:#f9f,stroke:#333,stroke-width:2px
    style skip_window fill:#eee,stroke:#333,stroke-width:2px
    style end_window fill:#ddd,stroke:#333,stroke-width:2px
    style all_windows_processed fill:#afa,stroke:#333,stroke-width:2px

```


The Time-Window Scanning Engine (`time_based_engine.py`) is Crow-Eye's advanced correlation strategy designed for systematic temporal analysis of forensic data. It processes records in discrete, configurable time windows, making it highly effective for identifying patterns and relationships across vast datasets. This engine is designed to deliver `O(N log N)` performance, where the `log N` factor typically arises from efficient database indexing and sorting operations within each window.

### Core Logic and Architecture

The TWSE operates on a "time-first" principle. It divides the entire forensic timeline into a series of potentially overlapping time windows. Within each window, it then performs cross-feather correlation by identifying records that share common attributes (identities) and fall within the defined temporal boundaries.

The engine's architecture is built around several key components:

1.  **Window Generation**: The entire dataset's time range is analyzed, and a series of fixed-size time windows are generated. These windows define the temporal slices within which correlation will occur.
2.  **Two-Phase Correlation (`two_phase_correlation.py`)**: To optimize performance and memory usage, the TWSE employs a two-phase correlation strategy:
    *   **Phase 1 (Quick Check)**: Rapidly identifies if a time window contains *any* relevant records. This phase aggressively skips empty or irrelevant windows, significantly reducing the `N` for further processing. This is implemented by `quick_check_window_has_records` within `TimeWindowScanningEngine`.
    *   **Phase 2 (Detailed Correlation)**: For windows that pass the quick check, a more in-depth correlation process is initiated. This involves querying all relevant feather data within the window, extracting identities, and generating `CorrelationMatch`es.
3.  **Optimized Feather Querying**: The engine utilizes specialized querying mechanisms (`OptimizedFeatherQuery` and `WindowQueryManager` classes within `time_based_engine.py`) to efficiently retrieve data from feather databases for each specific time window. This ensures that only necessary data is loaded, minimizing I/O and memory overhead.
4.  **Identity Extraction and Matching**: Within each window, potential identities (e.g., application names, file paths) are extracted from records. The engine then correlates records from different feathers that share these identities, forming the basis of a `CorrelationMatch`.
5.  **Memory Management (`memory_manager.py`)**: For very large datasets, the engine integrates a `WindowMemoryManager` that can transparently spill intermediate window data to disk (`WindowDataStorage` within `two_phase_correlation.py`) if configured memory limits are reached. This ensures robust handling of memory without exhausting system resources.
6.  **Parallel Processing (`parallel_window_processor.py`)**: The TWSE is designed to leverage multi-core processors by distributing independent time windows to be processed concurrently. This is managed by the `ParallelWindowProcessor`, which includes advanced load balancing and resource monitoring to maximize throughput.

### Key Components

*   **`time_based_engine.py`**: This is the primary implementation of the `BaseCorrelationEngine` for the Time-Window Scanning strategy. It orchestrates the window generation, two-phase correlation, feather querying, identity extraction, and match generation processes. It manages the `Wing` execution and applies filters.
*   **`two_phase_correlation.py`**: Implements the core logic for the two-phase approach (quick check and detailed correlation). It also contains the `WindowDataStorage` class for managing intermediate data and potentially spilling it to disk.
*   **`parallel_window_processor.py`**: Manages the parallel execution of time windows, distributing tasks to worker threads and handling load balancing.
*   **`memory_manager.py`**: Provides proactive memory management, including estimation, limit checking, and optimization suggestions, especially when dealing with large numbers of records per window.
*   **`feather_loader.py`**: Although a general component, it's heavily utilized by the TWSE for efficient, time-window-specific data retrieval from feather databases.
*   **`timestamp_parser.py`**: Ensures all timestamps from various forensic artifacts are consistently parsed and validated, critical for accurate time-windowing.

### Use Cases and Strengths

The TWSE is ideal for:

-   **General Timeline Reconstruction**: Systematically building a chronological sequence of events across diverse data sources.
-   **Broad Anomaly Detection**: Identifying unusual activity patterns by comparing events within a specific time context.
-   **Comprehensive Data Review**: Ensuring all temporal relationships within a given time slice are considered.
-   **Scalability for Extensive Timelines**: Efficiently handles long forensic timelines by dividing them into manageable windows, with optimizations for skipping empty periods.

### Performance Characteristics

-   **`O(N log N)` Complexity**: Achieved through efficient indexing and optimized querying within time windows.
-   **Memory Efficiency**: Utilizes `WindowDataStorage` to keep memory footprint low, even with large datasets, by intelligently managing intermediate data on disk.
-   **Aggressive Skipping**: The two-phase approach minimizes processing for empty windows, focusing resources on areas with actual activity.
-   **Parallel Processing**: Scales well on multi-core systems by processing independent time windows concurrently.

---

## Identity-Based Correlation Engine (IBCE)

```mermaid
graph TD
    subgraph "IBCE Workflow"
        start((Start)) --> configure(Load Pipeline & Engine Configs)
        configure --> load_feathers(Load Feather Databases)
        load_feathers --> extract_identities(Extract & Normalize Identities<br/>identity_extractor.py)
        extract_identities --> validate_identities(Validate Identities<br/>identity_validator.py)
        validate_identities --> process_identities{Process Each Identity}
        
        process_identities -- For Each Identity --> build_in_memory_state(Build In-Memory State<br/>identifier_correlation_engine.py)
        build_in_memory_state --> assign_anchors(Assign Temporal Anchors)
        assign_anchors --> stream_results(Stream Results to Database<br/>database_persistence.py)
        stream_results --> apply_semantic_mapping(Apply Semantic Mapping<br/>semantic_mapping_integration.py)
        apply_semantic_mapping --> apply_scoring(Apply Weighted Scoring<br/>weighted_scoring_integration.py)
        apply_scoring --> persist_results(Persist Final Results)
        persist_results --> end((End))
    end

    style start fill:#fff,stroke:#333,stroke-width:2px
    style end fill:#fff,stroke:#333,stroke-width:2px
    style configure fill:#f9f,stroke:#333,stroke-width:2px
    style load_feathers fill:#ccf,stroke:#333,stroke-width:2px
    style extract_identities fill:#ccf,stroke:#333,stroke-width:2px
    style validate_identities fill:#ccf,stroke:#333,stroke-width:2px
    style process_identities fill:#afa,stroke:#333,stroke-width:2px
    style build_in_memory_state fill:#bbf,stroke:#333,stroke-width:2px
    style assign_anchors fill:#bbf,stroke:#333,stroke-width:2px
    style stream_results fill:#f9f,stroke:#333,stroke-width:2px
    style apply_semantic_mapping fill:#f9f,stroke:#333,stroke-width:2px
    style apply_scoring fill:#f9f,stroke:#333,stroke-width:2px
    style persist_results fill:#f9f,stroke:#333,stroke-width:2px

```


The Identity-Based Correlation Engine (IBCE) is Crow-Eye's advanced correlation strategy optimized for tracing activity related to specific entities (identities) across disparate forensic artifacts. It prioritizes the grouping of evidence by a common, normalized identity *first*, and then clusters temporally proximate events within that identity's timeline. This engine is designed for `O(N log N)` performance, particularly excelling with large datasets by focusing on robust identity extraction and streaming capabilities.

### Core Logic and Architecture

The IBCE operates on an "identity-first" principle. It systematically extracts, normalizes, and validates identities from all available records. All records pertaining to a single identity are then processed together. Within each identity's timeline, events are clustered into "anchors" based on a defined time window, representing distinct periods of activity for that identity.

The engine's architecture is a sophisticated orchestration of several specialized components:

1.  **Identity Extraction and Normalization (`identity_extractor.py`)**: This foundational step ensures consistency. Values (e.g., filenames, paths) are converted to a standard format (lowercase, consistent path separators). This enables accurate grouping of records that refer to the same logical entity but may have different textual representations.
2.  **Identity Validation (`identity_validator.py`)**: To prevent noise and false positives, extracted identity values are rigorously validated. This filters out non-meaningful data such as boolean strings, pure numeric values, very short strings, or values without alphanumeric characters, ensuring that only high-quality identifiers contribute to the correlation.
3.  **In-Memory Correlation State (`identifier_correlation_engine.py`)**: This module builds and manages the core in-memory state of the engine. It processes extracted values from feather data to create and manage:
    *   **Identities**: Logical entities representing a file, application, or user.
    *   **Anchors**: Temporal groupings of evidence for a specific identity, representing a distinct execution or activity window.
    *   **EvidenceRows**: References to the original feather data associated with an anchor.
    The `IdentifierCorrelationEngine` processes incoming evidence, infers identities, groups them into anchors based on time windows, and stores the `EvidenceRow`s.
4.  **Complete Pipeline Orchestration (`identifier_extraction_pipeline.py`)**: This module acts as the conductor for the entire Identity-Based Correlation workflow. It wires together the `FeatherLoader`, `IdentifierCorrelationEngine`, and `DatabasePersistence` components. Its `run()` method systematically loads `WingsConfig`, initializes components, loads feather tables, extracts identifiers, correlates evidence using the `IdentifierCorrelationEngine`, and finally persists the aggregated results to the database.
5.  **Database Persistence (`database_persistence.py`)**: Correlation results (Identities, Anchors, and Evidence) are stored in a normalized relational SQLite database schema. The IBCE heavily leverages a `StreamingMatchWriter` (part of `database_persistence.py`) to stream results directly to disk as they are found, ensuring constant memory usage even when processing millions of records.
6.  **Query Interface (`query_interface.py`)**: Provides extensive capabilities to retrieve, filter, and summarize the persisted correlation results. It supports hierarchical retrieval (Identity → Anchors → Evidence), semantic filtering, pagination, and aggregate queries, including the ability to organize results by anchor time for time-centric analysis.
7.  **Integrated Semantic Mapping (`semantic_mapping_integration.py`)**: The IBCE integrates the semantic mapping system directly within its processing flow. This allows for real-time semantic enrichment of evidence records, providing richer context and interpretation to correlation matches. This integration handles configuration, graceful degradation, and provides detailed statistics.
8.  **Weighted Scoring (`weighted_scoring_integration.py`)**: Scores are calculated for correlation matches based on configured weights for different artifact types. This integration layer manages global and case-specific scoring configurations, performs validation, resolves conflicts, and can fall back to simpler scoring methods in case of errors.

### Key Components

*   **`identity_based_engine_adapter.py`**: This is the primary implementation of the `BaseCorrelationEngine` for the Identity-Based strategy. It acts as an adapter, wrapping the `IdentifierCorrelationEngine` and integrating it with other services like semantic mapping, weighted scoring, and progress tracking. It orchestrates the identity processing, anchor creation, streaming to the database, and the final Identity Semantic Phase.
*   **`identifier_correlation_engine.py`**: Builds and manages the in-memory state (Identities, Anchors, EvidenceRows) for identity-based correlation. It processes extracted values and clusters them temporally within each identity.
*   **`identity_extractor.py`**: Responsible for normalizing values (names, paths) and generating consistent identity keys, which is critical for accurate grouping.
*   **`identity_validator.py`**: Filters out noisy or non-meaningful identity values (e.g., boolean strings, numeric-only values) to ensure high-quality identifiers.
*   **`identifier_extraction_pipeline.py`**: Orchestrates the entire end-to-end workflow of identity extraction, correlation, and persistence. It ties together the `FeatherLoader`, `IdentifierCorrelationEngine`, and `DatabasePersistence`.
*   **`query_interface.py`**: Provides comprehensive query capabilities for the persisted identity-based correlation results.
*   **`semantic_mapping_integration.py`** (from `integration/`): Facilitates the application of semantic rules to evidence records, enriching correlation matches with contextual meaning.
*   **`weighted_scoring_integration.py`** (from `integration/`): Manages the calculation and interpretation of confidence scores based on configured artifact weights.

### Use Cases and Strengths

The IBCE is ideal for:

-   **Tracing Specific Entity Activity**: Following the digital footprints of a particular application, file, or user across various artifacts.
-   **Malware Analysis**: Understanding the full scope of a malware's activity, including execution, file modification, and network connections.
-   **User Behavior Profiling**: Constructing a timeline of actions performed by a specific user on a system.
-   **Focused Incident Response**: Quickly identifying all relevant evidence related to a suspicious identity.
-   **Scalability for Extensive Datasets**: Efficiently processes millions of records by streaming results to disk, maintaining a near-constant memory footprint.

### Performance Characteristics

-   **`O(N log N)` Complexity**: Achieved through efficient hash-based indexing for identity grouping and sorting for temporal clustering within identities.
-   **Memory Efficiency**: Utilizes a `StreamingMatchWriter` to persist results incrementally, ensuring constant memory usage even for very large `N`. This allows it to process datasets of virtually any size without running out of memory.
-   **Aggressive Normalization**: Reduces the effective `N` by ensuring that variations of the same identity are grouped, leading to more focused processing.
-   **Integrated Semantic Enrichment**: Enhances results with context and meaning directly, streamlining the analysis workflow.

---

## Core Components

The correlation engine is built upon a modular architecture, where various components collaborate to achieve the overall correlation process. These components are categorized below based on their primary function.

### Abstract Interfaces (`base_engine.py`, `integration/interfaces.py`)

These modules define the foundational contracts and abstract structures that enable modularity, extensibility, and testability throughout the correlation engine.

-   **`base_engine.py`**:
    -   **Purpose**: Defines the abstract interface (`BaseCorrelationEngine`) that all concrete correlation engine implementations must adhere to. It establishes a contract for engine functionality, ensuring consistency and extensibility.
    -   **Key Functionalities**:
        -   `BaseCorrelationEngine`: An Abstract Base Class (ABC) with abstract methods like `execute_wing()`, enforcing a common API.
        -   `EngineMetadata`: A dataclass for providing metadata about each engine (name, description, capabilities).
        -   `FilterConfig`: A dataclass to encapsulate filtering parameters (time periods, identity filters, case sensitivity).
        -   Common utilities: Provides helper methods for parsing timestamps and filtering records that are reusable by different engine implementations.
    -   **Role in Architecture**: Acts as the foundational interface, enabling the dual-engine architecture to function interchangeably within the `PipelineExecutor` and `EngineSelector`.
-   **`integration/interfaces.py`**:
    -   **Purpose**: Defines abstract base classes (`IScoringIntegration`, `ISemanticMappingIntegration`, `IConfigurationObserver`) that act as contracts for various integration components.
    -   **Key Functionalities**:
        -   Enables dependency injection, testability with mocks, and promotes loose coupling between the core engines and external services, adhering to the Dependency Inversion Principle.
        -   Includes `IntegrationStatistics` dataclass for standardized reporting of integration metrics.
    -   **Role in Architecture**: Defines the foundational contracts and abstract structures that enable modularity, extensibility, and testability throughout the correlation engine.

### Engine Orchestration (`engine_selector.py`, `pipeline/pipeline_executor.py`, `pipeline/pipeline_loader.py`, `config/pipeline_config.py`)

These components manage the lifecycle of correlation analysis, from loading configurations to executing the chosen engine and generating reports.

-   **`engine_selector.py`**:
    -   **Purpose**: Acts as a factory for creating and managing different engine instances (`TimeWindowScanningEngine`, `IdentityBasedEngineAdapter`).
    -   **Key Functionalities**:
        -   `create_engine()`: Instantiates the correct `BaseCorrelationEngine` implementation (TWSE or IBCE) based on the `engine_type` specified in the `PipelineConfig`.
        -   `EngineType` enum: Defines available engine types.
        -   Provides metadata about registered engines.
    -   **Role in Architecture**: Decouples the `PipelineExecutor` from direct engine instantiation, making the system flexible and allowing new engine types to be added easily.
-   **`pipeline/pipeline_executor.py`**:
    -   **Purpose**: The central orchestrator responsible for executing entire analysis pipelines defined by `PipelineConfig` objects.
    -   **Key Functionalities**:
        -   Manages the process from feather creation and wing execution to dependency handling and report generation.
        -   Integrates shared services like scoring and semantic mapping, and supports cancellation of ongoing operations.
    -   **Role in Architecture**: The primary client of the correlation engine, orchestrating its execution based on pipeline configurations.
-   **`pipeline/pipeline_loader.py`**:
    -   **Purpose**: Loads a complete pipeline bundle, encompassing `PipelineConfig` and all associated `FeatherConfig` and `WingConfig` files.
    -   **Key Functionalities**:
        -   Handles validation of dependencies, resolves file paths (absolute and relative), and manages database connections, preparing all components for the `PipelineExecutor`.
    -   **Role in Architecture**: Prepares all configurations and dependencies, ensuring the `PipelineExecutor` (and by extension, the correlation engine) receives a validated and resolved setup.
-   **`config/pipeline_config.py`**:
    -   **Purpose**: Defines the `PipelineConfig` dataclass, the comprehensive configuration object for an entire correlation pipeline.
    -   **Key Functionalities**:
        -   Centralizes all settings, including engine selection, case information, feather/wing configurations, execution parameters (time ranges, filters), semantic mapping and scoring settings, logging options, and output directives.
    -   **Role in Architecture**: The ultimate source of truth for an engine's operational parameters, defining how the engine should behave.

### Data Loading & Processing (`feather_loader.py`)

This component is responsible for efficiently accessing and preparing forensic artifact data for the correlation engines.

-   **`feather_loader.py`**:
    -   **Purpose**: Provides a unified interface for loading data from feather databases and performing initial identifier extraction and validation.
    -   **Key Functionalities**:
        -   `FeatherLoader`: Handles loading feather files with schema detection and optional identifier extraction.
        -   Supports column mapping and data validation against configured rules.
        -   Integrates with `identity_extractor.py` and `identity_validator.py` for pre-processing steps.
    -   **Role in Architecture**: Abstracts the complexities of feather data access, providing a consistent stream of processed records to both correlation engines.

### Identity & Temporal Management (`identity_extractor.py`, `identity_validator.py`, `identifier_correlation_engine.py`, `identifier_extraction_pipeline.py`, `time_based_engine.py`, `two_phase_correlation.py`, `timestamp_parser.py`, `weighted_scoring.py`)

These components form the core logic for identifying entities, validating their significance, and managing their temporal relationships within the correlation process. This includes the direct implementation of engine logic as well as supporting utilities.

-   **`identity_extractor.py`**:
    -   **Purpose**: Responsible for normalizing various types of identifier values (names, paths) and generating consistent identity keys.
    -   **Key Functionalities**:
        -   `normalize_name()`: Converts filenames to a standard format (e.g., lowercase).
        -   `normalize_path()`: Standardizes Windows paths (lowercase, consistent separators).
        -   `extract_filename_from_path()`: Extracts the filename component from a full path.
        -   `generate_identity_key()`: Creates consistent keys like `type:normalized_value`.
    -   **Role in Architecture**: A fundamental utility for both engines, ensuring that different textual representations of the same entity are consistently mapped for accurate correlation.
-   **`identity_validator.py`**:
    -   **Purpose**: Validates identity values extracted from forensic artifacts to filter out "noisy" or non-meaningful data.
    -   **Key Functionalities**:
        -   `is_valid_identity()`: Checks for boolean strings, pure numeric values, empty/short strings, and absence of alphanumeric characters.
        -   `should_validate_field()`: Supports context-aware validation by allowing specific fields (e.g., 'guid', 'event_id') to bypass strict numeric/boolean checks.
    -   **Role in Architecture**: Enhances the quality of correlation by preventing irrelevant or misleading values from being treated as significant identities.
-   **`identifier_correlation_engine.py`**:
    -   **Purpose**: Implements the core in-memory processing logic for the Identity-Based Correlation Engine.
    -   **Key Functionalities**:
        -   `IdentifierCorrelationEngine`: Processes `ExtractedValues` from feather rows.
        -   Manages an internal state that builds `Identities`, `Anchors` (temporal activity clusters for identities), and links `EvidenceRows` to them.
        -   Provides methods for querying identity, anchor, and evidence counts, and resetting its state.
    -   **Role in Architecture**: The primary component responsible for constructing the identity-centric view of forensic data in memory before it is persisted.
-   **`identifier_extraction_pipeline.py`**:
    -   **Purpose**: Orchestrates the end-to-end workflow for identifier extraction, correlation, and persistence specifically for the Identity-Based Engine.
    -   **Key Functionalities**:
        -   `IdentifierExtractionPipeline`: Wires together `FeatherLoader`, `IdentifierCorrelationEngine`, and `DatabasePersistence`.
        -   Manages the sequence of operations: loading configurations, processing feather tables, extracting identifiers, correlating evidence, and persisting results.
    -   **Role in Architecture**: Provides the full operational workflow for the Identity-Based Correlation Engine, acting as a high-level controller for its specialized components.
-   **`time_based_engine.py`**:
    -   **Purpose**: The concrete implementation of the `BaseCorrelationEngine` for the Time-Window Scanning strategy.
    -   **Key Functionalities**:
        -   `TimeWindowScanningEngine`: Orchestrates the entire TWSE workflow, including window generation, two-phase correlation, parallel processing, and match generation.
        -   `OptimizedFeatherQuery`, `WindowQueryManager`: Internal classes for efficient, window-centric data retrieval from feather databases.
        -   Integrates `memory_manager.py` and `parallel_window_processor.py` to manage resources and concurrency.
    -   **Role in Architecture**: The high-level entry point for executing Time-Window Scanning correlation, providing a robust and feature-rich implementation of the `ICorrelationEngine` interface.
-   **`two_phase_correlation.py`**:
    -   **Purpose**: Implements the core logic for the Two-Phase Correlation strategy used by the Time-Window Scanning Engine.
    -   **Key Functionalities**:
        -   Defines the two phases: a quick check (`quick_check_window_has_records`) to rapidly identify windows with activity, and a detailed correlation for active windows.
        -   `WindowDataStorage`: Manages intermediate window data, potentially spilling it to disk to maintain memory efficiency for large datasets.
    -   **Role in Architecture**: A key performance optimization for the TWSE, significantly reducing processing time by avoiding expensive operations on empty or sparse time windows.
-   **`timestamp_parser.py`**:
    -   **Purpose**: Provides robust and flexible parsing for a wide array of timestamp formats.
    -   **Key Functionalities**:
        -   `TimestampParser`: Handles ISO 8601, Unix epoch, Windows FILETIME, and custom formats.
        -   Includes validation for forensic relevance (e.g., within 1990-2050 range) and graceful error handling for unparseable values.
    -   **Role in Architecture**: A critical utility for ensuring all time-related data from diverse sources is accurately normalized, which is fundamental for any temporal correlation.
-   **`weighted_scoring.py`**:
    -   **Purpose**: Provides the core logic for calculating weighted confidence scores for correlation matches.
    -   **Key Functionalities**:
        -   `WeightedScoringEngine`: Applies configurable weights (based on artifact type, tier, etc.) to matched evidence to produce a composite score.
        -   Includes logic for breaking down scores and providing human-readable interpretations.
    -   **Role in Architecture**: The algorithmic core for assessing the significance and confidence of identified correlations, used directly by the TWSE and integrated into the IBCE via `integration/weighted_scoring_integration.py`.

### Result Management (`correlation_result.py`, `query_interface.py`, `database_persistence.py`)

These components handle the structuring, storage, and retrieval of correlation outcomes.

-   **`correlation_result.py`**:
    -   **Purpose**: Defines the data structures used to encapsulate the output of correlation engine execution.
    -   **Key Functionalities**:
        -   `CorrelationMatch`: A dataclass representing a single identified correlation, including matched records, timestamps, scores, and metadata.
        -   `CorrelationResult`: A comprehensive dataclass summarizing the outcome of a single wing's execution, including lists of `CorrelationMatch`es, execution statistics, and any errors or warnings.
        -   `FeatherMatchResult`: Details matches found within a specific feather.
    -   **Role in Architecture**: Provides standardized and rich data structures for reporting correlation findings, enabling consistent handling and persistence of results across different engines and pipelines.
-   **`query_interface.py`**:
    -   **Purpose**: Provides a rich interface for querying and filtering correlation results stored in the SQLite database.
    -   **Key Functionalities**:
        -   `QueryInterface`: Connects to the correlation results database.
        -   Hierarchical retrieval: Supports querying identities, their associated anchors, and the evidence within those anchors.
        -   Filtering: Offers extensive filtering by time range, identity type/value, and semantic properties.
        -   Pagination: Efficiently loads large result sets using `LIMIT` and `OFFSET`.
        -   Aggregate queries: Provides methods for summarizing data (e.g., semantic breakdown, artifact counts).
        -   Time-first organization: Specialized queries (`query_identities_by_anchor_time`) for presenting results grouped by temporal anchors.
    -   **Role in Architecture**: The primary mechanism for users and GUI components to explore and analyze the persisted correlation results, supporting diverse analytical needs.
-   **`database_persistence.py`**:
    -   **Purpose**: Provides robust and efficient mechanisms for persisting correlation results (Identities, Anchors, Evidence, Matches) into an SQLite database.
    -   **Key Functionalities**:
        -   `ResultsDatabase`: Manages database schema creation, migration, and data writing.
        -   `StreamingMatchWriter`: Facilitates incremental writing of `CorrelationMatch`es to disk, enabling constant memory usage for large datasets.
        -   Handles schema migration, data compression, and supports resuming paused executions from the database.
    -   **Role in Architecture**: The primary module for storing all correlation output, making results queryable and persistent. It's crucial for the scalability of both engines, especially the IBCE's streaming mode.

### Integrated Services (`integration/semantic_mapping_integration.py`, `integration/weighted_scoring_integration.py`)

These modules provide external capabilities that are seamlessly integrated into the correlation process, enriching results and assigning confidence levels.

-   **`integration/semantic_mapping_integration.py`**:
    -   **Purpose**: Acts as the integration layer between the core correlation engines and the semantic mapping system (`SemanticMappingManager`).
    -   **Key Functionalities**:
        -   Loads global and case-specific semantic mapping configurations and rules.
        -   Applies semantic mappings to correlation results, enriching them with contextual meaning, categories, and severity levels.
        -   Implements robust error handling with graceful degradation and fallback strategies in case mapping operations fail.
        -   Provides statistics and health checks for the semantic mapping system.
    -   **Role in Architecture**: Directly injected into `IdentityBasedEngineAdapter` (and potentially `TimeWindowScanningEngine`) to apply semantic rules to correlation matches. It allows for dynamic configuration reloading and ensures that semantic insights are integrated into the correlation output.
-   **`integration/weighted_scoring_integration.py`**:
    -   **Purpose**: Acts as the integration layer for the `WeightedScoringEngine` with correlation engines.
    -   **Key Functionalities**:
        -   Manages the loading of global and case-specific weighted scoring configurations.
        -   Applies complex scoring logic to correlation matches based on configured weights for artifact types and other factors.
        -   Performs configuration validation, resolves conflicts between global and case-specific settings, and handles graceful degradation for scoring failures.
    -   **Role in Architecture**: Directly injected into `IdentityBasedEngineAdapter` (and leverages `weighted_scoring.py` for direct use in `TimeWindowScanningEngine`) to calculate and interpret confidence scores for correlation matches. It allows for dynamic adjustment of scoring parameters and ensures scores are meaningful.

### Monitoring & Error Handling (`integration/integration_monitor.py`, `integration/integration_error_handler.py`, `performance_monitor.py`, `performance_analysis.py`, `progress_tracking.py`, `error_handling_coordinator.py`, `cancellation_support.py`, `memory_manager.py`, `correlation_statistics.py`, `parallel_window_processor.py`)

These critical components ensure the reliability, performance, and transparency of the correlation process, offering tools for diagnostics, recovery, and user feedback.

-   **`integration/integration_monitor.py`**:
    -   **Purpose**: A comprehensive monitoring and diagnostics system for integration components.
    -   **Key Functionalities**:
        -   Tracks performance of operations (execution time, memory usage), traces their execution (`OperationTrace`), and monitors system resources (CPU, memory via `psutil`).
        -   Provides diagnostic checks, health monitoring, and troubleshooting recommendations for various integration points.
    -   **Role in Architecture**: Provides critical insights into the performance and reliability of integrated services used by the correlation engines.
-   **`integration/integration_error_handler.py`**:
    -   **Purpose**: Provides a comprehensive error handling system for all integration components.
    -   **Key Functionalities**:
        -   Implements graceful degradation strategies and error recovery mechanisms.
        -   Defines `IntegrationComponent` enum, `ErrorSeverity` enum, and `FallbackStrategy` enum to categorize and manage errors.
        -   Attempts automatic recovery from failures and provides detailed error reporting with full context capture.
    -   **Role in Architecture**: Acts as a safety net for integrations, ensuring the correlation process continues even when sub-components encounter errors.
-   **`performance_monitor.py`**:
    -   **Purpose**: Collects detailed performance metrics during correlation engine execution.
    -   **Key Functionalities**:
        -   `PerformanceMonitor`: Tracks phase-by-phase timing, memory usage (via background `psutil` sampling), and window-level metrics.
        -   `ProcessingPhase` enum: Defines granular phases for precise timing.
        -   `PerformanceReport`, `PhaseMetrics`, `WindowMetrics`: Dataclasses for structuring collected performance data.
        -   `PhaseTimer` context manager: Simplifies timing of code blocks.
    -   **Role in Architecture**: Acts as the data collector for performance metrics, providing the raw data that `performance_analysis.py` consumes to generate insights.
-   **`performance_analysis.py`**:
    -   **Purpose**: Provides advanced analytical capabilities for understanding and optimizing the performance of the correlation engine.
    -   **Key Functionalities**:
        -   `AdvancedPerformanceAnalyzer`: Analyzes `PerformanceReport`s from `performance_monitor.py`.
        -   Algorithm complexity validation: Assesses if `O(N)` performance characteristics are maintained.
        -   Phase-by-phase breakdown: Identifies performance bottlenecks within different processing stages.
        -   Memory efficiency analysis and trend analysis.
        -   Comparison with other engine types (e.g., anchor-based).
        -   Generates comprehensive insights and optimization recommendations.
    -   **Role in Architecture**: Essential for continuous improvement, debugging performance issues, and validating the scalability claims of the correlation engines.
-   **`progress_tracking.py`**:
    -   **Purpose**: Provides a comprehensive system for tracking and reporting the progress of correlation engines.
    -   **Key Functionalities**:
        -   `ProgressTracker`: Manages progress events, time estimation, and cancellation support.
        -   `ProgressEventType` enum: Defines various event types for detailed feedback.
        -   `ProgressListener` interface: Allows external components (e.g., GUI) to subscribe to progress updates.
        -   `TimeEstimator`: Provides estimated completion times and processing rates.
        -   `CancellationToken`: Enables graceful cancellation of long-running operations.
        -   `CorrelationStallMonitor`: Detects and diagnoses processing stalls.
    -   **Role in Architecture**: Ensures transparency and user responsiveness by providing real-time feedback on the correlation process, supporting graceful interruptions, and diagnosing potential issues.
-   **`error_handling_coordinator.py`**:
    -   **Purpose**: Provides a centralized orchestration point for error handling, recovery, and system health monitoring across various engine components.
    -   **Key Functionalities**:
        -   Coordinates responses to critical errors that might impact multiple subsystems.
        -   Manages system-wide health checks and triggers recovery procedures when necessary.
        -   Aggregates error reports from different parts of the engine.
    -   **Role in Architecture**: Acts as a high-level manager for overall system stability, ensuring that localized errors don't lead to catastrophic failures and facilitating a more robust and resilient correlation process.
-   **`cancellation_support.py`**:
    -   **Purpose**: Provides robust and thread-safe mechanisms for managing cancellation of long-running operations within the correlation engine.
    -   **Key Functionalities**:
        -   `EnhancedCancellationManager`: Coordinates cancellation requests, allows registration of cleanup callbacks, and supports graceful shutdown and partial result preservation.
        -   Cancellation tokens/flags: Mechanisms to signal and check for cancellation status across different threads or processes.
    -   **Role in Architecture**: Enhances the resilience and user experience by allowing operations to be stopped gracefully, preventing resource leaks and ensuring data integrity during interruption.
-   **`memory_manager.py`**:
    -   **Purpose**: Proactively manages memory usage during time-window processing or other large-scale operations.
    -   **Key Functionalities**:
        -   `WindowMemoryManager`: Tracks memory usage, estimates requirements for new windows, enforces memory limits, and offers optimization suggestions.
        -   Integrates with `psutil` for real-time system memory monitoring and `gc` for Python garbage collection.
    -   **Role in Architecture**: Crucial for the stability and scalability of the Time-Window Scanning Engine, especially when dealing with very large datasets, by preventing out-of-memory errors and suggesting performance improvements.
-   **`correlation_statistics.py`**:
    -   **Purpose**: Provides comprehensive progress monitoring and statistical analysis specifically for engine execution.
    -   **Key Functionalities**:
        -   Tracks metrics suchs as records processed, matches found, processing times for different phases, memory usage, and error/warning counts.
        -   Generates comprehensive statistical reports that can be used for performance analysis and debugging.
    -   **Role in Architecture**: Offers deep insights into the operational efficiency and behavior of the correlation engines, complementing the more general performance monitoring provided by `performance_monitor.py`.
-   **`parallel_window_processor.py`**:
    -   **Purpose**: Manages the parallel processing of multiple `TimeWindow`s, primarily for the Time-Window Scanning Engine.
    -   **Key Functionalities**:
        -   `ParallelWindowProcessor`: Orchestrates parallel execution using a thread pool.
        -   `WorkerLoadBalancer`: Dynamically balances tasks across workers based on load, performance, and resource utilization.
        -   Resource monitoring: Integrates with `psutil` for CPU/memory monitoring and enables adaptive batch sizing.
    -   **Role in Architecture**: Significantly enhances the performance of the TWSE by leveraging multi-core processors, ensuring efficient utilization of system resources during large-scale scans.

---

## Files in This Directory (`engine/`)

This section provides a detailed breakdown of each Python file within the `Crow-Eye/correlation_engine/engine/` directory, outlining its purpose, key functionalities, and its role within the overall engine architecture.

### `base_engine.py`

-   **Purpose**: Defines the abstract interface (`BaseCorrelationEngine`) that all concrete correlation engine implementations must adhere to. It establishes a contract for engine functionality, ensuring consistency and extensibility.
-   **Key Functionalities**:
    -   `BaseCorrelationEngine`: An Abstract Base Class (ABC) with abstract methods like `execute_wing()`, enforcing a common API.
    -   `EngineMetadata`: A dataclass for providing metadata about each engine (name, description, capabilities).
    -   `FilterConfig`: A dataclass to encapsulate filtering parameters (time periods, identity filters, case sensitivity).
    -   Common utilities: Provides helper methods for parsing timestamps and filtering records that are reusable by different engine implementations.
-   **Role in Architecture**: Acts as the foundational interface, enabling the dual-engine architecture to function interchangeably within the `PipelineExecutor` and `EngineSelector`.

### `cancellation_support.py`

-   **Purpose**: Provides robust and thread-safe mechanisms for managing cancellation of long-running operations within the correlation engine.
-   **Key Functionalities**:
    -   `EnhancedCancellationManager`: Coordinates cancellation requests, allows registration of cleanup callbacks, and supports graceful shutdown and partial result preservation.
    -   Cancellation tokens/flags: Mechanisms to signal and check for cancellation status across different threads or processes.
-   **Role in Architecture**: Enhances the resilience and user experience by allowing operations to be stopped gracefully, preventing resource leaks and ensuring data integrity during interruption.

### `correlation_engine.py`

-   **Purpose**: Implements a concrete correlation strategy, likely an older or alternative Time-Window Scanning approach.
-   **Key Functionalities**:
    -   Contains logic for time-window generation, feather querying, and match creation.
    -   Includes internal mechanisms for managing execution flow and result aggregation.
-   **Architectural Note**: **This module does NOT inherit from `BaseCorrelationEngine`**, which is an architectural inconsistency given the defined dual-engine approach. Its functionality appears to overlap with `time_based_engine.py`, suggesting it might be a legacy implementation or a specific internal component that has not been refactored to conform to the `BaseCorrelationEngine` interface. Care should be taken to understand its exact relationship with `time_based_engine.py` and why it bypasses the standard engine interface.

### `correlation_result.py`

-   **Purpose**: Defines the data structures used to encapsulate the output of correlation engine execution.
-   **Key Functionalities**:
    -   `CorrelationMatch`: A dataclass representing a single identified correlation, including matched records, timestamps, scores, and metadata.
    -   `CorrelationResult`: A comprehensive dataclass summarizing the outcome of a single wing's execution, including lists of `CorrelationMatch`es, execution statistics, and any errors or warnings.
    -   `FeatherMatchResult`: Details matches found within a specific feather.
-   **Role in Architecture**: Provides standardized and rich data structures for reporting correlation findings, enabling consistent handling and persistence of results across different engines and pipelines.

### `correlation_statistics.py`

-   **Purpose**: Provides a system for collecting, aggregating, and reporting detailed statistics about the correlation process.
-   **Key Functionalities**:
    -   Tracks metrics such as records processed, matches found, processing times for different phases, memory usage, and error/warning counts.
    -   Generates comprehensive statistical reports that can be used for performance analysis and debugging.
-   **Role in Architecture**: Offers deep insights into the operational efficiency and behavior of the correlation engines, complementing the more general performance monitoring provided by `performance_monitor.py`.

### `data_structures.py`

-   **Purpose**: Defines fundamental dataclasses and enums used across the correlation engine for representing core concepts and data.
-   **Key Functionalities**:
    -   `Identity`, `Anchor`, `EvidenceRow`: Core dataclasses for identity-based correlation.
    -   `ExtractedValues`: Represents values extracted from feather rows for processing.
    -   `QueryFilters`: General-purpose filters for querying data.
    -   `CorrelationMatch`, `CorrelationResult`: (Also defined in `correlation_result.py`, likely a central definition here or a duplication to be resolved).
    -   `PaginatedResult`, `IdentityWithAnchors`, `AnchorWithEvidence`, `IdentityWithAllEvidence`, `AnchorTimeGroup`, `TimeBasedQueryResult`: Structures for presenting query results.
-   **Role in Architecture**: Serves as a central repository for shared data models, ensuring consistency and type safety across various engine components and integration layers.

### `database_error_handler.py`

-   **Purpose**: Manages robust error handling and recovery specific to database operations within the correlation engine.
-   **Key Functionalities**:
    -   Provides strategies for retrying failed database transactions with exponential backoff.
    -   Manages database connection resilience and graceful degradation for persistent storage.
    -   Logs database-specific errors and attempts automatic recovery to prevent pipeline crashes.
-   **Role in Architecture**: Enhances the reliability of data persistence, a critical aspect of any forensic tool, by isolating database-related failures and attempting to resolve them without interrupting the entire correlation process.

### `database_persistence.py`

-   **Purpose**: Provides robust and efficient mechanisms for persisting correlation results (Identities, Anchors, Evidence, Matches) into an SQLite database.
-   **Key Functionalities**:
    -   `ResultsDatabase`: Manages database schema creation, migration, and data writing.
    -   `StreamingMatchWriter`: Facilitates incremental writing of `CorrelationMatch`es to disk, enabling constant memory usage for large datasets.
    -   Handles schema migration, data compression, and supports resuming paused executions from the database.
-   **Role in Architecture**: The primary module for storing all correlation output, making results queryable and persistent. It's crucial for the scalability of both engines, especially the IBCE's streaming mode.

### `engine_selector.py`

-   **Purpose**: Acts as a factory and registry for all correlation engine implementations.
-   **Key Functionalities**:
    -   `create_engine()`: Instantiates the correct `BaseCorrelationEngine` implementation (TWSE or IBCE) based on the `engine_type` specified in the `PipelineConfig`.
    -   `EngineType` enum: Defines available engine types.
    -   Provides metadata about registered engines.
-   **Role in Architecture**: Decouples the `PipelineExecutor` from direct engine instantiation, making the system flexible and allowing new engine types to be added easily.

### `error_handling_coordinator.py`

-   **Purpose**: Provides a centralized orchestration point for error handling, recovery, and system health monitoring across various engine components.
-   **Key Functionalities**:
    -   Coordinates responses to critical errors that might impact multiple subsystems.
    -   Manages system-wide health checks and triggers recovery procedures when necessary.
    -   Aggregates error reports from different parts of the engine.
-   **Role in Architecture**: Acts as a high-level manager for overall system stability, ensuring that localized errors don't lead to catastrophic failures and facilitating a more robust and resilient correlation process.

### `feather_loader.py`

-   **Purpose**: Provides a unified interface for loading data from feather databases and performing initial identifier extraction and validation.
-   **Key Functionalities**:
    -   `FeatherLoader`: Handles loading feather files with schema detection and optional identifier extraction.
    -   Supports column mapping and data validation against configured rules.
    -   Integrates with `identity_extractor.py` and `identity_validator.py` for pre-processing steps.
-   **Role in Architecture**: Abstracts the complexities of feather data access, providing a consistent stream of processed records to both correlation engines.

### `identifier_correlation_engine.py`

-   **Purpose**: Implements the core in-memory processing logic for the Identity-Based Correlation Engine.
-   **Key Functionalities**:
    -   `IdentifierCorrelationEngine`: Processes `ExtractedValues` from feather rows.
    -   Manages an internal state that builds `Identities`, `Anchors` (temporal activity clusters for identities), and links `EvidenceRows` to them.
    -   Provides methods for querying identity, anchor, and evidence counts, and resetting its state.
-   **Role in Architecture**: The primary component responsible for constructing the identity-centric view of forensic data in memory before it is persisted.

### `identifier_extraction_pipeline.py`

-   **Purpose**: Orchestrates the end-to-end workflow for identifier extraction, correlation, and persistence specifically for the Identity-Based Engine.
-   **Key Functionalities**:
    -   `IdentifierExtractionPipeline`: Wires together `FeatherLoader`, `IdentifierCorrelationEngine`, and `DatabasePersistence`.
    -   Manages the sequence of operations: loading configurations, processing feather tables, extracting identifiers, correlating evidence, and persisting results.
-   **Role in Architecture**: Provides the full operational workflow for the Identity-Based Correlation Engine, acting as a high-level controller for its specialized components.

### `IDENTIFIER_EXTRACTION_README.md`

-   **Purpose**: Provides a detailed, up-to-date overview of the Identifier Extraction and Correlation Engine (which is the Identity-Based Correlation Engine).
-   **Key Content**: Describes architecture, core components (`data_structures.py`, `identity_extractor.py`, `identifier_correlation_engine.py`, `database_persistence.py`, `query_interface.py`, `identifier_extraction_pipeline.py`), database schema, usage examples, in-memory engine state structure, anchor assignment algorithm, column detection patterns, supported timestamp formats, design principles, and implemented requirements.
-   **Role in Architecture**: This document serves as the primary detailed specification for the Identity-Based Correlation Engine and its supporting modules. Its content has been systematically integrated into the relevant sections of this `ENGINE_DOCUMENTATION.md`.

### `identity_based_engine_adapter.py`

-   **Purpose**: The concrete implementation of the `BaseCorrelationEngine` for the Identity-Based strategy. It acts as an adapter, integrating the core `IdentifierCorrelationEngine` with other critical services.
-   **Key Functionalities**:
    -   Wraps `IdentifierCorrelationEngine` and conforms to the `BaseCorrelationEngine` interface.
    -   Integrates `SemanticMappingIntegration`, `WeightedScoringIntegration`, and `ProgressTracker`.
    -   Manages the processing of wings, streaming results (`StreamingMatchWriter`) to the database, and supports resuming paused executions.
    -   Orchestrates the Identity Semantic Phase for final, identity-level semantic analysis.
-   **Role in Architecture**: The high-level entry point for executing Identity-Based correlation, providing a robust and feature-rich implementation of the `ICorrelationEngine` interface.

### `identity_extractor.py`

-   **Purpose**: Responsible for normalizing various types of identifier values (names, paths) and generating consistent identity keys.
-   **Key Functionalities**:
    -   `normalize_name()`: Converts filenames to a standard format (e.g., lowercase).
    -   `normalize_path()`: Standardizes Windows paths (lowercase, consistent separators).
    -   `extract_filename_from_path()`: Extracts the filename component from a full path.
    -   `generate_identity_key()`: Creates consistent keys like `type:normalized_value`.
-   **Role in Architecture**: A fundamental utility for both engines, ensuring that different textual representations of the same entity are consistently mapped for accurate correlation.

### `identity_validator.py`

-   **Purpose**: Validates identity values extracted from forensic artifacts to filter out "noisy" or non-meaningful data.
-   **Key Functionalities**:
    -   `is_valid_identity()`: Checks for boolean strings, pure numeric values, empty/short strings, and absence of alphanumeric characters.
    -   `should_validate_field()`: Supports context-aware validation by allowing specific fields (e.g., 'guid', 'event_id') to bypass strict numeric/boolean checks.
-   **Role in Architecture**: Enhances the quality of correlation by preventing irrelevant or misleading values from being treated as significant identities.

### `memory_manager.py`

-   **Purpose**: Provides proactive memory management during time-window processing or other large-scale operations.
-   **Key Functionalities**:
    -   `WindowMemoryManager`: Tracks memory usage, estimates requirements for new windows, enforces memory limits, and offers optimization suggestions.
    -   Integrates with `psutil` for real-time system memory monitoring and `gc` for Python garbage collection.
-   **Role in Architecture**: Crucial for the stability and scalability of the Time-Window Scanning Engine, especially when dealing with very large datasets, by preventing out-of-memory errors and suggesting performance improvements.

### `parallel_window_processor.py`

-   **Purpose**: Manages the parallel processing of multiple `TimeWindow`s, primarily for the Time-Window Scanning Engine.
-   **Key Functionalities**:
    -   `ParallelWindowProcessor`: Orchestrates parallel execution using a thread pool.
    -   `WorkerLoadBalancer`: Dynamically balances tasks across workers based on load, performance, and resource utilization.
    -   Resource monitoring: Integrates with `psutil` for CPU/memory monitoring and enables adaptive batch sizing.
-   **Role in Architecture**: Significantly enhances the performance of the TWSE by leveraging multi-core processors, ensuring efficient utilization of system resources during large-scale scans.

### `performance_analysis.py`

-   **Purpose**: Provides advanced analytical capabilities for understanding and optimizing the performance of the correlation engine.
-   **Key Functionalities**:
    -   `AdvancedPerformanceAnalyzer`: Analyzes `PerformanceReport`s from `performance_monitor.py`.
    -   Algorithm complexity validation: Assesses if `O(N)` performance characteristics are maintained.
    -   Phase-by-phase breakdown: Identifies performance bottlenecks within different processing stages.
    -   Memory efficiency analysis and trend analysis.
    -   Comparison with other engine types (e.g., anchor-based).
    -   Generates comprehensive insights and optimization recommendations.
-   **Role in Architecture**: Essential for continuous improvement, debugging performance issues, and validating the scalability claims of the correlation engines.

### `performance_monitor.py`

-   **Purpose**: Collects detailed performance metrics during correlation engine execution.
-   **Key Functionalities**:
    -   `PerformanceMonitor`: Tracks phase-by-phase timing, memory usage (via background `psutil` sampling), and window-level metrics.
    -   `ProcessingPhase` enum: Defines granular phases for precise timing.
    -   `PerformanceReport`, `PhaseMetrics`, `WindowMetrics`: Dataclasses for structuring collected performance data.
    -   `PhaseTimer` context manager: Simplifies timing of code blocks.
-   **Role in Architecture**: Acts as the data collector for performance metrics, providing the raw data that `performance_analysis.py` consumes to generate insights.

### `progress_tracking.py`

-   **Purpose**: Provides a comprehensive system for tracking and reporting the progress of correlation engines.
-   **Key Functionalities**:
    -   `ProgressTracker`: Manages progress events, time estimation, and cancellation support.
    -   `ProgressEventType` enum: Defines various event types for detailed feedback.
    -   `ProgressListener` interface: Allows external components (e.g., GUI) to subscribe to progress updates.
    -   `TimeEstimator`: Provides estimated completion times and processing rates.
    -   `CancellationToken`: Enables graceful cancellation of long-running operations.
    -   `CorrelationStallMonitor`: Detects and diagnoses processing stalls.
-   **Role in Architecture**: Ensures transparency and user responsiveness by providing real-time feedback on the correlation process, supporting graceful interruptions, and diagnosing potential issues.

### `query_interface.py`

-   **Purpose**: Provides a rich interface for querying and filtering correlation results stored in the SQLite database.
-   **Key Functionalities**:
    -   `QueryInterface`: Connects to the correlation results database.
    -   Hierarchical retrieval: Supports querying identities, their associated anchors, and the evidence within those anchors.
    -   Filtering: Offers extensive filtering by time range, identity type/value, and semantic properties.
    -   Pagination: Efficiently loads large result sets using `LIMIT` and `OFFSET`.
    -   Aggregate queries: Provides methods for summarizing data (e.g., semantic breakdown, artifact counts).
    -   Time-first organization: Specialized queries (`query_identities_by_anchor_time`) for presenting results grouped by temporal anchors.
-   **Role in Architecture**: The primary mechanism for users and GUI components to explore and analyze the persisted correlation results, supporting diverse analytical needs.

### `time_based_engine.py`

-   **Purpose**: The concrete implementation of the `BaseCorrelationEngine` for the Time-Window Scanning strategy.
-   **Key Functionalities**:
    -   `TimeWindowScanningEngine`: Orchestrates the entire TWSE workflow, including window generation, two-phase correlation, parallel processing, and match generation.
    -   `OptimizedFeatherQuery`, `WindowQueryManager`: Internal classes for efficient, window-centric data retrieval from feather databases.
    -   Integrates `memory_manager.py` and `parallel_window_processor.py` to manage resources and concurrency.
-   **Role in Architecture**: The high-level entry point for executing Time-Window Scanning correlation, providing a robust and feature-rich implementation of the `ICorrelationEngine` interface.

### `timestamp_parser.py`

-   **Purpose**: Provides robust and flexible parsing for a wide array of timestamp formats.
-   **Key Functionalities**:
    -   `TimestampParser`: Handles ISO 8601, Unix epoch, Windows FILETIME, and custom formats.
    -   Includes validation for forensic relevance (e.g., within 1990-2050 range) and graceful error handling for unparseable values.
-   **Role in Architecture**: A critical utility for ensuring all time-related data from diverse sources is accurately normalized, which is fundamental for any temporal correlation.

### `two_phase_correlation.py`

-   **Purpose**: Implements the core logic for the Two-Phase Correlation strategy used by the Time-Window Scanning Engine.
-   **Key Functionalities**:
    -   Defines the two phases: a quick check (`quick_check_window_has_records`) to rapidly identify windows with activity, and a detailed correlation for active windows.
    -   `WindowDataStorage`: Manages intermediate window data, potentially spilling it to disk to maintain memory efficiency for large datasets.
-   **Role in Architecture**: A key performance optimization for the TWSE, significantly reducing processing time by avoiding expensive operations on empty or sparse time windows.

### `weighted_scoring.py`

-   **Purpose**: Provides the core logic for calculating weighted confidence scores for correlation matches.
-   **Key Functionalities**:
    -   `WeightedScoringEngine`: Applies configurable weights (based on artifact type, tier, etc.) to matched evidence to produce a composite score.
    -   Includes logic for breaking down scores and providing human-readable interpretations.
-   **Role in Architecture**: The algorithmic core for assessing the significance and confidence of identified correlations, used directly by the TWSE and integrated into the IBCE via `integration/weighted_scoring_integration.py`.

### `__init__.py`

-   **Purpose**: Marks the `engine/` directory as a Python package and controls what symbols are exposed when the package is imported.
-   **Key Functionalities**:
    -   Typically contains imports to make key classes and functions directly accessible (e.g., `BaseCorrelationEngine`, `EngineSelector`, `EngineType`).
-   **Role in Architecture**: Standard Python package boilerplate, facilitating organized imports and module access.

---

## Files in Other Directories Referenced by Engine Components

This section details Python files located in other directories (`config/`, `integration/`, `pipeline/`) that are directly referenced by or provide critical functionality to the components within the `engine/` directory.

### `config/pipeline_config.py`

-   **Purpose**: Defines the `PipelineConfig` dataclass, which serves as the comprehensive configuration object for an entire correlation analysis pipeline.
-   **Key Functionalities**:
    -   Centralizes all settings required to run a correlation, including case metadata, feather and wing configurations, execution parameters (engine type, time filters, identity filters), semantic mapping and scoring settings, logging verbosity, and output directives.
    -   Supports serialization to and deserialization from JSON, enabling persistent and shareable analysis configurations.
-   **Relationship to Engine**: `PipelineExecutor` loads a `PipelineConfig`, which then dictates which `engine_type` to instantiate via `EngineSelector`, the `FilterConfig` to apply, and how integrated services (semantic mapping, weighted scoring) should be initialized and configured. It is the ultimate source of truth for an engine's operational parameters.

### `integration/semantic_mapping_integration.py`

-   **Purpose**: Acts as the integration layer between the core correlation engines and the semantic mapping system (`SemanticMappingManager`).
-   **Key Functionalities**:
    -   Loads global and case-specific semantic mapping configurations and rules.
    -   Applies semantic mappings to correlation results, enriching them with contextual meaning, categories, and severity levels.
    -   Implements robust error handling with graceful degradation and fallback strategies in case mapping operations fail.
    -   Provides statistics and health checks for the semantic mapping system.
-   **Relationship to Engine**: Directly injected into `IdentityBasedEngineAdapter` (and potentially `TimeWindowScanningEngine`) to apply semantic rules to correlation matches. It allows for dynamic configuration reloading and ensures that semantic insights are integrated into the correlation output.

### `integration/integration_error_handler.py`

-   **Purpose**: Provides a comprehensive error handling system for all integration components (semantic mapping, weighted scoring, progress tracking, etc.).
-   **Key Functionalities**:
    -   Implements graceful degradation strategies and error recovery mechanisms.
    -   Defines `IntegrationComponent` enum, `ErrorSeverity` enum, and `FallbackStrategy` enum to categorize and manage errors.
    -   Attempts automatic recovery from failures and provides detailed error reporting with full context capture.
-   **Relationship to Engine**: Acts as a safety net for integrations used by the engine. When semantic mapping or weighted scoring encounters an error, `IntegrationErrorHandler` is invoked to attempt recovery or apply a fallback strategy, ensuring the correlation process continues without crashing.

### `integration/integration_monitor.py`

-   **Purpose**: A comprehensive monitoring and diagnostics system for integration components.
-   **Key Functionalities**:
    -   Tracks performance of operations (execution time, memory usage), traces their execution (`OperationTrace`), and monitors system resources (CPU, memory via `psutil`).
    -   Provides diagnostic checks, health monitoring, and troubleshooting recommendations for various integration points.
-   **Relationship to Engine**: Used by `SemanticMappingIntegration` and `WeightedScoringIntegration` to monitor their internal operations. This provides critical insights into the performance and reliability of these integrated services as they are utilized by the correlation engines.

### `integration/interfaces.py`

-   **Purpose**: Defines Abstract Base Classes (ABCs) that act as formal interfaces for key integration components.
-   **Key Functionalities**:
    -   `IScoringIntegration`, `ISemanticMappingIntegration`, `IConfigurationObserver`: These ABCs enforce contracts for integration implementations, ensuring a consistent API.
    -   `IntegrationStatistics`: A base dataclass for standardized reporting of integration metrics.
-   **Relationship to Engine**: Enables dependency injection and promotes loose coupling. Core engine components (like `IdentityBasedEngineAdapter` and `TimeWindowScanningEngine`) depend on these abstractions rather than concrete implementations, allowing for flexible and testable integration of services.

### `integration/weighted_scoring_integration.py`

-   **Purpose**: Acts as the integration layer between the core correlation engines and the weighted scoring system (`WeightedScoringEngine`).
-   **Key Functionalities**:
    -   Manages the loading of global and case-specific weighted scoring configurations.
    -   Applies complex scoring logic to correlation matches based on configured weights for artifact types and other factors.
    -   Performs configuration validation, resolves conflicts between global and case-specific settings, and handles graceful degradation for scoring failures.
-   **Relationship to Engine**: Directly injected into `IdentityBasedEngineAdapter` (and leverages `weighted_scoring.py` for direct use in `TimeWindowScanningEngine`) to calculate and interpret confidence scores for correlation matches. It allows for dynamic adjustment of scoring parameters and ensures scores are meaningful.

### `pipeline/pipeline_executor.py`

-   **Purpose**: The central orchestrator responsible for executing entire analysis pipelines.
-   **Key Functionalities**:
    -   Loads `PipelineConfig`, creates the appropriate correlation engine (`BaseCorrelationEngine`) via `EngineSelector`, and manages the end-to-end execution flow.
    -   Coordinates feather creation, wing execution, dependency handling, and report generation.
    -   Integrates shared integration services (semantic mapping, weighted scoring) and supports cancellation.
-   **Relationship to Engine**: The `PipelineExecutor` is the primary client of the correlation engine. It calls the `execute_wing()` method on the chosen engine instance, providing it with the `Wing` and feather paths, and then processes the results returned by the engine.

### `pipeline/pipeline_loader.py`

-   **Purpose**: Designed to load a complete pipeline bundle, including the `PipelineConfig` and all associated `FeatherConfig` and `WingConfig` files.
-   **Key Functionalities**:
    -   Validates dependencies, resolves file paths (absolute and relative), and manages database connections.
    -   Assembles all necessary components into a `PipelineBundle` object, which is then ready for the `PipelineExecutor`.
-   **Relationship to Engine**: Ensures that the `PipelineExecutor` (and by extension, the correlation engine) receives a fully validated and resolved set of configurations and data source references before execution begins. It acts as the preparatory step before any engine logic is invoked.

---

## Common Modification Scenarios

This section outlines common scenarios where you might need to modify the engine's behavior and points to the relevant files.

1.  **Adding a New Correlation Engine Strategy**:
    *   **Files**: `base_engine.py` (define abstract methods if needed), `engine_selector.py` (add new `EngineType` and instantiation logic), new `my_new_engine.py` (implement `BaseCorrelationEngine`), `config/pipeline_config.py` (add `engine_type` option).
2.  **Modifying Correlation Logic within TWSE**:
    *   **Files**: `time_based_engine.py` (main logic), `two_phase_correlation.py` (window processing), `feather_loader.py` (data extraction).
3.  **Modifying Correlation Logic within IBCE**:
    *   **Files**: `identity_based_engine_adapter.py` (main logic), `identifier_correlation_engine.py` (in-memory state), `identity_extractor.py` (normalization), `identity_validator.py` (validation).
4.  **Changing Timestamp Parsing Rules**:
    *   **Files**: `timestamp_parser.py`.
5.  **Adjusting Weighted Scoring Algorithm**:
    *   **Files**: `weighted_scoring.py` (core algorithm), `integration/weighted_scoring_integration.py` (configuration, validation).
6.  **Integrating a New Semantic Mapping Rule**:
    *   **Files**: `integration/semantic_mapping_integration.py` (integration logic), `config/semantic_mapping.py` (manager, rule definitions).
7.  **Enhancing Error Handling/Recovery**:
    *   **Files**: `integration/integration_error_handler.py`, `error_handling_coordinator.py`, `database_error_handler.py`.
8.  **Optimizing Performance (Memory/Speed)**:
    *   **Files**: `memory_manager.py`, `parallel_window_processor.py`, `performance_monitor.py`, `performance_analysis.py`, `database_persistence.py` (streaming aspects).
9.  **Changing Result Persistence or Querying**:
    *   **Files**: `database_persistence.py`, `query_interface.py`, `correlation_result.py` (data structures).

---

## Testing

The engine components are thoroughly tested to ensure correctness, performance, and resilience.

-   **Unit Tests**: Located in `Crow-Eye/correlation_engine/tests/` (e.g., `test_engine_selector.py`, `test_time_based_engine.py`, `test_identity_based_engine.py`).
-   **Integration Tests**: Located in `Crow-Eye/correlation_engine/tests/integration/` (e.g., `test_semantic_mapping_integration.py`, `test_weighted_scoring_integration.py`).
-   **Performance Tests**: Specific benchmarks and profiling tools are used to validate `O(N)` characteristics and identify bottlenecks.

---

## See Also

-   [**Configuration Documentation**](docs/config/CONFIG_DOCUMENTATION.md): Details on `PipelineConfig`, `FeatherConfig`, `WingConfig`, and semantic rules.
-   [**Wings Documentation**](docs/wings/WINGS_DOCUMENTATION.md): How to define and use correlation wings.
-   [**Pipeline Documentation**](docs/pipeline/PIPELINE_DOCUMENTATION.md): How analysis pipelines are constructed and executed.
-   [**GUI Documentation**](docs/gui/GUI_DOCUMENTATION.md): How to interact with the engine via the graphical user interface.
