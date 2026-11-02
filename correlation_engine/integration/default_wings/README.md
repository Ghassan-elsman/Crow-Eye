# Default Wings

This directory contains pre-configured correlation Wings that provide immediate value for forensic analysis.

## Categories: one engine per Wing

Every Wing has a `wing_category` - `time`, `identity` or `behaviour` - and each category runs on
exactly one engine (`correlation_engine/engine/engine_registry.py`). An engine skips a Wing of
another category, records a SKIPPED row with the reason, and writes the same line to the case log.

- The five Wings that were built with absence / sequence / threshold rules (Anti-Forensics, Brute
  Force & Spray, Execution Without Trace, Lateral Movement, Ransomware Mass-Encryption) are
  **Identity Wings**. Four of their rules could never fire there, because each spans many
  identities, and moved to Behaviour Wings (below); each Identity Wing lists them under
  `moved_rules` with the file that replaces them.
- The six match-only Wings ship twice: `<Name>.json` is the Identity copy (same `wing_id` as
  before, name suffixed "(Identity)") and `<Name>_Time.json` the Time copy (`wing_id` + `_time`,
  name suffixed "(Time)"). Their rules are identical.
- A case copy of a shipped Wing saved before categories existed takes the shipped category by
  `wing_id`. A user Wing with no category is listed under "Needs a category" and does not run
  until the Wing Creator gives it one.

## Behaviour Wings (run by the Behavioural engine)

A Behaviour Wing (`wing_category: "behaviour"`) names no Feathers. It is a set of behaviour
steps - each a UBA rule (`uba/config/behavior_rules.json`, or an analyst-created rule) or an
activity, with optional extra conditions and a minimum count - that must all happen for ONE
person (SID), in order (`ordered: true`) or in any order, inside `within_minutes`, with an
optional `max_gap_minutes` between ordered steps. `subject` says whom it watches (everyone,
accounts, SIDs or groups; service accounts in or out) and `alert` the severity and ATT&CK tags
of a hit. The fields are defined and validated in `config/wing_config.py` (`BEHAVIOUR_FIELDS`,
`behaviour_problems`); `engine/behavioural_engine.py` runs them over the case's stored UBA
analysis (`<case>/UBA/uba_events.db`) and writes `behaviour_hits` / `behaviour_actors` /
`behaviour_runs` to `correlation_results.db`. A hit is a pointer to UBA events, which point at
artifact rows; it is cited only after those rows are re-read.

A step's `actor` is `person` (default: the person's own events), `machine` (events Windows
records with no account - a service installed by the Service Control Manager, a program known
from Prefetch, a USB device) or `any`. A person's hit always rests on at least one of their own
events. Counts use each event's `aggregate_count` (one UBA burst of 312 files counts 312); a
burst lasting longer than the time range is counted at its average rate, and the hit says so.

- **Only the user's document folders.** The burst steps (mass delete, both ransomware Wings, mass
  copy) count only events whose `details.folder` - the label UBA gives the burst's folder - is
  the Desktop, Documents, Downloads, Pictures, Videos, Music or OneDrive folder. Application
  caches (AppData), Program Files, ProgramData, Windows and the NTFS metadata area churn
  constantly and are left out. UBA's file events come from the local USN journal and never carry
  a network-share path, so shares cannot be included.
- **Machine-only hits are capped.** A hit resting only on events with no account recorded is
  shown as "(no account recorded)", never credited to a person, and its severity is at most
  `low` (UBA `notable`) whatever the Wing's alert says; the hit's note says so.
- **Every occurrence.** Each non-overlapping occurrence of a Wing for a person is its own hit,
  earliest first, up to 100 per Wing per person; a cap reached is noted on the Wing's result
  and the person's `behaviour_actors` row.

| File | Steps (UBA rule ids) | Order / range | Alert |
|---|---|---|---|
| `Log_Clearing_After_Admin_Signin_Behaviour.json` | `privileged_logon` -> `log_cleared` | in order, 60 min | critical, T1070.001 |
| `Enumeration_Runas_New_Service_Behaviour.json` | `account_enumeration` -> `explicit_credentials` -> `service_installed` (machine) | in order, 60 min | high, T1087.001 T1078 T1543.003 |
| `USB_Insert_Mass_Copy_Behaviour.json` | `usb_connected` (machine, storage drives only: `details.storage`) -> `file_copy_inferred` x20 | in order, 30 min | medium, T1025 |
| `Lateral_Movement_Behaviour.json` | `interactive_logon` -> `program_run`/`process_created` (remote-admin tool) -> `file_created` (executable in the Windows area) | in order, 60 min gaps, 180 min | critical, T1021 T1570 |
| `Ransomware_Mass_Encryption_Behaviour.json` | `file_edited`/`file_renamed` x100; plus a threshold rule: 10 renames into an encrypted-looking extension in 10 min | 5 min | critical, T1486 |
| `Ransomware_Encrypt_Then_Inhibit_Behaviour.json` | `file_edited`/`file_renamed` x50 + `program_run`/`process_created` (vssadmin, wbadmin, bcdedit, wmic, diskshadow) | any order, 10 min | critical, T1486 T1490 |
| `Mass_File_Deletion_Behaviour.json` | `file_deleted` x20 | 5 min | high, T1070.004 T1485 |
| `Collect_Then_Upload_Behaviour.json` | `file_copy_inferred` x10 (own folders) -> `browser_upload_inferred` | in order, 120 min | high, T1074.001 T1567.002 |
| `Anonymiser_And_Upload_Behaviour.json` | `browser_visit_anonymiser` + `browser_upload_inferred` | any order, 60 min | high, T1090.003 T1567.002 |
| `Risky_Download_Opened_Behaviour.json` | `browser_download_risky_source` + `browser_download_opened` (program) - both timed at the download | any order, 60 min | medium, T1204.002 T1105 |
| `Remote_Access_Tool_Download_Behaviour.json` | `browser_visit_remote_access` -> `browser_download_executable` | in order, 60 min | medium, T1219 |
| `Hacking_Resource_Download_Behaviour.json` | `browser_visit_hacking_resource` -> `browser_download_executable` | in order, 120 min | medium, T1588.002 |
| `Defender_Exclusion_And_Persistence_Behaviour.json` | `defender_exclusion` (machine) + `service_installed`/`autostart_service`/`scheduled_task_registered`/`autostart_persistence` (machine) | any order, 60 min | high, capped low (no account) - T1562.001 T1543.003 T1053.005 T1547.001 |
| `Failed_Signins_Then_Success_Behaviour.json` | `failed_logon` x5 -> `interactive_logon`/`workstation_unlock` | in order, 30 min | high, T1110.001 |
| `Share_Access_Then_Mass_Copy_Behaviour.json` | `network_share_access` -> `file_copy_inferred` x20 (own folders) | in order, 60 min | medium, T1039 |
| `Off_Hours_Signin_Then_Credential_Tool_Behaviour.json` | `interactive_logon`/`workstation_unlock` at 22:00-04:59 (`hour_local`) -> `program_run`/`process_created` (credential tool by name, any) | in order, 120 min | critical, T1003.001 T1078 |
| `Risky_Visit_Then_History_Gap_Behaviour.json` | `browser_visit_anonymiser`/`browser_visit_hacking_resource` -> `browser_history_gap` | in order, 3 days | medium, T1070 |
| `Unattributed_Log_Clear_After_Admin_Signin_Behaviour.json` | `privileged_logon` -> `log_cleared` with no account (any) | in order, 60 min | medium, T1070.001 |

**Moved from the Identity Wings** (they could not fire per identity): `lat_ordered_chain` ->
`Lateral_Movement_Behaviour.json`; `rw_mass_write_burst` -> `Ransomware_Mass_Encryption_Behaviour.json`;
`rw_encrypt_then_inhibit` -> `Ransomware_Encrypt_Then_Inhibit_Behaviour.json` (whose name always
required recovery-inhibition tooling, which the old rule never checked); `af_mass_delete` ->
`Mass_File_Deletion_Behaviour.json`.

**Gaps - behaviours with no UBA rule, so nothing is shipped for them:**

- **Credential dumping that is not a known tool name.** `Off_Hours_Signin_Then_Credential_Tool_Behaviour.json`
  (Sentinel 19.6's fourth Wing) finds the tools by program name in Prefetch / 4688, as the
  Lateral Movement Wing finds remote-admin tools. A renamed binary, or a living-off-the-land
  dump (`rundll32 comsvcs.dll,MiniDump`, Task Manager's "create dump file") is not caught: no UBA
  rule reads the command line or the dump file. An analyst-created rule can supply one.
- **Who erased the System log.** Event 104 carries the subject in its payload, but the parsed
  record keeps none, so `log_cleared` from the System log names no account and only
  `Unattributed_Log_Clear_After_Admin_Signin_Behaviour.json` (an `any` step) can use it.
- **Network sign-ins (4624 logon type 3).** `interactive_logon` covers types 2, 10 and 11 only,
  so a lateral-movement chain that begins with a network sign-in is not found.
- **Copies to a USB drive.** `file_copy_inferred` sees files arriving on this computer's disk;
  files written to the removable drive are not on this volume. `usb_connected` carries only each
  device's last connection time, and lists every USB device (mice, webcams, hubs): `details.storage`
  marks the drives (enumerated under USBSTOR, a storage driver, or a USBStorageDevices entry).

## Available Default Wings

### 1. Execution Proof Correlation

**File:** `Execution_Proof_Correlation.json`  
**Wing ID:** `default_wing_execution_001`  
**Purpose:** Scores execution likelihood by weighted corroboration across artifacts of differing forensic strength

#### What It Indicates
This Wing scores how strongly the available artifacts corroborate that a program executed on the system, weighting artifacts by their differing levels of forensic confidence.

#### Scoring Tiers

**Tier 1: Primary Indicators (Weight: 0.65)**
- **Prefetch** (0.40) - Strongest execution indicator
- **ShimCache** (0.25) - Presence / compatibility indicator; does not by itself prove execution

**Tier 2: Presence / Inventory Indicators (Weight: 0.45)**
- **AmCache - InventoryApplication** (0.15)
- **AmCache - InventoryApplicationFile** (0.15)
- **AmCache - InventoryApplicationShortcut** (0.15)

**Tier 3: User-Triggered Execution Traces (Weight: 0.37)**
- **LNK Files** (0.10)
- **Automatic Jumplists** (0.10)
- **Custom Jumplists** (0.10)
- **ShellBags** (0.07) - User folder navigation evidence

**Tier 4: Runtime + Behavior Correlation (Weight: 0.28)**
- **SRUM Application Usage** (0.10)
- **SRUM Network Data Usage** (0.08) - Network activity evidence
- **MFT/USN Journal** (0.10) - File system evidence
- **System Logs** (0.05) - System event logs
- **Application Logs** (0.05) - Application event logs

#### Score Interpretation

| Score Range | Interpretation | Meaning |
|-------------|----------------|---------|
| ≥ 0.70 | **Strongly Corroborated Execution** | High confidence - multiple strong artifacts corroborate |
| 0.40 - 0.69 | **Likely Execution** | Moderate confidence - some strong artifacts present |
| 0.20 - 0.39 | **Weak / Partial** | Low confidence - only weak artifacts present |
| < 0.20 | **Insufficient Evidence** | Not enough corroboration to assess |

#### Configuration
- **Time Window:** 180 minutes (3 hours)
- **Minimum Matches:** 1
- **Anchor Priority:** Prefetch → ShimCache → AmCache → LNK → Jumplists → SRUM → MFT → Logs → Registry

#### Feathers Included
1. **Prefetch_CrowEyeFeather** - Primary execution indicator
2. **ShimCache_CrowEyeFeather** - Application compatibility cache
3. **InventoryApplication_CrowEyeFeather** - AmCache application inventory
4. **InventoryApplicationFile_CrowEyeFeather** - AmCache file inventory
5. **InventoryApplicationShortcut_CrowEyeFeather** - AmCache shortcut inventory
6. **LNK_CrowEyeFeather** - Windows shortcut files
7. **AutomaticJumplist_CrowEyeFeather** - Automatic destination lists
8. **CustomJumplist_CrowEyeFeather** - Custom destination lists
9. **SRUM_ApplicationUsage_CrowEyeFeather** - System Resource Usage Monitor
10. **MFT_USN_Correlated_CrowEyeFeather** - Master File Table and USN Journal
11. **SystemLogs_CrowEyeFeather** - Windows system event logs
12. **SRUM_NetworkDataUsage_CrowEyeFeather** - Network usage data
13. **ApplicationLogs_CrowEyeFeather** - Application event logs
14. **ShellBags_CrowEyeFeather** - User folder navigation history

---

### 2. User Activity Correlation

**File:** `User_Activity_Correlation.json`  
**Wing ID:** `default_wing_activity_001`  
**Purpose:** Proves user activity using weighted scoring based on user interaction evidence strength

#### What It Proves
This Wing establishes that a user actively interacted with the system by correlating user-generated artifacts that indicate explicit interaction.

#### Scoring Tiers

**Tier 1: Explicit User Interaction (Weight: 0.90)**
- **UserAssist** (0.30) - Direct evidence of GUI program execution
- **RecentDocs** (0.20) - Recent document access
- **OpenSaveMRU** (0.20) - File open/save dialogs
- **LastSaveMRU** (0.20) - Last saved file locations

**Tier 2: Navigation & Exploration (Weight: 0.25)**
- **ShellBags** (0.15) - Folder navigation and window positions
- **TypedPaths** (0.10) - Manually typed paths in Explorer

**Tier 3: Temporal System Confirmation (Weight: 0.05)**
- **Security Logs** (0.05) - Login/logout events for temporal context

#### Score Interpretation

| Score Range | Interpretation | Meaning |
|-------------|----------------|---------|
| ≥ 0.60 | **Confirmed User Activity** | High confidence - multiple explicit interaction artifacts |
| 0.35 - 0.59 | **Likely User Activity** | Moderate confidence - some interaction artifacts present |
| < 0.35 | **Insufficient Evidence** | Not enough evidence to confirm user activity |

#### Configuration
- **Time Window:** 5 minutes
- **Minimum Matches:** 1
- **Anchor Priority:** Registry → Logs

#### Semantic Mappings
This Wing includes pre-configured semantic mappings for Security Log Event IDs:
- 4624 → "User Login"
- 4634 → "User Logoff"
- 4647 → "User Logoff"
- 4800 → "Session Locked"
- 4801 → "Session Unlocked"
- 4648 → "Account Switch"

---

## Usage

### Loading Default Wings

Default Wings are automatically loaded when:
1. The application starts (copied to user config directory)
2. A new case is opened (copied to case Wings directory)
3. The Correlation Engine tab is accessed

### Customizing Default Wings

You can customize default Wings by:
1. Copying them to your case's `Correlation/wings/` directory
2. Editing the JSON file to adjust weights, thresholds, or Feathers
3. Saving with a new name to preserve the original

### Creating New Wings Based on Defaults

Use default Wings as templates:
1. Copy a default Wing JSON file
2. Rename it (change `wing_id` and `wing_name`)
3. Adjust Feathers, weights, and scoring thresholds
4. Save to your case's Wings directory

---

## Technical Details

### Weighted Scoring Algorithm

The weighted scoring system calculates match confidence as:

```
Total Score = Σ (Weight of Matched Feather)
```

Each Feather contributes its weight only if it has a matching record within the time window.

### Score Breakdown

When viewing results, you'll see:
- **Overall Score:** Total weighted score (0.0 - 1.0+)
- **Interpretation:** Human-readable confidence level
- **Breakdown:** Per-Feather contribution showing:
  - Matched status (✓ or ✗)
  - Weight assigned
  - Contribution to total score
  - Tier and tier name

### Time Window

The 5-minute time window means:
- All correlated records must occur within 5 minutes of the anchor record
- The anchor is selected based on the `anchor_priority` list
- Earlier artifacts in the priority list are preferred as anchors

---

## Best Practices

### When to Use Execution Proof Correlation

Use this Wing when you need to:
- Establish that a specific program was executed
- Determine execution timeline
- Correlate execution across multiple artifact types
- Build evidence for malware execution
- Investigate program execution in intrusion cases

### When to Use User Activity Correlation

Use this Wing when you need to:
- Prove user interaction (vs. automated execution)
- Establish user session activity
- Investigate data theft or insider threats
- Correlate user actions across artifacts
- Determine if activity was user-initiated

### Combining Wings

For comprehensive analysis:
1. Run both Wings on the same dataset
2. Compare results to distinguish user-initiated vs. automated execution
3. Use Execution Proof for "what ran"
4. Use User Activity for "who did it"

---

## Maintenance

### Updating Default Wings

To update default Wings:
1. Edit the JSON files in this directory
2. Increment the `version` field
3. Update `last_modified` timestamp
4. Test with sample data
5. Document changes in this README

### Adding New Default Wings

To add a new default Wing:
1. Create a new JSON file in this directory
2. Follow the structure of existing Wings
3. Add the filename to `DEFAULT_WING_FILES` in `default_wings_loader.py`
4. Document it in this README
5. Test thoroughly before committing

---

## Version History

### Version 1.0 (2024-12-23)
- Initial release
- Execution Proof Correlation Wing
- User Activity Correlation Wing
- Weighted scoring system
- Semantic mappings for Security Logs

---

## Support

For questions or issues with default Wings:
1. Check the Correlation Engine documentation
2. Review the Wing configuration format
3. Test with sample data
4. Consult the Crow-Eye team

---

**Last Updated:** December 23, 2024  
**Maintained By:** Crow-Eye Team
