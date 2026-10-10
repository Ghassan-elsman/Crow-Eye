# MFT Artifact Knowledge

## 📖 Visual Anatomy Reference (binary structure)

For the **byte-level layout** of an MFT record — `FILE0`/`FILE*` signature, fixup array, sequence number, hard-link count, attribute list (`$STANDARD_INFORMATION`, `$FILE_NAME`, `$DATA`), MACB timestamps in `$SIA` vs `$FNA` streams, resident vs non-resident attributes, data runs — consult the interactive anatomy page:

**https://crow-eye.com/eye-describe/mft_anatomy.html**

This is the authoritative answer to *"how is an MFT record structured on disk?"*. The page renders every byte with annotations and walks the structure attribute by attribute. Cite this URL when surfacing MFT byte-layout questions to the user.

For platform context (where the `$MFT` lives on disk, $LogFile, $UsnJrnl, MBR vs GPT, NTFS boot sector): see **https://crow-eye.com/eye-describe/windows_boot_disk_explorer.html**.

The rest of this file covers the **semantic / forensic** side: what MFT proves, what fields mean, how Crow-Eye parses it.

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
The whole $MFT is read through its own data runs (record 0's $DATA), so every
fragment is parsed - including deleted entries (`in_use = 0`). A file's
attributes stored in extension records are merged into its base record.

- `record_number` + `mft_sequence_number` (+ `volume_letter`): the file's identity.
  A record number is reused after a delete; the sequence number says which occupant.
- `file_name`: the long (Win32) name when the record has one; the 8.3 alias only when not.
- `file_size`: the unnamed $DATA stream's real size, resident or not (alternate
  data streams are separate rows in `mft_data_attributes`).
- `in_use`, `is_directory`, `has_ads`, `ads_count`, `file_attributes`
- `created_time`, `modified_time`, `accessed_time`, `mft_modified_time`:
  $STANDARD_INFORMATION times (user-settable - the timestomp target).
- `mft_file_names`: every $FILE_NAME of the record (`namespace` 0 POSIX, 1 Win32,
  2 DOS 8.3, 3 Win32+DOS), with its own four times and `parent_record` /
  `parent_sequence`.

## Database Schema
Database `mft_claw_analysis.db`: `mft_records`, `mft_standard_info`,
`mft_file_names`, `mft_data_attributes`. The MFT joined with the USN journal is
`mft_usn_correlated_analysis.db` -> `mft_usn_correlated`, and renames
(old name -> new name) are `mft_usn_correlated_analysis.db` -> `filename_changes`.

## Timestamp Interpretation
`created_time`, `modified_time`, `accessed_time`, `mft_modified_time` in
`mft_records` are the $STANDARD_INFORMATION times (UTC). `mft_file_names` has
the $FILE_NAME times (`created`, `modified`, `accessed`, `mft_modified`), written
by the kernel - $SI creation later than $FN creation is the classic timestomp
signature. A $SI time of 1601 is a zero FILETIME, not a date.

## Common Queries
- Identify files created in a specific time range
- Find deleted files (`in_use = 0` - the record survives, the data may not)
- Trace file system activity by directory (`reconstructed_path` in the correlated DB)

## SQL Query Templates

**IMPORTANT PRIORITY:** If the database `mft_usn_correlated_analysis.db` exists in the case directory, query it instead of `mft_claw_analysis.db`: it has full paths and both time sets per file.

- **Files and their times (`mft_usn_correlated_analysis.db`):**
  ```sql
  SELECT reconstructed_path, si_creation_time, si_modification_time, fn_creation_time, file_size FROM mft_usn_correlated WHERE has_mft_record = 1 GROUP BY volume_letter, mft_record_number, mft_sequence_number ORDER BY si_modification_time DESC LIMIT 20;
  ```

- **Timestomp candidates (`mft_usn_correlated_analysis.db`):**
  ```sql
  SELECT DISTINCT reconstructed_path, si_creation_time, fn_creation_time FROM mft_usn_correlated WHERE has_mft_record = 1 AND si_creation_time > fn_creation_time AND fn_creation_time >= '2008-01-01' LIMIT 50;
  ```

- **Deleted entries (`mft_claw_analysis.db` - ONLY if the correlated DB is missing):**
  ```sql
  SELECT record_number, mft_sequence_number, file_name, file_size, modified_time FROM mft_records WHERE in_use = 0 ORDER BY modified_time DESC LIMIT 20;
  ```
