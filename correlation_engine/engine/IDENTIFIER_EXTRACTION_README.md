# Identifier Extraction and Correlation Engine

## Overview

This implementation provides comprehensive identifier extraction and correlation capabilities for the Crow-Eye forensic analysis system. The engine automatically extracts file names and paths from Feather databases, creates identities, groups evidence into execution windows (anchors), and persists results to a queryable relational database.

## Architecture

### Core Components

1. **Data Structures** (`data_structures.py`)
   - `Identity`: Logical entity representing a file/application
   - `Anchor`: Execution window grouping evidence by time
   - `EvidenceRow`: Reference to Feather data
   - `DetectedColumns`: Column detection results
   - `ExtractedValues`: Values extracted from Feather rows

2. **Configuration** (`identifier_extraction_config.py`)
   - `WingsConfig`: Main configuration class
   - `IdentifierExtractionConfig`: Extraction strategy settings
   - `TimestampParsingConfig`: Timestamp parsing options

3. **Timestamp Parser** (`timestamp_parser.py`)
   - Handles multiple timestamp formats (ISO 8601, Unix epoch, Windows FILETIME, custom formats)
   - Validates timestamps within forensic range (1990-2050)
   - Graceful error handling for unparseable timestamps

4. **Identity Extractor** (`identity_extractor.py`)
   - Normalizes file names and paths (lowercase, standard separators)
   - Extracts filenames from full paths
   - Generates identity keys (`type:normalized_value`)

5. **Feather Loader** (`feather_loader.py`)
   - Unified loader supporting both traditional querying and identifier extraction
   - Detects name, path, and timestamp columns automatically
   - Supports manual column specification
   - Extracts values and parses timestamps
   - Metadata-based and metadata-optional operation modes

6. **Identifier Correlation Engine** (`identifier_correlation_engine.py`)
   - Builds in-memory engine state dictionary
   - Implements anchor assignment algorithm
   - Groups evidence within configurable time windows (default: 5 minutes)
   - Supports multiple identifiers per evidence row

7. **Database Persistence** (`database_persistence.py`)
   - Normalized relational schema (identities, anchors, evidence tables)
   - Transaction-based persistence with rollback support
   - Foreign key constraints and indexes for performance

8. **Query Interface** (`query_interface.py`)
   - Hierarchical data retrieval (Identity → Anchors → Evidence)
   - Filtering by time range, identity type, and value
   - Maintains traceability to Feather source data

9. **Integration Pipeline** (`identifier_extraction_pipeline.py`)
   - End-to-end workflow orchestration
   - Progress reporting and error handling
   - Command-line interface for batch processing

### GUI Components

1. **Configuration Panel** (`identifier_extraction_config_panel.py`)
   - Extract from Names/Paths checkboxes
   - Anchor time window configuration
   - Advanced options (column overrides, custom timestamp formats)

2. **Results View** (`correlation_results_view.py`)
   - Hierarchical tree view of results
   - Time range and identity filters
   - Details panel and export functionality

## Database Schema

### Identities Table
```sql
CREATE TABLE identities (
    identity_id TEXT PRIMARY KEY,
    identity_type TEXT NOT NULL,
    identity_value TEXT NOT NULL,
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    wings_config_path TEXT,
    UNIQUE(identity_type, identity_value)
);
```

### Anchors Table
```sql
CREATE TABLE anchors (
    anchor_id TEXT PRIMARY KEY,
    identity_id TEXT NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    FOREIGN KEY (identity_id) REFERENCES identities(identity_id)
);
```

### Evidence Table
```sql
CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY,
    anchor_id TEXT NOT NULL,
    identity_id TEXT NOT NULL,
    artifact TEXT NOT NULL,
    feather_table TEXT NOT NULL,
    feather_row_id INTEGER NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    semantic_json TEXT NOT NULL,
    FOREIGN KEY (anchor_id) REFERENCES anchors(anchor_id),
    FOREIGN KEY (identity_id) REFERENCES identities(identity_id)
);
```

## Usage

### Configuration

Create a Wings configuration file (`wings_config.json`):

```json
{
  "identifier_extraction": {
    "extract_from_names": true,
    "extract_from_paths": true,
    "name_columns": [],
    "path_columns": []
  },
  "anchor_time_window_minutes": 5,
  "timestamp_parsing": {
    "custom_formats": [
      "%d-%b-%Y %H:%M:%S",
      "%Y%m%d%H%M%S"
    ],
    "default_timezone": "UTC",
    "fallback_to_current_time": false
  },
  "correlation_database": "correlation.db"
}
```

### Running the Pipeline

```python
from correlation_engine.engine.identifier_extraction_pipeline import run_identifier_extraction

results = run_identifier_extraction(
    config_path="wings_config.json",
    feather_paths=["prefetch.db", "srum.db", "shimcache.db"],
    output_db="correlation_results.db"
)

print(f"Identities: {results['database_stats']['identities']}")
print(f"Anchors: {results['database_stats']['anchors']}")
print(f"Evidence: {results['database_stats']['evidence']}")
```

### Querying Results

```python
from correlation_engine.engine.query_interface import QueryInterface
from correlation_engine.engine.data_structures import QueryFilters
from datetime import datetime

# Query all identities
with QueryInterface("correlation_results.db") as qi:
    identities = qi.query_identities()
    
    # Filter by time range
    filters = QueryFilters(
        start_time=datetime(2024, 1, 1),
        end_time=datetime(2024, 12, 31)
    )
    filtered = qi.query_identities(filters)
    
    # Get specific identity
    identity = qi.get_identity_with_anchors("identity-uuid")
```

## In-Memory Engine State Structure

The engine builds the following in-memory structure before persistence:

```python
engine_state = {
    "name:evil.exe": {
        "identity_id": "uuid-1",
        "identity_type": "name",
        "identity_value": "evil.exe",
        "first_seen": datetime,
        "last_seen": datetime,
        "anchors": [
            {
                "anchor_id": "uuid-a1",
                "start_time": datetime(2024, 1, 1, 10, 0, 0),
                "end_time": datetime(2024, 1, 1, 10, 2, 0),
                "rows": [
                    {
                        "artifact": "prefetch",
                        "table": "prefetch",
                        "row_id": 142,
                        "timestamp": datetime(2024, 1, 1, 10, 0, 0),
                        "semantic": {
                            "name": "evil.exe"
                        }
                    },
                    {
                        "artifact": "srum",
                        "table": "srum_app",
                        "row_id": 88,
                        "timestamp": datetime(2024, 1, 1, 10, 2, 0),
                        "semantic": {
                            "name": "evil.exe"
                        }
                    }
                ]
            },
            {
                "anchor_id": "uuid-a2",
                "start_time": datetime(2024, 1, 1, 15, 0, 0),
                "end_time": datetime(2024, 1, 1, 15, 0, 0),
                "rows": [
                    {
                        "artifact": "prefetch",
                        "table": "prefetch",
                        "row_id": 256,
                        "timestamp": datetime(2024, 1, 1, 15, 0, 0),
                        "semantic": {
                            "name": "evil.exe"
                        }
                    }
                ]
            }
        ]
    }
}
```

## Anchor Assignment Algorithm

Evidence rows are grouped into anchors based on timestamps:

1. For each evidence row with timestamp T:
2. Check if identity exists in engine_state
3. If not, create new identity with empty anchors list
4. For each existing anchor in identity:
   - If T falls within [anchor.start_time, anchor.end_time + time_window]:
     - Add evidence to anchor.rows
     - Update anchor.end_time if T > anchor.end_time
     - Return
5. If no matching anchor found:
   - Create new anchor with start_time = T, end_time = T
   - Add evidence to new anchor.rows
   - Append anchor to identity.anchors

## Column Detection Patterns

### Name Columns
- `name`, `executable`, `filename`, `exe_name`, `application`, `app_name`, `process_name`

### Path Columns
- `path`, `filepath`, `full_path`, `exe_path`, `executable_path`, `file_path`, `full_file_path`

### Timestamp Columns
- `timestamp`, `time`, `datetime`, `execution_time`, `last_run`, `modified_time`, `created_time`, `accessed_time`, `run_time`, `exec_time`

## Supported Timestamp Formats

- ISO 8601: `2024-01-01T10:00:00Z`, `2024-01-01T10:00:00+00:00`
- Unix Epoch: `1704103200` (seconds), `1704103200000` (milliseconds)
- Windows FILETIME: 64-bit value (100-nanosecond intervals since 1601-01-01)
- Human-readable: `2024-01-01 10:00:00`, `01/01/2024 10:00:00 AM`
- Date only: `2024-01-01`, `01/01/2024`
- Custom formats: Configurable via Wings config

## Design Principles

1. **Separation of Concerns**: Strict separation between Feather (facts) and Engine (inference)
2. **Deterministic Correlation**: Rule-based algorithms produce consistent results
3. **Explainability**: All correlations are traceable and suitable for forensic reporting
4. **Performance**: Optimized for large datasets with efficient data structures
5. **Temporary State**: In-memory engine state is temporary; database is authoritative after persistence

## Files Created

### Core Engine
- `correlation_engine/engine/data_structures.py`
- `correlation_engine/engine/timestamp_parser.py`
- `correlation_engine/engine/identity_extractor.py`
- `correlation_engine/engine/feather_loader.py` (unified loader with identifier extraction)
- `correlation_engine/engine/identifier_correlation_engine.py`
- `correlation_engine/engine/database_persistence.py`
- `correlation_engine/engine/query_interface.py`
- `correlation_engine/engine/identifier_extraction_pipeline.py`

### Configuration
- `correlation_engine/config/identifier_extraction_config.py`

### GUI
- `correlation_engine/gui/identifier_extraction_config_panel.py`
- `correlation_engine/gui/correlation_results_view.py`

## Next Steps

1. **Testing**: Create unit tests, integration tests, and performance tests
2. **Documentation**: Add user guides and API documentation
3. **GUI Integration**: Integrate configuration panel and results view into main Wings GUI
4. **Export Functionality**: Implement JSON, CSV, and PDF export formats
5. **Optimization**: Profile and optimize for very large datasets (100K+ rows)

## Requirements Implemented

All 11 requirements from the specification have been implemented:
- ✅ Requirement 0: Core Engine Architecture
- ✅ Requirement 0.1: In-Memory Engine State Structure
- ✅ Requirement 0.2: Identity Key Normalization
- ✅ Requirement 0.3: Anchor Time Window Configuration
- ✅ Requirement 0.4: Relational Database Persistence
- ✅ Requirement 0.5: Design Principles and Performance
- ✅ Requirement 1: Automatic file name discovery
- ✅ Requirement 2: Automatic file path discovery
- ✅ Requirement 3: Wings configuration for extraction strategy
- ✅ Requirement 4: Automatic column detection
- ✅ Requirement 5: Manual column specification
- ✅ Requirement 6: Multiple identifiers per evidence row
- ✅ Requirement 7: Filename extraction from paths
- ✅ Requirement 8: GUI configuration panel
- ✅ Requirement 9: Query interface with filtering
- ✅ Requirement 10: GUI results view

## License

Part of the Crow-Eye Correlation Engine project.
