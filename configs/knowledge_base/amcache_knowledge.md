# AmCache Artifact Knowledge

Every figure below was measured on a real `Amcache.hve` (26 `Root` subkeys,
7,325 rows) and cross-checked against four independent published sources. Where
a source and the hive disagree, the hive wins and the disagreement is recorded.

## What AmCache is

`Amcache.hve` is an **inventory**, not an execution log. The Application
Experience service - the **Microsoft Compatibility Appraiser** scheduled task,
`compattelrunner.exe` - records what it has seen so compatibility decisions can
be made quickly later.

It is evidence of:

- A binary's **presence**, path, size, publisher and SHA-1, **even after the
  file is deleted**
- Installed programs: install date, install source, uninstall string, and
  sometimes the SID of the installing user
- **Drivers**, with signing state
- **Devices**, including devices attached once, with install dates

### What AmCache does NOT prove

**An entry is not proof that a program ran.** AmCache records files in
directories the Appraiser scanned, binaries copied during installation, and
applications that needed a compatibility shim. Only the last reliably implies
execution, and nothing in a record says *when* anything ran. There is no run
count.

**Absence is not evidence of absence.** `InventoryApplication` is only updated
when the Appraiser runs, so software installed since its last run may simply
not be there yet.

For execution, corroborate with Prefetch, ShimCache (presence too), Security
4688 events, or SRUM.

## Timestamps

### `key_last_write` - when the Appraiser wrote the entry

Every entry is a registry key, and this is that key's LastWriteTime. It is
**not** when the program ran or was installed. It is when the Appraiser
recorded it, and the Appraiser writes in batches, so how useful it is for
ordering depends entirely on the table:

| Table | Rows | Distinct times | Commonest covers | Usable for ordering? |
|---|---|---|---|---|
| `InventoryApplicationFile` | 5212 | 1086 | 2% | **Yes** - granular |
| `InventoryApplication` | 380 | 17 | 17% | Coarse |
| `InventoryDevicePnp` | 292 | 17 | 92% | Barely |
| `InventoryDriverBinary` | 445 | 2 | 90% | **No** |
| `Mare` | 373 | **1** | **100%** | **No** |

So it bounds "seen by" and nothing more, and on the driver, device and Mare
tables it is one batch stamp shared by nearly every row. Do not present it as
an event time.

`parsed_at` is when Crow-Eye ran. It belongs on no timeline.

### The `_utc` columns

AmCache stores its other dates as locale-formatted **text**, in three shapes,
so they sort wrongly and read ambiguously. Crow-Eye adds a normalised
`<column>_utc` beside each and **never overwrites the raw string**:

| Raw column | Format seen | Normalised |
|---|---|---|
| `InventoryApplication.install_date`, `msi_install_date` | `06/11/2026 00:00:00` | `install_date_utc`, `msi_install_date_utc` |
| `InventoryApplicationFile.link_date` | `06/05/2026 21:16:00` | `link_date_utc` |
| `InventoryDevicePnp.install_date`, `first_install_date`, `driver_ver_date` | `09-08-2025`, `06-21-2006` | `*_utc` |
| `InventoryDriverBinary.driver_last_write_time` | `MM/DD/YYYY` | `driver_last_write_time_utc` |
| `InventoryDriverBinary.driver_time_stamp` | Unix seconds, e.g. `1431988083` | `driver_time_stamp_utc` |
| `InventoryDriverPackage.date` | `2025-12-2`, unpadded Y-M-D | `date_utc` |

**Month/day order.** Counted across the hive, the second component exceeds 12
hundreds of times and the first essentially never, so these are **MM/DD/YYYY**.
The parser forces the reading where a value forces it, and defaults to MM/DD
only where both components are 12 or under. One real counter-example exists:
`InventoryApplication.install_date` for **Discord** reads `20/12/2026`, written
by that application's own installer, and is read as 20 December.

**A `_utc` of NULL is meaningful.** It means the raw value was not a date:

- `link_date` = `01/01/1970` is **epoch zero, meaning the PE carries no link
  date** - normal for Go, Rust and reproducible builds. 467 of 2,408 link dates
  here fell outside a plausible window, most of them this. Reading them as 1970
  would invent a cluster of hundreds of files at one instant.
- Randomised `TimeDateStamp` values, which modern toolchains emit - e.g. a link
  date in 2105.
- Version strings: `link_date` holds `2.3.8.0` and `1.0.9188` on some rows,
  because the hive itself puts them there.

## `FileId` - a SHA-1, with a limit that matters

`InventoryApplicationFile.file_id` is a 44-character string. **The SHA-1 is the
last 40**; the leading `0000` is not part of it. Hand the whole string to a hash
lookup and it matches nothing, on every entry, with no error.

```sql
SELECT substr(file_id, 5) AS sha1 FROM InventoryApplicationFile;
```

**AmCache hashes only the first 31,457,280 bytes (30 MiB).** Proven here: of 71
files larger than that, **0 matched the whole-file SHA-1 and 71 of 71 matched
the SHA-1 of the first 30 MiB**. All four sources agree.

This is the only hash Crow-Eye matches IOCs against, so a partial hash reads as
"not this file" when the truth is "cannot tell". Two columns say so:

- **`file_id_is_partial`** - `1` when the cached `Size` exceeds the limit, `0`
  when it does not, NULL when the entry carries no `Size` (2,789 of 5,212 rows
  here). Derived from the hive alone, so it works against an image.
  **`file_id_is_partial = '1'` means a non-match proves nothing.**
- **`file_id_verified`** - live parses only, and only when the operator asks
  for it: `match`, `mismatch`, or NULL when the file is gone. **`mismatch` is a
  finding** - the binary was replaced after AmCache recorded it. Here 1,576
  matched and **57 did not**.

## The tables

| Table | Rows here | What it holds |
|---|---|---|
| `InventoryApplicationFile` | 5212 | Every executable the Appraiser has seen: path, SHA-1, size, publisher, link date, `program_id` |
| `InventoryApplication` | 380 | Installed programs: install date and source, uninstall string, registry key, sometimes the installing user's SID |
| `InventoryDriverBinary` | 445 | Drivers, with `driver_signed`. Where an unsigned driver shows up |
| `InventoryDriverPackage` | 80 | Driver packages: INF, provider, hardware ids |
| `InventoryDevicePnp` | 292 | Devices: `install_date`, `first_install_date`, manufacturer, `hwid`, `container_id` |
| `InventoryDeviceContainer` | 16 | Devices as containers, including things attached once |
| `InventoryApplicationShortcut` | 129 | Shortcuts - a Start-menu or desktop presence |
| `Mare` | 373 | Compatibility entries. The real directory is inside `restore`, decoded into `root_dir_path`; `sdbentryguid` names the shim database entry (149/373) |
| `MareBackupApps` | 85 | `sid_state` carries a **user SID** |
| `DeviceCensus` | 237 | Machine identity, one row per value |
| `InventoryMiscellaneousUser` | 12 | Per-user identifiers such as `AdvertisingID` |
| `InventoryMiscellaneousUupInfo` | 28 | Update packages |
| other `InventoryMiscellaneous*` / `InventoryDevice*` | 1-25 | Memory slots, media class, USB hub port counts, sensor capabilities |
| `UnknownSubkeys` | 0 | Catch-all for a `Root` subkey this build does not know |

Ten tables store **one row per registry value** (`entry`, `name`, `value`)
rather than fixed columns: `DeviceCensus`, which carries 237 distinct value
names and gains more each Windows release, and nine subkeys that were empty on
every system available - their columns could not be verified, so none were
invented.

## Value meanings

### `InventoryApplicationFile`

| Value | Meaning |
|---|---|
| `file_id` | SHA-1 of the first 30 MiB, with a `0000` prefix |
| `program_id` | Links to `InventoryApplication.program_id`; a hash of name, version, publisher and language. 5212/5212 populated here; 1,426 rows join |
| `lower_case_long_path` | Full path, lowercased by Windows |
| `size` | File size in bytes as the Appraiser saw it |
| `binary_type` | `pe64_amd64` (1904), `pe32_i386` (276), `pe64_clr_64` (111), `pe32_clr_il` (53), `pe32_clr_32` (28). **A `clr` form means a .NET assembly** |
| `is_os_component` | `1` on 193 rows - shipped as part of Windows |
| `link_date` | PE compile timestamp. Attacker-controllable, often zero or randomised |
| `usn` | USN journal record number at the time of the scan |
| `appx_package_full_name`, `appx_package_relative_id` | Store/UWP identity when the file belongs to a package |

### `InventoryApplication`

| Value | Meaning |
|---|---|
| `source` | How Windows learned of it: `AppxPackage` (192), `Msi` (103), `AddRemoveProgram` (65), `AddRemoveProgramPerUser` (14), **`Steam`** (5). Published lists give only the first four plus `File` - `AddRemoveProgramPerUser` and `Steam` are real and missing from them |
| `install_date` | **Only meaningful for `AddRemoveProgram` and `Msi` sources** |
| `uninstall_string` | The command the uninstaller registered (171/380) |
| `registry_key_path` | The `Uninstall` key in SOFTWARE this came from |
| `user_sid` | The installing user, when per-user (15/380) |
| `store_app_type` | `Win10StoreApp` (122), `CentennialStoreApp` (70 - a desktop app repackaged for the Store) |
| `root_dir_path` | Install directory |

### `InventoryDriverBinary`

`driver_signed` (445/445 here), `driver_is_kernel_mode`, `driver_in_box` (part
of Windows), `driver_company`, `service`, `inf`, `driver_time_stamp` (PE
TimeDateStamp, frequently randomised), `driver_last_write_time`.

### `InventoryDevicePnp`

`install_date` and `first_install_date` (288/292 each) - **live device
properties are denied to a running system, so for a device attached once this
is often the only source**. Plus `manufacturer`, `description`, `hwid`,
`compid`, `container_id`, `driver_name`, `driver_ver_date`,
`driver_package_strong_name`, `service`, `enumerator`, and `install_state`
(`0` on 291 of 292).

## Deleted entries, recovered from free space

Deleting a registry key does not erase it. Windows flips the cell's size field
positive, marks it free, and moves on - the signature, the name, the timestamp
and the values survive until something allocates over that space. A key
unlinked from the tree is invisible to every tree walker and is still in the
file.

Crow-Eye recovers them into **`AmcacheCarvedKeys`** and
**`AmcacheCarvedValues`**. **No reference AmCache parser does this** -
AmcacheParser has no unallocated-space recovery at all.

`record_state` is always `deleted` on these rows. They are not live entries and
must never be reported as such. A carved value has no timestamp of its own,
because a registry value never does - the key that held it carries it, and
`parent_cell_offset` and `key_path` link the two.

**Where it pays off, and where it cannot.** This needs free space to read, so
it works on a hive taken from an image, a Volume Shadow Copy, or any file copy.
A **live** parse exports the hive with `NtSaveKeyEx`, which serialises the hive
as the kernel holds it - a reorganised hive whose free space has been
discarded. Measured on this machine: 1,777 bins, 610 free cells, 4,936 free
bytes, and **0 recoverable records**. The parse runs the walk anyway and
reports the reorganisation, so a zero is a measurement rather than silence.

```sql
SELECT key_last_write, key_name, key_path FROM AmcacheCarvedKeys
ORDER BY key_last_write DESC;

SELECT k.key_path, v.value_name, v.data
FROM AmcacheCarvedValues v
JOIN AmcacheCarvedKeys k ON k.cell_offset = v.parent_cell_offset
WHERE v.value_name IN ('LowerCaseLongPath', 'FileId', 'ProgramId');
```

## Associated and unassociated file entries

`program_association` on `InventoryApplicationFile`:

- **`associated`** - the row's `ProgramId` resolves to an `InventoryApplication`
  row, so the file belongs to something installed. 1,426 of 5,212 here.
- **`unassociated`** - seen on disk, belonging to no installed program. 3,786
  here. **This is where dropped and portable binaries show up.**
- NULL - the entry carries no `ProgramId` at all.

```sql
SELECT key_last_write, lower_case_long_path, substr(file_id, 5) AS sha1
FROM InventoryApplicationFile
WHERE program_association = 'unassociated'
  AND (lower_case_long_path LIKE '%appdata%'
    OR lower_case_long_path LIKE '%temp%'
    OR lower_case_long_path LIKE '%downloads%')
ORDER BY key_last_write DESC;
```

186 rows matched that on this machine - temporary unpack directories and
portable applications among them.

## The Windows 7/8 schema is reported, not parsed

Before Windows 10 the layout was `Root\File\{VolumeGUID}\{FileReference}`
with **numbered** value names, plus `Root\Programs`. It sits two levels below
`Root` where the modern schema sits one, so Crow-Eye's walk reaches none of it.

Such a hive is now **detected and named** - *"the Windows 7/8 AmCache schema is
NOT parsed by this build"* - with a count of the entry keys it could not read,
and a note when a hive carries both layouts saying it is only partly read. It
is not decoded, because no Windows 7/8 hive was available to test a decoder
against and untested decoding of evidence is worse than an honest refusal.

The map, from Yogesh Khatri's original research and cross-checked, for when a
hive is available. **Documented, not implemented:**

| Value | Meaning | | Value | Meaning |
|---|---|---|---|---|
| `0` | Product name | | `c` | File description |
| `1` | Company name | | `d` | OS version (major/minor) |
| `2` | File version number | | `f` | Compile time, Unix seconds |
| `3` | Language code | | `11` | Last modified (FILETIME) |
| `5` | File version | | `12` | Created (FILETIME) |
| `6` | File size in bytes | | `15` | **Full path** |
| `7` | PE SizeOfImage | | `17` | Last modified 2 (FILETIME) |
| `9` | PE checksum | | `100` | **ProgramId** |
| | | | `101` | **SHA-1 of the file** |

Note `101` is the SHA-1 directly, without the `0000` prefix the modern
`FileId` carries.

## Where published sources disagree with the hive

Checked against this build; three documented value names do not exist here.

| Source claims | Source | This hive |
|---|---|---|
| `DigitalSignature` on `InventoryDriverBinary` | Securelist | **`DriverSigned`** |
| `LastModified` on `InventoryDriverBinary` | Securelist | **`DriverLastWriteTime`** |
| `LastScanTime` on `InventoryApplication` | Securelist | **absent** |
| `Source` has four values | Psmths | **six seen**, incl. `AddRemoveProgramPerUser`, `Steam` |

Sources: Securelist/Kaspersky, Psmths windows-forensic-artifacts, Qazeer
InfoSec-Notes, amcacheparser.com. The Windows 7/8 `File\{GUID}` numbered-value
schema is documented by others but absent from this build, so it is
documented-but-not-measured here.

## SQL templates

- **A hash safe to compare against threat intelligence:**
  ```sql
  SELECT substr(file_id, 5) AS sha1, lower_case_long_path, size
  FROM InventoryApplicationFile
  WHERE file_id_is_partial = '0';
  ```

- **Binaries whose hash cannot be trusted for IOC matching:**
  ```sql
  SELECT lower_case_long_path, size FROM InventoryApplicationFile
  WHERE file_id_is_partial = '1';
  ```

- **Files replaced since AmCache recorded them** (live parse, verification on):
  ```sql
  SELECT lower_case_long_path, key_last_write FROM InventoryApplicationFile
  WHERE file_id_verified = 'mismatch';
  ```

- **A timeline, using the granular table and normalised dates:**
  ```sql
  SELECT key_last_write, link_date_utc, name, lower_case_long_path
  FROM InventoryApplicationFile
  ORDER BY key_last_write DESC LIMIT 50;
  ```

- **Files in suspicious locations that may since have been deleted:**
  ```sql
  SELECT key_last_write, lower_case_long_path, substr(file_id, 5) AS sha1
  FROM InventoryApplicationFile
  WHERE lower_case_long_path LIKE '%\appdata\%'
     OR lower_case_long_path LIKE '%\temp\%'
  ORDER BY key_last_write DESC;
  ```

- **A file joined to the program that installed it:**
  ```sql
  SELECT f.lower_case_long_path, a.name, a.publisher, a.install_date_utc, a.source
  FROM InventoryApplicationFile f
  JOIN InventoryApplication a ON a.program_id = f.program_id;
  ```

- **Unsigned drivers, oldest first:**
  ```sql
  SELECT driver_last_write_time_utc, driver_name, driver_company, inf
  FROM InventoryDriverBinary
  WHERE driver_signed IN ('0', 'false', 'False')
  ORDER BY driver_last_write_time_utc;
  ```

- **Device history:**
  ```sql
  SELECT first_install_date_utc, install_date_utc, manufacturer, model, hwid
  FROM InventoryDevicePnp ORDER BY first_install_date_utc DESC;
  ```

- **Machine identity:**
  ```sql
  SELECT name, value FROM DeviceCensus
  WHERE name IN ('AADDeviceId','ActivationChannel','AzureVMType','OSVersion');
  ```
