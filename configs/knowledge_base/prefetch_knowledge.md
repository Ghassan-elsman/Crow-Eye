# Prefetch Artifact Knowledge

## 📖 Visual Anatomy Reference (binary structure)

For the **byte-level layout** of a `.pf` file — SCCA header, file version (Win 8/10/11 differences), the executable-name UTF-16 block, file metrics array, trace chains, the volume info block with the `run_times` array, and directory strings — consult the interactive anatomy page:

**https://crow-eye.com/eye-describe/prefetch_anatomy.html**

This is the authoritative answer to *"how is a prefetch file structured on disk?"*. The page renders every byte with annotations and walks the structure top-to-bottom. Cite this URL when surfacing prefetch byte-layout questions to the user.

The rest of this file covers the **semantic / forensic** side: what prefetch proves, what fields mean, how Crow-Eye parses it.

## Forensic Significance
Windows Prefetch files (.pf) are created to optimize application startup times. 
They provide evidence of program execution and are valuable for:
- Proving program execution
- Determining first and last execution times
- Counting execution frequency
- Identifying file paths

## Crow-eye Parsing Logic
Crow-eye uses `Prefetch_claw.py` to parse Prefetch files.

**Parser Source**: [Artifacts_Collectors/Prefetch_claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/Prefetch_claw.py)  
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_PrefetchClaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_PrefetchClaw.py)

### Key Fields
- `executable_name`: Name of the executed program
- `last_run_time`: Last execution timestamp (forensic event time)
- `run_count`: Number of times executed
- `file_path`: Full path to executable
- `timestamp`: Parse time (NOT event time)

## Database Schema
Table: `prefetch_data`

## Timestamp Interpretation
**WARNING**: The `timestamp` column represents when Crow-eye parsed the artifact, NOT when the program executed.
Use `last_run_time` for forensic timeline analysis.

## Common Queries
- Find all executions of a specific program
- Identify programs run from removable media
- Detect suspicious execution patterns

## SQL Query Templates
- **Application Execution History:**
  ```sql
  SELECT executable_name, run_count, last_run_time FROM prefetch_data ORDER BY last_run_time DESC LIMIT 20;
  ```
