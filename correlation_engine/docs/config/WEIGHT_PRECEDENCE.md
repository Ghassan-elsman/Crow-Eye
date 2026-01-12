# Weight Precedence in Crow-Eye Correlation Engine

## Overview

The Crow-Eye Correlation Engine uses a hierarchical weight precedence system to determine which weight value to use for each feather during weighted scoring. This system ensures that more specific configurations override more general ones, while providing sensible defaults.

## Precedence Order

The weight precedence follows this strict order (highest to lowest priority):

```
1. Wing-Specific Weight (highest priority)
   ↓
2. Case-Specific Weight
   ↓
3. Global Weight
   ↓
4. Default Fallback Weight (lowest priority)
```

### 1. Wing-Specific Weight

**Priority**: Highest  
**Source**: Wing configuration file or wing editor  
**Condition**: Weight must be explicitly set and > 0

When a weight is explicitly set in a wing configuration, it takes absolute precedence over all other weight sources.

**Example**:
```python
# In wing configuration
feather = {
    'feather_id': 'logs_feather',
    'artifact_type': 'Logs',
    'weight': 0.5  # This weight will be used
}
```

**Use Case**: When you need a specific weight for a particular wing that differs from the standard configuration.

### 2. Case-Specific Weight

**Priority**: Second  
**Source**: Case-specific configuration file  
**Condition**: Case-specific configuration must be loaded and contain weight for the artifact type

Case-specific weights allow you to customize weights for a particular investigation without modifying global settings or individual wings.

**Example**:
```json
// In cases/{case_id}/scoring_weights.json
{
  "default_weights": {
    "Logs": 0.45,
    "Prefetch": 0.35
  }
}
```

**Use Case**: When investigating a specific case where certain artifact types are more or less reliable than usual.

### 3. Global Weight

**Priority**: Third  
**Source**: Global configuration or artifact type registry  
**Condition**: Global configuration must contain weight for the artifact type

Global weights provide system-wide defaults that apply to all wings and cases unless overridden.

**Example**:
```json
// In configs/integrated_config.json
{
  "weighted_scoring": {
    "default_weights": {
      "Logs": 0.4,
      "Prefetch": 0.3,
      "SRUM": 0.2
    }
  }
}
```

**Use Case**: Standard weights that apply across all investigations.

### 4. Default Fallback Weight

**Priority**: Lowest  
**Source**: Hard-coded fallback  
**Value**: 0.1  
**Condition**: Used when no other weight source provides a value

The fallback weight ensures the system always has a weight value, even for unknown or newly added artifact types.

**Use Case**: Graceful degradation when configuration is incomplete or artifact type is not recognized.

## Implementation Details

### Weight Resolution Algorithm

```python
def resolve_weight(feather_spec, artifact_type, case_config, global_config):
    """
    Resolve weight using precedence order.
    
    Returns: (final_weight, weight_source)
    """
    # 1. Check wing-specific weight
    wing_weight = feather_spec.get('weight', 0.0)
    if wing_weight > 0.0:
        return (wing_weight, 'wing')
    
    # 2. Check case-specific weight
    if case_config and artifact_type in case_config.default_weights:
        return (case_config.default_weights[artifact_type], 'case')
    
    # 3. Check global weight
    if artifact_type in global_config.default_weights:
        return (global_config.default_weights[artifact_type], 'global')
    
    # 4. Use default fallback
    return (0.1, 'default')
```

### Logging Weight Decisions

The system logs weight decisions for debugging:

```
Weight precedence for logs_feather (Logs): 0.500 from wing 
  (wing=0.500, case=0.450, global=0.400)
```

This helps you understand which weight source was used and what other options were available.

## Configuration Examples

### Example 1: Wing Override

**Scenario**: You want a specific wing to use different weights than the global configuration.

**Global Configuration**:
```json
{
  "weighted_scoring": {
    "default_weights": {
      "Logs": 0.4,
      "Prefetch": 0.3
    }
  }
}
```

**Wing Configuration**:
```python
wing = Wing(
    wing_id='custom_wing',
    feathers=[
        Feather(
            feather_id='logs',
            artifact_type='Logs',
            weight=0.6  # Override: use 0.6 instead of 0.4
        ),
        Feather(
            feather_id='prefetch',
            artifact_type='Prefetch',
            weight=0.0  # Use global weight (0.3)
        )
    ]
)
```

**Result**:
- Logs feather: weight = 0.6 (from wing)
- Prefetch feather: weight = 0.3 (from global)

### Example 2: Case-Specific Weights

**Scenario**: A specific case requires different weight priorities.

**Global Configuration**:
```json
{
  "weighted_scoring": {
    "default_weights": {
      "Logs": 0.4,
      "Prefetch": 0.3,
      "SRUM": 0.2
    }
  }
}
```

**Case Configuration** (`cases/case_001/scoring_weights.json`):
```json
{
  "default_weights": {
    "Logs": 0.5,
    "SRUM": 0.3
  }
}
```

**Wing Configuration** (no explicit weights):
```python
wing = Wing(
    wing_id='standard_wing',
    feathers=[
        Feather(feather_id='logs', artifact_type='Logs'),
        Feather(feather_id='prefetch', artifact_type='Prefetch'),
        Feather(feather_id='srum', artifact_type='SRUM')
    ]
)
```

**Result** (when case_001 is loaded):
- Logs feather: weight = 0.5 (from case)
- Prefetch feather: weight = 0.3 (from global, no case override)
- SRUM feather: weight = 0.3 (from case)

### Example 3: Complete Precedence Chain

**Scenario**: Demonstrating all precedence levels.

**Global Configuration**:
```json
{
  "weighted_scoring": {
    "default_weights": {
      "Logs": 0.4,
      "Prefetch": 0.3,
      "SRUM": 0.2,
      "AmCache": 0.15
    }
  }
}
```

**Case Configuration**:
```json
{
  "default_weights": {
    "Logs": 0.45,
    "SRUM": 0.25
  }
}
```

**Wing Configuration**:
```python
wing = Wing(
    wing_id='mixed_wing',
    feathers=[
        Feather(feather_id='logs', artifact_type='Logs', weight=0.5),
        Feather(feather_id='prefetch', artifact_type='Prefetch'),
        Feather(feather_id='srum', artifact_type='SRUM'),
        Feather(feather_id='amcache', artifact_type='AmCache'),
        Feather(feather_id='custom', artifact_type='CustomType')
    ]
)
```

**Result**:
- Logs: weight = 0.5 (from wing - highest priority)
- Prefetch: weight = 0.3 (from global - no case or wing override)
- SRUM: weight = 0.25 (from case - no wing override)
- AmCache: weight = 0.15 (from global - no case or wing override)
- CustomType: weight = 0.1 (default fallback - unknown type)

## Best Practices

### 1. Use Global Weights as Defaults

Set reasonable global weights that work for most cases:

```json
{
  "weighted_scoring": {
    "default_weights": {
      "Logs": 0.4,
      "Prefetch": 0.3,
      "SRUM": 0.2
    }
  }
}
```

### 2. Use Case Weights for Investigation-Specific Adjustments

When a specific investigation requires different priorities:

```json
// cases/ransomware_investigation/scoring_weights.json
{
  "default_weights": {
    "Logs": 0.5,      // Logs more important in ransomware cases
    "Prefetch": 0.4,  // Prefetch very important for execution
    "SRUM": 0.15      // SRUM less critical
  }
}
```

### 3. Use Wing Weights for Special-Purpose Wings

When creating a wing for a specific purpose:

```python
# Wing for quick triage (emphasize fast artifacts)
triage_wing = Wing(
    wing_id='triage_wing',
    feathers=[
        Feather(artifact_type='Prefetch', weight=0.5),  # Fast to process
        Feather(artifact_type='Logs', weight=0.4),      # Fast to process
        Feather(artifact_type='MFT', weight=0.05)       # Slow, low priority
    ]
)
```

### 4. Document Weight Decisions

Add comments explaining why specific weights were chosen:

```python
wing = Wing(
    wing_id='lateral_movement_wing',
    feathers=[
        # Network artifacts are critical for lateral movement detection
        Feather(artifact_type='Network', weight=0.6),
        
        # Logs provide authentication context
        Feather(artifact_type='Logs', weight=0.4),
        
        # Use global weights for other artifacts
        Feather(artifact_type='Prefetch'),
        Feather(artifact_type='SRUM')
    ]
)
```

### 5. Avoid Setting Weight to 0 in Wings

Setting weight to 0 in a wing means "use the next precedence level":

```python
# GOOD: Explicit weight
Feather(artifact_type='Logs', weight=0.4)

# GOOD: No weight specified (use case/global/default)
Feather(artifact_type='Logs')

# CONFUSING: Weight set to 0 (same as not specified)
Feather(artifact_type='Logs', weight=0.0)
```

## Troubleshooting

### Problem: Wing Weight Not Being Used

**Symptoms**: Wing-specific weight is ignored

**Possible Causes**:
1. Weight is set to 0 (use explicit value > 0)
2. Weight is not being saved in wing configuration
3. Configuration is being overridden elsewhere

**Solution**:
```python
# Check weight is explicitly set and > 0
feather.weight = 0.5  # Not 0.0

# Verify in logs
# Look for: "Weight precedence for X: Y from wing"
```

### Problem: Case Weight Not Applied

**Symptoms**: Case-specific weights are ignored

**Possible Causes**:
1. Case configuration not loaded
2. Case ID mismatch
3. Wing has explicit weights that override case weights

**Solution**:
```python
# Ensure case is loaded
integration.load_case_specific_scoring_weights(case_id)

# Check logs for:
# "Loaded case-specific scoring configuration for case X"

# Verify case config file exists
# cases/{case_id}/scoring_weights.json
```

### Problem: Unexpected Weight Values

**Symptoms**: Weights don't match any configuration

**Possible Causes**:
1. Multiple configuration sources conflicting
2. Configuration not reloaded after changes
3. Caching issues

**Solution**:
```python
# Reload configuration
integration.reload_configuration()

# Check weight decision logs
# "Weight precedence for X: Y from Z (wing=A, case=B, global=C)"

# Verify configuration files are correct
```

## Debugging Weight Precedence

### Enable Debug Logging

```python
import logging
logging.getLogger('correlation_engine.integration.weighted_scoring_integration').setLevel(logging.DEBUG)
```

### Check Weight Decision Logs

Look for log entries like:

```
DEBUG: Weight precedence for logs_feather (Logs): 0.500 from wing 
       (wing=0.500, case=0.450, global=0.400)
```

This shows:
- Final weight: 0.500
- Source: wing
- Available alternatives: case=0.450, global=0.400

### Verify Configuration Loading

```python
# Check if case config is loaded
if integration.case_specific_config:
    print("Case config loaded")
    print(f"Case weights: {integration.case_specific_config.default_weights}")
else:
    print("No case config loaded")

# Check global config
global_config = integration.get_scoring_configuration()
print(f"Global weights: {global_config.default_weights}")
```

## API Reference

### Getting Effective Weight

```python
from correlation_engine.integration.weighted_scoring_integration import WeightedScoringIntegration

integration = WeightedScoringIntegration(config_manager)

# Load case-specific configuration
integration.load_case_specific_scoring_weights('case_001')

# Get effective configuration (includes case overrides)
effective_config = integration.get_scoring_configuration('case_001')

# Check weight for specific artifact type
weight = effective_config.default_weights.get('Logs', 0.1)
```

### Checking Weight Source

The weight precedence logic is implemented in `_apply_case_specific_weights()`:

```python
# This method is called automatically during scoring
# It applies the precedence logic and logs decisions
wing_config = integration._apply_case_specific_weights(
    wing_config,
    effective_config
)
```

## See Also

- [Artifact Type Registry](ARTIFACT_TYPE_REGISTRY.md)
- [Configuration Documentation](CONFIG_DOCUMENTATION.md)
- [Integration Interfaces](../integration/INTEGRATION_INTERFACES.md)
- [Weighted Scoring Engine](../engine/WEIGHTED_SCORING.md)
