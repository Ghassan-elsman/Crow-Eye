# USN Journal Artifact Knowledge

## Forensic Significance
The Update Sequence Number (USN) Journal is a change log for NTFS volumes.
It records file system operations including:
- File creation, deletion, and renaming
- Data modifications
- Attribute changes
- Timestamp updates

## Crow-eye Parsing Logic
Crow-eye uses `USN_Claw.py` to parse USN Journal entries.

**Parser Source**: [Artifacts_Collectors/MFT and USN journal/USN_Claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/MFT%20and%20USN%20journal/USN_Claw.py)  
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_USNClaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_USNClaw.py)

### Key Fields
- `file_name`: Name of the affected file
- `reason`: Type of change (e.g., FILE_CREATE, DATA_EXTEND, FILE_DELETE)
- `usn_timestamp`: Timestamp of the file system operation
- `file_reference_number`: MFT entry reference
- `parent_reference_number`: Parent directory MFT reference
- `timestamp`: Parse time (NOT event time)

## Database Schema
Table: `usn_data`

## Timestamp Interpretation
**WARNING**: The `timestamp` column represents when Crow-eye parsed the USN Journal, NOT when file system events occurred.
Use `usn_timestamp` for forensic timeline analysis.

## Common Queries
- Track file creation and deletion events
- Identify file renaming operations
- Correlate with MFT data for comprehensive file history

## SQL Query Templates

**IMPORTANT PRIORITY:** If the database `mft_usn_correlated_analysis.db` exists in the case directory, you MUST query it instead of the standard `USN_journal.db`. It provides much richer file system context by combining MFT metadata with USN events.

- **Query Correlated MFT/USN DB (`mft_usn_correlated_analysis.db`):**
  ```sql
  SELECT reconstructed_path, usn_reason, usn_timestamp, is_deleted, correlation_confidence FROM mft_usn_correlated WHERE has_usn_event = 1 ORDER BY usn_timestamp DESC LIMIT 20;
  ```

- **Standard USN Deletion Tracking (`USN_journal.db` - ONLY if correlated DB is missing):**
  ```sql
  SELECT file_name, usn_timestamp, reason FROM usn_data WHERE reason LIKE '%FILE_DELETE%' ORDER BY usn_timestamp DESC LIMIT 20;
  ```

- **Standard USN Creation Tracking (`USN_journal.db` - ONLY if correlated DB is missing):**
  ```sql
  SELECT file_name, usn_timestamp, reason FROM usn_data WHERE reason LIKE '%FILE_CREATE%' ORDER BY usn_timestamp DESC LIMIT 20;
  ```
