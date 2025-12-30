# Correlation Engine GUI

A PyQt5-based desktop application for forensic correlation analysis.

## Features

### Pipeline Manager
- Create and edit pipeline configurations
- Add feathers and wings from configuration library
- Validate pipeline configurations
- Save/load pipelines
- Extract individual components

### Configuration Library
- Browse saved pipelines, feathers, and wings
- Search and filter configurations
- Import/export configurations
- Duplicate and delete configurations

### Execution Controller
- Execute correlation analysis pipelines
- Monitor progress in real-time
- View execution logs
- Configure output directory

### Results Viewer
- Dynamic tabs for each wing's results
- Filter results by application, file path, score
- View detailed match information
- Summary statistics and wing breakdown

## Installation

### Requirements
- Python 3.9+
- PyQt5
- Existing correlation engine modules

### Install Dependencies
```bash
pip install PyQt5
```

## Usage

### Launch the GUI
```bash
python test_gui.py
```

Or from the correlation_engine directory:
```bash
python -m correlation_engine.gui.main
```

### Workflow

1. **Create/Load Pipeline**
   - Go to Pipeline Manager tab
   - Click "Add Feather" to add feather configurations
   - Click "Add Wing" to add wing configurations
   - Fill in pipeline metadata (name, description, case info)
   - Save the pipeline (File → Save Pipeline)

2. **Execute Correlation**
   - Load a pipeline (File → Open Pipeline)
   - Switch to Execution tab
   - Select output directory
   - Click "Execute Correlation"
   - Monitor progress in real-time

3. **View Results**
   - After execution completes, results automatically load
   - Browse results by wing in separate tabs
   - Use filters to narrow down matches
   - Click on matches to view details
   - View summary statistics

### Keyboard Shortcuts
- `Ctrl+N` - New Pipeline
- `Ctrl+O` - Open Pipeline
- `Ctrl+S` - Save Pipeline
- `Ctrl+Shift+S` - Save Pipeline As
- `Ctrl+Q` - Quit

## Architecture

### Main Components

- **MainWindow**: Primary application window with tabbed interface
- **PipelineBuilderWidget**: Create and edit pipeline configurations
- **ConfigurationLibraryWidget**: Browse and manage configurations
- **ComponentDetailPanel**: Display detailed component information
- **ExecutionControlWidget**: Control correlation execution
- **CorrelationEngineWrapper**: Background thread wrapper for engine
- **DynamicResultsTabWidget**: Display results with dynamic tabs
- **ResultsTableWidget**: Sortable, filterable results table
- **MatchDetailViewer**: Detailed match information display
- **FilterPanelWidget**: Filter controls for results

### Integration with Existing Engine

The GUI integrates seamlessly with the existing correlation engine:
- Uses `PipelineConfig`, `FeatherConfig`, `WingConfig` from `correlation_engine.config`
- Executes pipelines using `PipelineExecutor` from `correlation_engine.pipeline`
- Loads results using `CorrelationResult` from `correlation_engine.engine`

## Configuration Files

### Pipeline Configuration
Stored in `demo_configs/pipelines/*.json`

Contains:
- Pipeline metadata (name, description, case info)
- List of feather configurations
- List of wing configurations
- Execution settings

### Feather Configuration
Stored in `demo_configs/feathers/*.json`

Contains:
- Source database and table information
- Column mappings
- Timestamp settings
- Output database path

### Wing Configuration
Stored in `demo_configs/wings/*.json`

Contains:
- Wing metadata (name, description, proves)
- Feather references
- Correlation rules (time window, minimum matches)
- Filters and anchor priority

## Troubleshooting

### GUI doesn't launch
- Ensure PyQt5 is installed: `pip install PyQt5`
- Check Python version: `python --version` (should be 3.9+)

### Pipeline validation fails
- Ensure all feather databases exist
- Check that wing references match feather names
- Verify at least one feather and one wing are included

### Execution fails
- Check output directory permissions
- Verify feather database paths are correct
- Review execution log for specific errors

### Results don't load
- Ensure execution completed successfully
- Check output directory contains result files
- Verify result files are valid JSON

## Development

### Adding New Features

1. Create new widget in `correlation_engine/gui/`
2. Import and integrate into `MainWindow`
3. Connect signals/slots for communication
4. Update this README

### Code Structure
```
correlation_engine/gui/
├── __init__.py
├── main.py                    # Entry point
├── main_window.py             # Main application window
├── pipeline_builder.py        # Pipeline creation/editing
├── config_library.py          # Configuration browser
├── component_detail.py        # Component details display
├── execution_control.py       # Execution orchestration
├── results_viewer.py          # Results display and filtering
└── README.md                  # This file
```

## License

Part of the Crow-Eye forensic toolkit.
