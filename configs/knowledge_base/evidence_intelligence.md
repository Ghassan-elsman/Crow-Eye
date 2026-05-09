# Crow-eye Evidence Intelligence Mapping

This document serves as the master intelligence reference for the EYE AI Assistant to identify which forensic artifacts and database tables to query based on investigative categories.

## 1. App Execution (App Runs)
Use these artifacts to prove a program was executed on the system.

| Artifact | Database | Key Tables | Significance |
| :--- | :--- | :--- | :--- |
| **Prefetch** | `prefetch_data.db` | `prefetch_data` | Primary execution proof. Includes `last_executed`, `run_count`, and `run_times` (up to 8 timestamps). |
| **Amcache** | `amcache.db` | `InventoryApplication`, `InventoryApplicationFile` | Records application installation and execution. High confidence for file paths and hashes. |
| **ShimCache** | `shimcache.db` | `shimcache_entries` | Proof of existence and potential execution. Focus on `last_modified` timestamp. |
| **BAM (Background Activity Moderator)** | `registry_data.db` | `BAM` | Registry-based execution tracking. Provides `last_execution` timestamp for apps. |
| **UserAssist** | `registry_data.db` | `UserAssist` | Tracks GUI-based program execution. Includes `focus_time` and run count. |
| **SRUM** | `srum_data.db` | `srum_application_usage` | Resource usage tracking. Proves an app ran and for how long (CPU/Network). |

## 2. System Browsing & Folder Navigation
Use these artifacts to track user movement through the file system and folder access.

| Artifact | Database | Key Tables | Significance |
| :--- | :--- | :--- | :--- |
| **ShellBags** | `registry_data.db` | `Shellbags` | Records which folders a user opened/viewed in Explorer. Includes `modified_date` of the folder view. |
| **Jump Lists** | `LnkDB.db` | `JLCE`, `Custom_JLCE` | Tracks "Pinned" and "Recent" items in taskbar menus. Proof of user interaction with specific files/folders. |
| **RunMRU** | `registry_data.db` | `RunMRU` | Records commands typed into the 'Run' dialog box (Win+R). |
| **WordWheelQuery** | `registry_data.db` | `WordWheelQuery` | Tracks search terms entered into the Windows Explorer search bar. |

## 3. File Interaction & Opening
Use these artifacts to prove a user opened or interacted with specific files.

| Artifact | Database | Key Tables | Significance |
| :--- | :--- | :--- | :--- |
| **LNK Files** | `LnkDB.db` | `JLCE` (Source_Name) | Shortcuts created automatically by Windows for recently opened files. |
| **OpenSaveMRU** | `registry_data.db` | `OpenSaveMRU` | Tracks files opened or saved through standard Windows dialog boxes. |
| **LastSaveMRU** | `registry_data.db` | `LastSaveMRU` | Specifically tracks the last saved file per application extension. |
| **RecentDocs** | `registry_data.db` | `RecentDocs` (if present) | General list of recently accessed documents in the Registry. |

## 4. File Lifecycle (Creation, Edition, Deletion)
Use these artifacts to track the physical history of files on the disk.

| Category | Artifact | Database | Key Tables |
| :--- | :--- | :--- | :--- |
| **Creation** | **MFT** | `mft_claw_analysis.db` | `mft_standard_info` (created), `mft_file_names` (created). |
| **Edition** | **USN Journal** | `USN_journal.db` | `journal_events` (Look for `File_Modification`, `Data_Extend`, `Data_Overwrite`). |
| **Deletion** | **USN Journal** | `USN_journal.db` | `journal_events` (Look for `File_Delete`). |
| **Deletion** | **Recycle Bin** | `recyclebin_analysis.db` | `recycle_bin_entries`. Provides `deletion_time` and original path. |
| **Correlation** | **MFT-USN** | `mft_usn_correlated_analysis.db` | `mft_usn_correlated`. Best for a unified view of file history. |

## 5. System Events & Connections
| Artifact | Database | Key Tables | Significance |
| :--- | :--- | :--- | :--- |
| **Event Logs** | `Log_Claw.db` | `SystemLogs`, `SecurityLogs`, `ApplicationLogs` | System-wide events, logins (4624), and process starts (4688). |
| **Network List** | `registry_data.db` | `Network_list` | History of connected Wi-Fi and Ethernet networks. |
