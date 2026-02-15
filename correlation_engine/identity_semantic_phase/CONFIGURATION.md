# Identity Semantic Phase Configuration

## Overview

The Identity Semantic Phase is a performance optimization feature that applies semantic mappings at the identity level after correlation completion, rather than processing each individual record during correlation. This approach significantly reduces processing time and output verbosity for datasets with repeated identities.

## Configuration Option

### `identity_semantic_phase_enabled`

**Type:** `bool`  
**Default:** `True`  
**Location:** `PipelineConfig` class in `correlation_engine/config/pipeline_config.py`

**Description:**  
Controls whether the Identity Semantic Phase is enabled for correlation processing. When enabled, semantic mappings are applied to unique identities in a dedicated final analysis phase after correlation completes. When disabled, the system falls back to per-record semantic mapping during correlation.

**Requirements:** 6.2, 6.3, 6.4, 6.5

## Usage

### Enabling Identity Semantic Phase (Default)

```python
from correlation_engine.config.pipeline_config import PipelineConfig

# Create config with Identity Semantic Phase enabled (default)
config = PipelineConfig(
    config_name="my_config",
    pipeline_name="my_pipeline",
    description="Pipeline with identity-level semantic mapping"
)

# identity_semantic_phase_enabled defaults to True
assert config.identity_semantic_phase_enabled == True
```

### Disabling Identity Semantic Phase

```python
from correlation_engine.config.pipeline_config import PipelineConfig

# Create config with Identity Semantic Phase disabled
config = PipelineConfig(
    config_name="my_config",
    pipeline_name="my_pipeline",
    description="Pipeline with per-record semantic mapping",
    identity_semantic_phase_enabled=False  # Explicitly disable
)

# Verify it's disabled
assert config.identity_semantic_phase_enabled == False
```

### JSON Configuration

The configuration option can be set in JSON configuration files:

```json
{
  "config_name": "my_config",
  "pipeline_name": "my_pipeline",
  "description": "Pipeline configuration",
  "identity_semantic_phase_enabled": true,
  "semantic_mapping_config": {
    "enabled": true
  }
}
```

To disable the Identity Semantic Phase:

```json
{
  "config_name": "my_config",
  "pipeline_name": "my_pipeline",
  "description": "Pipeline configuration",
  "identity_semantic_phase_enabled": false,
  "semantic_mapping_config": {
    "enabled": true
  }
}
```

## Behavior

### When Enabled (Default)

1. **Correlation Phase:** Semantic mappings are NOT applied during correlation processing
2. **Identity Semantic Phase:** After correlation completes:
   - Unique identities are extracted from correlation results
   - Semantic mappings are applied once per unique identity
   - Semantic data is propagated to all records sharing each identity
3. **Output:** Summary statistics only (no per-record messages)
4. **Performance:** Optimized for datasets with repeated identities

### When Disabled

1. **Correlation Phase:** Semantic mappings are applied to each record during correlation
2. **Identity Semantic Phase:** Skipped entirely
3. **Output:** Per-record semantic mapping messages (more verbose)
4. **Performance:** Standard per-record processing

## Backward Compatibility

The `identity_semantic_phase_enabled` configuration option maintains full backward compatibility:

- **Existing configurations without this field:** Automatically default to `True` (enabled)
- **External API:** No changes to existing PipelineConfig API
- **Serialization:** Field is included in JSON serialization/deserialization
- **Engine integration:** Both Identity-Based and Time-Based engines check this flag

## Engine Integration

Both correlation engines check the configuration flag:

```python
# In IdentityBasedEngineAdapter and TimeWindowScanningEngine
phase_enabled = getattr(self.config, 'identity_semantic_phase_enabled', True)

if not phase_enabled:
    # Skip Identity Semantic Phase
    return correlation_results

# Execute Identity Semantic Phase
enhanced_results = self._execute_identity_semantic_phase(
    correlation_results,
    engine_type
)
```

## Fallback Behavior

When the Identity Semantic Phase is disabled or encounters errors:

1. **Configuration disabled:** Falls back to per-record semantic mapping
2. **Phase errors:** Returns original correlation results without semantic enhancement
3. **No semantic integration:** Skips semantic processing entirely
4. **Same external API:** Correlation results maintain the same structure

## Performance Considerations

### When to Enable (Recommended)

- Datasets with many repeated identities (e.g., same file paths, process names)
- Large correlation results (thousands of records)
- Production environments where performance is critical
- Scenarios where output verbosity should be minimized

### When to Disable

- Debugging semantic mapping rules (per-record output is helpful)
- Small datasets where performance difference is negligible
- Testing scenarios where detailed per-record logging is needed
- Compatibility with legacy systems expecting per-record processing

## Examples

### Example 1: Production Pipeline with Identity Semantic Phase

```python
config = PipelineConfig(
    config_name="production_config",
    pipeline_name="production_pipeline",
    description="Production correlation with identity-level semantic mapping",
    identity_semantic_phase_enabled=True,  # Enabled for performance
    semantic_mapping_config={
        "enabled": True,
        "rules_file": "semantic_rules.json"
    },
    debug_mode=False,
    verbose_logging=False
)
```

### Example 2: Debug Pipeline with Per-Record Processing

```python
config = PipelineConfig(
    config_name="debug_config",
    pipeline_name="debug_pipeline",
    description="Debug correlation with per-record semantic mapping",
    identity_semantic_phase_enabled=False,  # Disabled for debugging
    semantic_mapping_config={
        "enabled": True,
        "rules_file": "semantic_rules.json"
    },
    debug_mode=True,
    verbose_logging=True
)
```

### Example 3: Loading from JSON File

```python
# Load configuration from file
config = PipelineConfig.load_from_file("pipeline_config.json")

# Check if Identity Semantic Phase is enabled
if config.identity_semantic_phase_enabled:
    print("Identity Semantic Phase is enabled")
else:
    print("Using per-record semantic mapping")
```

## Related Configuration

The Identity Semantic Phase works in conjunction with other configuration options:

- **`semantic_mapping_config`:** Controls semantic mapping behavior
- **`debug_mode`:** Enables debug output for Identity Semantic Phase
- **`verbose_logging`:** Enables verbose logging for phase execution

## Troubleshooting

### Issue: Identity Semantic Phase not executing

**Solution:** Check that `identity_semantic_phase_enabled` is `True` in your configuration:

```python
print(f"Identity Semantic Phase enabled: {config.identity_semantic_phase_enabled}")
```

### Issue: Want per-record semantic mapping output

**Solution:** Disable the Identity Semantic Phase:

```python
config.identity_semantic_phase_enabled = False
```

### Issue: Old configuration files not working

**Solution:** The system automatically defaults to `True` for backward compatibility. No changes needed to existing configuration files.

## See Also

- [Identity Semantic Phase Design Document](../../.kiro/specs/identity-level-semantic-mapping/design.md)
- [Identity Semantic Phase Requirements](../../.kiro/specs/identity-level-semantic-mapping/requirements.md)
- [Identity Semantic Phase Tasks](../../.kiro/specs/identity-level-semantic-mapping/tasks.md)
- [IdentitySemanticController](identity_semantic_controller.py)
- [PipelineConfig](../config/pipeline_config.py)
