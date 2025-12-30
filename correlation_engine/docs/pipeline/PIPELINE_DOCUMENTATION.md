# Pipeline Directory Documentation

## Overview

The **pipeline/** directory orchestrates complete analysis workflows, including feather creation, wing execution, dependency validation, and report generation.

### Purpose
- Execute complete analysis pipelines
- Validate feather-wing linkages
- Detect circular dependencies
- Manage database connections
- Handle errors gracefully
- Resolve configuration paths

---

## Files in This Directory

### pipeline_executor.py

**Lines**: 671 lines

**Purpose**: Main pipeline execution orchestrator.

**Key Classes**:
- `PipelineExecutor`: Executes complete pipelines

**Key Methods**:
```python
def execute() -> Dict[str, Any]:
    """Execute complete pipeline"""
    # Steps:
    # 1. Create feathers (if configured)
    # 2. Execute wings (if configured)
    # 3. Generate report (if configured)
    
def _create_feathers() -> Dict[str, str]:
    """Create feather databases"""
    
def _execute_wings(feather_paths):
    """Execute all wings in pipeline"""
    
def _validate_feather_wing_linkages(feather_paths) -> Dict:
    """Validate all feather-wing linkages"""
    
def _detect_circular_dependencies(feather_paths) -> Dict:
    """Detect circular dependencies"""
    
def _generate_dependency_graph_dot(feather_paths) -> str:
    """Generate GraphViz dependency graph"""
    
def _wing_config_to_wing(wing_config) -> Wing:
    """Convert WingConfig to Wing with validation"""
```

**Execution Flow**:
1. Load pipeline configuration
2. Validate configuration
3. Create feathers (optional)
4. Validate feather-wing linkages
5. Detect circular dependencies
6. Execute wings sequentially
7. Generate reports (optional)
8. Return summary

**Dependencies**:
- `config/pipeline_config.py`
- `engine/correlation_engine.py`
- `wings/core/wing_model.py`

**Dependents**:
- `gui/execution_control.py`
- `integration/crow_eye_integration.py`

**Impact**: CRITICAL - Changes affect all pipeline operations

**Code Example**:
```python
from correlation_engine.pipeline import PipelineExecutor
from correlation_engine.config import PipelineConfig

# Load pipeline config
config = PipelineConfig.load_from_file("pipeline.json")

# Create executor
executor = PipelineExecutor(config)

# Execute pipeline
summary = executor.execute()

print(f"Feathers created: {summary['feathers_created']}")
print(f"Wings executed: {summary['wings_executed']}")
print(f"Total matches: {summary['total_matches']}")
```

---

### pipeline_loader.py

**Purpose**: Load pipeline configurations from files with dependency resolution.

**Key Classes**:
- `PipelineLoader`: Loads pipeline bundles

**Key Methods**:
```python
def load_pipeline(pipeline_path):
    """Load pipeline with all dependencies"""
    
def resolve_dependencies(pipeline_config):
    """Resolve feather and wing references"""
```

**Dependencies**: `config/pipeline_config.py`

**Dependents**: `pipeline_executor.py`, `gui/` components

**Impact**: MEDIUM - Affects pipeline loading

---

### feather_auto_registration.py

**Purpose**: Automatically register newly created feather databases.

**Key Classes**:
- `FeatherAutoRegistrationService`: Auto-registers feathers

**Key Methods**:
```python
def scan_for_feathers(directory):
    """Scan directory for feather databases"""
    
def register_feather(feather_path):
    """Register feather in configuration"""
```

**Impact**: LOW - Optional feature

---

### discovery_service.py

**Purpose**: Discover available feathers, wings, and pipelines.

**Key Classes**:
- `ConfigurationDiscoveryService`: Discovers configurations

**Key Methods**:
```python
def discover_feathers(directory):
    """Discover feather configurations"""
    
def discover_wings(directory):
    """Discover wing configurations"""
    
def discover_pipelines(directory):
    """Discover pipeline configurations"""
```

**Dependencies**: `config/config_manager.py`

**Dependents**: `gui/` components

**Impact**: LOW - Only affects discovery

---

### database_connection_manager.py

**Purpose**: Manage database connections for feather databases.

**Key Classes**:
- `DatabaseConnectionManager`: Manages DB connections

**Key Methods**:
```python
def get_connection(db_path):
    """Get or create database connection"""
    
def close_all_connections():
    """Close all open connections"""
```

**Impact**: MEDIUM - Affects database access

---

### error_handler.py

**Purpose**: Centralized error handling for pipeline operations.

**Key Classes**:
- `ErrorHandler`: Handles errors gracefully

**Key Methods**:
```python
def handle_error(error, context):
    """Handle error with context"""
    
def log_error(error, context):
    """Log error details"""
```

**Impact**: LOW - Only affects error handling

---

### path_resolver.py

**Purpose**: Resolve relative and absolute configuration paths.

**Key Classes**:
- `PathResolver`: Resolves paths

**Key Methods**:
```python
def resolve_path(path, base_dir):
    """Resolve relative or absolute path"""
    
def validate_path(path):
    """Validate path exists"""
```

**Impact**: MEDIUM - Affects path resolution

---

## Common Modification Scenarios

### Scenario 1: Adding a New Pipeline Stage

**Files to Modify**:
1. `pipeline_executor.py` - Add new stage method
2. `config/pipeline_config.py` - Add configuration option
3. Test with sample pipeline

**Steps**:
1. Add method for new stage (e.g., `_post_process_results()`)
2. Call method in `execute()`
3. Add configuration option if needed
4. Test execution

**Impact**: MEDIUM - Extends pipeline functionality

---

### Scenario 2: Modifying Dependency Resolution

**Files to Modify**:
1. `pipeline_executor.py` - Update `_detect_circular_dependencies()`
2. `pipeline_loader.py` - Update dependency resolution
3. Test with complex pipelines

**Impact**: MEDIUM - Affects dependency validation

---

### Scenario 3: Adding New Validation Check

**Files to Modify**:
1. `pipeline_executor.py` - Add validation method
2. Call in `_validate_feather_wing_linkages()`
3. Test with valid and invalid configs

**Impact**: LOW - Only affects validation

---

## Pipeline Execution Sequence

```
1. Load Pipeline Config
   ↓
2. Validate Configuration
   ↓
3. Create Feathers (optional)
   ├─ For each feather config:
   │  ├─ Load source data
   │  ├─ Apply transformations
   │  └─ Create feather database
   ↓
4. Validate Feather-Wing Linkages
   ├─ Check all feather references exist
   ├─ Validate database paths
   └─ Detect circular dependencies
   ↓
5. Execute Wings
   ├─ For each wing config:
   │  ├─ Convert to Wing object
   │  ├─ Resolve feather paths
   │  ├─ Execute correlation
   │  └─ Collect results
   ↓
6. Generate Reports (optional)
   ├─ Save individual results
   ├─ Generate summary report
   └─ Create dependency graph
   ↓
7. Return Summary
```

---

## See Also
- [Main Overview](../CORRELATION_ENGINE_OVERVIEW.md)
- [Engine Documentation](../engine/ENGINE_DOCUMENTATION.md)
- [Config Documentation](../config/CONFIG_DOCUMENTATION.md)
