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

### ~~correlation_results_view.py~~ *(removed)*

**Status**: Deleted in the gui consolidation — zero instantiations, superseded by the dual `IdentityResultsView` + `TimeBasedResultsViewer` split hosted by `DynamicResultsTabWidget`.

---

### ~~hierarchical_results_view.py~~ *(removed)*

**Status**: Deleted in the gui consolidation — zero instantiations. Was an unfinished prototype that overlapped with the active tree-based viewers.

---

### identity_results_view.py

**Purpose**: Identity-centric tree view of correlation results.

**Tree shape**: `Identity → Sub-Identity → Anchor → Evidence`

**Key Classes**:
- `IdentityResultsView`: Main widget

**Features**:
- Group matches by identity (name, path, hash, composite key)
- Pagination (100 identities/page)
- Compact single-row filter, semantic search, weighted scoring display
- **Cascade expand**: clicking a Sub-Identity opens its anchors and underlying evidence in one click

**Dependencies**: `engine/correlation_result.py`, `results_tab_widget.py`

**Impact**: HIGH — primary identity-results view

---

### timebased_results_viewer.py

**Purpose**: Time-window tree view of correlation results.

**Tree shape**: `Time Window → Identity → Sub-Identity → Anchor → Evidence`

**Key Classes**:
- `TimeBasedResultsViewer`: Main widget

**Features**:
- Group matches by user-adjustable time window (default 3 h)
- Dynamic re-grouping when window size changes
- Shares semantic search with the Identity view
- **Cascade expand** behaviour identical to the Identity view

**Dependencies**: `engine/correlation_result.py`, `identity_results_view.py` (for `_search_semantic_data`)

**Impact**: HIGH — primary time-based results view

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
- `wing_selection_dialog.py` - Select wings
- `pipeline_selection_dialog.py` - Select pipelines

**Purpose**: Modal dialogs for detailed information

**Impact**: LOW - Supporting dialogs

---

### Widget Components

**Files**:
- `scoring_breakdown_widget.py` - Score breakdown

**Purpose**: Reusable UI components

**Impact**: LOW - Supporting widgets

---

### Styling

**Files**:
- `ui_styling.py` - UI styling utilities
- `crow_eye_styles.qss` - Qt stylesheet

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
