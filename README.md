# Crow Eye

<p align="center">
  <img src="GUI Resources/CrowEye.jpg" alt="Crow Eye Logo" width="200"/>
</p>

## Overview

Crow Eye is an open-source Windows forensic investigation tool designed to collect, analyze, and visualize various Windows artifacts. It features a modular architecture with specialized components for artifact collection, data processing, and visualization through a cyberpunk-themed GUI.

## Features

### Artifact Collection

Crow Eye can collect and parse the following Windows artifacts:

- **Prefetch Files**: Extract program execution history from Windows Prefetch files
- **Registry Hives**: Analyze Windows Registry for forensic artifacts (UserAssist, ShimCache, BAM, etc.)
- **Amcache**: Extract application execution history from Amcache.hve
- **Event Logs**: Parse Windows Event Logs for security events
- **Jump Lists & LNK Files**: Process AutomaticDestinations-MS, CustomDestinations, Jump Lists, and LNK files
- **Shim Cache**: Extract data from the Application Compatibility Shim Cache

### Data Correlation

Crow Eye correlates evidence across different artifacts:

- Cross-reference execution evidence between Prefetch, Amcache, and Registry
- Compare timestamps to identify potential anomalies
- Link related artifacts for comprehensive analysis

### Cyberpunk UI

The interface features a distinctive dark/cyberpunk theme:

- Dark backgrounds with neon accents
- Custom-styled tables, buttons, and dialogs
- Animated components for visual feedback

## Getting Started

### Prerequisites

- Windows operating system (Windows 7/10/11)
- Python 3.7 or higher
- Administrator privileges (for accessing certain artifacts)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Ghassan-Elsman/Crow-Eye.git
   cd Crow-Eye
   ```

2. Run the main application with administrator privileges:
   ```bash
   python "Crow Eye.py"
   ```

   The application will automatically set up a virtual environment and install the required dependencies.

### Usage

#### Creating a New Case

1. Launch Crow Eye
2. Click on "New Case" in the main menu
3. Enter a case name and select a location to store case files
4. Click "Create Case"

#### Collecting Artifacts

1. Open a case
2. Navigate to the artifact collection tab
3. Select the artifacts you want to collect
4. Click "Collect Artifacts"

#### Analyzing Data

1. Navigate to the analysis tab
2. Select the artifacts you want to analyze
3. Use the search and filter functions to find specific information
4. View correlations between different artifacts

## Documentation

Crow Eye includes comprehensive documentation to help users and contributors:

- **[CROW_EYE_TECHNICAL_DOCUMENTATION.md](CROW_EYE_TECHNICAL_DOCUMENTATION.md)**: Comprehensive technical documentation including architecture, components, and development workflows
- **[CROW_EYE_CONTRIBUTION_GUIDE.md](CROW_EYE_CONTRIBUTION_GUIDE.md)**: Contribution guidelines and documentation index

## Project Structure

```
Crow-Eye/
├── Artifacts_Collectors/       # Specialized parsers for Windows artifacts
├── data/                       # Data management components
├── ui/                         # UI components
├── utils/                      # Utility functions
├── GUI Resources/              # UI assets and resources
├── config/                     # Case configuration files
├── Crow Eye.py                 # Main application entry point
├── styles.py                   # UI styling definitions
└── GUI_resources.py            # Compiled UI resources
```

## Contributing

Contributions are welcome! Please see [CROW_EYE_CONTRIBUTION_GUIDE.md](CROW_EYE_CONTRIBUTION_GUIDE.md) for guidelines on how to contribute to Crow Eye.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Thanks to all contributors who have helped make Crow Eye better
- Special thanks to the open-source forensic community for their valuable resources and tools
