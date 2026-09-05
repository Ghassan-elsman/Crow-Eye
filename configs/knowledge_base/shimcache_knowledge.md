# ShimCache Artifact Knowledge

## Forensic Significance
ShimCache (Application Compatibility Cache) records executables the system has
seen. It provides evidence of:
- **Presence** of a program on disk at a point in time
- **File paths**, including paths whose files have since been deleted
- The file's **last-modified** time as the cache recorded it
- **Cache order**, which is the order the entries were inserted

### What ShimCache does NOT prove
An entry means Windows examined the file for compatibility shimming. That
happens on execution, but it also happens when a file is merely enumerated by
Explorer. **An entry is not proof of execution.** Corroborate with Prefetch,
Amcache, or 4688 events before calling it execution.

`last_modified` is the **file's** modification time, not the time the entry was
created and not an execution time. It is attacker-controllable via timestomping.

### Fields this format does not carry
On **Windows 10/11** the record carries no file size and no execution flag.
Those fields belong to the Windows XP/Vista/7/8 layouts. If an analyst asks for
a ShimCache file size or "executed" flag on a Win10/11 system, the correct
answer is that the artifact does not record them - not a value from another
table presented as if it came from here.

### What the record's trailing blob holds
Every record ends with a data blob that older parsers skip. It is an **array of
12-byte slots**, each three little-endian DWORDs: `tag`, `type`, `value`.
`type = 2` means the value is a PE machine type.

Two tags are decoded by name because they were established from the bytes:

| Tag | Meaning | Evidence |
|---|---|---|
| `0x800`, `0x2000` | the executable's **machine type** | agreed with the PE header of the file on disk on **296 of 300** files that still exist |
| `0x200` | set on **operating-system binaries** | 164 of 165 against "path under `C:\Windows`"; the one exception is a third-party driver package staged in DriverStore, which is not an OS binary |

The remaining tags - `0x20`, `0x40`, `0x100`, `0x400` - are **recorded by
number, not named**. Their best correlations sit at 94-97%, close enough to the
base rates to be coincidence. `0x400` tracks "declares a Windows 10 or later
subsystem version" at 96.7%; `0x100` appeared only on binaries declaring
subsystem 6.x but not on all of them; `0x20` is constant 0 and correlates with
nothing. **Do not tell an analyst what those four mean** - report the value and
say it is not identified.

Where the machine type disagrees with the file on disk today, that is normally
the file having been **replaced since** the cache recorded it, which is a
finding rather than a parser error.

## Crow-eye Parsing Logic
**Parser Source**: [Artifacts_Collectors/shimcash_claw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/shimcash_claw.py)
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_ShimCacheClaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_ShimCacheClaw.py)

The offline parser reuses the live parser's format logic, so both produce
identical rows from identical bytes. Both read **every** control set present
(`CurrentControlSet`, `ControlSet001`, `ControlSet002`, ...) and merge them,
skipping a set that is byte-identical to one already read.

### Supported format
Only **Windows 10/11** (`AppCompatCache` header size `0x30` or `0x34`) is
parsed. The record is:

    "10ts"(4) | unknown(4) | cell size(4) | path size(2) | path (UTF-16LE)
              | FILETIME(8) | data size(4) | data blob

An XP, Vista, Windows 7 or Windows 8 cache is **named and refused**, and
produces zero rows rather than rows guessed from a layout the parser does not
understand. If a case yields no ShimCache rows, check the parse log for
"is not supported by this parser" before concluding the cache was empty.

### Packaged (Store / UWP) applications
Not every entry names a file. Store and UWP applications are recorded as seven
tab-separated fields instead of a path. Those rows have `entry_type =
'packaged app'`, an **empty** `path`, the whole original string in `raw_entry`,
and a decoded `package_family_name`, `package_version` and `architecture`.
They legitimately carry **`FILETIME = 0`**, so a null `last_modified` on a
packaged-app row is the artifact, not a parse failure. On a reference case,
201 of 1,024 rows were packaged apps.

Query `filename` and `package_family_name` for these; `path` is empty by design.

## Database Schema
Database: `shimcache.db` &nbsp;&nbsp; Table: `shimcache_entries`

| Column | Meaning |
|---|---|
| `id` | row id |
| `filename` | leaf name of `path`, or the package name for a packaged app |
| `path` | full path; **empty** for a packaged app |
| `entry_type` | `file` or `packaged app` |
| `package_family_name` | packaged apps only; matches `Get-AppxPackage` |
| `package_version` | packaged apps only |
| `architecture` | packaged apps only (PE machine type) |
| `raw_entry` | the original tab-separated record, packaged apps only |
| `last_modified` | the file's modification time (NOT execution) |
| `last_modified_readable` | the same, formatted; `Unknown` when the record has none |
| `data_size` | length of the record's trailing data blob |
| `entry_size` | the record's own cell size in bytes |
| `cache_entry_position` | **byte offset** of the record inside the cache value |
| `cache_index` | **ordinal** in the cache - 0 is the most recently inserted |
| `record_id` | the 32-bit value the record carries at offset 4; unique per record, not derived from the path or timestamp |
| `shim_flags` | the trailing blob decoded, one `name=value` or `0xTAG=0xVALUE` per 12-byte slot |
| `entry_hash` | dedup identity |
| `parsed_at` | when Crow-Eye parsed it (NOT an event time) |

`cache_entry_position` and `cache_index` answer different questions. The byte
offset locates the record in the blob; the **ordinal** is the recency ordering
an analyst reasons about. Use `cache_index` for ordering, never the byte offset
and never `id`.

## Timestamp Interpretation
- `parsed_at` is parse time, not event time. Never put it on a timeline.
- `last_modified` is file modification time. Use it for timeline work, but
  label it as modification, not execution.
- A null / `Unknown` `last_modified` on a packaged-app row is expected.

## SQL Query Templates

- **Most recently inserted entries (true cache recency):**
  ```sql
  SELECT cache_index, filename, path, last_modified_readable
  FROM shimcache_entries
  WHERE cache_index >= 0
  ORDER BY cache_index ASC
  LIMIT 20;
  ```

- **Executables from suspicious locations:**
  ```sql
  SELECT cache_index, filename, path, last_modified_readable
  FROM shimcache_entries
  WHERE entry_type = 'file'
    AND (path LIKE '%\Users\%\AppData\%' OR path LIKE '%\Temp\%'
         OR path LIKE '%\ProgramData\%' OR path LIKE '%\Downloads\%')
  ORDER BY cache_index ASC;
  ```

- **Architecture of everything the cache saw** (from the record's blob, not
  from the path):
  ```sql
  SELECT architecture, count(*) FROM shimcache_entries
  WHERE architecture != '' GROUP BY architecture;
  ```

- **Non-OS binaries, by cache recency** - `os_binary=0` is the flag the record
  itself carries, independent of where the file sits:
  ```sql
  SELECT cache_index, filename, path, architecture
  FROM shimcache_entries
  WHERE shim_flags LIKE '%os_binary=0%'
  ORDER BY cache_index ASC;
  ```

- **Packaged applications seen on the system:**
  ```sql
  SELECT package_family_name, package_version, architecture, cache_index
  FROM shimcache_entries
  WHERE entry_type = 'packaged app'
  ORDER BY cache_index ASC;
  ```

- **Corroborate a ShimCache path against execution artifacts** (ShimCache alone
  is presence, not execution):
  ```sql
  SELECT filename, path, last_modified_readable
  FROM shimcache_entries
  WHERE entry_type = 'file' AND filename = ?;
  ```
