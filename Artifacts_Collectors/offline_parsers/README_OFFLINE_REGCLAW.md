# Offline Registry Parser (offline_RegClaw.py)

## Overview

The offline registry parser (`offline_RegClaw.py`) provides comprehensive forensic analysis of Windows registry hives without requiring a live system. It extracts 40+ forensic artifact types from registry hives and stores them in a SQLite database for analysis.

## Supported Registry Hives

The parser supports the following registry hive types:

### System Hives
- **SYSTEM**: System configuration, hardware information, services, USB devices
- **SOFTWARE**: Installed software, system-wide settings, network configuration
- **SAM**: User account information (Security Account Manager)
- **SECURITY**: Security policies and settings

### User Hives
- **NTUSER.DAT**: Per-user settings, Desktop ShellBags, Network Location ShellBags
- **UsrClass.dat**: Per-user Windows Explorer ShellBags, file associations, COM registrations

## ShellBags Analysis

ShellBags are Windows Registry structures that track folder view settings and access history. The parser extracts ShellBags from **both** NTUSER.DAT and UsrClass.dat hives for complete coverage.

### Why Both Hives Are Required

Starting from Windows 7, ShellBags data is distributed across two registry hives:

1. **NTUSER.DAT ShellBags**:
   - Desktop folder access
   - Network location browsing
   - Special folders (My Computer, Control Panel, etc.)
   - Registry paths:
     - `Software\Microsoft\Windows\Shell\BagMRU`
     - `Software\Microsoft\Windows\ShellNoRoam\BagMRU`
     - `Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\BagMRU`

2. **UsrClass.dat ShellBags**:
   - Windows Explorer folder navigation (majority of folder access history)
   - ZIP file access (opened as folders)
   - Control Panel interface access
   - Removable device browsing
   - Network share navigation
   - Registry path:
     - `Local Settings\Software\Microsoft\Windows\Shell\BagMRU`

### Registry Path Differences

**IMPORTANT**: The registry paths differ between live registry view and offline hive files:

#### Live Registry (HKEY_CURRENT_USER)
When viewing the live registry, Windows merges both hives:
- NTUSER.DAT is loaded at `HKEY_USERS\{SID}`
- UsrClass.dat is loaded at `HKEY_USERS\{SID}_Classes`
- The merged view shows UsrClass.dat paths as:
  ```
  HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\BagMRU
  ```

#### Offline Hive Files
When parsing hive files directly (offline analysis):
- **NTUSER.DAT** paths remain:
  ```
  Software\Microsoft\Windows\Shell\BagMRU
  ```
- **UsrClass.dat** paths are:
  ```
  Local Settings\Software\Microsoft\Windows\Shell\BagMRU
  ```
  (NOT `Software\Classes\Local Settings\...` - that's only in the merged view)

### UsrClass.dat File Location

UsrClass.dat is typically located at:
```
C:\Users\<USERNAME>\AppData\Local\Microsoft\Windows\UsrClass.dat
```

In offline acquisitions, it may be found in:
```
<case_root>/Target_Artifacts/Registry_Hives/UsrClass.dat
<case_root>/live_acquisition/registry/UsrClass.dat
<case_root>/live_acquisition/registry/<USERNAME>/UsrClass.dat
```

## Usage

### Basic Usage
```bash
python Artifacts_Collectors/offline_parsers/offline_RegClaw.py
```

### With Case Root (Offline Mode)
```bash
python Artifacts_Collectors/offline_parsers/offline_RegClaw.py --case-root <path_to_case>
```

The parser will automatically:
1. Detect all registry hive files (SYSTEM, SOFTWARE, NTUSER.DAT, UsrClass.dat)
2. Validate each hive file
3. Extract forensic artifacts from all hives
4. Process ShellBags from both NTUSER.DAT and UsrClass.dat
5. Store results in `registry_data.db`

## Hive Detection

The parser uses flexible hive detection that supports:
- Files without extensions: `SYSTEM`, `SOFTWARE`, `SAM`, `SECURITY`
- Files with .DAT extension: `NTUSER.DAT`, `UsrClass.dat`
- Backup extensions: `.OLD`, `.SAV`, `.BAK`
- Case-insensitive matching
- Multiple user hives (multiple NTUSER.DAT and UsrClass.dat files)

### Example Detection Output
```
[Detected Hives] Found hive types:
  - SYSTEM: SYSTEM
  - SOFTWARE: SOFTWARE
  - NTUSER: 2 file(s)
      NTUSER.DAT
      user2/NTUSER.DAT
  - USRCLASS: 2 file(s)
      UsrClass.dat
      user2/UsrClass.dat
```

## ShellBags Processing Output

The parser provides detailed output during ShellBags processing:

```
[SHELLBAGS] Collecting folder access history...
  Processing NTUSER[0]: NTUSER.DAT
  Processing NTUSER[1]: user2/NTUSER.DAT
  Processing USRCLASS[0]: UsrClass.dat
  Processing USRCLASS[1]: user2/UsrClass.dat
[✓] Shellbags data collected
```

### Missing UsrClass.dat Warning

If no UsrClass.dat files are found, the parser will display a warning:

```
[SHELLBAGS] Collecting folder access history...
  Processing NTUSER[0]: NTUSER.DAT
  [WARNING] No UsrClass.dat files found - Windows Explorer ShellBags unavailable
[✓] Shellbags data collected
```

This indicates that ShellBags data will be incomplete (missing Windows Explorer folder access history).

## Forensic Artifacts Extracted

The parser extracts 40+ forensic artifact types including:

### Execution Tracking
- UserAssist (program execution tracking)
- BAM/DAM (Background/Desktop Activity Moderator)
- MUICache (application names)

### File/Folder Access
- ShellBags (folder access history from NTUSER.DAT and UsrClass.dat)
- OpenSaveMRU (Open/Save dialog history)
- RecentDocs (recently accessed documents)
- TypedPaths (manually typed paths)

### Autostart Programs
- Run/RunOnce keys (machine and user)
- Services (system services)
- AutoStartPrograms (comprehensive autostart locations)

### USB Devices
- USB device timeline
- USB storage devices
- USB volumes and drive letters

### Network
- Network interfaces
- Network connection history
- Network profiles

### System Information
- Computer name
- Time zone
- Windows Update history
- Shutdown information
- User profiles

### Software
- Installed software inventory
- Browser history (IE TypedURLs)

### Security
- Suspicious indicators
- Malware detection
- Risk scoring

## Database Output

All extracted data is stored in `registry_data.db` (SQLite database) in the `Target_Artifacts` directory.

### ShellBags Table Schema

The `Shellbags` table contains 17 fields:
- `file_name` - Folder/file name
- `short_name` - 8.3 short name
- `shell_item_type` - Type of shell item
- `mru_position` - Most Recently Used position
- `created_date` - Creation timestamp
- `modified_date` - Modification timestamp
- `accessed_date` - Access timestamp
- `attributes` - File attributes
- `file_size` - File size
- `special_folder` - Special folder GUID
- `network_share` - Network share path
- `server_name` - Server name
- `share_name` - Share name
- `drive_letter` - Drive letter
- `mft_record_number` - MFT record number
- `registry_path` - Source registry path
- `analyzing_date` - Analysis timestamp

## Validation

The parser validates all hive files before processing:

```
[Validation] Validating detected hive files...
  ✓ SYSTEM: Valid
  ✓ SOFTWARE: Valid
  ✓ NTUSER[0]: Valid (NTUSER.DAT)
  ✓ NTUSER[1]: Valid (user2/NTUSER.DAT)
  ✓ USRCLASS[0]: Valid (UsrClass.dat)
  ✓ USRCLASS[1]: Valid (user2/UsrClass.dat)
[Validation] All detected hives are valid
```

Validation checks include:
- File existence
- File readability
- File size (not empty, reasonable size)
- Registry hive format validation

## Error Handling

The parser handles various scenarios gracefully:

- **Missing UsrClass.dat**: Logs warning, continues with NTUSER.DAT only
- **Corrupted UsrClass.dat**: Logs error, skips that file
- **Missing registry paths**: Logs debug message, tries next path
- **Invalid hive files**: Stops processing, displays validation errors

## Performance

Typical processing times:
- Hive detection: < 1 second
- Hive validation: < 1 second per hive
- ShellBags processing: 5-10 seconds per UsrClass.dat file
- Total processing: 2-5 minutes for complete registry analysis

## Comparison: Live vs Offline Analysis

### Live Analysis (Regclaw.py)
- Accesses merged registry view (HKEY_CURRENT_USER)
- Automatically includes both NTUSER.DAT and UsrClass.dat data
- Requires running on live system

### Offline Analysis (offline_RegClaw.py)
- Parses individual hive files directly
- Must explicitly process both NTUSER.DAT and UsrClass.dat
- Works on forensic images and offline acquisitions
- Should produce identical ShellBags results to live analysis

## Troubleshooting

### No ShellBags Found

If no ShellBags are found, check:
1. Are both NTUSER.DAT and UsrClass.dat present?
2. Are the hive files valid (not corrupted)?
3. Check the console output for warnings about missing hives

### Incomplete ShellBags Data

If ShellBags data seems incomplete:
1. Verify UsrClass.dat files are present (check for warning message)
2. Ensure UsrClass.dat files are from the correct user profile
3. Compare record counts with live analysis

### UsrClass.dat Not Detected

If UsrClass.dat is not detected:
1. Check file name (case-insensitive: UsrClass.dat, USRCLASS.DAT, usrclass.dat)
2. Verify file location (should be in same directory as NTUSER.DAT)
3. Check for backup extensions (.OLD, .SAV, .BAK)

## References

For more information about ShellBags forensics:
- [InfoSec Notes - ShellBags](https://notes.qazeer.io/dfir/windows/_artefacts_overview/shellbags)
- [Athena Forensics - Windows ShellBags](https://athenaforensics.co.uk/digital-forensics-windows-shellbags/)
- [Count Upon Security - ShellBags Analysis](https://countuponsecurity.com/2017/11/)

## Version History

### Current Version
- Added UsrClass.dat detection and processing
- Complete ShellBags analysis (NTUSER.DAT + UsrClass.dat)
- Multi-user support (multiple NTUSER.DAT and UsrClass.dat files)
- Enhanced validation and error handling
- Detailed console output and warnings

