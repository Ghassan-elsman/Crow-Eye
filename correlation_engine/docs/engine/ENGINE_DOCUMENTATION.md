# Engine Directory Documentation

## Table of Contents

- [Overview](#overview)
- [Files in This Directory](#files-in-this-directory)
  - [correlation_engine.py](#correlation_enginepy)
  - [feather_loader.py](#feather_loaderpy)
  - [correlation_result.py](#correlation_resultpy)
  - [weighted_scoring.py](#weighted_scoringpy)
  - [timestamp_parser.py](#timestamp_parserpy)
  - [identifier_correlation_engine.py](#identifier_correlation_enginepy)
  - [identity_extractor.py](#identity_extractorpy)
  - [query_interface.py](#query_interfacepy)
  - [results_formatter.py](#results_formatterpy)
  - [data_structures.py](#data_structurespy)
  - [database_persistence.py](#database_persistencepy)
  - [enhanced_feather_loader.py](#enhanced_feather_loaderpy)
  - [identifier_extraction_pipeline.py](#identifier_extraction_pipelinepy)
  - [identity_correlation_engine.py](#identity_correlation_enginepy)
  - [__init__.py](#__init__py)
- [Common Modification Scenarios](#common-modification-scenarios)
- [Testing](#testing)
- [See Also](#see-also)

---

## Overview

The **engine/** directory contains the core correlation logic of the Crow-Eye Correlation Engine. This is where the actual temporal correlation happens, where feathers are loaded, where matches are scored, and where results are generated.

### Purpose

- Execute Wing configurations to find temporal correlations
- Load and query feather databases
- Calculate confidence scores for matches
- Parse various timestamp formats
- Extract identity information from records
- Format and persist correlation results

### How It Fits in the Overall System

The engine is the **heart** of the correlation system. It receives:
- **Input**: Wing configurations (from wings/), feather database paths (from config/), execution commands (from pipeline/)
- **Output**: CorrelationResult objects containing matches with confidence scores

The engine is used by:
- `pipeline/pipeline_executor.py` - Orchestrates wing execution
- `gui/execution_control.py` - Executes wings from GUI
- `integration/crow_eye_integration.py` - Integrates with Crow-Eye

---

## Files in This Directory

### correlation_engine.py

**Lines**: 1854 lines (largest file in engine/)

**Purpose**: Main correlation engine that executes Wings and finds temporal correlations between feather records.

**Key Classes**:

1. **`CorrelationEngine`**
   - Main engine class that orchestrates correlation
   - Manages feather loaders, scoring engine, semantic mappings
   - Implements duplicate prevention and progress tracking

2. **`ProgressEvent`**
   - Data class for progress events
   - Fields: `event_type`, `timestamp`, `data`
   - Used for real-time UI feedback

3. **`DuplicateInfo`**
   - Tracks duplicate match information
   - Fields: `is_duplicate`, `original_match_id`, `duplicate_count`

4. **`MatchSet`**
   - Unique identifier for correlation matches
   - Uses frozen set of (feather_id, record_id) tuples
   - Prevents duplicate matches with same record combinations

**Key Methods**:

```python
def execute_wing(wing: Wing, feather_paths: Dict[str, str]) -> CorrelationResult:
    """Main entry point for wing execution"""
    
def _correlate_records(wing: Wing, filtered_records: Dict, result: CorrelationResult) -> List[CorrelationMatch]:
    """Core correlation algorithm - collects anchors and finds matches"""
    
def _generate_match_combinations(anchor_record, anchor_feather_id, anchor_time, 
                                 filtered_records, time_window_minutes, 
                                 minimum_matches, max_matches_per_anchor) -> List:
    """Generate all valid match combinations for an anchor"""
    
def _detect_forensic_timestamp_columns(feather_id: str, records: List[Dict]) -> List[str]:
    """Detect valid timestamp columns in feather records"""
    
def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse timestamp from various formats"""
```

**Dependencies**:
- `feather_loader.py` (FeatherLoader)
- `correlation_result.py` (CorrelationResult, CorrelationMatch)
- `weighted_scoring.py` (WeightedScoringEngine)
- `wings/core/wing_model.py` (Wing, FeatherSpec)
- `config/semantic_mapping.py` (SemanticMappingManager)

**Dependents** (files that import this):
- `pipeline/pipeline_executor.py`
- `gui/execution_control.py`
- `integration/crow_eye_integration.py`
- `engine/__init__.py`

**Impact Analysis**:
- **CRITICAL FILE** - Changes affect all correlation operations
- Modifying `_correlate_records()` changes how matches are found
- Modifying `forensic_timestamp_patterns` affects which feathers are processed
- Modifying duplicate detection affects result accuracy
- Changes require extensive testing with multiple artifact types

**Code Example**:

```python
from correlation_engine.engine import CorrelationEngine
from correlation_engine.wings.core.wing_model import Wing

# Initialize engine
engine = CorrelationEngine(debug_mode=True)

# Load wing configuration
wing = Wing.load_from_file("my_wing.json")

# Define feather paths
feather_paths = {
    "prefetch": "path/to/prefetch.db",
    "shimcache": "path/to/shimcache.db"
}

# Execute correlation
result = engine.execute_wing(wing, feather_paths)

# Access results
print(f"Found {result.total_matches} matches")
for match in result.matches:
    print(f"Match at {match.timestamp}: {match.feather_count} feathers")
```

---

### feather_loader.py

**Purpose**: Loads and queries feather databases (SQLite), with automatic schema detection and column type identification.

**Key Classes**:

1. **`FeatherLoader`**
   - Connects to feather SQLite databases
   - Detects schema and column types automatically
   - Provides query interface for records

**Exception Hierarchy**:
- `FeatherLoaderError` (base)
  - `InvalidDatabaseError`
  - `NoDataTablesError`
  - `EmptyTableError`
  - `SchemaDetectionError`

**Key Methods**:

```python
def connect() -> None:
    """Connect to feather database"""
    
def get_all_records() -> List[Dict[str, Any]]:
    """Retrieve all records from feather"""
    
def get_records_by_filters(application=None, file_path=None, event_id=None) -> List[Dict]:
    """Get filtered records"""
    
def detect_columns() -> DetectedColumns:
    """Auto-detect timestamp, name, and path columns"""
    
def get_record_count() -> int:
    """Get total record count"""
```

**Dependencies**:
- `timestamp_parser.py` (parse_timestamp)
- SQLite3 (standard library)

**Dependents**:
- `correlation_engine.py`
- `engine/__init__.py`

**Impact Analysis**:
- **HIGH IMPACT** - Changes affect how all feathers are loaded
- Modifying `detect_columns()` affects timestamp detection
- Modifying query methods affects filtering behavior
- Changes require testing with all artifact types

**Code Example**:

```python
from correlation_engine.engine import FeatherLoader

# Load feather
loader = FeatherLoader("prefetch.db")
loader.connect()

# Get all records
records = loader.get_all_records()

# Get filtered records
chrome_records = loader.get_records_by_filters(application="chrome.exe")

# Detect columns
detected = loader.detect_columns()
print(f"Timestamp columns: {detected.timestamp_columns}")
print(f"Name columns: {detected.name_columns}")
```

---

### correlation_result.py

**Purpose**: Data structures for storing and serializing correlation results.

**Key Classes**:

1. **`CorrelationMatch`**
   - Represents a single correlation match
   - Contains matched records from multiple feathers
   - Includes scoring and metadata

**Fields**:
- `match_id`: Unique identifier
- `timestamp`: Central timestamp
- `feather_records`: Dict of feather_id → record data
- `match_score`: Quality score (0.0-1.0)
- `feather_count`: Number of matched feathers
- `time_spread_seconds`: Time range of match
- `anchor_feather_id`: Which feather was the anchor
- `confidence_score`: Weighted confidence score
- `score_breakdown`: Detailed scoring information
- `is_duplicate`: Duplicate flag
- `semantic_data`: Semantic mapping data

2. **`CorrelationResult`**
   - Complete results from wing execution
   - Contains list of matches and statistics

**Fields**:
- `wing_id`, `wing_name`: Wing identification
- `matches`: List of CorrelationMatch objects
- `total_matches`: Match count
- `feathers_processed`: Number of feathers
- `total_records_scanned`: Records processed
- `duplicates_prevented`: Duplicate count
- `execution_duration_seconds`: Performance metric
- `errors`, `warnings`: Issues encountered

**Key Methods**:

```python
def add_match(match: CorrelationMatch):
    """Add a match to results"""
    
def get_matches_by_score(min_score: float) -> List[CorrelationMatch]:
    """Filter matches by score"""
    
def get_summary() -> Dict[str, Any]:
    """Get summary statistics"""
    
def to_dict() -> dict:
    """Serialize to dictionary"""
    
def save_to_file(file_path: str):
    """Save to JSON file"""
```

**Dependencies**:
- None (pure data structures)

**Dependents**:
- `correlation_engine.py`
- `results_formatter.py`
- `query_interface.py`
- `gui/correlation_results_view.py`
- `gui/hierarchical_results_view.py`
- `pipeline/pipeline_executor.py`

**Impact Analysis**:
- **MEDIUM IMPACT** - Changes affect result storage and display
- Adding fields requires updating serialization methods
- Changes affect GUI display components
- Backward compatibility important for saved results

**Code Example**:

```python
from correlation_engine.engine import CorrelationResult, CorrelationMatch

# Create result
result = CorrelationResult(
    wing_id="wing-123",
    wing_name="Execution Proof"
)

# Add match
match = CorrelationMatch(
    match_id="match-1",
    timestamp="2024-01-15T10:30:00Z",
    feather_records={"prefetch": {...}, "shimcache": {...}},
    match_score=0.85,
    feather_count=2,
    time_spread_seconds=120.0,
    anchor_feather_id="prefetch",
    anchor_artifact_type="Prefetch"
)
result.add_match(match)

# Save results
result.save_to_file("results.json")

# Get summary
summary = result.get_summary()
print(f"Average score: {summary['avg_score']}")
```

---

### weighted_scoring.py

**Purpose**: Calculate weighted confidence scores for correlation matches based on feather importance and match quality.

**Key Classes**:

1. **`WeightedScoringEngine`**
   - Calculates weighted scores for matches
   - Interprets scores using configurable thresholds
   - Provides per-feather contribution breakdown

**Key Methods**:

```python
def calculate_match_score(match_records: Dict[str, Dict], 
                         wing_config: Any) -> Dict[str, Any]:
    """
    Calculate weighted score for a match.
    
    Returns:
        {
            'score': float,  # Total weighted score
            'interpretation': str,  # "High", "Medium", "Low"
            'breakdown': dict,  # Per-feather contributions
            'matched_feathers': int,
            'total_feathers': int
        }
    """
    
def _interpret_score(score: float, interpretation_config: Dict) -> str:
    """Interpret score based on thresholds"""
```

**Scoring Logic**:
1. Each feather in wing has a configured weight
2. If feather matches, its weight contributes to total score
3. Total score is sum of matched feather weights
4. Score is interpreted using thresholds (e.g., >0.8 = "High")

**Dependencies**:
- None (pure calculation logic)

**Dependents**:
- `correlation_engine.py`
- `engine/__init__.py`

**Impact Analysis**:
- **MEDIUM IMPACT** - Changes affect match confidence scores
- Modifying scoring logic affects result interpretation
- Changes should be tested with various wing configurations
- Backward compatibility important for comparing results

**Code Example**:

```python
from correlation_engine.engine import WeightedScoringEngine

engine = WeightedScoringEngine()

# Match records
match_records = {
    "prefetch": {"application": "chrome.exe"},
    "shimcache": {"file_path": "C:\\...\\chrome.exe"}
}

# Calculate score
score_data = engine.calculate_match_score(match_records, wing_config)

print(f"Score: {score_data['score']}")
print(f"Interpretation: {score_data['interpretation']}")
print(f"Breakdown: {score_data['breakdown']}")
```

---

### timestamp_parser.py

**Purpose**: Parse and normalize timestamps from various forensic artifact formats.

**Key Classes**:

1. **`TimestampParser`**
   - Parses timestamps from multiple formats
   - Supports ISO 8601, Unix epoch, Windows FILETIME
   - Validates timestamps are in reasonable range

**Supported Formats**:
- ISO 8601 (with/without timezone, with/without microseconds)
- Unix epoch (seconds and milliseconds)
- Windows FILETIME (100-nanosecond intervals since 1601)
- US date formats (MM/DD/YYYY)
- European date formats (DD/MM/YYYY)
- Compact formats (YYYYMMDDHHMMSS)
- Custom formats via configuration

**Key Methods**:

```python
def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse timestamp from any supported format"""
    
def validate_timestamp(dt: datetime) -> bool:
    """Validate timestamp is in reasonable range (1990-2050)"""
    
def _parse_numeric_timestamp(value: Union[int, float]) -> Optional[datetime]:
    """Parse Unix epoch or Windows FILETIME"""
    
def _parse_string_timestamp(value: str) -> Optional[datetime]:
    """Parse string timestamp using multiple formats"""
    
def _parse_windows_filetime(filetime: int) -> Optional[datetime]:
    """Convert Windows FILETIME to datetime"""
```

**Dependencies**:
- `datetime` (standard library)
- `dateutil.parser` (optional fallback)

**Dependents**:
- `correlation_engine.py`
- `feather_loader.py`

**Impact Analysis**:
- **MEDIUM IMPACT** - Changes affect timestamp parsing across all feathers
- Adding new formats enables support for new artifact types
- Validation changes affect which records are processed
- Errors in parsing can cause records to be skipped

**Code Example**:

```python
from correlation_engine.engine.timestamp_parser import parse_timestamp

# Parse various formats
dt1 = parse_timestamp("2024-01-15T10:30:00Z")  # ISO 8601
dt2 = parse_timestamp(1705318200)  # Unix epoch
dt3 = parse_timestamp(133500000000000000)  # Windows FILETIME
dt4 = parse_timestamp("01/15/2024 10:30:00 AM")  # US format

# Custom formats
parser = TimestampParser(custom_formats=["%d.%m.%Y %H:%M"])
dt5 = parser.parse_timestamp("15.01.2024 10:30")
```

---

### identifier_correlation_engine.py

**Purpose**: Correlate records based on identifiers (usernames, file paths, etc.) rather than just time proximity.

**Key Classes**:

1. **`IdentifierCorrelationEngine`**
   - Finds records with matching identifiers
   - Complements temporal correlation
   - Useful for tracking user activity or file access

**Key Methods**:

```python
def correlate_by_identifier(feather_records: Dict, 
                           identifier_field: str) -> List[CorrelationMatch]:
    """Find records with matching identifier values"""
```

**Use Cases**:
- Find all records related to a specific user
- Track file access across multiple artifacts
- Correlate by process ID or session ID

**Dependencies**:
- `correlation_result.py`
- `identity_extractor.py`

**Dependents**:
- `correlation_engine.py` (optional correlation mode)

**Impact Analysis**:
- **LOW IMPACT** - Optional feature, doesn't affect main correlation
- Changes only affect identifier-based correlation
- Can be modified independently

---

### identity_extractor.py

**Purpose**: Extract identity information (usernames, SIDs, email addresses, device names) from forensic records.

**Key Classes**:

1. **`IdentityExtractor`**
   - Extracts identity fields from records
   - Normalizes identity information
   - Supports multiple identity types

**Extracted Identity Types**:
- Usernames
- Security Identifiers (SIDs)
- Email addresses
- Device names
- Domain names

**Key Methods**:

```python
def extract_identities(record: Dict) -> Dict[str, List[str]]:
    """Extract all identity information from a record"""
    
def extract_username(record: Dict) -> Optional[str]:
    """Extract username from record"""
    
def extract_sid(record: Dict) -> Optional[str]:
    """Extract SID from record"""
```

**Dependencies**:
- None (pure extraction logic)

**Dependents**:
- `identifier_correlation_engine.py`
- `identity_correlation_engine.py`

**Impact Analysis**:
- **LOW IMPACT** - Changes only affect identity extraction
- Adding new identity types extends functionality
- Doesn't affect core temporal correlation

---

### query_interface.py

**Purpose**: Provide query interface for searching and filtering correlation results.

**Key Classes**:

1. **`QueryInterface`**
   - Query correlation results
   - Filter by various criteria
   - Aggregate statistics

**Key Methods**:

```python
def query_by_application(results: CorrelationResult, 
                        application: str) -> List[CorrelationMatch]:
    """Find matches for specific application"""
    
def query_by_time_range(results: CorrelationResult,
                       start: datetime, end: datetime) -> List[CorrelationMatch]:
    """Find matches in time range"""
    
def query_by_score(results: CorrelationResult,
                  min_score: float) -> List[CorrelationMatch]:
    """Find matches above score threshold"""
```

**Dependencies**:
- `correlation_result.py`

**Dependents**:
- `gui/correlation_results_view.py`
- `gui/semantic_filter_panel.py`

**Impact Analysis**:
- **LOW IMPACT** - Changes only affect result querying
- Adding new query methods extends functionality
- Doesn't affect correlation execution

---

### results_formatter.py

**Purpose**: Format correlation results for display and export, apply semantic mappings to results.

**Key Functions**:

```python
def apply_semantic_mappings_to_result(result: CorrelationResult,
                                     semantic_manager: SemanticMappingManager) -> CorrelationResult:
    """Apply semantic mappings to all matches in result"""
    
class ResultsFormatter:
    """Format results for various output formats"""
    
    def format_as_table(result: CorrelationResult) -> str:
        """Format as ASCII table"""
        
    def format_as_json(result: CorrelationResult) -> str:
        """Format as JSON"""
        
    def format_as_csv(result: CorrelationResult) -> str:
        """Format as CSV"""
```

**Dependencies**:
- `correlation_result.py`
- `config/semantic_mapping.py`

**Dependents**:
- `gui/correlation_results_view.py`
- `pipeline/pipeline_executor.py`
- `engine/__init__.py`

**Impact Analysis**:
- **LOW IMPACT** - Changes only affect result formatting
- Adding new formats extends functionality
- Doesn't affect correlation execution

---

### data_structures.py

**Purpose**: Additional data structures used by the correlation engine.

**Key Classes**:
- `DetectedColumns`: Column detection results
- `MatchCandidate`: Candidate match information
- Other utility data structures

**Dependencies**:
- None (pure data structures)

**Dependents**:
- `correlation_engine.py`
- `feather_loader.py`

**Impact Analysis**:
- **LOW IMPACT** - Changes only affect internal data structures
- Modifications should maintain backward compatibility

---

### database_persistence.py

**Purpose**: Persist correlation results to database for later analysis.

**Key Classes**:

1. **`DatabasePersistence`**
   - Save results to SQLite database
   - Load results from database
   - Query historical results

**Key Methods**:

```python
def save_result(result: CorrelationResult):
    """Save result to database"""
    
def load_result(result_id: str) -> CorrelationResult:
    """Load result from database"""
    
def query_results(filters: Dict) -> List[CorrelationResult]:
    """Query historical results"""
```

**Dependencies**:
- `correlation_result.py`
- SQLite3

**Dependents**:
- `gui/results_viewer.py`
- `pipeline/pipeline_executor.py`

**Impact Analysis**:
- **LOW IMPACT** - Optional persistence feature
- Changes don't affect correlation execution
- Schema changes require migration

---

### enhanced_feather_loader.py

**Purpose**: Enhanced version of FeatherLoader with additional features (caching, optimization).

**Key Classes**:

1. **`EnhancedFeatherLoader`**
   - Extends FeatherLoader
   - Adds caching for performance
   - Optimized query methods

**Dependencies**:
- `feather_loader.py`

**Dependents**:
- `correlation_engine.py` (optional)

**Impact Analysis**:
- **LOW IMPACT** - Optional enhancement
- Can be used as drop-in replacement for FeatherLoader

---

### identifier_extraction_pipeline.py

**Purpose**: Pipeline for extracting and processing identifiers from feather records.

**Key Classes**:

1. **`IdentifierExtractionPipeline`**
   - Orchestrates identifier extraction
   - Processes multiple feathers
   - Aggregates identity information

**Dependencies**:
- `identity_extractor.py`
- `feather_loader.py`

**Dependents**:
- `identifier_correlation_engine.py`

**Impact Analysis**:
- **LOW IMPACT** - Optional feature
- Changes don't affect core correlation

---

### identity_correlation_engine.py

**Purpose**: Specialized correlation engine for identity-based correlation.

**Key Classes**:

1. **`IdentityCorrelationEngine`**
   - Correlates records by identity
   - Tracks user activity across artifacts
   - Complements temporal correlation

**Dependencies**:
- `correlation_engine.py`
- `identity_extractor.py`

**Dependents**:
- `pipeline/pipeline_executor.py` (optional mode)

**Impact Analysis**:
- **LOW IMPACT** - Optional feature
- Independent from main correlation engine

---

### __init__.py

**Purpose**: Package initialization, exports main classes for easy importing.

**Exports**:
- `CorrelationEngine`
- `CorrelationResult`
- `CorrelationMatch`
- `FeatherLoader`
- `WeightedScoringEngine`
- `ResultsFormatter`
- `apply_semantic_mappings_to_result`

**Impact Analysis**:
- **LOW IMPACT** - Changes only affect import statements
- Adding exports makes classes easier to import
- Removing exports breaks external imports

---

## Common Modification Scenarios

### Scenario 1: Adding a New Correlation Algorithm

**Goal**: Implement a new way to correlate records (e.g., by semantic similarity, by network connections).

**Files to Modify**:

1. **`correlation_engine.py`**
   - Add new method `_correlate_by_semantic_similarity()`
   - Add configuration option to choose algorithm
   - Update `execute_wing()` to support new algorithm

2. **`wings/core/wing_model.py`**
   - Add `correlation_algorithm` field to `CorrelationRules`
   - Options: "temporal", "identifier", "semantic", "hybrid"

3. **`correlation_result.py`**
   - Add `correlation_algorithm` field to `CorrelationMatch`
   - Track which algorithm produced each match

**Steps**:
1. Implement new correlation method in `correlation_engine.py`
2. Add configuration option to wing model
3. Update result structures to track algorithm used
4. Test with sample data
5. Update GUI to allow algorithm selection

**Impact**: Medium - Adds new functionality without breaking existing code

---

### Scenario 2: Modifying Scoring Weights

**Goal**: Change how confidence scores are calculated (e.g., give more weight to certain artifact types).

**Files to Modify**:

1. **`weighted_scoring.py`**
   - Modify `calculate_match_score()` method
   - Adjust weight calculations
   - Update interpretation thresholds

2. **`wings/core/wing_model.py`**
   - Add weight configuration to `FeatherSpec`
   - Add scoring configuration to `CorrelationRules`

**Steps**:
1. Update scoring logic in `weighted_scoring.py`
2. Add configuration options to wing model
3. Test with various wing configurations
4. Update documentation

**Impact**: Low - Only affects scoring, doesn't change correlation logic

---

### Scenario 3: Adding New Timestamp Format Support

**Goal**: Support a new timestamp format found in a custom artifact.

**Files to Modify**:

1. **`timestamp_parser.py`**
   - Add new format to `supported_formats` list
   - Or add custom parsing logic in `_parse_string_timestamp()`

**Steps**:
1. Identify the timestamp format (e.g., "DD.MM.YYYY HH:MM:SS")
2. Add format string to `supported_formats`
3. Test with sample timestamps
4. Verify timestamps are parsed correctly

**Example**:

```python
# In timestamp_parser.py
self.supported_formats = [
    # ... existing formats ...
    "%d.%m.%Y %H:%M:%S",  # European format with dots
    "%Y年%m月%d日 %H:%M:%S",  # Japanese format
]
```

**Impact**: Very Low - Only affects timestamp parsing, isolated change

---

### Scenario 4: Improving Duplicate Detection

**Goal**: Enhance duplicate detection to catch more edge cases.

**Files to Modify**:

1. **`correlation_engine.py`**
   - Modify `MatchSet` class
   - Update `_is_duplicate_match()` logic
   - Adjust duplicate tracking

**Steps**:
1. Identify duplicate detection issues
2. Update `MatchSet` to include more identifying information
3. Test with data that previously produced duplicates
4. Verify duplicates are correctly identified

**Impact**: Medium - Affects result accuracy, requires thorough testing

---

### Scenario 5: Adding Performance Optimization

**Goal**: Improve correlation performance for large datasets.

**Files to Modify**:

1. **`correlation_engine.py`**
   - Add caching for frequently accessed data
   - Optimize `_generate_match_combinations()`
   - Add parallel processing for independent operations

2. **`feather_loader.py`**
   - Add query result caching
   - Optimize database queries
   - Add connection pooling

**Steps**:
1. Profile code to identify bottlenecks
2. Implement caching where appropriate
3. Optimize database queries
4. Test performance improvements
5. Ensure results remain accurate

**Impact**: Medium - Improves performance without changing functionality

---

## Testing

### Unit Tests

Test individual components in isolation:

```python
# test_timestamp_parser.py
def test_parse_iso8601():
    parser = TimestampParser()
    dt = parser.parse_timestamp("2024-01-15T10:30:00Z")
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 15

# test_weighted_scoring.py
def test_calculate_score():
    engine = WeightedScoringEngine()
    score_data = engine.calculate_match_score(match_records, wing_config)
    assert 0.0 <= score_data['score'] <= 1.0
```

### Integration Tests

Test component interactions:

```python
# test_correlation_engine.py
def test_execute_wing():
    engine = CorrelationEngine()
    wing = create_test_wing()
    feather_paths = create_test_feathers()
    
    result = engine.execute_wing(wing, feather_paths)
    
    assert result.total_matches > 0
    assert len(result.errors) == 0
```

### Performance Tests

Test with large datasets:

```python
# test_performance.py
def test_large_dataset_performance():
    engine = CorrelationEngine()
    # Create feathers with 10,000+ records each
    result = engine.execute_wing(wing, large_feather_paths)
    
    assert result.execution_duration_seconds < 60  # Should complete in under 1 minute
```

---

## See Also

- **[Main Overview](../CORRELATION_ENGINE_OVERVIEW.md)** - System architecture and overview
- **[Feather Documentation](../feather/FEATHER_DOCUMENTATION.md)** - Data normalization system
- **[Wings Documentation](../wings/WINGS_DOCUMENTATION.md)** - Correlation rule definitions
- **[Pipeline Documentation](../pipeline/PIPELINE_DOCUMENTATION.md)** - Workflow orchestration
- **[GUI Documentation](../gui/GUI_DOCUMENTATION.md)** - User interface components

---

*Last Updated: 2024*
*Engine Directory: 15 Python files*
