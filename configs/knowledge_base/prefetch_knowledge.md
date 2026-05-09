# Prefetch Artifact Knowledge

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
