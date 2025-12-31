# Wings Directory Documentation

## Overview

The **wings/** directory defines the data models and validation logic for Wing configurations. Wings are correlation rules that specify which feathers to correlate, time windows, filters, and other parameters.

### Purpose
- Define Wing data models
- Validate wing configurations
- Detect artifact types
- Provide GUI for wing creation

### Key Concepts
- **Wing**: A correlation rule configuration
- **FeatherSpec**: Specification for a feather in a wing
- **CorrelationRules**: Parameters for correlation (time window, minimum matches, filters)

---

## Files in This Directory

### core/wing_model.py

**Purpose**: Core data models for Wing configurations.

**Key Classes**:

1. **`Wing`**
   - Complete wing configuration
   - Fields: `wing_id`, `wing_name`, `description`, `proves`, `feathers`, `correlation_rules`, `metadata`
   - Methods: `validate()`, `to_dict()`, `from_dict()`, `save_to_file()`, `load_from_file()`

2. **`FeatherSpec`**
   - Specification for a feather in a wing
   - Fields: `feather_id`, `database_filename`, `artifact_type`, `detection_confidence`

3. **`CorrelationRules`**
   - Correlation parameters
   - Fields: `time_window_minutes`, `minimum_matches`, `target_application`, `anchor_priority`

4. **`WingMetadata`**
   - Wing metadata
   - Fields: `tags`, `case_types`, `confidence_level`, `notes`

**Dependencies**: None (pure data models)

**Dependents**: 
- `engine/correlation_engine.py`
- `config/wing_config.py`
- `pipeline/pipeline_executor.py`
- `gui/` components

**Impact**: CRITICAL - Changes affect all wing operations

**Code Example**:
```python
from correlation_engine.wings.core.wing_model import Wing, FeatherSpec, CorrelationRules

# Create wing
wing = Wing()
wing.wing_name = "Execution Proof"
wing.description = "Correlate execution artifacts"

# Add feathers
wing.feathers.append(FeatherSpec(
    feather_id="prefetch",
    database_filename="prefetch.db",
    artifact_type="Prefetch",
    detection_confidence="high",
    manually_overridden=False
))

# Set correlation rules
wing.correlation_rules.time_window_minutes = 5
wing.correlation_rules.minimum_matches = 2

# Validate and save
is_valid, errors = wing.validate()
if is_valid:
    wing.save_to_file("my_wing.json")
```

---

### core/artifact_detector.py

**Purpose**: Detect artifact types from database schema and metadata.

**Key Classes**:
- `ArtifactDetector`: Detects artifact type from database

**Key Methods**:
```python
def detect_artifact_type(db_path):
    """Detect artifact type from database"""
    # Returns: (artifact_type, confidence, detection_method)
```

**Detection Methods**:
1. Check metadata table
2. Analyze table names
3. Analyze column names
4. Check filename patterns

**Dependencies**: SQLite3

**Dependents**: `ui/` components, `integration/auto_feather_generator.py`

**Impact**: MEDIUM - Affects automatic artifact detection

---

### core/wing_validator.py

**Purpose**: Validate wing configurations for correctness and completeness.

**Key Classes**:
- `WingValidator`: Validates wing configurations

**Key Methods**:
```python
def validate_wing(wing):
    """Validate wing configuration"""
    # Returns: (is_valid, errors, warnings)
```

**Validation Checks**:
- Required fields present
- Time window > 0
- Minimum matches >= 1
- Feather references valid
- Artifact types recognized

**Dependencies**: `wing_model.py`

**Dependents**: `engine/correlation_engine.py`, `gui/` components

**Impact**: MEDIUM - Affects wing validation

---

### ui/ Subdirectory

**Files**:
- `main_window.py` - Main Wings Creator window
- `feather_widget.py` - Feather selection and configuration
- `anchor_priority_widget.py` - Configure anchor priority
- `semantic_mapping_dialog.py` - Edit semantic mappings
- `json_viewer.py` - View wing JSON
- `wings_styles.qss` - Qt stylesheet

**Purpose**: GUI components for Wings Creator application

**Impact**: LOW - Changes only affect GUI

---

## Common Modification Scenarios

### Scenario 1: Adding a New Correlation Rule Parameter

**Files to Modify**:
1. `core/wing_model.py` - Add field to `CorrelationRules`
2. `engine/correlation_engine.py` - Use new parameter
3. `ui/` - Add UI controls for new parameter

**Steps**:
1. Add field to `CorrelationRules` dataclass
2. Update `to_dict()` and `from_dict()` methods
3. Implement logic in correlation engine
4. Add GUI controls
5. Test with sample wings

**Impact**: MEDIUM - Extends wing functionality

---

### Scenario 2: Modifying Wing Validation Logic

**Files to Modify**:
1. `core/wing_validator.py` - Update validation rules
2. `core/wing_model.py` - Update `validate()` method

**Steps**:
1. Identify validation issue
2. Update validation logic
3. Test with valid and invalid wings
4. Update error messages

**Impact**: LOW - Only affects validation

---

### Scenario 3: Adding New Metadata Fields

**Files to Modify**:
1. `core/wing_model.py` - Add fields to `WingMetadata`
2. `ui/` - Add UI controls for new fields

**Steps**:
1. Add fields to `WingMetadata` dataclass
2. Update serialization methods
3. Add GUI controls
4. Test saving and loading

**Impact**: LOW - Extends metadata

---

## Wing Configuration Format

Wings are stored as JSON files with this structure:

```json
{
  "wing_id": "unique-id",
  "wing_name": "Execution Proof",
  "version": "1.0",
  "author": "Investigator",
  "description": "Correlate execution artifacts",
  "proves": "Program execution occurred",
  "feathers": [
    {
      "feather_id": "prefetch",
      "database_filename": "prefetch.db",
      "artifact_type": "Prefetch",
      "detection_confidence": "high"
    }
  ],
  "correlation_rules": {
    "time_window_minutes": 5,
    "minimum_matches": 2,
    "target_application": "",
    "anchor_priority": ["Logs", "Prefetch", "SRUM"]
  },
  "metadata": {
    "tags": ["execution", "proof"],
    "case_types": ["malware", "insider-threat"],
    "confidence_level": "high"
  }
}
```

---

## See Also
- [Main Overview](../CORRELATION_ENGINE_OVERVIEW.md)
- [Engine Documentation](../engine/ENGINE_DOCUMENTATION.md)
- [Config Documentation](../config/CONFIG_DOCUMENTATION.md)
