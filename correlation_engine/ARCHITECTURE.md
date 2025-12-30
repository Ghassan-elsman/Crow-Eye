# Correlation Engine Architecture

This document describes the architecture of the Crow-Eye Correlation Engine, explaining how the various components work together to process forensic data and produce correlation results.

## Overview

The Correlation Engine is a modular system for correlating forensic artifacts across multiple data sources (feathers). It supports two correlation strategies:
- **Time-Based Correlation**: Uses temporal proximity as the primary correlation factor
- **Identity-Based Correlation**: Groups records by identity (application/file) first, then creates temporal anchors

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACE                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │ Pipeline Builder│  │ Results Viewer  │  │ Identity Results View       │  │
│  │ (pipeline_      │  │ (results_       │  │ (identity_results_view.py)  │  │
│  │  builder.py)    │  │  viewer.py)     │  │                             │  │
│  └────────┬────────┘  └────────┬────────┘  └──────────────┬──────────────┘  │
└───────────┼─────────────────────┼─────────────────────────┼─────────────────┘
            │                     │                         │
            ▼                     │                         │
┌───────────────────────┐         │                         │
│   Pipeline Executor   │         │                         │
│ (pipeline_executor.py)│         │                         │
└───────────┬───────────┘         │                         │
            │                     │                         │
            ▼                     │                         │
┌───────────────────────┐         │                         │
│   Engine Selector     │         │                         │
│ (engine_selector.py)  │         │                         │
└───────────┬───────────┘         │                         │
            │                     │                         │
     ┌──────┴──────┐              │                         │
     ▼             ▼              │                         │
┌─────────┐  ┌──────────────┐     │                         │
│Time-    │  │Identity-Based│     │                         │
│Based    │  │Engine Adapter│     │                         │
│Engine   │  │              │     │                         │
└────┬────┘  └──────┬───────┘     │                         │
     │              │             │                         │
     └──────┬───────┘             │                         │
            ▼                     │                         │
┌───────────────────────┐         │                         │
│  Correlation Result   │◄────────┴─────────────────────────┘
│ (correlation_result.py)│
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│ Database Persistence  │
│(database_persistence.py)│
└───────────────────────┘
            │
            ▼
    ┌───────────────┐
    │ SQLite DB     │
    │ (.db file)    │
    └───────────────┘
```

## Component Details

---

## 1. Pipeline Builder (`gui/pipeline_builder.py`)

**Purpose**: GUI for creating and configuring correlation pipelines.

**Responsibilities**:
- Create/edit pipeline configurations
- Add/remove feathers (data sources)
- Configure wings (correlation rules)
- Set engine type (time-based or identity-based)
- Configure filters (time period, identity patterns)
- Save/load pipeline configurations

**Key Classes**:
- `PipelineBuilderWidget`: Main widget for pipeline configuration

**Outputs**:
- `PipelineConfig` object containing all pipeline settings

---

## 2. Pipeline Executor (`pipeline/pipeline_executor.py`)

**Purpose**: Orchestrates the execution of correlation pipelines.

**Responsibilities**:
- Load pipeline configuration
- Create appropriate correlation engine via `EngineSelector`
- Execute wings (correlation rules) against feathers
- Collect results from engine
- Save results to database via `ResultsDatabase`
- Generate JSON summaries

**Key Classes**:
- `PipelineExecutor`: Main executor class

**Flow**:
```
1. Load PipelineConfig
2. Create FilterConfig from pipeline settings
3. Use EngineSelector to create appropriate engine
4. For each wing:
   a. Resolve feather database paths
   b. Call engine.execute_wing(wing, feather_paths)
   c. Collect CorrelationResult
5. Call _generate_report() to save to database
6. Return execution summary
```

**Key Method**: `_generate_report()`
- Creates `ResultsDatabase` instance
- Calls `db.save_execution()` with all results
- Handles streaming mode results (already in DB)

---

## 3. Engine Selector (`engine/engine_selector.py`)

**Purpose**: Factory for creating correlation engine instances.

**Responsibilities**:
- Create engine based on type string
- Provide metadata about available engines
- Validate engine types

**Key Classes**:
- `EngineType`: Constants for engine types
- `EngineSelector`: Factory class with static methods

**Engine Types**:
| Type | Class | Complexity | Best For |
|------|-------|------------|----------|
| `time_based` | `TimeBasedCorrelationEngine` | O(N²) | Small datasets, detailed analysis |
| `identity_based` | `IdentityBasedEngineAdapter` | O(N log N) | Large datasets, identity tracking |

---

## 4. Base Engine (`engine/base_engine.py`)

**Purpose**: Abstract base class defining the engine interface.

**Key Classes**:
- `EngineMetadata`: Dataclass describing engine capabilities
- `FilterConfig`: Dataclass for filter settings
- `BaseCorrelationEngine`: Abstract base class

**Required Methods** (must be implemented by engines):
```python
@abstractmethod
def execute(self, wing_configs: List[Any]) -> Dict[str, Any]

@abstractmethod
def get_results(self) -> Any

@abstractmethod
def get_statistics(self) -> Dict[str, Any]

@property
@abstractmethod
def metadata(self) -> EngineMetadata
```

**Provided Methods** (common implementations):
- `apply_time_period_filter()`: Filter records by time range
- `_parse_timestamp()`: Parse various timestamp formats

---

## 5. Identity Correlation Engine (`engine/identity_correlation_engine.py`)

**Purpose**: Implements identity-first correlation with temporal anchors.

**Key Classes**:
- `IdentityCorrelationEngine`: Core correlation logic
- `IdentityBasedEngineAdapter`: Adapter implementing `BaseCorrelationEngine`

**Algorithm**:
```
1. Extract identities from all records
   - Use field patterns (name, path, hash)
   - Normalize identity keys
   - Group records by identity

2. For each identity:
   - Sort evidence by timestamp
   - Create temporal anchors (clusters)
   - Classify evidence (primary/secondary/supporting)

3. Convert to CorrelationMatch objects
   - One match per anchor
   - Include feather_records from each source
```

**Streaming Mode** (for large datasets > 5000 anchors):
```
1. Create StreamingMatchWriter
2. Create result record with execution_id=0 (placeholder)
3. Write matches directly to database
4. Later, save_result() updates execution_id
```

**Key Fields for Identity Extraction**:
- Name fields: `executable_name`, `app_name`, `fn_filename`, `Source`, etc.
- Path fields: `app_path`, `Local_Path`, `reconstructed_path`, etc.
- Hash fields: `sha256`, `md5`, `Hashes`, etc.

---

## 6. Correlation Result (`engine/correlation_result.py`)

**Purpose**: Data structures for storing correlation results.

**Key Classes**:

### `CorrelationMatch`
Represents a single correlation match:
```python
@dataclass
class CorrelationMatch:
    match_id: str              # Unique identifier
    timestamp: str             # Central timestamp
    feather_records: Dict      # feather_id -> record data
    match_score: float         # 0.0 to 1.0
    feather_count: int         # Number of feathers matched
    time_spread_seconds: float # Time range of match
    anchor_feather_id: str     # Primary feather
    anchor_artifact_type: str  # Artifact type
    matched_application: str   # Application name
    matched_file_path: str     # File path
    weighted_score: Dict       # Weighted scoring data
    semantic_data: Dict        # Identity metadata
```

### `CorrelationResult`
Represents results from executing a wing:
```python
@dataclass
class CorrelationResult:
    wing_id: str
    wing_name: str
    matches: List[CorrelationMatch]
    total_matches: int
    feathers_processed: int
    feather_metadata: Dict     # feather_id -> metadata
    
    # Streaming support
    streaming_mode: bool
    _result_id: int            # Database result_id (for streaming)
```

**Streaming Mode Methods**:
- `enable_streaming(db_writer, result_id)`: Enable streaming to database
- `add_match(match)`: Add match (streams if enabled)
- `finalize_streaming()`: Flush and close writer

---

## 7. Database Persistence (`engine/database_persistence.py`)

**Purpose**: SQLite storage for correlation results.

**Key Classes**:

### `StreamingMatchWriter`
Efficient batch writer for large result sets:
```python
class StreamingMatchWriter:
    def create_result(...) -> int    # Create result record, return result_id
    def write_match(result_id, match) # Add match to batch
    def flush()                       # Write batch to database
    def update_result_count(...)      # Update final counts
```

### `ResultsDatabase`
Main database interface:
```python
class ResultsDatabase:
    def save_execution(...) -> int   # Save execution + results
    def save_result(execution_id, result)  # Save single result
    def get_execution_results(execution_id) -> List[Dict]
    def get_matches(result_id) -> List[Dict]
    def get_match_details(match_id) -> Dict
```

**Database Schema**:
```sql
-- Pipeline executions
executions (
    execution_id, pipeline_name, execution_time,
    total_wings, total_matches, engine_type, ...
)

-- Wing results
results (
    result_id, execution_id, wing_id, wing_name,
    total_matches, feathers_processed, ...
)

-- Individual matches
matches (
    match_id, result_id, timestamp, match_score,
    feather_count, feather_records (JSON), ...
)

-- Feather metadata
feather_metadata (
    result_id, feather_id, artifact_type, total_records
)
```

**Streaming Mode Handling**:
When `save_result()` detects a streamed result (`_result_id > 0`):
1. Updates existing result record with correct `execution_id`
2. Skips saving matches (already in database)
3. Updates feather metadata

---

## 8. Results Viewer (`gui/results_viewer.py`)

**Purpose**: GUI for viewing and filtering correlation results.

**Key Classes**:
- `ResultsTableWidget`: Table displaying matches
- `MatchDetailViewer`: Detail panel for selected match
- `FilterPanelWidget`: Filter controls
- `DynamicResultsTabWidget`: Tab container for wing results

**Loading Flow**:
```
1. Check for pipeline_summary.json
2. If results truncated or full_results_in_database:
   a. Load from SQLite via _load_results_from_database()
3. Else:
   a. Load from JSON files via CorrelationResult.load_from_file()
4. Create tabs for each wing
5. For identity-based results, use IdentityResultsView
```

---

## 9. Identity Results View (`gui/identity_results_view.py`)

**Purpose**: Specialized view for identity-based correlation results.

**Features**:
- Groups matches by identity
- Shows identity hierarchy (name → anchors → evidence)
- Displays feather contribution per identity
- Timeline visualization

**Key Classes**:
- `IdentityResultsView`: Main widget
- `IdentityTreeWidget`: Tree view of identities
- `AnchorDetailWidget`: Details for selected anchor

---

## Data Flow

### Execution Flow
```
User clicks "Execute" in Pipeline Builder
         │
         ▼
PipelineExecutor.execute()
         │
         ├─► EngineSelector.create_engine(engine_type)
         │            │
         │            ▼
         │   TimeBasedEngine OR IdentityBasedEngineAdapter
         │
         ├─► engine.execute_wing(wing, feather_paths)
         │            │
         │            ▼
         │   CorrelationResult (with matches)
         │   [If streaming: matches written to DB directly]
         │
         ▼
PipelineExecutor._generate_report()
         │
         ├─► ResultsDatabase.save_execution()
         │            │
         │            ▼
         │   save_result() for each result
         │   [If streamed: updates execution_id, skips match save]
         │
         ▼
Returns execution_id + summary
```

### Viewing Flow
```
User opens Results Viewer
         │
         ▼
DynamicResultsTabWidget.load_results(output_dir)
         │
         ├─► Check pipeline_summary.json for execution_id
         │
         ├─► If large/streamed results:
         │   │
         │   ▼
         │   _load_results_from_database(db_path, execution_id)
         │            │
         │            ├─► db.get_execution_results(execution_id)
         │            │
         │            ├─► For each result:
         │            │   db.get_matches(result_id)
         │            │   db.get_match_details(match_id)
         │            │
         │            ▼
         │   Create CorrelationResult objects
         │
         ├─► Else:
         │   │
         │   ▼
         │   CorrelationResult.load_from_file(json_path)
         │
         ▼
Create tabs (IdentityResultsView or standard view)
```

---

## Key Relationships

```
PipelineConfig ──────► PipelineExecutor
                              │
                              ▼
                       EngineSelector
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
    TimeBasedEngine              IdentityBasedEngineAdapter
              │                               │
              └───────────┬───────────────────┘
                          ▼
                  CorrelationResult
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
    In-Memory Matches         StreamingMatchWriter
              │                       │
              └───────────┬───────────┘
                          ▼
                  ResultsDatabase
                          │
                          ▼
                    SQLite DB
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
       ResultsViewer          IdentityResultsView
```

---

## File Summary

| File | Purpose | Key Classes |
|------|---------|-------------|
| `pipeline_builder.py` | GUI for pipeline config | `PipelineBuilderWidget` |
| `pipeline_executor.py` | Execute pipelines | `PipelineExecutor` |
| `engine_selector.py` | Engine factory | `EngineSelector`, `EngineType` |
| `base_engine.py` | Engine interface | `BaseCorrelationEngine`, `FilterConfig` |
| `identity_correlation_engine.py` | Identity correlation | `IdentityCorrelationEngine`, `IdentityBasedEngineAdapter` |
| `time_based_engine.py` | Time correlation | `TimeBasedCorrelationEngine` |
| `correlation_result.py` | Result data structures | `CorrelationResult`, `CorrelationMatch` |
| `database_persistence.py` | SQLite storage | `ResultsDatabase`, `StreamingMatchWriter` |
| `results_viewer.py` | Results GUI | `DynamicResultsTabWidget`, `ResultsTableWidget` |
| `identity_results_view.py` | Identity results GUI | `IdentityResultsView` |

---

## Streaming Mode (Large Datasets)

For datasets with > 5000 anchors, the identity engine uses streaming mode to avoid memory issues:

1. **During Execution**:
   - `StreamingMatchWriter` created
   - Result record created with `execution_id=0` (placeholder)
   - Matches written directly to database in batches
   - `CorrelationResult.matches` list stays empty

2. **During Report Generation**:
   - `save_result()` detects `_result_id > 0`
   - Updates existing result record with correct `execution_id`
   - Skips match saving (already in DB)

3. **During Viewing**:
   - Detects `full_results_in_database: true` in JSON
   - Loads from SQLite instead of JSON
   - Queries matches by `result_id`
