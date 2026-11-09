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
- `partition_diagnostic`: Microsoft-Windows-Partition/Diagnostic event 1006, one row per disk arriving or leaving (see Device evidence below).
- `driver_frameworks_usermode`: Microsoft-Windows-DriverFrameworks-UserMode/Operational events 2003 and 2100 (see Device evidence below).
- `setupapi_dev_log`: one row per section of setupapi.dev.log and its rotated copies (see Device evidence below).

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

## Device evidence (partition_diagnostic, driver_frameworks_usermode, setupapi_dev_log)
The registry (USBSTOR, MountedDevices) says a storage device was seen. These two
channels say WHEN it was connected and removed, and what it was. Both tables keep
every field of the event in `EventData` (JSON), and the device's serial in
`SerialNumber`.

- `partition_diagnostic` (event 1006): written when a disk arrives - Model,
  Manufacturer, Revision, SerialNumber, BusType (7 = USB, 17 = NVMe, 11 = SATA,
  10 = SAS, 3 = ATA), Capacity in bytes, PartitionStyle (0 MBR, 1 GPT),
  PartitionCount, ParentId (the device instance ID, e.g. USB\VID_..&PID_..\<serial>),
  DiskId - and again when it leaves, with Capacity 0 and PartitionCount 0. So a row
  with Capacity > 0 is a connection and a row with Capacity 0 a disconnection of
  the same SerialNumber. The channel is on by default on Windows 10 1607 and later.
- `driver_frameworks_usermode`: 2003 = the UMDF host was asked to load drivers for a
  device (it arrived); 2100 = a PnP or power request to it (MajorCode/MinorCode;
  27/23 is the surprise-removal path). InstanceId is the device instance ID and
  SerialNumber is read from it. This channel is OFF by default, so an empty table on
  most machines means the channel was off, not that no device was used.
- Join to the registry on the serial: `USBStorageDevices_Registry` and
  `partition_diagnostic.SerialNumber` / `driver_frameworks_usermode.SerialNumber`.
  A device that reports no serial gets one made up by Windows (second character
  '&', e.g. 8&5e75b0f&0&000000); SerialNumber is empty for those.

- `setupapi_dev_log`: one row per section of `%SystemRoot%\INF\setupapi.dev*.log`.
  `section_kind` "Device Install (Hardware initiated)" with a USB/USBSTOR
  `device_instance_id` is the FIRST time that device was installed on the machine;
  `serial_number` is read from the instance ID (USB and USB storage only).
  `section_start_local` is the machine's local time as written;
  `section_start_utc` is converted by that machine's zone rules (live: this
  machine's; offline: the image's SYSTEM hive) and empty when they are not known -
  `time_basis` says which. Windows rotates the file (setupapi.dev.YYYYMMDD_HHMMSS.log),
  so old installs can be gone.

```sql
-- First installs of USB devices, with their serials
SELECT section_start_utc, section_start_local, device_instance_id, serial_number, exit_status
FROM setupapi_dev_log
WHERE section_kind = 'Device Install (Hardware initiated)' AND serial_number IS NOT NULL
ORDER BY section_start_local;
```

```sql
-- USB disks connected (Capacity > 0) and removed (Capacity = 0), newest first
SELECT EventTimestampUTC, Model, SerialNumber, Capacity, PartitionCount,
       CASE WHEN Capacity > 0 THEN 'connected' ELSE 'removed' END AS state
FROM partition_diagnostic
WHERE BusType = 7
ORDER BY EventTimestampUTC DESC;
```

