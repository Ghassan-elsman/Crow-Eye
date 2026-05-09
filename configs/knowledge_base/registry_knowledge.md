# Registry Artifact Knowledge

## Forensic Significance
The Windows Registry contains system and user configuration data.
Forensically relevant areas include:
- User activity (RecentDocs, UserAssist, MUICache)
- Persistence mechanisms (Run keys, Services)
- USB device history
- Network configuration
- Installed software

## Crow-eye Parsing Logic
Crow-eye uses `Regclaw.py` and `offline_RegClaw.py` to parse registry hives.

**Parser Source**: [Artifacts_Collectors/Regclaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/Regclaw.py)  
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_RegClaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_RegClaw.py)

### Key Fields
- `key_path`: Full registry key path
- `value_name`: Registry value name
- `value_data`: Registry value data
- `value_type`: Data type (REG_SZ, REG_DWORD, etc.)
- `last_write_time`: Key last write timestamp
- `timestamp`: Parse time (NOT event time)

## Database Schema
Table: `registry_data`

## Timestamp Interpretation
**WARNING**: The `timestamp` column represents when Crow-eye parsed the registry, NOT when keys were modified.
Use `last_write_time` for forensic timeline analysis.

## Common Queries
- Find persistence mechanisms in Run keys
- Identify recently accessed files via RecentDocs
- Enumerate USB devices
- Check for suspicious services

## SQL Query Templates
- **Last Logged On User (SAM):**
  ```sql
  SELECT * FROM registry_data WHERE key_path LIKE '%SAM\\Domains\\Account\\Users%' AND value_name = 'LastLoggedOnUser';
  ```
- **Recently Opened Files (RecentDocs):**
  ```sql
  SELECT * FROM registry_data WHERE key_path LIKE '%Explorer\\RecentDocs%';
  ```
- **Executed Applications (UserAssist):**
  ```sql
  SELECT * FROM registry_data WHERE key_path LIKE '%UserAssist%';
  ```
- **Persistence (Run Keys):**
  ```sql
  SELECT * FROM registry_data WHERE key_path LIKE '%CurrentVersion\\Run%';
  ```
