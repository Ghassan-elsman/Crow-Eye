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
| Artifact          | Live | Data Extracted                          |
|-------------------|------|-----------------------------------------|
| Prefetch          | Yes  | Execution history, run count, timestamps |
| Registry          | Yes  | Auto-run, UserAssist, ShimCache, BAM, networks, time zone |
| Jump Lists & LNK  | Yes  | File access, paths, timestamps, metadata |
| Event Logs        | Yes  | System, Security, Application events    |
| Amcache           | Yes  | App execution, install time, SHA1, file paths |
| ShimCache         | Yes  | Executed apps, last modified, size      |
| ShellBags         | Yes  | Folder views, access history, timestamps |
| MRU & RecentDocs  | Yes  | Typed paths, Open/Save history, recent files |
| MFT Parser        | Yes  | File metadata, deleted files, timestamps |
| USN Journal       | Yes  | File changes (create/modify/delete)     |
| Recycle Bin       | Yes  | Deleted file names, paths, deletion time |
| SRUM              | Yes  | App resource usage, network, energy, execution |

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

## Documentation & Contribution

- **[README.md](README.md)**: Project overview, vision, features, and usage guide (this document)
- **[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)**: Complete technical documentation including architecture, components, and development guide
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: Contribution guidelines, coding standards, and development workflows
- **[timeline/ARCHITECTURE.md](timeline/ARCHITECTURE.md)**: Detailed timeline module architecture

For developers and contributors, please review the technical documentation and contribution guide before submitting pull requests.

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

## 🚀 Coming Soon Features
- 📊 **Advanced GUI Views and Reports**
- 🧩 **Correlation Engine** (Correlates all forensic artifacts)
- 🔎 **Advanced Search Engine and Dialog** for efficient artifact querying
- 🔄 **Enhanced Search Dialog** with advanced filtering and natural language support
- ⏱️ **Enhanced Visualization Timeline** with interactive zooming and event correlation
- 🤖 **AI Integration** for querying results, summarizing findings, and assisting non-technical users with natural language questions

If you're interested in contributing to these features or have suggestions for additional forensic artifacts, please feel free to:
- Open an issue with your ideas
- Submit a pull request
- Contact me directly at ghassanelsman@gmail.com

## Development Credits
- Jump List/LNK parsing based on work by Saleh Muhaysin
- Created and maintained by Ghassan Elsman
