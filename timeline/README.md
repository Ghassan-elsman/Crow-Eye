# Crow-Eye Forensic Timeline Visualization

The `timeline` component is a core analytical feature of Crow-Eye, designed to aggregate, correlate, and visualize forensic artifacts from various system sources into a unified, chronologically ordered interface. It bridges a robust Python data-processing backend with a modern, responsive React frontend.

## Architecture Overview

The timeline is built using a hybrid architecture:
1. **Frontend (React)**: A Single-Page Application (SPA) that provides the visual interface (e.g., swimlanes, heatmaps, detailed event views). It is hosted within a PyQt5 `QWebEngineView`.
2. **Backend (Python)**: Handles SQLite database connections, data extraction, timestamp normalization, and event correlation.
3. **Bridge (QWebChannel)**: `TimelineBridge` serves as the communication layer, allowing the React frontend to asynchronously call Python methods to query forensic data and receive JSON responses.

### Key Components

#### 1. UI and Integration
- **`timeline_dialog.py`**: The main entry point. It creates the PyQt5 dialog, initializes the `QWebEngineView`, and sets up the `QWebChannel` to load the React application.
- **`timeline_bridge.py`**: The API exposed to the frontend. It contains slots (e.g., `getSessionData`, `getSrumAppData`, `getMftUsnData`) that the React UI calls to fetch data for specific lanes. It handles safe, time-sliced querying to evenly sample large datasets and prevent SQL injection.

#### 2. Data Management (`/data`)
- **`timeline_data_manager.py`**: Central hub for database interactions. It manages a thread-safe connection pool to multiple SQLite artifact databases (e.g., Prefetch, LNK, Registry, BAM, ShellBags, SRUM, MFT, USN). It abstracts the complexities of querying across different database schemas.
- **`timestamp_indexer.py`**: Optimizes time-range queries by indexing timestamp columns in the target databases.
- **`event_aggregator.py` & `power_event_extractor.py`**: Handle condensing raw events into higher-level representations (like system uptime sessions or aggregated heatmaps) to improve UI performance when zoomed out.
- **`progressive_loader.py` & `query_worker.py`**: Facilitate asynchronous, chunked data loading.

#### 3. Correlation (`/correlation`)
- **`correlation_engine.py`**: Identifies temporal and contextual relationships between isolated events. It can group events by exact timestamp, temporal proximity (time window), application, path, or user. It calculates correlation scores to help analysts identify related malicious or benign activities that occurred sequentially.

#### 4. Rendering (`/rendering`)
- Python-side utilities (`event_renderer.py`, `viewport_optimizer.py`, `zoom_manager.py`) that prepare and optimize data structures before they are sent over the bridge to the React frontend, ensuring smooth scrolling and zooming even with thousands of events.

#### 5. Utilities (`/utils`)
- **`timestamp_parser.py` (and `UniversalTimestampParser`)**: A critical forensic component that normalizes timestamps from diverse formats and epochs (e.g., Windows FILETIME, Unix Epoch, Mac/Cocoa Absolute Time, OLE Automation Dates) into standard UTC ISO 8601 strings. It silently filters out corrupted or unrealistic dates.
- **`error_handler.py`**: Provides centralized, graceful error handling for missing databases, locked files, and malformed data.

## Data Flow

1. **Initialization**: The user opens the timeline in Crow-Eye. `TimelineDialog` instantiates the `TimelineBridge` with the current case's `Target_Artifacts` directory and loads the React build.
2. **Time Bounds**: The React UI calls `getTimeBounds()` to determine the absolute start and end dates of the case across all databases.
3. **Data Request**: As the user pans or zooms, the React UI requests data for specific time slices and lanes (e.g., "Give me MFT events between T1 and T2").
4. **Query & Normalization**: `TimelineBridge` translates this into safe SQL queries via `TimelineDataManager`. It parses and normalizes timestamps using `UniversalTimestampParser`.
5. **Delivery**: The JSON-serialized events are returned to the React frontend, which renders them into the appropriate swimlanes.

## Adding New Artifacts

To integrate a new forensic artifact into the timeline:
1. Ensure the artifact's SQLite database is generated in the `Target_Artifacts` directory.
2. Register the database and its timestamp columns in `timeline_data_manager.py` (`ARTIFACT_DB_MAPPING` and `TIMESTAMP_MAPPINGS`).
3. Add a dedicated slot in `timeline_bridge.py` to query the data and apply necessary formatting.
4. Update the React frontend to create a new swimlane or integrate the events into an existing lane.

## Security Considerations
The timeline backend makes extensive use of parameterized queries and positional parameter substitution (specifically for time-slicing in `timeline_bridge.py`) to strictly prevent SQL injection vulnerabilities when handling arbitrary timestamp ranges from the frontend UI.