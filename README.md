# Crow Eye - Windows Forensics Tool

<p align="center">
  <img src="GUI Resources/CrowEye.jpg" alt="Crow Eye Logo" width="200"/>
</p>

## Overview

Crow Eye is a comprehensive Windows forensics tool designed to collect, parse, and analyze various Windows artifacts through a user-friendly GUI interface. The tool focuses on extracting key forensic evidence from Windows systems to support digital investigations.

## Created by
Ghassan Elsman

## Installation

### Requirements
It will be installed when you run Crow-Eye
- Python 3.12.4
- The following packages are required to run Crow Eye:
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
   ```
   python Crow_Eye.py
   ```
2. The main interface will appear, showing different tabs for various forensic artifacts
3. Create your case then start the analysis

## Analysis Types

Crow Eye offers two primary modes of operation:

### 1. Live Analysis
- Analyzes artifacts directly from the running system
- Automatically extracts and parses artifacts from their standard locations
- Provides real-time forensic analysis of the current Windows environment

### 2. Offline Analysis
- Allows analysis of artifacts from external sources
- Perfect for examining evidence from different systems
- Supports forensic investigation of collected artifacts

### Case Management
- Upon launch, Crow Eye creates a case to organize and save all analysis output
- Each case maintains a separate directory structure for different artifact types
- Results are preserved for later review and reporting

### Custom Artifact Analysis
To analyze custom artifacts:
1. Navigate to your case directory
2. Go to the `target artifacts/` folder
3. Add files to the appropriate subdirectories:
   - `C_AJL_Lnk/`: For LNK files and automatic/custom jump lists
   - `prefetch/`: For prefetch files
   - `registry/`: For registry hive files
4. After adding the files, press "Parse Offline Artifacts" in the Crow Eye interface

### Search and Export Features
- **Search Bar**: Quickly find specific artifacts or information within the database
- **Export Options**: Convert analysis results from the database into:
  - CSV format for spreadsheet analysis
  - JSON format for integration with other tools
- These features make it easy to further process and analyze the collected forensic data

### Supported Artifacts and Functionality

#### 1. Jump Lists and LNK Files Analysis

**Automatic Parsing:**
- The tool automatically parses Jump Lists and LNK files from standard system locations

**Custom/Selective Parsing:**
- Copy specific Jump Lists/LNK files you want to analyze
- Paste them into `CrowEye/Artifacts Collectors/Target Artifacts` or your case directory's `C_AJL_Lnk/` folder
- Run the analysis

#### 2. Registry Analysis

**Automatic Parsing:**
- Crow Eye automatically parses registry hives from the system

**Custom Registry Analysis:**
- Copy the following registry files to `CrowEye/Artifacts Collectors/Target Artifacts` or your case directory's `registry/` folder:
  - `NTUSER.DAT` from `C:\Users\<Username>\NTUSER.DAT`
  - `SOFTWARE` from `C:\Windows\System32\config\SOFTWARE`
  - `SYSTEM` from `C:\Windows\System32\config\SYSTEM`

**Important Note:**
- Windows locks these registry files during operation
- For custom registry analysis of a live system, you must:
  - Boot from external media (WinPE/Live CD)
  - Use forensic acquisition tools
  - Analyze a disk image

#### 3. Prefetch Files Analysis
- Automatically parses prefetch files from `C:\Windows\Prefetch`
- For custom analysis, add prefetch files to your case directory's `prefetch/` folder
- Extracts execution history and other forensic metadata

#### 4. Event Logs Analysis
- Automatic parsing of Windows event logs
- Logs are saved into a database for comprehensive analysis

## Data Collected by Crow Eye

### Registry Data
- Network interfaces
- Network list (networks the computer accessed)
- Machine auto-run programs
- User auto-run programs
- Last Windows update
- Last Windows shutdown time
- Time zone information

### File Activity Data
- Recent documents
- Searches via Explorer bar
- Typed paths
- Open/Save MRU (Most Recently Used)
- Last save MRU

### Prefetch Files Data
- Executable name
- Run counts
- File size
- Last modified time
- Last accessed time
- Creation time
- File node
- Inode number
- Device ID
- User UID
- Group UID

### Jump Lists and LNK Files Data
- Source name
- Source path
- Owner UID
- Group UID
- Time accessed
- Time created
- Time modified
- Data flag
- Local path
- File size header size
- Show window settings
- File permissions
- Device ID
- Inode number

### Event Logs Analysis
- Application logs
- System logs
- Security logs

### ShimCache Data
- Application path
- Last modified time
- Process execution flag
- File size
- Last update time

### AmCache Data
- Application full path
- File size
- SHA1 hash
- Compilation time
- Installation time
- Last modification time
- Product name
- Company name
- File description
- Original file name
- Program ID

### MFT Data

### USN Journal Data

## Technical Notes
- The tool incorporates a modified version of the JumpList_Lnk_Parser Python module
- Registry parsing requires complete registry hive files
- Some artifacts require special handling due to Windows file locking mechanisms

## Screenshots
![Screenshot 1](https://github.com/user-attachments/assets/a768a871-b9aa-4e9b-a8d8-3d12b0439865)
![Screenshot 2](https://github.com/user-attachments/assets/a937f1ca-4b2d-4365-809e-4dc71ae2650d)
![Screenshot 3](https://github.com/user-attachments/assets/c63ebbcc-a88d-468e-81ea-1c610b5e3345)
![Screenshot 4](https://github.com/user-attachments/assets/532ff85e-ae66-4434-ae01-79a8ea151f48)

## 🌐 Official Website
Visit our official website: [https://croweye.pages.dev/](https://croweye.pages.dev/)

For additional resources, documentation, and updates, check out our dedicated website.

## 🚀 Coming Soon Features

- 🗑️ **Recycle Bin Parser**
- - 🧠 **Enhanced Binary Parsing** for RecentDocs, MRU, and ShellBags  
- ⚡ **SRUM Parser** (System Resource Usage Monitor analysis)
- 🔍 **Timeline Visualization**  
- 📊 **Advanced GUI Views and Reports**
- 🧩 **Correlation Engine** (linking MFT, USN, Prefetch, and LNK)  


If you're interested in contributing to these features or have suggestions for additional forensic artifacts, please feel free to:

* Open an issue with your ideas
* Submit a pull request
* Contact me

## Development Credits
- Jump List/LNK parsing based on work by Saleh Muhaysin
- Created and maintained by Ghassan Elsman
