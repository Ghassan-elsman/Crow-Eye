# Jump List Artifact Knowledge

## Forensic Significance
Jump Lists track recently accessed files and applications in Windows 7+.
They provide evidence of:
- User file access patterns
- Application usage
- File paths and timestamps
- User interaction with specific documents

## Crow-eye Parsing Logic
Crow-eye uses `A_CJL_LNK_Claw.py` to parse Jump List files.

**Parser Source**: [Artifacts_Collectors/A_CJL_LNK_Claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/A_CJL_LNK_Claw.py)  
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_ACJLClaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_ACJLClaw.py)

### Key Fields
- `application_name`: Application that accessed the file
- `file_path`: Full path to the accessed file
- `access_time`: Last access timestamp
- `creation_time`: Jump List entry creation timestamp
- `target_created`: Target file creation timestamp
- `target_modified`: Target file modification timestamp
- `timestamp`: Parse time (NOT event time)

## Database Schema
Table: `jumplist_data`

## Timestamp Interpretation
**WARNING**: The `timestamp` column represents when Crow-eye parsed the Jump List, NOT when files were accessed.
Use `access_time`, `target_created`, and `target_modified` for forensic timeline analysis.

## Common Queries
- Identify recently accessed documents by application (Jump Lists)
- Analyze standalone Windows Shortcuts (LNK files)
- Find files accessed from removable media
- Correlate user activity across applications

## SQL Query Templates
- **Recently Opened Files/Folders (Jump Lists & LNKs):**
  ```sql
  SELECT application_name, file_path, access_time, creation_time FROM jumplist_data ORDER BY access_time DESC LIMIT 20;
  ```
- **Find Specific LNK File Activity:**
  ```sql
  SELECT * FROM jumplist_data WHERE file_path LIKE '%.lnk' ORDER BY access_time DESC LIMIT 10;
  ```
- **Target File Information (Files pointed to by LNKs/Jump Lists):**
  ```sql
  SELECT application_name, file_path, target_created, target_modified FROM jumplist_data WHERE file_path IS NOT NULL LIMIT 20;
  ```
