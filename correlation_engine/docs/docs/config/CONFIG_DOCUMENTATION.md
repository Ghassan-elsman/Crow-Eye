# Config Directory Documentation

## Table of Contents

- [Overview](#overview)
- [Files in This Directory](#files-in-this-directory)
  - [config_manager.py](#config_managerpy)
  - [feather_config.py](#feather_configpy)
  - [wing_config.py](#wing_configpy)
  - [pipeline_config.py](#pipeline_configpy)
  - [semantic_mapping.py](#semantic_mappingpy)
  - [semantic_mapping_discovery.py](#semantic_mapping_discoverypy)
  - [session_state.py](#session_statepy)
  - [identifier_extraction_config.py](#identifier_extraction_configpy)
  - [pipeline_config_manager.py](#pipeline_config_managerpy)
- [Common Modification Scenarios](#common-modification-scenarios)
- [Testing](#testing)
- [See Also](#see-also)

---

## Overview

The **config/** directory manages all configuration files (feathers, wings, pipelines) and semantic mappings. It provides centralized configuration management with save/load capabilities, session persistence, and semantic field mapping across different artifact types.

### Purpose
- Manage feather, wing, and pipeline configurations
- Handle semantic field mappings across artifacts
- Persist GUI session state
- Validate configurations before use
- Provide configuration discovery services
- Manage identifier extraction settings

### How It Fits in the Overall System

The config directory is the **foundation layer** - it has no dependencies on other correlation_engine modules and is used by all other components. It provides:
- **Input**: Configuration files (JSON), user preferences
- **Output**: Configuration objects, validation results, semantic mappings

Used by:
- `engine/correlation_engine.py` - Loads wing configs and semantic mappings
- `pipeline/pipeline_executor.py` - Loads pipeline configs
- `gui/` components - Manages session state and displays configs
- `integration/` - Generates and manages configs

---

## Files in This Directory

### config_manager.py

**Lines**: ~200 lines

**Purpose**: Central configuration management for all config types (feathers, wings, pipelines).

**Key Classes**:

1. **`ConfigManager`**
   - Manages all configuration files
   - Provides save/load operations
   - Organizes configs in directory structure
   - Handles import/export

**Key Methods**:

```python
def __init__(config_directory: str = "configs"):
    """Initialize with config directory"""
    
# Feather Configuration Methods
def save_feather_config(config: FeatherConfig, custom_name: Optional[str] = None) -> str:
    """Save feather configuration to configs/feathers/"""
    
def load_feather_config(config_name: str) -> FeatherConfig:
    """Load feather configuration by name"""
    
def list_feather_configs() -> List[str]:
    """List all available feather configurations"""
    
def delete_feather_config(config_name: str):
    """Delete a feather configuration"""

# Wing Configuration Methods
def save_wing_config(config: WingConfig, custom_name: Optional[str] = None) -> str:
    """Save wing configuration to configs/wings/"""
    
def load_wing_config(config_name: str) -> WingConfig:
    """Load wing configuration by name"""
    
def list_wing_configs() -> List[str]:
    """List all available wing configurations"""
    
def delete_wing_config(config_name: str):
    """Delete a wing configuration"""

# Pipeline Configuration Methods
def save_pipeline_config(config: PipelineConfig, custom_name: Optional[str] = None) -> str:
    """Save pipeline configuration to configs/pipelines/"""
    
def load_pipeline_config(config_name: str) -> PipelineConfig:
    """Load pipeline configuration by name"""
    
def list_pipeline_configs() -> List[str]:
    """List all available pipeline configurations"""
    
def delete_pipeline_config(config_name: str):
    """Delete a pipeline configuration"""

# Utility Methods
def get_config_info(config_type: str, config_name: str) -> Dict:
    """Get summary information about a configuration"""
    
def export_config(config_type: str, config_name: str, export_path: str):
    """Export configuration to specific path"""
    
def import_config(config_type: str, import_path: str, new_name: Optional[str] = None):
    """Import configuration from file"""
```

**Directory Structure Created**:
```
configs/
├── feathers/
│   ├── prefetch.json
│   ├── shimcache.json
│   └── amcache.json
├── wings/
│   ├── execution_proof.json
│   └── user_activity.json
└── pipelines/
    └── full_analysis.json
├── wings/
│   ├── execution_proof.json
│   └── user_activity.json
└── pipelines/
    └── full_analysis.json
```

**Dependencies**: `feather_config.py`, `wing_config.py`, `pipeline_config.py`

**Dependents**: All GUI components, pipeline executor

**Impact**: CRITICAL - Changes affect all configuration operations

---

### feather_config.py

**Purpose**: Feather configuration data model.

**Key Classes**:
- `FeatherConfig`: Configuration for creating a feather

**Fields**:
- `config_name`: Configuration name
- `feather_name`: Feather display name
- `artifact_type`: Type of artifact
- `source_database`: Source data path
- `output_database`: Output feather path
- `column_mappings`: Field mappings
- `transformations`: Data transformations

**Impact**: MEDIUM - Changes affect feather creation

---

### wing_config.py

**Purpose**: Wing configuration data model.

**Key Classes**:
- `WingConfig`: Configuration for a wing
- `WingFeatherReference`: Reference to a feather in a wing

**Fields**:
- `wing_id`, `wing_name`: Identification
- `feathers`: List of feather references
- `time_window_minutes`: Correlation time window
- `minimum_matches`: Minimum required matches
- `target_application`: Application filter
- `anchor_priority`: Anchor selection order

**Impact**: HIGH - Changes affect wing execution

---

### pipeline_config.py

**Purpose**: Pipeline configuration data model.

**Key Classes**:
- `PipelineConfig`: Complete pipeline configuration

**Fields**:
- `pipeline_name`: Pipeline name
- `feather_configs`: List of feather configs
- `wing_configs`: List of wing configs
- `auto_create_feathers`: Auto-create flag
- `auto_run_correlation`: Auto-run flag
- `output_directory`: Output path

**Impact**: HIGH - Changes affect pipeline execution

---

### semantic_mapping.py

**Purpose**: Manage semantic field mappings across artifacts.

**Key Classes**:
- `SemanticMappingManager`: Manages semantic mappings

**Key Methods**:
```python
def add_mapping(semantic_field, artifact_type, actual_field):
    """Add semantic mapping"""
    
def get_mapping(semantic_field, artifact_type):
    """Get actual field name for semantic field"""
    
def apply_mappings(record, artifact_type):
    """Apply semantic mappings to record"""
```

**Semantic Fields**:
- `application` → "app_name", "program", "executable"
- `file_path` → "path", "file", "full_path"
- `timestamp` → "time", "datetime", "event_time"
- `user` → "username", "user_name", "account"

**Dependencies**: None

**Dependents**: `engine/correlation_engine.py`, `engine/results_formatter.py`

**Impact**: MEDIUM - Changes affect field matching

---

### semantic_mapping_discovery.py

**Purpose**: Automatically discover semantic mappings from data.

**Key Classes**:
- `SemanticMappingDiscovery`: Discovers mappings

**Key Methods**:
```python
def discover_mappings(records, artifact_type):
    """Discover semantic mappings from sample records"""
```

**Impact**: LOW - Optional feature

---

### session_state.py

**Purpose**: Persist GUI session state.

**Key Classes**:
- `SessionState`: Session state data
- `PipelineMetadata`: Pipeline metadata
- `FeatherMetadata`: Feather metadata
- `WingsMetadata`: Wings metadata
- `DiscoveryResult`: Configuration discovery results
- `ConnectionStatus`: Database connection status
- `ValidationResult`: Validation results

**Impact**: LOW - Only affects GUI state

---

### identifier_extraction_config.py

**Purpose**: Configuration for identifier extraction.

**Key Classes**:
- `IdentifierExtractionConfig`: Extraction configuration
- `TimestampParsingConfig`: Timestamp parsing configuration
- `WingsConfig`: Wings-specific configuration

**Impact**: LOW - Optional feature

---

### pipeline_config_manager.py

**Purpose**: Pipeline-specific configuration management.

**Key Classes**:
- `PipelineConfigManager`: Manages pipeline configs

**Impact**: MEDIUM - Affects pipeline management

---

### default_mappings/ Subdirectory

**Files**:
- `browser_history.yaml` - Browser artifact mappings
- `event_logs.yaml` - Event log mappings
- `file_system.yaml` - File system artifact mappings
- `prefetch.yaml` - Prefetch mappings
- `registry.yaml` - Registry mappings

**Purpose**: Default semantic mappings for common artifacts

**Impact**: LOW - Provides defaults

---

## Common Modification Scenarios

### Scenario 1: Adding a New Configuration Option

**Files to Modify**:
1. Relevant config model (`feather_config.py`, `wing_config.py`, or `pipeline_config.py`)
2. `config_manager.py` - Update save/load if needed
3. GUI components - Add UI controls

**Steps**:
1. Add field to dataclass
2. Update serialization methods
3. Add GUI controls
4. Test saving and loading

**Impact**: LOW-MEDIUM depending on option

---

### Scenario 2: Modifying Semantic Mappings

**Files to Modify**:
1. `semantic_mapping.py` - Update mapping logic
2. `default_mappings/*.yaml` - Update default mappings
3. Test with various artifacts

**Impact**: MEDIUM - Affects field matching

---

### Scenario 3: Adding New Config Validation Rule

**Files to Modify**:
1. Relevant config model - Add validation method
2. `config_manager.py` - Call validation before save
3. Test with valid and invalid configs

**Impact**: LOW - Only affects validation

---

## Configuration File Formats

### Feather Config
```json
{
  "config_name": "prefetch",
  "feather_name": "Prefetch",
  "artifact_type": "Prefetch",
  "source_database": "source.db",
  "output_database": "prefetch.db",
  "column_mappings": {
    "app_name": "application",
    "last_run": "timestamp"
  }
}
```

### Wing Config
```json
{
  "wing_id": "wing-123",
  "wing_name": "Execution Proof",
  "feathers": [...],
  "time_window_minutes": 5,
  "minimum_matches": 2
}
```

### Pipeline Config
```json
{
  "pipeline_name": "Full Analysis",
  "feather_configs": [...],
  "wing_configs": [...],
  "auto_create_feathers": true,
  "auto_run_correlation": true
}
```

---

## See Also
- [Main Overview](../CORRELATION_ENGINE_OVERVIEW.md)
- [Wings Documentation](../wings/WINGS_DOCUMENTATION.md)
- [Pipeline Documentation](../pipeline/PIPELINE_DOCUMENTATION.md)
