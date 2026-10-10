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
- `volume_letter`, `usn`: the record's position in the journal.
- `filename`: the name AT the time of the event (a rename writes the old name
  in a RENAME_OLD_NAME record and the new one in the RENAME_NEW_NAME after it).
- `frn` / `parent_frn`: file references as text - low 48 bits the MFT record
  number, high 16 bits its sequence number (v3 journals: 32 hex digits).
- `timestamp`: WHEN the change happened (UTC) - the event time.
- `reason`: the change flags, e.g. `DATA_EXTEND | FILE_CREATE | CLOSE`. One change
  to one file writes several records, so count files with DISTINCT frn.
- `parsed_at`: when Crow-Eye parsed it (not event time).

## Database Schema
Database `USN_journal.db`: `journal_events`, and `deleted_entries` (gaps in
the journal - missing USN ranges, not deleted files). Renames paired old -> new
are in `mft_usn_correlated_analysis.db` -> `filename_changes`.

## Timestamp Interpretation
In `journal_events`, `timestamp` IS the event time (UTC) - when the change was
written. `parsed_at` is when Crow-Eye parsed the journal. In
`mft_usn_correlated` the same time is `usn_timestamp`.

## Common Queries
- Track file creation and deletion events
- Renames old -> new (and moves between folders): `filename_changes`
- Correlate with MFT data for comprehensive file history

## SQL Query Templates

**IMPORTANT PRIORITY:** If the database `mft_usn_correlated_analysis.db` exists in the case directory, query it instead of `USN_journal.db`: it carries each event's file path (rebuilt from the journal when the file is no longer in the MFT) and the MFT metadata.

- **Recent changes with paths (`mft_usn_correlated_analysis.db`):**
  ```sql
  SELECT usn_timestamp, COALESCE(usn_filename, fn_filename) AS name, reconstructed_path, usn_reason, has_mft_record FROM mft_usn_correlated WHERE has_usn_event = 1 ORDER BY usn_timestamp DESC LIMIT 20;
  ```

- **Renames, old name -> new name (`mft_usn_correlated_analysis.db`):**
  ```sql
  SELECT rename_time, old_name, new_name, old_parent_path, new_parent_path, is_move FROM filename_changes ORDER BY rename_time DESC LIMIT 20;
  ```

- **Deletions (`USN_journal.db` - ONLY if the correlated DB is missing):**
  ```sql
  SELECT filename, timestamp, reason FROM journal_events WHERE reason LIKE '%FILE_DELETE%' ORDER BY timestamp DESC LIMIT 20;
  ```

- **Files created, counted as files not records (`USN_journal.db`):**
  ```sql
  SELECT date(timestamp) AS day, COUNT(DISTINCT frn) AS files FROM journal_events WHERE reason LIKE '%FILE_CREATE%' GROUP BY day ORDER BY day DESC;
  ```
