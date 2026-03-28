# Offline MFT-USN Correlation

## Overview

The offline MFT-USN correlator automatically runs when both MFT and USN databases exist in a case directory. It creates a comprehensive correlated database that combines MFT (Master File Table) and USN (Update Sequence Number) journal data for forensic analysis.

## Automatic Correlation

Correlation is automatically triggered in the following scenarios:

### 1. After Offline USN Parsing
When `offline_USNClaw.py` successfully parses a USN journal file, it automatically checks for an existing MFT database and runs correlation if found.

```bash
python Artifacts_Collectors/offline_parsers/offline_USNClaw.py <case_path>
```

**Output:**
```
[Offline USN] Successfully parsed 305,252 records
[Offline USN] Checking for MFT database to run correlation...
[Offline MFT] MFT database found - running correlation...
[Offline Correlator] Correlation complete: 202,303 correlated records
```

### 2. After Offline MFT Parsing
When `offline_MFTClaw.py` successfully parses an MFT file, it automatically checks for an existing USN database and runs correlation if found.

```bash
python Artifacts_Collectors/offline_parsers/offline_MFTClaw.py <case_path>
```

**Output:**
```
[Offline MFT] Successfully parsed 202,303 MFT records
[Offline MFT] Checking for USN database to run correlation...
[Offline MFT] USN database found - running correlation...
[Offline Correlator] Correlation complete: 202,303 correlated records
```

### 3. Manual Correlation
You can also run correlation manually if both databases already exist:

```bash
python Artifacts_Collectors/offline_parsers/offline_MFT_USN_Correlator.py <case_path>
```

## Database Locations

All databases are stored in the `Target_Artifacts` subdirectory of the case directory:

```
<case_path>/
└── Target_Artifacts/
    ├── MFT_data.db                          # MFT database (or mft_claw_analysis.db)
    ├── USN_journal.db                       # USN journal database
    └── mft_usn_correlated_analysis.db       # Correlated database (created by correlator)
```

## Correlated Database Schema

The correlated database contains a comprehensive `mft_usn_correlated` table with:

### MFT Core Information
- `mft_record_number` - MFT record number
- `fn_filename` - Filename
- `mft_sequence_number` - Sequence number
- `mft_flags` - MFT flags
- `is_directory` - Directory flag
- `is_deleted` - Deletion flag

### MFT Standard Information
- `si_creation_time` - SI creation timestamp
- `si_modification_time` - SI modification timestamp
- `si_access_time` - SI access timestamp
- `si_mft_entry_change_time` - SI MFT change timestamp
- `si_file_attributes` - SI file attributes

### MFT File Name Information
- `fn_parent_record_number` - Parent record number
- `fn_parent_sequence_number` - Parent sequence number
- `fn_namespace` - Namespace (POSIX, Win32, DOS, etc.)
- `fn_creation_time` - FN creation timestamp
- `fn_modification_time` - FN modification timestamp
- `fn_access_time` - FN access timestamp
- `fn_mft_entry_change_time` - FN MFT change timestamp
- `fn_allocated_size` - Allocated size
- `fn_real_size` - Real size
- `fn_file_attributes` - FN file attributes

### Derived Information
- `reconstructed_path` - Full file path reconstructed from MFT

### USN Journal Information
- `usn_event_id` - USN event ID
- `usn_timestamp` - USN event timestamp
- `usn_reason` - USN reason flags (FILE_CREATE, FILE_DELETE, etc.)
- `usn_source_info` - USN source information
- `usn_file_attributes` - USN file attributes

### Correlation Metadata
- `has_mft_record` - Flag indicating MFT record exists
- `has_usn_event` - Flag indicating USN event exists
- `correlation_confidence` - Confidence level of correlation
- `filename_change_timeline` - Timeline of filename changes
- `namespace_evolution` - Namespace evolution tracking

## Performance

The correlator is optimized for large datasets:

- **MFT Processing**: ~90,000 records/second
- **USN Processing**: Instant (already in database)
- **Correlation**: ~125,000 records/second
- **Total Time**: Typically 2-5 seconds for 200K+ records

## Example Output

```
[Offline Correlator] Found MFT database: C:\...\Target_Artifacts\MFT_data.db
[Offline Correlator] Found USN database: C:\...\Target_Artifacts\USN_journal.db
[Offline Correlator] Starting correlation...

Retrieving MFT data...
Successfully processed 202,303 MFT records in 2.26 seconds

Retrieving USN data...
Successfully fetched 305,252 USN journal events

Correlating MFT and USN data...
============================================================
✓ Correlation complete in 1.62 seconds!
✓ Total records processed: 202,303 (124641.5 records/second)
✓ Records with USN matches: 6,226 (3.1%)
============================================================

[Offline Correlator] Correlation complete!
[Offline Correlator] Correlated records: 202,303
```

## Forensic Analysis

The correlated database enables powerful forensic queries:

### Find files with specific USN events
```sql
SELECT fn_filename, reconstructed_path, usn_timestamp, usn_reason
FROM mft_usn_correlated
WHERE usn_reason LIKE '%FILE_DELETE%'
ORDER BY usn_timestamp DESC;
```

### Find files modified in a time range
```sql
SELECT fn_filename, reconstructed_path, si_modification_time, usn_timestamp
FROM mft_usn_correlated
WHERE si_modification_time BETWEEN '2026-03-20' AND '2026-03-21'
ORDER BY si_modification_time;
```

### Find deleted files with USN events
```sql
SELECT fn_filename, reconstructed_path, is_deleted, usn_reason, usn_timestamp
FROM mft_usn_correlated
WHERE is_deleted = 1 AND has_usn_event = 1
ORDER BY usn_timestamp DESC;
```

## Error Handling

The correlator handles various scenarios gracefully:

- **Missing MFT database**: Skips correlation, provides clear message
- **Missing USN database**: Skips correlation, provides clear message
- **Existing correlated database**: Uses existing database, reports record count
- **Correlation failure**: Logs error but doesn't fail parent operation

## Integration

The correlation is seamlessly integrated into the offline parsing workflow:

1. Run offline MFT parser → Parses MFT → Checks for USN → Runs correlation if found
2. Run offline USN parser → Parses USN → Checks for MFT → Runs correlation if found
3. Both parsers can be run in any order
4. Correlation only runs once (checks for existing correlated database)
5. Manual correlation available if needed

## Notes

- Correlation requires both MFT and USN databases to exist
- The correlator uses the same database paths as the live parser for consistency
- Supports both `MFT_data.db` and `mft_claw_analysis.db` naming conventions
- Correlation is idempotent - running multiple times uses existing database
- The correlated database is stored in the same `Target_Artifacts` directory as source databases
