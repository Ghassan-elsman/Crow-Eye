# SRUM Artifact Knowledge

## Forensic Significance
System Resource Usage Monitor (SRUM) tracks application resource usage in Windows 8+.
It provides evidence of:
- Application execution and runtime
- Network usage by application
- Energy consumption
- User context for application execution

## Crow-eye Parsing Logic
Crow-eye uses `offline_SRUM_Claw.py` to parse SRUM database.

**Parser Source**: [Artifacts_Collectors/SRUM_Claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/SRUM_Claw.py)  
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_SRUM_Claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_SRUM_Claw.py)

### Key Fields
- `application_name`: Name of the application
- `user_sid`: Security Identifier of the user
- `start_time`: Application start timestamp
- `end_time`: Application end timestamp
- `bytes_sent`: Network bytes sent
- `bytes_received`: Network bytes received
- `timestamp`: Parse time (NOT event time)

## Database Schema
Table: `srum_data`

## Timestamp Interpretation
**WARNING**: The `timestamp` column represents when Crow-eye parsed the SRUM database, NOT when applications ran.
Use `start_time` and `end_time` for forensic timeline analysis.

## Common Queries
- Identify applications with network activity
- Find programs run by specific users
- Analyze application runtime patterns

## SQL Query Templates
- **Network Usage by App:**
  ```sql
  SELECT application_name, bytes_sent, bytes_received, start_time FROM srum_data WHERE bytes_sent > 0 OR bytes_received > 0 ORDER BY start_time DESC LIMIT 20;
  ```
- **Application Execution Timeline:**
  ```sql
  SELECT application_name, start_time, end_time FROM srum_data ORDER BY start_time DESC LIMIT 20;
  ```
