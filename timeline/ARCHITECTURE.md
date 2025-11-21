# Timeline Module Architecture

This document provides a high-level overview of the Crow-Eye Timeline module, designed to help contributors understand how the system is structured, how files connect, and the specific responsibilities of each component.

## System Overview

The Timeline module is a complex visualization system that handles:
1.  **Data Loading**: Efficiently querying millions of forensic artifacts from SQLite databases.
2.  **Visualization**: Rendering events on a zoomable, pannable time axis using OpenGL acceleration.
3.  **Interaction**: Providing filtering, searching, and detailed inspection of events.

## Component Architecture

The system follows a layered architecture separating UI, Logic, and Data.

```text
+-------------------------------------------------------+
|                  UI & Orchestration                   |
|                                                       |
|   [ timeline_dialog.py ] <----> [ filter_bar.py ]     |
|             ^      |                                  |
|             |      v                                  |
|             |   [ event_details_panel.py ]            |
+-------------|-----------------------------------------+
              |
              v
+-------------------------------------------------------+
|                    Visualization                      |
|                                                       |
|   [ timeline_canvas.py ]                              |
|             |                                         |
|             +----> [ rendering/event_renderer.py ]    |
|             |                                         |
|             +----> [ rendering/zoom_manager.py ]      |
|             |                                         |
|             +----> [ rendering/viewport_optimizer.py ]|
+-------------------------------------------------------+
              ^
              |
+-------------------------------------------------------+
|                    Data & Logic                       |
|                                                       |
|   [ data/query_worker.py ]                            |
|             |                                         |
|             v                                         |
|   [ data/timeline_data_manager.py ]                   |
|             |                                         |
|             v                                         |
|   [ utils/timestamp_parser.py ]                       |
|             |                                         |
|             v                                         |
|      [( SQLite DBs )]                                 |
+-------------------------------------------------------+
```

## File Hierarchy & Ownership

This tree diagram shows the ownership structure (who initializes whom).

```text
timeline_dialog.py (Main Controller)
├── filter_bar.py (Top Controls)
├── event_details_panel.py (Bottom/Side Panel)
├── timeline_canvas.py (Visualization View)
│   ├── rendering/event_renderer.py (Drawing Logic)
│   ├── rendering/zoom_manager.py (Zoom/Scale Logic)
│   └── rendering/viewport_optimizer.py (Performance)
├── data/timeline_data_manager.py (Data Access)
│   └── utils/timestamp_parser.py (Utility)
└── data/query_worker.py (Background Thread)
    └── (Uses TimelineDataManager)
```

## File Responsibilities

### 1. Core Orchestration
*   **`timeline_dialog.py`**: The main entry point. It initializes the UI, manages the high-level state (current time range, active filters), and orchestrates communication between the Data Manager and the Canvas. It handles user inputs from the Filter Bar and updates the visualization accordingly.

### 2. Visualization (The "Canvas")
*   **`timeline_canvas.py`**: The heart of the visualization. It uses `QGraphicsView` and `QGraphicsScene` to display the timeline. It handles:
    *   Mouse events (pan, zoom, click).
    *   Coordinate transformations (time ↔ pixels).
    *   Managing the scene graph.
    *   **Key Feature**: Implements an LRU cache for event markers to manage memory.
*   **`rendering/event_renderer.py`**: Responsible for the actual drawing of event markers. It contains the logic for shapes, colors, and selection highlights.
*   **`rendering/zoom_manager.py`**: Manages zoom levels (0-10), calculates time scales, and handles the "Max Zoom Cap" logic.
*   **`rendering/viewport_optimizer.py`**: Determines which events are currently visible and need to be rendered, optimizing performance by culling off-screen items.

### 3. Data Management
*   **`data/timeline_data_manager.py`**: The data access layer. It manages connections to multiple SQLite databases (one per artifact type). It handles:
    *   Connection pooling and thread safety.
    *   Executing SQL queries.
    *   Aggregating results.
*   **`data/query_worker.py`**: Runs queries in a background thread (`QThread`) to prevent the UI from freezing during heavy data loads. It emits signals with progress updates and results.

### 4. Utilities
*   **`utils/timestamp_parser.py`**: A robust utility for parsing various timestamp formats (Unix, Filetime, String) into Python `datetime` objects. It includes failure tracking and warning logs.
*   **`utils/error_handler.py`**: Centralized error handling logic to catch exceptions and display user-friendly error messages.

### 5. UI Components
*   **`filter_bar.py`**: The control panel at the top of the dialog (Date pickers, Checkboxes, Search).
*   **`event_details_panel.py`**: The side/bottom panel that shows raw data for the selected event.

## Data Flow

1.  **Initialization**: `TimelineDialog` starts and calls `TimelineDataManager.get_all_time_bounds()` to determine the global start/end times.
2.  **Loading**: `TimelineDialog` creates a `QueryWorker`.
3.  **Querying**: `QueryWorker` asks `TimelineDataManager` for events within the current view.
4.  **Processing**: `TimelineDataManager` queries SQLite, parses timestamps using `TimestampParser`, and returns a list of event dictionaries.
5.  **Rendering**: `TimelineDialog` passes the events to `TimelineCanvas`.
6.  **Drawing**: `TimelineCanvas` uses `ZoomManager` to determine positions and `EventRenderer` to create graphics items.

## Signal & Event Flow (Connections)

This diagram illustrates how components communicate via PyQt5 Signals and Slots.

```text
User             FilterBar        TimelineDialog      QueryWorker      TimelineCanvas
 |                   |                  |                  |                 |
 | -- Change Filter ->|                  |                  |                 |
 |                   | -- signal ------>|                  |                 |
 |                   |                  | -- start() ----->|                 |
 |                   |                  |                  |                 |
 |                   |                  | <---- signal ----|                 |
 |                   |                  | (progress/done)  |                 |
 |                   |                  |                  |                 |
 |                   |                  | -- render() ---->|                 |
 |                   |                  |                  | -- draw() ----->|
 |                   |                  |                  |                 |
 | -- Zoom/Pan ------------------------------------------------------------>|
 |                   |                  |                  |                 |
 |                   | <---- signal ----| <---- signal -----|                 |
 |                   | (update range)   | (range changed)  |                 |
```

## Key Design Patterns
*   **Observer Pattern**: Signals and Slots (PyQt5) are used extensively for communication between components (e.g., Worker → Dialog → Canvas).
*   **Strategy Pattern**: Different rendering strategies for different zoom levels (Cluster vs. Individual).
*   **Caching**: LRU Cache in `TimelineCanvas` and Connection Pooling in `TimelineDataManager`.

## Contributing Guidelines
*   **Logging**: Use `logger = logging.getLogger(__name__)`. Do not use `print()`.
*   **Thread Safety**: Database connections must be thread-local. Use `TimelineDataManager`'s accessors.
*   **Performance**: Always check `_has_visible_events` or use `ViewportOptimizer` before expensive rendering operations.
