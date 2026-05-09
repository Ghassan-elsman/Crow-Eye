# ShimCache Artifact Knowledge

## Forensic Significance
ShimCache (Application Compatibility Cache) tracks executables that have been run or present on the system.
It provides evidence of:
- Program execution (with caveats)
- File paths and sizes
- Last modification timestamps
- Execution order (via cache position)

## Crow-eye Parsing Logic
Crow-eye uses `offline_ShimCacheClaw.py` to parse ShimCache from registry hives.

**Parser Source**: [Artifacts_Collectors/shimcache_claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/shimcache_claw.py)  
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_ShimCacheClaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_ShimCacheClaw.py)

### Key Fields
- `file_path`: Full path to the executable
- `last_modified`: File modification timestamp
- `file_size`: Size in bytes
- `executed`: Boolean flag (Windows 8+ only)
- `cache_position`: Position in cache (indicates recency)
- `timestamp`: Parse time (NOT event time)

## Database Schema
Table: `shimcache_data`

## Timestamp Interpretation
**WARNING**: The `timestamp` column represents when Crow-eye parsed the artifact, NOT execution time.
Use `last_modified` for forensic timeline analysis.
Note: ShimCache timestamps reflect file modification, not execution time.

## Common Queries
- Identify recently executed programs
- Find executables from suspicious paths
- Correlate with other execution artifacts

## SQL Query Templates
- **Historical Execution Evidence:**
  ```sql
  SELECT file_path, last_modified, executed FROM shimcache_data ORDER BY last_modified DESC LIMIT 20;
  ```
