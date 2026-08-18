# SRUM Artifact Knowledge

## Forensic Significance
System Resource Usage Monitor (SRUM) tracks application resource usage in Windows 8+.
It provides evidence of:
- Application execution, with CPU, disk and network cost per hour
- Network usage by application, and which wireless profile carried it
- How an application was used, not only that it ran: focus time, keyboard and mouse input
- Energy consumption and battery state transitions
- User context for every one of the above

SRUM aggregates into roughly hourly windows and typically retains 30-60 days, so it answers
"was this running, and was someone using it" over a longer period than Prefetch.

## Crow-eye Parsing Logic
**Parser Source**: [Artifacts_Collectors/SRUM_Claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/SRUM_Claw.py)
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_SRUM_Claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_SRUM_Claw.py)

Both read `SRUDB.dat` (an ESE database) and resolve the numeric `AppId` and `UserId` on every row
through `SruDbIdMapTable`.

## Database Schema
Database: `srum_data.db`. There is no single `srum_data` table - each SRUM provider becomes its own
table:

| Table | Holds |
|---|---|
| `srum_application_usage` | CPU cycles, context switches, bytes read and written, per app per hour |
| `srum_network_data_usage` | Bytes sent and received, per app, per interface |
| `srum_network_connectivity` | Interface connection windows: `connected_time`, `connect_start_time` |
| `srum_energy_usage` | Battery charge level, state transitions, `event_timestamp` |
| `srum_app_timeline` | Focus, keyboard and mouse seconds, duration, `hosted_services` |
| `srum_metadata` | One row per parse: `parsed_at`, source path, record counts |

## Timestamp Interpretation
`timestamp` is the **event time** - the SRUM aggregation window, taken from the provider's own
`TimeStamp` column. Use it for timeline analysis.

`parsed_at`, in `srum_metadata` only, is when Crow-Eye read the database. It is bookkeeping and
never evidence.

`event_timestamp`, `connect_start_time` and `end_time` are Int64 FILETIME columns, distinct from
`timestamp`, giving the moment inside the window that the row is really about.

## Identifying a shared host process
Two identity forms appear, and which one is used decides how svchost.exe is told apart:

- The resource and network tables store a **device path** with the service appended:
  `\Device\HarddiskVolume3\Windows\System32\svchost.exe [DcomLaunch]`. Query `app_path`, not
  `app_name` - `app_name` is only the basename and is `svchost.exe` for every one of them.
- `srum_app_timeline` uses the `!!svchost.exe!2054/02/06:15:19:25!1642e![netsvcs] [Winmgmt]` form.
  Crow-Eye splits it: the executable into `app_name`, the service list into `hosted_services`.
  `app_path` is empty on those rows because that form names no path.

## Sparse columns are sparse for a reason
In `srum_app_timeline`, `in_focus_s`, `keyboard_input_s` and `mouse_input_s` are set on only a small
share of rows. A service accrues CPU cycles for hours and never sees a keystroke. A NULL there means
no such activity in that window, not a failed decode - so a non-NULL keyboard or mouse value is
strong evidence a person was present.

## SQL Query Templates
- **Network usage by application:**
  ```sql
  SELECT app_name, app_path, bytes_sent, bytes_received, timestamp
  FROM srum_network_data_usage
  ORDER BY timestamp DESC LIMIT 20;
  ```
- **Application execution timeline:**
  ```sql
  SELECT app_name, app_path, user_name, timestamp
  FROM srum_application_usage
  ORDER BY timestamp DESC LIMIT 20;
  ```
- **Evidence a person was at the keyboard:**
  ```sql
  SELECT timestamp, app_name, in_focus_s, keyboard_input_s, mouse_input_s, user_name
  FROM srum_app_timeline
  WHERE keyboard_input_s > 0 OR mouse_input_s > 0
  ORDER BY timestamp DESC LIMIT 20;
  ```
- **Telling one svchost.exe apart from another:**
  ```sql
  SELECT timestamp, hosted_services, in_focus_s, duration_ms
  FROM srum_app_timeline
  WHERE app_name = 'svchost.exe' AND hosted_services != ''
  ORDER BY timestamp DESC LIMIT 20;
  ```
