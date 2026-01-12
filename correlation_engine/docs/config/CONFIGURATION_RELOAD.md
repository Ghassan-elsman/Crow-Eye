# Configuration Reload Without Restart

## Overview

The Crow-Eye Correlation Engine supports live configuration reload, allowing you to update configuration settings without restarting the application. This feature significantly improves workflow efficiency during investigation and development.

## Supported Configuration Changes

The following configuration changes can be applied without restart:

### 1. Weighted Scoring Configuration
- Default weights for artifact types
- Score interpretation thresholds
- Tier definitions
- Validation rules
- Case-specific scoring weights

### 2. Semantic Mapping Configuration
- Global semantic mappings
- Case-specific semantic mappings
- Mapping patterns and rules

### 3. Artifact Type Registry
- New artifact type definitions
- Updated artifact metadata
- Weight and tier defaults

### 4. Progress Tracking Configuration
- Update frequency
- Display options
- Logging preferences

## How Configuration Reload Works

### Architecture

The configuration reload system uses the **Observer Pattern**:

```
Configuration Manager (Subject)
    ↓ notifies
Observers (Integrations, Engines)
    ↓ reload
Updated Configuration
```

### Components

1. **Configuration Manager**: Manages configuration files and notifies observers
2. **Observers**: Integration components that react to configuration changes
3. **Reload Methods**: Each integration implements `reload_configuration()`

### Flow

```
1. User modifies configuration
   ↓
2. User clicks "Apply" in Settings Dialog
   ↓
3. Configuration Manager saves changes
   ↓
4. Configuration Manager notifies observers
   ↓
5. Each observer reloads its configuration
   ↓
6. New configuration is active
```

## Using Configuration Reload

### From Settings Dialog

1. Open Settings Dialog (Tools → Settings)
2. Modify configuration values
3. Click "Apply" button
4. Configuration is saved and reloaded automatically
5. Success message confirms reload

### Programmatically

#### Reload All Configurations

```python
from correlation_engine.config.integrated_configuration_manager import IntegratedConfigurationManager

config_manager = IntegratedConfigurationManager()

# Modify configuration
config_manager.global_config.weighted_scoring.default_weights['Logs'] = 0.5

# Save and notify observers
config_manager._save_global_configuration()
# Observers are automatically notified and reload
```

#### Reload Specific Integration

```python
from correlation_engine.integration.weighted_scoring_integration import WeightedScoringIntegration

scoring_integration = WeightedScoringIntegration(config_manager)

# Reload scoring configuration
success = scoring_integration.reload_configuration()

if success:
    print("Scoring configuration reloaded successfully")
else:
    print("Failed to reload scoring configuration")
```

#### Reload Artifact Type Registry

```python
from correlation_engine.config.artifact_type_registry import get_registry

registry = get_registry()

# Modify artifact_types.json file
# Then reload:
success = registry.reload()

if success:
    print("Artifact type registry reloaded successfully")
else:
    print("Failed to reload artifact type registry")
```

## Implementing Configuration Observers

### Creating an Observer

To make a component react to configuration changes, implement the observer pattern:

```python
from correlation_engine.config.integrated_configuration_manager import IntegratedConfigurationManager

class MyComponent:
    def __init__(self, config_manager: IntegratedConfigurationManager):
        self.config_manager = config_manager
        
        # Register as observer
        self.config_manager.register_observer(self._on_config_changed)
    
    def _on_config_changed(self, old_config, new_config):
        """
        Called when configuration changes.
        
        Args:
            old_config: Previous configuration (may be None)
            new_config: New configuration
        """
        print("Configuration changed, reloading...")
        
        # Reload your component's configuration
        self.reload_configuration()
    
    def reload_configuration(self):
        """Reload configuration from config manager"""
        # Implement your reload logic
        pass
    
    def cleanup(self):
        """Unregister observer when component is destroyed"""
        self.config_manager.unregister_observer(self._on_config_changed)
```

### Observer Best Practices

1. **Handle Errors Gracefully**: Don't let reload failures crash the observer
2. **Preserve State**: Keep statistics and runtime state during reload
3. **Log Actions**: Log reload success/failure for debugging
4. **Be Fast**: Reload should be quick to avoid blocking
5. **Unregister on Cleanup**: Remove observers when components are destroyed

### Example: Integration Observer

```python
from correlation_engine.integration.interfaces import IScoringIntegration, IntegrationStatistics

class MyScoringIntegration(IScoringIntegration):
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.stats = IntegrationStatistics()
        
        # Register as observer
        self.config_manager.register_observer(self._on_config_changed)
        
        # Load initial configuration
        self._load_configuration()
    
    def _on_config_changed(self, old_config, new_config):
        """React to configuration changes"""
        try:
            # Reload configuration
            self.reload_configuration()
            print("Scoring configuration reloaded successfully")
        except Exception as e:
            print(f"Failed to reload scoring configuration: {e}")
    
    def reload_configuration(self) -> bool:
        """Reload configuration from config manager"""
        try:
            # Preserve statistics
            preserved_stats = self.stats
            
            # Reload configuration
            self._load_configuration()
            
            # Restore statistics
            self.stats = preserved_stats
            
            return True
        except Exception as e:
            print(f"Reload failed: {e}")
            return False
    
    def _load_configuration(self):
        """Load configuration from config manager"""
        config = self.config_manager.get_weighted_scoring_config()
        # Process configuration...
```

## Configuration Reload Scenarios

### Scenario 1: Adjusting Weights During Investigation

**Situation**: You discover that Prefetch artifacts are more reliable than expected in your current investigation.

**Steps**:
1. Open Settings Dialog
2. Navigate to Weighted Scoring section
3. Increase Prefetch weight from 0.3 to 0.4
4. Click "Apply"
5. Run correlation again with new weights

**Result**: New correlations use updated weight without restart.

### Scenario 2: Adding New Artifact Type

**Situation**: You want to add a new artifact type for custom logs.

**Steps**:
1. Edit `config/artifact_types.json`
2. Add new artifact type definition:
```json
{
  "id": "CustomLogs",
  "name": "Custom Application Logs",
  "default_weight": 0.35,
  "default_tier": 1,
  "anchor_priority": 2,
  "category": "primary_evidence",
  "forensic_strength": "high"
}
```
3. Reload registry:
```python
from correlation_engine.config.artifact_type_registry import get_registry
get_registry().reload()
```
4. New artifact type is available in wing editor

**Result**: New artifact type can be used immediately.

### Scenario 3: Case-Specific Weight Adjustment

**Situation**: Current case requires different weight priorities.

**Steps**:
1. Create case-specific configuration:
```json
// cases/case_123/scoring_weights.json
{
  "default_weights": {
    "Logs": 0.5,
    "Network": 0.4
  }
}
```
2. Load case configuration:
```python
scoring_integration.load_case_specific_scoring_weights('case_123')
```
3. Run correlation

**Result**: Case-specific weights are used automatically.

### Scenario 4: Updating Semantic Mappings

**Situation**: You want to add new semantic mappings for Event IDs.

**Steps**:
1. Edit semantic mappings file
2. Add new mappings
3. Reload semantic mapping integration:
```python
mapping_integration.reload_configuration()
```
4. Run correlation

**Result**: New semantic mappings are applied to results.

## Performance Considerations

### Reload Performance

Configuration reload is designed to be fast:
- **Typical reload time**: < 100ms
- **Impact on running operations**: Minimal (non-blocking)
- **Memory overhead**: Negligible

### Optimization Strategies

1. **Debouncing**: Rapid configuration changes are debounced
2. **Caching**: Registry caches artifact definitions
3. **Async Notifications**: Observer notifications don't block saves
4. **Selective Reload**: Only affected components reload

### Monitoring Reload Performance

```python
import time

start_time = time.time()
success = integration.reload_configuration()
elapsed = time.time() - start_time

print(f"Reload took {elapsed*1000:.2f}ms")
```

## Error Handling

### Reload Failures

Configuration reload is designed to be resilient:

1. **Invalid Configuration**: Falls back to previous valid configuration
2. **File Not Found**: Uses default configuration
3. **Observer Errors**: Isolated (one observer failure doesn't affect others)
4. **Partial Reload**: Some components may reload successfully even if others fail

### Error Recovery

```python
def safe_reload():
    """Safely reload configuration with error handling"""
    try:
        success = integration.reload_configuration()
        
        if success:
            print("Configuration reloaded successfully")
        else:
            print("Reload failed, using previous configuration")
            
    except Exception as e:
        print(f"Reload error: {e}")
        print("Continuing with previous configuration")
```

### Logging Reload Events

Enable debug logging to monitor reload events:

```python
import logging

# Enable debug logging for configuration
logging.getLogger('correlation_engine.config').setLevel(logging.DEBUG)
logging.getLogger('correlation_engine.integration').setLevel(logging.DEBUG)

# Reload will now log detailed information
integration.reload_configuration()
```

## Limitations

### What Cannot Be Reloaded

Some changes still require application restart:

1. **Database Schema Changes**: Require restart and migration
2. **Core Engine Architecture**: Engine selection and initialization
3. **Plugin Loading**: New plugins require restart
4. **System-Level Settings**: Memory limits, thread pools, etc.

### Workarounds

For changes that require restart:
1. Save your work
2. Close application
3. Make changes
4. Restart application

## Testing Configuration Reload

### Unit Test Example

```python
def test_configuration_reload():
    """Test that configuration reload works correctly"""
    # Create integration
    integration = WeightedScoringIntegration(config_manager)
    
    # Get initial weight
    initial_config = integration.get_scoring_configuration()
    initial_weight = initial_config.default_weights['Logs']
    
    # Modify configuration
    config_manager.global_config.weighted_scoring.default_weights['Logs'] = 0.5
    config_manager._save_global_configuration()
    
    # Reload integration
    success = integration.reload_configuration()
    assert success
    
    # Verify new weight is used
    new_config = integration.get_scoring_configuration()
    new_weight = new_config.default_weights['Logs']
    assert new_weight == 0.5
    assert new_weight != initial_weight
```

### Integration Test Example

```python
def test_end_to_end_reload():
    """Test configuration reload in complete workflow"""
    # Setup
    engine = create_engine_with_integrations()
    
    # Run correlation with initial config
    results1 = engine.correlate(wing_config)
    score1 = results1['score']
    
    # Modify configuration
    modify_weights({'Logs': 0.6})
    
    # Reload
    engine.scoring_integration.reload_configuration()
    
    # Run correlation again
    results2 = engine.correlate(wing_config)
    score2 = results2['score']
    
    # Verify scores are different (new weights applied)
    assert score2 != score1
```

## Best Practices

1. **Test Configuration Changes**: Test in development before applying to production
2. **Document Changes**: Keep notes on why configuration was changed
3. **Monitor Impact**: Check that reload had desired effect
4. **Use Version Control**: Track configuration file changes
5. **Backup Configurations**: Keep backups before major changes
6. **Gradual Changes**: Make incremental changes rather than large overhauls
7. **Verify Reload Success**: Check logs to confirm reload succeeded

## Troubleshooting

### Configuration Not Reloading

**Problem**: Changes don't take effect after reload

**Solutions**:
1. Check if reload was successful (check return value)
2. Verify configuration file was saved correctly
3. Check logs for error messages
4. Ensure observers are registered
5. Try explicit reload call

### Observers Not Notified

**Problem**: Observers don't receive configuration change notifications

**Solutions**:
1. Verify observer is registered: `config_manager.change_listeners`
2. Check observer callback signature matches expected format
3. Ensure configuration save triggers notification
4. Check for exceptions in observer callbacks

### Performance Degradation

**Problem**: Reload is slow or impacts performance

**Solutions**:
1. Check for expensive operations in observer callbacks
2. Ensure reload methods are optimized
3. Consider debouncing rapid configuration changes
4. Profile reload operations to identify bottlenecks

## See Also

- [Configuration Documentation](CONFIG_DOCUMENTATION.md)
- [Integration Interfaces](../integration/INTEGRATION_INTERFACES.md)
- [Weight Precedence](WEIGHT_PRECEDENCE.md)
- [Artifact Type Registry](ARTIFACT_TYPE_REGISTRY.md)
