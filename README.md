# Crow Eye - Windows Forensics Engine

<p align="center">
  <img src="GUI Resources/CrowEye.jpg" alt="Crow Eye Logo" width="200"/>
</p>

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)


## Table of Contents
- [Overview](#overview)
- [Created by](#created-by)
- [Supported Artifacts (Live Analysis)](#supported-artifacts-live-analysis)
- [Installation](#installation)
- [How to Use Crow Eye](#how-to-use-crow-eye)
- [Analysis Types](#analysis-types)
- [Custom Artifact Analysis](#custom-artifact-analysis)
- [Search and Export Features](#search-and-export-features)
- [Supported Artifacts and Functionality](#supported-artifacts-and-functionality)
- [Documentation & Contribution](#documentation--contribution)
- [Technical Notes](#technical-notes)
- [Screenshots](#screenshots)
- [Official Website](#-official-website)
- [Correlation Engine](#-correlation-engine)
- [Coming Soon Features](#-coming-soon-features)
- [Development Credits](#development-credits)

## Overview

Crow Eye is a comprehensive Windows forensics tool designed to collect, parse, and analyze various Windows artifacts through a user-friendly GUI interface. The tool focuses on extracting key forensic evidence from Windows systems to support digital investigations.

## Created by
Ghassan Elsman

## Vision: Forensics for Everyone

### Our Mission

Crow-Eye mission is to put the truth of what happened on a computer into the hands of every person — not just experts. We believe digital forensics should be accessible to everyone, regardless of technical background.

**Empowering Everyone**

Whether you're a parent worried about what your teen downloaded, a senior who thinks they might have been scammed, or just someone wondering why their PC feels "off," Crow-Eye analyzes your PC, understands the deep forensic traces Windows leaves behind, and explains them in plain, trustworthy language.

**The Future: Crow-Eye Assistant ("Eye")**

Soon you'll simply ask Crow-Eye Assistant (we call it "Eye"):
- *"Was anyone using my laptop while I was away last weekend?"*
- *"Which program has been secretly connecting to the internet?"*

Eye answers instantly, shows you the proof, and never sends your data anywhere.

### For Digital Forensics Professionals

**Faster, Smarter DFIR**
- Advanced parsing of Windows artifacts
- Detection of evasion techniques
- Proof-of-execution and file activity tracing
- One-click proof-of-execution
- Raw artifact views + correlated views
- Plugin system for custom parsers, correlation rules, and workflow extensions

Crow-Eye lets investigators skip repetitive manual work, focus on complex reasoning, and achieve faster, more accurate results.

### For Business

**Multi-Machine Forensics at Scale**

Crow-Eye goes beyond single-machine analysis with a scalable multi-machine processing engine.

Businesses can:
- Parse and store artifacts from multiple machines
- Maintain historical forensic data (even after Windows deletes it)
- Access device activity anytime during an incident
- Reduce dependency on high-cost forensic solutions
- Gain continuous visibility without enterprise-level budgets

Small and medium businesses finally get the investigative power that only large corporations could afford before. Crow-Eye delivers daily or weekly micro-forensics, giving real security insight without heavy infrastructure.

### Research Platform

**Advancing Windows Forensics**

Crow-Eye is more than software — it's an open research platform accelerating the entire field of Windows forensics.

The project focuses on:
- Publishing detailed documentation on internal artifact structures
- Sharing correlation logic and methodologies
- Enabling peer review, transparency, and academic collaboration
- Contributing to the forensics community's collective knowledge



## Supported Artifacts (Live Analysis)

| Artifact                  | Live | Data Extracted                                                                 |
|---------------------------|------|--------------------------------------------------------------------------------|
| Prefetch                  | Yes  | Execution history, run count, timestamps                                       |
| Registry                  | Yes  | Auto-run, UserAssist, ShimCache, BAM, networks, time zone                     |
| Jump Lists & LNK          | Yes  | File access, paths, timestamps, metadata                                       |
| Event Logs                | Yes  | System, Security, Application events                                           |
| Amcache                   | Yes  | App execution, install time, SHA1, file paths                                  |
| ShimCache                 | Yes  | Executed apps, last modified, size                                             |
| ShellBags                 | Yes  | Folder views, access history, timestamps                                       |
| MRU & RecentDocs          | Yes  | Typed paths, Open/Save history, recent files                                   |
| MFT Parser                | Yes  | File metadata, deleted files, timestamps                                       |
| USN Journal               | Yes  | File changes (create/modify/delete)                                            |
| Recycle Bin               | Yes  | Deleted file names, paths, deletion time                                       |
| SRUM                      | Yes  | App resource usage, network, energy, execution                                 |
| Disks & Partitions    | Yes | Physical disks, partition layout, hidden/unmounted partitions, EFI/Recovery/MSR     |

**Note:** Not all artifacts support offline analysis; it is still under development.

## Installation

### Requirements
These will be installed automatically when you run Crow Eye:
- Python 3.12.4
- Required packages:
  - PyQt5
  - python-registry
  - pywin32
  - pandas
  - streamlit
  - altair
  - olefile
  - windowsprefetch
  - sqlite3
  - colorama
  - setuptools

## How to Use Crow Eye

1. Run Crow Eye as administrator to ensure access to all system artifacts:
   ```bash
   python Crow_Eye.py
   ```
2. The main interface will appear, showing different tabs for various forensic artifacts.
3. Create your case and start the analysis.

## Demo
[![Watch the video](https://img.youtube.com/vi/hbvNlBhTfdQ/maxresdefault.jpg)](https://youtu.be/hbvNlBhTfdQ)

## Analysis Types

Crow Eye offers two primary modes of operation:

### Live Analysis
- Analyzes artifacts directly from the running system.
- Automatically extracts and parses artifacts from their standard locations.
- Provides real-time forensic analysis of the current Windows environment.

### Offline Analysis
- Allows analysis of artifacts from external sources.
- Ideal for examining evidence from different systems.
- Supports forensic investigation of collected artifacts.

### Case Management
- Upon launch, Crow Eye creates a case to organize and save all analysis output.
- Each case maintains a separate directory structure for different artifact types.
- Results are preserved for later review and reporting.

### Interactive Timeline Visualization
- Correlate events in real time across artifacts.

### Advanced Search Engine
- Full-text search across live data.

## Custom Artifact Analysis
To analyze custom artifacts:
1. Navigate to your case directory.
2. Go to the `target artifacts/` folder.
3. Add files to the appropriate subdirectories:
   - `C_AJL_Lnk/`: For LNK files and automatic/custom jump lists.
   - `prefetch/`: For prefetch files.
   - `registry/`: For registry hive files.
4. After adding the files, press "Parse Offline Artifacts" in the Crow Eye interface.

## Search and Export Features
- **Search Bar**: Quickly find specific artifacts or information within the database.
- **Export Options**: Convert analysis results from the database into:
  - CSV format for spreadsheet analysis.
  - JSON format for integration with other tools.
- These features make it easy to further process and analyze the collected forensic data.

## Supported Artifacts and Functionality

### Jump Lists and LNK Files Analysis

**Automatic Parsing:**
- The tool automatically parses Jump Lists and LNK files from standard system locations.

**Custom/Selective Parsing:**
- Copy specific Jump Lists/LNK files you want to analyze.
- Paste them into `CrowEye/Artifacts Collectors/Target Artifacts` or your case directory's `C_AJL_Lnk/` folder.
- Run the analysis.

### Registry Analysis

**Automatic Parsing:**
- Crow Eye automatically parses registry hives from the system.

**Custom Registry Analysis:**
- Copy the following registry files to `CrowEye/Artifacts Collectors/Target Artifacts` or your case directory's `registry/` folder:
  - `NTUSER.DAT` from `C:\Users\<Username>\NTUSER.DAT`.
  - `SOFTWARE` from `C:\Windows\System32\config\SOFTWARE`.
  - `SYSTEM` from `C:\Windows\System32\config\SYSTEM`.

**Important Note:**
- Windows locks these registry files during operation.
- For custom registry analysis of a live system, you must:
  - Boot from external media (WinPE/Live CD).
  - Use forensic acquisition tools.
  - Analyze a disk image.

### Prefetch Files Analysis
- Automatically parses prefetch files from `C:\Windows\Prefetch`.
- For custom analysis, add prefetch files to your case directory's `prefetch/` folder.
- Extracts execution history and other forensic metadata.

### Event Logs Analysis
- Automatic parsing of Windows event logs.
- Logs are saved into a database for comprehensive analysis.

### ShellBags Analysis
- Parses ShellBags artifacts to reveal folder access history and user navigation patterns.

### Recycle Bin Parser
- Parses Recycle Bin ($RECYCLE.BIN) to recover deleted file metadata.
- Extracts original file names, paths, deletion times, and sizes.
- Supports recovery from live systems and disk images.

### MFT Parser
- Parses Master File Table (MFT) for file system metadata.
- Extracts file attributes, timestamps, and deleted file information.
- Supports NTFS file systems on Windows 7/10/11.

### USN Journal Parser
- Parses USN (Update Sequence Number) Journal for file change events.
- Tracks file creations, deletions, modifications with timestamps.
- Correlates with other artifacts for timeline reconstruction.

  ### Storage Forensics Analyzer
- Complete tree view of every physical disk and its partitions
- Color-coded partition types (EFI=blue, Linux=purple, Recovery=orange, Hidden=swap/red, etc.)
- Warnings for bootable USBs, hidden Linux roots, and Intel Rapid Start
- Raw sector magic scanning fallback 

## Documentation & Contribution

### General Documentation

- **[README.md](README.md)**: Project overview, vision, features, and usage guide (this document)
- **[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)**: Complete technical documentation including architecture, components, and development guide
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: Contribution guidelines, coding standards, and development workflows
- **[timeline/ARCHITECTURE.md](timeline/ARCHITECTURE.md)**: Detailed timeline module architecture

### 🔥 Correlation Engine Documentation & Contributing

The Correlation Engine is our most active development area with comprehensive documentation:

**Documentation** (~7,200 lines):
- **[Correlation Engine Overview](correlation_engine/docs/CORRELATION_ENGINE_OVERVIEW.md)** - System overview with architecture diagrams
- **[Engine Documentation](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md)** - Dual-engine architecture, engine selection guide, performance optimization
- **[Architecture Documentation](correlation_engine/ARCHITECTURE.md)** - Component integration and data flow
- **[Feather Documentation](correlation_engine/docs/feather/FEATHER_DOCUMENTATION.md)** - Data normalization system
- **[Wings Documentation](correlation_engine/docs/wings/WINGS_DOCUMENTATION.md)** - Correlation rules
- **[Pipeline Documentation](correlation_engine/docs/pipeline/PIPELINE_DOCUMENTATION.md)** - Workflow orchestration

**Contributing**:
- **[Correlation Engine Contributing Guide](correlation_engine/CONTRIBUTING.md)** - Priority areas, development status, and how to contribute

**Quick Links**:
- [Engine Selection Guide](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md#engine-selection-guide) - Choose the right engine
- [Troubleshooting Guide](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md#troubleshooting) - Common issues and solutions
- [Performance Optimization](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md#performance-and-optimization) - Optimize correlation

### For Contributors

For developers and contributors:
- **General contributions**: Review the [Main Contributing Guide](CONTRIBUTING.md)
- **Correlation Engine contributions** (priority area): See the [Correlation Engine Contributing Guide](correlation_engine/CONTRIBUTING.md)
- Please review the technical documentation before submitting pull requests



## Technical Notes
- The tool incorporates a modified version of the JumpList_Lnk_Parser Python module.
- Registry parsing requires complete registry hive files.
- Some artifacts require special handling due to Windows file locking mechanisms.

## Screenshots
![Screenshot 2025-10-30 064143](https://github.com/user-attachments/assets/f400d4b3-e8f6-4c57-a59e-7f24107bc9e7)

![Screenshot 2025-10-30 064155](https://github.com/user-attachments/assets/20878078-742c-4d7c-b51c-571ba6640f90)

![Screenshot 2025-10-30 064205](https://github.com/user-attachments/assets/f23752e6-6a2b-4617-b665-c139a23676e8)

![Screenshot 2025-10-30 064219](https://github.com/user-attachments/assets/9079a99e-bc42-4690-bec0-ee3c5bffa41c)

![Screenshot 2025-10-30 064237](https://github.com/user-attachments/assets/bcdb9f14-6f13-45f4-a3d8-92871f73ab83)

![Screenshot 2025-10-30 064403](https://github.com/user-attachments/assets/b3f113f5-4cd8-482d-86dd-b0b18ff650a0)

## 🌐 Official Website
Visit our official website: [https://crow-eye.com/](https://crow-eye.com/)

For additional resources, documentation, and updates, check out our dedicated website.

---

## 🧩 Correlation Engine

The **Crow-Eye Correlation Engine** is a correlation system designed to collect and correlate various artifacts into meaningful connections. It works with default correlation rules out of the box, and also allows users to build custom rules tailored to their specific investigation needs.

The engine finds temporal and semantic relationships between different types of forensic artifacts, helping investigators discover connections between events that occurred on a system by correlating data from multiple sources.

**Universal Data Import**: The Correlation Engine can take output from **any forensic tool** in CSV, JSON, or SQLite format and convert it into a Feather database. This means you can correlate data from third-party tools (Plaso, Autopsy, Volatility, etc.) with Crow-Eye's native artifacts, creating a unified correlation analysis across all your forensic data sources.

### 🚧 Development Status

The Correlation Engine is **functional and actively being used**, but is still under **active development** with ongoing enhancements:

**Current Status**:
- ✅ **Feather Builder**: Fully functional - imports CSV/JSON/SQLite from any tool
- ✅ **Wings System**: Fully functional - create and manage correlation rules
- ✅ **Pipeline Orchestration**: Fully functional - automate correlation workflows
- 🔄 **Identity-Based Engine**: Functional and more mature - recommended for production use
- ⚠️ **Time-Based Engine**: Prototype stage - functional but not finalized
- 🔄 **Identity Extractor**: Working but being enhanced for better accuracy
- 🔄 **Semantic Mapping**: Under active implementation
- 🔄 **Correlation Scoring**: Under active implementation

**Recommendations**:
- ✅ **Use Identity-Based Engine** for production investigations (more mature)
- ⚠️ **Time-Based Engine** is available for testing but not yet production-ready
- 📊 **Feather Builder** is stable and ready for all data import needs
- 🎯 **Wings and Pipelines** are production-ready

**What We're Working On**:
- Enhancing identity extraction accuracy across more artifact types
- Implementing comprehensive semantic field mapping
- Finalizing correlation scoring algorithms
- Completing Time-Based Engine development
- Improving performance and optimization

The system is usable now and actively being improved. Feedback and contributions are welcome!

### Key Features

- **🔄 Dual-Engine Architecture**: Choose between Time-Based (O(N²)) and Identity-Based (O(N log N)) correlation strategies
- **📊 Multi-Artifact Support**: Correlate Prefetch, ShimCache, AmCache, Event Logs, LNK files, Jumplists, MFT, SRUM, Registry, and more
- **🔌 Universal Import**: Import CSV/JSON/SQLite output from any forensic tool and convert to Feather databases
- **🎯 Identity Tracking**: Track applications and files across multiple artifacts
- **⚡ High Performance**: Process millions of records with streaming mode
- **🔍 Flexible Rules**: Define custom correlation rules (Wings) with configurable parameters
- **🎨 Professional UI**: Cyberpunk-styled interface with timeline visualization

### System Architecture

The Correlation Engine consists of four main components:

#### 1. 🗄️ Feathers (Data Normalization)

**Purpose**: Transform raw forensic artifacts into a standardized, queryable format.

**What They Are**:
- SQLite databases containing normalized forensic artifact data
- Each feather represents one artifact type (e.g., Prefetch, ShimCache, Event Logs)
- Standardized schema with metadata for efficient querying
- **Universal format** that accepts data from any forensic tool

**How They Work**:
```
Any Tool Output → Feather Builder → Normalized Feather Database
(CSV/JSON/SQLite)                   (SQLite with standard schema)

Examples:
- Plaso CSV → Feather Builder → timeline.db
- Autopsy JSON → Feather Builder → autopsy_artifacts.db
- Volatility CSV → Feather Builder → memory_artifacts.db
- Custom Tool Output → Feather Builder → custom.db
```

**Key Features**:
- **Multi-source import**: SQLite databases, CSV files, JSON files from any tool
- Automatic column mapping and data type detection
- Timestamp normalization to ISO format
- Data validation and error handling
- Optimized indexes for fast correlation

**Supported Import Formats**:
- **CSV**: Any CSV file with headers (from Plaso, Excel exports, custom scripts, etc.)
- **JSON**: Flat or nested JSON from any forensic tool
- **SQLite**: Direct import from other SQLite databases

**Example**:
```
prefetch.db (Feather)
├── feather_metadata (artifact type, source, record count)
├── prefetch_data (executable_name, path, last_executed, hash)
└── Indexes (timestamp, name, path)
```

#### 2. 🎯 Wings (Correlation Rules)

**Purpose**: Define which artifacts to correlate and how to correlate them.

**What They Are**:
- JSON/YAML configuration files that specify correlation rules
- Define time windows, minimum matches, and feather relationships
- Reusable across different cases and datasets

**Key Components**:
- **Correlation Rules**: Time window, minimum matches, anchor priority
- **Feather Specifications**: Which feathers to correlate, weights, requirements
- **Filters**: Optional time period or identity filters

**Example Wing**:
```json
{
  "wing_id": "execution-proof",
  "wing_name": "Execution Proof",
  "correlation_rules": {
    "time_window_minutes": 5,
    "minimum_matches": 2,
    "anchor_priority": ["Prefetch", "SRUM", "AmCache"]
  },
  "feathers": [
    {"feather_id": "prefetch", "weight": 0.4},
    {"feather_id": "shimcache", "weight": 0.3},
    {"feather_id": "amcache", "weight": 0.3}
  ]
}
```

#### 3. ⚙️ Engines (Correlation Strategies)

**Purpose**: Execute correlation logic to find relationships between artifacts.

The Correlation Engine offers two distinct strategies:

##### Time-Based Correlation Engine

**Best For**: Small datasets (< 1,000 records), comprehensive analysis, research

**How It Works**:
1. Collect anchor records from ALL feathers
2. For each anchor, find records within time window from other feathers
3. Apply semantic field matching and weighted scoring
4. Prevent duplicates using MatchSet tracking
5. Return correlation matches with confidence scores

**Complexity**: O(N²) where N = number of anchor records

**Key Features**:
- Comprehensive field-level matching
- Semantic field mapping across artifact types
- Weighted confidence scoring
- Duplicate prevention

##### Identity-Based Correlation Engine

**Best For**: Large datasets (> 1,000 records), production environments, identity tracking

**How It Works**:
1. Extract and normalize identity information from all records
2. Group records by identity (application/file)
3. Create temporal anchors within each identity cluster
4. Classify evidence as primary, secondary, or supporting
5. Return identity-centric correlation results

**Complexity**: O(N log N) where N = number of records

**Key Features**:
- Identity extraction with 40+ field patterns per type
- Multi-feather identity grouping
- Temporal anchor clustering
- Streaming mode for large datasets (> 5,000 anchors)
- Constant memory usage with streaming
- Identity filtering support

**Engine Selection**:
- **< 1,000 records**: Use Time-Based Engine for detailed analysis
- **> 1,000 records**: Use Identity-Based Engine for performance

#### 4. 🔄 Pipelines (Workflow Orchestration)

**Purpose**: Automate complete analysis workflows from feather creation to result generation.

**What They Are**:
- Orchestration layer that ties everything together
- Automate feather creation, wing execution, and report generation
- Support for multiple wings and complex workflows

**Pipeline Workflow**:
1. **Load Configuration**: Read pipeline config with engine type, wings, feathers
2. **Create Engine**: Use EngineSelector to instantiate appropriate engine
3. **Execute Wings**: Run each wing against specified feathers
4. **Collect Results**: Aggregate correlation matches from all wings
5. **Generate Reports**: Save results to database and JSON files
6. **Display Results**: Present in GUI with filtering and visualization

**Example Pipeline**:
```json
{
  "pipeline_name": "Investigation Pipeline",
  "engine_type": "identity_based",
  "wings": [
    {"wing_id": "execution-proof"},
    {"wing_id": "file-access"}
  ],
  "feathers": [
    {"feather_id": "prefetch", "database_path": "data/prefetch.db"},
    {"feather_id": "srum", "database_path": "data/srum.db"},
    {"feather_id": "eventlogs", "database_path": "data/eventlogs.db"}
  ],
  "filters": {
    "time_period_start": "2024-01-01T00:00:00",
    "time_period_end": "2024-12-31T23:59:59"
  }
}
```

### How It All Works Together

```
1. Data Preparation
   Raw Forensic Data → Feather Builder → Feather Databases

2. Configuration
   Wing Configs + Feather References → Pipeline Config

3. Execution
   Pipeline Executor → Engine Selector → Correlation Engine

4. Correlation
   Engine loads Feathers + applies Wing rules → Correlation Results

5. Visualization
   Results Database → Results Viewer GUI
```

### Example Use Case: Finding Execution Proof

**Scenario**: Prove that `malware.exe` was executed on a system

**Step 1: Create Feathers**
```bash
# Import Prefetch, ShimCache, and AmCache data
python -m correlation_engine.feather.feather_builder
```

**Step 2: Create Wing**
```json
{
  "wing_id": "malware-execution",
  "correlation_rules": {
    "time_window_minutes": 5,
    "minimum_matches": 2
  },
  "feathers": ["prefetch", "shimcache", "amcache"]
}
```

**Step 3: Execute Pipeline**
```python
from correlation_engine.pipeline import PipelineExecutor

executor = PipelineExecutor(pipeline_config)
results = executor.execute()
```

**Step 4: View Results**
```
Identity: malware.exe
  Anchor 1 (2024-01-15 10:30:00):
    ✓ Prefetch: malware.exe executed at 10:30:00
    ✓ ShimCache: malware.exe modified at 10:30:15
    ✓ AmCache: malware.exe installed at 10:29:45
  
  Conclusion: Execution proven with 3 corroborating artifacts
```

### Performance Benchmarks

**Time-Based Engine**:
- 100 records: 0.5s
- 1,000 records: 20s
- Best for: < 1,000 records

**Identity-Based Engine**:
- 1,000 records: 2s
- 10,000 records: 15s
- 100,000 records: 2.5 min (with streaming)
- 1,000,000 records: 25 min (with streaming)
- Best for: > 1,000 records

### Documentation

**Comprehensive Documentation** (~7,200 lines):
- **[Correlation Engine Overview](correlation_engine/docs/CORRELATION_ENGINE_OVERVIEW.md)** - System overview with architecture diagrams
- **[Engine Documentation](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md)** - Dual-engine architecture, engine selection guide, performance optimization
- **[Architecture Documentation](correlation_engine/ARCHITECTURE.md)** - Component integration and data flow
- **[Feather Documentation](correlation_engine/docs/feather/FEATHER_DOCUMENTATION.md)** - Data normalization system
- **[Wings Documentation](correlation_engine/docs/wings/WINGS_DOCUMENTATION.md)** - Correlation rules
- **[Pipeline Documentation](correlation_engine/docs/pipeline/PIPELINE_DOCUMENTATION.md)** - Workflow orchestration

**Quick Links**:
- [Engine Selection Guide](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md#engine-selection-guide) - Choose the right engine
- [Troubleshooting Guide](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md#troubleshooting) - Common issues and solutions
- [Performance Optimization](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md#performance-and-optimization) - Optimize correlation

### Getting Started with Correlation Engine

1. **Launch Feather Builder**:
   ```bash
   python -m correlation_engine.main
   ```

2. **Create Feathers**: Import your forensic artifacts (Prefetch, ShimCache, etc.)

3. **Create Wings**: Define correlation rules for your investigation

4. **Create Pipeline**: Configure which wings and feathers to use

5. **Execute**: Run the pipeline and view correlated results

6. **Analyze**: Use the Results Viewer to explore temporal relationships

**Current Status**: 
- ✅ **Functional and Usable** - Core system operational
- 🔄 **Active Development** - Ongoing enhancements to semantic mapping, scoring, and identity extraction
- ✅ **Identity-Based Engine** - Production-ready (recommended)
- ⚠️ **Time-Based Engine** - Prototype stage (functional but not finalized)

### 📚 Correlation Engine Documentation

**Comprehensive Documentation** (~7,200 lines covering all aspects):
- **[Correlation Engine Overview](correlation_engine/docs/CORRELATION_ENGINE_OVERVIEW.md)** - System overview with architecture diagrams
- **[Engine Documentation](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md)** - Dual-engine architecture, engine selection guide, performance optimization
- **[Architecture Documentation](correlation_engine/ARCHITECTURE.md)** - Component integration and data flow
- **[Contribution Guide](correlation_engine/CONTRIBUTING.md)** - How to contribute to the Correlation Engine

**Quick Links**:
- [Engine Selection Guide](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md#engine-selection-guide) - Choose the right engine
- [Troubleshooting Guide](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md#troubleshooting) - Common issues and solutions
- [Performance Optimization](correlation_engine/docs/engine/ENGINE_DOCUMENTATION.md#performance-and-optimization) - Optimize correlation

---

## 🚀 Coming Soon Features
- 📊 **Advanced GUI Views and Reports**
- 🔄 **Enhanced Search Dialog** with advanced filtering and natural language support
- ⏱️ **Enhanced Visualization Timeline** with interactive zooming and event correlation
- 🤖 **AI Integration** for querying results, summarizing findings, and assisting non-technical users with natural language questions

---

If you're interested in contributing to these features or have suggestions for additional forensic artifacts, please feel free to:
- Open an issue with your ideas
- Submit a pull request
- Contact me directly at ghassanelsman@gmail.com

**For Correlation Engine Contributions**:
See the [Correlation Engine Contribution Guide](correlation_engine/CONTRIBUTING.md) for detailed information on:
- Development status and priority areas
- How to contribute to specific components
- Code guidelines and testing requirements
- Documentation standards

## Development Credits
- Jump List/LNK parsing based on work by Saleh Muhaysin
- Created and maintained by Ghassan Elsman
