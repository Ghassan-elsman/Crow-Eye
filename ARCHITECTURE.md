# Crow Eye Architecture Documentation

## Overview

Crow Eye is an open-source Windows forensic investigation tool designed to collect, analyze, and visualize various Windows artifacts. The application follows a modular architecture with specialized components for artifact collection, data processing, and visualization through a cyberpunk-themed GUI.

## Core Components

### 1. Main Application (`Crow Eye.py`)

The main application serves as the entry point and orchestrator for the entire system. It handles:

- **Environment Setup**: Creates and manages a virtual environment with required dependencies
- **UI Initialization**: Sets up the PyQt5-based user interface with cyberpunk styling
- **Artifact Collection Coordination**: Invokes the appropriate artifact collectors based on user actions
- **Data Visualization**: Displays collected artifacts in tables and other UI components
- **Case Management**: Handles case creation, loading, and configuration persistence

### 2. Artifact Collectors (`Artifacts_Collectors/`)

Specialized modules for extracting and parsing different Windows forensic artifacts:

- **`amcacheparser.py`**: Parses Amcache.hve files to extract application execution history
- **`Prefetch_claw.py`**: Extracts data from Windows Prefetch files for program execution evidence
- **`Regclaw.py`**: Analyzes Windows Registry hives for forensic artifacts
- **`offline_RegClaw.py`**: Handles offline registry analysis scenarios
- **`WinLog_Claw.py`**: Parses Windows Event Logs
- **`A_CJL_LNK_Claw.py`**: Processes AutomaticDestinations-MS, CustomDestinations, Jump Lists, and LNK files
- **`shimcash_claw.py`**: Extracts data from the Application Compatibility Shim Cache

Each collector follows a similar pattern:
1. Locate and access the artifact source
2. Parse the binary data into structured information
3. Store results in SQLite databases for efficient querying
4. Provide JSON output for interoperability

### 3. UI Components (`ui/`)

- **`component_factory.py`**: Factory class for creating consistent UI elements
- **`Loading_dialog.py`**: Custom loading dialog with cyberpunk styling

### 4. Styling (`styles.py`)

Centralized styling definitions that implement the dark/cyberpunk theme:

- **Color Palette**: Defines the application's color scheme
- **Component Styles**: Provides consistent styling for UI elements
- **Animation Effects**: Defines transitions and visual effects

### 5. Utilities (`utils/`)

- **`file_utils.py`**: Helper functions for file operations
- **`error_handler.py`**: Error handling and logging utilities

### 6. Data Management (`data/`)

- **`base_loader.py`**: Base class for data loading operations
- **`registry_loader.py`**: Specialized loader for registry data

## Data Flow

1. **User Initiates Analysis**: Through the GUI, the user selects artifacts to analyze
2. **Artifact Collection**: The appropriate collector module is invoked to extract data
3. **Data Storage**: Parsed artifacts are stored in SQLite databases
4. **Data Loading**: The main application loads data from databases into UI tables
5. **Visualization**: Data is presented to the user through the styled UI components

## Key Features

### Case Management

Crow Eye implements a case-based workflow:
- Cases can be created, opened, and managed
- Case configurations are stored as JSON in the `config/` directory
- The last opened case is tracked for convenience

### Artifact Correlation

The application correlates evidence across different artifacts:
- Execution evidence is cross-referenced between Prefetch, Amcache, and Registry
- Timestamps are compared to identify potential anomalies
- Related artifacts are linked for comprehensive analysis

### Cyberpunk UI

The interface features a distinctive dark/cyberpunk theme:
- Dark backgrounds with neon accents
- Custom-styled tables, buttons, and dialogs
- Animated components for visual feedback

## Technical Implementation

### Dependencies

Crow Eye relies on several key libraries:
- **PyQt5**: For the graphical user interface
- **python-registry**: For parsing Windows Registry hives
- **pywin32**: For Windows-specific functionality
- **pandas**: For data manipulation
- **streamlit**: For additional visualization capabilities
- **windowsprefetch**: For prefetch file parsing

### Database Schema

Each artifact type has its own database schema optimized for the specific data it contains. For example, the Amcache parser uses tables like:
- InventoryApplication
- InventoryApplicationFile
- InventoryDriverBinary
- DeviceCensus

## Extension Points

Crow Eye is designed for extensibility:

1. **New Artifact Collectors**: Additional collectors can be added to the `Artifacts_Collectors/` directory
2. **UI Enhancements**: The component factory pattern allows for consistent UI expansion
3. **Visualization Methods**: New visualization techniques can be integrated through the existing framework

## Deployment Considerations

- Requires administrator privileges on Windows systems
- Uses a virtual environment for dependency isolation
- Supports both live system analysis and offline artifact examination