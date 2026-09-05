"""Which databases and which time columns the timeline plots.

One copy, deliberately. This lived twice - once in `timeline_data_manager.py`
and once in `timestamp_indexer.py` - and the two drifted: the manager filed
ShellBags under `Shellbags` while the indexer used `ShellBag`, the manager had
DAM and USB storage that the indexer did not, and the indexer carried
`UserAssist.focus_time`, which is a DURATION and not a time at all.

Two maps, and BOTH are required for an artifact to appear:

  * `ARTIFACT_DB_MAPPING` decides what exists. `_detect_available_artifacts()`
    iterates this one, so an artifact absent here is never considered no matter
    what times are defined for it.
  * `TIMESTAMP_MAPPINGS` decides what is plotted.

Six artifact types once had times and no database entry - Shellbags, Amcache,
Shimcache, RecycleBin, DAM, USB storage - so 804 ShellBags rows with three date
columns each appeared nowhere, and the only complaint was one debug line saying
"No timestamp mappings defined for ShellBag".

## Exact times and bounded times

A mapping entry is `(table, column, kind)` with two optional fields:

    (table, column, kind, description)
    (table, column, kind, description, basis_column)

`is_key_time(entry)` says whether the time is the containing KEY's write time
rather than the record's own. A key's write time is an upper bound on every
value under it - writing any value updates the whole key - so a hundred rows
under one key all carry the same time, and it is wrong for at least
ninety-nine of them. The timeline draws these as hollow markers behind a
toggle that starts off; `<= T` is what they mean, and the shape says so in a
screenshot where a tooltip cannot.

`basis_column` is a separate question: it names the column holding the
parser's own `time_basis` string, which only the `last_written` tables carry.
It is NOT the marker for a key time, and using it as one called every MRU
table exact.

`key_last_write` is a key time too, not only `last_written`. The MRU tables are
the clearest case: 246 OpenSaveMRU rows share one key write time, which dates
the newest entry in the list and nothing else.
"""

# --------------------------------------------------------------------------
#  What exists
# --------------------------------------------------------------------------

ARTIFACT_DB_MAPPING = {
    "Prefetch": "prefetch_data.db",
    "LNK": "LnkDB.db",
    "Registry": "registry_data.db",
    "BAM": "registry_data.db",
    "DAM": "registry_data.db",
    # One spelling. `ShellBag` here against `Shellbags` in the time map is what
    # orphaned both halves of this artifact.
    "Shellbags": "registry_data.db",
    "USBStorageDevices": "registry_data.db",
    "ScheduledTasks": "registry_data.db",
    "RegistryChanges": "registry_data.db",
    "Amcache": "amcache.db",
    "Shimcache": "shimcache.db",
    "RecycleBin": "recyclebin_analysis.db",
    "SRUM": "srum_data.db",
    "USN": "USN_journal.db",
    "MFT": "mft_claw_analysis.db",
    # Windows Event Logs. Absent from both maps until now, while the bridge read
    # eighteen hard-coded EventIDs out of them for the session band and nothing
    # else - 41,109 of 43,802 records on an ordinary machine, including every
    # service install, every process creation and every log clear, could not be
    # seen on the timeline at all.
    "Logs": "Log_Claw.db",
    # The MFT/USN correlator's output. The bridge has always queried this file;
    # it was simply never named here, so nothing that reasons from the map knew
    # it existed.
    "MftUsn": "mft_usn_correlated_analysis.db",
}

ARTIFACT_DB_ALTERNATIVES = {
    "MFT": ["MFT_data.db"],
    "Shimcache": ["shimcache_data.db"],
    "RecycleBin": ["recyclebin.db"],
    "USN": ["usn_journal.db", "USN_Journal.db"],
}

# --------------------------------------------------------------------------
#  What is plotted
# --------------------------------------------------------------------------

# The registry tables whose only time is the containing KEY's write time.
# Split out so the reason is stated once instead of repeated thirty times.
_KEY_TIME_TABLES = [
    # (table, column, kind, basis column)
    #
    # Only the `last_written` tables carry a `time_basis` column. The MRU
    # tables, the carved keys and the SECURITY-hive tables do not - their
    # time is a key write time unconditionally, so there is nothing to
    # record per row. Naming a `time_basis` column they do not have would
    # make every one of those queries raise.
    ("AutoStartPrograms", "last_written", "modified", "time_basis"),
    ("BAM", "last_written", "modified", "time_basis"),
    ("CompatibilityAssistant", "last_written", "modified", "time_basis"),
    ("ConnectedDevices", "last_written", "modified", "time_basis"),
    ("DefenderExclusions", "last_written", "modified", "time_basis"),
    ("FeatureUsage", "last_written", "modified", "time_basis"),
    ("FirewallRules", "last_written", "modified", "time_basis"),
    ("MountPoints2", "last_written", "modified", "time_basis"),
    ("NetworkProfiles", "last_written", "modified", "time_basis"),
    ("OfficeDocuments", "last_written", "modified", "time_basis"),
    ("SecurityPosture", "last_written", "modified", "time_basis"),
    ("app_paths", "last_written", "modified", "time_basis"),
    ("app_permissions", "last_written", "modified", "time_basis"),
    ("cid_size_mru", "last_written", "modified", "time_basis"),
    ("explorer_advanced", "last_written", "modified", "time_basis"),
    ("file_exts", "last_written", "modified", "time_basis"),
    ("machine_guid", "last_written", "modified", "time_basis"),
    ("network_cards", "last_written", "modified", "time_basis"),
    ("os_install_history", "last_written", "modified", "time_basis"),
    ("shared_dlls", "last_written", "modified", "time_basis"),
    ("startup_approved", "last_written", "modified", "time_basis"),
    ("system_configuration", "last_written", "modified", "time_basis"),
    ("volume_info_cache", "last_written", "modified", "time_basis"),
    ("windows_script_host", "last_written", "modified", "time_basis"),
    ("winevt_channels", "last_written", "modified", "time_basis"),
    ("zone_map", "last_written", "modified", "time_basis"),
    # The SECURITY-hive tables spell it `last_write`.
    ("audit_policy", "last_write", "modified", ""),
    ("local_groups", "last_write", "modified", ""),
    ("lsa_policy", "last_write", "modified", ""),
    ("lsa_secrets", "last_write", "modified", ""),
    # MRU lists: `key_last_write` dates the newest entry in the list, and every
    # row in that list carries it. `access_date` is empty by design here - the
    # parser refuses to assign the key's time to whichever entry looks newest,
    # and pointing the timeline at it plotted nothing from 246 OpenSaveMRU rows
    # and 20 LastSaveMRU rows.
    ("OpenSaveMRU", "key_last_write", "modified", ""),
    ("LastSaveMRU", "key_last_write", "modified", ""),
    ("RunMRU", "key_last_write", "modified", ""),
    ("WordWheelQuery", "key_last_write", "modified", ""),
    ("TypedPaths", "key_last_write", "modified", ""),
    ("RecentDocs", "key_last_write", "modified", ""),
    # Keys recovered by carving. Deleted keys are evidence, so they are here
    # rather than excluded with the structural tables below.
    ("registry_carved_keys", "key_last_write", "modified", ""),
]

# Deliberately NOT plotted: `registry_class_names` (1,584 rows) and
# `registry_key_times` (615) are the hive-structure index the last_written
# back-fill reads, not events. Every time in them already reaches the timeline
# through the table it dated, so plotting them draws each of those a second
# time under a name that means nothing to an examiner.

_REGISTRY_RECORD_TIMES = [
    # Times a record carries in its own right.
    ("UserAssist", "last_execution", "executed", "Last run recorded by UserAssist"),
    ("InstalledSoftware", "install_date", "installed", "Software install date"),
    ("ComputerNameInfo", "installation_date", "installed", "Windows install date"),
    ("ShutdownInfo", "shutdown_time", "executed", "Last shutdown"),
    # NOT `scheduled_install_time`: despite the name that column holds
    # `ScheduledInstallTime`, the HOUR OF DAY the AU policy installs at, as an
    # INTEGER 0-23. It was mapped as an event time, which put update policy on
    # the timeline at the first second of 1970 whenever it parsed at all.
    ("WindowsUpdateInfo", "last_install_time", "installed", "Last update installed"),
    ("WindowsUpdateInfo", "last_check_time", "accessed", "Last update check"),
    ("Network_list", "connection_date", "accessed", "Network last connected"),
    ("NetworkProfiles", "date_created", "created", "Network profile created"),
    ("NetworkProfiles", "date_last_connected", "accessed", "Network last connected"),
    # Recovered from the transaction log: this IS the moment the value changed.
    ("registry_value_changes", "changed_at", "modified",
     "Value change recovered from the transaction log"),
    # SAM. When an account last signed in and when its password was last set
    # are among the first things asked in an intrusion, and neither was on the
    # timeline. They come from `user_identity.py`, not Regclaw, which is why a
    # check reading one file per family never noticed.
    ("UserAccounts", "last_logon", "accessed", "Account last logon"),
    ("UserAccounts", "password_last_set", "modified", "Password last set"),
    # Per-app capability use - microphone, camera, location. The record's own
    # times, beside the same table's `last_written`, which is its key's.
    ("app_permissions", "last_used_start", "executed",
     "App started using this capability"),
    ("app_permissions", "last_used_stop", "executed",
     "App stopped using this capability"),
]

TIMESTAMP_MAPPINGS = {
    "Prefetch": [
        ("prefetch_data", "last_executed", "executed", "Last execution time"),
        ("prefetch_data", "created_on", "created", "File creation time"),
        ("prefetch_data", "modified_on", "modified", "File modification time"),
        ("prefetch_data", "accessed_on", "accessed", "File access time"),
    ],
    "LNK": [
        ("LNK_Files", "Time_Creation", "created"),
        ("LNK_Files", "Time_Modification", "modified"),
        ("LNK_Files", "Time_Access", "accessed"),
        ("Automatic_JumpLists", "Time_Creation", "created"),
        ("Automatic_JumpLists", "Time_Modification", "modified"),
        ("Automatic_JumpLists", "Time_Access", "accessed"),
        ("Custom_JumpLists", "Time_Creation", "created"),
        ("Custom_JumpLists", "Time_Modification", "modified"),
        ("Custom_JumpLists", "Time_Access", "accessed"),
    ],
    # Registry = record times, then every key time with its basis column.
    "Registry": _REGISTRY_RECORD_TIMES + [
        (table, column, kind, "Registry key last-write time", basis)
        for table, column, kind, basis in _KEY_TIME_TABLES
    ],
    "BAM": [
        ("BAM", "last_execution", "executed"),
    ],
    "DAM": [
        ("DAM", "last_execution", "executed"),
    ],
    "ScheduledTasks": [
        # The scheduler's own per-task times, not key times.
        ("ScheduledTasks", "task_registered", "created", "Task created"),
        ("ScheduledTasks", "last_run", "executed", "Task last ran"),
        ("ScheduledTasks", "last_completed", "executed", "Task last finished"),
    ],
    "RegistryChanges": [
        ("registry_value_changes", "changed_at", "modified",
         "Value change recovered from the transaction log"),
    ],
    "USBStorageDevices": [
        # Device property FILETIMEs, read from the acquired hive. Empty on every
        # live case until the USBSTOR block stopped raising NameError.
        ("USBStorageDevices", "first_connected", "installed"),
        ("USBStorageDevices", "last_connected", "accessed"),
        ("USBStorageDevices", "last_removed", "deleted"),
        ("USBDevices", "last_connected", "accessed"),
    ],
    "Amcache": [
        # The `_utc` columns, NOT the raw ones. AmCache's own values are
        # MM/DD/YYYY text - which SQLite's `datetime()` reads as NULL, so every
        # AmCache query on this timeline returned zero rows for as long as they
        # existed - and `link_date` additionally holds version strings on some
        # rows ("6.4.7.0", "0.5") because the hive itself puts them there.
        # `amcacheparser` already resolves both, writing a normalised column
        # beside each and refusing to normalise what is not a date; these are
        # those columns.
        ("InventoryApplication", "install_date_utc", "installed",
         "Application install date"),
        ("InventoryApplication", "msi_install_date_utc", "installed",
         "MSI install date"),
        ("InventoryApplicationFile", "link_date_utc", "linked",
         "PE link date"),
        ("InventoryDriverBinary", "driver_last_write_time_utc", "modified",
         "Driver last write time"),
        ("InventoryDriverBinary", "driver_time_stamp_utc", "created",
         "Driver PE timestamp"),
        # Device installation. When a driver or a piece of hardware first
        # appeared on this machine is a question asked in most USB and
        # rogue-device investigations, and none of it was mapped.
        ("InventoryDevicePnp", "install_date_utc", "installed",
         "Device installed"),
        ("InventoryDevicePnp", "first_install_date_utc", "installed",
         "Device first installed"),
        ("InventoryDevicePnp", "driver_ver_date_utc", "created",
         "Driver version date"),
        ("InventoryDriverPackage", "date_utc", "created", "Driver package date"),
    ] + [
        # AmCache is a registry hive, so every one of its tables carries the
        # containing key's write time - an upper bound on that entry, in the
        # same sense as `last_written` in the registry proper. 5,212 of them on
        # InventoryApplicationFile alone. Bounded, hidden by default.
        (table, "key_last_write", "modified", "AmCache key last-write time")
        for table in (
            "InventoryApplication", "InventoryApplicationFile",
            "InventoryApplicationShortcut", "InventoryDriverBinary",
            "InventoryDriverPackage", "InventoryDevicePnp",
            "InventoryDeviceContainer", "InventoryDeviceInterface",
            "InventoryDeviceMediaClass", "InventoryDeviceUsbHubClass",
            "InventoryMiscellaneous", "InventoryMiscellaneousUser",
            "InventoryMiscellaneousUupInfo",
            "InventoryMiscellaneousMemorySlotArrayInfo",
            "DeviceCensus", "Mare", "MareBackupApps",
        )
    ],
    "Shimcache": [
        ("shimcache_entries", "last_modified", "modified", "Shimcache last modified time"),
    ],
    "RecycleBin": [
        ("recycle_bin_entries", "deletion_time", "deleted", "File deletion time"),
    ],
    "Shellbags": [
        # The shell item's own MAC times - a record time, not a key time.
        ("Shellbags", "created_date", "created"),
        ("Shellbags", "modified_date", "modified"),
        ("Shellbags", "accessed_date", "accessed"),
    ],
    "SRUM": [
        ("srum_application_usage", "timestamp", "various"),
        ("srum_network_connectivity", "timestamp", "various"),
        ("srum_network_data_usage", "timestamp", "various"),
        ("srum_energy_usage", "timestamp", "various"),
        # The battery state transition's own time, as opposed to the SRUM row's.
        # `SRUM_Claw` writes it only where the record carries one, so it is
        # empty on every row of a desktop and populated on a laptop - which is
        # why `test_timeline_bridge_queries_run` names it as a known-empty
        # column instead of reporting it as a mis-keyed mapping.
        ("srum_energy_usage", "event_timestamp", "various",
         "Battery state transition"),
        ("srum_app_timeline", "timestamp", "various"),
    ],
    "USN": [
        ("journal_events", "timestamp", "various"),
    ],
    "MFT": [
        # $STANDARD_INFORMATION, promoted onto the record by the parser.
        ("mft_records", "created_time", "created", "$SI created"),
        ("mft_records", "modified_time", "modified", "$SI modified"),
        ("mft_records", "accessed_time", "accessed", "$SI accessed"),
        ("mft_records", "mft_modified_time", "mft_modified", "$SI MFT entry changed"),
        # $FILE_NAME - a DIFFERENT set of times, and the timestomping tell.
        # $SI is what most tampering rewrites; $FN is written by the kernel at
        # creation and rarely touched, so the two disagreeing is the signal.
        # They differ on 155,239 of 199,533 records here, which is normal - the
        # point is that the examiner can only compare them if both are plotted.
        #
        # `mft_standard_info` is deliberately absent: it holds the same four
        # times as `mft_records`, identical on all 199,533 rows, so mapping it
        # would draw every MFT marker twice.
        ("mft_file_names", "created", "created", "$FN created"),
        ("mft_file_names", "modified", "modified", "$FN modified"),
        ("mft_file_names", "accessed", "accessed", "$FN accessed"),
        ("mft_file_names", "mft_modified", "mft_modified", "$FN MFT entry changed"),
        # Renames recovered by the correlator - 133,614 of them here, and a
        # rename is exactly the kind of thing a timeline is asked about.
        ("filename_changes", "change_timestamp", "modified", "File renamed"),
    ],
    "MftUsn": [
        # Ten time columns; the bridge used three. $SI and $FN side by side per
        # record is the whole reason this table exists.
        ("mft_usn_correlated", "si_creation_time", "created", "$SI created"),
        ("mft_usn_correlated", "si_modification_time", "modified", "$SI modified"),
        ("mft_usn_correlated", "si_access_time", "accessed", "$SI accessed"),
        ("mft_usn_correlated", "si_mft_entry_change_time", "mft_modified",
         "$SI MFT entry changed"),
        ("mft_usn_correlated", "fn_creation_time", "created", "$FN created"),
        ("mft_usn_correlated", "fn_modification_time", "modified", "$FN modified"),
        ("mft_usn_correlated", "fn_access_time", "accessed", "$FN accessed"),
        ("mft_usn_correlated", "fn_mft_entry_change_time", "mft_modified",
         "$FN MFT entry changed"),
        ("mft_usn_correlated", "usn_timestamp", "various", "USN journal entry"),
    ],
    "Logs": [
        ("SystemLogs", "EventTimestampUTC", "various", "System event log"),
        ("SecurityLogs", "EventTimestampUTC", "various", "Security event log"),
        ("ApplicationLogs", "EventTimestampUTC", "various", "Application event log"),
    ],
}


# --------------------------------------------------------------------------
#  Which event log records are drawn by default
# --------------------------------------------------------------------------

# The event log is the largest time source in most cases and the least usable
# raw: 43,802 records here, of which one ID - 5379, a credential-manager read -
# is 22,012 on its own. Drawing all of it by default buries everything that
# matters, so the timeline draws THESE by default and puts the rest behind a
# pill, the same shape as the bounded key times.
#
# `{event_id: (log table, what it means in words)}`. The label is what the
# marker reads, because `7045` on a timeline tells an examiner nothing and
# "Service installed" tells them everything.
#
# Left OUT deliberately, though they are present in quantity: 4672 (special
# privileges assigned - fires on every administrative logon, 2,017 rows here),
# 4798/4799 (a process enumerated a user's group membership, 4,763 rows),
# 5379 (credential read, 22,012), 7036 (service entered running/stopped state).
# Each is normal Windows behaviour at a volume that would drown the lane. They
# are still reachable with the pill on.
SIGNIFICANT_EVENT_IDS = {
    # --- Security: logon and credentials --------------------------------
    4624: ("SecurityLogs", "Logon"),
    4625: ("SecurityLogs", "Failed logon"),
    4634: ("SecurityLogs", "Logoff"),
    4647: ("SecurityLogs", "User-initiated logoff"),
    4648: ("SecurityLogs", "Logon with explicit credentials"),
    4768: ("SecurityLogs", "Kerberos TGT requested"),
    4769: ("SecurityLogs", "Kerberos service ticket requested"),
    4771: ("SecurityLogs", "Kerberos pre-auth failed"),
    4776: ("SecurityLogs", "NTLM credential validation"),
    4778: ("SecurityLogs", "Session reconnected (RDP)"),
    4779: ("SecurityLogs", "Session disconnected (RDP)"),
    4800: ("SecurityLogs", "Workstation locked"),
    4801: ("SecurityLogs", "Workstation unlocked"),
    # --- Security: execution and persistence ----------------------------
    4688: ("SecurityLogs", "Process created"),
    4689: ("SecurityLogs", "Process exited"),
    4697: ("SecurityLogs", "Service installed"),
    4698: ("SecurityLogs", "Scheduled task created"),
    4699: ("SecurityLogs", "Scheduled task deleted"),
    4700: ("SecurityLogs", "Scheduled task enabled"),
    4701: ("SecurityLogs", "Scheduled task disabled"),
    4702: ("SecurityLogs", "Scheduled task updated"),
    # --- Security: accounts ---------------------------------------------
    4720: ("SecurityLogs", "User account created"),
    4722: ("SecurityLogs", "User account enabled"),
    4723: ("SecurityLogs", "Password change attempted"),
    4724: ("SecurityLogs", "Password reset"),
    4725: ("SecurityLogs", "User account disabled"),
    4726: ("SecurityLogs", "User account deleted"),
    4728: ("SecurityLogs", "Member added to a global group"),
    4732: ("SecurityLogs", "Member added to a local group"),
    4738: ("SecurityLogs", "User account changed"),
    4740: ("SecurityLogs", "User account locked out"),
    4756: ("SecurityLogs", "Member added to a universal group"),
    # --- Security: anti-forensics and policy ----------------------------
    1102: ("SecurityLogs", "Security log cleared"),
    4616: ("SecurityLogs", "System time changed"),
    4657: ("SecurityLogs", "Registry value modified"),
    4719: ("SecurityLogs", "Audit policy changed"),
    4964: ("SecurityLogs", "Special group assigned at logon"),
    6416: ("SecurityLogs", "External device recognised"),
    # --- Security: shares ------------------------------------------------
    5140: ("SecurityLogs", "Network share accessed"),
    5142: ("SecurityLogs", "Network share added"),
    5145: ("SecurityLogs", "Network share access checked"),
    # --- System: services and drivers ------------------------------------
    7045: ("SystemLogs", "Service installed"),
    7040: ("SystemLogs", "Service start type changed"),
    7034: ("SystemLogs", "Service crashed"),
    7000: ("SystemLogs", "Service failed to start"),
    7001: ("SystemLogs", "Service dependency failed"),
    219: ("SystemLogs", "Driver loaded"),
    # --- System: power and integrity -------------------------------------
    104: ("SystemLogs", "Event log cleared"),
    41: ("SystemLogs", "Unexpected shutdown"),
    6008: ("SystemLogs", "Unexpected shutdown"),
    6005: ("SystemLogs", "Event log service started"),
    6006: ("SystemLogs", "Event log service stopped"),
    6013: ("SystemLogs", "System uptime reported"),
    1074: ("SystemLogs", "Shutdown initiated"),
    1: ("SystemLogs", "System resumed"),
    12: ("SystemLogs", "System started"),
    13: ("SystemLogs", "System shut down"),
    # --- Application: crashes and installs -------------------------------
    1000: ("ApplicationLogs", "Application crash"),
    1001: ("ApplicationLogs", "Application error report"),
    1002: ("ApplicationLogs", "Application hang"),
    1026: ("ApplicationLogs", ".NET runtime error"),
    11707: ("ApplicationLogs", "MSI install completed"),
    11724: ("ApplicationLogs", "MSI uninstall completed"),
    # --- PowerShell -------------------------------------------------------
    4103: ("ApplicationLogs", "PowerShell pipeline executed"),
    4104: ("ApplicationLogs", "PowerShell script block logged"),
}

EVENT_LOG_TABLES = ("SystemLogs", "SecurityLogs", "ApplicationLogs")


# Keyed on (table, column), not on the table. `NetworkProfiles` carries both:
# `date_created` and `date_last_connected` are the profile's own record times,
# while `last_written` is the containing key's - and marking the whole table
# bounded would have drawn its two exact times hollow.
#
# `key_last_write` is added by name as well, because AmCache is a registry hive
# too: every one of its tables carries the containing key's write time, and it
# is an upper bound there for exactly the same reason.
KEY_TIME_COLUMNS = frozenset(
    [(t, c) for t, c, _k, _b in _KEY_TIME_TABLES]
    + [(e[0], e[1]) for entries in TIMESTAMP_MAPPINGS.values() for e in entries
       if e[1] == "key_last_write"])


def basis_column(entry):
    """The `time_basis` column for a mapping entry, or "" if there is none.

    Empty is normal: only the `last_written` tables record a per-row basis.
    The MRU tables, the carved keys and the SECURITY-hive tables have no such
    column, and naming one they do not have makes the query raise.
    """
    return entry[4] if len(entry) > 4 else ""


def is_key_time(entry):
    """Is this entry a KEY write time - an upper bound, not a moment?

    Answered from the mapping list, not from `basis_column`. Keying it on the
    basis column was wrong in both directions: it called the six MRU tables and
    the carved keys exact, because none of those tables has a `time_basis`
    column to name, and it would call a record time bounded the moment someone
    added one to its table.
    """
    return (entry[0], entry[1]) in KEY_TIME_COLUMNS
