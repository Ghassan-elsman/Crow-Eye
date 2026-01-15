# GUI Directory Documentation

## Overview

The **gui/** directory provides all user interface components for the correlation engine, including pipeline management, results visualization, timeline views, and configuration editing.

### Purpose
- Provide visual interface for correlation engine
- Manage pipelines, feathers, and wings
- Visualize correlation results
- Display timelines and hierarchical views
- Edit configurations and semantic mappings

---

## Files in This Directory

### main_window.py

**Purpose**: Main application window with tabbed interface.

**Key Classes**:
- `MainWindow`: Main application window
- `PipelineManagerTab`: Custom pipeline management tab

**Tabs**:
1. Pipeline Management - Create and execute pipelines
2. Results View - View correlation results
3. Timeline - Timeline visualization
4. Configuration - Edit configurations

**Dependencies**: All other GUI components

**Impact**: HIGH - Main entry point for GUI

---

### pipeline_management_tab.py

**Purpose**: Pipeline creation and management interface.

**Key Classes**:
- `PipelineManagementTab`: Pipeline management UI

**Features**:
- Create new pipelines
- Add feathers and wings
- Configure pipeline settings
- Execute pipelines
- View execution status

**Dependencies**: `pipeline_builder.py`, `execution_control.py`

**Impact**: MEDIUM - Core pipeline management

---

### correlation_results_view.py

**Purpose**: Display correlation results in table format.

**Key Classes**:
- `CorrelationResultsView`: Results table view

**Features**:
- Display matches in table
- Sort by columns
- Filter results
- Export to CSV/JSON
- View match details

**Dependencies**: `engine/correlation_result.py`

**Impact**: MEDIUM - Primary results view

---

### hierarchical_results_view.py

**Purpose**: Display correlation results in tree/hierarchical format.

**Key Classes**:
- `HierarchicalResultsView`: Tree view of results

**Features**:
- Group by anchor feather
- Expand/collapse groups
- Drill down into matches
- Show match relationships

**Dependencies**: `engine/correlation_result.py`

**Impact**: MEDIUM - Alternative results view

---

### timeline_widget.py

**Purpose**: Timeline visualization of correlation matches.

**Key Classes**:
- `TimelineWidget`: Timeline chart widget

**Features**:
- Display matches on timeline
- Zoom and pan
- Highlight time windows
- Show temporal relationships
- Interactive selection

**Dependencies**: `engine/correlation_result.py`, PyQt5

**Impact**: MEDIUM - Timeline visualization

---

### execution_control.py

**Purpose**: Control pipeline execution with progress tracking.

**Key Classes**:
- `ExecutionControlWidget`: Execution control panel
- `CorrelationEngineWrapper`: Background thread wrapper
- `OutputRedirector`: Redirect stdout/stderr to GUI

**Features**:
- Start/stop execution
- Display progress
- Show console output
- Cancel execution
- Display errors

**Dependencies**: `pipeline/pipeline_executor.py`, `engine/correlation_engine.py`

**Impact**: HIGH - Controls execution

---

### pipeline_builder.py

**Purpose**: Visual pipeline builder with drag-and-drop.

**Key Classes**:
- `PipelineBuilderWidget`: Visual pipeline builder

**Features**:
- Drag-and-drop feathers and wings
- Visual connection display
- Configure components
- Validate pipeline

**Dependencies**: `config/pipeline_config.py`

**Impact**: MEDIUM - Visual pipeline creation

---

### semantic_mapping_viewer.py

**Purpose**: View and edit semantic field mappings.

**Key Classes**:
- `SemanticMappingViewer`: Mapping editor

**Features**:
- View current mappings
- Add new mappings
- Edit existing mappings
- Preview mapping effects
- Validate mappings

**Dependencies**: `config/semantic_mapping.py`

**Impact**: LOW - Mapping management

---

### results_viewer.py

**Purpose**: Comprehensive results viewer with multiple views.

**Key Classes**:
- `ResultsTableWidget`: Table view
- `MatchDetailViewer`: Match details
- `FilterPanelWidget`: Filter controls
- `DynamicResultsTabWidget`: Dynamic tabs for wings

**Features**:
- Multiple result views
- Detailed match information
- Advanced filtering
- Export capabilities

**Dependencies**: `engine/correlation_result.py`

**Impact**: HIGH - Main results interface

---

### timebased_results_viewer.py

**Purpose**: Display Time-Window Scanning Engine results in hierarchical tree format.

**Key Classes**:
- `TimeBasedResultsViewer`: Main viewer widget for time-window results
- `TimeWindowTreeItem`: Tree item representing a time window
- `FeatherGroupTreeItem`: Tree item for feather groups
- `EvidenceTreeItem`: Tree item for individual evidence records

**Features**:
- Hierarchical display: Window → Feather → Evidence
- Semantic column showing semantic mappings
- Time-based filtering and sorting
- Export to CSV/JSON
- Match detail dialogs
- Progress tracking integration
- Streaming mode support

**Tree Structure**:
```
Time Window (2024-01-15 10:30:00 - 10:35:00)
├── Prefetch (5 records)
│   ├── chrome.exe - Execution
│   ├── firefox.exe - Execution
│   └── ...
├── SRUM (3 records)
│   ├── chrome.exe - Network Activity
│   └── ...
└── EventLogs (8 records)
    ├── User Login
    └── ...
```

**Columns**:
1. **Item** - Window/Feather/Evidence name
2. **Timestamp** - Record timestamp
3. **Type** - Artifact type
4. **Semantic** - Semantic mapping value
5. **Score** - Correlation score
6. **Details** - Additional information

**Dependencies**: `engine/time_based_engine.py`, `engine/correlation_result.py`

**Impact**: HIGH - Primary viewer for Time-Window Scanning Engine

---

### identity_results_view.py

**Purpose**: Display Identity-Based Engine results in hierarchical tree format.

**Key Classes**:
- `IdentityResultsView`: Main viewer widget for identity-based results
- `IdentityTreeItem`: Tree item representing an identity
- `SubIdentityTreeItem`: Tree item for sub-identities (paths/hashes)
- `AnchorTreeItem`: Tree item for temporal anchors
- `EvidenceTreeItem`: Tree item for evidence records

**Features**:
- Hierarchical display: Identity → Sub-Identity → Anchor → Evidence
- Semantic column showing semantic mappings
- Identity filtering and search
- Export to CSV/JSON
- Identity detail dialogs
- Anchor detail dialogs
- Evidence classification (primary/secondary/supporting)

**Tree Structure**:
```
Identity: chrome.exe (Application)
├── Sub-Identity: c:/program files/google/chrome/application/chrome.exe
│   ├── Anchor 1 (2024-01-15 10:30:00)
│   │   ├── Prefetch: chrome.exe [PRIMARY]
│   │   ├── SRUM: chrome.exe [PRIMARY]
│   │   └── EventLogs: Process Creation [SECONDARY]
│   └── Anchor 2 (2024-01-15 14:45:00)
│       ├── Prefetch: chrome.exe [PRIMARY]
│       └── AmCache: chrome.exe [SUPPORTING]
└── Sub-Identity: [hash: abc123...]
    └── ...
```

**Columns**:
1. **Item** - Identity/Sub-Identity/Anchor/Evidence name
2. **Timestamp** - Anchor or evidence timestamp
3. **Type** - Identity type or artifact type
4. **Semantic** - Semantic mapping value
5. **Count** - Number of anchors/evidence
6. **Details** - Additional information

**Evidence Classification**:
- **PRIMARY**: One representative record per feather per anchor (green icon)
- **SECONDARY**: Additional timestamped records (blue icon)
- **SUPPORTING**: Non-timestamped context records (gray icon)

**Dependencies**: `engine/identity_correlation_engine.py`, `engine/data_structures.py`

**Impact**: HIGH - Primary viewer for Identity-Based Engine

---

### Dialog Components

**Files**:
- `anchor_detail_dialog.py` - Anchor record details
- `identity_detail_dialog.py` - Identity information
- `match_detail_dialog.py` - Match details
- `wing_selection_dialog.py` - Select wings
- `pipeline_selection_dialog.py` - Select pipelines

**Purpose**: Modal dialogs for detailed information

**Impact**: LOW - Supporting dialogs

---

### Widget Components

**Files**:
- `pipeline_selector_widget.py` - Pipeline selection
- `progress_display_widget.py` - Progress display
- `scoring_breakdown_widget.py` - Score breakdown
- `semantic_filter_panel.py` - Semantic filtering
- `component_detail.py` - Component details
- `config_library.py` - Configuration library
- `identifier_extraction_config_panel.py` - Identifier config

**Purpose**: Reusable UI components

**Impact**: LOW - Supporting widgets

---

### Styling

**Files**:
- `ui_styling.py` - UI styling utilities
- `crow_eye_styles.qss` - Qt stylesheet
- `tooltips_help.py` - Tooltips and help text

**Purpose**: Visual styling and help

**Impact**: LOW - Visual appearance only

---

## Common Modification Scenarios

### Scenario 1: Adding a New Tab to Main Window

**Files to Modify**:
1. `main_window.py` - Add new tab
2. Create new widget file for tab content
3. Connect to backend if needed

**Steps**:
1. Create new widget class
2. Add tab in `MainWindow.__init__()`
3. Connect signals/slots
4. Test functionality

**Impact**: LOW - Extends GUI

---

### Scenario 2: Adding a New Results Visualization

**Files to Modify**:
1. Create new widget file (e.g., `graph_view.py`)
2. `results_viewer.py` - Add new view option
3. Connect to `CorrelationResult` data

**Steps**:
1. Create visualization widget
2. Accept `CorrelationResult` in constructor
3. Render visualization
4. Add to results viewer
5. Test with sample results

**Impact**: LOW - Adds visualization

---

### Scenario 3: Modifying the Timeline Widget

**Files to Modify**:
1. `timeline_widget.py` - Update rendering logic
2. Test with various result sets

**Steps**:
1. Modify rendering code
2. Update interaction handlers
3. Test zoom/pan functionality
4. Verify performance

**Impact**: MEDIUM - Affects timeline display

---

## GUI Architecture

```
MainWindow
├── Pipeline Management Tab
│   ├── Pipeline Builder
│   ├── Execution Control
│   └── Progress Display
├── Results View Tab
│   ├── Correlation Results View
│   ├── Hierarchical Results View
│   └── Match Detail Dialogs
├── Timeline Tab
│   ├── Timeline Widget
│   └── Timeline Filters
└── Configuration Tab
    ├── Semantic Mapping Viewer
    ├── Config Library
    └── Settings
```

---

## See Also
- [Main Overview](../CORRELATION_ENGINE_OVERVIEW.md)
- [Engine Documentation](../engine/ENGINE_DOCUMENTATION.md)
- [Pipeline Documentation](../pipeline/PIPELINE_DOCUMENTATION.md)
