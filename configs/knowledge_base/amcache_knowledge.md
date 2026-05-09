# Amcache Artifact Knowledge

## Forensic Significance
Amcache.hve is a registry hive that tracks application execution and installation.
It provides evidence of:
- Program execution (even if the executable is deleted)
- File metadata (size, hash, version)
- Installation timestamps
- Publisher information

## Crow-eye Parsing Logic
Crow-eye uses `amcacheparser.py` to parse Amcache.hve.

**Parser Source**: [Artifacts_Collectors/amcacheparser.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/amcacheparser.py)  
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_AmCacheClaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_AmCacheClaw.py)

### Key Fields
- `file_path`: Full path to the executable
- `sha1_hash`: SHA-1 hash of the file
- `file_size`: Size in bytes
- `publisher`: Software publisher name
- `product_name`: Product name
- `first_execution`: First execution timestamp
- `timestamp`: Parse time (NOT event time)

## Database Schema
Table: `amcache_data`

## Timestamp Interpretation
**WARNING**: The `timestamp` column represents when Crow-eye parsed the artifact, NOT execution time.
Use `first_execution` for forensic timeline analysis.

## Common Queries
- Identify all executables run from a specific path
- Find programs by hash value
- Detect unsigned or suspicious executables

## SQL Query Templates
- **Application Installation & Execution:**
  ```sql
  SELECT product_name, publisher, first_execution FROM amcache_data ORDER BY first_execution DESC LIMIT 20;
  ```
