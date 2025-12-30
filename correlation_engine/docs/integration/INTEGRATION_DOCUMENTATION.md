# Integration Directory Documentation

## Overview

The **integration/** directory integrates the correlation engine with the main Crow-Eye application, providing auto-generation features, default configurations, and case initialization.

### Purpose
- Bridge correlation engine with Crow-Eye
- Auto-generate feathers from Crow-Eye data
- Initialize correlation engine for cases
- Provide default wings and pipelines
- Generate feather configurations automatically

---

## Files in This Directory

### correlation_integration.py

**Purpose**: Main integration bridge between Crow-Eye and Correlation Engine.

**Key Classes**:
- `CorrelationIntegration`: Integration coordinator

**Key Methods**:
```python
def __init__(main_window):
    """
    Initialize correlation integration
    
    Args:
        main_window: Reference to Crow-Eye main window (Ui_Crow_Eye object)
    
    Sets up:
        - Reference to Crow-Eye main window
        - Configuration Manager (if available)
        - Correlation window placeholder
    """

def show_correlation_dialog():
    """
    Launch the Correlation Engine GUI
    
    Steps:
    1. Import Correlation Engine modules
    2. Get parent widget from Crow-Eye
    3. Get case directory
    4. Initialize case (wings, feathers, pipeline)
    5. Create Correlation Engine window
    6. Apply Crow-Eye styling
    7. Set default directories
    8. Show window
    
    Directory Structure Created:
        case_root/Correlation/
        ├── feathers/
        ├── wings/
        ├── pipelines/
        └── results/
    """

def _apply_crow_eye_styles():
    """
    Apply Crow-Eye dark theme to Correlation Engine
    
    Attempts to load from crow_eye_styles.qss
    Falls back to inline theme if file not found
    """

def _apply_inline_dark_theme():
    """
    Apply inline dark theme as fallback
    
    Color Palette:
        - Background: #0F172A (Dark blue)
        - Accent: #00FFFF (Cyan)
        - Button: #00FF00 (Green)
        - Text: #E2E8F0 (Light gray)
    """
```

**Integration Flow**:
```
Crow-Eye Button Click
        ↓
show_correlation_dialog()
        ↓
    ┌───┴───┐
    ↓       ↓
Get Case    Get Parent
Directory   Widget
    ↓       ↓
    └───┬───┘
        ↓
Initialize Case
    ├─ Copy Default Wings
    ├─ Generate Feather Configs
    └─ Create Default Pipeline
        ↓
Create Correlation Engine Window
        ↓
Apply Crow-Eye Styling
        ↓
Set Default Directories
        ↓
Show Window
```

**Dependencies**:
- `gui.main_window.MainWindow` - Correlation Engine GUI
- `integration.case_initializer.CaseInitializer` - Case setup
- `integration.default_wings_loader.DefaultWingsLoader` - Default wings
- `config.configuration_manager.ConfigurationManager` - Config management (optional)
- PyQt5 - GUI framework

**Dependents**: 
- `Crow Eye.py` - Main Crow-Eye application

**Impact Analysis**:
- **CRITICAL FILE** - Main integration point between Crow-Eye and Correlation Engine
- Changes affect how Correlation Engine is launched from Crow-Eye
- Modifying initialization affects case setup
- Styling changes affect Correlation Engine appearance
- Error handling changes affect user experience

**Error Handling**:
- `ImportError`: Shows dialog if Correlation Engine modules not found
- `Exception`: Shows dialog for any launch failures
- All errors logged with stack traces

**Code Example**:
```python
# In Crow-Eye main window initialization
from correlation_engine.integration.correlation_integration import CorrelationIntegration

# Initialize integration
ui.correlation_integration = CorrelationIntegration(ui)

# In correlation button click handler
def on_correlation_button_clicked(self):
    """Launch Correlation Engine when button is clicked"""
    try:
        self.correlation_integration.show_correlation_dialog()
    except Exception as e:
        print(f"Error launching Correlation Engine: {e}")
```

**Configuration Manager Integration**:
```python
# If Configuration Manager is available
if CONFIG_MANAGER_AVAILABLE:
    self.config_manager = ConfigurationManager.get_instance()
    
    # Set case directory
    self.config_manager.set_case_directory(case_root)
    
    # Get correlation directory
    correlation_dir = self.config_manager.get_correlation_directory()
    
    # Load all configurations
    self.config_manager.load_all_configurations()
```

**Styling Integration**:
```python
# Try to load external stylesheet
style_file = Path(__file__).parent.parent / "gui" / "crow_eye_styles.qss"

if style_file.exists():
    with open(style_file, 'r') as f:
        stylesheet = f.read()
    self.correlation_window.setStyleSheet(stylesheet)
else:
    # Fallback to inline theme
    self._apply_inline_dark_theme()
```

---

### crow_eye_integration.py

**Purpose**: Main integration bridge between Crow-Eye and Correlation Engine.

**Key Classes**:
- `CrowEyeIntegration`: Integration coordinator

**Key Methods**:
```python
def initialize_for_case(case_path):
    """Initialize correlation engine for a case"""
    
def import_crow_eye_artifacts(case_path):
    """Import artifacts from Crow-Eye case"""
    
def export_results_to_crow_eye(results):
    """Export correlation results to Crow-Eye"""
```

**Dependencies**: All correlation engine modules

**Dependents**: Crow-Eye main application

**Impact**: CRITICAL - Main integration point

---

### case_initializer.py

**Purpose**: Initialize correlation engine for a forensic case.

**Key Classes**:
- `CaseInitializer`: Orchestrates case initialization
- `InitializationResult`: Initialization result data

**Key Methods**:
```python
def initialize_case(case_path, case_name):
    """
    Initialize correlation engine for case
    
    Steps:
    1. Create directory structure
    2. Scan for artifacts
    3. Auto-generate feathers
    4. Load default wings
    5. Create default pipeline
    """
    
def scan_artifacts(case_path):
    """Scan case directory for artifacts"""
    
def setup_directories(case_path):
    """Create correlation engine directories"""
```

**Initialization Steps**:
1. Create `correlation_engine/` directory in case
2. Create subdirectories: `feathers/`, `wings/`, `pipelines/`, `results/`
3. Scan for Crow-Eye parsed databases
4. Auto-generate feather configurations
5. Load default wings
6. Create default pipeline
7. Return initialization result

**Dependencies**:
- `auto_feather_generator.py`
- `default_wings_loader.py`
- `default_pipeline_creator.py`

**Dependents**: `crow_eye_integration.py`

**Impact**: HIGH - Affects case setup

**Code Example**:
```python
from correlation_engine.integration import CaseInitializer

# Initialize for case
initializer = CaseInitializer()
result = initializer.initialize_case(
    case_path="/path/to/case",
    case_name="Investigation-2024"
)

if result.success:
    print(f"Feathers created: {result.feathers_created}")
    print(f"Wings loaded: {result.wings_loaded}")
    print(f"Pipeline created: {result.pipeline_created}")
else:
    print(f"Errors: {result.errors}")
```

---

### auto_feather_generator.py

**Purpose**: Automatically generate feathers from Crow-Eye parser output.

**Key Classes**:
- `AutoFeatherGenerator`: Auto-generates feathers

**Key Methods**:
```python
def generate_feathers(case_path):
    """
    Generate feathers from Crow-Eye artifacts
    
    Steps:
    1. Scan for parsed databases
    2. Detect artifact types
    3. Generate feather configs
    4. Create feather databases
    5. Return feather paths
    """
    
def detect_artifact_type(db_path):
    """Detect artifact type from database"""
    
def create_feather_from_database(db_path, artifact_type):
    """Create feather from source database"""
```

**Supported Artifacts**:
- Prefetch
- ShimCache
- AmCache
- Event Logs
- LNK files
- Jumplists
- MFT
- SRUM
- Registry
- Browser History

**Dependencies**:
- `feather_config_generator.py`
- `feather_mappings.py`
- `feather/transformer.py`

**Dependents**: `case_initializer.py`

**Impact**: HIGH - Affects feather creation

---

### feather_config_generator.py

**Purpose**: Generate feather configuration files from artifact metadata.

**Key Classes**:
- `FeatherConfigGenerator`: Generates feather configs

**Key Methods**:
```python
def generate_config(db_path, artifact_type):
    """
    Generate feather configuration
    
    Steps:
    1. Analyze database schema
    2. Detect column types
    3. Create column mappings
    4. Generate configuration
    5. Save to file
    """
    
def analyze_schema(db_path):
    """Analyze database schema"""
    
def create_column_mappings(schema, artifact_type):
    """Create column mappings for artifact type"""
```

**Dependencies**:
- `feather_mappings.py`
- `config/feather_config.py`

**Dependents**: `auto_feather_generator.py`

**Impact**: MEDIUM - Affects config generation

---

### feather_mappings.py

**Purpose**: Standard column mappings for common artifact types.

**Mappings Provided**:

```python
PREFETCH_MAPPINGS = {
    'executable': 'application',
    'last_run_time': 'timestamp',
    'run_count': 'execution_count'
}

SHIMCACHE_MAPPINGS = {
    'path': 'file_path',
    'last_modified': 'timestamp',
    'file_size': 'size'
}

AMCACHE_MAPPINGS = {
    'program_name': 'application',
    'install_date': 'timestamp',
    'publisher': 'vendor'
}

# ... more mappings for other artifact types
```

**Dependencies**: None (pure data)

**Dependents**:
- `feather_config_generator.py`
- `auto_feather_generator.py`

**Impact**: MEDIUM - Affects field mappings

---

### default_wings_loader.py

**Purpose**: Load default wing configurations.

**Key Classes**:
- `DefaultWingsLoader`: Loads default wings

**Key Methods**:
```python
def load_default_wings():
    """Load all default wings from default_wings/ directory"""
    
def get_wing_by_name(wing_name):
    """Get specific default wing"""
```

**Default Wings**:
- `Execution_Proof_Correlation.json` - Correlate execution artifacts
- `User_Activity_Correlation.json` - Correlate user activity
- More wings in `default_wings/` directory

**Dependencies**: `wings/core/wing_model.py`

**Dependents**: `case_initializer.py`

**Impact**: LOW - Provides defaults

---

### default_pipeline_creator.py

**Purpose**: Create default pipeline configurations for cases.

**Key Classes**:
- `DefaultPipelineCreator`: Creates default pipelines

**Key Methods**:
```python
def create_default_pipeline(case_path, feather_configs, wing_configs):
    """
    Create default pipeline
    
    Includes:
    - All generated feathers
    - All default wings
    - Auto-execution enabled
    - Report generation enabled
    """
```

**Dependencies**: `config/pipeline_config.py`

**Dependents**: `case_initializer.py`

**Impact**: LOW - Provides defaults

---

### default_wings/ Subdirectory

**Files**:
- `Execution_Proof_Correlation.json` - Execution proof wing
- `User_Activity_Correlation.json` - User activity wing
- `README.md` - Documentation for default wings

**Purpose**: Default wing configurations for common scenarios

**Impact**: LOW - Provides templates

---

## Common Modification Scenarios

### Scenario 1: Adding Integration with a New Tool

**Files to Modify**:
1. `crow_eye_integration.py` - Add integration method
2. Create new integration module if needed
3. Test with sample data

**Steps**:
1. Identify integration requirements
2. Add integration method
3. Handle data format conversion
4. Test integration
5. Document integration

**Impact**: MEDIUM - Extends integration

---

### Scenario 2: Modifying Auto-Generation Logic

**Files to Modify**:
1. `auto_feather_generator.py` - Update generation logic
2. `feather_config_generator.py` - Update config generation
3. Test with various artifacts

**Steps**:
1. Identify generation issues
2. Update detection logic
3. Update mapping logic
4. Test with sample artifacts
5. Verify feathers are correct

**Impact**: HIGH - Affects auto-generation

---

### Scenario 3: Adding New Default Wing

**Files to Modify**:
1. Create new wing JSON in `default_wings/`
2. `default_wings_loader.py` - Update if needed
3. Test wing with sample data

**Steps**:
1. Design wing configuration
2. Create JSON file
3. Test wing execution
4. Document wing purpose
5. Add to default wings

**Impact**: LOW - Adds default

---

## Troubleshooting

### Issue: Default Wings Don't Show Connected Feathers

**Problem**: When opening default wings, feather connections are not displayed.

**Root Cause**: 
- Default wings reference feathers with relative paths
- Path resolution fails if case directory not set or feathers don't exist

**Solution**:
1. **Improved Path Resolution** (Fixed in v1.1):
   - `FeatherWidget` now has `_resolve_feather_path()` method
   - Checks multiple potential locations
   - Provides visual feedback with color coding:
     - **Green text**: Feather found
     - **Orange text**: Feather not found (needs creation)

2. **Ensure Case Directory is Set**:
   ```python
   # In wings/ui/main_window.py
   for feather in self.wing.feathers:
       feather_widget = FeatherWidget(len(self.feather_widgets) + 1)
       
       # Set case directory BEFORE setting feather spec
       if self.case_directory:
           feather_widget.set_case_directory(self.case_directory)
       
       # Now set feather spec (triggers path resolution)
       feather_widget.set_feather_spec(feather)
   ```

3. **Path Resolution Logic**:
   ```python
   # Checks these locations in order:
   1. case_directory/Correlation/feathers/[filename]
   2. case_directory/Correlation/feathers/[feather_config_name].db
   3. case_directory/Correlation/feathers/[feather_id].db
   4. case_directory/Correlation/feathers/[feather_id]_CrowEyeFeather.db
   5. Relative paths from current directory
   ```

**Verification**:
- Load default wing
- Check feather widgets show green (found) or orange (not found)
- If orange, create feathers using auto-generation
- Reload wing to verify feathers now show green

---

### Issue: No Clear Way to View Correlation Results

**Problem**: After running correlation, users don't know how to view results.

**Solution** (Implemented in v1.1):
1. **"View Results" Button** added to Pipeline Builder
2. **Results Viewer Dialog** opens automatically
3. **Summary Statistics** tab shows overview
4. **Per-Wing Tabs** show detailed matches
5. **Export Functionality** for JSON/CSV/HTML

**Usage**:
```python
# After pipeline execution completes:
1. "View Results" button becomes enabled
2. Click button to open results viewer
3. View summary statistics
4. Click on wing tabs to see matches
5. Export results if needed
```

---

### Issue: Feather Paths Not Resolving

**Symptoms**:
- Feather widgets show orange text
- Paths show as relative (e.g., "feathers/Prefetch_CrowEyeFeather.db")
- Cannot execute wing

**Diagnosis**:
```python
# Check if case directory is set
print(f"Case directory: {feather_widget.case_directory}")

# Check if feather file exists
import os
from pathlib import Path
case_path = Path(case_directory)
feather_path = case_path / "Correlation" / "feathers" / "Prefetch_CrowEyeFeather.db"
print(f"Feather exists: {feather_path.exists()}")
```

**Solutions**:
1. **Set Case Directory**: Ensure case is loaded in Crow-Eye
2. **Generate Feathers**: Run auto-generation to create missing feathers
3. **Check Paths**: Verify feather files exist in expected locations
4. **Manual Path**: Use "Browse" button to manually select feather database

---

## Integration Flow

```
Crow-Eye Application
        ↓
CrowEyeIntegration.initialize_for_case()
        ↓
CaseInitializer.initialize_case()
        ↓
    ┌───┴───┐
    ↓       ↓
AutoFeatherGenerator    DefaultWingsLoader
    ↓                       ↓
FeatherConfigGenerator  Load default wings
    ↓                       ↓
Create feathers         ←───┘
    ↓
DefaultPipelineCreator
    ↓
Create default pipeline
    ↓
Return InitializationResult
```

---

## Case Directory Structure

After initialization:

```
case_directory/
├── correlation_engine/
│   ├── feathers/
│   │   ├── prefetch.db
│   │   ├── shimcache.db
│   │   └── amcache.db
│   ├── wings/
│   │   ├── execution_proof.json
│   │   └── user_activity.json
│   ├── pipelines/
│   │   └── default_pipeline.json
│   └── results/
│       └── (results will be saved here)
└── (other Crow-Eye files)
```

---

## See Also
- [Main Overview](../CORRELATION_ENGINE_OVERVIEW.md)
- [Feather Documentation](../feather/FEATHER_DOCUMENTATION.md)
- [Pipeline Documentation](../pipeline/PIPELINE_DOCUMENTATION.md)
