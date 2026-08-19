# Registry Artifact Knowledge

## Forensic Significance
The Windows Registry contains system and user configuration data.
Forensically relevant areas include:
- User activity (RecentDocs, UserAssist, MUICache)
- Persistence mechanisms (Run keys, Services)
- USB device history
- Network configuration
- Installed software

## Crow-eye Parsing Logic
Crow-eye uses `Regclaw.py` and `offline_RegClaw.py` to parse registry hives.

**Parser Source**: [Artifacts_Collectors/Regclaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/Regclaw.py)  
**Offline Parser**: [Artifacts_Collectors/offline_parsers/offline_RegClaw.py](https://github.com/crow-eye/crow-eye/blob/main/Artifacts_Collectors/offline_parsers/offline_RegClaw.py)

### Key Fields

There is no single generic registry table. The parsers write **108 named tables**, one per artifact
- `AutoStartPrograms`, `UserAssist`, `Shellbags`, `SystemServices` and so on - into
`registry_data.db`. Query the table for the artifact; there is no `registry_data` table to filter
with a `key_path LIKE` clause.

Columns that recur across those tables:

- `parsed_at`: when Crow-Eye parsed the artifact. **Never an event time.** This is the only
  bookkeeping column; older names (`timestamp`, `inserted_at`) are legacy and read-only.
- `key_last_write`: the registry key's own last-write time. For an MRU artifact this is the only
  time the evidence holds.
- `user_name` / `user_sid`: whose hive the row came from, as `MACHINE\\username`.
- `subkey`, `name`, `row_data`, `type`: the raw layer, on tables that keep one - the value exactly
  as the registry stores it.

## Database Schema

See `Global_schema_database_Reference.md` for every table and column. `registry_hive_state` is worth
knowing on its own: one row per hive parsed, saying whether Windows had it open and whether its
transaction logs were replayed. A row with `was_dirty = 1` and `replayed = 0` means the other tables
may be missing that hive's last transactions.

## Scheduled Tasks (TaskCache)

Table: `ScheduledTasks` in `registry_data.db`. Each task's executable is also written to
`AutoStartPrograms` with `location` = `TaskCache\<task path>`, so a persistence query over
`AutoStartPrograms` sees scheduled tasks beside the Run keys.

**Where it comes from.** `SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache` - the
SOFTWARE hive, not SYSTEM. `Tasks\{GUID}` holds the task; `Tree\<folder>\<name>` maps the human path
to that GUID; and `Plain` / `Logon` / `Boot` / `Maintenance` index the same GUIDs by trigger type.

**Why it matters.** A scheduled task is persistence and execution evidence at once: it names a binary,
records when it last ran, and says whether that run succeeded. Attacker-created tasks are a standard
persistence mechanism, and a task under `Logon` or `Boot` runs without the user doing anything.

**Columns**

| Column | Meaning |
|---|---|
| `task_path` | human task path, e.g. `\Microsoft\Windows\UpdateOrchestrator\Reboot` |
| `task_guid` | the `{GUID}` under `TaskCache\Tasks` |
| `command`, `arguments`, `working_dir` | what the task runs, decoded from the binary `Actions` value |
| `run_context` | the account or principal the task runs as |
| `triggers_index` | which of Plain / Logon / Boot / Maintenance the task is indexed under |
| `task_registered` | when the task was created (UTC) |
| `last_run`, `last_completed` | when it last started and finished (UTC) |
| `last_result` | 0 is success; anything else is an HRESULT, e.g. `0x80070002` file not found |

**Reading it.** `triggers_index` containing `Logon` or `Boot` is a persistence signal without decoding
the Triggers blob. A task registered close to an incident, or one whose `command` points outside
`C:\Windows` or `C:\Program Files`, deserves attention. `last_run` empty means it has never run.

**Caveat.** Timestamps are UTC. A task present in `Tree` but absent from `Tasks` (or the reverse) is
worth noting - the two are meant to agree.

## Persistence / ASEP keys

An **ASEP** (auto-start extensibility point) is any registry location Windows reads to decide what to
launch. Each has its own raw table holding every value verbatim, and anything that names an
executable is also written to `AutoStartPrograms`, so one query over `AutoStartPrograms` sees Run
keys, scheduled tasks and these together.

| Table | Key | Why it matters |
|---|---|---|
| `winlogon` | `Windows NT\CurrentVersion\Winlogon` | `Shell` and `Userinit` launch the desktop. `Shell` should be `explorer.exe`; `Userinit` should be `C:\Windows\system32\userinit.exe,`. Anything appended runs at every logon |
| `image_file_execution_options` | `...\Image File Execution Options\<exe>` | A `Debugger` value silently replaces the program it names - launching the exe runs the debugger instead. Also the Sticky Keys backdoor. `SilentProcessExit\MonitorProcess` runs on process death |
| `appinit_dlls` | `Windows NT\CurrentVersion\Windows` | Loaded into every process that links user32.dll. Only active when `LoadAppInit_DLLs` is 1 |
| `appcert_dlls` | `Session Manager\AppCertDlls` | Loaded into every process calling CreateProcess. **Absent on a stock system - its presence is the signal** |
| `active_setup` | `Active Setup\Installed Components\<GUID>` | `StubPath` runs once per user at first logon, before the desktop |
| `run_services`, `run_services_once` | `CurrentVersion\RunServices(Once)` | Legacy, absent on modern Windows - which is why an entry stands out |
| `policies_explorer_run` | `CurrentVersion\Policies\Explorer\Run` | Policy-driven autostart, easy to miss because it is not the usual Run key |
| `user_shell_folders` | `Explorer\User Shell Folders` | Redirecting `Startup` makes an attacker-controlled folder the startup folder |
| `lsa_packages` | `Control\Lsa` | DLLs loaded by lsass. `Notification Packages` normally holds `scecli` only |
| `boot_execute` | `Control\Session Manager` | Runs before any user logs on. Normally `autocheck autochk *` |
| `clsid_inprocserver32` | `HKCU\Software\Classes\CLSID\{...}\InprocServer32` | A per-user CLSID shadowing the machine-wide one loads a user-writable DLL in place of the real component. **Only entries that actually shadow an HKLM CLSID are recorded**. Was called `com_hijack`; renamed because a table name should say what the artifact *is*, not what an attacker might be doing with it |
| `command_processor` | `Microsoft\Command Processor` (HKLM + HKCU) | `AutoRun` runs on **every** `cmd.exe` launch. The HKCU copy needs no admin rights. Legitimate uses exist (clink, chocolatey), so read the command, not the presence |
| `drivers32` | `Windows NT\CurrentVersion\Drivers32` | Multimedia driver DLLs loaded by `winmm`. Stock content is the `wdmaud`/`msacm` set - roughly 30 entries per view, all short filenames with no path |
| `shell_service_object_delay_load` | `CurrentVersion\ShellServiceObjectDelayLoad` | COM objects Explorer loads at startup. **Stock content is `WebCheck` and nothing else** |
| `browser_helper_objects` | `CurrentVersion\Explorer\Browser Helper Objects` | DLLs loaded into IE and the legacy WebBrowser control. The CLSID is resolved to its backing file, so `data` names a DLL |
| `shared_task_scheduler` | `CurrentVersion\Explorer\SharedTaskScheduler` | **Absent on modern Windows.** An empty table is normal; any row is worth attention |
| `shell_icon_overlay_identifiers` | `CurrentVersion\Explorer\ShellIconOverlayIdentifiers` | In-process DLLs loaded by Explorer. OneDrive and cloud providers legitimately register several (leading spaces in the names are theirs - they sort to the top of a 15-slot limit) |
| `credential_providers` | `CurrentVersion\Authentication\Credential Providers` | DLLs in the logon UI - a rogue one sees every credential typed at the lock screen. **~21 ship with Windows**, so judge the DLL path, not the count |
| `netsh_helper_dlls` | `Microsoft\Netsh` | Loaded every time `netsh.exe` runs. Stock entries are all `%SystemRoot%\System32` DLLs |
| `amsi_providers` | `Microsoft\AMSI\Providers` | A hostile provider sees, and can lie about, every script AMSI scans. Normally exactly one: Defender's `MpOav.dll` |
| `security_providers` | `Control\SecurityProviders` | SSP DLLs loaded into lsass at boot. **Stock is `credssp.dll` alone.** Distinct from `lsa_packages`, which is the Lsa package lists |
| `print_monitors` | `Control\Print\Monitors` | DLLs loaded by `spoolsv.exe` as SYSTEM. Stock set is Appmon / Local Port / Standard TCP-IP Port / USB Monitor / WSD Port |
| `print_processors` | `Control\Print\Environments\*\Print Processors` | Same spooler load point one level deeper. Stock is `winprint.dll` under `Windows x64` |
| `network_providers` | `Control\NetworkProvider\Order` + each provider's `NetworkProvider` key | `ProviderOrder` names the services whose DLLs handle UNC paths; an inserted name loads first. Each named service's `ProviderPath` is recorded beside it |
| `wmi_autorecover_mofs` | `Microsoft\WBEM\CIMOM` | MOF files recompiled into the WMI repository whenever it rebuilds - persistence that survives repository repair |
| `windows_load_run` | `HKCU\Software\Microsoft\Windows NT\CurrentVersion\Windows` | The NT-era `Load` and `Run` pair, per user. **Empty on a stock profile** |
| `shell_open_command` | `Classes\<ProgID>\shell\open\command` (HKLM + HKCU) | How a file class is launched. HKCU wins over HKLM for the same ProgID, **so an HKCU row means the machine-wide handler is being overridden** - the mechanism behind the fodhelper (`ms-settings`) and eventvwr (`mscfile`) UAC bypasses. `DelegateExecute` is recorded because those techniques work by adding `(Default)` and blanking it. Stock HKLM rows for `exefile`/`mscfile`/`Folder` are normal; **HKCU rows are the finding** |

**Columns** (identical across all of them): `hive`, `key_path`, `name`, `data`, `type`, `user_name`,
`parsed_at`. `REG_MULTI_SZ` values are joined with `; ` rather than stored as a Python list.

**Reading them.** Compare against the known-good defaults above rather than looking for bad words -
most of these keys are empty or fixed on a clean system, so any content is worth a look. An empty
table means the ASEP does not exist on this machine, which is normal for `appcert_dlls`,
`run_services`, `policies_explorer_run`, `shared_task_scheduler` and `windows_load_run`.

**Naming.** Every table above is named for the registry artifact, never for the technique that
abuses it - `shell_open_command`, not "uac_bypass"; `clsid_inprocserver32`, not "com_hijack". The
row records what the registry holds; deciding whether it is an attack is the analyst's call, and a
schema that has already decided prejudges the evidence.

## Security posture and anti-forensics

One table per key, each carrying the stock default so a deviation reads without a second source.

| Table | Key | Why it matters |
|---|---|---|
| `rdp_tcp` | `Control\Terminal Server\WinStations\RDP-Tcp` | `PortNumber` defaults to 3389 - a change hides RDP from a port scan. `UserAuthentication` 0 disables NLA; `SecurityLayer` 2 is TLS |
| `usbstor_start` | `Services\usbstor` | `Start` 3 is the normal on-demand start. **4 means USB storage is disabled** - deliberate, and it stops USB history being written at all, so an empty `USBStorageDevices` may be policy rather than absence |
| `windows_script_host` | `Microsoft\Windows Script Host\Settings` | Usually **absent, which means enabled**. An explicit `Enabled=0` is someone turning scripting off |
| `explorer_advanced` | `HKCU\...\Explorer\Advanced` | `ShowSuperHidden=1` is off by default - switching it on means somebody went looking for protected OS files. `Hidden=1` shows hidden files (default 2) |
| `files_not_to_snapshot` | `Control\BackupRestore\FilesNotToSnapshot` | Files VSS drops from shadow copies. Stock entries exist (Outlook OST/OAB, Storage Tiers); **an added entry removes a file from the very copies an examiner relies on** |
| `dnscache_parameters` | `Services\Dnscache\Parameters` | `ServiceDll` should be `dnsrslvr.dll`; a replacement is a svchost-hosted load point |
| `winevt_channels` | two places - see below | Which logs were on, and how big |

**`winevt_channels` reads two different locations, because Windows keeps event log config in two
places.** The classic `Security`, `System` and `Application` logs are **not** under
`WINEVT\Channels` - they are legacy `SYSTEM\CurrentControlSet\Services\EventLog\<name>` keys
(`source` = `EventLog (classic)`). Only Vista-era channels live under WINEVT, and there are ~1166 of
them with ~788 disabled as shipped, so recording all of them would bury the finding. The table keeps
every classic log, a watch list of channels examiners ask about by name, and any channel someone has
resized (`reason` says which).

**Known-good defaults that trip people up:** `Microsoft-Windows-TaskScheduler/Operational` ships
**disabled** (`Enabled=0`) - that is Windows' default, not tampering. So does
`Microsoft-Windows-DNS-Client/Operational`. `PowerShell/Operational` ships enabled. Judge a disabled
channel against this list before calling it log tampering.

## Device attribution

| Table | Key | Why it matters |
|---|---|---|
| `wpdbusenum` | `Enum\SWD\WPDBUSENUM` | **The missing hop in USB attribution**: ties a volume GUID to the device that provided it, joining `USBStorageDevices` (which device) to `USBStorageVolumes` (which drive letter) |
| `device_classes` | `Control\DeviceClasses\{GUID}` | Device arrival per class. Only the disk, volume, storage-adapter and USB class GUIDs are recorded - the full set is thousands of rows of keyboards and audio endpoints |
| `volume_info_cache` | `CurrentVersion\Explorer\VolumeInfoCache` | Drive letter to the volume label the user actually saw. Often absent |

## Host identity

| Table | Key | Why it matters |
|---|---|---|
| `machine_guid` | `Microsoft\Cryptography` | Survives profile reimaging - the steadiest single answer to "is this the same host" |
| `product_options` | `Control\ProductOptions` | `ProductType`: `WinNT` is a workstation, `ServerNT`/`LanmanNT` a server |
| `os_install_history` | `SYSTEM\Setup` and its `Source OS` subkeys | The in-place upgrade trail: which build the machine came from, and when |
| `system_environment` | `Control\Session Manager\Environment` | Machine-wide `PATH` and friends - a prepended directory is a hijack primitive |
| `network_adapters` | `Control\Network\{4d36e972-...}` | Adapter GUID to the name shown in `ncpa.cpl`, so a Tcpip interface GUID elsewhere in the case can be named |
| `group_policy_history` | `CurrentVersion\Group Policy\History` | Which GPOs applied, and when |
| `active_computer_name` | `Control\ComputerName\ActiveComputerName` | The name in use **this boot** - differs from `ComputerName` after a rename with no reboot |
| `hivelist` | `Control\hivelist` | Backing file of every loaded hive - how you confirm the hives collected are the ones in use |

**`active_computer_name` and `hivelist` are volatile keys.** Windows builds them at runtime and
never writes them to a hive file, so **both are populated on a live acquisition and correctly empty
for an image or hive-set case**. An empty table there is not a parsing failure.

`hivelist` also legitimately changes size between two live parses of the same machine — Windows
loads and unloads application hives continuously, so a re-parse minutes later can add a row. That
is new data, not a duplicate: the table is keyed on the hive name and holds no repeats.

## Per-user activity

| Table | Key | Why it matters |
|---|---|---|
| `file_exts` | `Explorer\FileExts\<.ext>` | `UserChoice\ProgId` is the association the **user picked**, which outranks the machine default. `OpenWithProgids` / `OpenWithList` are only what was offered, kept separate via `choice_type` |
| `cid_size_mru` | `Explorer\ComDlg32\CIDSizeMRU` | Applications that opened a common file dialog, `position` 0 = most recent |
| `programs_cache` | `Explorer\StartPage2` | Start menu program list as a shell-item blob; presence and size only - decoding is the shellbag parser's job |
| `regedit_lastkey` | `Applets\Regedit` | **The key this user last had selected in regedit** - direct evidence of what they went looking at - plus any saved Favorites |
| `printer_connections` | `HKCU\Printers\Connections` | Network printers this user attached; the subkey encodes `,,server,printer` |

## Local group membership

Table: `local_groups`, built from the SAM hive alongside `UserAccounts`. **One row per group
member**, so "who was in Administrators" and "which groups was this SID in" are both a single
query. A group with no members still gets one row with an empty `member_sid` — an empty group
and an unparsed one must not look the same, and the stock set of empty built-in groups is the
baseline a deviation shows against.

| Column | Holds |
|---|---|
| `scope` | `Builtin` (Administrators, Users, Remote Desktop Users) or `Account` (groups an installer created, e.g. `docker-users`) |
| `rid` | 544 Administrators, 545 Users, 546 Guests, 555 Remote Desktop Users |
| `group_name`, `comment` | as stored in the hive |
| `member_sid`, `member_name` | member SIDs resolved through the same account map `UserAccounts` uses; group and logon-type SIDs (`S-1-5-11` Authenticated Users, `S-1-5-4` INTERACTIVE) resolve from a well-known table |
| `member_count` | what the hive declares, so a mismatch against the rows present is visible |
| `last_write` | when the group was last modified — **this dates a privilege change** |

**Reading it.** RID 544 is the one that matters: an account there that is not the built-in
Administrator or a known admin is privilege escalation, and `last_write` dates it. RID 555
(Remote Desktop Users) matters for remote access. Both scopes must be read — Builtin alone
misses installer-created groups, Account alone misses Administrators.

## LSA policy and the SECURITY hive

The SECURITY hive is the second one winreg cannot read: its **root key** denies Administrators
outright, so unlike SAM there is not even a handle to work from. Both parsers get at it the same
way — the live parser exports it with `SeBackupPrivilege` + `NtSaveKeyEx` to a hive file that
lives only for the parse, the offline parser reads the collected file, and from there it is the
same code.

| Table | Key | Why it matters |
|---|---|---|
| `lsa_policy` | `Policy\PolAcDmS`, `PolAcDmN`, `PolPrDmN`, `PolPrDmS`, `PolDnDDN` | `MachineSID` as LSA holds it — every local account SID is this plus a RID, so it is how you prove a SID belongs to *this* host. `PrimaryDomainName` reads `WORKGROUP` when the machine is not joined |
| `audit_policy` | `Policy\PolAdtEv`, `PolAdtLg` | What was being logged — the precondition for reading any event-log *absence* correctly |
| `lsa_secrets` | `Policy\Secrets\<name>` | Which secrets exist and when each was last written. `DPAPI_SYSTEM` is present on every machine; a `_SC_<service>` entry is a service account credential |
| `cached_domain_logons` | `Cache\NL$1`…`NL$25` | How many domain accounts are cached. **The key is absent entirely on a machine no domain account has logged on to** — that absence is itself the finding, not a gap |

**`audit_policy` is deliberately not fully decoded.** The pre-Vista `PolAdtEv` layout is an
enabled flag, a category count, then that many DWORDs. Modern blobs do not fit it — on a
Windows 11 host the value is 152 bytes whose third DWORD reads 134, not a valid setting — and
the modern layout is not publicly settled. The parser applies the legacy decode **only when the
blob validates against it** and otherwise keeps the raw bytes with a note. A guessed decode
would be a confident, wrong answer about what was being logged, which is the worst possible
output for this table. `last_write` is still meaningful on its own: it dates the last audit
policy change.

**`lsa_secrets` holds no plaintext, by choice.** Decrypting `Policy\Secrets` needs the boot key
assembled from the class names of `SYSTEM\CurrentControlSet\Control\Lsa\{JD,Skew1,GBG,Data}` and
then AES or RC4 over each blob — and it yields live service-account passwords. Recording which
secrets exist, their size and when they changed answers the forensic question without making the
parser a credential dumper.

## User Accounts

Table: `UserAccounts` in `registry_data.db`. **This is where a SID becomes a person.** Built by
merging the SAM hive (account names, flags, logon counts) with `ProfileList` (SIDs, profile paths),
and it lists accounts that have never logged on and own no profile - a disabled built-in
Administrator that suddenly shows a logon count is exactly the kind of thing that is invisible if the
list is profile-driven.

| Column | Meaning |
|---|---|
| `user_sid` | full SID; machine SID + `-<RID>` |
| `rid` | relative ID. 500 Administrator, 501 Guest, 503 DefaultAccount, 504 WDAGUtilityAccount, 1000+ created accounts |
| `username` / `display_name` | account name, and `MACHINE\username` as shown elsewhere |
| `account_type` | `local`, `built-in`, `service`, `synthetic` (DWM/UMFD sessions), `unresolved` |
| `account_enabled`, `account_flags` | from the SAM ACB bits: `DISABLED`, `PWD_NOT_REQUIRED`, `PWD_NEVER_EXPIRES`, `AUTO_LOCKED` |
| `last_logon`, `password_last_set`, `login_count`, `bad_password_count` | from the SAM F record; empty means never |
| `profile_path`, `profile_loaded` | from ProfileList |
| `source` | `SAM`, `ProfileList`, `SAM+ProfileList`, or `Artifact` |

**`source = 'Artifact'` deserves attention.** It means the SID appears in BAM, DAM or UserAssist but
in neither SAM nor ProfileList: a deleted account, a removed profile, or a domain user. The activity
is real and the account is gone.

**Attribution elsewhere.** Columns holding a SID read `S-1-5-21-...-1001 (MACHINE\username)` - the SID
is kept because accounts get renamed and names reused, while the name makes the row readable. Names
are `MACHINE\username`, or `NT AUTHORITY\SYSTEM` for service accounts, and are derived from the
evidence itself, never from the analyst's machine.

**Caveat.** Without a collected SAM hive only ProfileList is available, so flags, logon counts and
never-logged-on accounts are missing. `source` records which inputs were present.

## Security posture, exposure and device coverage

**`SecurityPosture`** records security-relevant settings, and records them **whether or not the value
exists** - absence is the finding for several of them. `assessment` is one of:

| assessment | meaning |
|---|---|
| `default` | matches an untouched Windows install - **not** a finding |
| `hardened` | deliberately stronger than default (e.g. `RunAsPPL`) |
| `weakened` | changed in a way that helps an attacker - this is the one to look at |
| `informational` | no security default to compare against |

Do not read `weakened` as "compromised", and do not read `default` as "checked and safe" - it means
the machine is as Windows shipped it. `UseLogonCredential` absent is the secure default; present and
set to 1 means plaintext credentials are cached in LSASS.

`NtfsDisableLastAccessUpdate` is not a boolean: bit `0x80000000` marks system-managed and the low bits
give the mode, where 0 and 2 mean last-access updates are **enabled**. `fsutil behavior query
disablelastaccess` reports the same pair. Getting it backwards inverts a conclusion about whether
`$STANDARD_INFORMATION` access times can be trusted.

**`DefenderExclusions`** - paths, extensions and processes Defender is told to ignore. An exclusion
naming an attacker-chosen directory is a strong signal; so is one naming a forensic tool.

**`FirewallRules`** carries both firewall rules and PortProxy entries under `rule_type`. The registry
value is pipe-delimited (`v2.33|Action=Allow|Dir=In|...`) and is split into columns. PortProxy rows
are listener-to-target forwards - a common pivot mechanism.

**`NetworkShares`** holds only **explicitly created** shares. The admin shares `C$`, `ADMIN$` and
`IPC$` are implicit and never appear here, so an empty table does not mean `net share` would be empty.

**`ConnectedDevices`** merges portable devices, Bluetooth pairings, SCSI devices and printers under
`device_type`. Bluetooth key names are MAC addresses and the friendly name is a `REG_BINARY` string.

**`MountPoints2`** is per-user: `##server#share` entries prove that user mounted that remote share.

**`RDPClientMRU`** is **outbound** RDP - servers this user connected TO, with the username hint.

**`OfficeDocuments`** merges File MRU and TrustRecords under `kind`. A TrustRecord is where the user
clicked "Enable Content" on a document - the usual macro-execution step.

**`FeatureUsage`**, **`CompatibilityAssistant`** and **`RecentApps`** are per-user program execution.
A value name in the Compatibility Assistant store is the full path of a program that ran.

**`ApplicationArtifacts`** collects remote-access and archive tool traces (PuTTY sessions and known
hosts, WinSCP, WinRAR/7-Zip history, Sysinternals EULA acceptance) under `application`.

**OS version caveat.** `ComputerNameInfo` carries the version from
`SOFTWARE\Microsoft\Windows NT\CurrentVersion`. `ProductName` there still reads "Windows 10" on
Windows 11 - Microsoft froze it. The build number is the truth: 22000+ is Windows 11.

## Timestamp Interpretation
**WARNING**: The `timestamp` column represents when Crow-eye parsed the registry, NOT when keys were modified.
Use `last_write_time` for forensic timeline analysis.

## Common Queries
- Find persistence mechanisms in Run keys
- Identify recently accessed files via RecentDocs
- Enumerate USB devices
- Check for suspicious services

## SQL Query Templates

Per artifact table, not against a generic one:

- **Persistence, every autostart location:**
  ```sql
  SELECT location, program_name, command, user_name FROM AutoStartPrograms ORDER BY location;
  ```
- **Persistence under a service account** - rows the parser labels rather than resolves, so they are
  never mistaken for a person:
  ```sql
  SELECT * FROM AutoStartPrograms WHERE location LIKE '%(LocalSystem)%'
     OR location LIKE '%(LocalService)%' OR location LIKE '%(NetworkService)%'
     OR location LIKE '%(.DEFAULT profile)%';
  ```
- **Executed applications:**
  ```sql
  SELECT program_path, run_count, last_execution, user_sid FROM UserAssist
  WHERE last_execution != '' ORDER BY last_execution DESC;
  ```
- **Recently opened files** - `access_date` is empty by design; the key's time is `key_last_write`:
  ```sql
  SELECT subkey, name, row_data, key_last_write, user_name FROM RecentDocs
  ORDER BY key_last_write DESC;
  ```
- **Folder access history:**
  ```sql
  SELECT file_name, modified_date, accessed_date, user_name FROM Shellbags
  WHERE file_name != '' ORDER BY modified_date DESC;
  ```
- **Is this parse stale?** Always worth asking of an offline case:
  ```sql
  SELECT hive_name, was_dirty, replayed, entries_applied, reason FROM registry_hive_state;
  ```

## Live vs offline parsing

Crow-Eye parses the registry two ways - `Regclaw.py` on a running machine, `offline_RegClaw.py` on
collected hives - into the same tables. They agree on 102 of 107 tables. The differences that remain
are documented in full in `docs/live-vs-offline.md`; the ones that change how an answer should be
worded:

- **`hivelist` and `active_computer_name` are live-only.** Windows builds them in memory at boot, so
  a hive file cannot contain them. Their absence from an offline case is not a gap.
- **A live parse sees only users who are logged on.** `HKEY_USERS` holds a hive only while its owner
  is logged in, so a user who logged off is invisible to a live parse while an offline parse reads
  every collected `NTUSER.DAT`. If a live case is missing a user, that user was not logged on.
- **An offline hive may be stale.** Windows keeps outstanding changes in `.LOG1`/`.LOG2`; Crow-Eye
  replays them into a temporary copy before parsing and records the outcome in `registry_hive_state`.
  Check that table before building a timeline from an offline parse.
- **Timing drift is not a defect.** Execution times, DHCP lease blobs, installed-software versions
  and drive letters all move between an image and a later live parse - and a package upgrade means
  the *image* can hold rows the live machine no longer has.
