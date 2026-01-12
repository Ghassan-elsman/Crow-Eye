# Artifact Type Registry

## Overview

The Artifact Type Registry provides a centralized, configuration-driven system for managing artifact type definitions in the Crow-Eye Correlation Engine. It eliminates hard-coded artifact type lists throughout the codebase and provides a single source of truth for artifact metadata.

## Purpose

Before the registry, artifact types were hard-coded in multiple locations:
- GUI components (settings dialogs, editors)
- Configuration managers
- Engine validators
- Wing models

This led to:
- Inconsistencies between components
- Difficulty adding new artifact types
- Maintenance burden across 10+ files

The registry solves these problems by:
- Centralizing artifact definitions in a JSON configuration file
- Providing a singleton API for accessing artifact metadata
- Supporting dynamic artifact type registration
- Enabling configuration reload without application restart

## Configuration File

### Location

```
Crow-Eye/correlation_engine/config/artifact_types.json
```

### Format

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "version": "1.0",
  "description": "Centralized artifact type definitions",
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
    }
  ]
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier for the artifact type (used in code) |
| `name` | string | Human-readable display name |
| `description` | string | Detailed description of the artifact type |
| `default_weight` | float | Default weight for weighted scoring (0.0-1.0) |
| `default_tier` | int | Default evidence tier (1-4, where 1 is highest) |
| `anchor_priority` | int | Priority for anchor selection (lower = higher priority) |
| `category` | string | Evidence category (primary_evidence, supporting_evidence, etc.) |
| `forensic_strength` | string | Forensic value (high, medium, low) |

## API Usage

### Getting the Registry

```python
from correlation_engine.config.artifact_type_registry import get_registry

registry = get_registry()
```

### Common Operations

#### Get All Artifact Types

```python
# Get list of all artifact type IDs
artifact_types = registry.get_all_types()
# Returns: ['Logs', 'Prefetch', 'SRUM', ...]
```

#### Get Artifact Details

```python
# Get full artifact definition
artifact = registry.get_artifact('Logs')
if artifact:
    print(f"Name: {artifact.name}")
    print(f"Weight: {artifact.default_weight}")
    print(f"Tier: {artifact.default_tier}")
```

#### Get Default Weight

```python
# Get default weight for an artifact type
weight = registry.get_default_weight('Prefetch')
# Returns: 0.3 (or 0.1 if not found)
```

#### Get Default Tier

```python
# Get default tier for an artifact type
tier = registry.get_default_tier('SRUM')
# Returns: 2 (or 3 if not found)
```

#### Get Anchor Priority List

```python
# Get artifact types sorted by anchor priority
priority_list = registry.get_anchor_priority_list()
# Returns: ['Logs', 'Prefetch', 'SRUM', 'AmCache', ...]
```

#### Get Default Weights Dictionary

```python
# Get all default weights as a dictionary
weights = registry.get_default_weights_dict()
# Returns: {'Logs': 0.4, 'Prefetch': 0.3, ...}
```

#### Validate Artifact Type

```python
# Check if an artifact type is valid
is_valid = registry.is_valid_artifact_type('Logs')
# Returns: True
```

### Advanced Operations

#### Register New Artifact Type

```python
from correlation_engine.config.artifact_type_registry import ArtifactType

new_artifact = ArtifactType(
    id='CustomArtifact',
    name='Custom Artifact',
    description='My custom artifact type',
    default_weight=0.2,
    default_tier=2,
    anchor_priority=13,
    category='supporting_evidence',
    forensic_strength='medium'
)

success = registry.register_artifact(new_artifact)
```

#### Reload Configuration

```python
# Reload artifact types from configuration file
success = registry.reload()
```

#### Filter by Category

```python
# Get all primary evidence artifacts
primary_artifacts = registry.get_artifacts_by_category('primary_evidence')
```

#### Filter by Forensic Strength

```python
# Get all high-strength artifacts
high_strength = registry.get_artifacts_by_forensic_strength('high')
```

## Adding New Artifact Types

### Method 1: Edit Configuration File

1. Open `Crow-Eye/correlation_engine/config/artifact_types.json`
2. Add a new entry to the `artifact_types` array:

```json
{
  "id": "NewArtifact",
  "name": "New Artifact Type",
  "description": "Description of the new artifact",
  "default_weight": 0.15,
  "default_tier": 2,
  "anchor_priority": 13,
  "category": "supporting_evidence",
  "forensic_strength": "medium"
}
```

3. Save the file
4. Restart the application or call `registry.reload()`

### Method 2: Programmatic Registration

```python
from correlation_engine.config.artifact_type_registry import get_registry, ArtifactType

registry = get_registry()

new_artifact = ArtifactType(
    id='NewArtifact',
    name='New Artifact Type',
    description='Description of the new artifact',
    default_weight=0.15,
    default_tier=2,
    anchor_priority=13,
    category='supporting_evidence',
    forensic_strength='medium'
)

registry.register_artifact(new_artifact)
```

## Integration with Existing Components

### GUI Components

GUI components should use the registry instead of hard-coded lists:

```python
# OLD WAY (hard-coded)
artifact_types = ["Logs", "Prefetch", "SRUM", "AmCache", ...]

# NEW WAY (using registry)
from correlation_engine.config.artifact_type_registry import get_registry
registry = get_registry()
artifact_types = registry.get_all_types()
```

### Configuration Managers

Configuration managers should use the registry for default values:

```python
# Get default weights from registry
from correlation_engine.config.artifact_type_registry import get_registry
registry = get_registry()
default_weights = registry.get_default_weights_dict()
```

### Engine Validators

Engines should validate artifact types using the registry:

```python
from correlation_engine.config.artifact_type_registry import get_registry
registry = get_registry()

if not registry.is_valid_artifact_type(artifact_type):
    raise ValueError(f"Invalid artifact type: {artifact_type}")
```

## Fallback Behavior

The registry implements multiple fallback strategies:

1. **File Not Found**: Creates default configuration file automatically
2. **Invalid JSON**: Falls back to hard-coded defaults
3. **Missing Fields**: Uses sensible defaults (weight=0.1, tier=3)
4. **Unknown Artifact**: Returns default values instead of failing

This ensures the system remains operational even with configuration issues.

## Performance Considerations

- **Singleton Pattern**: Only one registry instance exists per application
- **Lazy Loading**: Configuration loaded on first access
- **Caching**: Artifact definitions cached in memory
- **Thread-Safe**: Uses locking for thread-safe initialization

## Migration Guide

### For Existing Code

Replace hard-coded artifact type lists with registry calls:

```python
# Before
artifact_types = ["Logs", "Prefetch", "SRUM", "AmCache", "ShimCache", 
                  "Jumplists", "LNK", "MFT", "USN"]

# After
from correlation_engine.config.artifact_type_registry import get_registry
artifact_types = get_registry().get_all_types()
```

Replace hard-coded default weights:

```python
# Before
default_weights = {
    "Logs": 0.4,
    "Prefetch": 0.3,
    "SRUM": 0.2,
    # ...
}

# After
from correlation_engine.config.artifact_type_registry import get_registry
default_weights = get_registry().get_default_weights_dict()
```

Replace hard-coded anchor priorities:

```python
# Before
anchor_priority = ["Logs", "Prefetch", "SRUM", "AmCache", "ShimCache",
                   "Jumplists", "LNK", "MFT", "USN"]

# After
from correlation_engine.config.artifact_type_registry import get_registry
anchor_priority = get_registry().get_anchor_priority_list()
```

## Best Practices

1. **Always use the registry** for artifact type information
2. **Don't hard-code** artifact type lists or metadata
3. **Validate artifact types** before using them
4. **Handle missing artifacts** gracefully with fallback values
5. **Document custom artifacts** in the configuration file
6. **Test configuration changes** before deploying

## Troubleshooting

### Registry Not Loading

**Problem**: Registry returns empty or default values

**Solutions**:
- Check if `artifact_types.json` exists in the correct location
- Verify JSON syntax is valid
- Check file permissions
- Review application logs for error messages

### Custom Artifacts Not Appearing

**Problem**: Newly added artifacts don't show up

**Solutions**:
- Verify JSON syntax in configuration file
- Ensure artifact ID is unique
- Call `registry.reload()` if application is running
- Restart application to force reload

### Performance Issues

**Problem**: Registry access is slow

**Solutions**:
- Registry uses caching, so first access may be slower
- Avoid calling `reload()` frequently
- Consider caching registry results in your component

## Examples

### Complete Example: Adding and Using Custom Artifact

```python
from correlation_engine.config.artifact_type_registry import get_registry, ArtifactType

# Get registry instance
registry = get_registry()

# Create custom artifact
custom_artifact = ArtifactType(
    id='CustomLogs',
    name='Custom Application Logs',
    description='Logs from custom application',
    default_weight=0.35,
    default_tier=1,
    anchor_priority=2,
    category='primary_evidence',
    forensic_strength='high'
)

# Register the artifact
if registry.register_artifact(custom_artifact):
    print("Custom artifact registered successfully")
    
    # Use the artifact
    weight = registry.get_default_weight('CustomLogs')
    print(f"Default weight: {weight}")
    
    # Verify it's in the list
    all_types = registry.get_all_types()
    if 'CustomLogs' in all_types:
        print("Custom artifact is available")
```

## See Also

- [Configuration Documentation](CONFIG_DOCUMENTATION.md)
- [Integration Documentation](../integration/INTEGRATION_DOCUMENTATION.md)
- [Weight Precedence Documentation](WEIGHT_PRECEDENCE.md)
