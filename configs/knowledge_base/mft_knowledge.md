# MFT Artifact Knowledge

## Forensic Significance
The Master File Table (MFT) is the core metadata structure of NTFS file systems.
Each file and directory has an MFT entry containing:
- File creation, modification, access, and MFT change timestamps (MACB)
- File size and attributes
- File name and parent directory
- Resident data for small files

## Crow-eye Parsing Logic
Crow-eye uses `MFT_Claw.py` to parse MFT entries.

**Parser Source**: [Artifacts_Collectors/MFT and USN journal/MFT_Claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/MFT%20and%20USN%20journal/MFT_Claw.py)  
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_MFTClaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_MFTClaw.py)

### Key Fields
- `file_name`: Name of the file or directory
- `creation_time`: File creation timestamp
- `modification_time`: Last write timestamp
- `access_time`: Last access timestamp
- `mft_change_time`: MFT entry modification timestamp
- `file_size`: Size in bytes
- `is_directory`: Boolean flag
- `timestamp`: Parse time (NOT event time)

## Database Schema
Table: `mft_data`

## Timestamp Interpretation
**WARNING**: The `timestamp` column represents when Crow-eye parsed the MFT, NOT file system events.
Use `creation_time`, `modification_time`, `access_time`, and `mft_change_time` for forensic timeline analysis.

## Common Queries
- Identify files created in a specific time range
- Find deleted files (entries marked as unallocated)
- Trace file system activity by user or directory

## SQL Query Templates

**IMPORTANT PRIORITY:** If the database `mft_usn_correlated_analysis.db` exists in the case directory, you MUST query it instead of the standard `mft_data.db`. It contains a unified timeline of MFT and USN data.

- **Query Correlated MFT/USN DB (`mft_usn_correlated_analysis.db`):**
  ```sql
  SELECT reconstructed_path, si_creation_time, si_modification_time, usn_reason, correlation_confidence FROM mft_usn_correlated ORDER BY si_modification_time DESC LIMIT 20;
  ```

- **Query Standard MFT DB (`mft_claw_analysis.db` - ONLY if correlated DB is missing):**
  ```sql
  SELECT file_name, creation_time, modification_time, is_directory FROM mft_data ORDER BY modification_time DESC LIMIT 20;
  ```
