# Pipeline Configuration Manager

## Overview

The Pipeline Configuration Manager is a comprehensive system that transforms the Correlation Engine from a component-based tool into a unified workflow platform. It treats pipelines as complete, self-contained units that automatically load all their dependencies (feathers, wings, databases), provides session persistence to remember the user's working state, and offers an intuitive interface for managing and switching between different correlation workflows.

## Key Features

### 1. Pipeline as Complete Unit
- Pipelines automatically load all referenced feather and wing configurations
- Database connections are established automatically
- All dependencies are validated before loading
- Partial loads are supported with detailed error reporting

### 2. Session Persistence
- Remembers the last used pipeline across application restarts
- Stores user preferences and window geometry
- Automatic recovery from corrupted session files

### 3. Configuration Discovery
- Automatically scans for available pipelines, feathers, and wings
- Validates configurations against schemas
- Provides metadata for each discovered configuration

### 4. Feather Auto-Registration
- Newly created feather databases are automatically registered
- Artifact type detection is integrated from the Feather Creation GUI
- Configurations are generated and saved automatically

### 5. Database Connection Management
- Connection pooling for all feather databases
- Status tracking for each connection
- Graceful handling of connection failures

## Directory Structure

```
<Case>/Correlation/
├── pipelines/          # Pipeline configuration files
│   └── *.json
├── feathers/           # Feather configuration files
│   └── *.json
├── wings/              # Wings configuration files
│   └── *.json
├── databases/          # Feather database files
│   └── *.db
├── results/            # Correlation results
│   └── *.json
└── session.json        # Session state file
```

## Configuration File Formats

### Pipeline Configuration

```json
{
  "config_name": "case21_full_analysis",
  "pipeline_name": "Case 21 Full Analysis",
  "description": "Complete correlation analysis for Case 21",
  "case_name": "Case 21",
  "case_id": "2024-001",
  "investigator": "John Doe",
  
  "feather_configs": [
    "feathers/prefetch_data.json",
    "feathers/browser_history.json",
    "feathers/srum_data.json"
  ],
  
  "wing_configs": [
    "wings/browser_execution_correlation.json",
    "wings/file_access_timeline.json"
  ],
  
  "output_directory": "results",
  "generate_report": true,
  "report_format": "html",
  
  "created_date": "2024-01-15T10:30:00",
  "last_modified": "2024-01-20T14:45:00",
  "last_executed": "2024-01-20T15:00:00",
  "version": "1.0",
  "tags": ["malware", "browser"],
  "notes": "Full analysis pipeline for Case 21"
}
```

### Session State File

```json
{
  "last_pipeline_path": "pipelines/case21_full_analysis.json",
  "last_pipeline_name": "Case 21 Full Analysis",
  "last_opened": "2024-01-20T15:30:00",
  "window_geometry": {
    "x": 100,
    "y": 100,
    "width": 1280,
    "height": 720
  },
  "active_tab_index": 1,
  "preferences": {
    "auto_load_last_pipeline": true,
    "show_load_notifications": true,
    "validate_on_load": true
  }
}
```

### Feather Configuration (Auto-Generated)

```json
{
  "config_name": "prefetch_data_20240120",
  "feather_name": "Prefetch Data",
  "artifact_type": "Prefetch",
  "source_database": "evidence/prefetch.db",
  "source_table": "prefetch_data",
  "selected_columns": ["timestamp", "application", "file_path", "event_data"],
  "column_mapping": {
    "timestamp": "timestamp",
    "application": "application",
    "file_path": "file_path",
    "event_data": "event_data"
  },
  "timestamp_column": "timestamp",
  "timestamp_format": "%Y-%m-%d %H:%M:%S",
  "output_database": "databases/prefetch_data.db",
  "detection_method": "table_name",
  "detection_confidence": "high",
  "auto_generated": true,
  "created_date": "2024-01-20T14:30:00",
  "total_records": 1523,
  "date_range_start": "2024-01-01 08:00:00",
  "date_range_end": "2024-01-20 17:30:00"
}
```

## Usage

### Python API

```python
from pathlib import Path
from correlation_engine.config.pipeline_config_manager import PipelineConfigurationManager

# Initialize manager with case directory
case_dir = Path("cases/case21/Correlation")
manager = PipelineConfigurationManager(case_dir)

# Initialize and auto-load last pipeline
result = manager.initialize()
if result.auto_loaded:
    print(f"Auto-loaded: {result.pipeline_bundle.pipeline_config.pipeline_name}")
    print(f"Feathers: {len(result.pipeline_bundle.feather_configs)}")
    print(f"Wings: {len(result.pipeline_bundle.wing_configs)}")

# Get available pipelines
pipelines = manager.get_available_pipelines()
for pipeline in pipelines:
    print(f"- {pipeline.pipeline_name}")
    print(f"  Feathers: {pipeline.feather_count}, Wings: {pipeline.wing_count}")
    print(f"  Valid: {pipeline.is_valid}")

# Load a specific pipeline
bundle = manager.load_pipeline("pipelines/my_pipeline.json")
print(f"Loaded: {bundle.pipeline_config.pipeline_name}")
print(f"Status: {bundle.load_status.get_summary()}")

# Check connection status
for feather_name, status in bundle.connection_statuses.items():
    if status.is_connected:
        print(f"✓ {feather_name}: {status.record_count} records")
    else:
        print(f"✗ {feather_name}: {status.error_message}")

# Auto-register a new feather
feather_config = manager.auto_register_feather(
    database_path="databases/new_feather.db",
    artifact_type="Prefetch",
    detection_method="table_name",
    confidence="high"
)
print(f"Registered: {feather_config.feather_name}")

# Switch to another pipeline
new_bundle = manager.switch_pipeline("pipelines/another_pipeline.json")

# Refresh configurations
manager.refresh_configurations()
```

### Integration with Crow Eye

```python
from pathlib import Path
from correlation_engine.integration.crow_eye_integration import CrowEyeIntegration

# When a case is opened in Crow Eye
case_path = Path("cases/case21")

# Initialize correlation directory structure
CrowEyeIntegration.initialize_case_correlation(case_path)

# Get configuration manager for the case
manager = CrowEyeIntegration.on_case_opened(case_path)

# Validate case structure
is_valid, error = CrowEyeIntegration.validate_case_structure(case_path)
if not is_valid:
    print(f"Invalid case structure: {error}")
```

### Feather Auto-Registration

```python
# In Feather Creation GUI
from correlation_engine.pipeline.feather_auto_registration import FeatherAutoRegistrationService

# Initialize service
case_dir = Path("cases/case21/Correlation")
auto_reg_service = FeatherAutoRegistrationService(case_dir)

# Set in feather builder
feather_builder.set_auto_registration_service(auto_reg_service)

# After successful import, auto-registration happens automatically
# The feather is registered with detected artifact type
```

## Error Handling

The system provides comprehensive error handling with user-friendly messages:

### Missing Configuration
```python
from correlation_engine.pipeline.error_handler import ErrorHandler

error = ErrorHandler.handle_missing_config(
    "pipelines/missing.json",
    "pipeline"
)
print(error.user_message)
# "The pipeline configuration could not be found. Would you like to select a different one?"
```

### Partial Load
```python
error = ErrorHandler.handle_partial_load(load_status)
print(error.user_message)
# "Some components could not be loaded (2 feather(s)). Continue with available components?"
```

### Connection Failure
```python
error = ErrorHandler.handle_connection_failure("Prefetch Data", exception)
print(error.user_message)
# "Could not connect to Prefetch Data database. Skip this feather and continue?"
```

## Path Resolution

The system handles both relative and absolute paths, and works across Windows and Unix:

```python
from pathlib import Path
from correlation_engine.pipeline.path_resolver import PathResolver

# Initialize resolver
case_dir = Path("cases/case21/Correlation")
resolver = PathResolver(case_dir)

# Resolve relative path
abs_path = resolver.resolve_relative_path("feathers/prefetch.json")
# Returns: /full/path/to/cases/case21/Correlation/feathers/prefetch.json

# Make path relative
rel_path = resolver.make_relative_path("/full/path/to/cases/case21/Correlation/feathers/prefetch.json")
# Returns: feathers/prefetch.json

# Validate path
is_valid, error = resolver.validate_path(
    "databases/feather.db",
    must_exist=True,
    must_be_file=True
)

# Resolve configuration reference
config_path = resolver.resolve_config_reference("prefetch.json", "feather")
# Returns: /full/path/to/cases/case21/Correlation/feathers/prefetch.json
```

## Troubleshooting

### Session State Issues

**Problem**: Auto-load fails with corrupted session error

**Solution**: The system automatically backs up corrupted session files to `session.json.corrupted`. Delete the corrupted file and restart:
```python
manager.session_manager.clear_session()
```

### Missing Configurations

**Problem**: Pipeline references configurations that don't exist

**Solution**: The system validates all dependencies before loading. Check the validation errors:
```python
validation = manager.pipeline_loader.validate_pipeline_dependencies(pipeline_config)
for error in validation.errors:
    print(error)
```

### Database Connection Failures

**Problem**: Cannot connect to feather database

**Solution**: Check connection status and test database accessibility:
```python
# Test database
is_accessible = manager.pipeline_loader.db_manager.test_connection("databases/feather.db")

# Get connection status
statuses = manager.pipeline_loader.db_manager.get_connection_status()
for name, status in statuses.items():
    if not status.is_connected:
        print(f"{name}: {status.error_message}")
```

### Partial Pipeline Loads

**Problem**: Pipeline loads but some components are missing

**Solution**: Check the load status for details:
```python
bundle = manager.load_pipeline("pipelines/my_pipeline.json")
if bundle.load_status.is_partial_load():
    print(bundle.load_status.get_summary())
    if bundle.load_status.partial_load_info:
        print("Failed feathers:", bundle.load_status.partial_load_info.feathers_failed)
        print("Failed wings:", bundle.load_status.partial_load_info.wings_failed)
```

### Discovery Issues

**Problem**: Configurations not appearing in available list

**Solution**: Refresh discovery and check for validation errors:
```python
manager.refresh_configurations()
discovery = manager.get_discovery_result()

for pipeline in discovery.pipelines:
    if not pipeline.is_valid:
        print(f"{pipeline.pipeline_name}: {pipeline.validation_errors}")
```

## Best Practices

### 1. Use Relative Paths in Configurations
Always use relative paths in pipeline configurations for portability:
```json
{
  "feather_configs": [
    "feathers/prefetch.json",  // Good
    "C:/cases/case21/Correlation/feathers/prefetch.json"  // Bad
  ]
}
```

### 2. Validate Before Loading
Always validate pipelines before attempting to load:
```python
validation = manager.pipeline_loader.validate_pipeline_dependencies(pipeline_config)
if not validation.is_valid:
    for error in validation.errors:
        print(f"Error: {error}")
    return
```

### 3. Handle Partial Loads Gracefully
Check load status and handle partial loads appropriately:
```python
bundle = manager.load_pipeline(pipeline_path)
if not bundle.load_status.is_complete:
    # Decide whether to continue or abort
    if bundle.load_status.feathers_loaded == 0:
        print("No feathers loaded, aborting")
        return
    else:
        print(f"Continuing with {bundle.load_status.feathers_loaded} feathers")
```

### 4. Use Auto-Registration
Let the system automatically register new feathers:
```python
# Set auto-registration service in feather builder
feather_builder.set_auto_registration_service(manager.auto_registration_service)

# Feathers will be automatically registered after creation
```

### 5. Refresh After Changes
Refresh discovery after creating or modifying configurations:
```python
# After creating a new pipeline
manager.create_pipeline(new_pipeline_config)
manager.refresh_configurations()  # Update available pipelines list
```

## Architecture

### Component Hierarchy
```
PipelineConfigurationManager (Core Coordinator)
├── SessionStateManager (Session persistence)
├── ConfigurationDiscoveryService (Config scanning & validation)
├── PipelineLoader (Pipeline loading & dependency resolution)
│   └── DatabaseConnectionManager (Database connections)
└── FeatherAutoRegistrationService (Auto-registration)
```

### Data Flow
```
1. Initialization
   └─> Load Session → Discover Configs → Auto-load Pipeline

2. Pipeline Loading
   └─> Validate → Resolve Paths → Load Configs → Connect DBs

3. Feather Creation
   └─> Detect Type → Generate Config → Save → Refresh Discovery

4. Pipeline Switching
   └─> Unload Current → Load New → Update Session
```

## API Reference

### PipelineConfigurationManager

Main coordinator for all configuration operations.

**Methods**:
- `initialize()` - Initialize manager and auto-load last pipeline
- `load_pipeline(pipeline_path)` - Load a specific pipeline
- `switch_pipeline(new_pipeline_path)` - Switch to different pipeline
- `get_available_pipelines()` - Get list of available pipelines
- `get_current_pipeline()` - Get currently loaded pipeline
- `create_pipeline(pipeline_config)` - Create new pipeline
- `auto_register_feather(...)` - Auto-register new feather
- `refresh_configurations()` - Refresh configuration discovery

### SessionStateManager

Manages persistent session state.

**Methods**:
- `load_session()` - Load session from file
- `save_session(state)` - Save session to file
- `get_last_pipeline()` - Get last used pipeline path
- `set_last_pipeline(path, name)` - Set last used pipeline
- `clear_session()` - Clear session state

### ConfigurationDiscoveryService

Discovers and validates configurations.

**Methods**:
- `discover_all()` - Discover all configurations
- `discover_pipelines()` - Discover pipelines
- `discover_feathers()` - Discover feathers
- `discover_wings()` - Discover wings
- `validate_configuration(path, type)` - Validate configuration
- `refresh()` - Refresh discovery cache

### PipelineLoader

Loads complete pipeline bundles.

**Methods**:
- `load_pipeline(pipeline_path)` - Load complete bundle
- `validate_pipeline_dependencies(config)` - Validate dependencies
- `resolve_config_paths(config)` - Resolve paths
- `unload_pipeline(bundle)` - Unload and cleanup

### DatabaseConnectionManager

Manages database connections.

**Methods**:
- `connect_feather(feather_config)` - Connect to database
- `connect_all(feather_configs)` - Connect to all databases
- `disconnect_feather(feather_name)` - Disconnect database
- `disconnect_all()` - Disconnect all databases
- `get_connection_status()` - Get connection statuses
- `test_connection(database_path)` - Test database accessibility

### FeatherAutoRegistrationService

Auto-registers newly created feathers.

**Methods**:
- `register_new_feather(...)` - Register new feather
- `generate_feather_config(...)` - Generate configuration
- `save_feather_config(config)` - Save configuration
- `validate_database(database_path)` - Validate feather database

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review error messages and technical details
3. Validate your configuration files
4. Check the correlation engine logs

## Version History

### Version 1.0 (Current)
- Initial release
- Core pipeline management functionality
- Session persistence
- Configuration discovery
- Feather auto-registration
- Database connection management
- Error handling and recovery
- Path resolution utilities
