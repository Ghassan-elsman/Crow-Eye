# Feather Directory Documentation

## Overview

The **feather/** directory handles data normalization and import from various forensic artifact sources. It transforms raw forensic data (CSV, JSON, databases) into standardized SQLite databases (feathers) that the correlation engine can process.

### Purpose
- Import forensic artifact data from multiple formats
- Normalize data into consistent schema
- Transform timestamps and field names
- Create feather databases with metadata
- Provide GUI for feather creation

### Key Concepts
- **Feather**: A normalized SQLite database containing forensic artifact data
- **Transformer**: Applies column mappings and data transformations
- **Feather Builder**: GUI application for creating feathers

---

## Files in This Directory

### feather_builder.py

**Purpose**: Main entry point for the Feather Builder GUI application.

**Key Classes**:
- `FeatherBuilder`: Main application class

**Key Methods**:
```python
def run():
    """Launch the Feather Builder application"""
```

**Dependencies**: `ui/main_window.py`, PyQt5

**Dependents**: None (entry point)

**Impact**: LOW - Only affects GUI launch

---

### database.py

**Purpose**: Database operations for creating and managing feather databases.

**Key Functions**:
- Create feather database schema
- Insert records with transactions
- Create indexes for performance
- Add metadata table

**Dependencies**: SQLite3

**Dependents**: `transformer.py`, `ui/` components

**Impact**: MEDIUM - Changes affect feather database structure

---

### transformer.py

**Purpose**: Transform source data to feather format with column mappings and normalization.

**Key Classes**:
- `Transformer`: Applies transformations to source data

**Key Methods**:
```python
def transform_records(source_records, column_mappings):
    """Apply column mappings and transformations"""
    
def normalize_timestamp(value):
    """Normalize timestamp to ISO 8601"""
    
def validate_record(record):
    """Validate record meets feather requirements"""
```

**Dependencies**: `database.py`, `timestamp_parser.py`

**Dependents**: `ui/` components

**Impact**: HIGH - Changes affect data transformation

---

### ui/ Subdirectory

**Files**:
- `main_window.py` - Main Feather Builder window
- `csv_tab.py` - CSV import tab
- `database_tab.py` - Database import tab
- `json_tab.py` - JSON import tab
- `data_viewer.py` - Preview imported data
- `progress_widget.py` - Progress display
- `styles.qss` - Qt stylesheet

**Purpose**: GUI components for Feather Builder application

**Impact**: LOW - Changes only affect GUI

---

## Common Modification Scenarios

### Scenario 1: Adding Support for a New Artifact Type

**Files to Modify**:
1. `integration/feather_mappings.py` - Add column mappings
2. `transformer.py` - Add artifact-specific transformations
3. `wings/core/artifact_detector.py` - Add detection logic

**Steps**:
1. Define column mappings for new artifact
2. Add transformation logic if needed
3. Test with sample data
4. Update artifact detector

---

### Scenario 2: Adding New Import Format

**Files to Modify**:
1. Create new tab in `ui/` (e.g., `xml_tab.py`)
2. Add parser for new format
3. Update `ui/main_window.py` to include new tab

**Impact**: LOW - Extends functionality

---

### Scenario 3: Modifying Database Schema

**Files to Modify**:
1. `database.py` - Update schema creation
2. `transformer.py` - Update record insertion
3. `engine/feather_loader.py` - Update queries

**Impact**: HIGH - Requires migration for existing feathers

---

## See Also
- [Main Overview](../CORRELATION_ENGINE_OVERVIEW.md)
- [Engine Documentation](../engine/ENGINE_DOCUMENTATION.md)
- [Integration Documentation](../integration/INTEGRATION_DOCUMENTATION.md)
