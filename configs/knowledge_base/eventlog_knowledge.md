# Event Log Artifact Knowledge

## Forensic Significance
Windows Event Logs record system, security, and application events.
They provide evidence of:
- User logon/logoff events (Event ID 4624, 4625)
- System startup/shutdown
- Security events (authentication, privilege use)
- Application errors and warnings
- Service installation and execution

## Crow-eye Parsing Logic
Crow-eye uses `offline_WinLog_Claw.py` to parse Windows Event Log files (.evtx) into `Log_Claw.db`.

## Database Schema (Log_Claw.db)
The data is divided into three primary tables based on the log source:
- `SecurityLogs`: Contains all security-related events including logins.
- `SystemLogs`: Contains system-level events and service changes.
- `ApplicationLogs`: Contains application-specific events.

### Key Fields (All Tables)
- `EventID`: Numeric event identifier (e.g., 4624)
- `EventTimestampUTC`: Primary forensic timestamp (YYYY-MM-DD HH:MM:SS)
- `ComputerName`: The name of the machine
- `User`: The user account associated with the event
- `Source`: The event source
- `EventType`: The severity level (Information, Warning, Error)
- `EventDescription`: Full description and data of the event

## SQL Query Templates

### Successful Logins (Event 4624)
```sql
SELECT EventTimestampUTC, User, ComputerName, EventDescription 
FROM SecurityLogs 
WHERE EventID = 4624 
ORDER BY EventTimestampUTC DESC 
LIMIT 10;
```

### Failed Logins (Event 4625)
```sql
SELECT EventTimestampUTC, User, ComputerName, EventDescription 
FROM SecurityLogs 
WHERE EventID = 4625 
ORDER BY EventTimestampUTC DESC 
LIMIT 10;
```

### System Shutdown/Startup
```sql
SELECT EventTimestampUTC, EventID, EventDescription 
FROM SystemLogs 
WHERE EventID IN (6005, 6006) 
ORDER BY EventTimestampUTC DESC;
```
