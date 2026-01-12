# Integration Interfaces

## Overview

The Integration Interfaces provide abstract base classes (ABCs) that define contracts for integration components in the Crow-Eye Correlation Engine. These interfaces enable:

- **Dependency Injection**: Engines depend on abstractions, not concrete implementations
- **Testing**: Easy creation of mock implementations for unit testing
- **Extensibility**: Custom integrations can be created by implementing interfaces
- **Decoupling**: High-level modules don't depend on low-level implementation details

## Available Interfaces

### IScoringIntegration

Interface for weighted scoring integration components.

**Location**: `correlation_engine/integration/interfaces.py`

**Purpose**: Defines the contract for scoring integration implementations, enabling engines to calculate weighted scores without depending on specific scoring implementations.

#### Methods

##### calculate_match_scores()

```python
def calculate_match_scores(self,
                          match_records: Dict[str, Dict],
                          wing_config: Any,
                          case_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculate weighted scores for correlation matches.
    
    Args:
        match_records: Dictionary of feather_id -> record
        wing_config: Wing configuration with weights
        case_id: Optional case ID for case-specific configuration
        
    Returns:
        Dictionary with score, interpretation, and breakdown
    """
```

**Return Format**:
```python
{
    'score': 0.75,  # Weighted score (0.0-1.0)
    'interpretation': 'Probable Match',  # Human-readable interpretation
    'breakdown': {  # Per-feather breakdown
        'feather_1': {
            'matched': True,
            'weight': 0.4,
            'contribution': 0.4,
            'tier': 1
        }
    },
    'matched_feathers': 3,
    'total_feathers': 5,
    'scoring_mode': 'weighted'  # or 'simple_count', 'error_fallback'
}
```

##### reload_configuration()

```python
def reload_configuration(self) -> bool:
    """
    Reload scoring configuration from config manager.
    
    Returns:
        True if reload was successful, False otherwise
    """
```

**Purpose**: Enables live configuration updates without application restart.

##### get_statistics()

```python
def get_statistics(self) -> IntegrationStatistics:
    """
    Get scoring integration statistics.
    
    Returns:
        IntegrationStatistics object with operation counts
    """
```

**Return Type**:
```python
@dataclass
class IntegrationStatistics:
    total_operations: int
    successful_operations: int
    failed_operations: int
    fallback_count: int
```

##### load_case_specific_scoring_weights()

```python
def load_case_specific_scoring_weights(self, case_id: str) -> bool:
    """
    Load case-specific scoring weights.
    
    Args:
        case_id: Case identifier
        
    Returns:
        True if case-specific configuration was loaded
    """
```

##### interpret_score()

```python
def interpret_score(self, score: float, case_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Interpret a weighted score into human-readable information.
    
    Args:
        score: Weighted score to interpret
        case_id: Optional case ID for case-specific interpretation
        
    Returns:
        Dictionary with interpretation details
    """
```

**Return Format**:
```python
{
    'label': 'Probable Match',
    'tier': 2,
    'confidence_percentage': 75.0,
    'description': 'Moderate confidence match with score 0.750'
}
```

##### validate_scoring_configuration()

```python
def validate_scoring_configuration(self,
                                  wing_config: Any,
                                  scoring_config: Any) -> Dict[str, Any]:
    """
    Validate wing scoring configuration against rules.
    
    Args:
        wing_config: Wing configuration to validate
        scoring_config: Scoring configuration with validation rules
        
    Returns:
        Dictionary with validation results
    """
```

**Return Format**:
```python
{
    'valid': True,
    'errors': [],
    'warnings': ['Feather X has zero weight'],
    'fixes': [
        {
            'feather_index': 0,
            'field': 'weight',
            'current_value': 1.5,
            'suggested_value': 1.0,
            'reason': 'Weight exceeds maximum'
        }
    ]
}
```

### ISemanticMappingIntegration

Interface for semantic mapping integration components.

**Location**: `correlation_engine/integration/interfaces.py`

**Purpose**: Defines the contract for semantic mapping implementations, enabling engines to apply semantic mappings without depending on specific mapping implementations.

#### Methods

##### apply_to_correlation_results()

```python
def apply_to_correlation_results(self,
                                results: List[Dict[str, Any]],
                                wing_id: Optional[str] = None,
                                pipeline_id: Optional[str] = None,
                                artifact_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Apply semantic mappings to correlation results.
    
    Args:
        results: List of correlation result records
        wing_id: Optional wing ID for wing-specific mappings
        pipeline_id: Optional pipeline ID for pipeline-specific mappings
        artifact_type: Optional artifact type for filtering mappings
        
    Returns:
        Enhanced results with semantic mapping information
    """
```

**Enhanced Result Format**:
```python
{
    # Original fields...
    '_semantic_mappings': {
        'EventID': {
            'semantic_value': 'User Login',
            'description': 'Successful user authentication',
            'category': 'authentication',
            'severity': 'info',
            'confidence': 1.0,
            'mapping_source': 'global'
        }
    }
}
```

##### reload_configuration()

```python
def reload_configuration(self) -> bool:
    """
    Reload semantic mapping configuration.
    
    Returns:
        True if reload was successful
    """
```

##### get_statistics()

```python
def get_statistics(self) -> IntegrationStatistics:
    """
    Get semantic mapping integration statistics.
    
    Returns:
        IntegrationStatistics object
    """
```

##### load_case_specific_mappings()

```python
def load_case_specific_mappings(self, case_id: str) -> bool:
    """
    Load case-specific semantic mappings.
    
    Args:
        case_id: Case identifier
        
    Returns:
        True if case-specific mappings were loaded
    """
```

##### get_semantic_display_data()

```python
def get_semantic_display_data(self,
                             record: Dict[str, Any],
                             artifact_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Get semantic information for UI display.
    
    Args:
        record: Record to get semantic data for
        artifact_type: Optional artifact type
        
    Returns:
        Dictionary with semantic display information
    """
```

**Return Format**:
```python
{
    'has_semantic_mappings': True,
    'semantic_fields': {
        'EventID': {
            'semantic_value': 'User Login',
            'description': '...',
            # ...
        }
    },
    'unmapped_fields': [
        {
            'field': 'ProcessName',
            'value': 'explorer.exe',
            'suggestion': 'Consider mapping process names to categories'
        }
    ],
    'mapping_summary': {
        'total_fields': 10,
        'mapped_fields': 7,
        'unmapped_fields': 3
    }
}
```

##### is_enabled()

```python
def is_enabled(self) -> bool:
    """
    Check if semantic mapping is enabled.
    
    Returns:
        True if enabled, False otherwise
    """
```

### IConfigurationObserver

Interface for configuration change observers.

**Location**: `correlation_engine/integration/interfaces.py`

**Purpose**: Defines the contract for components that need to react to configuration changes.

#### Methods

##### on_configuration_changed()

```python
def on_configuration_changed(self, old_config: Any, new_config: Any) -> None:
    """
    Called when configuration changes.
    
    Args:
        old_config: Previous configuration state
        new_config: New configuration state
    """
```

## Implementing Custom Integrations

### Creating a Custom Scoring Integration

```python
from correlation_engine.integration.interfaces import IScoringIntegration, IntegrationStatistics
from typing import Dict, List, Optional, Any

class CustomScoringIntegration(IScoringIntegration):
    """Custom scoring implementation"""
    
    def __init__(self):
        self.stats = IntegrationStatistics()
    
    def calculate_match_scores(self,
                              match_records: Dict[str, Dict],
                              wing_config: Any,
                              case_id: Optional[str] = None) -> Dict[str, Any]:
        """Implement custom scoring logic"""
        # Your custom scoring logic here
        score = len(match_records) / len(wing_config.feathers)
        
        self.stats.total_operations += 1
        self.stats.successful_operations += 1
        
        return {
            'score': score,
            'interpretation': f'{len(match_records)} matches',
            'breakdown': {},
            'matched_feathers': len(match_records),
            'total_feathers': len(wing_config.feathers),
            'scoring_mode': 'custom'
        }
    
    def reload_configuration(self) -> bool:
        """Reload configuration"""
        # Implement reload logic
        return True
    
    def get_statistics(self) -> IntegrationStatistics:
        """Return statistics"""
        return self.stats
    
    def load_case_specific_scoring_weights(self, case_id: str) -> bool:
        """Load case-specific weights"""
        # Implement case-specific loading
        return False
    
    def interpret_score(self, score: float, case_id: Optional[str] = None) -> Dict[str, Any]:
        """Interpret score"""
        return {
            'label': 'Custom Interpretation',
            'tier': 2,
            'confidence_percentage': score * 100,
            'description': f'Custom score: {score:.3f}'
        }
    
    def validate_scoring_configuration(self,
                                      wing_config: Any,
                                      scoring_config: Any) -> Dict[str, Any]:
        """Validate configuration"""
        return {
            'valid': True,
            'errors': [],
            'warnings': [],
            'fixes': []
        }
```

### Creating a Custom Semantic Mapping Integration

```python
from correlation_engine.integration.interfaces import ISemanticMappingIntegration, IntegrationStatistics
from typing import Dict, List, Optional, Any

class CustomSemanticMappingIntegration(ISemanticMappingIntegration):
    """Custom semantic mapping implementation"""
    
    def __init__(self):
        self.stats = IntegrationStatistics()
        self.mappings = {}
    
    def apply_to_correlation_results(self,
                                    results: List[Dict[str, Any]],
                                    wing_id: Optional[str] = None,
                                    pipeline_id: Optional[str] = None,
                                    artifact_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Apply custom semantic mappings"""
        enhanced_results = []
        
        for result in results:
            # Apply your custom mapping logic
            result['_semantic_mappings'] = self._apply_custom_mappings(result)
            enhanced_results.append(result)
            
            self.stats.total_operations += 1
            self.stats.successful_operations += 1
        
        return enhanced_results
    
    def _apply_custom_mappings(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Custom mapping logic"""
        mappings = {}
        # Implement your mapping logic
        return mappings
    
    def reload_configuration(self) -> bool:
        """Reload configuration"""
        # Implement reload logic
        return True
    
    def get_statistics(self) -> IntegrationStatistics:
        """Return statistics"""
        return self.stats
    
    def load_case_specific_mappings(self, case_id: str) -> bool:
        """Load case-specific mappings"""
        # Implement case-specific loading
        return False
    
    def get_semantic_display_data(self,
                                 record: Dict[str, Any],
                                 artifact_type: Optional[str] = None) -> Dict[str, Any]:
        """Get display data"""
        return {
            'has_semantic_mappings': False,
            'semantic_fields': {},
            'unmapped_fields': [],
            'mapping_summary': {
                'total_fields': 0,
                'mapped_fields': 0,
                'unmapped_fields': 0
            }
        }
    
    def is_enabled(self) -> bool:
        """Check if enabled"""
        return True
```

## Using Interfaces with Dependency Injection

### In Engines

```python
from correlation_engine.integration.interfaces import IScoringIntegration, ISemanticMappingIntegration

class MyCorrelationEngine:
    def __init__(self,
                 scoring_integration: IScoringIntegration,
                 mapping_integration: ISemanticMappingIntegration):
        """
        Initialize engine with injected integrations.
        
        Args:
            scoring_integration: Scoring integration implementation
            mapping_integration: Semantic mapping integration implementation
        """
        self.scoring = scoring_integration
        self.mapping = mapping_integration
    
    def correlate(self, wing_config):
        """Run correlation using injected integrations"""
        # Use scoring integration
        scores = self.scoring.calculate_match_scores(
            match_records={},
            wing_config=wing_config
        )
        
        # Use mapping integration
        results = self.mapping.apply_to_correlation_results(
            results=[],
            wing_id=wing_config.wing_id
        )
        
        return results
```

### In Tests

```python
from correlation_engine.integration.interfaces import IScoringIntegration, IntegrationStatistics

class MockScoringIntegration(IScoringIntegration):
    """Mock implementation for testing"""
    
    def __init__(self):
        self.calculate_calls = []
        self.mock_score = 0.8
    
    def calculate_match_scores(self, match_records, wing_config, case_id=None):
        self.calculate_calls.append({
            'match_records': match_records,
            'wing_config': wing_config,
            'case_id': case_id
        })
        return {
            'score': self.mock_score,
            'interpretation': 'Mock Score',
            'breakdown': {},
            'matched_feathers': len(match_records),
            'total_feathers': 5,
            'scoring_mode': 'mock'
        }
    
    # Implement other required methods...

# Use in test
def test_engine_scoring():
    mock_scoring = MockScoringIntegration()
    mock_scoring.mock_score = 0.9
    
    engine = MyCorrelationEngine(
        scoring_integration=mock_scoring,
        mapping_integration=mock_mapping
    )
    
    result = engine.correlate(wing_config)
    
    # Verify mock was called
    assert len(mock_scoring.calculate_calls) == 1
    assert result['score'] == 0.9
```

## Benefits of Interface-Based Design

### 1. Testability

- Easy to create mock implementations
- Isolated unit testing without dependencies
- Predictable test behavior

### 2. Flexibility

- Swap implementations at runtime
- Support multiple scoring strategies
- Easy to add new integration types

### 3. Maintainability

- Clear contracts between components
- Changes to implementations don't affect interfaces
- Easier to understand component responsibilities

### 4. Extensibility

- Third-party integrations can implement interfaces
- Plugin architecture support
- Custom implementations for specific use cases

## Best Practices

1. **Always program to interfaces**, not implementations
2. **Use dependency injection** to provide implementations
3. **Create mock implementations** for testing
4. **Document interface contracts** clearly
5. **Handle errors gracefully** in implementations
6. **Maintain backward compatibility** when updating interfaces
7. **Use type hints** for better IDE support

## See Also

- [Configuration Documentation](../config/CONFIG_DOCUMENTATION.md)
- [Weight Precedence Documentation](../config/WEIGHT_PRECEDENCE.md)
- [Testing Guide](TESTING_GUIDE.md)
