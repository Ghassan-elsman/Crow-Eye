# Recycle Bin Artifact Knowledge

## Forensic Significance
The Recycle Bin stores metadata about deleted files.
It provides evidence of:
- File deletion events
- Original file paths
- Deletion timestamps
- File sizes

## Crow-eye Parsing Logic
Crow-eye uses `recyclebin_claw.py` to parse Recycle Bin artifacts ($I and $R files).

**Parser Source**: [Artifacts_Collectors/recyclebin_claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/recyclebin_claw.py)  
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_RecycleBinClaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_RecycleBinClaw.py)

### Key Fields
- `original_filename`: Original file name before deletion
- `original_path`: Full path before deletion
- `deletion_time`: Timestamp when file was deleted
- `file_size`: Size of the deleted file
- `timestamp`: Parse time (NOT event time)

## Database Schema
Table: `recyclebin_data`

## Timestamp Interpretation
**WARNING**: The `timestamp` column represents when Crow-eye parsed the Recycle Bin, NOT when files were deleted.
Use `deletion_time` for forensic timeline analysis.

## Common Queries
- Identify recently deleted files
- Find deleted files from specific paths
- Correlate deletions with other user activity

## SQL Query Templates
- **Deleted Files:**
  ```sql
  SELECT original_filename, deletion_time, file_size FROM recyclebin_data ORDER BY deletion_time DESC LIMIT 20;
  ```
