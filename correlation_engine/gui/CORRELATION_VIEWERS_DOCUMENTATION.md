# Correlation Viewers Documentation

This document describes the three correlation result viewers in the Crow-Eye Correlation Engine.

## Overview

The Correlation Engine provides three specialized viewers for displaying correlation results:

| Viewer | File | Purpose |
|--------|------|---------|
| **CorrelationResultsView** | `correlation_results_view.py` | Database-backed hierarchical view with multi-tab support |
| **TimeBasedResultsViewer** | `timebased_results_viewer.py` | Time-based correlation results with compact design |
| **IdentityResultsView** | `identity_results_view.py` | Identity-based correlation with tree hierarchy |

---

## 1. CorrelationResultsView

### Location
`Crow-Eye/correlation_engine/gui/correlation_results_view.py`

### Purpose
Display correlation results from a SQLite database with hierarchical tree view and multi-tab support. Best for viewing persisted results from previous executions.

### Key Features
- **Multi-Tab Support**: Open multiple result sets in separate tabs
- **Database-Backed**: Loads results from SQLite database via `DatabasePersistence`
- **Execution Metadata**: Shows execution details (date, engine type, filters applied)
- **Hierarchical View**: Identity → Anchor → Evidence hierarchy
- **Advanced Filtering**: Time range, identity type, and search filters
- **Context Menus**: Right-click to duplicate tabs, rename, or open in new tab

### Main Classes

```python
class CorrelationResultsView(QWidget):
    """
    Display correlation results in hierarchical tree view with multi-tab support.
    
    Args:
        db_path: Path to correlation database
        execution_id: Optional execution ID to load initially
        parent: Parent widget
    """
```

### Usage Example

```python
from correlation_engine.gui.correlation_results_view import CorrelationResultsView

# Create viewer with database path
viewer = CorrelationResultsView(
    db_path="path/to/correlation.db",
    execution_id=1  # Optional: load specific execution
)

# Load a specific execution
viewer.load_execution(execution_id=5)

# Apply filters
viewer.apply_filters()
```

### UI Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Execution Metadata                                          │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Execution ID: 1 | Date: 2025-12-21 | Engine: Identity   │ │
│ │ Pipeline: Default | Wing: Application Execution Proof   │ │
│ │ Statistics: Duration: 2.5s | Records: 50,000 | Matches: 150 │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ [Tab: All Results] [Tab: Execution 1] [Tab: Execution 2]    │
├─────────────────────────────────────────────────────────────┤
│ Filters: Start: [____] End: [____] Type: [All▼] Search: [__]│
├─────────────────────────────────────────────────────────────┤
│ Summary Statistics                                          │
│ Total: 150 | Duplicates: 5 | Validation Failures: 0        │
├─────────────────────────────────────────────────────────────┤
│ Results Table                                               │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Match ID | Anchor Time | Feathers | Path | App | Score │ │
│ │ abc123   | 2025-12-21  | SRUM,Pre | C:\..| chr | 0.95  │ │
│ │ def456   | 2025-12-21  | SRUM     | C:\..| not | 0.80  │ │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ Details Panel                                               │
│ Selected match details shown here...                        │
├─────────────────────────────────────────────────────────────┤
│                                            [Export Results] │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. TimeBasedResultsViewer

### Location
`Crow-Eye/correlation_engine/gui/timebased_results_viewer.py`

### Purpose
Display time-based correlation results with a compact, modern design. Optimized for viewing results from the Time-Based Correlation Engine.

### Key Features
- **Compact Design**: Summary and filters on single row
- **Weighted Scoring Support**: Color-coded scores with interpretation
- **Dynamic Tabs**: One tab per wing with match counts
- **Inline Filtering**: Application, file path, and score filters
- **Match Details**: Feather records with semantic highlighting

### Main Classes

```python
class TimeBasedResultsViewer(QWidget):
    """
    Main widget for time-based correlation results with dynamic tabs.
    
    Features:
    - Compact layout matching identity view design
    - Wider tabs with smaller text for full names
    - Weighted scoring visualization
    """

class TimeBasedResultsTableWidget(QTableWidget):
    """Table widget for displaying time-based correlation matches."""
    
class TimeBasedMatchDetailViewer(QWidget):
    """Widget for displaying time-based match details."""

class TimeBasedFilterPanelWidget(QWidget):
    """Widget for filtering time-based results."""
```

### Usage Example

```python
from correlation_engine.gui.timebased_results_viewer import TimeBasedResultsViewer

# Create viewer
viewer = TimeBasedResultsViewer()

# Load results from output directory
viewer.load_results(
    output_dir="path/to/output",
    wing_id="wing_123",
    pipeline_id="pipeline_456"
)
```

### UI Layout

```
┌─────────────────────────────────────────────────────────────┐
│ [Summary] [⏱️ Application Execution (150)] [⏱️ User Activity (75)]│
├─────────────────────────────────────────────────────────────┤
│ Matches: 150 | Avg Score: 0.85 | Avg Feathers: 2.3 | Scoring: Weighted │ App: [____] Path: [____] Min: [===] Reset │
├─────────────────────────────────────────────────────────────┤
│ Results Table                                               │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ID  | Timestamp  | Score | Interp | Feathers | App     │ │
│ │ abc | 2025-12-21 | 0.95  | Confirm| 3        | chrome  │ │
│ │ def | 2025-12-21 | 0.75  | Likely | 2        | notepad │ │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ Match Details                                               │
│ Match ID: abc123 | Timestamp: 2025-12-21 10:30:00          │
│ Feather Count: 3 | Time Spread: 45.0 seconds               │
│ Feather Records: SRUM, Prefetch, AmCache                   │
└─────────────────────────────────────────────────────────────┘
```

### Styling

The viewer uses a dark theme with blue accents:

```css
QTabBar::tab {
    padding: 4px 12px;
    font-size: 8pt;
    min-width: 150px;
    max-width: 250px;
}
QTabBar::tab:selected {
    background-color: #2d2d2d;
    color: #2196F3;
}
```

---

## 3. IdentityResultsView

### Location
`Crow-Eye/correlation_engine/gui/identity_results_view.py`

### Purpose
Display identity-based correlation results with a hierarchical tree structure. Shows Identity → Anchor → Evidence relationships.

### Key Features
- **Tree Hierarchy**: Identity (🔷) → Anchor (⏱️) → Evidence (📄)
- **Compact Statistics**: Feather contribution, identity types, evidence roles
- **Multi-Feather Tracking**: Shows which feathers contributed to each identity
- **Expandable Details**: Double-click for detailed view dialogs

### Main Classes

```python
class IdentityResultsView(QWidget):
    """
    Compact Identity-Based Correlation Results View.
    
    Features:
    - Compact layout with summary and filters on same row
    - Tree view matching app background
    - Smaller tab text
    - Compact statistics tables
    """

class IdentityDetailDialog(QDialog):
    """Compact detail dialog for identity/anchor/evidence."""
```

### Usage Example

```python
from correlation_engine.gui.identity_results_view import IdentityResultsView

# Create viewer
viewer = IdentityResultsView()

# Load from dictionary
viewer.load_results({
    'identities': [...],
    'statistics': {
        'total_identities': 50,
        'total_anchors': 150,
        'total_evidence': 500
    },
    'feather_metadata': {...}
})

# Or load from CorrelationResult object
viewer.load_from_correlation_result(correlation_result)
```

### UI Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Identities: 50 | Anchors: 150 | Evidence: 500 | Time: 2.5s | Feathers: 5 │ Search: [____] [All▼] [1▼] Reset │
├─────────────────────────────────────────────────────────────┤
│ Results Tree                                                │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 🔷 chrome.exe          | SRUM, Prefetch | 25 evidence   │ │
│ │   ⏱️ Anchor            | SRUM, Prefetch | 2025-12-21    │ │
│ │     📄 SRUM            | srum_app...    | 10:30:00      │ │
│ │     📄 Prefetch        | prefetch       | 10:30:15      │ │
│ │   ⏱️ Anchor            | SRUM           | 2025-12-21    │ │
│ │ 🔷 notepad.exe         | Prefetch       | 10 evidence   │ │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────┐ ┌───────────┐ ┌───────────┐            │
│ │ Feather Contrib │ │ Types     │ │ Roles     │            │
│ │ SRUM    | 500   │ │ Name | 40 │ │ Primary|50│            │
│ │ Prefetch| 300   │ │ Path | 10 │ │ Second|100│            │
│ └─────────────────┘ └───────────┘ └───────────┘            │
└─────────────────────────────────────────────────────────────┘
```

### Tree Item Structure

```python
# Identity item (top level)
🔷 chrome.exe | SRUM, Prefetch | | 25 | 

# Anchor item (child of identity)
⏱️ Anchor | SRUM, Prefetch | 2025-12-21 10:30:00 | 5 | Prefetch

# Evidence item (child of anchor)
📄 SRUM | srum_applicationusage | 10:30:00 | 1 | SRUM
```

---

## Comparison Table

| Feature | CorrelationResultsView | TimeBasedResultsViewer | IdentityResultsView |
|---------|------------------------|------------------------|---------------------|
| **Data Source** | SQLite Database | JSON Files | Dictionary/Object |
| **View Type** | Table + Tree | Table | Tree |
| **Multi-Tab** | ✅ Closable tabs | ✅ Wing tabs | ❌ Single view |
| **Hierarchy** | Identity→Anchor→Evidence | Flat matches | Identity→Anchor→Evidence |
| **Filtering** | Time, Type, Search | App, Path, Score | Search, Feather, Min |
| **Statistics** | Summary panel | Inline labels | Bottom tables |
| **Best For** | Historical analysis | Time-based results | Identity tracking |

---

## Integration with Engines

### Time-Based Engine → TimeBasedResultsViewer

```python
from correlation_engine.engine.time_based_engine import TimeBasedCorrelationEngine
from correlation_engine.gui.timebased_results_viewer import TimeBasedResultsViewer

# Run correlation
engine = TimeBasedCorrelationEngine()
result = engine.execute_wing(wing, feather_paths)

# Display results
viewer = TimeBasedResultsViewer()
viewer._create_wing_tab(wing.wing_name, result.matches)
```

### Identity-Based Engine → IdentityResultsView

```python
from correlation_engine.engine.identity_correlation_engine import IdentityBasedEngineAdapter
from correlation_engine.gui.identity_results_view import IdentityResultsView

# Run correlation
engine = IdentityBasedEngineAdapter(config)
result = engine.execute_wing(wing, feather_paths)

# Display results
viewer = IdentityResultsView()
viewer.load_from_correlation_result(result)
```

---

## Styling Guidelines

All viewers follow a consistent dark theme:

```css
/* Background */
background-color: transparent;  /* Inherit from app */
alternate-background-color: rgba(255,255,255,0.02);

/* Headers */
QHeaderView::section {
    background-color: #2196F3;
    color: white;
    font-size: 8pt;
    font-weight: bold;
}

/* Selection */
QTableWidget::item:selected,
QTreeWidget::item:selected {
    background-color: #0d47a1;
}

/* Tabs */
QTabBar::tab:selected {
    color: #2196F3;
}
```

---

## Common Patterns

### Loading Results

```python
# From file
viewer.load_results(output_dir="path/to/output")

# From object
viewer.load_from_correlation_result(result)

# From dictionary
viewer.load_results({
    'identities': [...],
    'statistics': {...}
})
```

### Filtering

```python
# Apply filters
filters = {
    'application': 'chrome',
    'file_path': 'Program Files',
    'score_min': 0.5
}
table.apply_filters(filters)

# Reset filters
viewer._reset_filters()
```

### Exporting

```python
# Export to JSON
viewer.export_results()  # Opens file dialog
```

---

## File Structure

```
Crow-Eye/correlation_engine/gui/
├── __init__.py                      # Exports viewers
├── correlation_results_view.py      # Database-backed viewer
├── timebased_results_viewer.py      # Time-based viewer
├── identity_results_view.py         # Identity-based viewer
├── results_viewer.py                # Legacy/shared components
├── scoring_breakdown_widget.py      # Weighted scoring display
├── match_detail_dialog.py           # Match detail popup
└── CORRELATION_VIEWERS_DOCUMENTATION.md  # This file
```
