# Crow Eye - Windows Forensics Engine

<p align="center">
  <img src="GUI Resources/CrowEye.jpg" alt="Crow Eye Logo" width="200"/>
</p>

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

<div align="center">

**Crow Eye is my full-time mission right now**

I’ve stepped away from contract work to build the Windows forensics tool I always wished existed.

Every star, issue, and future sponsor keeps me in the chair writing parsers instead of taking side gigs.

<a href="https://www.paypal.com/paypalme/CrowEyeDev">
  <img src="https://img.shields.io/badge/PayPal-Support-00d4ff?style=for-the-badge&logo=paypal" />
</a>

</div>

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

- [Technical Notes](#technical-notes)
- [Screenshots](#screenshots)
- [Official Website](#-official-website)
- [Coming Soon Features](#-coming-soon-features)
- [Development Credits](#development-credits)

## Overview

Crow Eye is a comprehensive Windows forensics tool designed to collect, parse, and analyze various Windows artifacts through a user-friendly GUI interface. The tool focuses on extracting key forensic evidence from Windows systems to support digital investigations.

## Created by
Ghassan Elsman

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
